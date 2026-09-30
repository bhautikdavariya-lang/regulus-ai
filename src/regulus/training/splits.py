"""Deterministic, group-level train / validation / test assignment.

Every example carries a `group` (the eCFR section, the guidance document, or
the negative identifier it was built from). A group's split is decided by
sha256(seed, group), so all examples of one section or document land in the
same split regardless of how many there are or in which order they were
generated. Re-running with the same seed reproduces the assignment exactly;
adding new groups never moves existing ones.
"""

from __future__ import annotations

from collections import Counter

from regulus.training.config import TrainingConfig
from regulus.training.models import SPLITS, TrainingExample
from regulus.training.text import stable_hash


def split_for_group(group: str, config: TrainingConfig) -> str:
    h = int(stable_hash(str(config.seed), group)[:12], 16) / float(16**12)
    if h < config.train_ratio:
        return "train"
    if h < config.train_ratio + config.validation_ratio:
        return "validation"
    return "test"


def assign_splits(examples: list[TrainingExample], config: TrainingConfig) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for ex in examples:
        ex.split = split_for_group(ex.group, config)
        counts[ex.split] += 1
    return {s: counts.get(s, 0) for s in SPLITS}


def group_overlap(examples: list[TrainingExample]) -> list[str]:
    """Groups that appear in more than one split (must be empty)."""
    seen: dict[str, set[str]] = {}
    for ex in examples:
        seen.setdefault(ex.group, set()).add(ex.split or "")
    return sorted(g for g, s in seen.items() if len(s) > 1)
