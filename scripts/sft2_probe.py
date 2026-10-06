"""Short read-only sanity probe: base Qwen3-0.6B vs the SFT v2 adapter, same decoding.

    .venv/bin/python scripts/sft2_probe.py

Not an evaluation. A handful of deterministic generations to see whether the adapter has
degenerated, started repeating, started refusing, or started hallucinating, before anything long
is run. Nothing is scored and no benchmark row is touched: the prompts are validation examples the
model already trained on, plus three out-of-scope questions written here. The 148 held-out
benchmark questions are deliberately NOT used, so this cannot contaminate the primary evaluation.

Decoding comes from the production config (`configured_generation_config`): greedy, thinking off,
cpu/float32 - identical to the baseline acceptance run. The ONE deviation is max_new_tokens, capped
at PROBE_MAX_TOKENS to keep the probe short; the pipeline's adaptive allowance is not reproduced.
The adapter is merged with the same `attach_saved_adapter(..., merge=True)` the pipeline uses.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.config import load_settings  # noqa: E402
from regulus.finetune import attach_saved_adapter  # noqa: E402
from regulus.finetune.data import example_messages  # noqa: E402
from regulus.model import load_model, load_tokenizer  # noqa: E402
from regulus.system_identity import configured_generation_config  # noqa: E402
from regulus.training.models import TrainingExample, read_jsonl  # noqa: E402

ADAPTER = ROOT / "models/qwen3-0.6b-lora/sft2_v1/adapter"
VALIDATION = ROOT / "artifacts/sft2/trainer/validation.jsonl"
PROBE_MAX_TOKENS = 400

# Out-of-scope subjects that genuinely EXIST. The correct behaviour is to decline scope, never to
# deny existence. Written here; none is a benchmark question.
OUT_OF_SCOPE = [
    "What does ISO 14971 require for risk management?",
    "What does EU MDR Annex IX require for conformity assessment?",
    "What are the UK MHRA registration requirements for a Class IIa device?",
]


def repetition_ratio(text: str) -> float:
    """Share of sentences that are duplicates - a cheap degeneration signal."""
    sents = [s.strip().lower() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 15]
    return 0.0 if not sents else round(1 - len(set(sents)) / len(sents), 3)


def generate(model, tokenizer, messages, max_new_tokens: int) -> tuple[str, int, float]:
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)
    ids = tokenizer(text, return_tensors="pt", add_special_tokens=False)
    t0 = time.time()
    out = model.generate(**ids, max_new_tokens=max_new_tokens, do_sample=False,
                         pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    new = out[0][ids["input_ids"].shape[1]:]
    return tokenizer.decode(new, skip_special_tokens=True), int(new.shape[0]), time.time() - t0


def main() -> int:
    settings = load_settings()
    gen = configured_generation_config(settings)
    print(f"decoding: do_sample={gen.do_sample} enable_thinking={gen.enable_thinking} "
          f"production_ceiling={gen.max_new_tokens} -> probe cap {PROBE_MAX_TOKENS}")
    print(f"device={settings.model.device} dtype={settings.model.dtype}\n")

    val = {ex.id: ex for ex in read_jsonl(VALIDATION)}
    answers = [ex for ex in val.values() if ex.context and ex.citations]
    no_ctx = [ex for ex in val.values() if not ex.context]
    probes: list[tuple[str, str, list]] = []
    for ex in no_ctx[:1]:
        probes.append((ex.id, "seen / no sources (scope)", example_messages(ex, "grounded")[:-1]))
    for ex in sorted(answers, key=lambda e: -len(e.answer))[:2]:
        probes.append((ex.id, "seen / grounded answer", example_messages(ex, "grounded")[:-1]))
    template = no_ctx[0] if no_ctx else None
    for q in OUT_OF_SCOPE:
        ex = TrainingExample(type=template.type, category=template.category, question=q,
                             context=[], answer="n/a", citations=[], grounded=False,
                             generator=template.generator, group="probe", id="probe")
        probes.append((f"UNSEEN:{q[:34]}", "unseen / no sources (scope)", example_messages(ex, "grounded")[:-1]))

    tokenizer = load_tokenizer(settings.model, local_files_only=True)
    results: dict[str, dict] = {}
    for arm in ("base", "sft2_v1"):
        model = load_model(settings.model, local_files_only=True)
        if arm != "base":
            model, info = attach_saved_adapter(model, ADAPTER, merge=True)
            print(f"adapter merged: {info.get('adapter_name')} r={info.get('r')} "
                  f"best={info.get('best_checkpoint')}\n")
        model.eval()
        for pid, kind, messages in probes:
            text, ntok, secs = generate(model, tokenizer, messages, PROBE_MAX_TOKENS)
            results.setdefault(pid, {"kind": kind})[arm] = {
                "text": text, "tokens": ntok, "seconds": round(secs, 1),
                "repetition": repetition_ratio(text), "hit_cap": ntok >= PROBE_MAX_TOKENS,
            }
            print(f"[{arm:8}] {pid:40} {ntok:4} tok {secs:6.1f}s rep={repetition_ratio(text)}")
        del model

    out = ROOT / "artifacts/sft2/trainer/probe.json"
    out.write_text(json.dumps({"adapter": str(ADAPTER), "probe_max_tokens": PROBE_MAX_TOKENS,
                               "results": results}, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
