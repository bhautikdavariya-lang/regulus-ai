"""Source-integrity check of the required sections: rows that announce content no stored row holds.

    python integrity_check.py <out_json>

Read-only. For every section a verified key cites (100 cosmetics questions), each live row is flagged when its text
announces following material ("the following ...", or ends with a colon) and the section stores no row below it
(no paragraph_path that extends its own). The flagged row is then checked against what is stored next. For the
required paragraphs of each question, it reports which are flagged. Also re-checks: duplicate live paths, removed
rows, and search_vector equal to its generated definition. Writes only <out_json>.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

OUT = Path(sys.argv[1]).resolve()
sys.argv = [sys.argv[0], str(OUT.parent)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_retrieval as T  # noqa: E402  (-> guarded)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

ANNOUNCES = re.compile(r"\bthe following\b|:\s*$", re.IGNORECASE)


def main() -> int:
    req_by_q = {qid: T.required(q) for qid, q in T.SEL.items()}
    sections = sorted({s for r in req_by_q.values() for s in r})
    db = Database.from_env()
    db.connect()
    flagged, checks = {}, {}
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        sv = db.query(T.SV_SQL)
        sv_expr = sv[0]["generation_expression"] if sv and sv[0]["is_generated"] == "ALWAYS" else None
        for sec in sections:
            rows = db.query("SELECT COALESCE(paragraph_path, '') AS path, ordinal, body_text, removed_on FROM cfr_records "
                            "WHERE section_number = %(s)s ORDER BY ordinal", {"s": sec})
            live = [r for r in rows if r["removed_on"] is None]
            paths = [r["path"] for r in live]
            ok = db.query(f"SELECT bool_and(search_vector = ({sv_expr})) AS ok FROM cfr_records r WHERE section_number = %(s)s "
                          "AND removed_on IS NULL", {"s": sec})[0]["ok"] if sv_expr else None
            checks[sec] = {"live_rows": len(live), "removed_rows": len(rows) - len(live),
                           "duplicate_live_paths": sorted({p for p in paths if paths.count(p) > 1}), "search_vector_matches_text": ok}
            for i, r in enumerate(live):
                text = (r["body_text"] or "").strip()
                if not ANNOUNCES.search(text):
                    continue
                children = [p for p in paths if r["path"] and p.startswith(r["path"] + "(")] if r["path"] else []
                if children:
                    continue
                nxt = live[i + 1] if i + 1 < len(live) else None
                flagged[f"21 CFR {sec}{r['path']}"] = {
                    "ends_with_colon": text.endswith(":"), "tail": text[-140:],
                    "next_row": (nxt["path"] or "(section)", (nxt["body_text"] or "")[:90]) if nxt else None}
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    affected = {}
    for qid, req in req_by_q.items():
        for sec, paras in req.items():
            for lab in flagged:
                s, p = T.split_cit(lab)
                top = re.match(r"\(([a-z])\)", p or "")
                if s == sec and (not paras or not p or (top and top.group(1) in paras)):
                    affected.setdefault(qid, []).append(lab)
    out = {"sections_checked": len(sections), "section_checks": checks, "flagged_rows": flagged,
           "questions_whose_required_paragraphs_include_a_flagged_row": affected,
           "summary": {"flagged_rows": len(flagged), "flagged_ending_with_colon": sum(v["ends_with_colon"] for v in flagged.values()),
                       "questions_affected": len(affected),
                       "duplicate_paths_anywhere": sum(1 for c in checks.values() if c["duplicate_live_paths"]),
                       "search_vector_all_match": all(c["search_vector_matches_text"] for c in checks.values()),
                       "removed_rows_total": sum(c["removed_rows"] for c in checks.values())},
           "run": {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS),
                   "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))}}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(out["summary"], indent=1), json.dumps(out["run"]))
    for lab, v in flagged.items():
        print(f"{lab:28} colon={v['ends_with_colon']!s:5} | ...{v['tail'][-90:]} | next {v['next_row'][0] if v['next_row'] else None}")
    print("questions:", json.dumps(affected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
