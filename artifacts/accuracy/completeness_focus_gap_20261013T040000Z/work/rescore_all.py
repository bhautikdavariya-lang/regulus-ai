"""All 300 recorded acceptance answers, every answer shape, re-scored on CURRENT production packages
under production vs both candidates. Same fidelity caveat as rescore.py. No model, no generation."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from candidate import dropped_time_anchor, patched  # noqa: E402
from harness import ROOT, _STATE, completeness, evaluate, package_for  # noqa: E402


def main():
    rows = [json.loads(l) for l in open(ROOT / "artifacts/stage_a/dataset.jsonl")]
    out = []
    for r in rows:
        q, ans = r["question"], r.get("answer") or ""
        if not ans.strip():
            continue
        pkg, _ = package_for(q)
        if pkg is None:
            continue
        rec = {"id": r["id"], "question": q, "N": r.get("N"), "O": r.get("O"), "M": r.get("M"),
               "mode": pkg.answer_plan.shape.mode if pkg.answer_plan else None}
        for name, ctx in (("production", None), ("both", patched)):
            if ctx is None:
                a = evaluate(q, ans)
            else:
                with ctx():
                    a = evaluate(q, ans)
            d = a.to_dict(); st, det = completeness(a)
            rec[name] = {"score": d["accuracy"], "verdict": d["answer_verdict"]["verdict"], "completeness": st,
                         "detail": det, "anchor_omissions": sum(1 for c in (a.checked.get("claims") or [])
                                                                 if "from a stated event" in str(c.get("support_reason")))}
        out.append(rec)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str))
    ch = [x for x in out if (x["production"]["score"], x["production"]["verdict"], x["production"]["completeness"])
          != (x["both"]["score"], x["both"]["verdict"], x["both"]["completeness"])]
    fired = [x for x in out if x["both"]["anchor_omissions"]]
    print(f"recorded answers re-scored: {len(out)}  (modes: {sorted({x['mode'] for x in out}, key=str)})")
    print(f"rows where the anchor check fired on any claim: {len(fired)}")
    print(f"rows whose score/verdict/completeness changed: {len(ch)}")
    for x in ch:
        p, b = x["production"], x["both"]
        print(f"  {x['id']:<8} mode={x['mode']:<11} hand N={x['N']} O={x['O']}  {p['verdict']}({p['score']}) -> "
              f"{b['verdict']}({b['score']})  completeness {p['completeness']} -> {b['completeness']}  anchor={b['anchor_omissions']}")
    _STATE["db"].close()


if __name__ == "__main__":
    main()
