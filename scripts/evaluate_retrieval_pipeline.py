"""Retrieval evaluation through the answering pipeline's own retrieval path (Stage 7). No model is loaded.

    python scripts/evaluate_retrieval_pipeline.py [--dataset data/evaluation/datasets/retrieval_v2.jsonl]

For every query, both configurations are run through RagPipeline's retrieval path
(reference-lookup re-plan, run_plan, scope policy, coverage and selection):

  A  lexical only              semantic_fallback="off"
  B  lexical + semantic fallback semantic_fallback="on"

and scored on (1) the ranked evidence list (Recall@1/5/10, MRR) and (2) the evidence actually
selected for the prompt (selected-evidence recall). Negative controls (empty `expected`) pass when
nothing matching is ranked. Per query it records the fallback decision and whether B recovered,
degraded or left the query unchanged. Retrieval metrics only: nothing here measures answers.

Output: artifacts/retrieval_eval/<label>_<utc>/ (per_query.jsonl, summary.json).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from regulus.config import load_settings  # noqa: E402
from regulus.evaluation.retrieval_eval import first_hit_rank, load_retrieval_dataset, target_matches  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import RagPipeline  # noqa: E402
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from run_diagnostics import configured_rag_config  # noqa: E402

KS = (1, 5, 10)


def benchmark_draft_queries():
    """Benchmark questions whose DRAFT expected citation names a CFR provision. The drafts are not expert
    verified: they serve as retrieval targets for comparing A and B, never as answer keys."""
    from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
    from regulus.evaluation.retrieval_eval import RetrievalQuery
    from regulus.retrieval.references import parse_cfr_references
    out = []
    for q in load_acceptance_benchmark().questions:
        targets = tuple(dict.fromkeys(r.canonical for r in parse_cfr_references(q.expected_citation_draft or "")))
        if targets:
            out.append(RetrievalQuery(q.question_id, q.question_type, q.question, targets, "draft citation (unverified)", True))
    return out


def run_one(pipe: RagPipeline, question: str) -> dict:
    plan = plan_query(question)
    plan, targets = pipe.reference_lookup_plan(plan)
    shape, _ = pipe.question_view(plan)
    response, registry = pipe.retrieve(question, plan, targets)
    scope = pipe.scope_policy.decide(question, plan, response.diagnostics, results=bool(response.results)) if pipe.scope_policy else None
    bundle, _, _ = pipe.build_bundle(response, registry, shape)
    fb = response.diagnostics.get("semantic_fallback") or {}
    return {"results": response.results, "selected": [s.result for s in bundle.sources], "fallback_invoked": bool(fb.get("invoked")),
            "insufficient": fb.get("lexical_insufficient"), "skipped": fb.get("skipped"), "scope": scope.status if scope else None,
            "mode": response.diagnostics.get("retrieval_mode")}


def score(q, out) -> dict:
    rank = first_hit_rank(q.expected, out["results"]) if q.expected else None
    sel = any(any(target_matches(t, r) for t in q.expected) for r in out["selected"]) if q.expected else None
    return {"rank": rank, "selected_hit": sel, **{k: out[k] for k in ("fallback_invoked", "insufficient", "skipped", "scope", "mode")}}


def summary(rows: list[dict], side: str) -> dict:
    pos = [r for r in rows if r["expected"]]
    out = {f"recall@{k}": round(sum(1 for r in pos if r[side]["rank"] and r[side]["rank"] <= k) / len(pos), 3) for k in KS}
    out["mrr"] = round(sum(1 / r[side]["rank"] for r in pos if r[side]["rank"]) / len(pos), 3)
    out["selected_evidence_recall"] = round(sum(1 for r in pos if r[side]["selected_hit"]) / len(pos), 3)
    out["positive_queries"] = len(pos)
    out["fallback_invoked"] = sum(1 for r in rows if r[side]["fallback_invoked"])
    out["scope_general_knowledge"] = sum(1 for r in rows if r[side]["scope"] == "general_knowledge")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "data/evaluation/datasets/retrieval_v2.jsonl"))
    ap.add_argument("--label", default="retrieval_pipeline")
    ap.add_argument("--merge-policy", default="interleave", choices=("interleave", "semantic_first"))
    ap.add_argument("--benchmark-drafts", action="store_true",
                    help="use the 300-question benchmark with its DRAFT expected citations as targets (not SME-verified)")
    args = ap.parse_args()
    queries = benchmark_draft_queries() if args.benchmark_drafts else load_retrieval_dataset(args.dataset)
    if args.benchmark_drafts:
        args.dataset = "benchmark REV02 draft citations (NOT SME-verified; retrieval targets only)"
    db = Database.from_env(); db.connect()
    base = configured_rag_config(load_settings())
    pipes = {}
    for side, fallback in (("A", "off"), ("B", "on")):
        cfg = dataclasses.replace(base, semantic_fallback=fallback)
        retriever, scope = build_retriever(db, cfg)
        if fallback == "on":
            retriever.config = dataclasses.replace(retriever.config, merge_policy=args.merge_policy)
        pipes[side] = RagPipeline(retriever, None, cfg, scope_policy=scope)
    rows = []
    for q in queries:
        row = {"id": q.id, "category": q.category, "query": q.query, "expected": list(q.expected)}
        for side, pipe in pipes.items():
            row[side] = score(q, run_one(pipe, q.query))
        a, b = row["A"]["rank"], row["B"]["rank"]
        if not q.expected:
            row["change"] = "negative_control"
        elif a == b:
            row["change"] = "unchanged"
        elif b is not None and (a is None or b < a):
            row["change"] = "recovered" if a is None or a > 10 else "improved_rank"
        else:
            row["change"] = "degraded"
        rows.append(row)
    out = ROOT / "artifacts/retrieval_eval" / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True, exist_ok=False)
    with (out / "per_query.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    changes = {}
    for r in rows:
        changes.setdefault(r["change"], []).append(r["id"])
    res = {"dataset": args.dataset, "merge_policy": args.merge_policy, "queries": len(rows), "A_lexical_only": summary(rows, "A"), "B_semantic_fallback": summary(rows, "B"),
           "changes": {k: {"count": len(v), "ids": v} for k, v in changes.items()},
           "negative_controls_with_a_match_B": [r["id"] for r in rows if not r["expected"] and r["B"]["rank"]]}
    (out / "summary.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
