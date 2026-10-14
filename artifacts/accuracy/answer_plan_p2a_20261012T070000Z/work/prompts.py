"""Rendered-prompt snapshot: the exact user message the model would receive, without generating.

Retrieval -> coverage -> selection -> package -> render, through the production pipeline
configuration. No model is loaded and nothing is generated, so this is not a benchmark run; it
records the deterministic prompt for each of the 300 frozen benchmark questions and a probe set,
so a planning change can be diffed prompt by prompt against the pre-change baseline.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

PROBES = [
    ("P1-direct7",    "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?"),
    ("P2-howquickly", "How quickly must IND safety reports be submitted under 21 CFR 312.32?"),
    ("P3-timeframes", "What are the IND safety reporting timeframes under 21 CFR 312.32?"),
    ("P3-both",       "What are the 7-day and 15-day IND safety reporting deadlines under 21 CFR 312.32?"),
    ("P3-all",        "What are all the reporting deadlines in 21 CFR 312.32?"),
    ("P4-compare",    "What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in 21 CFR 312.32?"),
    ("P5-summarize",  "Summarize 21 CFR 312.32."),
    ("P5-require",    "What does 21 CFR 312.32 require?"),
    ("P5-indsafety",  "What are the IND safety reporting requirements under 21 CFR 312.32?"),
    ("C-retention",   "How long must records be retained under 21 CFR 211.180?"),
    ("C-personnel",   "What are the personnel qualification requirements in 21 CFR 211.25?"),
    ("C-followup",    "What follow-up does 21 CFR 312.32 require after an IND safety report?"),
    ("C-mdr30",       "How soon must a manufacturer submit a 5-day report under 21 CFR 803.53?"),
    ("C-recall",      "Within how many working days must a correction or removal be reported under 21 CFR 806.10?"),
]


class Stub:
    def describe(self): return {"generator": "none (prompt snapshot)"}
    def generate(self, *a, **k): raise AssertionError("the prompt snapshot must not generate")


def main() -> int:
    out_path = Path(sys.argv[1])
    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.generation import build_grounded_messages, build_package
    from regulus.retrieval import Database, Filters, LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config

    settings = load_settings()
    db = Database.from_env(); db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config, lexical=LexicalRetriever(db))
    from dataclasses import replace
    config = replace(config, top_k=8)                       # the answering UI's default
    pipeline = RagPipeline(retriever, Stub(), config, scope_policy=scope)

    cases = [(q.question_id, q.question) for q in load_acceptance_benchmark(ROOT / DEFAULT_WORKBOOK)] + PROBES
    res = {}
    for n, (qid, question) in enumerate(cases, start=1):
        plan = pipeline.complete_plan(plan_query(question))
        shape, analysis = pipeline.question_view(plan)
        out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
        bundle, coverage, sel = pipeline.build_bundle(out.response, out.registry, shape, question)
        prompt = None
        if sel is not None and coverage is not None:
            try:
                # exactly the call RagPipeline.answer() makes
                package = build_package(plan, coverage, sel, notes=bundle.notes, budget=pipeline.config.generation_budget,
                                        answer_shape=shape, question_analysis=analysis)
                prompt = build_grounded_messages(package)[-1]["content"]
            except Exception as exc:  # recorded, never hidden
                prompt = f"<<render failed: {type(exc).__name__}: {exc}>>"
        res[qid] = {"question": question, "mode": shape.mode if shape else None,
                    "prompt_sha": hashlib.sha256((prompt or "").encode()).hexdigest()[:16], "prompt": prompt}
        if n % 100 == 0:
            print(f"  {n}/{len(cases)}", flush=True)
    db.close()
    out_path.write_text(json.dumps(res, indent=0, ensure_ascii=False), encoding="utf-8")
    print(f"{len(res)} prompts -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
