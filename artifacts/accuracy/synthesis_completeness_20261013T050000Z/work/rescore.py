"""All 299 recorded acceptance answers, re-scored against CURRENT production packages, under production and
each candidate. No model, no generation; nothing written outside this directory. (Same fidelity caveat as
the previous task: markers may not match today's numbering; every rule sees identical inputs.)"""
from __future__ import annotations
import contextlib, json, sys
from pathlib import Path
HERE = Path(__file__).parent
FG = HERE.parents[1] / "completeness_focus_gap_20261013T040000Z" / "work"
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(FG))
from harness import ROOT, _STATE, completeness, evaluate, package_for  # noqa: E402
from proto import patched  # noqa: E402

RULES = ["production"]


def label(a, question):
    from regulus.accuracy.review import question_review
    return question_review(a.to_dict(), question=question)["label"]


def main():
    rows = [json.loads(l) for l in open(ROOT / "artifacts/stage_a/dataset.jsonl")]
    with patched("T"):                                  # build every package once, carrying `withheld`
        for r in rows:
            if (r.get("answer") or "").strip():
                package_for(r["question"])
    out = []
    for r in rows:
        q, ans = r["question"], r.get("answer") or ""
        if not ans.strip():
            continue
        pkg, _ = package_for(q)
        if pkg is None:
            continue
        rec = {"id": r["id"], "N": r.get("N"), "O": r.get("O"), "M": r.get("M"),
               "mode": pkg.answer_plan.shape.mode if pkg.answer_plan else None,
               "withheld_obligations": None}
        for rule in RULES:
            ctx = contextlib.nullcontext() if rule == "production" else patched(rule)
            with ctx:
                a = evaluate(q, ans)
            st, det = completeness(a)
            rec[rule] = {"label": label(a, q), "score": a.to_dict()["accuracy"], "completeness": st, "detail": det}
        out.append(rec)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str))
    for rule in []:
        ch = [x for x in out if (x["production"]["label"], x["production"]["score"]) != (x[rule]["label"], x[rule]["score"])]
        print(f"\n== {rule}: {len(ch)} of {len(out)} recorded answers change ==")
        for x in ch:
            p, c = x["production"], x[rule]
            print(f"  {x['id']:<8} {str(x['mode']):<11} hand N={x['N']} O={x['O']}  {p['label']} {p['score']} -> {c['label']} {c['score']}  "
                  f"[{c['completeness']}: {c['detail'][:110]}]")
    _STATE["db"].close()


if __name__ == "__main__":
    main()
