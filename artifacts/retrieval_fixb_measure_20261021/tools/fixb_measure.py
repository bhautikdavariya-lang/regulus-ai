"""Fix B read-only measurement (PREREGISTRATION.md): section-coverage row caps base 2/4 vs F1 4/8 vs F2 8/16.

    python fixb_measure.py <out_dir>

The production pipeline (configured RagConfig, SemanticFallbackRetriever + ScopePolicy, stub generator) is built once.
LexicalRetriever.section_coverage_ecfr is replaced on the instance by a copy of its body whose rows_per_section and row
limit come from the current condition (sections = the production limit, 4). Context budget and ordering untouched.
Read-only database behind the guarded.py guards. Writes <out_dir>/raw.json and <out_dir>/runs_352/<cond>.jsonl only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/retrieval_rootcause_20261021/tools"))
import trace_retrieval as T  # noqa: E402  (-> guarded: SELECT-only, semantic loader refused; literal-OR switch unset)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.retrieval import sql  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.lexical import METHOD_FULL_TEXT_OR, SECTION_COVERAGE_ROWS_PER_SECTION  # noqa: E402
from regulus.retrieval.ranking import section_coverage_score  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
CONDS = {"base": (SECTION_COVERAGE_ROWS_PER_SECTION, None), "F1": (4, 8), "F2": (8, 16)}
assert SECTION_COVERAGE_ROWS_PER_SECTION == 2
CURRENT = {"cond": "base"}


def install(lex):
    def section_coverage_ecfr(terms, filters, limit):
        per, total = CONDS[CURRENT["cond"]]
        rows = lex.db.query(sql.ECFR_SECTION_COVERAGE,
                            {**lex._ecfr_filter_params(filters), "query": terms, "sections": limit,
                             "rows_per_section": per, "limit": total if total is not None else limit})
        return [lex._ecfr_result(row, METHOD_FULL_TEXT_OR, section_coverage_score(row["section_score"], row["row_score"]),
                                 {"section_coverage": round(float(row["section_score"]), 4),
                                  "paragraph_coverage": round(float(row["row_score"]), 4), "coverage_terms": terms})
                for row in rows]
    lex.section_coverage_ecfr = section_coverage_ecfr


def labels_of(req):
    out = []
    for sec, paras in req.items():
        for p in sorted(paras) or [""]:
            lab = f"21 CFR {sec}{'(' + p + ')' if p else ''}"
            if lab != "21 CFR 740.11(i)":
                out.append((lab, sec, p))
    return out


def hit(cits, sec, p):
    return any(T.split_cit(c)[0] == sec and (not p or (T.split_cit(c)[1] or "").startswith(f"({p})")) for c in cits)


def record(out, req):
    reg = [e.citation for e in out.evidence.evidence] if out.evidence is not None else []
    final = [s.result.citation.label for s in out.context.sources]
    dropped = [(d.evidence.citation, d.reason) for d in out.selection.dropped] if out.selection else []
    st = {}
    for lab, sec, p in labels_of(req):
        reason = next((r for c, r in dropped if hit([c], sec, p)), None)
        st[lab] = {"candidate": hit(reg, sec, p), "in_context": hit(final, sec, p), "drop_reason": reason}
    return {"required": st, "sources": [(s.result.citation.label, s.result.corpus, s.result.key, len(s.text)) for s in out.context.sources],
            "total_chars": out.selection.total_chars if out.selection else None}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs_352").mkdir(exist_ok=True)
    db = Database.from_env()
    db.connect()
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        fp0 = RB.database_fingerprint(db)
        pipe, gen = RB.production_pipeline(db)
        install(pipe.retriever.lexical)
        q100 = {}
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            plan = plan_query(question)
            req = T.required(q)
            q100[qid] = {"general": not plan.requirements and plan.docket is None}
            for c in CONDS:
                CURRENT["cond"] = c
                q100[qid][c] = record(pipe.answer(question), req)
        rows = RB.load_dataset()
        lookup = RB.CorpusLookup(db)
        summ = {}
        for c in ("F1", "F2"):
            CURRENT["cond"] = c
            recs = []
            with (OUT / "runs_352" / f"{c}.jsonl").open("w", encoding="utf-8") as f:
                for row in rows:
                    rec = RB.run_question(pipe, gen, lookup, row)
                    recs.append(rec)
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            summ[c] = RB.summarise(recs)
        CURRENT["cond"] = "base"
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    run = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "generator_calls": gen.calls,
           "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
           "corpus_identity": fp0["corpus_identity"]["ecfr"]}
    (OUT / "raw.json").write_text(json.dumps({"run": run, "q100": q100, "summary_352": summ}, indent=1, default=str))
    print(json.dumps(run, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
