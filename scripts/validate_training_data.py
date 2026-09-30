"""Validate the Stage 11 dataset files (structure, provenance, citations,
negatives, leakage, secrets) and write validation_<v>.json next to them.

Usage:
    python scripts/validate_training_data.py            # verifies provenance against the read-only database
    python scripts/validate_training_data.py --offline  # structural / leakage / secret checks only
Exit code 1 when any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys

import psycopg

from regulus.retrieval import Database, DatabaseConfigError
from regulus.training import TrainingConfigError, dataset_paths, load_training_config, validate_dataset


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--version", default=None)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--offline", action="store_true", help="do not connect to the database")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        config = load_training_config(args.config, version=args.version, output_dir=args.output_dir)
    except TrainingConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    paths = dataset_paths(config)
    db = None
    if not args.offline:
        try:
            db = Database.from_env()
            db.connect()
        except DatabaseConfigError as exc:
            print(f"database not configured ({exc}); running offline checks only")
            db = None
        except psycopg.OperationalError as exc:
            print(f"database unavailable ({type(exc).__name__}); running offline checks only")
            db = None
    try:
        report = validate_dataset(paths, config, db)
    finally:
        if db is not None:
            db.close()
    out = config.output_dir / f"validation_{config.version}.json"
    out.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("Dataset validation")
    print("==================")
    for split, name in report.files.items():
        print(f"{split:<12} {name}")
    print()
    for k, v in report.checks.items():
        print(f"{k:<36} {v}")
    print()
    s = report.stats
    if s:
        print(f"{'total examples':<36} {s['total']}")
        print(f"{'by split':<36} {s['by_split']}")
        print(f"{'by category':<36} {s['by_category']}")
        print(f"{'by source type':<36} {s['examples_by_source_type']}")
        print(f"{'negative examples':<36} {s['negative_examples']}")
    if report.errors:
        print()
        print(f"ERRORS ({len(report.errors)} shown):")
        for e in report.errors[:50]:
            print(f"  - {e}")
    print()
    print(f"RESULT: {'PASS' if report.ok else 'FAIL'}  (report: {out.name})")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
