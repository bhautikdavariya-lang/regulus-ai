"""Stage 4 token-budget benchmark on the live database and the base model.

Runs a set of representative questions through the full pipeline under
several GenerationBudget configurations and records, per run: configured
limit, generated tokens, finished flag, truncation, validation status,
repair, addressed/unaddressed requirements, and timings. Read-only;
greedy decoding; base model only. Results:
    audit/results/stage4_token_benchmark.jsonl   one line per (config, question)
    audit/results/stage4_token_benchmark.log     progress

Run with the UI server stopped: this machine cannot hold two models.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from regulus.config import load_settings  # noqa: E402
from regulus.rag import GenerationBudget, RagConfig, RagPipeline, load_qwen_generator  # noqa: E402
from regulus.retrieval import Database, LexicalRetriever  # noqa: E402

QUESTIONS = [
    ("single", "What does 21 CFR 820.10(b)(2) require?"),
    ("two", "What do 21 CFR 820.10(b)(2) and 820.10(b)(4) require?"),
    ("range4", "What do 21 CFR 820.10(b)(1) through 820.10(b)(4) require?"),
    ("range5", "What do 820.10(b)(1) through 820.10(b)(5) require?"),
    ("section", "What does 21 CFR 820.10 say?"),
    ("general", "When must a manufacturer notify FDA about a complaint?"),
]

CONFIGS = {
    "fixed_128": GenerationBudget(base_tokens=128, per_unit_tokens=1, range_bonus_tokens=1, general_tokens=128, hard_max_tokens=128),
    "policy_small": GenerationBudget(base_tokens=48, per_unit_tokens=48, range_bonus_tokens=16, general_tokens=128, hard_max_tokens=320),
    "policy_default": GenerationBudget(base_tokens=64, per_unit_tokens=64, range_bonus_tokens=32, general_tokens=160, hard_max_tokens=448),
    "policy_large": GenerationBudget(base_tokens=96, per_unit_tokens=96, range_bonus_tokens=48, general_tokens=224, hard_max_tokens=640),
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    out_dir = Path(__file__).resolve().parent / "results"
    out_path = out_dir / "stage4_token_benchmark.jsonl"
    settings = load_settings()
    settings.generation.do_sample = False
    settings.generation.enable_thinking = False
    print("loading model ...")
    generator = load_qwen_generator(settings, local_files_only=True)
    db = Database.from_env()
    db.connect()
    retriever = LexicalRetriever(db)
    rows: list[dict] = []
    try:
        for cname, budget in CONFIGS.items():
            pipeline = RagPipeline(retriever, generator, RagConfig(generation_budget=budget))
            for qname, q in QUESTIONS:
                t0 = time.perf_counter()
                out = pipeline.answer(q)
                wall = round(time.perf_counter() - t0, 1)
                v = out.validation
                g = out.metadata.get("generation") or {}
                row = {
                    "config": cname, "question": qname, "text": q,
                    "max_new_tokens": g.get("max_new_tokens"), "generated_tokens": g.get("generated_tokens"), "finished": g.get("finished"),
                    "truncated": bool(v.truncated) if v else None,
                    "validation_initial": (out.metadata.get("validation") or {}).get("initial", {}).get("status"),
                    "validation_final": v.status if v else None, "repair": (out.metadata.get("validation") or {}).get("repair"),
                    "addressed": list(v.addressed) if v else [], "unaddressed": list((out.metadata.get("validation") or {}).get("initial", {}).get("unaddressed", [])),
                    "coverage_action": out.metadata.get("coverage_action"),
                    "timings_ms": out.timings_ms, "wall_s": wall, "model_called": out.model_called,
                    "answer": out.answer,
                }
                rows.append(row)
                with out_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[{cname:<14}] {qname:<8} cap={row['max_new_tokens']!s:<4} gen={row['generated_tokens']!s:<4} finished={row['finished']!s:<5} "
                      f"init={row['validation_initial']!s:<19} final={row['validation_final']!s:<11} repair={row['repair']!s:<32} "
                      f"gen_ms={round(out.timings_ms.get('generation_ms', 0))} wall={wall}s", flush=True)
    finally:
        db.close()
    print("\n=== summary per config")
    for cname in CONFIGS:
        rs = [r for r in rows if r["config"] == cname and r["model_called"]]
        if not rs:
            continue
        gen_ms = [r["timings_ms"].get("generation_ms", 0) for r in rs]
        tot_ms = [r["timings_ms"].get("total_ms", 0) for r in rs]
        print(f"{cname:<14} n={len(rs)} median_gen={statistics.median(gen_ms)/1000:.1f}s median_total={statistics.median(tot_ms)/1000:.1f}s "
              f"truncated={sum(1 for r in rs if r['truncated'])} initial_valid={sum(1 for r in rs if r['validation_initial']=='valid')} "
              f"final_valid={sum(1 for r in rs if r['validation_final']=='valid')} repaired={sum(1 for r in rs if r['repair'])} "
              f"tokens={[r['generated_tokens'] for r in rs]}")
    print("BENCHMARK COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
