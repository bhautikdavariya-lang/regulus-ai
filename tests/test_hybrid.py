"""Stage 9 hybrid fusion, model-free: authority rules, non-existence safety,
dedup, bounds, determinism, strategy isolation, floor, config, citations,
and untouched lexical/semantic behaviour. Fake retrievers return canned
SearchResponse objects."""

import pytest

from regulus.retrieval import HybridConfig, HybridRetriever, LexicalRetriever, QueryType
from regulus.retrieval.hybrid import STRATEGIES, rrf_score
from regulus.retrieval.lexical import SearchResponse
from regulus.retrieval.models import METHOD_EXACT_CFR, METHOD_FULL_TEXT, METHOD_FULL_TEXT_OR, METHOD_SEMANTIC, METHOD_TRIGRAM
from tests.test_retrieval_lexical import ecfr_row, guidance_row


def L(section, para="", ordinal=0, method=METHOD_FULL_TEXT, score=5.0, **extra):
    row = ecfr_row(section=section, para=para, ordinal=ordinal)
    if method == METHOD_EXACT_CFR:
        extra.setdefault("match_kind", "exact")
    return LexicalRetriever._ecfr_result(row, method, score, extra)


def S(section, para="", ordinal=0, sim=0.75):
    row = ecfr_row(section=section, para=para, ordinal=ordinal)
    return LexicalRetriever._ecfr_result(row, METHOD_SEMANTIC, sim, {"cosine_similarity": sim, "corpus_role": "target", "experimental": True})


def SG(docket, ordinal=0, sim=0.75):
    return LexicalRetriever._guidance_result(guidance_row(docket=docket, ordinal=ordinal), METHOD_SEMANTIC, sim, {"cosine_similarity": sim})


class FakeLexical:
    def __init__(self, results, *, primary_count=None, notes=(), fallback_used=False):
        self.results = list(results)
        self.primary_count = len([r for r in results if r.retrieval_method in (METHOD_EXACT_CFR, METHOD_FULL_TEXT)]) if primary_count is None else primary_count
        self.notes = list(notes)
        self.fallback_used = fallback_used
        self.calls = []

    def run(self, query, *, corpus=None, top_k=10, filters=None, methods=None):
        self.calls.append({"query": query, "corpus": corpus, "top_k": top_k, "methods": methods})
        res = self.results[:top_k]
        return SearchResponse(query, QueryType.GENERAL_REGULATORY_SEARCH, res, {"full_text:ecfr": 3.0}, {"full_text:ecfr": len(res)}, 5.0, self.notes,
                              {"primary_result_count": self.primary_count, "fallback_used": self.fallback_used, "fallback_terms": [], "final_result_count": len(res), "retrieval_mode": "primary" if res else "none"})

    def describe(self):
        return {"retriever": "FakeLexical"}


class FakeSemantic:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, query, *, corpus=None, top_k=10, filters=None, methods=None):
        self.calls.append({"query": query, "corpus": corpus, "top_k": top_k})
        res = self.results[:top_k]
        return SearchResponse(query, QueryType.GENERAL_REGULATORY_SEARCH, res, {"semantic:embed": 20.0, "semantic:search": 3.0}, {"semantic": len(res)}, 23.0, [],
                              {"retrieval_mode": "semantic", "top_similarity": res[0].relevance_score if res else None})

    def describe(self):
        return {"retriever": "FakeSemantic"}


def H(lex, sem, **cfg):
    return HybridRetriever(lex, sem, HybridConfig(**cfg))


EXACT = [L("820.10", "", 0, METHOD_EXACT_CFR, 100.0), L("820.10", "(a)", 1, METHOD_EXACT_CFR, 100.0), L("820.10", "(b)", 2, METHOD_EXACT_CFR, 100.0)]
SEM_STRONG = [S("211.1", "(a)", 1, 0.90), S("50.20", "", 0, 0.88), S("820.10", "(a)", 1, 0.85)]  # third duplicates an exact hit


# ------------------------------------------------------------ config / basics


def test_config_validation_and_description():
    for bad in ({"strategy": "sum"}, {"lexical_top_n": 0}, {"semantic_floor": 1.5}, {"rrf_k": 0}, {"primary_min_results": -1}):
        with pytest.raises(ValueError):
            HybridConfig(**bad)
    d = HybridConfig().to_dict()
    assert d["strategy"] == "authority" and d["fusion_method"] == "rrf" and d["semantic_floor"] is None
    assert HybridConfig(strategy="fallback").to_dict()["fusion_method"] == "append"
    assert set(STRATEGIES) == {"fallback", "rrf", "authority"}
    assert rrf_score((1, None), 60) == pytest.approx(1 / 61) and rrf_score((1, 1), 60) == pytest.approx(2 / 61)


def test_empty_query_and_top_k_validation():
    h = H(FakeLexical([]), FakeSemantic([]))
    with pytest.raises(ValueError):
        h.run("   ")
    with pytest.raises(ValueError):
        h.run("q", top_k=0)


# ----------------------------------------------------- authority (rules 1 & 3)


@pytest.mark.parametrize("strategy", ["fallback", "authority"])
def test_exact_lexical_match_stays_first_and_is_not_displaced(strategy):
    resp = H(FakeLexical(EXACT), FakeSemantic(SEM_STRONG), strategy=strategy).run("21 CFR 820.10", top_k=5)
    labels = [r.citation.label for r in resp.results[:3]]
    assert labels == ["21 CFR 820.10", "21 CFR 820.10(a)", "21 CFR 820.10(b)"]
    assert all(r.retrieval_method == METHOD_EXACT_CFR for r in resp.results[:3])
    assert resp.diagnostics["exact_identifier_detected"] and resp.diagnostics["exact_match_present"] and resp.diagnostics["retrieval_mode"] == "exact"
    assert not resp.diagnostics["identifier_not_found"]


def test_pure_rrf_control_can_interleave_semantic_above_exact():
    """Strategy B has no authority rule by design; this documents what it does."""
    resp = H(FakeLexical(EXACT), FakeSemantic(SEM_STRONG), strategy="rrf").run("21 CFR 820.10", top_k=6)
    methods = [r.retrieval_method for r in resp.results]
    assert METHOD_SEMANTIC in methods[:3]  # a semantic-only item reached the top three
    # the duplicated exact hit 820.10(a) got both ranks and therefore the top fusion score
    assert resp.results[0].citation.label == "21 CFR 820.10(a)" and resp.results[0].methods == (METHOD_EXACT_CFR, METHOD_SEMANTIC)


def test_semantic_supplements_lexical_for_conceptual_queries_in_authority_mode():
    lex = [L("820.10", "(b)", 2, METHOD_FULL_TEXT, 8.0), L("211.100", "(a)", 1, METHOD_FULL_TEXT, 6.0)]
    sem = [S("820.10", "(a)", 1, 0.80), S("820.10", "(b)", 2, 0.79)]
    resp = H(FakeLexical(lex), FakeSemantic(sem), strategy="authority").run("quality management system documentation", top_k=5)
    keys = [r.key for r in resp.results]
    assert "ecfr:820.10:(b):0" in keys and "ecfr:820.10:(a):0" in keys and "ecfr:211.100:(a):0" in keys
    dup = next(r for r in resp.results if r.key == "ecfr:820.10:(b):0")
    assert dup.retrieval_method == METHOD_FULL_TEXT and dup.methods == (METHOD_FULL_TEXT, METHOD_SEMANTIC)
    assert dup.metadata["hybrid"]["lexical_rank"] == 1 and dup.metadata["hybrid"]["semantic_rank"] == 2
    assert dup.metadata["hybrid"]["fusion_score"] == pytest.approx(1 / 61 + 1 / 62, abs=1e-6)
    assert resp.results[0].key == "ecfr:820.10:(b):0"  # found by both legs -> highest fusion score
    assert resp.diagnostics["retrieval_mode"] == "hybrid" and resp.diagnostics["semantic_in_final"] == 2 and resp.diagnostics["deduplicated_candidate_count"] == 3


# --------------------------------------------------------- rule 2: existence


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_fake_identifier_never_becomes_verified(strategy):
    note = "No live record for 21 CFR 314.999 in this eCFR snapshot (section may be reserved, removed, outside Title 21, or excluded by filters); remaining results are text matches only."
    lex = FakeLexical([L("111.360", "", 0, METHOD_TRIGRAM, 2.0)], primary_count=0, notes=[note])
    sem = FakeSemantic([S("314.50", "(a)", 1, 0.72), SG("FDA-2018-D-0671", 0, 0.70)])
    resp = H(lex, sem, strategy=strategy).run("What are the specific requirements of 21 CFR 314.999?", top_k=5)
    d = resp.diagnostics
    assert d["exact_identifier_detected"] and not d["exact_match_present"] and d["identifier_not_found"]
    assert resp.notes == [note]
    assert not any(r.retrieval_method in (METHOD_EXACT_CFR,) for r in resp.results)
    assert not any("314.999" in r.citation.label for r in resp.results)
    for r in resp.results:
        if METHOD_SEMANTIC in r.methods:
            assert r.metadata["contextual_only"] is True and r.metadata["existence_evidence"] is False


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_fake_docket_gets_a_not_found_note_and_contextual_semantic_results(strategy):
    lex = FakeLexical([], primary_count=0)  # lexical finds nothing and emits no note for dockets
    sem = FakeSemantic([SG("FDA-2015-D-4599", 0, 0.80), SG("FDA-2016-D-2565", 0, 0.77)])
    resp = H(lex, sem, strategy=strategy).run("Summarize the main recommendations of FDA guidance document FDA-2023-D-99999.", top_k=5)
    assert resp.diagnostics["identifier_not_found"] and resp.diagnostics["retrieval_mode"] == "semantic"
    assert len(resp.notes) == 1 and "FDA-2023-D-99999" in resp.notes[0] and "do not show that the docket exists" in resp.notes[0]
    assert all(r.metadata["contextual_only"] for r in resp.results)
    assert not any("FDA-2023-D-99999" in r.citation.label for r in resp.results)


def test_semantic_result_cannot_replace_or_impersonate_exact_identifier():
    """A semantic hit on a *different* section must not outrank exact rows or claim the requested label."""
    sem = [S("820.1", "(a)", 1, 0.99)]
    resp = H(FakeLexical(EXACT), FakeSemantic(sem), strategy="authority").run("What does 21 CFR 820.10 cover?", top_k=4)
    assert [r.citation.section for r in resp.results[:3]] == ["820.10"] * 3
    assert resp.results[3].citation.section == "820.1" and resp.results[3].retrieval_method == METHOD_SEMANTIC


# ------------------------------------------------- fallback strategy (A)


def test_fallback_strategy_keeps_lexical_only_when_coverage_is_strong():
    lex = [L(f"1.{i}", "", 0, METHOD_FULL_TEXT, 5.0 - i) for i in range(4)]
    resp = H(FakeLexical(lex), FakeSemantic(SEM_STRONG), strategy="fallback").run("labeling requirements", top_k=10)
    assert [r.key for r in resp.results] == [r.key for r in lex]
    assert resp.diagnostics["semantic_in_final"] == 0 and resp.diagnostics["retrieval_mode"] == "lexical"


def test_fallback_strategy_adds_semantic_when_weak_and_preserves_lexical_first():
    lex = [L("21.30", "(a)", 1, METHOD_FULL_TEXT_OR, 1.5)]
    resp = H(FakeLexical(lex, primary_count=0, fallback_used=True), FakeSemantic(SEM_STRONG), strategy="fallback").run("explain why a new drug must be approved before it can be sold", top_k=3)
    assert resp.results[0].key == "ecfr:21.30:(a):0"
    assert [r.retrieval_method for r in resp.results[1:]] == [METHOD_SEMANTIC, METHOD_SEMANTIC]
    assert resp.results[1].relevance_score == 0.90  # semantic order preserved by similarity
    assert resp.diagnostics["retrieval_mode"] == "hybrid" and resp.diagnostics["fallback_used"] is True and len(resp.results) == 3


# ------------------------------------------ dedup, bounds, determinism, floor


def test_duplicates_removed_and_lexical_metadata_kept():
    lex = [L("50.20", "", 0, METHOD_FULL_TEXT, 7.0)]
    sem = [S("50.20", "", 0, 0.88)]
    for strategy in STRATEGIES:
        resp = H(FakeLexical(lex, primary_count=0), FakeSemantic(sem), strategy=strategy).run("informed consent", top_k=5)
        assert len(resp.results) == 1 and resp.results[0].retrieval_method == METHOD_FULL_TEXT
        assert resp.results[0].citation.label == "21 CFR 50.20" and resp.results[0].text == lex[0].text
        assert resp.diagnostics["deduplicated_candidate_count"] == 1


def test_final_count_bounded_and_candidate_top_n_passed_to_legs():
    lex = FakeLexical([L(f"1.{i}", "", 0, METHOD_FULL_TEXT, 9.0 - i * 0.1) for i in range(20)])
    sem = FakeSemantic([S(f"2.{i}", "", 0, 0.9 - i * 0.01) for i in range(20)])
    resp = H(lex, sem, strategy="rrf", lexical_top_n=7, semantic_top_n=4).run("q", top_k=5)
    assert lex.calls[0]["top_k"] == 7 and sem.calls[0]["top_k"] == 4
    assert len(resp.results) == 5 and resp.diagnostics["lexical_candidate_count"] == 7 and resp.diagnostics["semantic_candidate_count"] == 4


def test_fusion_is_deterministic_and_tie_broken_by_key():
    lex = FakeLexical([L("9.9", "", 0), L("1.1", "", 0)], primary_count=2)
    sem = FakeSemantic([S("5.5", "", 0, 0.8), S("3.3", "", 0, 0.7)])
    a = [r.key for r in H(lex, sem, strategy="rrf").run("q", top_k=4).results]
    b = [r.key for r in H(lex, sem, strategy="rrf").run("q", top_k=4).results]
    assert a == b
    # lexical rank 1 and semantic rank 1 tie on RRF -> key order decides
    assert a[:2] == sorted(["ecfr:9.9::0", "ecfr:5.5::0"])


def test_similarity_floor_removes_weak_semantic_candidates_and_is_reported():
    sem = FakeSemantic([S("5.5", "", 0, 0.82), S("3.3", "", 0, 0.71), S("2.2", "", 0, 0.66)])
    lex = FakeLexical([], primary_count=0)
    resp = H(lex, sem, strategy="authority", semantic_floor=0.70).run("conceptual question", top_k=5)
    assert [r.citation.section for r in resp.results] == ["5.5", "3.3"]
    d = resp.diagnostics
    assert d["semantic_floor"] == 0.70 and d["semantic_candidate_count"] == 3 and d["semantic_candidates_accepted"] == 2 and d["semantic_candidates_removed"] == 1
    none = H(lex, sem, strategy="authority", semantic_floor=None).run("conceptual question", top_k=5)
    assert len(none.results) == 3 and none.diagnostics["semantic_candidates_removed"] == 0
    strict = H(lex, sem, strategy="authority", semantic_floor=0.95).run("conceptual question", top_k=5)
    assert strict.results == [] and strict.diagnostics["retrieval_mode"] == "none"


def test_strategies_are_isolated():
    lex = FakeLexical(EXACT + [L("211.1", "(a)", 1, METHOD_FULL_TEXT, 3.0)])
    sem = FakeSemantic(SEM_STRONG)
    outs = {s: [r.key for r in H(lex, sem, strategy=s).run("21 CFR 820.10", top_k=6).results] for s in STRATEGIES}
    assert outs["fallback"] == [r.key for r in lex.results]  # strong coverage: lexical only
    assert outs["authority"][:3] == [r.key for r in EXACT]
    assert outs["rrf"] != outs["authority"]
    for s in STRATEGIES:
        assert H(lex, sem, strategy=s).run("21 CFR 820.10").diagnostics["retrieval_strategy"] == s


def test_citations_scores_and_serialisation():
    lex = [L("7.40", "(a)", 1, METHOD_FULL_TEXT, 4.0)]
    sem = [SG("FDA-2018-D-2074", 0, 0.81)]
    resp = H(FakeLexical(lex, primary_count=1), FakeSemantic(sem), strategy="authority").run("recall policy", top_k=5)
    g = next(r for r in resp.results if r.corpus == "fda_guidance")
    assert g.citation.docket_number == "FDA-2018-D-2074" and g.citation.url.startswith("https://") and g.retrieval_method == METHOD_SEMANTIC
    assert g.metadata["hybrid"]["semantic_rank"] == 1 and g.metadata["hybrid"]["lexical_rank"] is None
    assert all(0 < r.relevance_score < 1 for r in resp.results)  # RRF scores, never lexical+cosine sums
    assert resp.results[0].metadata["scores"].get("full_text") == 4.0
    d = resp.to_dict()
    assert d["diagnostics"]["retrieval_strategy"] == "authority" and "lexical" in d["diagnostics"]
    assert "password" not in str(d) and "postgresql://" not in str(d)


def test_timings_and_notes_propagate():
    resp = H(FakeLexical(EXACT, notes=[]), FakeSemantic(SEM_STRONG)).run("21 CFR 820.10", top_k=3)
    for k in ("lexical", "semantic", "semantic:embed", "semantic:search", "fusion"):
        assert k in resp.timings_ms
    assert resp.counts["semantic"] == 3 and resp.counts["semantic_accepted"] == 3


def test_lexical_and_semantic_retrievers_are_untouched():
    from regulus.retrieval.lexical import DEFAULT_METHODS
    from regulus.retrieval.semantic.retriever import SemanticRetriever

    assert METHOD_SEMANTIC not in DEFAULT_METHODS
    lex = FakeLexical(EXACT)
    H(lex, FakeSemantic(SEM_STRONG)).run("21 CFR 820.10", methods=[METHOD_EXACT_CFR])
    assert lex.calls[0]["methods"] == [METHOD_EXACT_CFR]  # pass-through, no rewriting
    assert not hasattr(SemanticRetriever, "fuse") and not hasattr(LexicalRetriever, "fuse")
