"""Blast radius of the single-digit-period extension to the fabrication figure check.

For each of the 300 recorded acceptance answers, reconstructs the evidence text from the recorded
evidence labels (the same read-only snapshot accuracy_validate.py uses) and computes the stray-figure
set the OLD rule reported and the one the NEW rule reports. Read-only; no model, no generation.
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
import psycopg
from regulus.rag.validation import _figures, _periods, _supplied_figures, _NUMBER_WORDS, _WORD_PERIOD_RE

LABEL_RE = re.compile(r"^21 CFR (\d+\.\d+[a-z]?)((?:\([A-Za-z0-9]+\))*)$")
SQL = """SELECT body_text FROM cfr_records
         WHERE section_number = %(s)s AND (%(p)s = '' OR paragraph_path = %(p)s)
           AND removed_on IS NULL ORDER BY ordinal"""


def old_stray(text, supplied_texts):
    supplied = set()
    for t in supplied_texts:
        supplied |= _figures(t)
    return sorted(f for f in _figures(text) if f not in supplied
                  and not any(f in sf or sf in f for sf in supplied if len(f) >= 3 and len(sf) >= 3))


def strict_supplied(t):
    """variant B: no bare digit runs - figures, periods, and spelled-out periods only"""
    return (_figures(t) | _periods(t)
            | {_NUMBER_WORDS[m.group(1).lower()] for m in _WORD_PERIOD_RE.finditer(t or "")})


def new_stray(text, supplied_texts, supplier=_supplied_figures):
    supplied = set()
    for t in supplied_texts:
        supplied |= supplier(t)
    mine = _figures(text) | _periods(text)
    return sorted(mine - supplied - {f for f in mine
                                     if any(f in sf or sf in f for sf in supplied if len(f) >= 3 and len(sf) >= 3)})


SUPPLIER = strict_supplied if "--strict" in sys.argv else _supplied_figures


def main() -> int:
    rows = [json.loads(l) for l in open(ROOT / "artifacts/stage_a/dataset.jsonl")]
    conn = psycopg.connect(os.environ["REGULUS_DATABASE_URL"])
    cache: dict[str, str] = {}

    def text_for(label):
        if label not in cache:
            m = LABEL_RE.match(label)
            if not m:
                cache[label] = ""
            else:
                with conn.cursor() as cur:
                    cur.execute(SQL, {"s": m.group(1), "p": m.group(2)})
                    cache[label] = " ".join(r[0] for r in cur.fetchall())
        return cache[label]

    out, newly, lost = {}, [], []
    for r in rows:
        ev = r.get("evidence") or []
        labels = [e.get("citation") if isinstance(e, dict) else str(e) for e in ev] if isinstance(ev, list) else []
        texts = [t for t in (text_for(l) for l in labels if l) if t]
        if not texts:
            continue
        answer = r.get("answer") or ""
        o, n = old_stray(answer, texts), new_stray(answer, texts, SUPPLIER)
        out[r["id"]] = {"old": o, "new": n, "N": r.get("N"), "M": r.get("M")}
        if n and not o:
            newly.append((r["id"], r.get("N"), r.get("M"), n))
        elif o and not n:
            lost.append((r["id"], r.get("N"), r.get("M"), o))
    conn.close()
    (Path(__file__).parent / "figure_ab.json").write_text(json.dumps(out, indent=0), encoding="utf-8")
    print(f"rows with reconstructable evidence: {len(out)}")
    print(f"  reported a stray figure before: {sum(1 for v in out.values() if v['old'])}")
    print(f"  reported a stray figure after : {sum(1 for v in out.values() if v['new'])}")
    print(f"\n  NEWLY flagged ({len(newly)}):")
    for qid, N, M, n in newly:
        print(f"    {qid:<8} N={N} M={M}  strays={n}")
    print(f"\n  NO LONGER flagged ({len(lost)}):")
    for qid, N, M, o in lost:
        print(f"    {qid:<8} N={N} M={M}  strays={o}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
