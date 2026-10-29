"""Hypothetical-question index (doc2query) for the section candidate list - HQ1, step D (29 Oct 2026).

Each section is represented by the plain-language questions the model wrote for it at index time
(scripts/build_section_questions.py); a user's question is compared with those questions, not with the legal text, so
"How long do we keep supplier records?" can find a section that says "retain ... for 2 years". The same pinned
bge-small embedder as regulus.retrieval.section_dense; vectors are cached under data/processed/section_questions/ keyed by
the sha256 of the questions and the model revision. A section's score is its best question's cosine similarity.

None when the questions file or the embedding model is missing: promotion then works as before.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import numpy as np

QUESTIONS = Path(__file__).resolve().parents[3] / "data" / "processed" / "section_questions" / "questions.jsonl"
CACHE_DIR = QUESTIONS.parent


class SectionQuestions:
    def __init__(self, owners: list[str], parts: dict[str, str], vectors: np.ndarray, embedder) -> None:
        self.owners, self.parts, self.vectors, self.embedder = owners, parts, vectors, embedder

    @classmethod
    def load(cls, path: Path = QUESTIONS, embedder=None) -> "SectionQuestions":
        rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
        owners, texts, parts = [], [], {}
        for r in rows:
            for q in r.get("questions") or []:
                owners.append(r["section"])
                texts.append(q)
            parts[r["section"]] = str(r.get("part") or r["section"].split(".")[0])
        if not texts:
            raise ValueError(f"{path}: no questions")
        if embedder is None:
            from regulus.retrieval.section_dense import _embedder

            embedder = _embedder()
        describe = embedder.describe() if hasattr(embedder, "describe") else {}
        revision = (describe or {}).get("resolved_revision") or (describe or {}).get("revision")
        key = hashlib.sha256(json.dumps([revision, owners, texts]).encode("utf-8")).hexdigest()[:16]
        cache = CACHE_DIR / f"vectors_{key}.npy"
        if cache.exists():
            vectors = np.load(cache)
        else:
            vectors = np.asarray(embedder.embed_batch(texts), dtype=np.float32)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp.npy")
            np.save(tmp, vectors)
            tmp.replace(cache)
        return cls(owners, parts, vectors, embedder)

    def rank(self, question: str, limit: int = 4, parts=None, min_score: float = 0.0) -> list[tuple[str, float]]:
        """(section, best question similarity), best first, at least `min_score`, inside `parts` when given."""
        if not (question or "").strip():
            return []
        sims = self.vectors @ np.asarray(self.embedder.embed_query(question), dtype=np.float32)
        best: dict[str, float] = {}
        for i in np.argsort(-sims):
            s, score = self.owners[i], float(sims[i])
            if score < min_score:
                break
            if s in best or (parts and self.parts.get(s) not in parts):
                continue
            best[s] = score
            if len(best) >= limit:
                break
        return list(best.items())


_LOCK = threading.Lock()
_CACHE: dict[str, SectionQuestions | None] = {}


def section_questions(path: Path = QUESTIONS) -> SectionQuestions | None:
    """The index for `path`, built once per process; None without the file or the model (an aid, never a requirement)."""
    with _LOCK:
        key = str(path)
        if key not in _CACHE:
            try:
                _CACHE[key] = SectionQuestions.load(path) if Path(path).is_file() else None
            except Exception:  # noqa: BLE001 - an aid only
                _CACHE[key] = None
        return _CACHE[key]
