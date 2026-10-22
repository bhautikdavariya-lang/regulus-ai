"""Is the text a lead-in row announces stored anywhere in its section? Read-only; writes only <out_json>.

    python absence_check.py <out_json>

For 740.11 and 740.12 the announced text is quoted on labels and in parallel drug/food warnings; a distinctive phrase of
it is searched in every live eCFR row, and the sections that contain it are listed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1]).resolve()
sys.argv = [sys.argv[0], str(OUT.parent)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_retrieval as T  # noqa: E402,F401  (-> guarded: SELECT only)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

PHRASES = {"740.11": ["%contents under pressure%", "%avoid spraying in eyes%", "%do not puncture or incinerate%"],
           "740.12": ["%for external use only%"]}
db = Database.from_env()
db.connect()
try:
    assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
    fp0 = RB.database_fingerprint(db)
    out = {}
    for sec, pats in PHRASES.items():
        for p in pats:
            rows = db.query("SELECT section_number, COALESCE(paragraph_path, '') AS path FROM cfr_records "
                            "WHERE body_text ILIKE %(p)s AND removed_on IS NULL ORDER BY section_number, ordinal", {"p": p})
            out[f"{sec} {p}"] = {"sections": sorted({r["section_number"] for r in rows}),
                                 "rows_in_own_section": [r["path"] for r in rows if r["section_number"] == sec]}
    lead = {}
    for sec, path in (("740.11", "(a)(1)"), ("740.11", "(b)(1)"), ("740.12", "(b)")):
        r = db.query("SELECT ordinal, body_text FROM cfr_records WHERE section_number = %(s)s AND paragraph_path = %(p)s "
                     "AND removed_on IS NULL", {"s": sec, "p": path})[0]
        nxt = db.query("SELECT COALESCE(paragraph_path, '') AS path, left(body_text, 100) AS t FROM cfr_records "
                       "WHERE section_number = %(s)s AND ordinal > %(o)s AND removed_on IS NULL ORDER BY ordinal LIMIT 1",
                       {"s": sec, "o": r["ordinal"]})
        lead[f"{sec}{path}"] = {"ends": r["body_text"][-100:], "next_row": nxt[0] if nxt else None}
    fp1 = RB.database_fingerprint(db)
finally:
    db.close()
res = {"phrase_search": out, "lead_in_rows": lead,
       "run": {"database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))}}
OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(res, indent=1, ensure_ascii=False))
