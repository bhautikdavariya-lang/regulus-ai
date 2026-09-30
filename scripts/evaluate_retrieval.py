"""Run the curated retrieval query set against the live database and report
Recall@K, MRR and latency. Read-only; no model is loaded.

Usage:
    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --top-k 10 --dataset data/evaluation/datasets/retrieval_v1.jsonl
Results: data/evaluation/results/retrieval_<YYYYmmdd>_<HHMMSS>_<run_id>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from regulus.evaluation.results import DEFAULT_RESULTS_DIR, result_filename
from regulus.evaluation.retrieval_eval import (
    DEFAULT_RETRIEVAL_DATASET,
    QueryOutcome,
    RetrievalDatasetError,
    crowding,
    first_hit_rank,
    hits_at,
    load_retrieval_dataset,
    summarise,
)
from regulus.evaluation.runner import new_run_id, sanitize_error
from regulus.retrieval import Database, DatabaseConfigError, LexicalRetriever
from regulus.retrieval.models import METHOD_EXACT_CFR, METHOD_EXACT_DOCKET


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default=None)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--pipeline", default="retrieval-lexical", help="label used in the result file name")
    p.add_argument("--no-fallback", action="store_true", help="disable the Stage 7 OR fallback (reproduces Stage 5)")
    p.add_argument("--primary-min-results", type=int, default=None, help="fallback trigger threshold (default: retriever default)")
    p.add_argument("--retriever", choices=("lexical", "semantic", "hybrid"), default="lexical", help="semantic = Stage 8 experimental retriever; hybrid = Stage 9 experimental fusion (both use the controlled corpus)")
    p.add_argument("--offline", action="store_true", help="semantic/hybrid: fail instead of downloading the embedding model")
    p.add_argument("--semantic-corpus", default=None, help="semantic/hybrid: corpus version name (default: Stage 8 corpus)")
    p.add_argument("--hybrid-strategy", choices=("fallback", "rrf", "authority"), default="authority", help="Stage 9 hybrid fusion strategy")
    p.add_argument("--semantic-floor", type=float, default=None, help="Stage 9: drop semantic candidates with cosine similarity below this")
    p.add_argument("--rrf-k", type=int, default=60, help="Stage 9: RRF constant")
    p.add_argument("--lexical-top-n", type=int, default=10, help="Stage 9: lexical candidates before fusion")
    p.add_argument("--semantic-top-n", type=int, default=10, help="Stage 9: semantic candidates before fusion")
    return p.parse_args()

def build_semantic_retriever(offline: bool = False, semantic_corpus: str | None = None):
    """Stage 8/10 experimental retriever over a controlled corpus (opt-in only)."""
    from regulus.retrieval.semantic.loaders import load_semantic_retriever

    return load_semantic_retriever(offline=offline, semantic_corpus=semantic_corpus)



def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        path = Path(args.dataset) if args.dataset else DEFAULT_RETRIEVAL_DATASET
        queries = load_retrieval_dataset(path)
    except RetrievalDatasetError as exc:
        print(f"DATASET ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        db = Database.from_env()
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2

    run_id = new_run_id()
    started = datetime.now().astimezone()
    outcomes: list[QueryOutcome] = []
    print(f"Dataset: {path.name} ({len(queries)} queries)  top_k={args.top_k}")
    with db:
        status = db.status()
        if args.retriever == "semantic":
            retriever = build_semantic_retriever(args.offline, args.semantic_corpus)
        elif args.retriever == "hybrid":
            from regulus.retrieval.semantic.loaders import load_hybrid_retriever

            rkw = {"enable_or_fallback": not args.no_fallback}
            if args.primary_min_results is not None:
                rkw["primary_min_results"] = args.primary_min_results
            retriever = load_hybrid_retriever(
                LexicalRetriever(db, **rkw), strategy=args.hybrid_strategy, semantic_floor=args.semantic_floor,
                rrf_k=args.rrf_k, lexical_top_n=args.lexical_top_n, semantic_top_n=args.semantic_top_n, offline=args.offline,
                semantic_corpus=args.semantic_corpus,
            )
        else:
            rkw = {"enable_or_fallback": not args.no_fallback}
            if args.primary_min_results is not None:
                rkw["primary_min_results"] = args.primary_min_results
            retriever = LexicalRetriever(db, **rkw)
        print(f"Retriever: {retriever.describe()}")
        for i, q in enumerate(queries, start=1):
            try:
                resp = retriever.run(q.query, top_k=args.top_k)
            except Exception as exc:  # record and continue
                outcomes.append(QueryOutcome(q.id, q.category, q.query, list(q.expected), None, not q.expected, None, [], 0.0, {}, sanitize_error(exc)))
                print(f"[{i:>2}/{len(queries)}] {q.id} FAIL {outcomes[-1].error}")
                continue
            negative = not q.expected
            rank = None if negative else first_hit_rank(q.expected, resp.results)
            exact_present = any(r.retrieval_method in (METHOD_EXACT_CFR, METHOD_EXACT_DOCKET) for r in resp.results)
            if "exact_match_present" in resp.diagnostics:
                exact_present = bool(resp.diagnostics["exact_match_present"])
            # A negative control passes when the lexical existence observation agrees with the
            # dataset: identifiers declared absent must yield no exact result; an identifier
            # declared present (e.g. a real Part with an unknowable future revision) must
            # resolve exactly; controls without an identifier must yield no exact result.
            if negative:
                neg_ok = (exact_present == q.identifier_exists_in_snapshot) if q.identifier_exists_in_snapshot is not None else (not exact_present)
            else:
                neg_ok = None
            top = [
                {"rank": n, "corpus": r.corpus, "citation": r.citation.label, "score": round(r.relevance_score, 3), "method": r.retrieval_method,
                 "methods": list(r.methods), "role": r.metadata.get("corpus_role"), "contextual_only": bool(r.metadata.get("contextual_only"))}
                for n, r in enumerate(resp.results[:10], start=1)
            ]
            outcomes.append(QueryOutcome(
                q.id, q.category, q.query, list(q.expected), rank, negative, neg_ok, top, resp.total_ms, resp.timings_ms, None, dict(resp.diagnostics),
                {} if negative else {str(k): hits_at(q.expected, resp.results, k) for k in (1, 3, 5)},
                {} if negative else crowding(q.expected, resp.results),
                q.identifier_exists_in_snapshot, exact_present,
            ))
            mark = ("neg-ok" if neg_ok else "neg-FAIL") if negative else (f"hit@{rank}" if rank else "miss")
            first = f"{top[0]['citation'][:55]}" if top else "(no results)"
            mode = resp.diagnostics.get("retrieval_mode", "?")
            print(f"[{i:>2}/{len(queries)}] {q.id:<14} {mark:<7} {mode:<9} {resp.total_ms:>7.1f} ms  {first}")

    summary = summarise(outcomes)
    payload = {
        "schema_version": 1,
        "run": {
            "evaluation_run_id": run_id,
            "pipeline": args.pipeline,
            "timestamp_utc": started.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "retriever": retriever.describe(),
            "top_k": args.top_k,
            "dataset": {"name": path.stem, "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "num_queries": len(queries)},
            "database": {k: status[k] for k in ("server_version", "database", "role", "transaction_read_only", "default_transaction_read_only")},
        },
        "summary": summary,
        "results": [asdict(o) for o in outcomes],
    }
    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / result_filename(args.pipeline, run_id, started)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print()
    print("Retrieval evaluation")
    print("====================")
    for k in ("queries", "scored", "negative_controls", "negative_controls_passed", "failed"):
        print(f"{k:<26} {summary[k]}")
    for k in ("recall@1", "recall@3", "recall@5", "recall@10", "mrr", "precision@1", "precision@3", "precision@5"):
        print(f"{k:<26} {summary[k]}")
    print(f"{'existence mismatches':<26} {summary['existence_mismatches']}")
    print(f"{'avg latency (ms)':<26} {summary['avg_total_ms']}")
    print(f"{'max latency (ms)':<26} {summary['max_total_ms']}")
    print(f"{'misses':<26} {summary['misses']}")
    fb = summary["fallback"]
    print(f"{'fallback activations':<26} {fb['activations']}")
    print(f"{'zero primary results':<26} {fb['zero_primary_results']}")
    print(f"{'zero final results':<26} {fb['zero_final_results']}")
    print(f"{'hits via fallback':<26} {fb['hits_via_fallback']}")
    print(f"{'retrieval modes':<26} {fb['modes']}")
    print()
    print("By category")
    for cat, row in summary["by_category"].items():
        neg = f" neg={row['negative_controls_passed']}/{row['negative_controls']}" if row["negative_controls"] else ""
        print(f"  {cat:<22} n={row['scored']:<2} r@1={row['recall@1']} r@3={row['recall@3']} r@5={row['recall@5']} r@10={row['recall@10']} mrr={row['mrr']} p@1={row['precision@1']} p@5={row['precision@5']}{neg}")
    print()
    print(f"Results saved to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
