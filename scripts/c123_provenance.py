"""Evidence provenance for the acceptance benchmark, through the PRODUCTION retriever.

    .venv/bin/python scripts/c123_provenance.py <out.json> [--no-c3]

Retrieval -> coverage -> selection only. No model is loaded and no answer is generated, so this
is not a benchmark run; it records what the pipeline would put in front of the model for each
question, which is deterministic given the question and the corpus:

    coverage state, requirements and which resolved, selected sources and their citations,
    selected characters, required/dropped evidence, per-section row counts.

`--no-c3` skips the cross-section range step (pipeline.complete_plan), so the same script can
produce the pre-C3 provenance for comparison. C1 and C2 live in the retriever and are always on.

Read-only; writes only the file it is given.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


class Stub:
    """Stands in for the generator: build_bundle never calls it."""

    def describe(self):
        return {"generator": "none (provenance pass)"}

    def generate(self, *a, **k):
        raise AssertionError("the provenance pass must not generate")


def main() -> int:
    out_path = Path(sys.argv[1])
    use_c3 = "--no-c3" not in sys.argv

    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.selection import is_required
    from regulus.retrieval import Database, Filters
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config

    settings = load_settings()
    db = Database.from_env()
    db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config)
    pipeline = RagPipeline(retriever, Stub(), config, scope_policy=scope)
    bench = load_acceptance_benchmark(ROOT / DEFAULT_WORKBOOK)

    res = {}
    for n, q in enumerate(bench, start=1):
        plan = plan_query(q.question)
        if use_c3:
            plan = pipeline.complete_plan(plan)
        shape, _ = pipeline.question_view(plan)
        out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
        bundle, coverage, selection = pipeline.build_bundle(out.response, out.registry, shape)
        per_section: dict[str, list[int]] = {}
        for s in selection.selected:
            sec = s.evidence.result.metadata.get("section")
            if sec is not None:
                per_section.setdefault(sec, []).append(s.evidence.result.metadata.get("ordinal"))
        part_level = any(r.reference.section is None and r.reference.title == "21" for r in plan.requirements)
        res[q.question_id] = {
            "question": q.question,
            "part_level": part_level,
            "plan_kind": plan.kind,
            "requirements": [r.canonical for r in plan.requirements],
            "coverage": coverage.state if coverage else None,
            "resolved": list(coverage.satisfied_ids) if coverage else [],
            "retrieved_evidence": [e.citation for e in out.registry.evidence],
            "required_evidence": [e.citation for e in out.registry.evidence if is_required(e)],
            "selected_evidence": [s.evidence.citation for s in selection.selected],
            "selected_sources": len(selection.selected),
            "selected_chars": selection.total_chars,
            "context_chars": len(bundle.text),
            "required_dropped": len(selection.diagnostics["required_dropped"]),
            "optional_dropped": len(selection.diagnostics["optional_dropped"]),
            "overflow": selection.overflow,
            "sections": per_section,
            "part_expanded": sorted({e.result.metadata["part_expanded_from"] for e in out.registry.evidence
                                     if "part_expanded_from" in e.result.metadata}),
        }
        if n % 50 == 0:
            print(f"  {n}/300", flush=True)
    db.close()
    out_path.write_text(json.dumps(res, indent=0, default=str), encoding="utf-8")
    print(f"300 questions -> {out_path} (c3={'on' if use_c3 else 'off'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
