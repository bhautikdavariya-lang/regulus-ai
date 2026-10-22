"""S1 offline simulation (PREREGISTRATION.md): value-per-cost selection in the soft-budget phase, in process only.

    python s1_sim.py <out_dir>

`regulus.rag.pipeline.select_evidence` is replaced in this process by a copy of `selection.select_evidence` whose
soft-budget phase gains the S1 greedy step (only when `_binding_reserve_applies`); everything else is the module's
own code, compiled from its source. Arm S1+F2 also replaces `section_coverage_ecfr` on the lexical instance with the
8-per-section / 16-total caps (as fixb_measure.py). Production pipeline, stub generator, read-only database behind the
guarded.py guards. Writes <out_dir>/eval100.json and <out_dir>/runs_352/<cond>.jsonl only.
"""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/retrieval_rootcause_20261021/tools"))
import trace_retrieval as T  # noqa: E402  (-> guarded: SELECT-only, semantic loader refused)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import pipeline as P  # noqa: E402
from regulus.rag import selection as S  # noqa: E402
from regulus.retrieval import sql  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.lexical import METHOD_FULL_TEXT_OR, SECTION_COVERAGE_ROWS_PER_SECTION  # noqa: E402
from regulus.retrieval.query import content_terms  # noqa: E402
from regulus.retrieval.ranking import section_coverage_score  # noqa: E402

sys.path.insert(0, str(ROOT / "artifacts/retrieval_selection_design_20261021/tools"))
_saved_argv = sys.argv
sys.argv = [sys.argv[0], str(ROOT / "artifacts/retrieval_selection_s1_sim_20261021")]
from signal_check import TEXT_LEX, WEIGHTS_SQL  # noqa: E402
sys.argv = _saved_argv

OUT = Path(sys.argv[1]).resolve()
assert SECTION_COVERAGE_ROWS_PER_SECTION == 2
STATE = {"s1": False, "cov": "base", "question": None, "db": None, "last": None}
CAPS = {"base": (SECTION_COVERAGE_ROWS_PER_SECTION, None), "F2": (8, 16)}
_W, _LEX = {}, {}

# ---------------------------------------------------------------- S1 selector, compiled from selection.py's source
SRC = Path(S.__file__).read_text(encoding="utf-8")
SRC_SHA = hashlib.sha256(SRC.encode()).hexdigest()
LOOP = "    # Phases 2-4: optional evidence within the soft budget, never displacing the above\n"
RESORT = "    if reserved_ids or binding_first:\n        # registry order"
GREEDY = '''    s1_ids: list[str] = []
    if _S1["on"]() and _binding_reserve_applies(registry):
        limit = min(policy.max_total_chars, policy.hard_max_total_chars)
        weights = _S1["weights"]()
        covered: set[str] = set()
        for s in selected:
            covered |= _S1["lex"](s.text, s.evidence.citation)
        cands = []
        for pos, e in enumerate(_optional_order(registry, binding_first)):
            if is_required(e) or e.evidence_id in handled:
                continue
            if e.tier != TIER_STRUCTURAL and optional_filter is not None and not optional_filter(e.result):
                continue  # recorded as filtered by the loop below
            text, truncated = _truncate(_clean(e.text), policy.max_chars_per_result)
            cands.append((pos, e, text, truncated, _S1["lex"](text, e.citation)))
        while cands and len(selected) < policy.max_results and len(selected) < policy.hard_max_results:
            best = None
            for c in cands:
                pos, e, text, truncated, lex = c
                chars = _block_chars(e, text, len(selected) + 1, truncated)
                if used + gap() + chars > limit:
                    continue
                value = sum(w for l, w in weights.items() if l in lex and l not in covered)
                if value <= 0:
                    continue
                rank = (value / chars, -pos)
                if best is None or rank > best[0]:
                    best = (rank, c, chars)
            if best is None:
                break
            _, c, chars = best
            pos, e, text, truncated, lex = c
            used += gap() + chars
            selected.append(SelectedEvidence(len(selected) + 1, e, text, truncated, False, _reason(e), chars))
            handled.add(e.evidence_id)
            s1_ids.append(e.evidence_id)
            covered |= lex
            cands.remove(c)

'''
assert SRC.count(LOOP) == 1 and SRC.count(RESORT) == 1
S1_SRC = SRC.replace(LOOP, GREEDY + LOOP).replace(RESORT, RESORT.replace("reserved_ids or binding_first", "reserved_ids or binding_first or s1_ids"))
s1mod = types.ModuleType("s1_selection")
s1mod.__dict__["_S1"] = {
    "on": lambda: STATE["s1"],
    "weights": lambda: weights(STATE["question"]),
    "lex": lambda text, citation: lexemes(f"{text} {citation}"),
}
sys.modules["s1_selection"] = s1mod
exec(compile(S1_SRC, "s1_selection.py", "exec"), s1mod.__dict__)
for _name in ("SelectedEvidence", "DroppedEvidence", "Selection"):  # production's classes, so downstream sees the same types
    setattr(s1mod, _name, getattr(S, _name))


def weights(question: str) -> dict[str, float]:
    if question not in _W:
        _W[question] = {r["l"]: float(r["idf"]) for r in STATE["db"].query(WEIGHTS_SQL, {"q": " ".join(content_terms(question))})}
    return _W[question]


def lexemes(t: str) -> set[str]:
    if t not in _LEX:
        _LEX[t] = frozenset(STATE["db"].query(TEXT_LEX, {"t": t})[0]["a"] or [])
    return _LEX[t]


# ---------------------------------------------------------------- harness
def install(pipe):
    lex = pipe.retriever.lexical

    def section_coverage_ecfr(terms, filters, limit):
        per, total = CAPS[STATE["cov"]]
        rows = lex.db.query(sql.ECFR_SECTION_COVERAGE,
                            {**lex._ecfr_filter_params(filters), "query": terms, "sections": limit,
                             "rows_per_section": per, "limit": total if total is not None else limit})
        return [lex._ecfr_result(row, METHOD_FULL_TEXT_OR, section_coverage_score(row["section_score"], row["row_score"]),
                                 {"section_coverage": round(float(row["section_score"]), 4),
                                  "paragraph_coverage": round(float(row["row_score"]), 4), "coverage_terms": terms})
                for row in rows]
    lex.section_coverage_ecfr = section_coverage_ecfr
    P.select_evidence = s1mod.select_evidence  # identical to production while STATE["s1"] is False
    real = pipe.answer

    def answer(question, *a, **k):
        STATE["question"] = question
        out = real(question, *a, **k)
        STATE["last"] = out
        return out
    pipe.answer = answer


def ctx(out) -> dict:
    sel = out.selection
    reg = list(out.evidence.evidence) if out.evidence is not None else []
    pos = {e.evidence_id: i for i, e in enumerate(reg)}
    srcs = out.context.sources
    sel_ids = [s.evidence.evidence_id for s in sel.selected] if sel else []
    opt = [pos.get(s.evidence.evidence_id, -1) for s in sel.selected if not s.protected and s.reason != "subordinate_of_requested"] if sel else []
    return {"sources": [{"citation": s.result.citation.label, "corpus": s.result.corpus, "key": s.result.key, "chars": len(s.text),
                         "tier": s.tier, "truncated": s.truncated, "text": s.text} for s in srcs],
            "total_chars": sel.total_chars if sel else None, "n": len(srcs),
            "optional_in_registry_order": opt == sorted(opt), "selected_ids": sel_ids,
            "general": S._binding_reserve_applies(out.evidence) if out.evidence is not None else False}


def hit(cits, sec, p):
    return any(T.split_cit(c)[0] == sec and (not p or (T.split_cit(c)[1] or "").startswith(f"({p})")) for c in cits)


def record100(out, req):
    reg = [e.citation for e in out.evidence.evidence] if out.evidence is not None else []
    c = ctx(out)
    final = [s["citation"] for s in c["sources"]]
    st = {}
    for sec, paras in req.items():
        for p in sorted(paras) or [""]:
            lab = f"21 CFR {sec}{'(' + p + ')' if p else ''}"
            if lab != "21 CFR 740.11(i)":
                st[lab] = {"candidate": hit(reg, sec, p), "in_context": hit(final, sec, p)}
    return {"required": st, **c}


ARMS = {"base": (False, "base"), "S1": (True, "base"), "S1F2": (True, "F2")}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs_352").mkdir(exist_ok=True)
    db = Database.from_env()
    db.connect()
    STATE["db"] = db
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        fp0 = RB.database_fingerprint(db)
        pipe, gen = RB.production_pipeline(db)
        install(pipe)
        q100 = {}
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            plan = plan_query(question)
            req = T.required(q)
            q100[qid] = {"question": question, "general_plan": not plan.requirements and plan.docket is None}
            for cond, (s1, cov) in (*ARMS.items(), ("S1_rep2", (True, "base")), ("S1F2_rep2", (True, "F2"))):
                STATE["s1"], STATE["cov"] = s1, cov
                try:
                    q100[qid][cond] = record100(pipe.answer(question), req)
                finally:
                    STATE["s1"], STATE["cov"] = False, "base"
        print("100 done", flush=True)
        rows = RB.load_dataset()
        lookup = RB.CorpusLookup(db)
        summ = {}
        for cond, (s1, cov) in ARMS.items():
            STATE["s1"], STATE["cov"] = s1, cov
            recs = []
            try:
                with (OUT / "runs_352" / f"{cond}.jsonl").open("w", encoding="utf-8") as f:
                    for row in rows:
                        STATE["last"] = None
                        rec = RB.run_question(pipe, gen, lookup, row)
                        recs.append(rec)
                        rec = {**rec, "s1_context": ctx(STATE["last"]) if STATE["last"] is not None else None}
                        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            finally:
                STATE["s1"], STATE["cov"] = False, "base"
            summ[cond] = RB.summarise(recs)
            print(cond, "352 done", flush=True)
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    run = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "generator_calls": gen.calls,
           "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
           "corpus_identity": fp0["corpus_identity"]["ecfr"], "selection_source_sha256": SRC_SHA}
    (OUT / "eval100.json").write_text(json.dumps({"run": run, "questions": q100, "summary_352": summ}, indent=1,
                                                 ensure_ascii=False, default=str))
    print(json.dumps(run, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
