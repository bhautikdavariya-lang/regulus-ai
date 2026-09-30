"""Local embedding with a pinned Hugging Face encoder via the already-installed
transformers + torch. No external API, no new dependency.

bge-small-en-v1.5: BERT encoder, [CLS] pooling, L2-normalised output, 384
dimensions. Mean pooling is also supported for models that need it.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol, Sequence

import numpy as np

from regulus.retrieval.semantic.models import EmbeddingConfig, SemanticConfigError

log = logging.getLogger("regulus.retrieval.semantic")


class Embedder(Protocol):
    config: EmbeddingConfig

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...

    def describe(self) -> dict[str, Any]: ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim == 1:
        norm = np.linalg.norm(vectors)
        return vectors / norm if norm > 0 else vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def cosine_similarity(query: np.ndarray, matrix: np.ndarray, *, normalized: bool) -> np.ndarray:
    """Cosine similarity of one query vector against every row of `matrix`.

    With `normalized=True` both sides are assumed unit-length and the dot
    product is returned as is; otherwise both are normalised first. The flag
    is explicit so normalised and raw vectors are never silently mixed."""
    q = np.asarray(query, dtype=np.float32)
    m = np.asarray(matrix, dtype=np.float32)
    if q.ndim != 1 or m.ndim != 2 or m.shape[1] != q.shape[0]:
        raise ValueError(f"shape mismatch: query {q.shape}, matrix {m.shape}")
    if not normalized:
        q = l2_normalize(q)
        m = l2_normalize(m)
    return m @ q


class TransformersEmbedder:
    """Loads the pinned model once; `embed_batch` is deterministic on CPU."""

    def __init__(self, config: EmbeddingConfig, *, cache_dir: str | None = None, local_files_only: bool = False) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.config = config
        self._torch = torch
        t0 = time.perf_counter()
        kwargs = {"revision": config.revision, "cache_dir": cache_dir, "local_files_only": local_files_only}
        self.tokenizer = AutoTokenizer.from_pretrained(config.model_id, **kwargs)
        self.model = AutoModel.from_pretrained(config.model_id, **kwargs)
        self.model.eval()
        self.load_seconds = round(time.perf_counter() - t0, 2)
        hidden = int(getattr(self.model.config, "hidden_size", 0))
        if hidden != config.dimension:
            raise SemanticConfigError(f"model hidden size {hidden} != manifest dimension {config.dimension}")
        self.model_revision = getattr(self.model.config, "_commit_hash", None)
        log.info("loaded %s (%s) in %.1fs", config.model_id, self.model_revision, self.load_seconds)

    # -- core ----------------------------------------------------------------

    def _pool(self, hidden: "torch.Tensor", mask: "torch.Tensor") -> "torch.Tensor":  # noqa: F821
        if self.config.pooling == "cls":
            return hidden[:, 0]
        mask = mask.unsqueeze(-1).to(hidden.dtype)
        return (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.config.dimension), dtype=np.float32)
        torch = self._torch
        out: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, len(texts), self.config.batch_size):
                batch = [t if t.strip() else " " for t in texts[start : start + self.config.batch_size]]
                enc = self.tokenizer(batch, padding=True, truncation=True, max_length=self.config.max_length, return_tensors="pt")
                hidden = self.model(**enc).last_hidden_state
                pooled = self._pool(hidden, enc["attention_mask"]).float().cpu().numpy()
                out.append(pooled)
        vectors = np.concatenate(out, axis=0).astype(np.float32)
        if vectors.shape[1] != self.config.dimension:
            raise SemanticConfigError(f"embedding dimension {vectors.shape[1]} != {self.config.dimension}")
        if not np.all(np.isfinite(vectors)):
            raise SemanticConfigError("embedding produced non-finite values")
        return l2_normalize(vectors) if self.config.normalize else vectors

    def embed_query(self, text: str) -> np.ndarray:
        if not text or not text.strip():
            raise ValueError("query must not be empty")
        return self.embed_batch([self.config.query_instruction + text.strip()])[0]

    def describe(self) -> dict[str, Any]:
        return {
            "embedder": "TransformersEmbedder",
            **self.config.to_dict(),
            "resolved_revision": self.model_revision,
            "load_seconds": self.load_seconds,
            "parameters_m": round(sum(p.numel() for p in self.model.parameters()) / 1e6, 1),
        }
