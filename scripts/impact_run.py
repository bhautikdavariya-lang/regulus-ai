"""Change-impact testing: run the model only where a change can alter the answer, then score only what changed.

The professional loop (record / replay / impact): a replay-only pass (run_cosmetics_eval --replay-only --cache C) runs the
code under test on every question with the recorded model replies; a question that needs a call the cache does not hold
is written as needs_live. Only those go to the model (a live pass with the same cache, which records them). The merged
answers are compared with a baseline run, and only answers that differ are blind-scored.

    python scripts/impact_run.py select REPLAY.jsonl SELECTION.json OUT_SELECTION.json   # needs_live -> a selection
    python scripts/impact_run.py merge REPLAY.jsonl LIVE.jsonl OUT.jsonl                 # replayed + live answers
    python scripts/impact_run.py diff BASE.jsonl NEW.jsonl [--out CHANGED_IDS.txt]       # what changed, and how

A question absent from BASE counts as changed. Errors are listed apart and never merged as answers.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def _rows(path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def _by_id(path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in _rows(path):
        out[r["id"]] = r   # a later line (a retried question) replaces an earlier one
    return out


def cmd_select(a) -> None:
    need = [i for i, r in _by_id(a.replay).items() if r.get("needs_live") or r.get("error")]
    sel = json.loads(Path(a.selection).read_text(encoding="utf-8"))
    keep = set(need)
    if isinstance(sel, dict):
        out = {k: v for k, v in sel.items() if k not in ("summary", "questions")}
        out["questions"] = [q for q in sel.get("questions") or [] if (q.get("ID") or q.get("question_id")) in keep]
        out["summary"] = dict(sel.get("summary") or {}, selected_ids=[i for i in sel["summary"]["selected_ids"] if i in keep])
    else:
        out = [x for x in sel if x["id"] in keep]
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(need)} questions need the model -> {a.out}")


def cmd_merge(a) -> None:
    replay, live = _by_id(a.replay), (_by_id(a.live) if a.live and Path(a.live).exists() else {})
    merged, missing = [], []
    for qid, r in replay.items():
        if r.get("needs_live") or r.get("error"):
            if qid in live and not live[qid].get("error"):
                merged.append(dict(live[qid], impact="live"))
            else:
                missing.append(qid)
        else:
            merged.append(dict(r, impact="replayed"))
    with Path(a.out).open("w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(f"{len(merged)} answers -> {a.out} ({collections.Counter(r['impact'] for r in merged)}); "
          f"{len(missing)} without an answer: {', '.join(missing)}")


def cmd_diff(a) -> None:
    base, new = _by_id(a.base), _by_id(a.new)
    changed, same = [], []
    for qid, r in new.items():
        if r.get("error") or r.get("needs_live"):
            continue
        b = base.get(qid)
        (same if b is not None and b.get("answer") == r.get("answer") else changed).append(qid)
    print(f"{len(new)} answers: {len(same)} identical to the baseline, {len(changed)} changed")
    for qid in changed:
        b, r = base.get(qid) or {}, new[qid]
        print(f"  {qid:8} {str(b.get('fallback_type') or 'model')[:22]:22} -> {str(r.get('fallback_type') or 'model')[:22]:22} "
              f"({r.get('impact', '')})")
    if a.out:
        Path(a.out).write_text(",".join(changed), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select"); s.add_argument("replay"); s.add_argument("selection"); s.add_argument("out")
    s.set_defaults(fn=cmd_select)
    m = sub.add_parser("merge"); m.add_argument("replay"); m.add_argument("live"); m.add_argument("out")
    m.set_defaults(fn=cmd_merge)
    d = sub.add_parser("diff"); d.add_argument("base"); d.add_argument("new"); d.add_argument("--out")
    d.set_defaults(fn=cmd_diff)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
