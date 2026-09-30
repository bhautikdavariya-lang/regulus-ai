"""Minimal lexical RAG CLI: question -> LexicalRetriever -> context -> Qwen -> answer + sources.

Usage:
    python scripts/rag.py "What does 21 CFR 820.10 cover?"
    python scripts/rag.py "recall policy" --top-k 6 --max-new-tokens 160
    python scripts/rag.py "design controls" --corpus ecfr --debug
    python scripts/rag.py "21 CFR 314.999" --json

The database is read-only; no embeddings or vector search are used.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
import time

from regulus.config import ConfigError, load_settings
from regulus.model import ModelLoadError
from regulus.rag import ContextPolicy, RagConfig, RagPipeline, load_qwen_generator
from regulus.retrieval import Database, DatabaseConfigError, LexicalRetriever

CORPUS_LABEL = {"ecfr": "eCFR", "fda_guidance": "FDA Guidance"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question")
    p.add_argument("--top-k", type=int, default=None, help="retrieval top_k (default: RagConfig)")
    p.add_argument("--corpus", choices=("ecfr", "fda_guidance"), default=None)
    p.add_argument("--max-results", type=int, default=None, help="max sources placed in the context")
    p.add_argument("--max-new-tokens", type=int, default=None)
    p.add_argument("--greedy", action="store_true", help="deterministic decoding")
    p.add_argument("--no-context-to-model", action="store_true", help="when nothing is retrieved, still ask the model (default: deterministic refusal)")
    p.add_argument("--retriever", choices=("lexical", "semantic", "hybrid"), default="lexical", help="EXPERIMENTAL: semantic = Stage 8 retriever; hybrid = Stage 9 fusion (controlled corpus only)")
    p.add_argument("--hybrid-strategy", choices=("fallback", "rrf", "authority"), default="authority", help="Stage 9 hybrid fusion strategy")
    p.add_argument("--semantic-floor", type=float, default=None, help="Stage 9: drop semantic candidates with cosine similarity below this")
    p.add_argument("--rrf-k", type=int, default=60, help="Stage 9: RRF constant")
    p.add_argument("--lexical-top-n", type=int, default=10, help="Stage 9: lexical candidates before fusion")
    p.add_argument("--semantic-top-n", type=int, default=10, help="Stage 9: semantic candidates before fusion")
    p.add_argument("--semantic-corpus", default=None, help="Stage 10: semantic corpus version (default: Stage 8 corpus)")
    p.add_argument("--debug", action="store_true", help="show retrieved sources, context and generation details")
    p.add_argument("--json", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    if args.max_new_tokens is not None:
        settings.generation.max_new_tokens = args.max_new_tokens
    if args.greedy:
        settings.generation.do_sample = False

    cfg_kwargs = {}
    if args.top_k is not None:
        cfg_kwargs["top_k"] = args.top_k
    if args.corpus is not None:
        cfg_kwargs["corpus"] = args.corpus
    if args.no_context_to_model:
        cfg_kwargs["no_context_behavior"] = "model"
    if args.max_results is not None:
        cfg_kwargs["context"] = ContextPolicy(max_results=args.max_results)
    config = RagConfig(**cfg_kwargs)

    try:
        db = Database.from_env()
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Loading {settings.model.id} ...", file=sys.stderr, flush=True)
    try:
        t0 = time.perf_counter()
        generator = load_qwen_generator(settings, local_files_only=args.offline)
        load_s = time.perf_counter() - t0
    except ModelLoadError as exc:
        print(f"MODEL LOAD ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        with db:
            if args.retriever == "semantic":
                from regulus.retrieval.semantic.loaders import load_semantic_retriever

                retriever = load_semantic_retriever(offline=args.offline, semantic_corpus=args.semantic_corpus)
                print("EXPERIMENTAL: semantic retriever over the controlled evaluation corpus only.", file=sys.stderr)
            elif args.retriever == "hybrid":
                from regulus.retrieval.semantic.loaders import load_hybrid_retriever

                retriever = load_hybrid_retriever(LexicalRetriever(db), strategy=args.hybrid_strategy, semantic_floor=args.semantic_floor, rrf_k=args.rrf_k, lexical_top_n=args.lexical_top_n, semantic_top_n=args.semantic_top_n, offline=args.offline, semantic_corpus=args.semantic_corpus)
                print("EXPERIMENTAL: hybrid retriever; the semantic leg covers the controlled evaluation corpus only.", file=sys.stderr)
            else:
                retriever = LexicalRetriever(db)
            pipeline = RagPipeline(retriever, generator, config)
            out = pipeline.answer(args.question)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # database down, auth failure ...
        print(f"DATABASE ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = out.to_dict()
        payload["model"] = generator.describe()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print("Question:")
    print(f"  {out.question}")
    print()
    print("Answer:")
    print(textwrap.indent(out.answer, "  "))
    print()
    print("Sources:")
    if not out.citations:
        print("  (none)")
    for c in out.citations:
        idx = ",".join(str(i) for i in c.indices)
        used = " (cited)" if c.cited_in_answer else ""
        print(f"  [{idx}] {c.label}{used}")
        print(f"      {c.url or 'URL not available'}")
    print()
    t = out.timings_ms
    print(f"Timing: retrieval {t['retrieval_ms']:.0f} ms | context {t['context_ms']:.0f} ms | generation {t['generation_ms']:.0f} ms | total {t['total_ms']:.0f} ms | model load {load_s:.1f} s")
    if out.no_context:
        print("Note: no sufficiently relevant sources were retrieved; the answer above is the conservative no-context response.")

    if args.debug:
        print()
        print("Retrieved sources:")
        for i, r in enumerate(out.retrieved_results, start=1):
            print(f"  {i}. [{CORPUS_LABEL[r.corpus]}] {r.citation.label}  score={r.relevance_score:.2f} method={r.retrieval_method}")
        print()
        print(f"Context ({len(out.context.text)} chars, {len(out.context.sources)} sources, {out.context.dropped} dropped):")
        print(textwrap.indent(out.context.text, "  "))
        print()
        print("Generation:")
        desc = generator.describe()
        print(f"  model={desc['model_id']} device={desc['device']} dtype={desc['dtype']} generation={desc['generation']}")
        print(f"  model_called={out.model_called} input_tokens={out.input_tokens} output_tokens={out.output_tokens}")
        print(f"  retrieval={out.metadata['retrieval_counts']} query_type={out.metadata['query_type']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
