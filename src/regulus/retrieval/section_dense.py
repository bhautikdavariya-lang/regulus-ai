"""Dense (embedding) ranking of the cosmetic-programme sections, to widen section promotion's candidate list.

Keyword ranking misses paraphrases ("How soon will FDA tell us whether it's accepted?" is 21 CFR 71.2 "Notice of
filing of petition"). On the cosmetics bank (22 Oct 2026) the primary key section was among the lexical top 14 for
129/143 unseen questions and among the lexical top 14 plus the dense top 8 for 138/143 (seen: 73 -> 77 of 80).

The model is the repository's pinned BAAI/bge-small-en-v1.5 (the semantic manifest, CLS pooling, normalized; 384
dimensions), loaded from the local cache only. Each section of Parts 70-82 and 700-740 is one document: its heading,
part and subpart titles and its first ~900 characters. The 343 vectors are built once per corpus content (about 11 s
on CPU) and cached under data/processed/section_dense/ keyed by the sha256 of the documents and the model revision.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import numpy as np

from regulus.retrieval.section_index import COSMETIC_PARTS

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "processed" / "section_dense"
MODEL_CACHE = Path(__file__).resolve().parents[3] / "models"
DOC_CHARS = 900

_ROWS_SQL = """
SELECT r.section_number, r.part_number, r.section_heading, r.parent_headings, r.body_text, p.title AS part_title
FROM cfr_records r LEFT JOIN cfr_parts p ON p.number = r.part_number
WHERE r.removed_on IS NULL AND NOT r.is_reserved AND r.part_number = ANY(%(parts)s)
ORDER BY r.section_number, r.ordinal
"""


class SectionDense:
    def __init__(self, names: list[str], vectors: np.ndarray, embedder) -> None:
        self.names, self.vectors, self.embedder = names, vectors, embedder

    @classmethod
    def build(cls, db, embedder=None) -> "SectionDense":
        docs: dict[str, dict] = {}
        for r in db.query(_ROWS_SQL, {"parts": sorted(COSMETIC_PARTS)}):
            d = docs.setdefault(r["section_number"], {
                "heading": r["section_heading"] or "", "part": r["part_title"] or "",
                "sub": " ".join(h for h in (r["parent_headings"] or []) if (h or "").lower().startswith("subpart")), "text": ""})
            if len(d["text"]) < DOC_CHARS:
                d["text"] += " " + (r["body_text"] or "")
        names = list(docs)
        texts = [f"{d['heading']} ({d['part']}; {d['sub']}) {d['text'][:DOC_CHARS]}" for d in docs.values()]
        embedder = embedder or _embedder()
        revision = (embedder.describe() or {}).get("resolved_revision") or (embedder.describe() or {}).get("revision")
        key = hashlib.sha256(json.dumps([revision, names, texts]).encode("utf-8")).hexdigest()[:16]
        path = CACHE_DIR / f"vectors_{key}.npy"
        if path.exists():
            vectors = np.load(path)
        else:
            vectors = embedder.embed_batch(texts).astype(np.float32)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp.npy")
            np.save(tmp, vectors)
            tmp.replace(path)
        return cls(names, vectors, embedder)

    def rank(self, question: str, limit: int = 8) -> list[str]:
        if not (question or "").strip():
            return []
        sims = self.vectors @ self.embedder.embed_query(question)
        return [self.names[i] for i in np.argsort(-sims)[:limit]]


def _embedder():
    from regulus.retrieval.semantic.embedder import TransformersEmbedder
    from regulus.retrieval.semantic.models import load_manifest

    return TransformersEmbedder(load_manifest().embedding, cache_dir=str(MODEL_CACHE), local_files_only=True)


_LOCK = threading.Lock()
_CACHE: dict[int, SectionDense | None] = {}


def section_dense(db) -> SectionDense | None:
    """The dense section index for this database connection; None when the embedding model cannot be loaded (the
    lexical candidates are then used alone - promotion never fails because of it)."""
    with _LOCK:
        if id(db) not in _CACHE:
            try:
                _CACHE[id(db)] = SectionDense.build(db)
            except Exception:  # noqa: BLE001 - an aid only
                _CACHE[id(db)] = None
        return _CACHE[id(db)]
