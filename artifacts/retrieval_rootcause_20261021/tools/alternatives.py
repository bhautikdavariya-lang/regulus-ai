"""Offline comparison: current retrieval against two single harness-only alternatives, one per confirmed mechanism,
and both together. No production code, configuration or switch is changed; no model.

    python alternatives.py <out_json>

Conditions (an alternative applies only to a general question: no named provision, no docket):
  base  production as is (checked against traces_all/: same final context);
  A     the operator word "or" removed from the question given to the two AND legs (full_text_ecfr,
        full_text_guidance), so the AND query means AND and the section-coverage gate sees its real result;
  D     at selection only, within each tier the eCFR rows go ahead of the guidance rows (each keeps its registry
        order); retrieval, candidates, tiers, budgets and limits unchanged;
  AD    both.
Metric, per required paragraph of the verified key (as trace_retrieval.required): in the final context or not.
Also per question: the final context's eCFR and guidance characters, and the guidance sector of every guidance
passage an alternative removes. Writes only <out_json>.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

OUT = Path(sys.argv[1]).resolve()
sys.argv = [sys.argv[0], str(OUT.parent)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import causal_checks as CC  # noqa: E402  (-> trace_retrieval -> guarded)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import selection as SELM  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

T = CC.T
TRACES = OUT.parent / "traces_all"


def ecfr_first(registry):
    ev = list(registry.evidence)
    return replace(registry, evidence=tuple([e for e in ev if e.result.corpus == "ecfr"] + [e for e in ev if e.result.corpus != "ecfr"]))


def main() -> int:
    db = Database.from_env()
    db.connect()
    res = {}
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        run = CC.Runner(db)
        pipe = run.pipe
        original_select = pipe.select
        mode = {"D": False}

        def select(registry, shape=None, question=None):
            if mode["D"] and SELM._binding_reserve_applies(registry):
                registry = ecfr_first(registry)
            return original_select(registry, shape, question)
        pipe.select = select
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            plan = plan_query(question)
            general = not plan.requirements and plan.docket is None
            req = T.required(q)
            rec = {"general": general, "conditions": {}}
            for cond in ("base", "A", "D", "AD"):
                if not general and cond != "base":
                    continue
                mode["D"] = "D" in cond
                out = run.answer(question, transform=(lambda s: CC.OP_RE.sub(" ", s)) if "A" in cond else None)
                mode["D"] = False
                c = CC.compact(out, list(run.calls), req)
                srcs = out.context.sources
                rec["conditions"][cond] = {
                    "required_status": c["required_status"],
                    "final": [(s.result.citation.label, s.result.corpus, len(s.text), (s.result.metadata or {}).get("sector")) for s in srcs],
                    "ecfr_chars": sum(len(s.text) for s in srcs if s.result.corpus == "ecfr"),
                    "guidance_chars": sum(len(s.text) for s in srcs if s.result.corpus != "ecfr"),
                    "legs": [(l["leg"], l["rows"]) for l in c["legs"]]}
            tr = json.loads((TRACES / f"{qid}.json").read_text(encoding="utf-8"))
            rec["base_equals_trace"] = [s[0] for s in rec["conditions"]["base"]["final"]] == [f["citation"] for f in tr["final_context"]]
            res[qid] = rec
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()

    def ok(st):
        return {k for k, v in st.items() if v == "in final context"}
    summ = {"base_equals_trace": sum(r["base_equals_trace"] for r in res.values()), "questions": len(res)}
    gen = {k: r for k, r in res.items() if r["general"]}
    keyed = {k: r for k, r in gen.items() if r["conditions"]["base"]["required_status"]}
    base_ok = {k: ok(r["conditions"]["base"]["required_status"]) for k, r in keyed.items()}
    for cond in ("A", "D", "AD"):
        gained, lost, q_gain, q_loss, guid_removed = [], [], set(), set(), {}
        for k, r in keyed.items():
            now = ok(r["conditions"][cond]["required_status"])
            for lab in sorted(now - base_ok[k]):
                gained.append(f"{k} {lab}"); q_gain.add(k)
            for lab in sorted(base_ok[k] - now):
                lost.append(f"{k} {lab}"); q_loss.add(k)
        for k, r in gen.items():
            bset = {(f[0]) for f in r["conditions"]["base"]["final"] if f[1] != "ecfr"}
            cset = {(f[0]) for f in r["conditions"][cond]["final"] if f[1] != "ecfr"}
            for f in r["conditions"]["base"]["final"]:
                if f[1] != "ecfr" and f[0] in bset - cset:
                    guid_removed[f[3] or "none"] = guid_removed.get(f[3] or "none", 0) + 1
        summ[cond] = {
            "required_paragraphs_in_context": sum(len(ok(r["conditions"][cond]["required_status"])) for r in keyed.values()),
            "questions_with_any_required_in_context": sum(1 for r in keyed.values() if ok(r["conditions"][cond]["required_status"])),
            "questions_with_all_required_in_context": sum(1 for r in keyed.values()
                                                          if ok(r["conditions"][cond]["required_status"]) == set(r["conditions"][cond]["required_status"])),
            "paragraphs_gained": gained, "paragraphs_lost": lost, "questions_gained": len(q_gain), "questions_lost": len(q_loss),
            "ecfr_chars": sum(r["conditions"][cond]["ecfr_chars"] for r in gen.values()),
            "guidance_chars": sum(r["conditions"][cond]["guidance_chars"] for r in gen.values()),
            "guidance_passages_removed_by_sector": guid_removed}
    summ["base"] = {"required_paragraphs": sum(len(r["conditions"]["base"]["required_status"]) for r in keyed.values()),
                    "required_paragraphs_in_context": sum(len(v) for v in base_ok.values()),
                    "questions_with_any_required_in_context": sum(1 for v in base_ok.values() if v),
                    "questions_with_all_required_in_context": sum(1 for k, r in keyed.items()
                                                                  if base_ok[k] == set(r["conditions"]["base"]["required_status"])),
                    "ecfr_chars": sum(r["conditions"]["base"]["ecfr_chars"] for r in gen.values()),
                    "guidance_chars": sum(r["conditions"]["base"]["guidance_chars"] for r in gen.values()),
                    "general_questions": len(gen), "general_with_ecfr_key": len(keyed)}
    summ["run"] = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "generation_stub_calls": run.gen.calls,
                   "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
                   "ecfr_literal_or_flag": CC.L.ECFR_LITERAL_OR_ENABLED}
    OUT.write_text(json.dumps({"summary": summ, "per_question": res}, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: ({kk: vv for kk, vv in v.items() if kk not in ("paragraphs_gained", "paragraphs_lost")} if isinstance(v, dict) else v)
                      for k, v in summ.items()}, indent=1))
    for cond in ("A", "D", "AD"):
        print(cond, "gained:", summ[cond]["paragraphs_gained"])
        print(cond, "lost:", summ[cond]["paragraphs_lost"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
