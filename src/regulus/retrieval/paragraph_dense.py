"""Dense (embedding) ranking of single paragraphs: every live paragraph of the cosmetics programme (21 CFR Parts 70-82
and 700-740) and every paragraph of the FD&C Act store.

Why paragraphs (23 Oct 2026, section-resolution benchmark): section-level vectors (regulus.retrieval.section_dense)
embed a section's heading and first ~900 characters, so a section whose answer sits deep inside it is invisible to them
(720.4(b) "The person filing Form FDA 2512 should ..."; FD&C Act 605(e) recordkeeping inside the adverse-event
section). Ranking paragraphs and scoring a section by its best paragraph puts the FD&C Act section that answers a
question first for 23 of 40 Act-keyed dev questions with the lexical ranking (fixed order: 1 of 40).

Each paragraph is embedded with its section heading and, for a sub-paragraph, its parent's lead-in ("(d) A certificate
shall expire ... if:" before "(2) the package is opened"). The model is the repository's pinned BAAI/bge-small-en-v1.5,
loaded from the local cache only; vectors are cached under data/processed/paragraph_dense/ by the sha256 of the texts
and the model revision (about 3,100 paragraphs, built once in about a minute on CPU).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from regulus.retrieval.section_index import COSMETIC_PARTS

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "processed" / "paragraph_dense"
TEXT_CHARS = 900
LEADIN_CHARS = 200

_ROWS_SQL = """
SELECT section_number, part_number, paragraph_path, ordinal, section_heading, body_text
FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved AND part_number = ANY(%(parts)s)
ORDER BY section_number, ordinal
"""


@dataclass(frozen=True)
class Para:
    corpus: str          # "cfr" | "fdca"
    section: str         # "720.4" | "605"
    path: str            # "(b)(1)" ("" for an undivided section)
    ordinal: int         # cfr_records.ordinal, or the statute store row index


def _parent(path: str) -> str | None:
    m = re.match(r"^((?:\([^)]+\))+)\([^)]+\)$", path or "")
    return m.group(1) if m else None


class ParagraphDense:
    def __init__(self, paras: list[Para], vectors: np.ndarray, embedder, texts: list[str] | None = None) -> None:
        self.paras, self.vectors, self.embedder = paras, vectors, embedder
        self.texts = texts or [""] * len(paras)   # the embedded text of each paragraph (heading, lead-in, path, body)
        self.by_section: dict[str, list[int]] = {}
        self.position: dict[Para, int] = {}
        for i, p in enumerate(paras):
            self.by_section.setdefault(p.section, []).append(i)
            self.position[p] = i

    def text(self, para: Para) -> str:
        return self.texts[self.position[para]]

    @classmethod
    def build(cls, db, statute=None, embedder=None) -> "ParagraphDense":
        paras, texts = [], []

        def add(corpus, section, heading, rows):   # rows: [(path, ordinal, body)]
            body_by_path = {p: b for p, _, b in rows}
            for path, ordinal, body in rows:
                lead = body_by_path.get(_parent(path) or "", "") if _parent(path) else ""
                text = f"{heading} " + (f"{lead[:LEADIN_CHARS]} ... " if lead else "") + f"{path} {body}"
                paras.append(Para(corpus, section, path, ordinal))
                texts.append(" ".join(text.split())[:TEXT_CHARS])

        by_sec: dict[str, list] = {}
        heads: dict[str, str] = {}
        for r in db.query(_ROWS_SQL, {"parts": sorted(COSMETIC_PARTS)}):
            by_sec.setdefault(r["section_number"], []).append((r["paragraph_path"] or "", int(r["ordinal"]), " ".join((r["body_text"] or "").split())))
            heads[r["section_number"]] = r["section_heading"] or ""
        for s, rows in by_sec.items():
            add("cfr", s, heads[s], rows)
        if statute is not None:
            for s, idx in statute.by_sec.items():
                rows = []
                for i in idx:
                    r = statute.rows[i]
                    body = " ".join((r["body_text"] or "").split())
                    if r.get("paragraph_heading") and not body.startswith("("):
                        body = f"{r['paragraph_heading']}. {body}"
                    rows.append((r["paragraph_path"] or "", i, body))
                add("fdca", s, f"FD&C Act {statute.heading(s)}.", rows)
        embedder = embedder or _embedder()
        desc = embedder.describe() or {}
        revision = desc.get("resolved_revision") or desc.get("revision")
        key = hashlib.sha256(json.dumps([revision, texts]).encode("utf-8")).hexdigest()[:16]
        path = CACHE_DIR / f"vectors_{key}.npy"
        if path.exists():
            vectors = np.load(path)
        else:
            vectors = embedder.embed_batch(texts).astype(np.float32)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp.npy")
            np.save(tmp, vectors)
            tmp.replace(path)
        return cls(paras, vectors, embedder, texts)

    def similarities(self, question: str) -> np.ndarray:
        return self.vectors @ self.embedder.embed_query(question)

    def rank_sections(self, question: str, corpus: str | None = None, sims: np.ndarray | None = None) -> list[tuple[str, float, Para]]:
        """Sections by their best paragraph's similarity to the question: (section, similarity, that paragraph)."""
        sims = self.similarities(question) if sims is None else sims
        best: dict[str, tuple[float, int]] = {}
        for s, idx in self.by_section.items():
            if corpus is not None and self.paras[idx[0]].corpus != corpus:
                continue
            j = max(idx, key=lambda i: sims[i])
            best[s] = (float(sims[j]), j)
        return [(s, v, self.paras[j]) for s, (v, j) in sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))]

    def section_paragraphs(self, question: str, section: str, sims: np.ndarray | None = None) -> list[tuple[Para, float]]:
        """One section's paragraphs, most similar first."""
        sims = self.similarities(question) if sims is None else sims
        return sorted(((self.paras[i], float(sims[i])) for i in self.by_section.get(section, ())), key=lambda x: -x[1])


def _embedder():
    from regulus.retrieval.section_dense import _embedder as section_embedder

    return section_embedder()


_LOCK = threading.Lock()
_CACHE: dict[int, ParagraphDense | None] = {}


def paragraph_dense(db) -> ParagraphDense | None:
    """The paragraph index for this database connection; None when the embedding model cannot be loaded (callers then
    rank without it - it is an aid, never a requirement)."""
    from regulus.retrieval.statute import statute_index

    with _LOCK:
        if id(db) not in _CACHE:
            try:
                _CACHE[id(db)] = ParagraphDense.build(db, statute_index(db))
            except Exception:  # noqa: BLE001 - an aid only
                _CACHE[id(db)] = None
        return _CACHE[id(db)]
