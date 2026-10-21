"""Per-required-provision stage attribution for the acceptance benchmark (regulus.evaluation.provision_trace).

    python scripts/trace_required_provisions.py --run artifacts/acceptance_runs/<run>    # a recorded run (measurement.jsonl)
    python scripts/trace_required_provisions.py --live <out_dir>                          # retrieval + selection now, no model

Required provisions: a locked key's accepted citation for rows an expert VERIFIED (key_status "expert_verified");
otherwise the workbook's draft citation (key_status "draft_unverified" - a retrieval target, not an answer key).
Without a model (--live) nothing is cited, so the last stage reached is in_prompt.

Writes <out>/provision_trace.jsonl (one line per question and provision) and <out>/provision_trace_summary.json
(stage counts overall, for questions that name a provision and for general ones, plus the corpus identity).
Reads the database only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.config import load_settings  # noqa: E402
from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark  # noqa: E402
from regulus.evaluation.acceptance_gate import locked_key_for  # noqa: E402
from regulus.evaluation.provision_trace import KEY_DRAFT, KEY_VERIFIED, summarise, trace_record  # noqa: E402
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.references import parse_cfr_references  # noqa: E402
from regulus.traceability import measurement as M  # noqa: E402
from regulus.traceability.corpus import corpus_identity  # noqa: E402


def required_provisions(bench) -> dict[str, tuple[tuple[str, ...], str]]:
    """question id -> (required provision labels, key status)."""
    locked = locked_key_for(bench.benchmark_key)
    verified = {r["question_id"]: r for r in (locked or {}).get("rows", []) if r.get("in_scope_for_scoring")}
    out = {}
    for q in bench.questions:
        row = verified.get(q.question_id)
        text, status = (row["accepted_citation"], KEY_VERIFIED) if row else (q.expected_citation_draft, KEY_DRAFT)
        out[q.question_id] = (tuple(dict.fromkeys(r.canonical for r in parse_cfr_references(text or ""))), status)
    return out


def live_records(bench, db):
    from regulus.inference.types import GenerationResult
    from regulus.rag import RagPipeline
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config

    class NoModel:   # retrieval and selection only; the "answer" is never evaluated
        def generate(self, messages, max_new_tokens=None, on_text=None):
            return GenerationResult("", "", 0, 0, 0.0, finished=True)

        def describe(self):
            return {"model_id": "none (retrieval trace)"}

    config = configured_rag_config(load_settings())
    retriever, scope = build_retriever(db, config)
    pipe = RagPipeline(retriever, NoModel(), config, scope_policy=scope)
    run = {"run_id": "provision-trace-live"}
    for n, q in enumerate(bench.questions, start=1):
        out = pipe.answer(q.question)
        rec = M.build_record(question_id=q.question_id, ordinal=n, question=q.question, out=out, run=run,
                             captured_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        rec["citations"] = []   # no model answered: nothing is cited
        yield rec


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", type=Path, help="a run directory containing measurement.jsonl")
    src.add_argument("--live", type=Path, help="output directory for a live retrieval-only trace")
    args = p.parse_args()

    load_settings()
    bench = load_acceptance_benchmark()
    keys = required_provisions(bench)
    db = Database.from_env()
    db.connect()
    try:
        corpus = corpus_identity(db)
        sections = {r["number"] for r in db.query("SELECT DISTINCT number FROM cfr_sections WHERE NOT is_reserved")}
        if args.run:
            out_dir = args.run
            records = [json.loads(l) for l in (args.run / M.MEASUREMENT_FILE).read_text(encoding="utf-8").splitlines() if l.strip()]
        else:
            out_dir = args.live
            out_dir.mkdir(parents=True, exist_ok=False)
            records = live_records(bench, db)
        names = {q.question_id: bool(parse_cfr_references(q.question)) for q in bench.questions}
        traces = []
        with (out_dir / "provision_trace.jsonl").open("w", encoding="utf-8") as f:
            for rec in records:
                wanted, status = keys.get(rec.get("question_id"), ((), KEY_DRAFT))
                for t in trace_record(rec, wanted, key_status=status, corpus_sections=sections):
                    traces.append(t)
                    f.write(json.dumps(t.to_dict()) + "\n")
    finally:
        db.close()
    summary = {"source": str(args.run or "live retrieval trace (no model)"), "corpus": corpus,
               "all": summarise(traces),
               "names_a_provision": summarise(t for t in traces if names.get(t.question_id)),
               "general": summarise(t for t in traces if not names.get(t.question_id))}
    (out_dir / "provision_trace_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    for group in ("all", "names_a_provision", "general"):
        s = summary[group]
        print(f"{group:18s} provisions={s['provisions']:4d} questions={s['questions']:3d} stages={s['stages']} "
              f"drops={s['drop_reasons']} keys={s['key_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
