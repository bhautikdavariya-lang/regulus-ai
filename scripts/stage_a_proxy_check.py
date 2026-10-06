"""Stage A: measure the two mechanical validators against the frozen substantive rubric.

Deliverable 3 - "a documented limitation of the old span-support validator" - turned into numbers
rather than a single anecdote. Two mechanical judgements are scored against the 300 hand-assigned
rubric verdicts in the Stage A dataset:

  PROXY   the D1 content-recall proxy, reimplemented exactly as `scripts/d1_experiment.py` applies
          it (lines 291-411): bag-of-words recall of the benchmark's Key Answer Elements, pass at
          >= 0.50, with trap rows instead passed by a refusal regex. This is the metric that gave
          M-003 ~0.80 recall and a PASS while the answer contradicted the governing rule.

  GATE    the production grounding validator's own final state (`validation_final == "valid"`),
          i.e. whether the pipeline considered the text it showed to be supported by its evidence.

Both are compared with the rubric verdict (PASS iff L=1, M=0, N=2, O>=1, P=1, Q in {1, blank}) and
with substantive correctness alone (N=2), because the interesting failure is a mechanical PASS over
a substantively wrong answer.

Read-only: consumes `artifacts/stage_a/dataset.jsonl`, writes under `artifacts/stage_a/`. No model,
no database, no production import.

    python3 scripts/stage_a_proxy_check.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------------------------
# verbatim from scripts/d1_experiment.py (REFUSE, STOP, words, the 0.5 threshold and trap markers)
# ---------------------------------------------------------------------------------------------
REFUSE = re.compile(r"(does not exist|no such|not contain|not found|cannot (state|answer|find)|will not infer|outside|"
                    r"not covered|does not provide enough information|no provision)", re.I)
STOP = set("what does which require requires required requirement requirements must shall under that this with from part "
           "section about their there these those have when where into such each every apply applies the and for are not "
           "you your how many give list cite explain describe summarize summarise walk tell does do is it its on in of a "
           "an be by or if my our we can confirm so also including include any other".split())
words = lambda t: {w for w in re.findall(r"[a-z][a-z-]{3,}", (t or "").lower())} - STOP
TRAP_MARKERS = ("NO SUCH", "FALSE PREMISE", "NOT COVERED", "REPEALED", "TEMPORAL TRAP", "MUST DECLINE",
                "MUST QUALIFY", "MUST REFUSE", "OUT OF SCOPE", "AMBIGUOUS")
THRESHOLD = 0.5


def proxy(row: dict, text: str) -> tuple[int, float, str]:
    """The D1 mechanical verdict for one answer: (pass, recall, scoring mode)."""
    is_trap = any(t in (row["key_citation_draft"] or "").upper() for t in TRAP_MARKERS)
    kw = words(row["key_elements"])
    recall = round(len(kw & words(text)) / len(kw), 3) if kw else 0.0
    if is_trap:
        return (1 if REFUSE.search(text or "") else 0), recall, "trap_refusal"
    return (1 if recall >= THRESHOLD else 0), recall, "substantive_recall"


def matrix(rows: list[dict], mech: str, truth: str) -> dict:
    """2x2 counts plus the four rates that matter for trusting a metric."""
    cells = {(m, t): [] for m in (1, 0) for t in (1, 0)}
    for r in rows:
        cells[(r[mech], r[truth])].append(r["id"])
    tp, fp, fn, tn = (cells[(1, 1)], cells[(1, 0)], cells[(0, 1)], cells[(0, 0)])
    n = len(rows)
    return {
        "n": n,
        "mech_pass": len(tp) + len(fp),
        "truth_pass": len(tp) + len(fn),
        "true_pass": len(tp), "false_pass": len(fp), "false_fail": len(fn), "true_fail": len(tn),
        "agreement_pct": round(100 * (len(tp) + len(tn)) / n, 1) if n else None,
        # of everything the mechanical metric calls a pass, how much is actually wrong
        "false_pass_rate_of_mech_passes_pct": round(100 * len(fp) / (len(tp) + len(fp)), 1) if (tp or fp) else None,
        # of everything that is actually correct, how much the metric suppresses
        "false_fail_rate_of_true_passes_pct": round(100 * len(fn) / (len(tp) + len(fn)), 1) if (tp or fn) else None,
        "false_pass_ids": sorted(fp),
        "false_fail_ids": sorted(fn),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "artifacts/stage_a/dataset.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_a")
    args = ap.parse_args()

    data = [json.loads(l) for l in args.dataset.read_text().splitlines() if l.strip()]
    scored = []
    for d in data:
        if d["result"] == "ERROR":      # one technical execution failure: no answer exists to judge
            continue
        p_final, r_final, mode = proxy(d, d["answer"] or "")
        p_raw, r_raw, _ = proxy(d, d["raw_model_output"] or "")
        scored.append({
            "id": d["id"], "type": d["type"], "mode": mode,
            "proxy_pass_final": p_final, "proxy_recall_final": r_final,
            "proxy_pass_raw": p_raw, "proxy_recall_raw": r_raw,
            "gate_pass": 1 if d["validation_final"] == "valid" else 0,
            "rubric_pass": 1 if d["result"] == "PASS" else 0,
            "substantive_pass": 1 if d["N"] == 2 else 0,
            "withheld": 1 if d["rev_withheld"] == "yes" else 0,
            "rubric_N": d["N"], "rubric_L": d["L"], "rubric_M": d["M"],
            "notes": d["notes"],
        })

    report = {
        "stage": "A",
        "deliverable": "3 - limitation of the mechanical span-support / content-recall validators",
        "scored_rows": len(scored),
        "excluded": [d["id"] for d in data if d["result"] == "ERROR"],
        "rubric_passes": sum(r["rubric_pass"] for r in scored),
        "substantive_passes_N2": sum(r["substantive_pass"] for r in scored),
        "matrices": {
            "proxy_on_final_vs_rubric": matrix(scored, "proxy_pass_final", "rubric_pass"),
            "proxy_on_final_vs_substantive": matrix(scored, "proxy_pass_final", "substantive_pass"),
            "proxy_on_raw_vs_substantive": matrix(scored, "proxy_pass_raw", "substantive_pass"),
            "gate_vs_rubric": matrix(scored, "gate_pass", "rubric_pass"),
            "gate_vs_substantive": matrix(scored, "gate_pass", "substantive_pass"),
        },
        "by_mode": {},
    }
    for mode in ("substantive_recall", "trap_refusal"):
        rows = [r for r in scored if r["mode"] == mode]
        report["by_mode"][mode] = {
            "n": len(rows),
            "proxy_on_final_vs_rubric": matrix(rows, "proxy_pass_final", "rubric_pass"),
        }

    # the headline example: every row the proxy passes while the rubric scored it substantively wrong
    report["false_pass_detail"] = [
        {"id": r["id"], "type": r["type"], "recall": r["proxy_recall_final"], "N": r["rubric_N"],
         "L": r["rubric_L"], "M": r["rubric_M"], "note": (r["notes"] or "")[:300]}
        for r in sorted(scored, key=lambda r: -r["proxy_recall_final"])
        if r["proxy_pass_final"] and not r["substantive_pass"]
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "proxy_check.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.out / "proxy_rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in scored))

    m = report["matrices"]
    print(f"scored {len(scored)} rows (1 ERROR excluded)")
    for name in ("proxy_on_final_vs_rubric", "proxy_on_final_vs_substantive", "gate_vs_rubric", "gate_vs_substantive"):
        x = m[name]
        print(f"\n{name}")
        print(f"   mechanical PASS {x['mech_pass']:3}   rubric/substantive PASS {x['truth_pass']:3}   agreement {x['agreement_pct']}%")
        print(f"   false pass {x['false_pass']:3} ({x['false_pass_rate_of_mech_passes_pct']}% of mechanical passes)"
              f"   false fail {x['false_fail']:3} ({x['false_fail_rate_of_true_passes_pct']}% of real passes)")
    print(f"\nfalse passes over substantively wrong answers: {len(report['false_pass_detail'])}")
    for r in report["false_pass_detail"][:10]:
        print(f"   {r['id']:7} recall {r['recall']:.2f} N={r['N']}  {r['note'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
