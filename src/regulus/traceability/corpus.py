"""What a run's evidence came from: the eCFR and guidance snapshot in the database and the semantic index on disk.

A run fingerprint (regulus.dashboard.fingerprint) covers configuration only; two runs with the same configuration can
still read different text after a re-ingest or an index backfill. `corpus_identity` names that text: row counts,
snapshot dates and a SHA-256 over every live row's own content hash, in a fixed order, plus the semantic index's
corpus hash and embedding fingerprint. Read-only; about 0.2 s on the full corpus.
"""

from __future__ import annotations

import json
from typing import Any

ECFR_IDENTITY = """
SELECT count(*) AS rows, count(DISTINCT section_number) AS sections, min(snapshot_date) AS first_snapshot,
       max(snapshot_date) AS last_snapshot,
       encode(sha256(convert_to(string_agg(content_sha256, ',' ORDER BY section_number, ordinal, id), 'UTF8')), 'hex') AS sha256
FROM cfr_records
WHERE removed_on IS NULL AND NOT is_reserved
"""

GUIDANCE_IDENTITY = """
SELECT count(*) AS chunks, count(DISTINCT c.guidance_id) AS documents,
       encode(sha256(convert_to(string_agg(c.content_sha256, ',' ORDER BY c.guidance_id, c.ordinal), 'UTF8')), 'hex') AS sha256
FROM fda_guidance_chunks c
JOIN fda_guidance g ON g.id = c.guidance_id
WHERE g.retrievable
"""


def semantic_index_identity(semantic_corpus: str = "semantic_expanded_v1") -> dict[str, Any]:
    from regulus.retrieval.semantic.models import resolve_paths
    paths = resolve_paths(semantic_corpus)
    if not paths.index_meta.is_file():
        return {"name": paths.name, "available": False}
    meta = json.loads(paths.index_meta.read_text(encoding="utf-8"))
    return {"name": paths.name, "available": True,
            **{k: meta.get(k) for k in ("corpus_sha256", "corpus_size", "embedding_fingerprint", "model_id", "revision", "embedded_at_utc")}}


def corpus_identity(db, *, semantic_corpus: str = "semantic_expanded_v1") -> dict[str, Any]:
    def plain(row: dict[str, Any]) -> dict[str, Any]:
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
    return {"ecfr": plain(db.query(ECFR_IDENTITY)[0]), "guidance": plain(db.query(GUIDANCE_IDENTITY)[0]),
            "semantic_index": semantic_index_identity(semantic_corpus)}
