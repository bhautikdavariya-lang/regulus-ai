"""End-to-end training-data preparation.

    read-only database -> source selection -> generators (+ negatives)
    -> de-duplication -> benchmark exclusion -> per-category caps
    -> group-level split -> JSONL files + manifest

Deterministic for a fixed config and database snapshot: generation order is
sorted, selection uses hash order, ids are content hashes and the split is a
hash of the source group. The only nondeterministic value is the generation
timestamp, which lives in the manifest and not in the dataset files (the
dataset hash therefore reproduces).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from regulus.retrieval.db import Database
from regulus.training.config import CATEGORIES, TrainingConfig
from regulus.training.dedup import benchmark_groups, deduplicate, exclude_benchmark, exclude_groups, hash_order, load_benchmark_questions, select_balanced
from regulus.training.generators import GENERATORS
from regulus.training.answer_examples import STAGE14_GENERATORS
from regulus.training.grounding_examples import STAGE13_GENERATORS
from regulus.stage6.generators import STAGE6_GENERATORS
from regulus.training.models import SPLITS, TrainingExample, write_jsonl
from regulus.training.negatives import gen_abstention
from regulus.training.sources import Corpus, assert_read_only, load_corpus, source_counts
from regulus.training.splits import assign_splits, group_overlap
from regulus.training.validate import compute_stats

MANIFEST_SCHEMA_VERSION = 1


class PipelineError(RuntimeError):
    pass


@dataclass
class PrepareResult:
    manifest: dict[str, Any]
    paths: dict[str, Path]
    examples: list[TrainingExample]


def dataset_paths(config: TrainingConfig) -> dict[str, Path]:
    v = config.version
    return {
        "train": config.output_dir / f"training_{v}.jsonl",
        "validation": config.output_dir / f"validation_{v}.jsonl",
        "test": config.output_dir / f"test_{v}.jsonl",
    }


def manifest_path(config: TrainingConfig) -> Path:
    return config.output_dir / f"manifest_{config.version}.json"


def generate_candidates(corpus: Corpus, config: TrainingConfig) -> dict[str, list[TrainingExample]]:
    out: dict[str, list[TrainingExample]] = {}
    for cat in CATEGORIES:
        if config.category_shares.get(cat, 0.0) <= 0:
            out[cat] = []
            continue
        if cat == "abstention":
            fn = gen_abstention
        elif cat in STAGE13_GENERATORS:
            fn = STAGE13_GENERATORS[cat]
        elif cat in STAGE14_GENERATORS:
            fn = STAGE14_GENERATORS[cat]
        elif cat in STAGE6_GENERATORS:
            fn = STAGE6_GENERATORS[cat]
        else:
            fn = GENERATORS[cat]
        out[cat] = fn(corpus, config)
    return out


def build_examples(corpus: Corpus, config: TrainingConfig) -> tuple[list[TrainingExample], dict[str, Any]]:
    """Generators -> dedup -> benchmark exclusion -> caps -> splits. Pure; no I/O."""
    candidates = generate_candidates(corpus, config)
    benchmark_questions = load_benchmark_questions(config.benchmarks)
    bench_groups = benchmark_groups(config.benchmarks) if config.quality.exclude_benchmark_groups else set()
    targets = config.category_targets()
    selected: list[TrainingExample] = []
    per_category: dict[str, dict[str, int]] = {}
    for cat in CATEGORIES:
        cands = hash_order(candidates[cat], config.seed)
        deduped, dd = deduplicate(cands, config.quality.near_duplicate_jaccard)
        kept, excluded = exclude_benchmark(deduped, benchmark_questions, config.quality.benchmark_jaccard, config.quality.benchmark_jaccard_same_identifiers)
        kept, group_excluded = exclude_groups(kept, bench_groups) if bench_groups else (kept, [])
        chosen = select_balanced(kept, targets[cat], config.seed)
        per_category[cat] = {
            "candidates": len(cands),
            "after_dedup": len(deduped),
            "benchmark_excluded": len(excluded),
            "benchmark_group_excluded": len(group_excluded),
            "target": targets[cat],
            "selected": len(chosen),
            **dd,
        }
        selected.extend(chosen)
    # a second global pass catches identical questions produced by two categories
    selected, global_dd = deduplicate(hash_order(selected, config.seed), config.quality.near_duplicate_jaccard)
    counts = assign_splits(selected, config)
    overlap = group_overlap(selected)
    if overlap:
        raise PipelineError(f"split assignment leaked groups across splits: {overlap[:3]}")
    selected.sort(key=lambda e: (e.split or "", e.category, e.id))
    info = {"per_category": per_category, "global_dedup": global_dd, "splits": counts,
            "benchmark_questions": len(benchmark_questions), "benchmark_groups": sorted(bench_groups)}
    return selected, info


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def prepare_dataset(config: TrainingConfig, db: Database) -> PrepareResult:
    db_status = assert_read_only(db)
    corpus = load_corpus(db, config)
    examples, info = build_examples(corpus, config)
    if not examples:
        raise PipelineError("no examples were generated")
    paths = dataset_paths(config)
    files: dict[str, Any] = {}
    combined = hashlib.sha256()
    for split in SPLITS:
        rows = [e for e in examples if e.split == split]
        n = write_jsonl(rows, paths[split])
        digest = _sha256_file(paths[split])
        combined.update(digest.encode("ascii"))
        files[split] = {"path": paths[split].name, "examples": n, "sha256": digest}
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_version": config.version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config.to_dict(),
        "database": {**db_status, "snapshot": corpus.snapshot},
        "source_counts": source_counts(corpus),
        "generation": info,
        "files": files,
        "dataset_sha256": combined.hexdigest(),
        "stats": compute_stats(examples),
    }
    mp = manifest_path(config)
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return PrepareResult(manifest, {**paths, "manifest": mp}, examples)
