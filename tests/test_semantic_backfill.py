"""Semantic index backfill: `SemanticIndex.build(..., reuse=previous)` embeds only new or edited items and gives the
same index a full build gives, so extending the corpus (e.g. adding CFR parts to the manifest) does not re-embed the
26,000 unchanged items and can be re-run safely."""

import numpy as np
import pytest

from regulus.retrieval.semantic import EmbeddingConfig, IndexMismatchError, SemanticIndex, load_manifest
from tests.test_semantic import CFG, DIM, ITEMS, E, FakeEmbedder


def test_without_reuse_the_build_is_unchanged():
    emb = FakeEmbedder()
    idx = SemanticIndex.build(ITEMS, emb)
    assert emb.calls == [[i.text for i in ITEMS]] and idx.meta.reused_items is None


def test_only_new_and_edited_items_are_embedded_and_the_result_equals_a_full_build():
    previous = SemanticIndex.build(ITEMS, FakeEmbedder())
    edited = E("820.10", "(b)", 2, text="paragraph text for 820.10 (b) - amended")
    added = E("70.3", "(f)", 6, text="a color additive is any material")
    items = [ITEMS[0], edited, added] + ITEMS[2:]
    emb = FakeEmbedder()
    idx = SemanticIndex.build(items, emb, reuse=previous)
    assert emb.calls == [[edited.text, added.text]]
    full = SemanticIndex.build(items, FakeEmbedder())
    assert np.array_equal(idx.vectors, full.vectors) and idx.meta.corpus_sha256 == full.meta.corpus_sha256
    assert idx.meta.reused_items == len(items) - 2


def test_a_rerun_embeds_nothing():
    first = SemanticIndex.build(ITEMS, FakeEmbedder())
    emb = FakeEmbedder()
    again = SemanticIndex.build(ITEMS, emb, reuse=first)
    assert emb.calls == [] and np.array_equal(again.vectors, first.vectors) and again.meta.reused_items == len(ITEMS)


def test_an_index_of_another_embedding_configuration_is_never_reused():
    other = EmbeddingConfig(model_id="fake/other", revision="zzz", dimension=DIM)
    previous = SemanticIndex.build(ITEMS, FakeEmbedder(other))
    with pytest.raises(IndexMismatchError, match="embedding configuration"):
        SemanticIndex.build(ITEMS, FakeEmbedder(CFG), reuse=previous)


def test_the_expanded_manifest_covers_the_colour_additive_jurisdiction_and_food_cgmp_parts():
    m = load_manifest(corpus="semantic_expanded_v1")
    assert {"3", "4", "70", "73", "74", "82", "117"} <= set(m.ecfr_parts)
    assert m.role_of_section("70.3") == "distractor"  # coverage, not new benchmark targets
