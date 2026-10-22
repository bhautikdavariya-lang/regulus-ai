"""Build the FD&C Act paragraph store used by regulus.retrieval.statute from fetched govinfo U.S. Code text.

    python scripts/build_statute_store.py [--src data/raw/statute_fdca] [--out data/processed/statute_fdca]

Input: <src>/usc_title21/21usc*.txt and <src>/usc_fetch_log.jsonl, as written by the govinfo fetcher
(artifacts/benchmark_verification/.../work/tools/fetch_usc.py: official USCODE most-recent edition, one file per
section with its SOURCE URL and FDCA label). Output: rows.jsonl (one paragraph per line, text verbatim) and
manifest.json (per file: sha256, source URL, retrieval time, row count). Nothing is written to the database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.ingestion.statute import parse_file  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "data/raw/statute_fdca"))
    ap.add_argument("--out", default=str(ROOT / "data/processed/statute_fdca"))
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    log = {}
    if (src / "usc_fetch_log.jsonl").exists():
        for line in (src / "usc_fetch_log.jsonl").read_text().splitlines():
            rec = json.loads(line)
            if "file" in rec:
                log[rec["file"]] = rec
    out.mkdir(parents=True, exist_ok=True)
    files, n = [], 0
    with open(out / "rows.jsonl", "w", encoding="utf-8") as f:
        for path in sorted((src / "usc_title21").glob("21usc*.txt")):
            rows = parse_file(path)
            for r in rows:
                f.write(json.dumps({"fdca_section": r.fdca_section, "usc_section": r.usc_section, "paragraph_path": r.paragraph_path,
                                    "ordinal": r.ordinal, "heading": r.heading, "paragraph_heading": r.paragraph_heading,
                                    "body_text": r.body_text, "top_caption": r.top_caption, "label": r.label, "source_url": r.source_url,
                                    "content_sha256": r.content_sha256}, ensure_ascii=False) + "\n")
            n += len(rows)
            meta = log.get(path.name, {})
            files.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": len(rows),
                          "fdca_section": rows[0].fdca_section, "usc_section": rows[0].usc_section, "heading": rows[0].heading,
                          "source_url": rows[0].source_url, "retrieved_utc": meta.get("retrieved_utc"),
                          "html_sha256": meta.get("html_sha256")})
    manifest = {"rows": n, "files": files, "rows_sha256": hashlib.sha256((out / "rows.jsonl").read_bytes()).hexdigest(),
                "edition": "United States Code, 2024 edition (govinfo USCODE-2024-title21)"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{n} paragraphs from {len(files)} sections -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
