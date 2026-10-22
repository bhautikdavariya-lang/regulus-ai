"""Experiment 2: run the 100 cosmetics questions under base and the guidance-floor candidate; build the A3 pool.

    python candidate_run.py <out_dir>

Conditions, all on the production pipeline with a stub generator (no model), read-only database:
  base  ContextPolicy default ("tier");
  c2    the candidate: general_evidence_order = "ecfr_discovery_first_guidance_floor" (the code under test, switched
        on in process only).
Per question and condition: the final context (citation, corpus, tier, method, key, chars, text, guidance title and
sector), the stage of each required paragraph (verified key, as trace_retrieval.required), and totals.
Pool (PREREGISTRATION.md): every guidance passage removed or added by c2 relative to base. Items judged in
experiment 1 (same question, key and text) reuse their adjudicated label; the others, with 20 fillers kept by both
(seed 20261021), shuffled (same seed), form the blind pool. Writes candidates.json, reused_labels.json,
pool_blind.json (what judges see) and pool_key.json (never shown to judges).
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
        c2, g2 = RB.production_pipeline(db, general_evidence_order="ecfr_discovery_first_guidance_floor")
        assert base.config.context.general_evidence_order == "tier"
        assert c2.config.context.general_evidence_order == "ecfr_discovery_first_guidance_floor"
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            plan = plan_query(question)
            req = T.required(q)
            res[qid] = {"question": question, "general": not plan.requirements and plan.docket is None,
                        "base": ctx(base.answer(question), req), "c2": ctx(c2.answer(question), req)}
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    run = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "generator_calls": [gb.calls, g2.calls],
           "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
           "corpus_identity": fp0["corpus_identity"]["ecfr"]}
    (OUT / "candidates.json").write_text(json.dumps({"run": run, "questions": res}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    # pool: guidance passages removed or added by c2, per question; reuse experiment-1 labels for identical items
    E1 = ROOT / "artifacts/retrieval_selection_d_20261021"
    e1_rel = json.loads((E1 / "relevance.json").read_text())
    e1_text = {it["item"]: it["passage"] for it in json.loads((E1 / "pool_blind.json").read_text())}
    prior = {(v["qid"], v["key"]): (v["label"], e1_text[i]) for i, v in e1_rel.items()}
    changed, both = {}, []
    for qid, r in res.items():
        g = {c: {s["key"]: s for s in r[c]["sources"] if s["corpus"] != "ecfr"} for c in ("base", "c2")}
        for k in g["base"].keys() - g["c2"].keys():
            changed[(qid, k)] = {"qid": qid, "key": k, "text": g["base"][k]["text"], "title": g["base"][k]["title"], "roles": ["removed_by_c2"]}
        for k in g["c2"].keys() - g["base"].keys():
            changed[(qid, k)] = {"qid": qid, "key": k, "text": g["c2"][k]["text"], "title": g["c2"][k]["title"], "roles": ["added_by_c2"]}
        both += [(qid, k) for k in g["base"].keys() & g["c2"].keys()]
    reused, new = {}, {}
    for ik, it in changed.items():
        p = prior.get(ik)
        if p is not None and p[1] == it["text"]:
            reused[f"{ik[0]}|{ik[1]}"] = {**it, "label": p[0], "source": "experiment 1 adjudicated label"}
        else:
            new[ik] = it
    (OUT / "reused_labels.json").write_text(json.dumps(reused, indent=1, ensure_ascii=False), encoding="utf-8")
    rng = random.Random(SEED)
    items = dict(new)
    if new:
        for qid, k in rng.sample(sorted(both), min(20, len(both))):
            s = next(x for x in res[qid]["base"]["sources"] if x["key"] == k)
            items.setdefault((qid, k), {"qid": qid, "key": k, "text": s["text"], "title": s["title"], "roles": ["filler_kept_by_c2"]})
    order = sorted(items)
    rng.shuffle(order)
    blind, key = [], {}
    for n, ik in enumerate(order, 1):
        it = items[ik]
        iid = f"H{n:03d}"
        blind.append({"item": iid, "question": res[it["qid"]]["question"], "guidance_document": it["title"], "passage": it["text"]})
        key[iid] = {"qid": it["qid"], "key": it["key"], "roles": sorted(it["roles"])}
    (OUT / "pool_blind.json").write_text(json.dumps(blind, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "pool_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")
    roles = {}
    for v in key.values():
        for r in v["roles"]:
            roles[r] = roles.get(r, 0) + 1
    print(json.dumps({"run": run, "changed_guidance": len(changed), "reused_labels": len(reused), "new_items_to_judge": len(new),
                      "pool_items": len(blind), "roles": roles}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
