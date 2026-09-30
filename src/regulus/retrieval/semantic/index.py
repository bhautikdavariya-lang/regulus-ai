"""Local NumPy cosine index over the experiment corpus, with strict metadata.

Files (data/evaluation/semantic/generated/, gitignored):
    corpus.jsonl      items (from build_semantic_corpus.py)
    vectors.npy       float32 [N, dimension], row i == items[i]
    index_meta.json   model/revision/dimension/normalize/corpus hash/timestamp
Loading refuses a vectors file whose metadata does not match the current
corpus hash or embedding configuration.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

import regulus
from regulus.retrieval.semantic.embedder import Embedder, cosine_similarity
from regulus.retrieval.semantic.models import (
    CORPUS_PATH,
    INDEX_META_PATH,
    VECTORS_PATH,
    CorpusItem,
    EmbeddingConfig,
    IndexMeta,
    SemanticConfigError,
    load_corpus,
)


class IndexMismatchError(RuntimeError):
    """Vectors on disk were built for a different corpus or embedding model."""


def corpus_sha256(items: Sequence[CorpusItem]) -> str:
    h = hashlib.sha256()
    for item in sorted(items, key=lambda i: i.id):
        h.update(item.id.encode("utf-8"))
        h.update(b"\t")
        h.update(item.content_sha256.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


class SemanticIndex:
    def __init__(self, items: list[CorpusItem], vectors: np.ndarray, meta: IndexMeta) -> None:
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(items):
            raise SemanticConfigError(f"vectors shape {vectors.shape} does not match {len(items)} items")
        if vectors.shape[1] != meta.dimension:
            raise SemanticConfigError(f"vectors dimension {vectors.shape[1]} != meta dimension {meta.dimension}")
        if meta.normalize:
            norms = np.linalg.norm(vectors, axis=1)
            if len(norms) and not np.allclose(norms, 1.0, atol=1e-3):
                raise SemanticConfigError("index metadata says normalized but vectors are not unit length")
        self.items = list(items)
        self.vectors = vectors
        self.meta = meta
        self._corpus_mask = {c: np.array([i.corpus == c for i in self.items]) for c in {i.corpus for i in self.items}}

    def __len__(self) -> int:
        return len(self.items)

    # -- build / persist -----------------------------------------------------

    @classmethod
    def build(cls, items: list[CorpusItem], embedder: Embedder, *, code_version: str = regulus.__version__) -> "SemanticIndex":
        t0 = time.perf_counter()
        vectors = embedder.embed_batch([i.text for i in items])
        cfg = embedder.config
        meta = IndexMeta(
            model_id=cfg.model_id,
            revision=cfg.revision,
            dimension=cfg.dimension,
            pooling=cfg.pooling,
            normalize=cfg.normalize,
            max_length=cfg.max_length,
            query_instruction=cfg.query_instruction,
            embedding_fingerprint=cfg.fingerprint(),
            corpus_sha256=corpus_sha256(items),
            corpus_size=len(items),
            embedded_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            code_version=code_version,
            build_seconds=round(time.perf_counter() - t0, 2),
        )
        return cls(items, vectors, meta)

    def save(self, vectors_path: Path = VECTORS_PATH, meta_path: Path = INDEX_META_PATH) -> None:
        """Write vectors.npy and index_meta.json (Stage 8 layout by default)."""
        vectors_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(vectors_path, self.vectors)
        meta_path.write_text(json.dumps(self.meta.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(
        cls,
        config: EmbeddingConfig,
        *,
        corpus_path: Path = CORPUS_PATH,
        vectors_path: Path = VECTORS_PATH,
        meta_path: Path = INDEX_META_PATH,
    ) -> "SemanticIndex":
        items = load_corpus(corpus_path)
        if not vectors_path.is_file() or not meta_path.is_file():
            raise IndexMismatchError("semantic index not built (run scripts/build_semantic_index.py)")
        meta = IndexMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        current = corpus_sha256(items)
        if meta.corpus_sha256 != current:
            raise IndexMismatchError(f"index built for corpus {meta.corpus_sha256[:12]} but current corpus is {current[:12]}; rebuild")
        if meta.embedding_fingerprint != config.fingerprint():
            raise IndexMismatchError("index built with a different embedding configuration (model, revision, pooling, normalize, max_length or query_instruction); rebuild")
        vectors = np.load(vectors_path)
        return cls(items, vectors, meta)

    @classmethod
    def load_paths(cls, config: EmbeddingConfig, paths) -> "SemanticIndex":
        """Load a named corpus version (see semantic.models.resolve_paths)."""
        return cls.load(config, corpus_path=paths.corpus, vectors_path=paths.vectors, meta_path=paths.index_meta)

    # -- search ------------------------------------------------------------

    def search(self, query_vector: np.ndarray, top_k: int, *, corpus: str | None = None) -> list[tuple[CorpusItem, float]]:
        """Top-k by cosine similarity; ties broken by item id for determinism."""
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        sims = cosine_similarity(query_vector, self.vectors, normalized=self.meta.normalize)
        if corpus is not None:
            mask = self._corpus_mask.get(corpus)
            if mask is None:
                return []
            sims = np.where(mask, sims, -np.inf)
        order = sorted(range(len(sims)), key=lambda i: (-float(sims[i]), self.items[i].id))
        out = []
        for i in order[:top_k]:
            if not np.isfinite(sims[i]):
                break
            out.append((self.items[i], float(sims[i])))
        return out

    def describe(self) -> dict[str, Any]:
        return {"index": "numpy-cosine", "size": len(self.items), **self.meta.to_dict()}
