"""Deterministic de-duplication, benchmark exclusion and capped selection."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from regulus.training.models import TrainingExample
from regulus.training.text import identifiers, jaccard, normalise_question, stable_hash, word_set


def _exact_key(ex: TrainingExample) -> str:
    return stable_hash(normalise_question(ex.question), "|".join(sorted(ex.citations)), normalise_question(ex.answer))


def deduplicate(examples: list[TrainingExample], near_threshold: float) -> tuple[list[TrainingExample], dict[str, int]]:
    """Drop exact duplicates (question + citations + answer, normalised) and,
    within one source group, near duplicates (word-set Jaccard of question +
    answer >= near_threshold). Input order decides which copy survives, so
    callers pass a deterministic order."""
    kept: list[TrainingExample] = []
    seen_ids: set[str] = set()
    seen_exact: set[str] = set()
    per_group: dict[str, list[frozenset[str]]] = defaultdict(list)
    report = {"duplicate_ids": 0, "exact_duplicates": 0, "near_duplicates": 0}
    for ex in examples:
        if ex.id in seen_ids:
            report["duplicate_ids"] += 1
            continue
        k = _exact_key(ex)
        if k in seen_exact:
            report["exact_duplicates"] += 1
            continue
        words = word_set(ex.question + " " + ex.answer)
        if any(jaccard(words, other) >= near_threshold for other in per_group[ex.group]):
            report["near_duplicates"] += 1
            continue
        seen_ids.add(ex.id)
        seen_exact.add(k)
        per_group[ex.group].append(words)
        kept.append(ex)
    return kept, report


def load_benchmark_questions(paths: Iterable[Path]) -> list[str]:
    """Questions/queries of the evaluation datasets (both schemas)."""
    out: list[str] = []
    for path in paths:
        if not Path(path).is_file():
            continue
        for raw in Path(path).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            record = json.loads(line)
            text = record.get("question") or record.get("query")
            if text:
                out.append(str(text))
    return out


def exclude_benchmark(examples: list[TrainingExample], questions: list[str], threshold: float, same_identifier_threshold: float | None = None) -> tuple[list[TrainingExample], list[str]]:
    """Remove examples whose question is identical or nearly identical to an
    evaluation question. Returns (kept, excluded ids).

    Two rules, both on normalised word sets:
      * questions naming the same identifiers (section, part, docket tokens) are
        excluded at the lower `same_identifier_threshold` ("What is 21 CFR Part
        11 about?" vs the benchmark's "What does 21 CFR Part 11 cover?");
      * questions naming different identifiers are never treated as look-alikes
        ("What does 21 CFR Part 1 cover?" is not "...Part 11...");
      * questions without identifiers use the plain `threshold`.
    """
    same_thr = threshold if same_identifier_threshold is None else same_identifier_threshold
    norms = {normalise_question(q) for q in questions}
    bench = [(word_set(q), identifiers(q)) for q in questions]
    kept, excluded = [], []
    for ex in examples:
        nq = normalise_question(ex.question)
        ws, ids = word_set(ex.question), identifiers(ex.question)
        if nq in norms:
            excluded.append(ex.id)
            continue
        similar = False
        for s, bids in bench:
            if ids or bids:
                if ids == bids and jaccard(ws, s) >= same_thr:
                    similar = True
                    break
            elif jaccard(ws, s) >= threshold:
                similar = True
                break
        (excluded if similar else kept).append(ex.id if similar else ex)
    return kept, excluded


def benchmark_groups(paths: Iterable[Path]) -> set[str]:
    """Split groups (section numbers, "part N") named by any benchmark question.

    Group-level separation is stronger than question-level: if an evaluation
    question is about 21 CFR 820.10, no training example built from 820.10 may
    exist at all, so the evaluation cannot be measuring memorised text.
    """
    from regulus.retrieval.references import parse_cfr_references

    groups: set[str] = set()
    for question in load_benchmark_questions(paths):
        for ref in parse_cfr_references(question):
            groups.add(ref.section if ref.section is not None else f"part {ref.part}")
    return groups


def exclude_groups(examples: list[TrainingExample], groups: set[str]) -> tuple[list[TrainingExample], list[str]]:
    """Drop every example whose split group is named by a benchmark question."""
    kept: list[TrainingExample] = []
    excluded: list[str] = []
    for ex in examples:
        if ex.group in groups:
            excluded.append(ex.id)
        else:
            kept.append(ex)
    return kept, excluded


def hash_order(examples: Iterable[TrainingExample], seed: int) -> list[TrainingExample]:
    """Deterministic pseudo-random order independent of generation order."""
    return sorted(examples, key=lambda ex: stable_hash(str(seed), ex.id))


def select_balanced(examples: list[TrainingExample], cap: int, seed: int) -> list[TrainingExample]:
    """Take up to `cap` examples, round-robin across subtypes (extra['subtype'])
    in hash order so no subtype or source region dominates."""
    if cap <= 0:
        return []
    buckets: dict[str, list[TrainingExample]] = defaultdict(list)
    for ex in hash_order(examples, seed):
        buckets[str(ex.extra.get("subtype", ""))].append(ex)
    order = sorted(buckets)
    chosen: list[TrainingExample] = []
    i = 0
    while len(chosen) < cap and any(buckets[k] for k in order):
        key = order[i % len(order)]
        if buckets[key]:
            chosen.append(buckets[key].pop(0))
        i += 1
    return chosen
