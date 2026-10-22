"""Retrieval-only trace of the scope restrictions (no model, read-only database, no file outside <out_dir> written).

    python scope_trace.py <out_dir>

For each sample question, the production pipeline (RB.production_pipeline: configured RagConfig, factory retriever
with ScopePolicy + semantic fallback, NoGenerator) records:
  * the plan; every lexical leg's input text, the tsquery PostgreSQL built from it, its limit and returned rows;
  * the corpus, filters and top_k passed to run_plan;
  * the semantic-fallback record (lexical insufficiency, skip reason, whether the index would be queried);
  * the general-knowledge scope decision, the intent classifier's scope (analyze_question, as the gate computes it),
    the answerability decision, whether generation was blocked and whether the generator was called;
  * the final context and, for benchmark questions, the stage of each required paragraph.
Each question is run twice: production, and a counterfactual pipeline built identically except
RagConfig.scope_policy = "off" (in this process only: no ScopePolicy, no skip_semantic hook). The two retrievals and
contexts are compared item by item. Guards (guarded.py): SELECT-only queries; the semantic loader raises and every
attempt is counted, so no embedding model can load. Writes <out_dir>/scope_trace.json.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/retrieval_rootcause_20261021/tools"))
import trace_retrieval as T  # noqa: E402  (-> guarded: SELECT-only, semantic loader refused; asserts literal-OR switch unset)

from regulus.config import load_settings  # noqa: E402
from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.planning.intent import analyze_question  # noqa: E402
from regulus.rag.pipeline import RagPipeline  # noqa: E402
from regulus.retrieval import lexical as L  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.system_identity import configured_rag_config  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
BENCH = ["COS-73.2725-Q1", "COS-700.25-Q2", "COS-74.2317-Q1", "COS-70.55-Q1", "COS-FDCA609-Q1", "COS-70.3-Q3",
         "COS-740.11-Q2", "COS-710.5-Q1"]
CONTROLS = {"CTRL-capital": "What is the capital of France?",
            "CTRL-hamlet": "Who wrote Hamlet?",
            "CTRL-boiling": "What is the boiling point of water in Celsius?",
            "CTRL-eu": "What does EU Regulation (EC) No 1223/2009 require for a cosmetic product information file?"}


class Recorder:
    def __init__(self, lex, db):
        self.calls, self.run_plan_args, self.db = [], [], db
        for name in T.LEGS:
            fn = getattr(lex, name)

            def wrapped(*a, _fn=fn, _name=name, **k):
                rows = _fn(*a, **k)
                inp = next((x for x in a if isinstance(x, str)), None)
                self.calls.append({"leg": _name, "input": inp if inp is not None else repr(a[0])[:160],
                                   "tsquery": T.tsq(self.db, inp) if _name.startswith(("full_text", "section_coverage")) else None,
                                   "limit": next((x for x in reversed(a) if isinstance(x, int)), None),
                                   "rows": [r.citation.label for r in rows]})
                return rows
            setattr(lex, name, wrapped)
        rp = lex.run_plan

        def run_plan(plan, *a, **k):
            f = k.get("filters")
            self.run_plan_args.append({"corpus": k.get("corpus"), "top_k": k.get("top_k"), "methods": k.get("methods"),
                                       "filters": {x: getattr(f, x) for x in dir(f) if not x.startswith("_") and not callable(getattr(f, x))}
                                       if f is not None else None})
            return rp(plan, *a, **k)
        lex.run_plan = run_plan

    def reset(self):
        self.calls, self.run_plan_args = [], []


def build(db, scope_off: bool):
    config = configured_rag_config(load_settings())
    if scope_off:
        config = replace(config, scope_policy="off")
    retriever, scope = build_retriever(db, config, lexical=L.LexicalRetriever(db))
    gen = RB.NoGenerator()
    pipe = RagPipeline(retriever, gen, replace(config, top_k=8), grounding=None, scope_policy=scope)
    lex = getattr(retriever, "lexical", retriever)
    return pipe, gen, Recorder(lex, db), config


def run(pipe, gen, rec, question, req):
    rec.reset()
    calls_before = gen.calls
    out = pipe.answer(question)
    md = out.metadata
    plan = plan_query(question)
    a = analyze_question(plan)
    final = [s.result.citation.label for s in out.context.sources]
    status = {}
    for sec, paras in (req or {}).items():
        for p in sorted(paras) or [""]:
            lab = f"21 CFR {sec}{'(' + p + ')' if p else ''}"
            match = lambda c: T.split_cit(c)[0] == sec and (not p or (T.split_cit(c)[1] or "").startswith(f"({p})"))
            status[lab] = ("in final context" if any(match(c) for c in final) else
                           "returned, not in context" if any(match(c) for x in rec.calls for c in x["rows"]) else "never returned")
    ans = md.get("answerability") or {}
    return {"plan": {"kind": plan.kind, "requirements": [r.canonical for r in plan.requirements], "docket": plan.docket,
                     "normalized_question": plan.normalized_question},
            "run_plan_args": rec.run_plan_args, "legs": list(rec.calls),
            "semantic_fallback": md.get("semantic_fallback"),
            "scope_policy": md.get("scope_policy"),
            "intent_scope": {"scope_status": a.scope_status, "scope_reason": a.scope_reason, "out_of_scope_part": a.out_of_scope_part,
                             "question_type": a.question_type, "signals": list(a.signals)},
            "answerability": {k: ans.get(k) for k in ("state", "reason", "blocking_conditions", "acted_on")},
            "generation_blocked": md.get("generation_blocked"), "fallback_type": md.get("fallback_type"),
            "generator_called": gen.calls > calls_before, "final_context": final, "required_status": status}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db = Database.from_env()
    db.connect()
    res = {}
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        prod, gen_p, rec_p, cfg_p = build(db, scope_off=False)
        off, gen_o, rec_o, cfg_o = build(db, scope_off=True)
        assert cfg_p.scope_policy == "general_knowledge" and cfg_o.scope_policy == "off"
        questions = {qid: (T.SEL[qid]["Question (ask verbatim)"], T.required(T.SEL[qid])) for qid in BENCH}
        questions.update({k: (q, None) for k, q in CONTROLS.items()})
        for qid, (q, req) in questions.items():
            p = run(prod, gen_p, rec_p, q, req)
            o = run(off, gen_o, rec_o, q, req)
            strip = lambda r: [(c["leg"], c["input"], c["limit"], c["rows"]) for c in r["legs"]]
            res[qid] = {"question": q, "key": str(T.SEL[qid]["Expected Citation — VERIFIED KEY"]) if qid in T.SEL else None,
                        "production": p,
                        "scope_off": {k: o[k] for k in ("semantic_fallback", "scope_policy", "answerability", "generation_blocked",
                                                         "fallback_type", "generator_called", "final_context", "required_status")},
                        "same_retrieval_legs": strip(p) == strip(o), "same_run_plan_args": p["run_plan_args"] == o["run_plan_args"],
                        "same_final_context": p["final_context"] == o["final_context"]}
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    res["_run"] = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS),
                   "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
                   "corpus_identity": fp0["corpus_identity"]["ecfr"]}
    (OUT / "scope_trace.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    for qid, r in res.items():
        if qid.startswith("_"):
            continue
        p = r["production"]
        print(f"{qid:15} legs_same={r['same_retrieval_legs']!s:5} ctx_same={r['same_final_context']!s:5} "
              f"scope={(p['scope_policy'] or {}).get('status')} intent={p['intent_scope']['scope_status']} "
              f"gate={p['answerability']['state']} blocked={p['generation_blocked']} gen={p['generator_called']} "
              f"sem={(p['semantic_fallback'] or {}).get('lexical_insufficient')}/{(p['semantic_fallback'] or {}).get('skipped')} "
              f"| off: gate={r['scope_off']['answerability']['state']} blocked={r['scope_off']['generation_blocked']} gen={r['scope_off']['generator_called']}")
    print(json.dumps(res["_run"], default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
