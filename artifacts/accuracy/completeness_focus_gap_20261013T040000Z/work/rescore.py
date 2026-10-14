"""Step 2b: the 300 RECORDED acceptance answers (artifacts/stage_a/dataset.jsonl, hand-scored once under
regulus_substantive_rubric_v1) re-scored against CURRENT production packages, under the production
_focus_gap and the candidate. No model, no generation, nothing written outside this directory.

Fidelity: the answers were generated against historical evidence, so their [n] markers need not match
the current package's numbering - citation dimensions are noisy here. Completeness (_focus_gap) works
from what the claims are aligned to, by content, and both rules see identical inputs, so the
comparison between the two rules is exact even where the absolute scores are not.
Hand completeness: O in {0,1,2}; O=2 means the answer is complete.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from harness import ROOT, _STATE, completeness, evaluate, focus_gap_rule, package_for, recording_rule  # noqa: E402


def main():
    rows = [json.loads(l) for l in open(ROOT / "artifacts/stage_a/dataset.jsonl")]
    out = []
    for n, r in enumerate(rows, 1):
        q, ans = r["question"], r.get("answer") or ""
        if not ans.strip():
            continue
        pkg, _ = package_for(q)
        if pkg is None or pkg.answer_plan is None or pkg.answer_plan.shape.mode != "focused":
            continue
        rec = {"id": r["id"], "question": q, "O": r.get("O"), "N": r.get("N"), "M": r.get("M")}
        for rule in ("production", "distinguishing"):
            store = []
            with focus_gap_rule(recording_rule(store, rule)):
                a = evaluate(q, ans)
            d = a.to_dict(); st, det = completeness(a)
            rec[rule] = {"completeness": st, "detail": det, "score": d["accuracy"], "verdict": d["answer_verdict"]["verdict"],
                         "focus": store[-1]["trace"][-1] if store and store[-1]["trace"] else None}
        out.append(rec)
        if n % 50 == 0:
            print(f"  {n}/300", flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str))
    ch = [x for x in out if (x["production"]["completeness"], x["production"]["score"])
          != (x["distinguishing"]["completeness"], x["distinguishing"]["score"])]
    print(f"\nfocused rows with a recorded answer: {len(out)}")
    print(f"rows the candidate changes: {len(ch)}")
    for x in ch:
        p, c = x["production"], x["distinguishing"]
        print(f"  {x['id']:<8} hand O={x['O']} N={x['N']}  completeness {p['completeness']}->{c['completeness']}  "
              f"score {p['score']}->{c['score']}  verdict {c['verdict']}")
        print(f"           Q: {x['question'][:110]}")
        print(f"           prod: {p['detail'][:170]}")
    _STATE["db"].close()


if __name__ == "__main__":
    main()
