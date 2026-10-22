"""ContextPolicy.general_evidence_order="ecfr_discovery_first_guidance_floor" (retrieval repair D, experiment 2;
OFF by default).

For a question that names no provision, docket or guidance, the default "tier" order is kept except within the
discovery tier: the highest-ranked guidance passage competes first, then every eCFR passage (the section-coverage rows
the registry puts last), then the remaining guidance. Experiment 1 (eCFR first, no floor) lost the top-ranked guidance
passage in all four of its regressions. No database, no model: TableDatabase stands in.
"""

import pytest

from regulus.planning import plan_query
from regulus.rag.context import ContextPolicy
from regulus.rag.selection import _optional_order, select_evidence
from regulus.retrieval.evidence import TIER_DISCOVERY, TIER_STRUCTURAL, TIER_SUPPORTING
from regulus.retrieval.query import QueryType
from tests.test_retrieval_plan import TableDatabase
from tests.test_retrieval_section_coverage import COVERAGE, UI12, coverage_row, guidance, run

ON = ContextPolicy(general_evidence_order="ecfr_discovery_first_guidance_floor")

# The answering paragraphs at production length: together longer than the 1,200-char eCFR reserve (as 71.6(c)(1),
# 818 chars, and 70.55, 790, in COS-70.55-Q1), so only the first fits the reserve.
LONG_COVERAGE = [coverage_row("11.10", "(c)", 3, 1.4, 0.5, body_text="(c) Protection of records to enable their accurate "
                              "and ready retrieval throughout the records retention period. " + "r" * 650),
                 coverage_row("11.10", "(b)", 2, 1.4, 0.4, body_text="(b) The ability to generate accurate and complete "
                              "copies of records in both human readable and electronic form. " + "c" * 650)]


def _or_crowded_registry(n_guidance=8, coverage=LONG_COVERAGE):
    """Production shape: no passage matched every word; section coverage found the answering paragraphs (discovery,
    placed last); the guidance OR fallback found n long chunks (discovery, in score order)."""
    db = TableDatabase(coverage=coverage, or_guidance=[guidance(i, rank=0.9 - i * 0.05) for i in range(n_guidance)])
    return run(UI12, db).registry


def _labels(sel):
    return [s.evidence.citation for s in sel.selected]


def _same_selection(a, b):
    """The same evidence selected (same text, same order) and dropped, whatever the policy is called."""
    return ([(s.evidence.evidence_id, s.text, s.index) for s in a.selected] == [(s.evidence.evidence_id, s.text, s.index) for s in b.selected]
            and [(d.evidence.evidence_id, d.reason) for d in a.dropped] == [(d.evidence.evidence_id, d.reason) for d in b.dropped])


def _top_guidance(reg):
    return next(e for e in reg.evidence if e.tier == TIER_DISCOVERY and e.result.corpus != "ecfr")


def test_the_default_policy_and_its_fingerprint_are_unchanged():
    assert ContextPolicy().general_evidence_order == "tier"
    assert "general_evidence_order" not in ContextPolicy().to_dict()
    assert ON.to_dict()["general_evidence_order"] == "ecfr_discovery_first_guidance_floor"
    with pytest.raises(ValueError):
        ContextPolicy(general_evidence_order="ecfr_discovery_first")      # experiment 1's mode is not available


def test_the_registry_has_the_production_shape():
    reg = _or_crowded_registry()
    discovery = [e for e in reg.evidence if e.tier == TIER_DISCOVERY]
    corpora = [e.result.corpus for e in discovery]
    assert corpora.count("fda_guidance") == 8 and corpora[-2:] == ["ecfr", "ecfr"]
    scores = [e.score for e in discovery if e.result.corpus != "ecfr"]
    assert scores == sorted(scores, reverse=True)                         # guidance discovery in score order


def test_default_order_is_unchanged():
    reg = _or_crowded_registry()
    previous = [e for tier in (TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY) for e in reg.evidence if e.tier == tier]
    assert _optional_order(reg, False) == previous == _optional_order(reg, False, False)


def test_by_default_a_coverage_row_beyond_the_reserve_is_crowded_out():
    sel = select_evidence(_or_crowded_registry(), ContextPolicy())
    assert sum(1 for c in _labels(sel) if c.startswith("21 CFR")) < 2
    assert any(d.evidence.citation.startswith("21 CFR 11.10") and d.reason == "soft_budget" for d in sel.dropped)


def test_the_floor_orders_top_guidance_then_ecfr_then_the_rest_of_the_discovery_tier():
    reg = _or_crowded_registry()
    order, default = _optional_order(reg, False, True), _optional_order(reg, False)
    assert sorted(e.evidence_id for e in order) == sorted(e.evidence_id for e in default)   # nothing added or removed
    head = [e for e in default if e.tier != TIER_DISCOVERY]
    assert order[:len(head)] == head                                                         # structural, supporting untouched
    disc = order[len(head):]
    guidance = [e for e in default if e.tier == TIER_DISCOVERY and e.result.corpus != "ecfr"]
    ecfr = [e for e in default if e.tier == TIER_DISCOVERY and e.result.corpus == "ecfr"]
    assert disc == guidance[:1] + ecfr + guidance[1:]


def test_the_floor_keeps_the_top_ranked_guidance_and_the_regulatory_rows_within_the_same_limits():
    reg = _or_crowded_registry()
    sel = select_evidence(reg, ON)
    assert _top_guidance(reg).evidence_id in {s.evidence.evidence_id for s in sel.selected}
    assert {"21 CFR 11.10(c)", "21 CFR 11.10(b)"} <= set(_labels(sel))
    assert len(sel.selected) <= ON.max_results and sel.total_chars <= ON.max_total_chars
    assert sel.diagnostics["general_evidence_order"] == "ecfr_discovery_first_guidance_floor"
    assert sel.diagnostics.get("binding_reserved")                                          # the RC2 reserve still applies
    position = {e.evidence_id: i for i, e in enumerate(reg.evidence)}                        # presented in registry order
    assert [position[s.evidence.evidence_id] for s in sel.selected] == sorted(position[s.evidence.evidence_id] for s in sel.selected)
    assert [s.index for s in sel.selected] == list(range(1, len(sel.selected) + 1))
    assert sel.total_chars == sum(s.chars for s in sel.selected) + 2 * (len(sel.selected) - 1)


def test_only_one_guidance_passage_is_floored():
    reg = _or_crowded_registry()
    order = _optional_order(reg, False, True)
    disc = [e for e in order if e.tier == TIER_DISCOVERY]
    first_ecfr = next(i for i, e in enumerate(disc) if e.result.corpus == "ecfr")
    assert [e.result.corpus for e in disc[:first_ecfr]] == ["fda_guidance"]


def test_without_discovery_guidance_the_floor_is_empty():
    db = TableDatabase(coverage=LONG_COVERAGE)
    reg = run(UI12, db).registry
    assert not any(e.result.corpus != "ecfr" and e.tier == TIER_DISCOVERY for e in reg.evidence)
    assert _optional_order(reg, False, True) == _optional_order(reg, False)


def test_guidance_that_matched_every_word_keeps_its_place():
    db = TableDatabase(coverage=COVERAGE, guidance=[guidance(i) for i in range(3)])
    reg = run(UI12, db).registry
    supporting_guidance = [e for e in reg.evidence if e.tier == TIER_SUPPORTING and e.result.corpus == "fda_guidance"]
    assert supporting_guidance and _optional_order(reg, False, True)[:len(supporting_guidance)] == supporting_guidance
    assert _same_selection(select_evidence(reg, ON), select_evidence(reg, ContextPolicy()))


def test_the_usefulness_filter_still_applies_to_the_floored_passage():
    reg = _or_crowded_registry()
    sel = select_evidence(reg, ON, optional_filter=lambda r: r.corpus != "fda_guidance")
    assert not any(s.evidence.result.corpus == "fda_guidance" for s in sel.selected)
    assert any(d.evidence.evidence_id == _top_guidance(reg).evidence_id and d.reason == "filtered" for d in sel.dropped)


def test_a_question_that_names_a_provision_is_not_affected():
    db = TableDatabase(or_guidance=[guidance(i) for i in range(3)])
    reg = run("What does 21 CFR 820.10 require for the quality management system?", db).registry
    assert reg.plan.requirements
    assert _same_selection(select_evidence(reg, ON), select_evidence(reg, ContextPolicy()))


def test_a_guidance_question_is_not_affected():
    q = "What does FDA guidance recommend for protecting and retaining electronic records?"
    assert plan_query(q).query_type is QueryType.GUIDANCE_SEARCH
    db = TableDatabase(coverage=LONG_COVERAGE, or_guidance=[guidance(i) for i in range(8)])
    reg = run(q, db).registry
    assert _same_selection(select_evidence(reg, ON), select_evidence(reg, ContextPolicy()))
