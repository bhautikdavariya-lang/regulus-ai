"""Aggregate + paired comparison: frozen base run vs the C1+C2+C3 run.

    .venv/bin/python scripts/c123_score_report.py <c123_run_dir>

Reads the hand-scored verdicts of each run (scoring/verdicts_*.jsonl) and the answers, and
reports the rubric aggregates, the paired PASS/FAIL transitions and the evidence-impact
breakdown. Scoring itself is not done here: the rubric is applied by reading each answer
against the verified corpus, and this script only tabulates the recorded verdicts.
"""

from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/acceptance_test/acceptance_rev02_20261001T083958Z"


def verdicts(run_dir: Path) -> dict:
    out = {}
    for f in sorted(glob.glob(str(run_dir / "scoring" / "verdicts_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
    return out


def answers(run_dir: Path) -> dict:
    return {r["question_id"]: r for r in
            (json.loads(l) for l in open(run_dir / "answers.jsonl", encoding="utf-8") if l.strip())}


def full_pass(r: dict) -> bool:
    """L=1 AND M=0 AND N=2 AND O>=1 AND P=1 AND Q in {1, blank}."""
    return (r.get("L") == 1 and r.get("M") == 0 and r.get("N") == 2
            and (r.get("O") or 0) >= 1 and r.get("P") == 1 and r.get("Q") in (1, None))


def summarise(name: str, v: dict, scored: list[str]) -> dict:
    s = [v[i] for i in scored]
    n = len(s)
    out = {
        "n": n,
        "full_pass": sum(1 for r in s if full_pass(r)),
        "N=2": sum(1 for r in s if r.get("N") == 2),
        "N>=1": sum(1 for r in s if (r.get("N") or 0) >= 1),
        "N=0": sum(1 for r in s if r.get("N") == 0),
        "L=1": sum(1 for r in s if r.get("L") == 1),
        "M=1 (fabrication)": sum(1 for r in s if r.get("M") == 1),
        "O>=1": sum(1 for r in s if (r.get("O") or 0) >= 1),
        "P=1": sum(1 for r in s if r.get("P") == 1),
        "Q=1": sum(1 for r in s if r.get("Q") == 1),
        "Q=0": sum(1 for r in s if r.get("Q") == 0),
        "Q blank": sum(1 for r in s if r.get("Q") is None),
    }
    print(f"\n=== {name} (n={n}) ===")
    for k, val in out.items():
        if k == "n":
            continue
        print(f"  {k:20} {val:4}  {100 * val / n:5.1f}%")
    return out


def main() -> int:
    run = Path(sys.argv[1]).resolve()
    bv, nv = verdicts(BASE), verdicts(run)
    ba, na = answers(BASE), answers(run)
    scored = sorted(i for i in bv if bv[i].get("result") != "ERROR" and i in nv and nv[i].get("result") != "ERROR")
    print(f"base verdicts {len(bv)}, new verdicts {len(nv)}, scored in both {len(scored)}")
    summarise("Original Base", bv, scored)
    summarise("C1+C2+C3", nv, scored)

    trans = Counter()
    changed = []
    for i in scored:
        a, b = full_pass(bv[i]), full_pass(nv[i])
        trans[("PASS" if a else "FAIL") + " -> " + ("PASS" if b else "FAIL")] += 1
        if a != b or any(bv[i].get(k) != nv[i].get(k) for k in "LMNOPQ"):
            changed.append(i)
    print("\n=== paired delta ===")
    for k in ("PASS -> PASS", "PASS -> FAIL", "FAIL -> PASS", "FAIL -> FAIL"):
        print(f"  {k:14} {trans[k]:4}")
    print(f"\nrows whose rubric scores changed at all: {len(changed)}")
    for i in changed:
        o, n = bv[i], nv[i]
        same_answer = ba[i].get("answer") == na[i].get("answer")
        print(f"  {i:8} L{o.get('L')}->{n.get('L')} M{o.get('M')}->{n.get('M')} N{o.get('N')}->{n.get('N')} "
              f"O{o.get('O')}->{n.get('O')} P{o.get('P')}->{n.get('P')} Q{o.get('Q')}->{n.get('Q')} "
              f"{'PASS' if full_pass(o) else 'FAIL'}->{'PASS' if full_pass(n) else 'FAIL'}"
              f"{'  (answer byte-identical)' if same_answer else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
