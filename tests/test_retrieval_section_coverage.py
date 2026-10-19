"""RC1 (section-coverage candidates) and RC2 (binding-text reserve) for questions that name no provision.

The in-memory TableDatabase from test_retrieval_plan stands in for PostgreSQL; ECFR_SECTION_COVERAGE
answers from canned rows, so these tests exercise when the leg runs and what happens to its rows,
not the SQL (tests/integration/test_section_coverage_live.py checks the SQL against the database).
"""

import pytest

from regulus.planning import plan_query
from regulus.rag.context import ContextPolicy
from regulus.rag.selection import select_evidence
from regulus.retrieval import LexicalRetriever
from regulus.retrieval.domain import DomainVocabulary, ScopePolicy
from regulus.retrieval.evidence import TIER_DISCOVERY
from regulus.retrieval.query import QueryType, content_terms, fallback_terms
from tests.test_retrieval_plan import TableDatabase, guidance_row, row

UI12 = ("What requirements apply to protecting and retaining electronic records so they remain accurate, "
        "accessible, and readable throughout the required retention period?")
LONG = "x" * 1500  # a guidance chunk longer than the per-source cap, as most are


def coverage_row(section, para, ordinal, section_score, row_score, **over):
    return row(section, para, ordinal, section_score=section_score, row_score=row_score, **over)


def guidance(i, **over):
    fields = {"source_url": f"https://www.fda.gov/media/{i}.pdf", "body_text": LONG, "rank": 0.9,
              "docket": f"FDA-2020-D-{1000 + i}", **over}
    return guidance_row(ordinal=i, **fields)


COVERAGE = [coverage_row("11.10", "(c)", 3, 1.4, 0.5, body_text="(c) Protection of records to enable their accurate "
                         "and ready retrieval throughout the records retention period."),
            coverage_row("11.10", "(b)", 2, 1.4, 0.4, body_text="(b) The ability to generate accurate and complete "
                         "copies of records in both human readable and electronic form.")]


def run(question, db, **kw):
    return LexicalRetriever(db, **kw).run_plan(plan_query(question), top_k=8)


def keys(items):
    return [getattr(i, "key", None) or i.evidence.key for i in items]


# ----------------------------------------------------------------- RC1: candidates


def test_no_identifier_question_without_eCFR_AND_hits_gets_section_coverage_candidates():
    db = TableDatabase(coverage=COVERAGE, or_ecfr=[row("876.5540", "(a)", 1, rank=0.9)])
    out = run(UI12, db)
    assert "ECFR_SECTION_COVERAGE" in db.names()
    got = [r.citation.label for r in out.response.results]
    assert "21 CFR 11.10(c)" in got and "21 CFR 11.10(b)" in got
    cov = [e for e in out.registry.evidence if e.result.metadata.get("section_coverage") is not None]
    assert cov and all(e.tier == TIER_DISCOVERY for e in cov)
    assert out.response.diagnostics["section_coverage"] == {"run": True, "candidates": 2, "kept": 2}


def test_section_coverage_rows_follow_the_existing_ranking():
    """A secondary source: it adds candidates, it does not reorder what the other methods found."""
    db = TableDatabase(coverage=COVERAGE, or_guidance=[guidance(1, rank=0.001)])
    results = run(UI12, db).response.results
    assert results[0].corpus == "fda_guidance"  # scored far below any coverage row, still ahead of them
    assert [r.citation.label for r in results[1:3]] == ["21 CFR 11.10(c)", "21 CFR 11.10(b)"]


def test_section_coverage_replaces_the_eCFR_OR_query_only_when_it_found_something():
    db = TableDatabase(coverage=COVERAGE, or_ecfr=[row("876.5540", "(a)", 1, rank=0.9)])
    out = run(UI12, db)
    ecfr_or = [p for n, p in db.calls if n == "ECFR_FULL_TEXT" and " or " in p["query"]]
    assert not ecfr_or and "21 CFR 876.5540(a)" not in [r.citation.label for r in out.response.results]
    assert any(n == "GUIDANCE_FULL_TEXT" and " or " in p["query"] for n, p in db.calls)  # guidance OR unchanged
    assert out.response.diagnostics["fallback_used"] is True  # as without the leg: the scope policy reads it
    db = TableDatabase(coverage=[], or_ecfr=[row("876.5540", "(a)", 1, rank=0.9)])
    out = run(UI12, db)
    assert "21 CFR 876.5540(a)" in [r.citation.label for r in out.response.results]


def test_many_weak_matches_cannot_push_section_coverage_out_of_the_candidates():
    db = TableDatabase(coverage=COVERAGE, or_guidance=[guidance(i) for i in range(12)],
                       or_ecfr=[row(f"1.{i}", "(a)", 1, rank=0.9) for i in range(12)])
    results = run(UI12, db).response.results
    assert len(results) <= 8
    assert {"21 CFR 11.10(c)", "21 CFR 11.10(b)"} <= {r.citation.label for r in results}


def test_section_coverage_is_skipped_when_AND_found_binding_text_and_when_disabled():
    hits = [row(f"801.{i}", "", 0, rank=0.5) for i in range(1, 5)]
    db = TableDatabase(full_text=hits, coverage=COVERAGE)
    run("labeling requirements for prescription drugs", db)
    assert "ECFR_SECTION_COVERAGE" not in db.names()
    db = TableDatabase(coverage=COVERAGE)
    run(UI12, db, section_coverage=False)
    assert "ECFR_SECTION_COVERAGE" not in db.names()


def test_section_coverage_searches_every_content_word_including_the_head_noun():
    """The OR fallback keeps the 8 longest words and drops "records"; the coverage leg keeps every content
    word and lets the corpus weight them. fallback_terms itself is unchanged: part-level ranking uses it."""
    assert "records" not in fallback_terms(UI12)
    assert fallback_terms(UI12) == ["protecting", "electronic", "accessible", "throughout", "retaining",
                                    "retention", "accurate", "readable"]
    assert content_terms(UI12) == ["protecting", "retaining", "electronic", "records", "remain", "accurate",
                                   "accessible", "readable", "throughout", "retention", "period"]
    db = TableDatabase(coverage=COVERAGE)
    run(UI12, db)
    (params,) = [p for n, p in db.calls if n == "ECFR_SECTION_COVERAGE"]
    assert "records" in params["query"].split()


def test_a_section_spread_over_paragraphs_contributes_several_rows_with_one_section_score():
    db = TableDatabase(coverage=COVERAGE)
    out = run(UI12, db)
    (params,) = [p for n, p in db.calls if n == "ECFR_SECTION_COVERAGE"]
    assert params["rows_per_section"] == 2 and params["limit"] == 4  # half of top_k
    rows = [r for r in out.response.results if r.metadata.get("section") == "11.10"]
    assert len(rows) == 2 and len({r.metadata["section_coverage"] for r in rows}) == 1


# --------------------------------------------------------------- explicit identifiers


def test_explicit_identifier_question_never_runs_section_coverage_and_selects_as_before():
    db = TableDatabase(coverage=COVERAGE, guidance=[guidance(i) for i in range(3)])
    out = run("What does 21 CFR 820.10 require?", db)
    assert "ECFR_SECTION_COVERAGE" not in db.names()
    on = select_evidence(out.registry, ContextPolicy()).to_dict()
    off = select_evidence(out.registry, ContextPolicy(binding_reserve_chars=0)).to_dict()
    on.pop("policy"), off.pop("policy")  # differs only by the reserve setting itself
    assert on == off


# --------------------------------------------------------------------- RC2: context


def _general_registry():
    db = TableDatabase(coverage=COVERAGE, guidance=[guidance(i) for i in range(3)])
    return run(UI12, db).registry


def test_binding_text_is_not_displaced_by_guidance_chunks():
    reg = _general_registry()
    before = select_evidence(reg, ContextPolicy(binding_reserve_chars=0))
    assert not any(s.evidence.result.corpus == "ecfr" for s in before.selected)  # the forensic finding
    after = select_evidence(reg, ContextPolicy())
    assert "21 CFR 11.10(c)" in [s.evidence.citation for s in after.selected]
    assert any(s.evidence.result.corpus == "fda_guidance" for s in after.selected)  # guidance still there
    assert after.total_chars <= ContextPolicy().max_total_chars
    assert after.diagnostics["binding_reserved"]


def test_reserved_sources_are_presented_in_registry_order():
    reg = _general_registry()
    sel = select_evidence(reg, ContextPolicy())
    position = {e.evidence_id: i for i, e in enumerate(reg.evidence)}
    assert [s.index for s in sel.selected] == list(range(1, len(sel.selected) + 1))
    assert [position[s.evidence.evidence_id] for s in sel.selected] == sorted(position[s.evidence.evidence_id]
                                                                              for s in sel.selected)
    assert sel.total_chars == sum(s.chars for s in sel.selected) + 2 * (len(sel.selected) - 1)


def test_guidance_question_keeps_guidance_first():
    q = "What does FDA guidance recommend for protecting and retaining electronic records?"
    assert plan_query(q).query_type is QueryType.GUIDANCE_SEARCH
    db = TableDatabase(coverage=COVERAGE, guidance=[guidance(i) for i in range(3)])
    reg = run(q, db).registry
    on = select_evidence(reg, ContextPolicy())
    off = select_evidence(reg, ContextPolicy(binding_reserve_chars=0))
    assert on.to_dict()["selected"] == off.to_dict()["selected"]
    assert on.selected and all(s.evidence.result.corpus == "fda_guidance" for s in on.selected)


def test_reserve_must_not_be_negative():
    with pytest.raises(ValueError):
        ContextPolicy(binding_reserve_chars=-1)


# ------------------------------------------------------------------------ scope


@pytest.mark.parametrize("question, kwargs", [
    (UI12, {"guidance": [guidance(i) for i in range(3)]}),  # AND matched guidance only: in scope
    ("What is the capital of France?", {}),                  # nothing matched: general knowledge
])
def test_scope_decision_is_unchanged_by_section_coverage(question, kwargs):
    policy = ScopePolicy(DomainVocabulary(["records", "electronic"]))
    decisions = []
    for enabled in (False, True):
        out = run(question, TableDatabase(coverage=COVERAGE, **kwargs), section_coverage=enabled)
        resp = out.response
        decisions.append((policy.decide(question, out.plan, resp.diagnostics, results=bool(resp.results)).status,
                          resp.diagnostics["fallback_used"]))
    assert decisions[0] == decisions[1]
