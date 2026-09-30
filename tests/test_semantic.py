"""Stage 8 semantic experiment, model-free: manifest/corpus schema, hashing,
normalisation, cosine, top-k bounds, determinism, mismatch detection,
result citations. A FakeEmbedder produces deterministic vectors from text."""

import hashlib
import json

import numpy as np
import pytest

from regulus.retrieval import LexicalRetriever
from regulus.retrieval.models import METHOD_FULL_TEXT, METHOD_SEMANTIC
from regulus.retrieval.ranking import METHOD_PRIORITY
from regulus.retrieval.semantic import (
    CorpusItem,
    EmbeddingConfig,
    IndexMismatchError,
    SemanticIndex,
    SemanticRetriever,
    corpus_sha256,
    cosine_similarity,
    l2_normalize,
    load_corpus,
    load_manifest,
)
from regulus.retrieval.semantic.models import MANIFEST_PATH, IndexMeta, SemanticConfigError, text_sha256
from tests.test_retrieval_lexical import ecfr_row, guidance_row

DIM = 8
CFG = EmbeddingConfig(model_id="fake/embedder", revision="abc123", dimension=DIM, pooling="cls", normalize=True, max_length=32, query_instruction="q: ")


class FakeEmbedder:
    """Deterministic: vector = normalised bytes of sha256(text) (first DIM bytes)."""

    def __init__(self, config=CFG):
        self.config = config
        self.calls = []

    def embed_batch(self, texts):
        self.calls.append(list(texts))
        rows = []
        for t in texts:
            digest = hashlib.sha256(t.encode("utf-8")).digest()[: self.config.dimension]
            rows.append(np.frombuffer(digest, dtype=np.uint8).astype(np.float32) + 1.0)
        return l2_normalize(np.stack(rows)) if self.config.normalize else np.stack(rows)

    def embed_query(self, text):
        if not text.strip():
            raise ValueError("empty")
        return self.embed_batch([self.config.query_instruction + text])[0]

    def describe(self):
        return {"embedder": "fake", **self.config.to_dict()}


def E(section, para="", ordinal=0, text=None, role="target"):
    row = ecfr_row(section=section, para=para, ordinal=ordinal)
    row["snapshot_date"] = "2026-09-03"
    text = text or f"paragraph text for {section} {para}"
    meta = {k: v for k, v in row.items() if k != "body_text"}
    return CorpusItem(f"ecfr:{section}:{para}:0", "ecfr", text, text_sha256(text), role, meta)


def G(docket, ordinal=0, text="guidance chunk", role="target"):
    row = guidance_row(docket=docket, ordinal=ordinal)
    row["issued_on"] = "2024-11-21"
    meta = {k: v for k, v in row.items() if k != "body_text"}
    return CorpusItem(f"fda_guidance:{row['source_url']}#{ordinal}", "fda_guidance", text, text_sha256(text), role, meta)


ITEMS = [E("820.10", "(a)", 1), E("820.10", "(b)", 2), E("211.132", "(a)", 1), G("FDA-2008-D-0559", 0), G("FDA-2008-D-0559", 1, text="second chunk")]


def build():
    return SemanticIndex.build(ITEMS, FakeEmbedder())


# ------------------------------------------------------------ manifest / corpus


def test_real_manifest_loads_and_is_consistent():
    m = load_manifest()
    assert m.embedding.model_id == "BAAI/bge-small-en-v1.5" and len(m.embedding.revision) == 40
    assert m.embedding.dimension == 384 and m.embedding.normalize and m.embedding.pooling == "cls"
    assert "820.10" in m.sections() and "201.327" in m.sections() and "FDA-2003-D-0143" in m.dockets()
    assert m.role_of_section("352.52") == "distractor" and m.role_of_docket("FDA-2015-D-0198") == "target"
    assert m.guidance_max_chunks_per_document == 60
    assert MANIFEST_PATH.is_file()


def test_manifest_errors(tmp_path):
    bad = tmp_path / "m.yaml"
    bad.write_text("embedding: {model_id: 'x/y', revision: 'r', dimension: 4}\nselection: {ecfr_sections: [], guidance_dockets: []}\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="selects nothing"):
        load_manifest(bad)
    bad.write_text("embedding: {model_id: 'noslash', revision: 'r', dimension: 4}\nselection: {ecfr_sections: [{section: '1.1'}], guidance_dockets: []}\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError):
        load_manifest(bad)
    bad.write_text("embedding: {model_id: 'x/y', revision: 'r', dimension: 4}\nselection: {ecfr_sections: [{section: '1.1'}, {section: '1.1'}], guidance_dockets: []}\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="duplicate"):
        load_manifest(bad)


def test_embedding_config_validation_and_fingerprint():
    with pytest.raises(SemanticConfigError):
        EmbeddingConfig(model_id="x/y", revision="", dimension=4)
    with pytest.raises(SemanticConfigError):
        EmbeddingConfig(model_id="x/y", revision="r", dimension=4, pooling="max")
    a = EmbeddingConfig(model_id="x/y", revision="r", dimension=4, batch_size=8)
    b = EmbeddingConfig(model_id="x/y", revision="r", dimension=4, batch_size=64)
    c = EmbeddingConfig(model_id="x/y", revision="r2", dimension=4)
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()  # batch size never changes vectors


def test_corpus_item_schema_and_hash_check():
    with pytest.raises(SemanticConfigError, match="content_sha256"):
        CorpusItem("ecfr:1.1::0", "ecfr", "text", "0" * 64, "target", {})
    with pytest.raises(SemanticConfigError, match="unknown corpus"):
        CorpusItem("x", "pubmed", "text", text_sha256("text"), "target", {})
    with pytest.raises(SemanticConfigError):
        CorpusItem("x", "ecfr", "   ", text_sha256("   "), "target", {})


def test_load_corpus_roundtrip_and_errors(tmp_path):
    p = tmp_path / "corpus.jsonl"
    p.write_text("\n".join(json.dumps(i.to_dict()) for i in ITEMS) + "\n", encoding="utf-8")
    loaded = load_corpus(p)
    assert [i.id for i in loaded] == [i.id for i in ITEMS]
    p.write_text(json.dumps(ITEMS[0].to_dict()) + "\n" + json.dumps(ITEMS[0].to_dict()) + "\n", encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="duplicate"):
        load_corpus(p)
    p.write_text('{"id": "a"}\n', encoding="utf-8")
    with pytest.raises(SemanticConfigError, match="missing"):
        load_corpus(p)
    with pytest.raises(SemanticConfigError, match="not found"):
        load_corpus(tmp_path / "nope.jsonl")


def test_corpus_hash_is_deterministic_and_order_independent():
    a = corpus_sha256(ITEMS)
    b = corpus_sha256(list(reversed(ITEMS)))
    assert a == b and len(a) == 64
    changed = ITEMS[:-1] + [G("FDA-2008-D-0559", 1, text="second chunk edited")]
    assert corpus_sha256(changed) != a


# ---------------------------------------------------------- vectors / cosine


def test_l2_normalize_and_cosine():
    v = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    n = l2_normalize(v)
    assert np.allclose(n[0], [0.6, 0.8]) and np.allclose(n[1], [0.0, 0.0])
    m = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    q = np.array([1.0, 0.0], dtype=np.float32)
    sims = cosine_similarity(q, m, normalized=False)
    assert np.allclose(sims, [1.0, 0.0, np.sqrt(0.5)])
    raw = cosine_similarity(np.array([2.0, 0.0], dtype=np.float32), m, normalized=True)
    assert raw[0] == 2.0  # normalized=True trusts the caller: no silent renormalisation
    with pytest.raises(ValueError):
        cosine_similarity(np.array([1.0, 0.0, 0.0]), m, normalized=True)


def test_fake_embedder_dimension_and_normalisation():
    vecs = FakeEmbedder().embed_batch(["a", "b"])
    assert vecs.shape == (2, DIM) and np.allclose(np.linalg.norm(vecs, axis=1), 1.0)
    assert np.all(np.isfinite(vecs))


# ------------------------------------------------------------------ index


def test_index_build_meta_and_search_bounds():
    idx = build()
    assert len(idx) == 5 and idx.vectors.shape == (5, DIM)
    assert idx.meta.corpus_sha256 == corpus_sha256(ITEMS) and idx.meta.embedding_fingerprint == CFG.fingerprint()
    assert idx.meta.dimension == DIM and idx.meta.normalize and idx.meta.corpus_size == 5
    q = FakeEmbedder().embed_query("anything")
    assert len(idx.search(q, 3)) == 3 and len(idx.search(q, 50)) == 5
    assert all(i.corpus == "ecfr" for i, _ in idx.search(q, 10, corpus="ecfr")) and len(idx.search(q, 10, corpus="ecfr")) == 3
    assert idx.search(q, 10, corpus="nope") == []
    with pytest.raises(ValueError):
        idx.search(q, 0)


def test_search_is_deterministic_and_ranks_identical_text_first():
    idx = build()
    emb = FakeEmbedder()
    q = emb.embed_batch(["second chunk"])[0]  # exact text of the last item, no instruction
    hits = idx.search(q, 5)
    assert hits[0][0].id.endswith("#1") and hits[0][1] == pytest.approx(1.0, abs=1e-6)
    assert [h[0].id for h in hits] == [h[0].id for h in idx.search(q, 5)]
    sims = [h[1] for h in hits]
    assert sims == sorted(sims, reverse=True)


def test_tie_break_by_id():
    items = [E("9.9", "(a)", 1, text="same"), E("1.1", "(a)", 1, text="same")]
    idx = SemanticIndex.build(items, FakeEmbedder())
    q = FakeEmbedder().embed_batch(["same"])[0]
    assert [h[0].id for h in idx.search(q, 2)] == ["ecfr:1.1:(a):0", "ecfr:9.9:(a):0"]


def test_index_rejects_inconsistent_vectors():
    idx = build()
    with pytest.raises(SemanticConfigError, match="does not match"):
        SemanticIndex(ITEMS, idx.vectors[:2], idx.meta)
    with pytest.raises(SemanticConfigError, match="not unit length"):
        SemanticIndex(ITEMS, idx.vectors * 3.0, idx.meta)
    with pytest.raises(SemanticConfigError, match="dimension"):
        SemanticIndex(ITEMS, np.zeros((5, DIM + 1), dtype=np.float32), idx.meta)


def test_save_load_and_mismatch_detection(tmp_path):
    idx = build()
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(i.to_dict()) for i in ITEMS) + "\n", encoding="utf-8")
    vec, meta = tmp_path / "vectors.npy", tmp_path / "index_meta.json"
    idx.save(vec, meta)
    loaded = SemanticIndex.load(CFG, corpus_path=corpus, vectors_path=vec, meta_path=meta)
    assert np.array_equal(loaded.vectors, idx.vectors) and loaded.meta == idx.meta
    # model/config mismatch
    other = EmbeddingConfig(model_id="fake/other", revision="zzz", dimension=DIM)
    with pytest.raises(IndexMismatchError, match="embedding configuration"):
        SemanticIndex.load(other, corpus_path=corpus, vectors_path=vec, meta_path=meta)
    # corpus mismatch
    edited = ITEMS[:-1] + [G("FDA-2008-D-0559", 1, text="second chunk edited")]
    corpus.write_text("\n".join(json.dumps(i.to_dict()) for i in edited) + "\n", encoding="utf-8")
    with pytest.raises(IndexMismatchError, match="corpus"):
        SemanticIndex.load(CFG, corpus_path=corpus, vectors_path=vec, meta_path=meta)
    # missing index
    with pytest.raises(IndexMismatchError, match="not built"):
        SemanticIndex.load(CFG, corpus_path=corpus, vectors_path=tmp_path / "missing.npy", meta_path=meta)


def test_index_meta_roundtrip():
    meta = build().meta
    assert IndexMeta.from_dict(meta.to_dict()) == meta


# -------------------------------------------------------------- retriever


def test_semantic_retriever_results_citations_and_diagnostics():
    idx = build()
    r = SemanticRetriever(idx, FakeEmbedder())
    resp = r.run("second chunk", top_k=3)
    assert resp.query_type.value == "GENERAL_REGULATORY_SEARCH"
    assert len(resp.results) == 3 and all(x.retrieval_method == METHOD_SEMANTIC for x in resp.results)
    assert 0.0 <= resp.results[0].relevance_score <= 1.0 + 1e-6
    assert resp.diagnostics["retrieval_mode"] == "semantic" and resp.diagnostics["candidates_searched"] == 5
    assert "semantic:embed" in resp.timings_ms and "semantic:search" in resp.timings_ms
    labels = {x.citation.label for x in resp.results}
    ecfr = next(x for x in resp.results if x.corpus == "ecfr")
    assert ecfr.citation.label.startswith("21 CFR ") and ecfr.source_url.startswith("https://www.ecfr.gov/")
    assert ecfr.metadata["experimental"] is True and ecfr.metadata["corpus_role"] == "target"
    g = next(x for x in resp.results if x.corpus == "fda_guidance")
    assert g.citation.docket_number == "FDA-2008-D-0559" and g.citation.issued_on == "2024-11-21"
    assert labels and json.dumps(resp.to_dict())
    text = json.dumps(resp.to_dict()).lower()
    assert "password" not in text and "guidance_id" not in text


def test_semantic_retriever_corpus_filter_bounds_and_empty_query():
    r = SemanticRetriever(build(), FakeEmbedder())
    assert all(x.corpus == "fda_guidance" for x in r.search("q", corpus="fda_guidance", top_k=10))
    assert len(r.search("q", top_k=2)) == 2
    with pytest.raises(ValueError):
        r.search("   ")
    with pytest.raises(ValueError):
        r.search("q", top_k=0)
    with pytest.raises(ValueError):
        r.search("q", corpus="pubmed")


def test_semantic_retriever_rejects_mismatched_embedder():
    idx = build()
    other = FakeEmbedder(EmbeddingConfig(model_id="fake/other", revision="r", dimension=DIM))
    with pytest.raises(ValueError, match="does not match"):
        SemanticRetriever(idx, other)


def test_semantic_method_registered_but_lexical_defaults_untouched():
    from regulus.retrieval.lexical import DEFAULT_METHODS

    assert METHOD_SEMANTIC not in DEFAULT_METHODS  # lexical retriever never runs semantic
    assert METHOD_PRIORITY[METHOD_SEMANTIC] < METHOD_PRIORITY[METHOD_FULL_TEXT]
    desc = LexicalRetriever(None).describe()
    assert desc["retriever"] == "LexicalRetriever" and desc["enable_or_fallback"] is True and desc["primary_min_results"] == 3


def test_semantic_module_has_no_database_or_network_writes():
    import inspect

    from regulus.retrieval.semantic import embedder, index, retriever

    for mod in (embedder, index, retriever):
        src = inspect.getsource(mod)
        for forbidden in ("INSERT", "UPDATE ", "DELETE", "psycopg", "requests.", "httpx", "openai", "voyage", "halfvec", "<=>"):
            assert forbidden not in src, f"{mod.__name__} contains {forbidden!r}"
