"""Exploratory, read-only: align each section's source lines (local eCFR rendering) with its stored rows, in order.
Writes <out_json>; prints unmatched source lines and unmatched rows."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401
from regulus.retrieval.db import Database  # noqa: E402
SRC = ROOT / "artifacts/benchmark_verification/independent_review_20261019T103917Z/sources/ecfr_2026-10-14"
OUT = Path(sys.argv[1]).resolve()
norm = lambda t: " ".join((t or "").split())


def sections(part):
    cur, out = None, {}
    for line in (SRC / f"part-{part}.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"=== § (\S+) \| (.*)$", line)
        if m:
            cur = m.group(1); out[cur] = {"heading": m.group(2), "lines": []}; continue
        if line.startswith("#####") or line.startswith("=== APPENDIX"):
            cur = None; continue
        if cur and line.strip():
            out[cur]["lines"].append(line)
    return out


db = Database.from_env(); db.connect()
res = {}
try:
    for part in ("701", "740"):
        for sec, s in sections(part).items():
            rows = db.query("SELECT paragraph_path, path_ordinal, ordinal, body_text, fr_citation, section_heading FROM cfr_records "
                            "WHERE section_number = %(s)s AND removed_on IS NULL ORDER BY ordinal", {"s": sec})
            i, matched, extra_src = 0, [], []
            for ln in s["lines"]:
                if i < len(rows) and norm(rows[i]["body_text"]) == norm(ln):
                    matched.append((ln[:50], rows[i]["paragraph_path"], rows[i]["path_ordinal"])); i += 1
                else:
                    extra_src.append({"after_row": (rows[i - 1]["paragraph_path"], rows[i - 1]["path_ordinal"]) if i else None, "line": ln})
            res[sec] = {"src_lines": len(s["lines"]), "db_rows": len(rows), "matched": len(matched), "unmatched_db_rows": len(rows) - i,
                        "unmatched_src": extra_src, "fr_citation": rows[0]["fr_citation"] if rows else None,
                        "first_unmatched_db": (rows[i]["paragraph_path"], rows[i]["body_text"][:120]) if i < len(rows) else None}
finally:
    db.close()
OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
for sec, r in res.items():
    flag = "OK " if r["unmatched_db_rows"] == 0 else "MISALIGNED"
    print(f"{sec:8} {flag} src {r['src_lines']:3} db {r['db_rows']:3} matched {r['matched']:3} unmatched_src {len(r['unmatched_src'])}")
    for u in r["unmatched_src"]:
        print(f"      + after {u['after_row']}: {u['line'][:150]}")
    if r["first_unmatched_db"]:
        print("      ! first unmatched db row:", r["first_unmatched_db"])
