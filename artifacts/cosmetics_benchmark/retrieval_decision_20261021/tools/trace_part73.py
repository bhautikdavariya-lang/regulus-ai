"""Evidence-selection trace for the 9 Part 73 questions under the saved literal-OR experiment's conditions.

    REGULUS_ECFR_LITERAL_OR=1 python trace_part73.py <out_dir>

Read-only and model-free (guarded.py: the semantic loader refuses, Database.query allows SELECT/WITH only; the
generator is the NoGenerator stub). The switch is on only in this process, exactly as in runs/C2_on_cosmetics.jsonl.
Per question it records: every leg's candidates in the leg's own order (score, method, metadata); the registry
order selection walks; the actual selection; a step-by-step replay of the selection budget, checked against the
actual selection; the database rows of the target sections; and the section-coverage lexeme weights that score
each competing section, checked against the leg's own section_score. Self-checks that fail are reported, never hidden.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guarded  # noqa: E402,F401  (installs the guards)
from guarded import ROOT, SEMANTIC_ATTEMPTS  # noqa: E402

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.rag import selection as SELM  # noqa: E402
from regulus.retrieval import lexical as L  # noqa: E402
from regulus.retrieval import sql as SQLM  # noqa: E402
from regulus.retrieval.base import Filters  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.evidence import TIER_DISCOVERY, TIER_STRUCTURAL, TIER_SUPPORTING  # noqa: E402
from regulus.retrieval.query import content_terms, literal_or  # noqa: E402

FAILED = ["COS-73.2085-Q1", "COS-73.2095-Q1", "COS-73.2298-Q1", "COS-73.2645-Q1", "COS-73.2725-Q1"]
CONTROLS = ["COS-73.2250-Q1", "COS-73.2575-Q1", "COS-73.2646-Q1", "COS-73.2647-Q1"]
SEL = {q["ID"]: q for q in json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json")
                                      .read_text(encoding="utf-8"))["questions"]}
SAVED = {r["id"]: r for r in (json.loads(l) for l in (HERE.parent / "runs/C2_on_cosmetics.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
LEG_NAMES = [n for n in dir(L.LexicalRetriever) if (n.endswith("_ecfr") or n.endswith("_guidance") or n.startswith("exact_"))
             and callable(getattr(L.LexicalRetriever, n))]


def row(r, rank):
    return {"rank": rank, "citation": r.citation.label, "corpus": r.corpus, "method": r.retrieval_method,
            "score": round(float(r.relevance_score), 4), "metadata": {k: v for k, v in (r.metadata or {}).items() if k != "coverage_terms"},
            "chars": len(r.text or "")}


def section_of(citation):
    m = re.match(r"21 CFR (\d+\.\d+[a-z]?)", citation or "")
    return m.group(1) if m else None


def budget_replay(out, pipe):
    """The general-question path of select_evidence, step by step (no required or material evidence)."""
    registry, sel = out.evidence, out.selection
    policy = sel.policy
    steps, chosen, dropped = [], [], []
    used = 0

    def gap():
        return 2 if chosen else 0

    limit = min(policy.max_total_chars, policy.hard_max_total_chars)
    binding_first = policy.general_evidence_order == SELM.ORDER_BINDING_FIRST and SELM._binding_reserve_applies(registry)
    handled = set()
    reserve = min(policy.binding_reserve_chars, policy.max_total_chars)
    if reserve > 0 and SELM._binding_reserve_applies(registry) and not binding_first:
        spent = 0
        for tier in (TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY):
            for e in registry.evidence:
                if e.tier != tier or e.evidence_id in handled or e.result.corpus != "ecfr":
                    continue
                if tier != TIER_STRUCTURAL and not pipe.is_useful(e.result):
                    continue
                if len(chosen) >= policy.max_results:
                    continue
                text, trunc = SELM._truncate(SELM._clean(e.text), policy.max_chars_per_result)
                chars = SELM._block_chars(e, text, len(chosen) + 1, trunc)
                st = {"phase": "eCFR reserve", "citation": e.citation, "tier": e.tier, "method": e.result.retrieval_method,
                      "block_chars": chars, "used_before": used, "reserve_spent_before": spent, "reserve": reserve, "limit": limit}
                if spent + chars > reserve or used + gap() + chars > limit:
                    st["outcome"] = "not reserved (reserve or budget full)"
                else:
                    spent += chars
                    used += gap() + chars
                    chosen.append(e.evidence_id)
                    handled.add(e.evidence_id)
                    st["outcome"] = "reserved"
                steps.append(st)
    for e in SELM._optional_order(registry, binding_first):
        if e.evidence_id in handled:
            continue
        st = {"phase": "soft budget", "citation": e.citation, "tier": e.tier, "method": e.result.retrieval_method,
              "used_before": used, "limit": limit}
        if e.tier != TIER_STRUCTURAL and not pipe.is_useful(e.result):
            st["outcome"] = "dropped: filtered"
            dropped.append((e.citation, "filtered"))
            steps.append(st)
            continue
        if len(chosen) >= policy.max_results:
            st["outcome"] = "dropped: max_results"
            dropped.append((e.citation, "max_results"))
            steps.append(st)
            continue
        text, trunc = SELM._truncate(SELM._clean(e.text), policy.max_chars_per_result)
        chars = SELM._block_chars(e, text, len(chosen) + 1, trunc)
        st["block_chars"] = chars
        if used + gap() + chars > limit:
            remaining = limit - used - gap()
            header = chars - len(text)
            st["remaining"] = remaining
            if remaining - header >= SELM.MIN_SQUEEZED_CHARS:
                text, trunc = SELM._truncate(text, remaining - header)
                chars = SELM._block_chars(e, text, len(chosen) + 1, True)
                st["outcome"], st["block_chars"] = "selected (squeezed to fit)", chars
            else:
                st["outcome"] = "dropped: soft_budget"
                dropped.append((e.citation, "soft_budget"))
                steps.append(st)
                continue
        else:
            st["outcome"] = "selected"
        used += gap() + chars
        chosen.append(e.evidence_id)
        steps.append(st)
    actual_sel = sorted(s.evidence.evidence_id for s in sel.selected)
    actual_drop = sorted((d.evidence.citation, d.reason) for d in sel.dropped)
    return {"steps": steps, "replay_matches_selection": sorted(chosen) == actual_sel and sorted(dropped) == actual_drop,
            "used_after": used, "actual_total_chars": sel.total_chars,
            "policy": {k: getattr(policy, k) for k in ("max_results", "max_chars_per_result", "max_total_chars", "binding_reserve_chars",
                                                        "hard_max_total_chars", "general_evidence_order")}}


LEXEME_SQL = f"""
WITH lex AS (SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', %(query)s))) AS l),
hits AS (
    SELECT r.section_number, r.paragraph_path, r.ordinal, lex.l
    FROM lex JOIN cfr_records r ON r.search_vector @@ quote_literal(lex.l)::tsquery
    WHERE NOT r.is_reserved
      {SQLM._ECFR_FILTERS}
),
df AS (SELECT l, count(DISTINCT section_number) AS n FROM hits GROUP BY l),
total AS (SELECT count(*)::float8 AS n FROM cfr_sections WHERE NOT is_reserved),
w AS (SELECT df.l, df.n AS df, ln(GREATEST(total.n / df.n, 1.0)) AS idf FROM df, total)
SELECT 'w' AS kind, NULL::text AS section_number, NULL::text AS paragraph_path, NULL::int AS ordinal, w.l, w.df, w.idf FROM w
UNION ALL
SELECT 'h', h.section_number, h.paragraph_path, h.ordinal, h.l, NULL, w.idf FROM hits h JOIN w USING (l)
WHERE h.section_number = ANY(%(secs)s)
"""


def lexeme_analysis(db, lex, terms, sections, leg_scores):
    params = {**lex._ecfr_filter_params(Filters()), "query": terms, "secs": sorted(sections)}
    rows = db.query(LEXEME_SQL, params)
    weights = {r["l"]: {"idf": round(float(r["idf"]), 4), "sections_containing": int(r["df"])} for r in rows if r["kind"] == "w"}
    mass = sum(v["idf"] for v in weights.values())
    per = {}
    for r in rows:
        if r["kind"] != "h":
            continue
        s = per.setdefault(r["section_number"], {"lexemes": {}, "rows": {}})
        s["lexemes"][r["l"]] = round(float(r["idf"]), 4)
        key = r["paragraph_path"] or "(section)"
        s["rows"].setdefault(key, {})[r["l"]] = round(float(r["idf"]), 4)
    out = {}
    for sec in sorted(sections):
        s = per.get(sec, {"lexemes": {}, "rows": {}})
        cov = sum(s["lexemes"].values())
        best_path, best = max(((p, sum(v.values())) for p, v in s["rows"].items()), key=lambda x: x[1], default=(None, 0.0))
        score = (cov + best) / mass if mass else None
        out[sec] = {"covered_lexemes": dict(sorted(s["lexemes"].items(), key=lambda kv: -kv[1])),
                    "section_cover": round(cov, 4), "best_paragraph": best_path, "best_paragraph_cover": round(best, 4),
                    "section_score_recomputed": round(score, 4) if score is not None else None,
                    "section_score_from_leg": leg_scores.get(sec),
                    "rows": {p: dict(sorted(v.items(), key=lambda kv: -kv[1])) for p, v in s["rows"].items()}}
    return {"question_lexemes": dict(sorted(weights.items(), key=lambda kv: -kv[1]["idf"])), "total_weight": round(mass, 4),
            "sections": out}


DB_SQL = """
SELECT section_number, paragraph_path, ordinal, length(body_text) AS chars, right(body_text, 100) AS tail,
       left(body_text, 160) AS head, is_reserved, removed_on
FROM cfr_records WHERE section_number = ANY(%(s)s) ORDER BY section_number, ordinal
"""


def db_rows(db, sections):
    rows = db.query(DB_SQL, {"s": sorted(sections)})
    paths = {(r["section_number"], r["paragraph_path"] or "") for r in rows if r["removed_on"] is None}
    out = {}
    for r in rows:
        p = r["paragraph_path"] or ""
        tail = (r["tail"] or "").rstrip()
        children = any(s == r["section_number"] and q.startswith(p + "(") for s, q in paths) if p else None
        out.setdefault(r["section_number"], []).append({
            "path": p or "(section)", "ordinal": r["ordinal"], "chars": r["chars"], "live": r["removed_on"] is None,
            "reserved": r["is_reserved"], "head": r["head"], "tail": tail,
            "ends_open": tail.endswith(":") or tail.endswith("following") or tail.endswith("—"),
            "has_children": children})
    return out


def main() -> int:
    out_dir = Path(sys.argv[1]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    assert os.environ.get("REGULUS_ECFR_LITERAL_OR") == "1" and L.ECFR_LITERAL_OR_ENABLED, "run under the experiment's switch"
    db = Database.from_env()
    db.connect()
    summary = {}
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        pipe, gen = RB.production_pipeline(db)
        lex = pipe.retriever.lexical
        calls: list = []
        for name in LEG_NAMES:
            fn = getattr(lex, name)

            def wrapped(*a, _fn=fn, _name=name, **k):
                rows = _fn(*a, **k)
                calls.append({"leg": _name, "input": next((x for x in a if isinstance(x, str)), str(a[0]) if a else None),
                              "rows": [row(r, i) for i, r in enumerate(rows, 1)]})
                return rows
            setattr(lex, name, wrapped)
        for qid in FAILED + CONTROLS:
            q = SEL[qid]
            calls.clear()
            question = q["Question (ask verbatim)"]
            out = pipe.answer(question)
            sel = out.selection
            prompt = [[s.result.citation.label, s.result.retrieval_method, s.tier, s.text] for s in out.context.sources]
            drops = [[d.get("citation"), d.get("reason")] for d in (out.metadata.get("selection") or {}).get("dropped") or []]
            reproduces = prompt == SAVED[qid]["sources"] and drops == SAVED[qid]["dropped"]
            expected = sorted(set(re.findall(r"\b(\d{2,3}\.\d+[a-z]?)\b", str(q["Expected Citation — VERIFIED KEY"]))))
            rc1 = [c for c in calls if c["leg"] == "section_coverage_ecfr"]
            rc1_secs = {section_of(r["citation"]) for c in rc1 for r in c["rows"]}
            leg_scores = {section_of(r["citation"]): r["metadata"].get("section_coverage") for c in rc1 for r in c["rows"]}
            prompt_secs = {section_of(p[0]) for p in prompt if section_of(p[0])}
            terms = " ".join(content_terms(question))
            plan = out.metadata.get("plan") or {}
            rec = {
                "id": qid, "question": question, "key_citation": str(q["Expected Citation — VERIFIED KEY"]),
                "key_elements": str(q["Key Answer Elements"]), "expected_sections": expected,
                "reproduces_saved_switch_on_replay": reproduces,
                "queries": {"ecfr_all_words": literal_or(plan.get("normalized_question") or question),
                            "guidance_all_words": plan.get("normalized_question") or question, "section_coverage_terms": terms},
                "legs": list(calls),
                "registry_order": [{"position": i, "evidence_id": e.evidence_id, "citation": e.citation, "corpus": e.result.corpus,
                                    "method": e.result.retrieval_method, "tier": e.tier, "score": round(float(e.result.relevance_score), 4),
                                    "chars": len(e.text or "")} for i, e in enumerate(out.evidence.evidence, 1)],
                "topk": [r.citation.label for r in out.retrieved_results],
                "selection": {"selected": [{"index": s.index, "citation": s.evidence.citation, "tier": s.evidence.tier,
                                            "method": s.evidence.result.retrieval_method, "chars": s.chars, "truncated": s.truncated,
                                            "reason": s.reason} for s in sel.selected],
                              "dropped": [{"citation": d.evidence.citation, "reason": d.reason, "tier": d.evidence.tier,
                                           "method": d.evidence.result.retrieval_method} for d in sel.dropped],
                              "total_chars": sel.total_chars, "diagnostics": sel.diagnostics},
                "budget_replay": budget_replay(out, pipe),
                "final_context": [{"index": i, "citation": p[0], "method": p[1], "tier": p[2], "chars": len(p[3])} for i, p in enumerate(prompt, 1)],
                "database": db_rows(db, set(expected)),
                "lexemes": lexeme_analysis(db, lex, terms, set(expected) | rc1_secs | (prompt_secs - {None}), leg_scores),
            }
            (out_dir / f"{qid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            summary[qid] = {"reproduces": reproduces, "budget_replay_matches": rec["budget_replay"]["replay_matches_selection"],
                            "rc1_sections": sorted(s for s in rc1_secs if s), "expected": expected,
                            "score_check": all(v["section_score_from_leg"] is None or abs(v["section_score_recomputed"] - v["section_score_from_leg"]) < 1e-3
                                               for v in rec["lexemes"]["sections"].values())}
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    summary["_run"] = {"generation_stub_calls": gen.calls, "semantic_load_attempts": len(SEMANTIC_ATTEMPTS),
                       "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
