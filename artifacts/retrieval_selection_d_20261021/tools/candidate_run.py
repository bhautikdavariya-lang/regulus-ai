"""Run the 100 cosmetics questions under three selections and build the blinded guidance-relevance pool.

    python candidate_run.py <out_dir>

Conditions, all on the production pipeline with a stub generator (no model), read-only database:
  base  ContextPolicy default ("tier");
  v1    the candidate: general_evidence_order = "ecfr_discovery_first" (the code under test, switched on in process);
  v2    comparator only: the base pipeline with each general question's registry reordered eCFR-first in every tier
        before selection (the root-cause report's D simulation, harness only).
Per question and condition: the final context (citation, corpus, tier, method, key, chars, text, guidance title and
sector), the stage of each required paragraph (verified key, as trace_retrieval.required), and totals.
Pool (PREREGISTRATION.md): every guidance passage that differs between base and v1 or base and v2, plus 40 fillers
in both base and v1 (seed 20261021); shuffled (same seed). Writes candidates.json, pool_blind.json (what judges see)
and pool_key.json (never shown to judges).
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/retrieval_rootcause_20261021/tools"))
import trace_retrieval as T  # noqa: E402  (-> guarded: SELECT-only, semantic loader refused; literal-OR switch unset)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import selection as SELM  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
SEED = 20261021


def ctx(out, req):
    srcs = []
    for s in out.context.sources:
        r = s.result
        srcs.append({"citation": r.citation.label, "corpus": r.corpus, "tier": s.tier, "method": r.retrieval_method, "key": r.key,
                     "chars": len(s.text), "truncated": s.truncated, "text": s.text,
                     "title": (r.citation.label if r.corpus != "ecfr" else None), "sector": (r.metadata or {}).get("sector")})
    final = [s["citation"] for s in srcs]
    status = {}
    for sec, paras in req.items():
        for p in sorted(paras) or [""]:
            lab = f"21 CFR {sec}{'(' + p + ')' if p else ''}"
            if lab == "21 CFR 740.11(i)":
                continue  # mis-parsed key ("(b)(2)(i)-(iv)"), excluded as in every earlier report
            match = lambda c: T.split_cit(c)[0] == sec and (not p or (T.split_cit(c)[1] or "").startswith(f"({p})"))
            status[lab] = any(match(c) for c in final)
    return {"sources": srcs, "required_in_context": status, "total_chars": out.selection.total_chars if out.selection else None,
            "n_sources": len(srcs), "dropped": [(d.evidence.citation, d.reason) for d in (out.selection.dropped if out.selection else ())],
            "diag_order": (out.selection.diagnostics or {}).get("general_evidence_order") if out.selection else None}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db = Database.from_env()
    db.connect()
    res = {}
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        fp0 = RB.database_fingerprint(db)
        base, gb = RB.production_pipeline(db)
        v1, g1 = RB.production_pipeline(db, general_evidence_order="ecfr_discovery_first")
        assert base.config.context.general_evidence_order == "tier" and v1.config.context.general_evidence_order == "ecfr_discovery_first"
        v2, g2 = RB.production_pipeline(db)
        original = v2.select

        def select(registry, shape=None, question=None):
            if SELM._binding_reserve_applies(registry):
                ev = list(registry.evidence)
                registry = replace(registry, evidence=tuple([e for e in ev if e.result.corpus == "ecfr"] + [e for e in ev if e.result.corpus != "ecfr"]))
            return original(registry, shape, question)
        v2.select = select
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            plan = plan_query(question)
            req = T.required(q)
            res[qid] = {"question": question, "general": not plan.requirements and plan.docket is None,
                        "base": ctx(base.answer(question), req), "v1": ctx(v1.answer(question), req), "v2": ctx(v2.answer(question), req)}
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    run = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "generator_calls": [gb.calls, g1.calls, g2.calls],
           "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
           "corpus_identity": fp0["corpus_identity"]["ecfr"]}
    (OUT / "candidates.json").write_text(json.dumps({"run": run, "questions": res}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    # pool: guidance passages that differ (by key) between base and v1 / base and v2, per question
    items, both_v1 = {}, []
    for qid, r in res.items():
        g = {c: {s["key"]: s for s in r[c]["sources"] if s["corpus"] != "ecfr"} for c in ("base", "v1", "v2")}
        for cond in ("v1", "v2"):
            for k in g["base"].keys() - g[cond].keys():
                items.setdefault((qid, k), {"qid": qid, "key": k, "text": g["base"][k]["text"], "title": g["base"][k]["title"],
                                            "roles": set()})["roles"].add(f"removed_by_{cond}")
            for k in g[cond].keys() - g["base"].keys():
                items.setdefault((qid, k), {"qid": qid, "key": k, "text": g[cond][k]["text"], "title": g[cond][k]["title"],
                                            "roles": set()})["roles"].add(f"added_by_{cond}")
        both_v1 += [(qid, k) for k in g["base"].keys() & g["v1"].keys()]
    rng = random.Random(SEED)
    fillers = rng.sample(sorted(both_v1), min(40, len(both_v1)))
    for qid, k in fillers:
        s = next(x for x in res[qid]["base"]["sources"] if x["key"] == k)
        items.setdefault((qid, k), {"qid": qid, "key": k, "text": s["text"], "title": s["title"], "roles": set()})["roles"].add("filler_kept_by_v1")
    order = sorted(items)
    rng.shuffle(order)
    blind, key = [], {}
    for n, ik in enumerate(order, 1):
        it = items[ik]
        iid = f"G{n:03d}"
        blind.append({"item": iid, "question": res[it["qid"]]["question"], "guidance_document": it["title"], "passage": it["text"]})
        key[iid] = {"qid": it["qid"], "key": it["key"], "roles": sorted(it["roles"])}
    (OUT / "pool_blind.json").write_text(json.dumps(blind, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "pool_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")
    roles = {}
    for v in key.values():
        for r in v["roles"]:
            roles[r] = roles.get(r, 0) + 1
    print(json.dumps({"run": run, "pool_items": len(blind), "roles": roles}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
