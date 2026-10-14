"""Evidence-selection snapshot: what the pipeline would put in front of the model.

Retrieval -> coverage -> selection only. No model is loaded and no answer is generated, so this is
not a benchmark run and it writes nothing but the file it is given.

Covers the 300 frozen benchmark questions AND a probe set of synonym wordings for the IND
safety-reporting deadline, so a change can be diffed against the pre-change baseline on both.

    .venv/bin/python .../work/snapshot.py out.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

# Synonym wordings of the same question, plus controls that must not move.
PROBES = [
    ("P-deadline",   "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?"),
    ("P-timeframes", "What are the IND safety reporting timeframes under 21 CFR 312.32?"),
    ("P-timelimits", "What are the time limits for IND safety reporting under 21 CFR 312.32?"),
    ("P-timeline",   "What is the reporting timeline for an unexpected fatal reaction under 21 CFR 312.32?"),
    ("P-howquickly", "How quickly must IND safety reports be submitted under 21 CFR 312.32?"),
    ("P-howsoon",    "How soon must a sponsor report an unexpected fatal reaction under 21 CFR 312.32?"),
    ("P-withindays", "Within how many days must a sponsor submit an IND safety report under 21 CFR 312.32?"),
    ("P-difference", "What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in 21 CFR 312.32?"),
    # controls: no value asked for, no salient terms, or a different subject entirely
    ("C-summarize",  "Summarize 21 CFR 312.32."),
    ("C-definitions","What are the definitions in 21 CFR 312.32?"),
    ("C-requires",   "What does 21 CFR 312.32 require?"),
    ("C-followup",   "What follow-up does 21 CFR 312.32 require after an IND safety report?"),
    ("C-retention",  "How long must records be retained under 21 CFR 211.180?"),
    ("C-personnel",  "What are the personnel qualification requirements in 21 CFR 211.25?"),
    ("C-complaints", "What must complaint records include under 21 CFR 820.198?"),
]


class Stub:
    def describe(self): return {"generator": "none (selection snapshot)"}
    def generate(self, *a, **k): raise AssertionError("the snapshot must not generate")


def main() -> int:
    out_path = Path(sys.argv[1])
    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.retrieval import Database, Filters
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config

    settings = load_settings()
    db = Database.from_env(); db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config)
    pipeline = RagPipeline(retriever, Stub(), config, scope_policy=scope)

    cases = [(q.question_id, q.question) for q in load_acceptance_benchmark(ROOT / DEFAULT_WORKBOOK)] + PROBES
    res = {}
    for n, (qid, question) in enumerate(cases, start=1):
        plan = pipeline.complete_plan(plan_query(question))
        shape, _ = pipeline.question_view(plan)
        out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
        bundle, coverage, sel = pipeline.build_bundle(out.response, out.registry, shape, question)
        res[qid] = {
            "question": question,
            "selected": [s.evidence.citation for s in sel.selected] if sel else [],
            "ordinals": [s.evidence.result.metadata.get("ordinal") for s in sel.selected] if sel else [],
            "chars": sel.total_chars if sel else 0,
            "sources": len(sel.selected) if sel else 0,
            "overflow": bool(sel.overflow) if sel else False,
            "required_order": (sel.diagnostics.get("required_order") if sel else None),
            "required_dropped": sorted(d.evidence.citation for d in sel.dropped if d.required) if sel else [],
            "context_sha": __import__("hashlib").sha256(bundle.text.encode()).hexdigest()[:16],
        }
        if n % 100 == 0:
            print(f"  {n}/{len(cases)}", flush=True)
    db.close()
    out_path.write_text(json.dumps(res, indent=0, default=str), encoding="utf-8")
    print(f"{len(res)} cases -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
