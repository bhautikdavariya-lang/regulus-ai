"""Read-only causal checks for the traced retrieval failures. No model, no switch, no production change.

    python causal_checks.py <out_dir>

Re-runs the production pipeline (built as trace_retrieval.py builds it) for the failing questions, capturing every
leg's actual arguments, then:
  A  COS-73.2725-Q1: match counts for each branch of the question's own AND query (websearch_to_tsquery reads its
     standalone "or" as OR), and a harness-only alternative in which both AND legs receive the question with that
     operator word removed. The production switch REGULUS_ECFR_LITERAL_OR stays unset and its flag False; the
     alternative is a wrapper in this process only.
  B  per-row coverage, computed with the section-coverage leg's own weighting (sql.ECFR_SECTION_COVERAGE, same
     lexemes, idf and filters), for every live row of each required section, with the lexemes each row matches; the
     full candidate list before the per-section and total caps; and a fidelity check that the capped list equals the
     rows the production leg returned.
  C  the full section ranking under the production terms (not only the top 4), with each required section's rank;
     for COS-74.2317-Q1 also with the identifier tokens content_terms drops.
  D  COS-70.55-Q1: selection re-run on the same registry with its eCFR rows ahead of its guidance rows (nothing else
     changed), after checking that the same call on the unchanged registry reproduces the actual selection.
Writes only <out_dir>/causal_checks.json.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import trace_retrieval as T  # noqa: E402  (imports guarded: semantic refusal + SELECT-only; asserts the switch is unset)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.rag import selection as SELM  # noqa: E402
from regulus.retrieval import lexical as L  # noqa: E402
from regulus.retrieval import sql as SQLM  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.query import content_terms  # noqa: E402

assert L.ECFR_LITERAL_OR_ENABLED is False
OUT = Path(sys.argv[1]).resolve()
# websearch_to_tsquery's OR operator: a standalone "or" (any case) beside spaces, commas or brackets
OP_RE = re.compile(r"(?<![\w/-])or(?![\w/-])", re.IGNORECASE)

COV_CTE = f"""
WITH lex AS (SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', %(query)s))) AS l),
hits AS (
    SELECT r.section_number, r.ordinal, lex.l FROM lex
    JOIN cfr_records r ON r.search_vector @@ quote_literal(lex.l)::tsquery
    WHERE NOT r.is_reserved {SQLM._ECFR_FILTERS}
),
df AS (SELECT l, count(DISTINCT section_number) AS n FROM hits GROUP BY l),
total AS (SELECT count(*)::float8 AS n FROM cfr_sections WHERE NOT is_reserved),
w AS (SELECT df.l, df.n AS df, ln(GREATEST(total.n / df.n, 1.0)) AS idf FROM df, total),
mass AS (SELECT sum(idf) AS m FROM w),
row_cov AS (
    SELECT h.section_number, h.ordinal, sum(w.idf) AS cov, array_agg(h.l ORDER BY h.l) AS lexemes
    FROM hits h JOIN w USING (l) GROUP BY h.section_number, h.ordinal
),
sec AS (
    SELECT s.section_number, s.cov / NULLIF((SELECT m FROM mass), 0) AS union_share,
           b.best / NULLIF((SELECT m FROM mass), 0) AS best_share,
           (s.cov + b.best) / NULLIF((SELECT m FROM mass), 0) AS section_score
    FROM (SELECT u.section_number, sum(w.idf) AS cov
          FROM (SELECT DISTINCT section_number, l FROM hits) u JOIN w USING (l) GROUP BY u.section_number) s
    JOIN (SELECT section_number, max(cov) AS best FROM row_cov GROUP BY section_number) b USING (section_number)
),
srank AS (
    SELECT sec.*, ROW_NUMBER() OVER (ORDER BY section_score DESC NULLS LAST, section_number) AS rank,
           count(*) OVER () AS n_sections
    FROM sec
)
"""
SQL_WEIGHTS = COV_CTE + "SELECT l, df, round(idf::numeric, 4) AS idf, (SELECT count(*) FROM lex) AS n_lexemes FROM w ORDER BY idf DESC"
SQL_SECTIONS = COV_CTE + """
SELECT section_number, rank, n_sections, round(section_score::numeric, 4) AS section_score,
       round(union_share::numeric, 4) AS union_share, round(best_share::numeric, 4) AS best_share
FROM srank WHERE rank <= 8 OR section_number = ANY(%(targets)s) ORDER BY rank"""
SQL_TARGET_ROWS = COV_CTE + """
SELECT r.section_number, COALESCE(r.paragraph_path, '') AS path, r.ordinal, length(r.body_text) AS chars,
       round((COALESCE(rc.cov, 0) / NULLIF((SELECT m FROM mass), 0))::numeric, 4) AS row_share, rc.lexemes,
       CASE WHEN rc.cov IS NULL THEN NULL
            ELSE ROW_NUMBER() OVER (PARTITION BY r.section_number ORDER BY rc.cov DESC NULLS LAST, r.ordinal) END AS rn
FROM cfr_records r LEFT JOIN row_cov rc ON rc.section_number = r.section_number AND rc.ordinal = r.ordinal
WHERE r.section_number = ANY(%(targets)s) AND r.removed_on IS NULL AND NOT r.is_reserved
ORDER BY r.section_number, r.ordinal"""
SQL_CANDIDATES = COV_CTE + """,
ranked AS (
    SELECT rc.section_number, rc.ordinal, s.rank AS section_rank, s.section_score,
           rc.cov / NULLIF((SELECT m FROM mass), 0) AS row_score,
           ROW_NUMBER() OVER (PARTITION BY rc.section_number ORDER BY rc.cov DESC, rc.ordinal) AS rn
    FROM row_cov rc JOIN srank s USING (section_number) WHERE s.rank <= %(sections)s
)
SELECT k.section_number, COALESCE(r.paragraph_path, '') AS path, k.section_rank, k.rn,
       round((k.section_score + k.row_score)::numeric, 4) AS combined
FROM ranked k JOIN cfr_records r ON r.section_number = k.section_number AND r.ordinal = k.ordinal
WHERE r.removed_on IS NULL AND k.section_score IS NOT NULL
ORDER BY k.section_score + k.row_score DESC, k.section_number, k.ordinal"""
SQL_TEXT = ("SELECT section_number, COALESCE(paragraph_path, '') AS path, body_text FROM cfr_records "
            "WHERE section_number = %(s)s AND COALESCE(paragraph_path, '') = %(p)s AND removed_on IS NULL")


def label(sec, path):
    return f"21 CFR {sec}{path}"


class Runner:
    def __init__(self, db):
        self.db = db
        self.pipe, self.gen = RB.production_pipeline(db)
        self.lex = self.pipe.retriever.lexical
        self.calls = []
        self.transform = None
        for name in T.LEGS:
            fn = getattr(self.lex, name)

            def wrapped(*a, _fn=fn, _name=name, **k):
                if self.transform and _name in ("full_text_ecfr", "full_text_guidance") and a and isinstance(a[0], str):
                    a = (self.transform(a[0]),) + tuple(a[1:])
                rows = _fn(*a, **k)
                self.calls.append({"leg": _name, "args": a, "rows": rows})
                return rows
            setattr(self.lex, name, wrapped)

    def answer(self, question, transform=None):
        self.calls, self.transform = [], transform
        try:
            return self.pipe.answer(question)
        finally:
            self.transform = None

    def leg(self, name):
        return next((c for c in self.calls if c["leg"] == name), None)


def compact(out, calls, req):
    final = [s.result.citation.label for s in out.context.sources]
    registry = [(e.citation, e.result.corpus, e.result.retrieval_method, e.tier) for e in out.evidence.evidence]
    status = {}
    for sec, paras in req.items():
        for p in sorted(paras) or [""]:
            lab = label(sec, f"({p})" if p else "")
            match = lambda c: T.split_cit(c)[0] == sec and (not p or (T.split_cit(c)[1] or "").startswith(f"({p})"))
            status[lab] = ("in final context" if any(match(c) for c in final) else
                           "dropped at selection" if any(match(d.evidence.citation) for d in out.selection.dropped) else
                           "in registry, not selected" if any(match(r[0]) for r in registry) else
                           "returned by a leg, lost before registry" if any(match(r.citation.label) for c in calls for r in c["rows"]) else
                           "never returned by any leg")
    return {"legs": [{"leg": c["leg"], "input": c["args"][0] if c["args"] and isinstance(c["args"][0], str) else None,
                      "rows": len(c["rows"]), "citations": [r.citation.label for r in c["rows"]][:16]} for c in calls],
            "registry": registry, "final_context": final,
            "dropped": [(d.evidence.citation, d.reason) for d in out.selection.dropped], "required_status": status}


def coverage(db, filters_params, terms, targets, sections):
    p = {**filters_params, "query": terms, "targets": sorted(targets), "sections": sections}
    weights = db.query(SQL_WEIGHTS, p)
    secs = db.query(SQL_SECTIONS, p)
    rows = db.query(SQL_TARGET_ROWS, p)
    cands = db.query(SQL_CANDIDATES, p)
    capped, n = [], 0
    for c in cands:
        c["outcome"] = ("excluded: rows_per_section cap" if c["rn"] > L.SECTION_COVERAGE_ROWS_PER_SECTION else
                        "returned" if n < sections else "excluded: total row limit")
        if c["outcome"] == "returned":
            n += 1
            capped.append(label(c["section_number"], c["path"]))
    return {"terms": terms, "weights": [dict(w, idf=float(w["idf"])) for w in weights],
            "sections_top8_and_targets": [dict(s, section_score=float(s["section_score"]), union_share=float(s["union_share"]),
                                               best_share=float(s["best_share"])) for s in secs],
            "target_rows": [dict(r, row_share=float(r["row_share"])) for r in rows],
            "candidates_before_caps": [dict(c, combined=float(c["combined"])) for c in cands], "capped": capped}


def eligible(r):
    return r.get("rn") is not None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db = Database.from_env()
    db.connect()
    res = {}
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        run = Runner(db)
        qs = {qid: T.SEL[qid] for qid in ("COS-73.2725-Q1", "COS-700.15-Q1", "COS-700.25-Q2", "COS-74.2317-Q1", "COS-70.55-Q1", "COS-70.3-Q1")}
        texts = {}
        for qid, q in qs.items():
            question = q["Question (ask verbatim)"]
            req = T.required(q)
            out = run.answer(question)
            calls = list(run.calls)
            rec = {"question": question, "required": {k: sorted(v) for k, v in req.items()}, "production": compact(out, calls, req)}
            for sec, paras in req.items():
                for p in sorted(paras) or [""]:
                    r = db.query(SQL_TEXT, {"s": sec, "p": f"({p})" if p else ""})
                    texts[label(sec, f"({p})" if p else "")] = r[0]["body_text"] if r else None
            sc = next((c for c in calls if c["leg"] == "section_coverage_ecfr"), None)
            if sc is not None:
                terms, filters, limit = sc["args"][0], sc["args"][1], sc["args"][2]
                fp = run.lex._ecfr_filter_params(filters)
                cov = coverage(db, fp, terms, set(req), limit)
                cov["fidelity_capped_equals_production"] = cov["capped"] == [r.citation.label for r in sc["rows"]]
                cov["limit"] = limit
                for r in cov["target_rows"]:
                    r["eligible_for_coverage_leg"] = eligible(r)
                rec["section_coverage"] = cov
                if qid == "COS-74.2317-Q1":
                    dropped = [t for t in re.findall(r"[\w&.-]+", question) if t.strip(".-").lower() not in content_terms(question)]
                    alt_terms = terms + " 17 D&C"
                    alt = coverage(db, fp, alt_terms, set(req), limit)
                    rec["section_coverage_with_identifier_tokens"] = {
                        "tokens_content_terms_drops": dropped, "terms": alt_terms,
                        "lexemes_added": db.query("SELECT to_tsvector('english', '17 D&C')::text AS v")[0]["v"],
                        "sections_top8_and_targets": alt["sections_top8_and_targets"], "capped": alt["capped"],
                        "target_rows": alt["target_rows"]}
            if qid == "COS-73.2725-Q1":
                fte = next(c for c in calls if c["leg"] == "full_text_ecfr")
                ftg = next(c for c in calls if c["leg"] == "full_text_guidance")
                efp = run.lex._ecfr_filter_params(fte["args"][1])
                gfp = run.lex._guidance_filter_params(ftg["args"][1])
                branches = [b.strip(" ,") for b in OP_RE.split(question)]
                br = []
                for text in branches + [OP_RE.sub(" ", question)]:
                    e = db.query("SELECT count(*) AS n, count(DISTINCT r.section_number) AS sections FROM cfr_records r, "
                                 f"websearch_to_tsquery('english', %(q)s) q WHERE r.search_vector @@ q AND NOT r.is_reserved {SQLM._ECFR_FILTERS}",
                                 {**efp, "q": text})[0]
                    g = db.query("SELECT count(*) AS n FROM fda_guidance_chunks c JOIN fda_guidance g ON g.id = c.guidance_id, "
                                 f"websearch_to_tsquery('english', %(q)s) q WHERE c.search_vector @@ q {SQLM._GUIDANCE_FILTERS}",
                                 {"anchor_section": None, **gfp, "q": text})[0]
                    tq = db.query("SELECT websearch_to_tsquery('english', %(q)s)::text AS t", {"q": text})[0]["t"]
                    br.append({"text": text, "tsquery": tq, "ecfr_rows": e["n"], "ecfr_sections": e["sections"], "guidance_chunks": g["n"]})
                br[-1]["note"] = "the whole question with the operator word removed (harness only)"
                rec["and_query_branches"] = {"full_question_tsquery": T.tsq(db, question), "branches": br,
                                             "production_ecfr_rows_returned": len(fte["rows"]),
                                             "production_ecfr_sections_returned": sorted({r.citation.label.split("(")[0] for r in fte["rows"]})}
                alt_out = run.answer(question, transform=lambda s: OP_RE.sub(" ", s))
                alt_calls = list(run.calls)
                rec["alternative_operator_removed_in_both_and_legs"] = compact(alt_out, alt_calls, req)
                asc = next((c for c in alt_calls if c["leg"] == "section_coverage_ecfr"), None)
                if asc is not None:
                    acov = coverage(db, run.lex._ecfr_filter_params(asc["args"][1]), asc["args"][0], set(req), asc["args"][2])
                    acov["fidelity_capped_equals_production"] = acov["capped"] == [r.citation.label for r in asc["rows"]]
                    rec["alternative_operator_removed_in_both_and_legs"]["section_coverage"] = {
                        k: acov[k] for k in ("terms", "sections_top8_and_targets", "target_rows", "candidates_before_caps", "capped",
                                             "fidelity_capped_equals_production")}
            if qid == "COS-70.55-Q1":
                reg = out.evidence
                actual = sorted(s.evidence.evidence_id for s in out.selection.selected)
                attempts = {}
                for name, material in (("material=None", None), ("material=is_subordinate", run.pipe.is_subordinate)):
                    s0 = SELM.select_evidence(reg, run.pipe.config.context, optional_filter=run.pipe.is_useful, material=material, question=question)
                    attempts[name] = sorted(s.evidence.evidence_id for s in s0.selected) == actual
                material = None if attempts["material=None"] else run.pipe.is_subordinate
                ev = list(reg.evidence)
                alt_reg = replace(reg, evidence=tuple([e for e in ev if e.result.corpus == "ecfr"] + [e for e in ev if e.result.corpus != "ecfr"]))
                s1 = SELM.select_evidence(alt_reg, run.pipe.config.context, optional_filter=run.pipe.is_useful, material=material, question=question)
                rec["selection_counterfactual_ecfr_rows_first"] = {
                    "reproduces_actual_selection": attempts,
                    "actual": {"selected": [(s.evidence.citation, s.evidence.result.corpus, len(s.text), s.truncated) for s in out.selection.selected],
                               "dropped": [(d.evidence.citation, d.reason) for d in out.selection.dropped]},
                    "counterfactual": {"selected": [(s.evidence.citation, s.evidence.result.corpus, len(s.text), s.truncated) for s in s1.selected],
                                       "dropped": [(d.evidence.citation, d.reason) for d in s1.dropped]},
                    "changed": "registry order only: eCFR rows (registry order kept) before guidance rows (registry order kept)"}
            res[qid] = rec
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    res["_texts"] = texts
    res["_run"] = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "generation_stub_calls": run.gen.calls,
                   "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
                   "ecfr_literal_or_flag": L.ECFR_LITERAL_OR_ENABLED}
    (OUT / "causal_checks.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(res["_run"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
