"""Show what Regulus understands a question to ask for (Stage 1 debug tool).

    python scripts/plan.py "What does 21 CFR 820.10(b)(1) through (b)(4) require?"
    python scripts/plan.py --json "820.10(b)(1), (b)(2), and 820.10(b)(4)"

Prints the trace question -> mentions -> ranges -> requirements, or the
QueryPlan as JSON. No database, no model: this is the deterministic parser
only, so it runs instantly and is safe to use while anything else is running.
"""

from __future__ import annotations

import argparse
import json
import sys

from regulus.planning import plan_query


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question", nargs="+", help="the question (quote it, or pass the words separately)")
    p.add_argument("--json", action="store_true", help="print the QueryPlan as JSON instead of the trace")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    plan = plan_query(" ".join(args.question))
    if args.json:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(plan.explain())
    return 0


if __name__ == "__main__":
    sys.exit(main())
