"""Stage 13 grounding metrics side by side across saved evaluation runs.

Reports unsupported answers and false refusals separately, because the point
of Stage 13 is to reduce the first without inflating the second.

Usage:
    python scripts/compare_grounding.py data/evaluation/results/rag-stage7_*.json data/evaluation/results/stage12_v1/rag-stage12-lora_*.json
    python scripts/compare_grounding.py A.json B.json --ids       # list the affected question ids
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from regulus.evaluation.grounding_eval import SUMMARY_ORDER, evaluate_grounding


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+", help="saved evaluation result files")
    p.add_argument("--ids", action="store_true", help="also list the question ids behind each count")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    runs, names = [], []
    for raw in args.runs:
        path = Path(raw)
        if not path.is_file():
            print(f"not found: {raw}", file=sys.stderr)
            return 2
        data = json.loads(path.read_text(encoding="utf-8"))
        runs.append(evaluate_grounding(data).to_dict())
        names.append(str(data.get("run", {}).get("pipeline", path.stem))[:22])

    width = max(22, *(len(n) for n in names)) + 2
    print("".rjust(34) + "".join(n.rjust(width) for n in names))
    for key in SUMMARY_ORDER:
        cells = []
        for r in runs:
            v = r.get(key)
            cells.append(("n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))).rjust(width))
        print(key.replace("_", " ").ljust(34) + "".join(cells))

    if args.ids:
        for key in ("unsupported_answer_ids", "false_refusal_ids", "ungrounded_identifier_ids", "degenerate_ids", "gate_refusal_ids"):
            print()
            print(key.replace("_", " ") + ":")
            for name, r in zip(names, runs):
                print(f"  {name:<24} {r.get(key)}")
    print()
    print("unsupported answers: questions the benchmark marks acknowledge_uncertainty that received content instead.")
    print("false refusals:      questions marked answer that were declined. Both must be read together.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
