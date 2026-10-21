"""Stage 7 controlled OR fallback: term selection, trigger, bounds,
determinism, preservation of exact/section/filter behaviour, diagnostics.
Uses the FakeDatabase; no PostgreSQL."""

import pytest

from regulus.retrieval import LexicalRetriever
from regulus.retrieval.base import Filters
from regulus.retrieval.models import METHOD_EXACT_CFR, METHOD_FULL_TEXT, METHOD_FULL_TEXT_OR, METHOD_TRIGRAM
from regulus.retrieval.query import fallback_terms
from regulus.retrieval.ranking import FULL_TEXT_OR_SCALE, FULL_TEXT_SCALE, METHOD_PRIORITY, full_text_or_score
from tests.test_retrieval_lexical import FakeDatabase, ecfr_row, guidance_row

LONG_Q = "Explain to someone with no medical background why a new drug must be approved before it can be sold."


class RoutingFakeDatabase(FakeDatabase):
    """Like FakeDatabase but can answer the OR query differently from the AND query."""

    def __init__(self, responses, or_responses=None):
        super().__init__(responses)
        self.or_responses = or_responses or {}

    def query(self, sql, params=None):
        import regulus.retrieval.sql as sql_module

        name = next(n for n, s in sql_module.ALL_STATEMENTS.items() if s == sql)
        self.calls.append((name, dict(params or {})))
        if " or " in str((params or {}).get("query", "")):
            return [dict(r) for r in self.or_responses.get(name, [])]
        return [dict(r) for r in self.responses.get(name, [])]


def _or_calls(fake):
    return [(n, p) for n, p in fake.calls if " or " in str(p.get("query", ""))]


# ------------------------------------------------------------ term selection


def test_fallback_terms_drop_question_and_generic_words_keep_content():
    terms = fallback_terms(LONG_Q)
    assert "approved" in terms and "medical" in terms and "sold" in terms
    for junk in ("explain", "someone", "background", "why", "new", "drug", "must", "before", "can"):
        assert junk not in terms


def test_fallback_terms_preserve_identifiers_and_phrases():
    assert fallback_terms("What does 21 CFR 820.10 cover?") == ["820.10"]
    assert fallback_terms('requirements for "design controls" under part 820') == ['"design controls"', "820"]
    assert fallback_terms("what is a 510(k) submission") == ["submission", "510"]
    assert fallback_terms("Summarize the main recommendations of FDA guidance document FDA-2023-D-99999.") == ["fda-2023-d-99999"]
    assert fallback_terms("in 2024 the rule changed") == ["changed", "2024"]  # longest first; bare '21'-style numbers need 3+ chars
    assert fallback_terms("in 21 the rule changed") == ["changed"]


def test_fallback_terms_are_bounded_deterministic_and_longest_first():
    q = "tamper-evident packaging labeling nutrition supplements ingredients allergens warnings storage temperature humidity"
    a = fallback_terms(q, max_terms=4)
    b = fallback_terms(q, max_terms=4)
    assert a == b and len(a) == 4
    assert a == sorted(a, key=lambda t: -len(t)) or len({len(t) for t in a}) < 4
    assert fallback_terms("", 8) == [] and fallback_terms(q, 0) == []
    assert fallback_terms("What is the CFR?") == []  # nothing usable -> no fallback query


# ------------------------------------------------------------------ trigger


def test_no_fallback_when_primary_is_sufficient():
    fake = RoutingFakeDatabase({"ECFR_FULL_TEXT": [ecfr_row(section=f"1.{i}", para="", ordinal=0, rank=0.2) for i in range(3)]})
    resp = LexicalRetriever(fake).run("tamper-evident packaging requirements", corpus="ecfr")
    assert not _or_calls(fake)
    d = resp.diagnostics
    assert d["primary_result_count"] == 3 and d["fallback_used"] is False and d["retrieval_mode"] == "primary"
    assert d["fallback_terms"] == [] and d["fallback_candidate_count"] == 0


def test_fallback_activates_on_zero_primary_results_and_is_diagnosed():
    fake = RoutingFakeDatabase({}, {"ECFR_FULL_TEXT": [ecfr_row(section="314.50", para="(a)", ordinal=1, rank=0.3)], "GUIDANCE_FULL_TEXT": [guidance_row(rank=0.2)]})
    resp = LexicalRetriever(fake).run(LONG_Q, top_k=5)
    or_calls = _or_calls(fake)
    assert [n for n, _ in or_calls] == ["ECFR_FULL_TEXT", "GUIDANCE_FULL_TEXT"]
    assert or_calls[0][1]["query"] == " or ".join(fallback_terms(LONG_Q))
    d = resp.diagnostics
    assert d["primary_result_count"] == 0 and d["fallback_used"] is True and d["retrieval_mode"] == "fallback"
    assert d["fallback_candidate_count"] == 2 and d["final_result_count"] == 2 and d["fallback_terms"]
    assert {r.retrieval_method for r in resp.results} == {METHOD_FULL_TEXT_OR}
    n_terms = len(fallback_terms(LONG_Q))
    assert resp.results[0].relevance_score == pytest.approx(FULL_TEXT_OR_SCALE * 0.3 / n_terms)
    assert resp.results[0].metadata["or_query"] == or_calls[0][1]["query"]


def test_fallback_activates_below_configurable_minimum_only():
    two = [ecfr_row(section=f"1.{i}", para="", ordinal=0, rank=0.2) for i in range(2)]
    fake = RoutingFakeDatabase({"ECFR_FULL_TEXT": two}, {"ECFR_FULL_TEXT": [ecfr_row(section="9.9", para="", ordinal=0, rank=0.1)]})
    resp = LexicalRetriever(fake, primary_min_results=3).run("packaging labeling storage", corpus="ecfr")
    assert resp.diagnostics["fallback_used"] and resp.diagnostics["primary_result_count"] == 2
    fake = RoutingFakeDatabase({"ECFR_FULL_TEXT": two})
    resp = LexicalRetriever(fake, primary_min_results=2).run("packaging labeling storage", corpus="ecfr")
    assert not resp.diagnostics["fallback_used"]
    fake = RoutingFakeDatabase({})
    resp = LexicalRetriever(fake, enable_or_fallback=False).run(LONG_Q)
    assert not _or_calls(fake) and resp.diagnostics["fallback_used"] is False and resp.diagnostics["retrieval_mode"] == "none"


def test_fallback_is_bounded_by_top_k_per_corpus():
    many = [ecfr_row(section=f"1.{i}", para="", ordinal=0, rank=0.5 - i * 0.01) for i in range(40)]
    fake = RoutingFakeDatabase({}, {"ECFR_FULL_TEXT": many})
    resp = LexicalRetriever(fake).run(LONG_Q, corpus="ecfr", top_k=5)
    or_call = _or_calls(fake)[0][1]
    assert or_call["limit"] == 5  # bound requested from the database
    assert len(resp.results) == 5


def test_fallback_is_deterministic():
    rows = [ecfr_row(section=f"1.{i}", para="", ordinal=0, rank=0.2) for i in range(6)]
    fake = RoutingFakeDatabase({}, {"ECFR_FULL_TEXT": rows})
    r = LexicalRetriever(fake)
    a = [x.key for x in r.run(LONG_Q, corpus="ecfr").results]
    b = [x.key for x in r.run(LONG_Q, corpus="ecfr").results]
    assert a == b


# --------------------------------------------------------- preservation


def test_exact_cfr_lookup_unchanged_and_never_triggers_fallback_when_found():
    fake = RoutingFakeDatabase({"ECFR_EXACT_SECTION": [ecfr_row(para="", ordinal=0, match_kind="exact"), ecfr_row(para="(a)", ordinal=1, match_kind="exact"), ecfr_row(para="(b)", ordinal=2, match_kind="exact")]})
    resp = LexicalRetriever(fake).run("21 CFR 820.10", corpus="ecfr")
    assert not _or_calls(fake)
    assert resp.diagnostics["retrieval_mode"] == "exact" and resp.diagnostics["primary_result_count"] == 3
    assert [r.citation.label for r in resp.results[:3]] == ["21 CFR 820.10", "21 CFR 820.10(a)", "21 CFR 820.10(b)"]
    assert all(r.retrieval_method == METHOD_EXACT_CFR for r in resp.results[:3])


def test_paragraph_lookup_unchanged():
    fake = RoutingFakeDatabase({"ECFR_EXACT_SECTION": [ecfr_row(para="(b)", ordinal=2, match_kind="exact"), ecfr_row(para="(b)(1)", ordinal=3, match_kind="descendant")]}, {"ECFR_FULL_TEXT": [ecfr_row(section="9.9", para="", ordinal=0, rank=0.9)]})
    # two content words + the identifier -> a multi-term OR query the fake can recognise
    resp = LexicalRetriever(fake).run("Explain 21 CFR 820.10(b) traceability identification", corpus="ecfr")
    exact = next(p for n, p in fake.calls if n == "ECFR_EXACT_SECTION")
    assert exact["paragraph"] == "(b)" and exact["paragraph_prefix"] == "(b)(%"
    # primary count is 2 (< 3) so fallback runs, but exact rows stay on top with score 100/95
    assert resp.results[0].citation.label == "21 CFR 820.10(b)" and resp.results[0].relevance_score == pytest.approx(100.0, abs=0.01)
    assert resp.results[1].metadata["match_kind"] == "descendant"
    assert resp.results[-1].retrieval_method == METHOD_FULL_TEXT_OR and resp.results[-1].relevance_score < 95


def test_filters_are_passed_to_fallback_queries():
    fake = RoutingFakeDatabase({}, {"ECFR_FULL_TEXT": [], "GUIDANCE_FULL_TEXT": []})
    LexicalRetriever(fake).run(LONG_Q, filters=Filters(part="820", sector="device", status="final"))
    for name, params in _or_calls(fake):
        if name == "ECFR_FULL_TEXT":
            assert params["part"] == "820" and params["section"] is None
        else:
            assert params["sector"] == "device" and params["status"] == "final" and params["retrievable"] is True


def test_corpus_restriction_applies_to_fallback():
    fake = RoutingFakeDatabase({}, {"ECFR_FULL_TEXT": [], "GUIDANCE_FULL_TEXT": []})
    LexicalRetriever(fake).run(LONG_Q, corpus="fda_guidance")
    assert [n for n, _ in _or_calls(fake)] == ["GUIDANCE_FULL_TEXT"]


def test_negative_control_reference_yields_tiny_or_query_not_broad_retrieval():
    """'21 CFR 820.30(b)(1)' has no live record; the fallback may run but only
    with the identifier itself, never with generic words like 'cfr'."""
    fake = RoutingFakeDatabase({}, {"ECFR_FULL_TEXT": [], "GUIDANCE_FULL_TEXT": []})
    resp = LexicalRetriever(fake).run("21 CFR 820.30(b)(1)")
    assert resp.diagnostics["fallback_terms"] == ["820.30"]
    assert not any(r.retrieval_method == METHOD_EXACT_CFR for r in resp.results)
    assert resp.notes and "820.30(b)(1)" in resp.notes[0]


def test_fallback_never_outranks_primary_hits_and_merge_prefers_primary_method():
    primary = [ecfr_row(section="1.1", para="", ordinal=0, rank=0.2)]  # one primary hit -> fallback runs
    fallback = [ecfr_row(section="1.1", para="", ordinal=0, rank=0.9), ecfr_row(section="2.2", para="", ordinal=0, rank=0.9)]
    fake = RoutingFakeDatabase({"ECFR_FULL_TEXT": primary}, {"ECFR_FULL_TEXT": fallback})
    resp = LexicalRetriever(fake).run("packaging labeling storage", corpus="ecfr")
    first = resp.results[0]
    assert first.citation.section == "2.2" or first.citation.section == "1.1"
    dup = next(r for r in resp.results if r.citation.section == "1.1")
    assert dup.retrieval_method == METHOD_FULL_TEXT and set(dup.methods) == {METHOD_FULL_TEXT, METHOD_FULL_TEXT_OR}
    assert METHOD_PRIORITY[METHOD_FULL_TEXT] > METHOD_PRIORITY[METHOD_FULL_TEXT_OR]
    assert full_text_or_score(0.5, 1) == 2.5 and full_text_or_score(3.0, 8) == pytest.approx(1.875)
    assert FULL_TEXT_OR_SCALE < FULL_TEXT_SCALE / 5  # fallback band sits far below primary full-text


def test_trigram_only_hits_do_not_count_as_primary():
    fake = RoutingFakeDatabase({"ECFR_TRIGRAM": [ecfr_row(section="820.3", para="", ordinal=0, sim=0.6)]}, {"ECFR_FULL_TEXT": []})
    resp = LexicalRetriever(fake).run("820.3 definitions", corpus="ecfr")
    assert resp.diagnostics["primary_result_count"] == 0 and resp.diagnostics["fallback_used"]
    assert resp.results[0].retrieval_method == METHOD_TRIGRAM


def test_methods_argument_can_disable_fallback_and_describe_reports_config():
    fake = RoutingFakeDatabase({}, {"ECFR_FULL_TEXT": [ecfr_row(rank=0.1)]})
    resp = LexicalRetriever(fake).run(LONG_Q, corpus="ecfr", methods=[METHOD_FULL_TEXT])
    assert not _or_calls(fake) and not resp.diagnostics["fallback_used"]
    d = LexicalRetriever(fake, primary_min_results=2).describe()
    assert d == {"retriever": "LexicalRetriever", "enable_or_fallback": True, "primary_min_results": 2,
                 "fallback_max_terms": 8, "chunks_per_document": 3,
                 "part_expand_sections": 3, "part_expand_rows": 2, "section_coverage": True, "defined_terms": True,
                 "heading_corroboration": True, "cross_references": False}
    with pytest.raises(ValueError):
        LexicalRetriever(fake, primary_min_results=-1)
    with pytest.raises(ValueError):
        LexicalRetriever(fake, part_expand_sections=-1)
    assert "diagnostics" in resp.to_dict()
