"""Stage 2 validation: plan-driven retrieval on representative audit questions.

Read-only: parses each question, runs LexicalRetriever.run_plan against the
live read-only database and prints, per requirement, what evidence was found
and how it was classified. No model, no writes. Output goes to stdout and to
audit/results/stage2_retrieval_check.txt.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from regulus.planning import plan_query  # noqa: E402
from regulus.retrieval import Database, LexicalRetriever  # noqa: E402

QUESTIONS = [
    ("single provision", "What does 21 CFR § 820.10(b)(2) require?"),
    ("multi-provision", "What are the requirements of 21 CFR § 820.10(b)(1) and § 820.10(b)(2)?"),
    ("multi-provision (compare)", "Compare the requirements of § 820.10(b)(2) and § 820.10(b)(4)."),
    ("range", "List all of the specific requirements in 21 CFR § 820.10(b)(1) through (b)(4)."),
    ("range (bare)", "820.10(b)(1)-(4)"),
    ("list", "What are the requirements of 21 CFR § 820.10(b)(1), (b)(2), and (b)(3)?"),
    ("missing identifier", "What are the specific requirements of 21 CFR 314.999?"),
    ("missing part", "What does 21 CFR Part 1400 say about artificial intelligence in drug labeling?"),
    ("partly missing", "What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?"),
    ("parent/child", "What does 21 CFR § 820.10(b) require manufacturers to comply with?"),
    ("nonexistent child", "What does 21 CFR 820.10(b)(5) require?"),
    ("guidance/docket", "Summarise the guidance in docket FDA-2016-D-2565"),
    ("general regulatory", "When must a manufacturer notify FDA about a complaint?"),
    ("general regulatory", "What are the traceability requirements for manufacturers?"),
    ("unsupported general", "What is the capital of France?"),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = Database.from_env()
    db.connect()
    retriever = LexicalRetriever(db)
    lines: list[str] = []
    try:
        for kind, q in QUESTIONS:
            plan = plan_query(q)
            out = retriever.run_plan(plan, top_k=8)
            reg, resp = out.registry, out.response
            d = resp.diagnostics
            lines.append("=" * 100)
            lines.append(f"[{kind}] {q}")
            lines.append(f"plan kind={plan.kind} requirements={[r.canonical for r in plan.requirements]} docket={plan.docket}")
            lines.append(f"resolved={reg.resolved_requirements()} unresolved={reg.unresolved_requirements()} mode={d['retrieval_mode']} "
                         f"fallback_used={d['fallback_used']} fallback_terms={d['fallback_terms']} evidence={len(reg.evidence)} "
                         f"results={len(resp.results)} ms={resp.total_ms}")
            for rid, st in reg.requirement_state.items():
                lines.append(f"  {rid} {st.canonical:<24} attempted={st.exact_attempted} exact={st.exact_hits} structural={st.structural_hits} "
                             f"discovery={st.discovery_hits} fallback={st.fallback_run} {('note: ' + st.note[:70]) if st.note else ''}")
            for e in reg.evidence[:10]:
                lines.append(f"    {e.evidence_id:<4} {e.tier:<11} {e.retrieval_method:<13} {e.score:>8.3f} sat={list(e.satisfies)} "
                             f"str={list(e.structural_for)} disc={list(e.discovered_for)} {e.citation[:64]}")
            if len(reg.evidence) > 10:
                lines.append(f"    ... {len(reg.evidence) - 10} more")
            lines.append(f"  results -> {[r.citation.label[:30] for r in resp.results]}")
            for n in resp.notes:
                lines.append(f"  note: {n[:120]}")
    finally:
        db.close()
    text = "\n".join(lines)
    print(text)
    out_path = Path(__file__).resolve().parent / "results" / "stage2_retrieval_check.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
