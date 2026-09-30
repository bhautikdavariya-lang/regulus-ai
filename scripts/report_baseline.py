"""Print a human-readable summary of a saved evaluation run.

Usage:
    python scripts/report_baseline.py                     # latest result file
    python scripts/report_baseline.py path/to/result.json
    python scripts/report_baseline.py --answers           # include every Q/A
    python scripts/report_baseline.py --answers --category hallucination
    python scripts/report_baseline.py --answers --ids baseline-023 baseline-027
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from regulus.evaluation.dataset import CATEGORIES
from regulus.evaluation.report import render_answers, render_summary
from regulus.evaluation.results import DEFAULT_RESULTS_DIR, ResultsError, latest_result, load_run


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("result", nargs="?", default=None, help="results JSON file (default: newest in results dir)")
    p.add_argument("--results-dir", default=None, help="where to look for the newest result")
    p.add_argument("--answers", action="store_true", help="print each question, model answer and reference")
    p.add_argument("--category", choices=sorted(CATEGORIES), default=None, help="filter answers by category")
    p.add_argument("--ids", nargs="+", default=None, help="filter answers by question id")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    path = Path(args.result) if args.result else latest_result(Path(args.results_dir) if args.results_dir else DEFAULT_RESULTS_DIR)
    if path is None:
        print("No result files found. Run scripts/evaluate_baseline.py first.", file=sys.stderr)
        return 1
    try:
        run = load_run(path)
    except ResultsError as exc:
        print(f"RESULTS ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"File: {path}")
    print()
    print(render_summary(run))
    if args.answers or args.category or args.ids:
        print()
        print("Questions and answers")
        print("=====================")
        print(render_answers(run, category=args.category, ids=set(args.ids) if args.ids else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
