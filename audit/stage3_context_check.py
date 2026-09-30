"""Stage 3 validation: coverage, selection and context on the live database.

Read-only. For each representative question: plan -> run_plan -> coverage ->
selection -> rendered context, without calling the model. Prints per question
the requirements, coverage state, selected/protected/dropped evidence,
context size and truncation. Output also goes to
audit/results/stage3_context_check.txt.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from regulus.planning import plan_query  # noqa: E402
from regulus.rag import ContextPolicy, RagConfig, RagPipeline, check_coverage, render_selection, select_evidence  # noqa: E402
from regulus.rag.prompt import coverage_note  # noqa: E402
from regulus.retrieval import Database, LexicalRetriever  # noqa: E402

QUESTIONS = [
    ("single", "What does 21 CFR 820.10(b)(2) require?"),
    ("two provisions", "What do 21 CFR 820.10(b)(2) and 820.10(b)(4) require?"),
    ("range", "What do 21 CFR 820.10(b)(1) through 820.10(b)(4) require?"),
    ("partly missing", "What do 21 CFR 820.10(b)(2) and 820.999 require?"),
    ("missing child", "What does 21 CFR 820.10(b)(5) require?"),
    ("parent", "What does 21 CFR 820.10(b) require?"),
    ("range incl. missing", "What do 820.10(b)(1) through 820.10(b)(5) require?"),
    ("section", "What does 21 CFR 820.10 say?"),
    ("docket", "Summarise the guidance in docket FDA-2016-D-2565"),
    ("general", "When must a manufacturer notify FDA about a complaint?"),
    ("general", "What is a CAPA?"),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = Database.from_env()
    db.connect()
    retriever = LexicalRetriever(db)
    config = RagConfig()
    pipeline = RagPipeline(retriever, generator=None, config=config)  # generator unused: no generation here
    lines: list[str] = []
    try:
        for kind, q in QUESTIONS:
            t0 = time.perf_counter()
            plan = plan_query(q)
            out = retriever.run_plan(plan, top_k=config.top_k)
            t1 = time.perf_counter()
            cov = check_coverage(out.registry)
            sel = select_evidence(out.registry, config.context, optional_filter=pipeline.is_useful)
            notes = list(out.response.notes) + ([coverage_note(cov.missing_labels)] if cov.state == "INCOMPLETE" else [])
            bundle = render_selection(sel, notes=notes)
            t2 = time.perf_counter()
            lines.append("=" * 100)
            lines.append(f"[{kind}] {q}")
            lines.append(f"requirements: {[r.canonical for r in plan.requirements]}")
            lines.append(f"coverage: {cov.state}  satisfied={list(cov.satisfied_ids)} missing={list(cov.missing_labels)}")
            for r in cov.requirements:
                lines.append(f"  {r.requirement_id} {r.canonical:<24} {r.status:<16} exact={list(r.exact_evidence_ids)} structural={list(r.structural_evidence_ids)} discovery={len(r.discovery_evidence_ids)}")
            lines.append(f"selected: {len(sel.selected)} (protected {len(sel.protected)}, optional {sel.diagnostics['optional_count']}); dropped {len(sel.dropped)}; "
                         f"context chars {len(bundle.text)} (blocks {sel.total_chars}); overflow={sel.overflow}; "
                         f"retrieval {round((t1 - t0) * 1000)} ms, coverage+selection+render {round((t2 - t1) * 1000, 1)} ms")
            for s in sel.selected:
                lines.append(f"  SOURCE {s.index:<2} {s.evidence.tier:<11} {'protected' if s.protected else 'optional ':<9} req={list(s.requirement_ids)} "
                             f"chars={len(s.text):<5} trunc={s.truncated} {s.evidence.citation[:60]}")
            for d in sel.dropped[:6]:
                lines.append(f"  dropped  {d.evidence.tier:<11} {d.reason:<18} {'required' if d.required else 'optional'} {d.evidence.citation[:60]}")
            if len(sel.dropped) > 6:
                lines.append(f"  ... {len(sel.dropped) - 6} more dropped")
            for n in bundle.notes:
                lines.append(f"  NOTE: {n[:140]}")
    finally:
        db.close()
    text = "\n".join(lines)
    print(text)
    out_path = Path(__file__).resolve().parent / "results" / "stage3_context_check.txt"
    out_path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
