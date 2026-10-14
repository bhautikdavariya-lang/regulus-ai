"""Retrieval evaluation metrics and dataset validation. No database."""

import pytest

from regulus.evaluation.retrieval_eval import (
    QueryOutcome,
    RetrievalDatasetError,
    first_hit_rank,
    load_retrieval_dataset,
    summarise,
    target_matches,
)
from regulus.retrieval import LexicalRetriever
from regulus.retrieval.models import METHOD_FULL_TEXT
from tests.test_retrieval_lexical import ecfr_row, guidance_row


def _e(section, para, ordinal=1):
    return LexicalRetriever._ecfr_result(ecfr_row(section=section, para=para, ordinal=ordinal), METHOD_FULL_TEXT, 1.0, {})


def _g(docket, title="510(k) Third Party Review Program"):
    return LexicalRetriever._guidance_result(guidance_row(docket=docket, title=title), METHOD_FULL_TEXT, 1.0, {})


def test_dataset_loads_and_targets_are_well_formed():
    qs = load_retrieval_dataset()
    assert 15 <= len(qs) <= 30
    assert len({q.id for q in qs}) == len(qs)
    cats = {q.category for q in qs}
    for needed in ("exact_cfr", "cfr_section", "cfr_paragraph", "regulatory_concept", "fda_guidance", "cross_corpus", "terminology_variation", "difficult_lexical"):
        assert needed in cats


def test_dataset_errors(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"id":"a","category":"c","query":"q","expected":["nonsense target"]}\n', encoding="utf-8")
    with pytest.raises(RetrievalDatasetError, match="unrecognised target"):
        load_retrieval_dataset(p)
    p.write_text('{"id":"a","category":"c","query":"q"}\n', encoding="utf-8")
    with pytest.raises(RetrievalDatasetError, match="missing field"):
        load_retrieval_dataset(p)
    p.write_text('{"id":"a","category":"c","query":"q","expected":[]}\n{"id":"a","category":"c","query":"q","expected":[]}\n', encoding="utf-8")
    with pytest.raises(RetrievalDatasetError, match="duplicate id"):
        load_retrieval_dataset(p)


def test_target_matching_rules():
    assert target_matches("21 CFR 820.10", _e("820.10", "(b)(1)"))
    assert target_matches("21 CFR 820.10", _e("820.10", ""))
    assert not target_matches("21 CFR 820.10", _e("820.1", ""))
    assert target_matches("21 CFR 820.10(b)", _e("820.10", "(b)(1)"))
    assert target_matches("21 CFR 820.10(b)", _e("820.10", "(b)"))
    assert not target_matches("21 CFR 820.10(b)", _e("820.10", "(bb)"))
    assert not target_matches("21 CFR 820.10(b)(1)", _e("820.10", "(b)"))
    assert target_matches("docket:fda-2016-d-2565", _g("FDA-2016-D-2565"))
    assert not target_matches("docket:FDA-2016-D-2565", _g(None))
    assert target_matches("guidance:510(k) third", _g("FDA-1"))
    assert not target_matches("21 CFR 820.10", _g("FDA-2016-D-2565"))


def test_first_hit_rank():
    results = [_e("1.1", ""), _g("FDA-2"), _e("820.10", "(a)")]
    assert first_hit_rank(("21 CFR 820.10",), results) == 3
    assert first_hit_rank(("docket:FDA-2",), results) == 2
    assert first_hit_rank(("21 CFR 999.1",), results) is None


def _outcome(id, rank, cat="c", negative=False, neg_ok=None, err=None, ms=10.0):
    return QueryOutcome(id, cat, "q", [], rank, negative, neg_ok, [], ms, {}, err)


def test_summarise_metrics():
    s = summarise([_outcome("a", 1), _outcome("b", 3), _outcome("c", None), _outcome("d", None, negative=True, neg_ok=True), _outcome("e", None, err="boom")])
    assert (s["queries"], s["scored"], s["negative_controls"], s["negative_controls_passed"], s["failed"]) == (5, 3, 1, 1, 1)
    assert s["recall@1"] == pytest.approx(1 / 3, abs=1e-3) and s["recall@3"] == pytest.approx(2 / 3, abs=1e-3) and s["recall@10"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["mrr"] == pytest.approx((1 + 1 / 3) / 3, abs=1e-3)
    assert s["misses"] == ["c"]
    assert s["by_category"]["c"]["scored"] == 3


def test_summarise_empty():
    s = summarise([])
    assert s["recall@1"] is None and s["mrr"] is None and s["avg_total_ms"] is None
