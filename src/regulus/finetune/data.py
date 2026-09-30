"""Dataset identity verification, chat rendering and tokenisation for SFT.

The Stage 11 files are used exactly as produced: `verify_dataset` compares
every file against manifest_v1.json (per-file SHA-256, combined dataset
hash, split counts) and refuses to continue on any mismatch. Rendering uses
`regulus.training.to_messages` (the Stage 6 RAG prompt layout) and the
tokenizer's own chat template; labels cover the assistant turn only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset

from regulus.finetune.config import DatasetConfig
from regulus.training.dedup import hash_order
from regulus.training.models import TrainingExample, read_jsonl, to_messages

IGNORE_INDEX = -100


class DatasetIdentityError(RuntimeError):
    """The files on disk are not the Stage 11 artifact the config expects."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_dataset(cfg: DatasetConfig) -> dict[str, Any]:
    """Stop rather than train on the wrong data. Returns the verified identity."""
    if not cfg.manifest.is_file():
        raise DatasetIdentityError(f"manifest not found: {cfg.manifest.name}")
    manifest = json.loads(cfg.manifest.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    paths = {"train": cfg.train, "validation": cfg.validation, "test": cfg.test}
    identity: dict[str, Any] = {"files": {}, "manifest": cfg.manifest.name}
    combined = hashlib.sha256()
    for split, path in paths.items():
        if not path.is_file():
            raise DatasetIdentityError(f"{split} file not found: {path.name}")
        digest = sha256_file(path)
        recorded = files.get(split, {})
        if recorded.get("sha256") != digest:
            raise DatasetIdentityError(f"{path.name}: sha256 does not match manifest_v1.json")
        count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        if recorded.get("examples") != count or cfg.expected_counts.get(split) != count:
            raise DatasetIdentityError(f"{path.name}: {count} examples, expected {cfg.expected_counts.get(split)} (manifest {recorded.get('examples')})")
        combined.update(digest.encode("ascii"))
        identity["files"][split] = {"path": path.name, "sha256": digest, "examples": count}
    dataset_hash = combined.hexdigest()
    if dataset_hash != manifest.get("dataset_sha256") or dataset_hash != cfg.expected_hash:
        raise DatasetIdentityError("combined dataset hash does not match the Stage 11 manifest / expected_hash")
    identity["dataset_sha256"] = dataset_hash
    identity["dataset_version"] = manifest.get("dataset_version")
    identity["generated_at_utc"] = manifest.get("generated_at_utc")
    identity["seed"] = manifest.get("config", {}).get("seed")
    identity["database_snapshot"] = manifest.get("database", {}).get("snapshot", {}).get("ecfr_snapshot_date")
    return identity


def protected_hashes(paths: tuple[Path, ...]) -> dict[str, str]:
    return {p.name: sha256_file(p) for p in paths if p.is_file()}


# ------------------------------------------------------------- rendering


def example_messages(example: TrainingExample, prompt_format: str = "legacy") -> list[dict[str, str]]:
    """system / user / assistant turns in the requested prompt format.

    "grounded" is the Stage 4 contract the pipeline uses at inference; training
    on it means the model never meets a prompt shape it was not trained on.
    """
    if prompt_format == "grounded":
        from regulus.stage6.prompting import to_grounded_messages

        return to_grounded_messages(example)
    return to_messages(example)


def render_example(example: TrainingExample, tokenizer, prompt_format: str = "legacy") -> tuple[list[int], list[int]]:
    """(input_ids, labels): prompt tokens are masked with IGNORE_INDEX, the
    assistant turn (answer + end-of-turn) is learned."""
    messages = example_messages(example, prompt_format)
    full_text = tokenizer.apply_chat_template(messages, tokenize=False, enable_thinking=False)
    prompt_text = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    if not full_text.startswith(prompt_text):
        raise ValueError("chat template: generation prompt is not a prefix of the full conversation")
    full_ids = tokenizer(full_text, add_special_tokens=False)["input_ids"]
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    if full_ids[: len(prompt_ids)] != prompt_ids:
        # tokenisation merged across the boundary; fall back to re-tokenising the answer part
        answer_ids = tokenizer(full_text[len(prompt_text):], add_special_tokens=False)["input_ids"]
        full_ids = prompt_ids + answer_ids
    labels = [IGNORE_INDEX] * len(prompt_ids) + full_ids[len(prompt_ids):]
    return full_ids, labels


@dataclass
class TokenizedDataset(Dataset):
    rows: list[dict[str, list[int]]]
    ids: list[str]
    stats: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int) -> dict[str, torch.Tensor]:
        r = self.rows[i]
        return {"input_ids": torch.tensor(r["input_ids"]), "attention_mask": torch.ones(len(r["input_ids"]), dtype=torch.long), "labels": torch.tensor(r["labels"])}


def tokenize_examples(examples: list[TrainingExample], tokenizer, max_seq_length: int, policy: str = "skip", prompt_format: str = "legacy") -> TokenizedDataset:
    rows, ids = [], []
    lengths: list[int] = []
    skipped = truncated = 0
    for ex in examples:
        input_ids, labels = render_example(ex, tokenizer, prompt_format)
        lengths.append(len(input_ids))
        if len(input_ids) > max_seq_length:
            if policy == "skip":
                skipped += 1
                continue
            input_ids, labels = input_ids[:max_seq_length], labels[:max_seq_length]
            truncated += 1
        if all(l == IGNORE_INDEX for l in labels):
            skipped += 1  # nothing to learn from
            continue
        rows.append({"input_ids": input_ids, "labels": labels})
        ids.append(ex.id)
    lengths.sort()
    stats = {
        "examples_in": len(examples),
        "examples_used": len(rows),
        "skipped_over_length": skipped,
        "truncated": truncated,
        "max_seq_length": max_seq_length,
        "over_length_policy": policy,
        "max_token_length_observed": lengths[-1] if lengths else 0,
        "median_token_length": lengths[len(lengths) // 2] if lengths else 0,
        "p95_token_length": lengths[int(0.95 * (len(lengths) - 1))] if lengths else 0,
        "answer_tokens_mean": round(sum(sum(1 for l in r["labels"] if l != IGNORE_INDEX) for r in rows) / len(rows), 1) if rows else 0,
    }
    return TokenizedDataset(rows, ids, stats)


def collate(batch: list[dict[str, torch.Tensor]], pad_token_id: int) -> dict[str, torch.Tensor]:
    """Right-pad to the longest sequence; padded labels are ignored."""
    width = max(b["input_ids"].shape[0] for b in batch)
    n = len(batch)
    input_ids = torch.full((n, width), pad_token_id, dtype=torch.long)
    attention = torch.zeros((n, width), dtype=torch.long)
    labels = torch.full((n, width), IGNORE_INDEX, dtype=torch.long)
    for i, b in enumerate(batch):
        L = b["input_ids"].shape[0]
        input_ids[i, :L] = b["input_ids"]
        attention[i, :L] = 1
        labels[i, :L] = b["labels"]
    return {"input_ids": input_ids, "attention_mask": attention, "labels": labels}


def load_split(path: Path) -> list[TrainingExample]:
    return read_jsonl(path)


def eval_subset(examples: list[TrainingExample], size: int, seed: int, stratified: bool = False) -> list[TrainingExample]:
    """Deterministic validation subset used for checkpoint selection.

    `stratified` allocates places to categories in proportion to their share of
    the split (largest-remainder, so the total is exact) and fills each from the
    same hash order. Selection never looks at model performance.
    """
    if not stratified:
        return hash_order(examples, seed)[:size]
    if size >= len(examples):
        return hash_order(examples, seed)
    ordered = hash_order(examples, seed)
    by_cat: dict[str, list[TrainingExample]] = {}
    for ex in ordered:
        by_cat.setdefault(ex.category, []).append(ex)
    total = len(ordered)
    exact = {c: size * len(rows) / total for c, rows in by_cat.items()}
    quota = {c: min(int(v), len(by_cat[c])) for c, v in exact.items()}
    # largest remainder, ties broken by category name so the result is stable
    remaining = size - sum(quota.values())
    order = sorted(by_cat, key=lambda c: (-(exact[c] - int(exact[c])), c))
    i = 0
    while remaining > 0 and i < len(order) * 10:
        c = order[i % len(order)]
        if quota[c] < len(by_cat[c]):
            quota[c] += 1
            remaining -= 1
        i += 1
    chosen = [ex for c in sorted(by_cat) for ex in by_cat[c][: quota[c]]]
    return hash_order(chosen, seed)


def subset_distribution(examples: list[TrainingExample]) -> dict[str, int]:
    out: dict[str, int] = {}
    for ex in examples:
        out[ex.category] = out.get(ex.category, 0) + 1
    return dict(sorted(out.items()))
