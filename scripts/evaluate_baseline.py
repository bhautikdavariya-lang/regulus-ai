"""Run the benchmark dataset through the configured Qwen model and save results.

The model is loaded once and every question is asked as a single-turn chat
message with no system prompt, no retrieved context and no history.

Usage:
    python scripts/evaluate_baseline.py                      # raw model (pipeline "baseline")
    python scripts/evaluate_baseline.py --pipeline rag       # lexical retrieval + model (Stage 6)
    python scripts/evaluate_baseline.py --max-new-tokens 100
    python scripts/evaluate_baseline.py --limit 3            # quick check
    python scripts/evaluate_baseline.py --ids baseline-023 baseline-024
    python scripts/evaluate_baseline.py --sample --seed 7    # non-deterministic

With --pipeline rag each question first goes through the read-only
LexicalRetriever (REGULUS_DATABASE_URL required); retrieved sources, context
and citations are stored per question in `diagnostics`.

Decoding is greedy by default so two runs on the same machine and software
produce identical answers. Results are written to
data/evaluation/results/<pipeline>_<YYYYmmdd>_<HHMMSS>_<run_id>.json
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import torch
import transformers

from regulus.config import ConfigError, load_settings
from regulus.evaluation import (
    DatasetError,
    build_run_metadata,
    load_dataset,
    result_filename,
    run_evaluation,
    save_run,
)
from regulus.evaluation.report import render_summary
from regulus.evaluation.results import DEFAULT_RESULTS_DIR, QuestionResult
from regulus.evaluation.runner import new_run_id
from regulus.inference import generate
from regulus.model import ModelLoadError, environment_info, load_model, load_tokenizer

DEFAULT_SEED = 42


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default=None, help="JSONL dataset (default: data/evaluation/datasets/baseline_v1.jsonl)")
    p.add_argument("--output-dir", default=None, help="where to write results (default: data/evaluation/results)")
    p.add_argument("--pipeline", choices=("baseline", "rag"), default="baseline", help="baseline = raw model; rag = lexical retrieval + model")
    p.add_argument("--rag-top-k", type=int, default=None, help="retrieval top_k for --pipeline rag (default: RagConfig)")
    p.add_argument("--rag-corpus", choices=("ecfr", "fda_guidance"), default=None, help="restrict retrieval corpus for --pipeline rag")
    p.add_argument("--no-fallback", action="store_true", help="--pipeline rag: disable the Stage 7 OR fallback (Stage 6 retriever)")
    p.add_argument("--run-label", default=None, help="file-name prefix and 'pipeline' label (default: --pipeline value)")
    p.add_argument("--retriever", choices=("lexical", "hybrid"), default="lexical", help="--pipeline rag: EXPERIMENTAL hybrid = Stage 9 fusion over the controlled semantic corpus")
    p.add_argument("--hybrid-strategy", choices=("fallback", "rrf", "authority"), default="authority", help="Stage 9 hybrid fusion strategy")
    p.add_argument("--semantic-floor", type=float, default=None, help="Stage 9: drop semantic candidates with cosine similarity below this")
    p.add_argument("--rrf-k", type=int, default=60, help="Stage 9: RRF constant")
    p.add_argument("--lexical-top-n", type=int, default=10, help="Stage 9: lexical candidates before fusion")
    p.add_argument("--semantic-top-n", type=int, default=10, help="Stage 9: semantic candidates before fusion")
    p.add_argument("--semantic-corpus", default=None, help="Stage 10: semantic corpus version (default: Stage 8 corpus)")
    p.add_argument("--adapter", default=None, help="Stage 12: directory of a saved LoRA adapter to merge into the base model before evaluating")
    p.add_argument("--grounding", action="store_true", help="Stage 13: enable the deterministic identifier-grounding gate (--pipeline rag only)")
    p.add_argument("--no-mismatch-refusal", action="store_true", help="Stage 13: with --grounding, verify identifier existence but do not refuse on context mismatch")
    p.add_argument("--config", default=None, help="YAML model config (default: configs/model.yaml)")
    p.add_argument("--max-new-tokens", type=int, default=None, help="override generation.max_new_tokens")
    p.add_argument("--sample", action="store_true", help="use sampling from configs/model.yaml instead of greedy")
    p.add_argument("--temperature", type=float, default=None, help="sampling temperature (with --sample)")
    p.add_argument("--top-p", type=float, default=None, help="nucleus top-p (with --sample)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"torch random seed (default {DEFAULT_SEED})")
    p.add_argument("--thinking", action="store_true", help="enable Qwen3 thinking mode (slow on CPU)")
    p.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    p.add_argument("--ids", nargs="+", default=None, help="only run these question ids")
    p.add_argument("--offline", action="store_true", help="fail instead of downloading if not cached")
    p.add_argument("-v", "--verbose", action="store_true", help="show library logging")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    gen = settings.generation
    gen.do_sample = bool(args.sample)  # greedy unless explicitly asked
    if args.max_new_tokens is not None:
        gen.max_new_tokens = args.max_new_tokens
    if args.temperature is not None:
        gen.temperature = args.temperature
    if args.top_p is not None:
        gen.top_p = args.top_p
    if args.thinking:
        gen.enable_thinking = True

    try:
        dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print(f"DATASET ERROR: {exc}", file=sys.stderr)
        return 2
    examples = list(dataset.examples)
    if args.ids:
        wanted = set(args.ids)
        examples = [e for e in examples if e.id in wanted]
        missing = wanted - {e.id for e in examples}
        if missing:
            print(f"DATASET ERROR: unknown id(s): {sorted(missing)}", file=sys.stderr)
            return 2
    if args.limit is not None:
        examples = examples[: max(args.limit, 0)]
    if not examples:
        print("DATASET ERROR: no questions selected", file=sys.stderr)
        return 2

    print(f"Dataset: {dataset.name} ({len(dataset)} examples, running {len(examples)})")
    print(f"Loading {settings.model.id} ...", flush=True)
    try:
        t0 = time.perf_counter()
        tokenizer = load_tokenizer(settings.model, local_files_only=args.offline)
        model = load_model(settings.model, local_files_only=args.offline)
    except ModelLoadError as exc:
        print(f"MODEL LOAD ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Loaded in {time.perf_counter() - t0:.1f}s on {model.device} ({model.dtype})")
    adapter_info = None
    if args.adapter:
        from regulus.finetune import AdapterError, attach_saved_adapter

        try:
            model, adapter_info = attach_saved_adapter(model, Path(args.adapter), merge=True)
        except AdapterError as exc:
            print(f"ADAPTER ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"Adapter merged: {adapter_info['adapter_name']} (r={adapter_info['r']}, alpha={adapter_info['lora_alpha']}, dataset {str(adapter_info.get('dataset_hash'))[:16]})")
    print(f"Decoding: {'sampling' if gen.do_sample else 'greedy'}, max_new_tokens={gen.max_new_tokens}, seed={args.seed}")
    print()

    extra = {"adapter": adapter_info} if adapter_info else None
    db = None
    if args.pipeline == "rag":
        from regulus.rag import QwenGenerator, RagConfig, RagPipeline
        from regulus.retrieval import Database, DatabaseConfigError, LexicalRetriever

        try:
            db = Database.from_env()
            db.connect()
        except DatabaseConfigError as exc:
            print(f"CONFIG ERROR: {exc}", file=sys.stderr)
            return 2
        rag_kwargs = {}
        if args.rag_top_k is not None:
            rag_kwargs["top_k"] = args.rag_top_k
        if args.rag_corpus is not None:
            rag_kwargs["corpus"] = args.rag_corpus
        retriever = LexicalRetriever(db, enable_or_fallback=not args.no_fallback)
        if args.retriever == "hybrid":
            from regulus.retrieval.semantic.loaders import load_hybrid_retriever

            retriever = load_hybrid_retriever(retriever, strategy=args.hybrid_strategy, semantic_floor=args.semantic_floor, rrf_k=args.rrf_k, lexical_top_n=args.lexical_top_n, semantic_top_n=args.semantic_top_n, offline=args.offline, semantic_corpus=args.semantic_corpus)
        grounding = None
        if args.grounding:
            from regulus.grounding import DatabaseIdentifierIndex, GroundingConfig, GroundingGate

            snapshot = db.query("SELECT max(snapshot_date)::text AS d FROM cfr_records WHERE removed_on IS NULL")[0]["d"]
            grounding = GroundingGate(
                DatabaseIdentifierIndex(db),
                GroundingConfig(enabled=True, refuse_context_mismatch=not args.no_mismatch_refusal),
                snapshot_date=snapshot,
            )
        pipeline = RagPipeline(retriever, QwenGenerator(model, tokenizer, gen, settings.model.id), RagConfig(**rag_kwargs), grounding=grounding)
        extra = {**(extra or {}), **pipeline.describe()}
        if grounding is not None:
            print(f"Grounding gate: {grounding.describe()['grounding']}")
        status = db.status()
        extra["database"] = {k: status[k] for k in ("server_version", "database", "transaction_read_only", "default_transaction_read_only")}
        print(f"RAG: {extra['rag']}")
        print(f"Retriever: {extra['retriever']}")

        def answer(question: str):
            return pipeline.answer_fn(question)

    else:

        def answer(question: str):
            return generate(model, tokenizer, question, gen)

    torch.manual_seed(args.seed)
    env = environment_info()
    env["transformers"] = transformers.__version__
    run_id = new_run_id()
    started_at = datetime.now().astimezone()
    label = args.run_label or args.pipeline
    metadata = build_run_metadata(
        run_id=run_id,
        pipeline=label,
        started_at=started_at,
        settings=settings,
        gen=gen,
        dataset=dataset,
        device=str(model.device),
        dtype=str(model.dtype).replace("torch.", ""),
        model_revision=getattr(model.config, "_commit_hash", None),
        environment=env,
        seed=args.seed,
        num_questions=len(examples),
        extra=extra,
    )

    def progress(index: int, total: int, r: QuestionResult) -> None:
        if r.status == "completed":
            preview = (r.model_answer or "").replace("\n", " ")[:70]
            print(f"[{index:>2}/{total}] {r.question_id} ok   {r.generation_seconds:>6.1f}s  {r.output_tokens:>3} tok  {preview}")
        else:
            print(f"[{index:>2}/{total}] {r.question_id} FAIL {r.error}")
        sys.stdout.flush()

    try:
        run = run_evaluation(examples, answer, metadata, on_progress=progress)
    finally:
        if db is not None:
            db.close()

    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_RESULTS_DIR
    out_path = save_run(run, out_dir / result_filename(label, run_id, started_at))

    print()
    print(render_summary(run))
    print()
    print(f"Results saved to: {out_path}")
    return 0 if run.summary["failed"] < run.summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
