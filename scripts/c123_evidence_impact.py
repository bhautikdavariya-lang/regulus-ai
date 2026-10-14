"""Did the evidence change, and did the answer change with it?

    .venv/bin/python scripts/c123_evidence_impact.py <c123_run_dir> [--verdicts]

Compares the frozen base run's artifact against the C1+C2+C3 run's artifact, question by
question, using what each run actually recorded: the selected evidence the model saw and the
answer it produced. With --verdicts it also partitions by the hand-scored rubric result, which
is the diagnostic that matters: when the evidence improved, did the answer?

Read-only; prints a report and writes nothing.
"""

from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/acceptance_test/acceptance_rev02_20261001T083958Z"


def answers(d: Path) -> dict:
    return {r["question_id"]: r for r in
            (json.loads(l) for l in open(d / "answers.jsonl", encoding="utf-8") if l.strip())}


def verdicts(d: Path) -> dict:
    out = {}
    for f in sorted(glob.glob(str(d / "scoring" / "verdicts_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
    return out


def full_pass(r: dict) -> bool:
    return (r.get("L") == 1 and r.get("M") == 0 and r.get("N") == 2
            and (r.get("O") or 0) >= 1 and r.get("P") == 1 and r.get("Q") in (1, None))


def main() -> int:
    run = Path(sys.argv[1]).resolve()
    ba, na = answers(BASE), answers(run)
    ids = sorted(set(ba) & set(na))
    ev_changed = [i for i in ids if ba[i].get("evidence") != na[i].get("evidence")]
    ans_changed = [i for i in ids if ba[i].get("answer") != na[i].get("answer")]
    print(f"questions in both runs: {len(ids)}")
    print(f"selected evidence changed: {len(ev_changed)}")
    print(f"answer text changed      : {len(ans_changed)}")
    print(f"evidence changed AND answer changed : {len(set(ev_changed) & set(ans_changed))}")
    print(f"evidence changed, answer IDENTICAL  : {len(set(ev_changed) - set(ans_changed))}")
    print(f"evidence IDENTICAL, answer changed  : {len(set(ans_changed) - set(ev_changed))}")

    if "--verdicts" in sys.argv:
        bv, nv = verdicts(BASE), verdicts(run)
        both = [i for i in ids if i in bv and i in nv
                and bv[i].get("result") != "ERROR" and nv[i].get("result") != "ERROR"]
        print(f"\nscored in both: {len(both)}")
        for label, pop in (("evidence CHANGED", [i for i in both if i in ev_changed]),
                           ("evidence UNCHANGED", [i for i in both if i not in ev_changed])):
            imp = [i for i in pop if not full_pass(bv[i]) and full_pass(nv[i])]
            reg = [i for i in pop if full_pass(bv[i]) and not full_pass(nv[i])]
            # a finer signal than PASS/FAIL: the substantive score N
            n_up = [i for i in pop if (nv[i].get("N") or 0) > (bv[i].get("N") or 0)]
            n_dn = [i for i in pop if (nv[i].get("N") or 0) < (bv[i].get("N") or 0)]
            same = [i for i in pop if all(bv[i].get(k) == nv[i].get(k) for k in "LMNOPQ")]
            print(f"\n  --- {label} (n={len(pop)})")
            print(f"      PASS gained      : {len(imp)} {imp}")
            print(f"      PASS lost        : {len(reg)} {reg}")
            print(f"      N improved       : {len(n_up)} {n_up}")
            print(f"      N regressed      : {len(n_dn)} {n_dn}")
            print(f"      rubric identical : {len(same)}")
        print("\n  base full-pass:", sum(1 for i in both if full_pass(bv[i])),
              " new full-pass:", sum(1 for i in both if full_pass(nv[i])))
    else:
        print("\nevidence-changed question ids:")
        print("  " + " ".join(ev_changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
