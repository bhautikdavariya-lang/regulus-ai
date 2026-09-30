"""Manual retrieval CLI (read-only). No model is loaded.

Usage:
    python scripts/search.py "21 CFR 820.10"
    python scripts/search.py "quality system requirements" --top-k 5
    python scripts/search.py "design controls" --corpus ecfr --part 820
    python scripts/search.py "human factors" --corpus fda_guidance --sector device --status final
    python scripts/search.py "820.3" --method trigram
    python scripts/search.py "recall policy" --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap

from regulus.retrieval import Database, DatabaseConfigError, FilterError, Filters, LexicalRetriever
from regulus.retrieval.models import CORPORA, METHODS

CORPUS_LABEL = {"ecfr": "eCFR", "fda_guidance": "FDA Guidance"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--corpus", choices=CORPORA, default=None, help="restrict to one corpus (default: both)")
    p.add_argument("--method", action="append", choices=METHODS, default=None, help="restrict retrieval methods (repeatable)")
    p.add_argument("--no-fallback", action="store_true", help="disable the Stage 7 OR fallback (Stage 5 behaviour)")
    p.add_argument("--primary-min-results", type=int, default=None, help="fallback trigger threshold")
    p.add_argument("--retriever", choices=("lexical", "semantic", "hybrid"), default="lexical", help="semantic = Stage 8 experimental retriever; hybrid = Stage 9 experimental fusion (controlled corpus only)")
    p.add_argument("--hybrid-strategy", choices=("fallback", "rrf", "authority"), default="authority", help="Stage 9 hybrid fusion strategy")
    p.add_argument("--semantic-floor", type=float, default=None, help="Stage 9: drop semantic candidates with cosine similarity below this")
    p.add_argument("--rrf-k", type=int, default=60, help="Stage 9: RRF constant")
    p.add_argument("--lexical-top-n", type=int, default=10, help="Stage 9: lexical candidates before fusion")
    p.add_argument("--semantic-top-n", type=int, default=10, help="Stage 9: semantic candidates before fusion")
    p.add_argument("--semantic-corpus", default=None, help="Stage 10: semantic corpus version (default: Stage 8 corpus)")
    g = p.add_argument_group("eCFR filters")
    g.add_argument("--part")
    g.add_argument("--section")
    g.add_argument("--subchapter")
    h = p.add_argument_group("FDA guidance filters")
    h.add_argument("--sector")
    h.add_argument("--center")
    h.add_argument("--status")
    h.add_argument("--anchor-part")
    h.add_argument("--anchor-section")
    h.add_argument("--include-unretrievable", action="store_true", help="also search held-out guidance documents")
    p.add_argument("--width", type=int, default=600, help="characters of text to show per result (0 = all)")
    p.add_argument("--json", action="store_true", help="print the full response as JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        filters = Filters(
            part=args.part, section=args.section, subchapter=args.subchapter,
            retrievable=None if args.include_unretrievable else True,
            sector=args.sector, center=args.center, status=args.status,
            anchor_part=args.anchor_part, anchor_section=args.anchor_section,
        )
    except FilterError as exc:
        print(f"FILTER ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        db = Database.from_env()
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        with db:
            rkw = {"enable_or_fallback": not args.no_fallback}
            if args.primary_min_results is not None:
                rkw["primary_min_results"] = args.primary_min_results
            if args.retriever == "semantic":
                from regulus.retrieval.semantic.loaders import load_semantic_retriever

                retriever = load_semantic_retriever(semantic_corpus=args.semantic_corpus)
            elif args.retriever == "hybrid":
                from regulus.retrieval.semantic.loaders import load_hybrid_retriever

                retriever = load_hybrid_retriever(LexicalRetriever(db, **rkw), strategy=args.hybrid_strategy, semantic_floor=args.semantic_floor, rrf_k=args.rrf_k, lexical_top_n=args.lexical_top_n, semantic_top_n=args.semantic_top_n, semantic_corpus=args.semantic_corpus)
            else:
                retriever = LexicalRetriever(db, **rkw)
            response = retriever.run(args.query, corpus=args.corpus, top_k=args.top_k, filters=filters, methods=args.method)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # connection refused, auth failure, timeout ...
        print(f"DATABASE ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"Query: {args.query}")
    print(f"Type:  {response.query_type.value}   results: {len(response.results)}   total: {response.total_ms:.1f} ms")
    print("Per method: " + ", ".join(f"{k}={response.counts[k]} ({response.timings_ms[k]:.1f} ms)" for k in response.counts))
    d = response.diagnostics
    if args.retriever in ("semantic", "hybrid"):
        print(f"EXPERIMENTAL {args.retriever} retriever: semantic leg covers the controlled evaluation corpus only, not the full database.")
    if args.retriever == "hybrid":
        print(f"Hybrid: strategy={d.get('retrieval_strategy')} lexical={d.get('lexical_candidate_count')} semantic={d.get('semantic_candidate_count')} accepted={d.get('semantic_candidates_accepted')} (floor {d.get('semantic_floor')}) dedup={d.get('deduplicated_candidate_count')} final={d.get('final_result_count')} semantic_in_final={d.get('semantic_in_final')} exact_detected={d.get('exact_identifier_detected')} exact_present={d.get('exact_match_present')} identifier_not_found={d.get('identifier_not_found')}")
    line = f"Mode: {d.get('retrieval_mode')}  primary={d.get('primary_result_count')}  fallback_used={d.get('fallback_used')}"
    if d.get("fallback_used"):
        line += f"  fallback_terms={d.get('fallback_terms')}  fallback_candidates={d.get('fallback_candidate_count')}"
    print(line)
    for n in response.notes:
        print(f"Note: {n}")
    print()
    for i, r in enumerate(response.results, start=1):
        print(f"{i}. [{CORPUS_LABEL[r.corpus]}] {r.citation.label}")
        print(f"   Score: {r.relevance_score:.2f}")
        print(f"   Method: {r.retrieval_method}" + (f" (also: {', '.join(m for m in r.methods if m != r.retrieval_method)})" if len(r.methods) > 1 else ""))
        if r.corpus == "ecfr" and r.heading:
            print(f"   Heading: {r.heading}")
        if r.corpus == "fda_guidance":
            print(f"   Chunk: {r.metadata.get('chunk_ordinal')}  Sector: {r.metadata.get('sector')}  Center: {r.metadata.get('center')}")
        print(f"   URL: {r.source_url}")
        text = r.text if args.width == 0 or len(r.text) <= args.width else r.text[: args.width] + " ..."
        print()
        print(textwrap.indent(text, "   "))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
