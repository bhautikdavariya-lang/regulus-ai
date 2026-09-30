"""Extract a controlled semantic evaluation corpus from the read-only database.

Selection comes from the corpus manifest (tracked); output goes to that
corpus version's gitignored generated/ folder and is reproducible from the
manifest and the database.

    python scripts/build_semantic_corpus.py                                   # Stage 8 corpus (data/evaluation/semantic/manifest.yaml)
    python scripts/build_semantic_corpus.py --semantic-corpus semantic_expanded_v1   # Stage 10 corpus (data/evaluation/semantic/semantic_expanded_v1/)

Manifest version 1 lists sections and dockets with roles (Stage 8).
Manifest version 2 selects scope (subchapters, parts, sections, sectors,
dockets) and names the benchmark targets; everything else is a distractor.
The build fails on duplicate keys, empty text or missing citation identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

from regulus.retrieval import Database, DatabaseConfigError
from regulus.retrieval.semantic.index import corpus_sha256
from regulus.retrieval.semantic.models import CorpusItem, SemanticConfigError, load_manifest, resolve_paths, text_sha256, validate_items

ECFR_COLUMNS = """
SELECT r.title, r.chapter, r.subchapter_code, r.part_number, r.section_number, r.paragraph_path,
       r.path_ordinal, r.ordinal, r.section_heading, r.parent_headings, r.body_text, r.ecfr_permalink,
       r.govinfo_pdf_url, r.snapshot_date, r.is_reserved, p.title AS part_title
FROM cfr_records r
LEFT JOIN cfr_parts p ON p.number = r.part_number
"""
ECFR_V1 = ECFR_COLUMNS + """
WHERE r.section_number = ANY(%(sections)s) AND r.removed_on IS NULL AND NOT r.is_reserved
ORDER BY r.section_number, r.ordinal
"""
ECFR_V2 = ECFR_COLUMNS + """
WHERE (r.subchapter_code = ANY(%(subchapters)s) OR r.part_number = ANY(%(parts)s) OR r.section_number = ANY(%(sections)s))
  AND r.removed_on IS NULL AND NOT r.is_reserved
ORDER BY r.section_number, r.ordinal
"""
GUIDANCE_COLUMNS = """
SELECT c.body_text, c.title_text, c.ordinal, c.start_offset,
       g.title, g.docket_number, g.status, g.center, g.sector, g.issued_on, g.source_url,
       g.anchor_part, g.anchor_section, g.doc_class, g.retrievable
FROM fda_guidance_chunks c
JOIN fda_guidance g ON g.id = c.guidance_id
"""
GUIDANCE_V1 = GUIDANCE_COLUMNS + """
WHERE g.docket_number = ANY(%(dockets)s) AND g.retrievable AND c.ordinal < %(cap)s
ORDER BY g.docket_number, g.source_url, c.ordinal
"""
GUIDANCE_V2 = GUIDANCE_COLUMNS + """
WHERE (g.sector = ANY(%(sectors)s) OR g.docket_number = ANY(%(dockets)s)) AND g.retrievable AND c.ordinal < %(cap)s
ORDER BY g.source_url, c.ordinal
"""


def _meta(row: dict, drop: tuple[str, ...] = ("body_text",)) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items() if k not in drop}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--semantic-corpus", default=None, help="corpus version name (default: Stage 8 layout)")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    paths = resolve_paths(args.semantic_corpus)
    manifest = load_manifest(paths.manifest)
    try:
        db = Database.from_env()
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2

    with db:
        if manifest.is_scope_based:
            ecfr_rows = db.query(ECFR_V2, {"subchapters": list(manifest.ecfr_subchapters), "parts": list(manifest.ecfr_parts), "sections": manifest.sections()})
            guidance_rows = db.query(GUIDANCE_V2, {"sectors": list(manifest.guidance_sectors), "dockets": manifest.dockets(), "cap": manifest.guidance_max_chunks_per_document})
        else:
            ecfr_rows = db.query(ECFR_V1, {"sections": manifest.sections()})
            guidance_rows = db.query(GUIDANCE_V1, {"dockets": manifest.dockets(), "cap": manifest.guidance_max_chunks_per_document})

    items: list[CorpusItem] = []
    for row in ecfr_rows:
        meta = _meta(row)
        meta["parent_headings"] = list(row.get("parent_headings") or [])
        key = f"ecfr:{row['section_number']}:{row.get('paragraph_path') or ''}:{row.get('path_ordinal', 0)}"
        items.append(CorpusItem(key, "ecfr", row["body_text"], text_sha256(row["body_text"]), manifest.role_of_section(row["section_number"]), meta))
    for row in guidance_rows:
        key = f"fda_guidance:{row['source_url']}#{row['ordinal']}"
        items.append(CorpusItem(key, "fda_guidance", row["body_text"], text_sha256(row["body_text"]), manifest.role_of_docket(row["docket_number"]), _meta(row)))

    try:
        counts = validate_items(items)
    except SemanticConfigError as exc:
        print(f"CORPUS INTEGRITY ERROR: {exc}", file=sys.stderr)
        return 1

    found_sections = {r["section_number"] for r in ecfr_rows}
    found_dockets = {r["docket_number"] for r in guidance_rows if r["docket_number"]}
    missing_sections = sorted((set(manifest.sections()) | set(manifest.target_sections)) - found_sections)
    missing_dockets = sorted((set(manifest.dockets()) | set(manifest.target_dockets)) - found_dockets)
    if manifest.is_scope_based and (missing_sections or missing_dockets):
        print(f"CORPUS INTEGRITY ERROR: manifest targets/sections not found in snapshot: sections={missing_sections} dockets={missing_dockets}", file=sys.stderr)
        return 1

    paths.generated.mkdir(parents=True, exist_ok=True)
    with paths.corpus.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    emb = manifest.embedding
    meta = {
        "corpus_name": paths.name,
        "corpus_version": manifest.version,
        "rationale": manifest.rationale,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "manifest_sha256": hashlib.sha256(paths.manifest.read_bytes()).hexdigest(),
        "corpus_sha256": corpus_sha256(items),
        **counts,
        "target_distractor_ratio": round(counts["targets"] / counts["distractors"], 3) if counts["distractors"] else None,
        "ecfr_sections_found": len(found_sections),
        "ecfr_parts_found": len({r["part_number"] for r in ecfr_rows}),
        "ecfr_subchapters_found": sorted({r["subchapter_code"] for r in ecfr_rows}),
        "guidance_documents_found": len({r["source_url"] for r in guidance_rows}),
        "guidance_sectors_found": sorted({r["sector"] for r in guidance_rows if r["sector"]}),
        "missing_sections": missing_sections,
        "missing_dockets": missing_dockets,
        "embedding": {"model_id": emb.model_id, "revision": emb.revision, "dimension": emb.dimension, "pooling": emb.pooling, "normalize": emb.normalize},
        "scope": manifest.scope_summary(),
    }
    paths.corpus_meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "scope"}, indent=2))
    print(f"corpus written to {paths.corpus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
