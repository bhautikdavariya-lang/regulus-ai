"""Build the Stage 11 instruction-tuning dataset from the read-only database.

Usage:
    python scripts/prepare_training_data.py
    python scripts/prepare_training_data.py --target 10000 --seed 42
    python scripts/prepare_training_data.py --config configs/training.yaml --output-dir data/training/datasets

Writes training_<v>.jsonl, validation_<v>.jsonl, test_<v>.jsonl and
manifest_<v>.json. Nothing is written to the database.
"""

from __future__ import annotations

import argparse
import sys
import time

import psycopg

from regulus.retrieval import Database, DatabaseConfigError
from regulus.training import PipelineError, TrainingConfigError, load_training_config, prepare_dataset
from regulus.training.sources import SourceError


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None, help="training config YAML (default: configs/training.yaml)")
    p.add_argument("--target", type=int, default=None, help="override dataset.target_examples")
    p.add_argument("--seed", type=int, default=None, help="override dataset.seed")
    p.add_argument("--version", default=None, help="override dataset.version (file suffix)")
    p.add_argument("--output-dir", default=None, help="override dataset.output_dir")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        config = load_training_config(args.config, target_examples=args.target, seed=args.seed, version=args.version, output_dir=args.output_dir)
    except TrainingConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        db = Database.from_env()
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Config: {config.source} target={config.target_examples} seed={config.seed} version={config.version}")
    t0 = time.perf_counter()
    try:
        with db:
            result = prepare_dataset(config, db)
    except (SourceError, PipelineError) as exc:
        print(f"PIPELINE ERROR: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"DATABASE ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1
    m = result.manifest
    print(f"Database: {m['database']['database']} read-only={m['database']['default_transaction_read_only']} snapshot={m['database']['snapshot'].get('ecfr_snapshot_date')}")
    print("Sources: " + ", ".join(f"{k}={v}" for k, v in m["source_counts"].items()))
    print()
    print(f"{'category':<20} {'candidates':>10} {'dedup':>8} {'bench-x':>8} {'target':>7} {'selected':>9}")
    for cat, row in m["generation"]["per_category"].items():
        print(f"{cat:<20} {row['candidates']:>10} {row['after_dedup']:>8} {row['benchmark_excluded']:>8} {row['target']:>7} {row['selected']:>9}")
    s = m["stats"]
    print()
    print(f"Total examples: {s['total']}  train={s['by_split']['train']} validation={s['by_split']['validation']} test={s['by_split']['test']}")
    print(f"Negative/abstention: {s['negative_examples']}  unique CFR citations: {s['unique_cfr_citations']}  unique guidance documents: {s['unique_guidance_documents']}")
    print(f"Dataset sha256: {m['dataset_sha256']}")
    for split, f in m["files"].items():
        print(f"  {split:<10} {f['examples']:>6}  {f['path']}")
    print(f"  manifest          {result.paths['manifest'].name}")
    print(f"Elapsed: {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
