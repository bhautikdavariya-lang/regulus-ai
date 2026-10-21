"""Where each required section sits in the section-coverage ranking, for every general question with an eCFR key.

    python rank_check.py <traces_dir> <out_json>

Read-only. For each general question traced by trace_retrieval.py, the section-coverage weighting
(sql.ECFR_SECTION_COVERAGE: the same lexemes, idf and filters, via causal_checks.COV_CTE) is computed over the
question's content terms (the terms recorded in the trace; for a question whose gate was closed, the terms the leg
would have used). Per required paragraph it records the section's rank among all matching sections, and whether the
paragraph itself matches any question lexeme (only such rows can be returned) and its rank within the section.
Fidelity: where the leg ran, the capped list computed here must equal the rows the trace recorded.
Filters: none (part, section and subchapter NULL) - checked by that fidelity test. Writes only <out_json>.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

TR, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.argv = [sys.argv[0], str(OUT.parent)]  # causal_checks reads its own out_dir argument at import
sys.path.insert(0, str(Path(__file__).resolve().parent))
import causal_checks as CC  # noqa: E402  (imports trace_retrieval -> guarded)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

PREV = json.loads((OUT.parent / "prevalence.json").read_text(encoding="utf-8"))["per_question"]
NOF = {"part": None, "section": None, "subchapter": None}


def bucket(rank):
    if rank is None:
        return "section matches no question lexeme"
    for hi, name in ((4, "1-4 (within the 4 section slots)"), (8, "5-8"), (20, "9-20"), (100, "21-100")):
        if rank <= hi:
            return name
    return ">100"


def main() -> int:
    db = Database.from_env()
    db.connect()
    res, fidelity = {}, []
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        for f in sorted(TR.glob("COS-*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            q = PREV[d["id"]]
            if not q["general"] or not q["labels"]:
                continue
            terms = d["gates"]["section_coverage_terms"]
            secs = sorted(d["required"])
            p = {**NOF, "query": terms, "targets": secs, "sections": 4}
            ranks = {r["section_number"]: r for r in db.query(CC.SQL_SECTIONS, p)}
            rows = db.query(CC.SQL_TARGET_ROWS, p)
            leg = next((c for c in d["legs"] if c["leg"] == "section_coverage_ecfr"), None)
            if leg is not None:
                cov = CC.coverage(db, NOF, terms, set(secs), 4)
                fidelity.append(cov["capped"] == [r["citation"] for r in leg["rows"]])
            out = {}
            for lab, info in q["labels"].items():
                sec = lab.split(" ")[2].split("(")[0]
                path = lab[len("21 CFR " + sec):]
                mine = [r for r in rows if r["section_number"] == sec and (r["path"] == path or (path and r["path"].startswith(path)))]
                own = next((r for r in mine if r["path"] == path), None)
                rk = ranks.get(sec)
                out[lab] = {"mechanism": info["mechanism"], "section_rank": rk["rank"] if rk else None,
                            "section_score": float(rk["section_score"]) if rk else None, "bucket": bucket(rk["rank"] if rk else None),
                            "paragraph_matches_a_lexeme": bool(own and own["rn"] is not None),
                            "paragraph_or_descendant_matches": any(r["rn"] is not None for r in mine),
                            "rank_within_section": own["rn"] if own else None, "lexemes": own["lexemes"] if own else None}
            res[d["id"]] = {"terms": terms, "coverage_ran": leg is not None, "labels": out}
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    agg = {}
    for mech in ("A", "B", "C", "D", "OK"):
        labs = [v for r in res.values() for v in r["labels"].values() if v["mechanism"] == mech]
        agg[mech] = {"paragraphs": len(labs), "section_rank_buckets": dict(Counter(v["bucket"] for v in labs)),
                     "paragraph_matches_no_lexeme": sum(1 for v in labs if not v["paragraph_matches_a_lexeme"])}
    qs_c = {qid for qid, r in res.items() if any(v["mechanism"] == "C" for v in r["labels"].values())}
    best_c = Counter()
    for qid in qs_c:
        rk = [v["section_rank"] for v in res[qid]["labels"].values() if v["mechanism"] == "C"]
        best = min((x for x in rk if x is not None), default=None)
        best_c[bucket(best)] += 1
    summary = {"questions": len(res), "fidelity_checked": len(fidelity), "fidelity_all_equal": all(fidelity),
               "by_mechanism": agg, "C_questions_by_best_required_section_rank": dict(best_c),
               "run": {"semantic_load_attempts": len(CC.T.SEMANTIC_ATTEMPTS),
                       "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))}}
    OUT.write_text(json.dumps({"summary": summary, "per_question": res}, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
