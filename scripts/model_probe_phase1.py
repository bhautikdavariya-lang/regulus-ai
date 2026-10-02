"""Phase 2 + Phase 1 of the capacity-vs-implementation diagnostic: runtime truth, then a sanity suite.

    python scripts/model_probe_phase1.py [--out artifacts/diagnostics/model_probe]

Loads the configured model exactly as production loads it (regulus.model.loader via load_qwen_generator)
and then records what is ACTUALLY running: model id and revision, weights and tokenizer hashes, chat
template hash, dtype, device, attention implementation, context length, library versions and the
generation config as the pipeline sets it.

The sanity suite then bypasses retrieval, the database, the grounded system prompt, citation processing,
validation and repair: a minimal instruction plus a short passage goes straight to generate_chat, and the
raw output is scored by string test, not judgement. It proves only whether the inference implementation
behaves; it says nothing about regulatory competence.

Output: <out>/phase2_runtime.json, <out>/phase1_sanity.json, <out>/phase1_sanity.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FILLER = ("The agency maintains records of correspondence with regulated establishments in accordance with its "
          "internal document retention schedule, which is reviewed periodically by the office of management. ")

# Each case: id, category, passage, question, and a mechanical check on the raw output.
CASES = [
    ("A1", "factual extraction", "Product X was approved on 15 March 2024.", "When was Product X approved?",
     lambda t: "15 march 2024" in t.lower() or "march 15, 2024" in t.lower()),
    ("A2", "factual extraction", "Facility 4417 holds registration number R-88213 and was last inspected on 2 July 2023.",
     "What is the registration number of Facility 4417?", lambda t: "r-88213" in t.lower()),
    ("A3", "factual extraction", "The retention period for batch records is 7 years after distribution.",
     "How long must batch records be retained?", lambda t: "7 year" in t.lower() or "seven year" in t.lower()),
    ("B1", "instruction following", "Product Y was recalled in 2022.",
     'Answer using exactly this format and nothing else:\nAnswer: YES\nReason: <one sentence>\n\nWas Product Y recalled?',
     lambda t: bool(re.search(r"^\s*Answer:\s*YES", t, re.I | re.M)) and bool(re.search(r"^\s*Reason:\s*\S", t, re.I | re.M))),
    ("B2", "instruction following", "The limit is 140 milligrams per serving.",
     "Reply with the number only, no words, no units.\n\nWhat is the limit in milligrams?",
     lambda t: t.strip().rstrip(".").strip() == "140"),
    ("C1", "multi-step reasoning", "Rule 1: a facility must register if it processes more than 500 units per year.\n"
     "Rule 2: a facility that only stores finished product is exempt from Rule 1.\n"
     "Facility Z processes 900 units per year and does not only store finished product.",
     "Must Facility Z register? Answer yes or no and say which rule decides it.",
     lambda t: "yes" in t.lower()[:200] and "rule 1" in t.lower()),
    ("C2", "multi-step reasoning", "Rule A: records must be kept 3 years.\nRule B: for exported product, records must be kept 5 years.\n"
     "Shipment 12 was exported.", "How long must records for Shipment 12 be kept?",
     lambda t: "5 year" in t.lower() or "five year" in t.lower()),
    ("C3", "multi-step reasoning", "Section 10 applies to Class II devices only.\nSection 20 applies to all devices.\n"
     "Device Q is a Class I device.", "Which of the two sections applies to Device Q?",
     lambda t: "20" in t and "section 10" not in t.lower().replace("section 10 applies", "")),
    ("D1", "context utilisation", FILLER * 3 + "The approved shelf life for Lot 77 is 18 months. " + FILLER * 3,
     "What is the approved shelf life for Lot 77?", lambda t: "18 month" in t.lower()),
    ("D2", "context utilisation", FILLER * 6 + "The designated contact for Facility 4417 is the quality manager.",
     "Who is the designated contact for Facility 4417?", lambda t: "quality manager" in t.lower()),
    ("E1", "negative evidence", "Product X was approved on 15 March 2024.", "What is the expiry date of Product X?",
     lambda t: any(p in t.lower() for p in ("not", "no ", "does not", "unavailable", "cannot", "unknown"))),
    ("E2", "negative evidence", "Facility 4417 holds registration number R-88213.",
     "How many employees does Facility 4417 have?",
     lambda t: any(p in t.lower() for p in ("not", "no ", "does not", "unavailable", "cannot", "unknown"))),
    ("F1", "long context 500", None, None, None),
    ("F2", "long context 1500", None, None, None),
    ("F3", "long context 2500", None, None, None),
    ("F4", "long context 3500", None, None, None),
]
NEEDLE = "The approved shelf life for Lot 77 is 18 months."
MINIMAL_SYSTEM = "Answer the question using only the PASSAGE. If the passage does not contain the answer, say so."


def long_case(tokenizer, target_tokens: int):
    """Needle in the middle of filler, grown to roughly target_tokens."""
    body, n = "", 0
    while True:
        candidate = FILLER * n
        if len(tokenizer(candidate)["input_ids"]) >= target_tokens:
            body = candidate
            break
        n += 1
    half = len(body) // 2
    return body[:half] + NEEDLE + " " + body[half:], "What is the approved shelf life for Lot 77?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts/diagnostics/model_probe"))
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    import torch
    import transformers
    from regulus.config import load_settings
    from regulus.inference.generate import generate_chat
    from regulus.rag.remote_generator import load_generator
    from regulus.system_identity import configured_generation_config

    settings = load_settings()
    settings.generation = configured_generation_config(settings)   # the pipeline's own decoding
    gen = load_generator(settings, local_files_only=True)
    model, tok = gen.model, gen.tokenizer

    # ---------------------------------------------------------------- Phase 2: what is actually running
    snap = sorted(Path(settings.model.cache_dir).glob(f"models--{settings.model.id.replace('/', '--')}/snapshots/*"))
    snap = snap[0] if snap else None
    def sha(p):
        if not p or not Path(p).is_file():
            return None
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 24), b""):
                h.update(c)
        return h.hexdigest()
    cfg = model.config
    gc = getattr(model, "generation_config", None)
    template = getattr(tok, "chat_template", None)
    runtime = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "intended_from_config": {"id": settings.model.id, "device": settings.model.device, "dtype": settings.model.dtype,
                                 "adapter": str(settings.model.adapter) if settings.model.adapter else None,
                                 "backend": settings.model.backend},
        "runtime_model": {
            "class": type(model).__name__, "config_name_or_path": getattr(cfg, "_name_or_path", None),
            "commit_hash": getattr(cfg, "_commit_hash", None), "architectures": getattr(cfg, "architectures", None),
            "dtype": str(model.dtype), "device": str(model.device),
            "attn_implementation": getattr(cfg, "_attn_implementation", None),
            "max_position_embeddings": getattr(cfg, "max_position_embeddings", None),
            "hidden_size": getattr(cfg, "hidden_size", None), "num_hidden_layers": getattr(cfg, "num_hidden_layers", None),
            "vocab_size": getattr(cfg, "vocab_size", None),
            "parameters": sum(p.numel() for p in model.parameters()),
            "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "weights_sha256": sha(snap / "model.safetensors") if snap else None,
            "snapshot_dir": str(snap) if snap else None,
        },
        "runtime_tokenizer": {
            "class": type(tok).__name__, "name_or_path": getattr(tok, "name_or_path", None),
            "vocab_size": tok.vocab_size, "model_max_length": tok.model_max_length,
            "eos_token": tok.eos_token, "eos_token_id": tok.eos_token_id,
            "pad_token": tok.pad_token, "pad_token_id": tok.pad_token_id,
            "tokenizer_json_sha256": sha(snap / "tokenizer.json") if snap else None,
            "chat_template_sha256": hashlib.sha256((template or "").encode()).hexdigest() if template else None,
            "chat_template_chars": len(template or ""),
            "chat_template_mentions_think": ("enable_thinking" in (template or "")),
        },
        "pipeline_generation_config": {
            "max_new_tokens": settings.generation.max_new_tokens, "do_sample": settings.generation.do_sample,
            "temperature": settings.generation.temperature, "top_p": settings.generation.top_p,
            "top_k": settings.generation.top_k, "enable_thinking": settings.generation.enable_thinking,
            "repetition_penalty": getattr(settings.generation, "repetition_penalty", None),
            "no_repeat_ngram_size": getattr(settings.generation, "no_repeat_ngram_size", None),
        },
        "model_generation_config_defaults": {k: getattr(gc, k, None) for k in
                                             ("do_sample", "temperature", "top_p", "top_k", "max_new_tokens",
                                              "repetition_penalty", "eos_token_id", "pad_token_id")} if gc else None,
        "stack": {"python": platform.python_version(), "torch": torch.__version__,
                  "transformers": transformers.__version__, "platform": platform.platform(),
                  "cuda_available": torch.cuda.is_available(),
                  "mps_available": bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()),
                  "threads": torch.get_num_threads()},
        "generator_describe": gen.describe(),
    }
    (out / "phase2_runtime.json").write_text(json.dumps(runtime, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: runtime[k] for k in ("intended_from_config", "runtime_model", "runtime_tokenizer",
                                              "pipeline_generation_config", "stack")}, indent=1, default=str)[:3000])

    # ---------------------------------------------------------------- Phase 1: sanity suite, nothing in the way
    cases = []
    for cid, cat, passage, question, check in CASES:
        if passage is None:
            target = int(cat.split()[-1])
            passage, question = long_case(tok, target)
            check = lambda t: "18 month" in t.lower()
        cases.append((cid, cat, passage, question, check))

    rows = []
    for cid, cat, passage, question, check in cases:
        user = f"PASSAGE:\n{passage}\n\nQUESTION: {question}"
        messages = [{"role": "system", "content": MINIMAL_SYSTEM}, {"role": "user", "content": user}]
        rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                           enable_thinking=settings.generation.enable_thinking)
        t0 = time.perf_counter()
        res = generate_chat(model, tok, messages, replace(settings.generation, max_new_tokens=256), stop_repetition=True)
        rows.append({
            "id": cid, "category": cat, "question": question, "passage_chars": len(passage),
            "prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(), "prompt_tokens": res.prompt_tokens,
            "generated_tokens": res.generated_tokens, "finished_with_eos": res.finished,
            "stop_reason": res.stop_reason, "seconds": round(time.perf_counter() - t0, 1),
            "raw_output": res.response, "mechanical_check_passed": bool(check(res.response)),
        })
        print(f"{cid:3} {cat:22} tokens in/out {res.prompt_tokens:5}/{res.generated_tokens:4} "
              f"{'PASS' if rows[-1]['mechanical_check_passed'] else 'FAIL'}  {rows[-1]['seconds']:5}s", flush=True)
    (out / "phase1_sanity.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    byc = {}
    for r in rows:
        k = r["category"].split()[0] if not r["category"].startswith("long") else "long context"
        byc.setdefault(k, []).append(r["mechanical_check_passed"])
    lines = ["# Phase 1 sanity suite (minimal prompt, no retrieval, no post-processing)", "",
             "| category | passed | n |", "|---|---:|---:|"]
    for k, v in byc.items():
        lines.append(f"| {k} | {sum(v)} | {len(v)} |")
    (out / "phase1_sanity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\npassed", sum(r["mechanical_check_passed"] for r in rows), "of", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
