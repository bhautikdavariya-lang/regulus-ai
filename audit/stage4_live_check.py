"""Stage 4 live validation: full pipeline on the base model and the live database.

Read-only. Each representative question runs through plan -> retrieval ->
coverage -> selection -> generation contract -> generation -> validation ->
citations, and everything is recorded:
    audit/results/stage4_live_check.jsonl   one full record per question
    audit/results/stage4_live_check.txt     readable summary
Greedy decoding, default GenerationBudget, base Qwen3-0.6B. No adapter.

Run with the UI server stopped: this machine cannot hold two models.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from regulus.config import load_settings  # noqa: E402
from regulus.rag import RagConfig, RagPipeline, load_qwen_generator  # noqa: E402
from regulus.retrieval import Database, LexicalRetriever  # noqa: E402

QUESTIONS = [
    ("single", "What does 21 CFR 820.10(b)(2) require?"),
    ("two", "What do 21 CFR 820.10(b)(2) and (b)(4) require?"),
    ("range4", "What do 21 CFR 820.10(b)(1) through (b)(4) require?"),
    ("range5 (partial)", "What do 21 CFR 820.10(b)(1) through (b)(5) require?"),
    ("missing child", "What does 21 CFR 820.10(b)(5) require?"),
    ("parent", "What does 21 CFR 820.10(b) require?"),
    ("section", "What does 21 CFR 820.10 say?"),
    ("partly missing", "What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?"),
    ("docket", "Summarise the guidance in docket FDA-2016-D-2565"),
    ("general", "When must a manufacturer notify FDA about a complaint?"),
    ("trap: form number", "Which FDA form number must be used under 21 CFR 820.10(b)(4)?"),
    ("trap: penalty", "What penalty amount does 21 CFR 820.10(b)(3) specify for late complaint notification?"),
    ("trap: world knowledge", "What is the capital of France?"),
    ("trap: compare", "Compare the requirements of § 820.10(b)(2) and § 820.10(b)(4)."),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    out_dir = Path(__file__).resolve().parent / "results"
    jsonl = out_dir / "stage4_live_check.jsonl"
    settings = load_settings()
    settings.generation.do_sample = False
    settings.generation.enable_thinking = False
    print("loading model ...")
    generator = load_qwen_generator(settings, local_files_only=True)
    db = Database.from_env()
    db.connect()
    pipeline = RagPipeline(LexicalRetriever(db), generator, RagConfig())
    lines: list[str] = []
    try:
        for kind, q in QUESTIONS:
            t0 = time.perf_counter()
            out = pipeline.answer(q)
            wall = round(time.perf_counter() - t0, 1)
            md = out.metadata
            v = md.get("validation") or {}
            g = md.get("generation") or {}
            record = {
                "kind": kind, "question": q, "plan": md["plan"], "coverage": md.get("coverage"), "coverage_action": md.get("coverage_action"),
                "selection": md.get("selection"), "generation": g, "validation": v, "citation_support": md.get("citation_support"),
                "citations": [c.to_dict() for c in out.citations], "answer": out.answer, "model_called": out.model_called,
                "timings_ms": out.timings_ms, "wall_s": wall, "input_tokens": out.input_tokens, "output_tokens": out.output_tokens,
            }
            with jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            cov = md.get("coverage") or {}
            lines.append("=" * 100)
            lines.append(f"[{kind}] {q}")
            lines.append(f"plan: {md['plan']['kind']} {[r['canonical'] for r in md['plan']['requirements']]}")
            lines.append(f"coverage: {cov.get('state')} missing={cov.get('missing_labels')}  action={md.get('coverage_action')}")
            sel = md.get("selection") or {}
            lines.append(f"selected: {[(s['citation'][:24], s['tier'], 'P' if s['protected'] else 'o') for s in sel.get('selected', [])]}")
            lines.append(f"generation: shape={g.get('shape')} cap={g.get('max_new_tokens')} generated={g.get('generated_tokens')} finished={g.get('finished')} prompt_chars={g.get('prompt_chars')}")
            if v:
                lines.append(f"validation: initial={v['initial']['status']} codes={v['initial']['codes']} -> final={v['final']['status']} repair={v.get('repair')}")
            lines.append(f"citations: {[(c.label[:24], c.role, c.tier) for c in out.citations]}")
            lines.append(f"timings: {', '.join(f'{k}={round(val)}' for k, val in out.timings_ms.items())} ms; wall {wall}s; model_called={out.model_called}")
            lines.append("ANSWER:\n" + out.answer)
            print("\n".join(lines[-9:]), flush=True)
    finally:
        db.close()
    (out_dir / "stage4_live_check.txt").write_text("\n".join(lines), encoding="utf-8")
    print("LIVE CHECK COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
