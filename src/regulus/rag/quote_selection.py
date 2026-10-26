"""Which supplied paragraphs a composed answer quotes (Q1, FP1, RS1; 26 Oct 2026).

A composed answer quotes the paragraphs of the identified provision that speak to the question. Ranking them by shared
words picked the wrong ones on recorded follow-ups: for "the special deposit for studies" 70.19(a), (b) and (l) - which
share "deposit" and "petition" - instead of (m), which states it; for "what makes a package tamper-resistant" 700.25(a),
the long background paragraph, instead of (b). Ranking by meaning (the repository's pinned bge-small embedding model,
local cache only, the same one the section and paragraph indexes use) puts (m) and (b) first.

Each paragraph is embedded with its citation, so "(b)" carries its section's subject. Similarity decides; shared subject
words break ties. When the model cannot be loaded, shared words alone decide - the composer never fails because of it.
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()
_EMBEDDER: list = []      # [embedder or None], loaded once


def _embedder():
    with _LOCK:
        if not _EMBEDDER:
            try:
                from regulus.retrieval.section_dense import _embedder as load

                _EMBEDDER.append(load())
            except Exception:  # noqa: BLE001 - an aid only
                _EMBEDDER.append(None)
        return _EMBEDDER[0]


def rank(question: str, items: list[tuple[str, str]]) -> list[int]:
    """`items`: (citation, paragraph text). Their indices, most relevant to the question first."""
    from regulus.rag.conversation import subject_words

    if not items:
        return []
    asked = subject_words(question)
    overlap = [len(asked & subject_words(t)) for _, t in items]
    sims = None
    model = _embedder()
    if model is not None:
        try:
            import numpy as np

            vectors = model.embed_batch([f"{c}: {t[:900]}" for c, t in items])
            sims = vectors @ model.embed_query(question)
            sims = [float(x) for x in np.asarray(sims).ravel()]
        except Exception:  # noqa: BLE001 - an aid only
            sims = None
    if sims is None:
        return sorted(range(len(items)), key=lambda i: (-overlap[i], i))
    return sorted(range(len(items)), key=lambda i: (-round(sims[i], 3), -overlap[i], i))
