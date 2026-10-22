"""ContextPolicy.general_evidence_order="ecfr_discovery_first" (retrieval repair D).

For a question that names no provision, docket or guidance, the default "tier" order is kept, except that within the
discovery tier every eCFR passage competes for the soft budget before every guidance passage. The section-coverage rows
are discovery evidence the registry puts last, so without this the broad OR-fallback guidance chunks (discovery,
~1,500 chars each) spend the budget before them (COS-70.55-Q1, 71.15-Q2, 701.3-Q1). Guidance that matched every
question word (supporting) keeps its place, and guidance still fills whatever budget the eCFR leaves.
No database, no model: TableDatabase stands in.
"""

import pytest

from regulus.planning import plan_query
from regulus.rag.context import ContextPolicy
from regulus.rag.selection import _optional_order, select_evidence
from regulus.retrieval.evidence import TIER_DISCOVERY, TIER_STRUCTURAL, TIER_SUPPORTING
from regulus.retrieval.query import QueryType
from tests.test_retrieval_plan import TableDatabase
from tests.test_retrieval_section_coverage import COVERAGE, UI12, coverage_row, guidance, run

ON = ContextPolicy(general_evidence_order="ecfr_discovery_first")


# The answering paragraphs at production length: together longer than the 1,200-char eCFR reserve, as 71.6(c)(1)
# (818 chars) and 70.55 (790) were in COS-70.55-Q1, so only the first fits the reserve.
LONG_COVERAGE = [coverage_row("11.10", "(c)", 3, 1.4, 0.5, body_text="(c) Protection of records to enable their accurate "
                              "and ready retrieval throughout the records retention period. " + "r" * 650),
                 coverage_row("11.10", "(b)", 2, 1.4, 0.4, body_text="(b) The ability to generate accurate and complete "
                              "copies of records in both human readable and electronic form. " + "c" * 650)]


def _or_crowded_registry(n_guidance=8, coverage=LONG_COVERAGE):
    """The production shape: no passage matched every word, section coverage found the answering paragraphs
    (discovery, moved behind everything) and the guidance OR fallback found n long chunks (discovery)."""
    db = TableDatabase(coverage=coverage, or_guidance=[guidance(i) for i in range(n_guidance)])
    return run(UI12, db).registry


def _labels(sel):
    return [s.evidence.citation for s in sel.selected]


def _same_selection(a, b):
    """The same evidence selected (with the same text and order) and dropped, whatever the policy is called."""
    return ([(s.evidence.evidence_id, s.text, s.index) for s in a.selected] == [(s.evidence.evidence_id, s.text, s.index) for s in b.selected]
            and [(d.evidence.evidence_id, d.reason) for d in a.dropped] == [(d.evidence.evidence_id, d.reason) for d in b.dropped])


def test_the_default_policy_and_its_fingerprint_are_unchanged():
    assert ContextPolicy().general_evidence_order == "tier"
    assert "general_evidence_order" not in ContextPolicy().to_dict()
    assert ON.to_dict()["general_evidence_order"] == "ecfr_discovery_first"
    with pytest.raises(ValueError):
        ContextPolicy(general_evidence_order="ecfr_first")


def test_the_registry_has_the_production_shape():
    reg = _or_crowded_registry()
    discovery = [e for e in reg.evidence if e.tier == TIER_DISCOVERY]
    corpora = [e.result.corpus for e in discovery]
    assert corpora.count("fda_guidance") == 8 and corpora.count("ecfr") == 2
    assert corpora[-2:] == ["ecfr", "ecfr"]                                     # coverage rows placed last


def test_default_order_is_unchanged():
    reg = _or_crowded_registry()
    previous = [e for tier in (TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY) for e in reg.evidence if e.tier == tier]
    assert _optional_order(reg, False) == previous
    assert _optional_order(reg, False, False) == previous


def test_by_default_a_coverage_row_beyond_the_reserve_is_crowded_out_by_or_guidance():
    sel = select_evidence(_or_crowded_registry(), ContextPolicy())
    dropped = {d.evidence.citation: d.reason for d in sel.dropped}
    assert sum(1 for c in _labels(sel) if c.startswith("21 CFR")) < 2
    assert any(c.startswith("21 CFR 11.10") and why == "soft_budget" for c, why in dropped.items())


def test_ecfr_discovery_first_keeps_the_regulatory_rows_within_the_same_limits():
    reg = _or_crowded_registry()
    sel = select_evidence(reg, ON)
    assert {"21 CFR 11.10(c)", "21 CFR 11.10(b)"} <= set(_labels(sel))
    assert len(sel.selected) <= ON.max_results and sel.total_chars <= ON.max_total_chars
    assert sel.diagnostics["general_evidence_order"] == "ecfr_discovery_first"
    assert sel.diagnostics.get("binding_reserved")                               # the RC2 reserve still applies
    position = {e.evidence_id: i for i, e in enumerate(reg.evidence)}             # presented in registry order
    assert [position[s.evidence.evidence_id] for s in sel.selected] == sorted(position[s.evidence.evidence_id] for s in sel.selected)
    assert [s.index for s in sel.selected] == list(range(1, len(sel.selected) + 1))
    assert sel.total_chars == sum(s.chars for s in sel.selected) + 2 * (len(sel.selected) - 1)


def test_guidance_still_fills_the_budget_the_ecfr_leaves():
    sel = select_evidence(_or_crowded_registry(), ON)
    assert any(s.evidence.result.corpus == "fda_guidance" for s in sel.selected)


def test_only_the_discovery_tier_is_reordered():
    reg = _or_crowded_registry()
    order = _optional_order(reg, False, True)
    default = _optional_order(reg, False)
    assert set(e.evidence_id for e in order) == set(e.evidence_id for e in default)    # nothing added or removed
    head = [e for e in default if e.tier != TIER_DISCOVERY]
    assert order[:len(head)] == head                                              # structural, supporting untouched
    disc = order[len(head):]
    n_ecfr = sum(1 for e in disc if e.result.corpus == "ecfr")
    assert all(e.result.corpus == "ecfr" for e in disc[:n_ecfr])
    assert [e for e in disc if e.result.corpus != "ecfr"] == [e for e in default if e.tier == TIER_DISCOVERY and e.result.corpus != "ecfr"]


def test_guidance_that_matched_every_word_keeps_its_place_ahead_of_discovery_ecfr():
    # AND-matched guidance (supporting) plus the coverage rows (discovery): supporting guidance still comes first
    db = TableDatabase(coverage=COVERAGE, guidance=[guidance(i) for i in range(3)])
    reg = run(UI12, db).registry
    order = _optional_order(reg, False, True)
    supporting_guidance = [e for e in reg.evidence if e.tier == TIER_SUPPORTING and e.result.corpus == "fda_guidance"]
    assert supporting_guidance and order[:len(supporting_guidance)] == supporting_guidance
    assert _same_selection(select_evidence(reg, ON), select_evidence(reg, ContextPolicy()))


def test_the_usefulness_filter_still_applies():
    sel = select_evidence(_or_crowded_registry(), ON, optional_filter=lambda r: r.corpus != "fda_guidance")
    assert not any(s.evidence.result.corpus == "fda_guidance" for s in sel.selected)
    assert any(d.reason == "filtered" for d in sel.dropped)


def test_a_question_that_names_a_provision_is_not_affected():
    db = TableDatabase(or_guidance=[guidance(i) for i in range(3)])
    reg = run("What does 21 CFR 820.10 require for the quality management system?", db).registry
    assert reg.plan.requirements
    assert _same_selection(select_evidence(reg, ON), select_evidence(reg, ContextPolicy()))


def test_a_guidance_question_is_not_affected():
    q = "What does FDA guidance recommend for protecting and retaining electronic records?"
    assert plan_query(q).query_type is QueryType.GUIDANCE_SEARCH
    db = TableDatabase(coverage=COVERAGE, or_guidance=[guidance(i) for i in range(8)])
    reg = run(q, db).registry
    assert _same_selection(select_evidence(reg, ON), select_evidence(reg, ContextPolicy()))
