"""Stage 10: versioned corpus paths, manifest v2, integrity gate, precision and
crowding metrics, the v2 benchmark, and reproducibility of Stage 8/9 defaults."""

import json

import pytest

from regulus.evaluation.retrieval_eval import crowding, hits_at, load_retrieval_dataset, summarise, QueryOutcome
from regulus.retrieval import LexicalRetriever
from regulus.retrieval.models import METHOD_FULL_TEXT, METHOD_SEMANTIC
from regulus.retrieval.semantic import CorpusItem, load_manifest, resolve_paths, validate_items
from regulus.retrieval.semantic.models import GENERATED_DIR, MANIFEST_PATH, SemanticConfigError, text_sha256
from tests.test_retrieval_lexical import ecfr_row, guidance_row
from tests.test_semantic import E, G


# ------------------------------------------------------------------ paths


def test_resolve_paths_keeps_stage8_layout_and_versions_others():
    s8 = resolve_paths(None)
    assert s8.name == "stage8" and s8.manifest == MANIFEST_PATH and s8.generated == GENERATED_DIR
    assert resolve_paths("stage8") == s8
    v1 = resolve_paths("semantic_expanded_v1")
    assert v1.manifest.parent.name == "semantic_expanded_v1" and v1.generated.name == "generated"
    assert v1.corpus.name == "corpus.jsonl" and v1.vectors.name == "vectors.npy" and v1.index_meta.name == "index_meta.json"
    assert v1.generated != s8.generated
    with pytest.raises(SemanticConfigError):
        resolve_paths("../escape")


# --------------------------------------------------------------- manifest v2


def test_expanded_manifest_loads_and_is_scope_based():
    m = load_manifest(corpus="semantic_expanded_v1")
    assert m.version == 2 and m.is_scope_based and m.name == "semantic_expanded_v1"
    assert m.embedding.model_id == "BAAI/bge-small-en-v1.5" and m.embedding.revision == "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    assert m.embedding.dimension == 384 and m.embedding.pooling == "cls" and m.embedding.normalize
    assert set(m.ecfr_subchapters) == {"C", "D"} and "820" in m.ecfr_parts and "870" in m.ecfr_parts
    assert set(m.guidance_sectors) == {"drug", "device"} and m.guidance_max_chunks_per_document == 12
    assert m.role_of_section("820.10") == "target" and m.role_of_section("870.1025") == "distractor"
    assert m.role_of_docket("FDA-2003-D-0143") == "target" and m.role_of_docket("FDA-2000-D-0186") == "distractor" and m.role_of_docket(None) == "distractor"
    assert m.rationale and m.scope_summary()["name"] == "semantic_expanded_v1"


def test_stage8_manifest_unchanged_and_role_logic_preserved():
    m = load_manifest()
    assert m.version == 1 and not m.is_scope_based and m.name == "stage8"
    assert m.role_of_section("352.52") == "distractor" and m.role_of_section("820.10") == "target"
    assert m.embedding == load_manifest(corpus="semantic_expanded_v1").embedding  # same pinned model


def test_manifest_v2_validation(tmp_path):
    base = "version: 2\nembedding: {model_id: 'x/y', revision: 'r', dimension: 4}\n"
    p = tmp_path / "manifest.yaml"
    p.write_text(base + "selection: {ecfr: {}, guidance: {}}\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="selects nothing"):
        load_manifest(p)
    p.write_text(base + "selection: {ecfr: {subchapters: ['C', 'C']}}\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="duplicate"):
        load_manifest(p)
    p.write_text(base + "selection: {ecfr: {subchapters: ['CD']}}\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="single letters"):
        load_manifest(p)
    p.write_text(base + "selection: {ecfr: {parts: ['820']}, guidance: {max_chunks_per_document: 0}}\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="positive"):
        load_manifest(p)


# ------------------------------------------------------------ integrity gate


def test_validate_items_counts_and_rejects_bad_records():
    items = [E("820.10", "(a)", 1), G("FDA-2008-D-0559", 0, text="chunk"), E("1.1", "(a)", 1, role="distractor")]
    assert validate_items(items) == {"items": 3, "ecfr_items": 2, "guidance_items": 1, "targets": 2, "distractors": 1}
    with pytest.raises(SemanticConfigError, match="duplicate natural key"):
        validate_items(items + [E("820.10", "(a)", 1)])
    bad = CorpusItem("ecfr:9.9:(a):0", "ecfr", "x", text_sha256("x"), "target", {})
    with pytest.raises(SemanticConfigError, match="missing eCFR identifier"):
        validate_items([bad])
    row = guidance_row(); row.pop("body_text"); row["source_url"] = ""
    badg = CorpusItem("fda_guidance:x#0", "fda_guidance", "t", text_sha256("t"), "target", row)
    with pytest.raises(SemanticConfigError, match="missing guidance identifier"):
        validate_items([badg])
    with pytest.raises(SemanticConfigError, match="role"):
        validate_items([E("1.1", "(a)", 1, role="scope")])


# ----------------------------------------------------- precision / crowding


def _r(section, para, method=METHOD_FULL_TEXT, role=None, sem=False):
    r = LexicalRetriever._ecfr_result(ecfr_row(section=section, para=para, ordinal=1), method, 1.0, {"corpus_role": role} if role else {})
    if sem:
        from dataclasses import replace
        r = replace(r, methods=(method, METHOD_SEMANTIC))
    return r


def test_hits_at_and_crowding():
    results = [_r("1.1", "(a)", role="distractor", sem=True), _r("2.2", "(a)", role="distractor"), _r("820.10", "(a)"), _r("820.10", "(b)"), _r("3.3", "(a)")]
    exp = ("21 CFR 820.10",)
    assert hits_at(exp, results, 1) == 0 and hits_at(exp, results, 3) == 1 and hits_at(exp, results, 5) == 2
    c = crowding(exp, results)
    assert c["target_rank"] == 3 and c["results_above_target"] == 2 and c["distractors_above_target"] == 2 and c["semantic_above_target"] == 1
    assert c["top10_ecfr"] == 5 and c["top10_guidance"] == 0 and c["top10_semantic"] == 1 and c["top10_distinct_documents"] == 4
    miss = crowding(("21 CFR 999.9",), results)
    assert miss["target_rank"] is None and miss["distractors_above_target"] is None


def test_summarise_precision_and_existence_mismatch():
    o1 = QueryOutcome("a", "c", "q", ["x"], 1, False, None, [], 1.0, {}, None, {}, {"1": 1, "3": 2, "5": 2}, {}, None, None)
    o2 = QueryOutcome("b", "c", "q", ["x"], None, False, None, [], 1.0, {}, None, {}, {"1": 0, "3": 0, "5": 0}, {}, None, None)
    n1 = QueryOutcome("n", "neg_fake_section", "q", [], None, True, True, [], 1.0, {}, None, {}, {}, {}, False, False)
    n2 = QueryOutcome("m", "neg_fake_section", "q", [], None, True, False, [], 1.0, {}, None, {}, {}, {}, False, True)
    s = summarise([o1, o2, n1, n2])
    assert s["precision@1"] == 0.5 and s["precision@3"] == pytest.approx(1 / 3, abs=1e-3) and s["precision@5"] == pytest.approx(0.2, abs=1e-3)
    assert s["existence_mismatches"] == ["m"]
    assert s["by_category"]["neg_fake_section"]["negative_controls"] == 2 and s["by_category"]["neg_fake_section"]["negative_controls_passed"] == 1


# --------------------------------------------------------------- benchmark v2


def test_retrieval_v2_dataset_is_balanced_and_flags_negatives():
    from regulus.config import PROJECT_ROOT

    qs = load_retrieval_dataset(PROJECT_ROOT / "data" / "evaluation" / "datasets" / "retrieval_v2.jsonl")
    assert len(qs) >= 45
    cats = {q.category for q in qs}
    for needed in ("identifier", "section_paragraph", "cross_corpus", "conceptual", "vocabulary_mismatch", "long_natural_language", "fda_guidance",
                   "neg_fake_section", "neg_fake_part", "neg_fake_docket", "neg_invalid_reference", "neg_unknowable"):
        assert needed in cats, needed
    negs = [q for q in qs if q.is_negative]
    assert 8 <= len(negs) <= len(qs) // 2  # negatives do not dominate
    for q in qs:
        if q.category.startswith("neg_") and q.category not in ("neg_unknowable",):
            assert q.identifier_exists_in_snapshot is False, q.id
    v1 = load_retrieval_dataset()
    v1_ids = {q.id for q in v1}
    assert v1_ids <= {q.id for q in qs}  # every v1 query is still present
    assert {q.query for q in v1} <= {q.query for q in qs}  # with unchanged text


def test_dataset_rejects_bad_existence_flag(tmp_path):
    from regulus.evaluation.retrieval_eval import RetrievalDatasetError

    p = tmp_path / "d.jsonl"
    p.write_text('{"id":"a","category":"neg_fake_section","query":"q","expected":[],"identifier_exists_in_snapshot":"no"}\n', encoding="utf-8")
    with pytest.raises(RetrievalDatasetError, match="identifier_exists_in_snapshot"):
        load_retrieval_dataset(p)


# ----------------------------------------------------- Stage 8/9 reproducibility


def test_stage8_and_stage9_defaults_are_unchanged():
    from regulus.retrieval import HybridConfig
    from regulus.retrieval.lexical import DEFAULT_ENABLE_OR_FALLBACK, DEFAULT_METHODS, DEFAULT_PRIMARY_MIN_RESULTS
    from regulus.rag import RagConfig

    assert HybridConfig().to_dict() == {"strategy": "authority", "lexical_top_n": 10, "semantic_top_n": 10, "semantic_floor": None, "fusion_method": "rrf", "rrf_k": 60, "primary_min_results": 3}
    assert DEFAULT_ENABLE_OR_FALLBACK is True and DEFAULT_PRIMARY_MIN_RESULTS == 3 and METHOD_SEMANTIC not in DEFAULT_METHODS
    assert RagConfig().exclude_contextual_only is True and RagConfig().to_dict()["context"]["max_total_chars"] == 3600
    meta = json.loads((GENERATED_DIR / "index_meta.json").read_text(encoding="utf-8")) if (GENERATED_DIR / "index_meta.json").is_file() else None
    if meta:
        assert meta["corpus_size"] == 2676 and meta["dimension"] == 384  # Stage 8 index untouched
