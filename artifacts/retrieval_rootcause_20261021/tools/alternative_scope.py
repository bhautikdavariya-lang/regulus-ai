"""Scope of correction A: is removing the operator word from the eCFR AND leg alone enough, or does the guidance AND
leg need it too? Harness only; the production switch stays unset. Runs the general questions whose question contains a
standalone "or" (the only ones A can change) under A_ecfr (eCFR leg only) and A_ecfr+D, and compares with the A, D and
AD results in alternatives.json.

    python alternative_scope.py <out_json>
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

OUT = Path(sys.argv[1]).resolve()
sys.argv = [sys.argv[0], str(OUT.parent)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import causal_checks as CC  # noqa: E402

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import selection as SELM  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

T = CC.T
PREV = json.loads((OUT.parent / "alternatives.json").read_text(encoding="utf-8"))["per_question"]


def main() -> int:
    db = Database.from_env()
    db.connect()
    res = {}
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        fp0 = RB.database_fingerprint(db)
        run = CC.Runner(db)
        pipe, original_select, mode = run.pipe, run.pipe.select, {"D": False}

        def select(registry, shape=None, question=None):
            if mode["D"] and SELM._binding_reserve_applies(registry):
                ev = list(registry.evidence)
                registry = replace(registry, evidence=tuple([e for e in ev if e.result.corpus == "ecfr"] + [e for e in ev if e.result.corpus != "ecfr"]))
            return original_select(registry, shape, question)
        pipe.select = select
        original_answer = run.answer

        def answer_ecfr_only(question, d):
            # the wrapper transforms both AND legs; restrict it to the eCFR leg here
            run.calls, run.transform = [], None
            fn = run.lex.full_text_ecfr
            run.lex.full_text_ecfr = lambda q, *a, **k: fn(CC.OP_RE.sub(" ", q), *a, **k)
            mode["D"] = d
            try:
                return pipe.answer(question)
            finally:
                run.lex.full_text_ecfr = fn
                mode["D"] = False
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            plan = plan_query(question)
            if plan.requirements or plan.docket is not None or not CC.OP_RE.search(question):
                continue
            req = T.required(q)
            rec = {}
            for cond, d in (("A_ecfr", False), ("A_ecfr+D", True)):
                out = answer_ecfr_only(question, d)
                c = CC.compact(out, list(run.calls), req)
                rec[cond] = {"required_status": c["required_status"], "final": c["final_context"],
                             "legs": [(l["leg"], l["input"][:60] if l["input"] else None, l["rows"]) for l in c["legs"]]}
            for cond in ("base", "A", "D", "AD"):
                rec[cond] = {"required_status": PREV[qid]["conditions"][cond]["required_status"]}
            res[qid] = rec
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    count = lambda cond: sum(1 for r in res.values() for v in r[cond]["required_status"].values() if v == "in final context")
    summary = {"questions": sorted(res), "required_in_context": {c: count(c) for c in ("base", "A_ecfr", "A", "D", "A_ecfr+D", "AD")},
               "run": {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "ecfr_literal_or_flag": CC.L.ECFR_LITERAL_OR_ENABLED,
                       "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))}}
    OUT.write_text(json.dumps({"summary": summary, "per_question": res}, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
