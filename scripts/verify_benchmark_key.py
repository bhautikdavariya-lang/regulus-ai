"""Verify the acceptance benchmark's draft answer key against the sources.

    python scripts/verify_benchmark_key.py
    python scripts/verify_benchmark_key.py --verifier "Name, Title"
    python scripts/verify_benchmark_key.py --workbook path/to/workbook.xlsx

Reads the workbook and the read-only regulatory snapshot, checks every row on
the dimensions a machine can settle, and writes a timestamped verification
artifact under `artifacts/benchmark_verification/`. Previous runs are never
overwritten.

Nothing is written to the workbook, the database or any evaluation artifact.
No model is loaded. The two dimensions that need a qualified reviewer -
whether the substance of the answer is right, and whether the key names every
governing provision - always come back REQUIRES_SME, so an unattended run can
never mark the key verified.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from regulus.evaluation.acceptance_benchmark import (  # noqa: E402
    DEFAULT_WORKBOOK,
    load_acceptance_benchmark,
)
from regulus.evaluation.key_verification import (  # noqa: E402
    CONTRADICTED,
    DatabaseSources,
    verify_benchmark,
)
from regulus.retrieval import Database  # noqa: E402

OUT_ROOT = ROOT / "artifacts" / "benchmark_verification"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", default=str(ROOT / DEFAULT_WORKBOOK))
    parser.add_argument("--verifier", default=None,
                        help="the person accountable for the reviewed dimensions")
    parser.add_argument("--out", default=str(OUT_ROOT))
    args = parser.parse_args()

    benchmark = load_acceptance_benchmark(args.workbook)
    print(f"benchmark : {benchmark.label}")
    print(f"identity  : {benchmark.benchmark_key}")

    db = Database.from_env()
    db.connect()
    status = db.status()
    if str(status.get("default_transaction_read_only", "")).lower() not in ("on", "true", "1"):
        print("refusing to run: the database connection is not read-only", file=sys.stderr)
        return 2
    print(f"database  : {status.get('database')} (read-only)")

    artifact = verify_benchmark(benchmark, DatabaseSources(db), verifier=args.verifier)
    summary = artifact.summary()

    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) / run
    out.mkdir(parents=True, exist_ok=True)
    (out / "verification.json").write_text(
        json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nrows          : {summary['rows']}")
    print(f"by status     : {summary['by_status']}")
    print(f"verified      : {summary['verified_rows']}")
    print(f"contradicted  : {summary['contradicted_rows']} {summary['contradicted_ids']}")
    print("\nby dimension:")
    for dimension, counts in summary["by_dimension"].items():
        print(f"  {dimension:22} {counts}")

    if artifact.contradicted:
        print("\ncontradictions — the draft key disagrees with the sources:")
        for row in artifact.contradicted:
            for finding in row.contradictions:
                print(f"  {row.question_id}  [{finding.dimension}]  {finding.detail}")

    print(f"\nartifact: {out / 'verification.json'}")
    print(f"scoring : {summary['scoring_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
