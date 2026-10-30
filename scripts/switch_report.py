"""Status report of the switch registry (src/regulus/rag/switches.yaml): what is on in DEFAULT, what waits for a
decision, what was rejected - and where the registry disagrees with the code.

    python scripts/switch_report.py                      # summary + every switch, grouped by status
    python scripts/switch_report.py --status candidate   # one status (default / candidate / experimental / rejected)
    python scripts/switch_report.py --stage selection    # one stage (docs/STAGES.md)
    python scripts/switch_report.py --run full300d       # the switches a recorded run added on top of DEFAULT
    python scripts/switch_report.py --promote-list       # the REGULUS_VALIDATOR_PRECISION string for DEFAULT + candidates
    python scripts/switch_report.py --check              # consistency problems only; exit 1 if any

Reads files only: no model, no database.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.rag import switch_registry as R  # noqa: E402

WIDTH = 118


def _line(code: str, e: dict, verbose: bool) -> list[str]:
    intro = e.get("introduced") or {}
    flag = " *" if e.get("notes") else ""
    head = f"  {code:<5} {e.get('stage', '?'):<13} {str(intro.get('date', '')):<10}  "
    out = [head + textwrap.shorten(str(e.get("purpose", "")), WIDTH - len(head), placeholder=" ...") + flag]
    if verbose:
        for key in ("evidence", "notes"):
            if e.get(key):
                out += textwrap.wrap(f"{key}: {' '.join(str(e[key]).split())}", WIDTH, initial_indent=" " * 8,
                                     subsequent_indent=" " * 10)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--status", choices=R.STATUSES)
    ap.add_argument("--stage", choices=R.STAGES)
    ap.add_argument("--run", help="a run named in meta.runs (full300c, full300d)")
    ap.add_argument("--check", action="store_true", help="only the registry/code consistency problems")
    ap.add_argument("--promote-list", action="store_true", help="DEFAULT + every candidate, as one switch string")
    ap.add_argument("--brief", action="store_true", help="one line per switch, no evidence")
    args = ap.parse_args(argv)

    reg = R.load()
    switches: dict = reg["switches"]
    problems = R.problems(reg)
    if args.check:
        print("\n".join(problems) if problems else "registry consistent with the code, the docstring and DEFAULT")
        return 1 if problems else 0
    if args.promote_list:
        print(",".join(c for c, e in switches.items() if e["status"] in ("default", "candidate")))
        return 0

    meta = reg.get("meta") or {}
    chosen = dict(switches)
    title = "all switches"
    if args.run:
        run = (meta.get("runs") or {}).get(args.run)
        if run is None:
            print(f"unknown run {args.run!r}; known: {', '.join(meta.get('runs') or {})}", file=sys.stderr)
            return 2
        extra = list(run.get("extra") or ())
        base = run.get("extra_over")
        if base:
            extra = list((meta["runs"][base].get("extra") or ())) + extra
        chosen = {c: switches[c] for c in extra if c in switches}
        title = f"run {args.run} ({run.get('date', '')}): DEFAULT + {len(chosen)}"
        print(f"{args.run}: {' '.join(str(run.get('result', '')).split())}")
    if args.status:
        chosen = {c: e for c, e in chosen.items() if e["status"] == args.status}
    if args.stage:
        chosen = {c: e for c, e in chosen.items() if e["stage"] == args.stage}

    print(f"Switch registry as of {meta.get('as_of')}, code {meta.get('code_ref')} - {len(switches)} switches")
    counts = Counter(e["status"] for e in switches.values())
    print("  " + "   ".join(f"{s}: {counts.get(s, 0)}" for s in R.STATUSES))
    stages = Counter(e["stage"] for e in switches.values() if e["status"] != "rejected")
    print("  live (not rejected) by stage: " + ", ".join(f"{s} {n}" for s, n in stages.most_common()))
    print(f"\n{title}" + (f", status {args.status}" if args.status else "") + (f", stage {args.stage}" if args.stage else ""))
    for status in R.STATUSES:
        group = {c: e for c, e in chosen.items() if e["status"] == status}
        if not group:
            continue
        print(f"\n[{status}] {len(group)}")
        for code, e in sorted(group.items(), key=lambda kv: (R.STAGES.index(kv[1]["stage"]), str(kv[1]["introduced"]["date"]), kv[0])):
            print("\n".join(_line(code, e, verbose=not args.brief)))
    flagged = {c: e for c, e in switches.items() if e.get("notes") and e["status"] != "default"}
    if flagged and not (args.status or args.stage or args.run):
        print("\n* notes worth reading before a promotion decision:")
        for code, e in flagged.items():
            print(textwrap.fill(f"{code}: {' '.join(str(e['notes']).split())}", WIDTH, initial_indent="  ",
                                subsequent_indent="    "))
    others = reg.get("other_switches") or {}
    if others and not (args.status or args.stage or args.run):
        print("\nother switches (own environment variables)")
        for code, e in others.items():
            print(f"  {code:<5} {e.get('status', ''):<13} {e.get('variable', '')}")
    print("\nconsistency: " + ("OK" if not problems else f"{len(problems)} problem(s) - run with --check"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
