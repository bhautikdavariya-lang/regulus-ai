"""Loads the real pinned embedding model once and embeds a few texts.
Slow; excluded by default:  pytest -m slow tests/test_semantic_model_slow.py
"""

import numpy as np
import pytest

from regulus.config import load_settings
from regulus.retrieval.semantic import TransformersEmbedder, cosine_similarity, load_manifest

pytestmark = pytest.mark.slow


def test_real_embedder_dimension_finite_normalised_and_meaningful():
    cfg = load_manifest().embedding
    emb = TransformersEmbedder(cfg, cache_dir=str(load_settings().model.cache_dir))
    texts = [
        "Design and development controls for medical devices under the quality management system regulation.",
        "Design controls for medical devices.",
        "Nutrition labeling of food: serving sizes and nutrient content.",
    ]
    vecs = emb.embed_batch(texts)
    assert vecs.shape == (3, cfg.dimension) and vecs.dtype == np.float32
    assert np.all(np.isfinite(vecs))
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-4)
    q = emb.embed_query("design controls for medical devices")
    sims = cosine_similarity(q, vecs, normalized=True)
    assert sims[1] > sims[2] and sims[0] > sims[2], sims  # related texts closer than the unrelated one
    again = emb.embed_batch(texts)
    assert np.allclose(vecs, again, atol=1e-5)  # deterministic on CPU
    d = emb.describe()
    assert d["model_id"] == cfg.model_id and d["dimension"] == cfg.dimension and d["load_seconds"] >= 0
