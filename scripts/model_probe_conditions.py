"""Phases 5-8: the same questions under three prompt conditions, plus a generation-config check.

    python scripts/model_probe_conditions.py --set artifacts/diagnostics/model_probe/probe_set.json

Conditions, run on identical questions with the identical model, decoding policy and token budget:

  B  production  - the pipeline unchanged: its prompt, its evidence, its tiering and ordering.
  C  simplified  - a short instruction, the SAME evidence set in the SAME order as B, rendered plainly.
  A  focused     - a short instruction and ONLY the keyed provision's text from the snapshot.

B -> C isolates the prompt. C -> A isolates evidence focusing and ordering. Raw model output is captured
for every cell before any validation, repair or citation processing, so a pipeline defect cannot be read
as a model defect. A small generation-config arm (sampling, and the budget halved) runs on a subset.

Scoring here is MECHANICAL and deliberately crude - content-word recall against the benchmark's key answer
elements, and whether the keyed section number is named - so the three conditions are compared on one
identical yardstick. It is a proxy for the rubric, not the rubric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from model_probe_phase3 import RecordingGenerator  # noqa: E402

MINIMAL_SYSTEM = ("Answer the question about U.S. FDA regulations using only the EVIDENCE below. "
                  "Cite the section you used. If the evidence does not answer the question, say so.")
STOP = set("what does which require requires required requirement requirements must shall under that this with from part "
           "section about their there these those have when where into such each every apply applies the and for are not "
           "you your how many give list cite explain describe summarize summarise walk tell does do is it its on in of a "
           "an be by or if my our we can confirm so also including include any other".split())
words = lambda t: {w for w in re.findall(r"[a-z][a-z-]{3,}", (t or "").lower())} - STOP


def recall(answer: str, key_elements: str) -> float:
    k = words(key_elements)
    return len(k & words(answer)) / len(k) if k else 0.0


def section_text(db, section: str, limit: int = 2600) -> str:
    rows = db.query("SELECT paragraph_path, body_text, section_heading FROM cfr_records "
                    "WHERE section_number=%s ORDER BY path_ordinal, ordinal", (section,))
    if not rows:
        return ""
    head = rows[0]["section_heading"] or ""
    body = " ".join(f"{r['paragraph_path'] or ''} {(r['body_text'] or '').strip()}" for r in rows)
    t = f"{section} {head}\n{re.sub(r'  +', ' ', body)}"
    return t[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--out", default=str(ROOT / "artifacts/diagnostics/model_probe"))
    ap.add_argument("--genconfig-subset", type=int, default=10)
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    probe = json.loads(Path(args.set).read_text(encoding="utf-8"))

    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
    from regulus.inference.generate import generate_chat
    from regulus.rag import RagPipeline
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config

    bench = {q.question_id: q for q in load_acceptance_benchmark()}
    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    base = load_generator(settings, local_files_only=True)
    rec = RecordingGenerator(base, base.tokenizer, settings.generation.enable_thinking)
    tok, model = base.tokenizer, base.model
    db = Database.from_env(); db.connect()
    cfg = configured_rag_config(settings)
    retriever, scope = build_retriever(db, cfg)
    pipe = RagPipeline(retriever, rec, cfg, scope_policy=scope)

    def run(system: str, user: str, budget: int, gen_override=None):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                           enable_thinking=settings.generation.enable_thinking)
        g = replace(settings.generation, max_new_tokens=budget)
        if gen_override:
            g = replace(g, **gen_override)
        t0 = time.perf_counter()
        res = generate_chat(model, tok, messages, g, stop_repetition=True)
        return {"prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(), "prompt_tokens": res.prompt_tokens,
                "generated_tokens": res.generated_tokens, "finished_with_eos": res.finished,
                "stop_reason": res.stop_reason, "seconds": round(time.perf_counter() - t0, 1), "raw": res.response}

    rows = []
    for i, item in enumerate(probe, start=1):
        qid = item["id"]; q = bench[qid]
        key_secs = item.get("key_sections") or []
        row = {"id": qid, "type": q.question_type, "question": q.question, "key_citation": q.expected_citation_draft,
               "key_elements": q.key_answer_elements, "key_sections": key_secs}

        # ---------- B: production, unchanged
        before = len(rec.calls)
        t0 = time.perf_counter()
        outp = pipe.answer(q.question)
        calls = rec.calls[before:]
        b = calls[0] if calls else None
        m = outp.metadata
        row["B_production"] = {
            "model_called": outp.model_called, "prompt_sha256": b and b["prompt_sha256"],
            "prompt_tokens": b and b["prompt_tokens_counted"], "budget": b and b["generation_budget_passed"],
            "generated_tokens": b and b["generated_tokens"], "finished_with_eos": b and b["finished_with_eos"],
            "stop_reason": b and b["stop_reason"], "seconds": round(time.perf_counter() - t0, 1),
            "raw": (b and b["raw_response"]) or "", "final_answer": outp.answer,
            "repair": (m.get("validation") or {}).get("repair"),
            "evidence": [s.result.citation.label for s in outp.context.sources],
            "sources_all_exact": (b and b["user"].count("Tier: EXACT") == b["user"].count("SOURCE ")) if b else None,
            "exact_source_count": (b and b["user"].count("Tier: EXACT")) if b else None,
            "source_count": len(outp.context.sources),
        }
        budget = (b and b["generation_budget_passed"]) or 384
        srcs = [(s.result.citation.label, s.text) for s in outp.context.sources]

        # ---------- C: simplified prompt, SAME evidence and order
        body = "\n\n".join(f"SOURCE {n}: {lab}\n{txt}" for n, (lab, txt) in enumerate(srcs, start=1)) or "(no sources)"
        row["C_simplified"] = run(MINIMAL_SYSTEM, f"EVIDENCE:\n{body}\n\nQUESTION: {q.question}", budget)

        # ---------- A: focused evidence, keyed provision only
        focused = "\n\n".join(t for t in (section_text(db, s) for s in key_secs) if t)
        if focused:
            row["A_focused"] = run(MINIMAL_SYSTEM, f"EVIDENCE:\n{focused}\n\nQUESTION: {q.question}", budget)
            row["A_focused"]["evidence_sections"] = key_secs
        else:
            row["A_focused"] = {"skipped": "no keyed section to supply (trap or statutory key)"}

        for cond in ("B_production", "C_simplified", "A_focused"):
            c = row[cond]
            if "raw" in c:
                c["key_recall"] = round(recall(c["raw"], q.key_answer_elements), 3)
                c["names_key_section"] = bool(key_secs) and any(s in (c["raw"] or "") for s in key_secs)
        row["B_final_key_recall"] = round(recall(row["B_production"]["final_answer"], q.key_answer_elements), 3)

        # ---------- Phase 8: generation config, on a subset, condition C held fixed
        if i <= args.genconfig_subset and srcs:
            user = f"EVIDENCE:\n{body}\n\nQUESTION: {q.question}"
            row["G_sampling"] = run(MINIMAL_SYSTEM, user, budget, {"do_sample": True, "temperature": 0.7, "top_p": 0.8, "top_k": 20})
            row["G_half_budget"] = run(MINIMAL_SYSTEM, user, max(64, budget // 2))
            row["G_thinking"] = run(MINIMAL_SYSTEM, user, budget, {"enable_thinking": True})
            for k in ("G_sampling", "G_half_budget", "G_thinking"):
                row[k]["key_recall"] = round(recall(row[k]["raw"], q.key_answer_elements), 3)
        rows.append(row)
        print(f"{i:3}/{len(probe)} {qid:8} {q.question_type:16} "
              f"B recall {row['B_production']['key_recall']:.2f} ({row['B_production']['prompt_tokens']}tok, "
              f"{row['B_production']['source_count']} src, all_exact={row['B_production']['sources_all_exact']})  "
              f"C {row['C_simplified']['key_recall']:.2f}  "
              f"A {row['A_focused'].get('key_recall', '-')}", flush=True)
        (out / "phase567_conditions.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    db.close()
    print("wrote", out / "phase567_conditions.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
