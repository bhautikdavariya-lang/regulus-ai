"""Convert SFT dataset v2 into the trainer's TrainingExample JSONL + identity manifest.

    python scripts/sft2_to_trainer.py

Read-only with respect to the dataset: artifacts/sft2/{train,validation}.jsonl are the source of
truth and are never written. The output goes to artifacts/sft2/trainer/, isolated from
data/training/datasets/ so no existing dataset or manifest can be overwritten.

Five gaps are bridged, none of which changes an answer or an evidence block:

* `grounded` and `provenance{group, generator, snapshot_date, extra}` are added; v2 carries those
  facts at the top level, where TrainingExample.from_dict does not look for them.
* `type` becomes "abstention" or "regulatory_qa" (v2 uses one label for all rows).
* `category` is mapped onto the trainer's fixed vocabulary. The true benchmark category is kept in
  provenance.extra.benchmark_category, and every per-category analysis must use that, not the
  mapped value, which exists only to satisfy the schema and the stratifier.
* every context item gets a stable `source_key`; v2 left it unset.
* `source_type: "verified_absence"` has no slot in SOURCE_TYPES. These items are eCFR snapshot
  queries, so they are emitted as "ecfr" with the citation and heading left exactly as written, so
  the rendered SOURCE block still says what the item is.

An empty-text context item is a section with no live rows in the snapshot (verified: every one has
paragraph_count 0). ContextItem rejects empty text, so the body states that fact. It does NOT say
"[Reserved]" - the snapshot does not mark these reserved, it simply holds no paragraphs for them.

A `test` split is required by the config schema, which rejects a zero count, and the trainer
verifies its identity but never reads it. The v2 dataset is a train/validation split and is NOT
re-cut here to manufacture one, so the config points `test` at the validation file itself. That is
deliberately self-evident in configs/sft2_training_v1.yaml rather than hidden behind a duplicated
file that a later reader might mistake for an independent test set. The real held-out set for this
experiment is the 148 benchmark questions absent from this dataset, and those have no authored
answers, so they cannot be TrainingExample rows.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.training.models import ContextItem, TrainingExample, read_jsonl  # noqa: E402

SRC = ROOT / "artifacts" / "sft2"
OUT = SRC / "trainer"
DATASET_VERSION = "sft2-v2.0"

# Nearest member of the trainer's fixed vocabulary. Reporting uses benchmark_category instead.
CATEGORY_MAP = {
    "Direct Lookup": "direct_cfr",
    "Cross-Reference": "multi_context",
    "Application": "relationship",
    "Distinction": "relationship",
    "Scope/Boundary": "partial_context",
    "Temporal/Version": "citation_grounding",
    "Negative Control": "abstention",
    "Abstention": "abstention",
}
NO_LIVE_ROWS = "No live paragraphs for this section in the eCFR snapshot (rows returned: 0)."


def source_key(c: dict) -> str:
    if c.get("source_type") == "verified_absence":
        return "absence:" + (c.get("heading") or c.get("citation") or "query")
    if c.get("source_type") == "fda_guidance":
        return "guidance:" + (c.get("docket_number") or c.get("document_title") or c.get("citation"))
    return "ecfr:" + (c.get("section") or c.get("citation", "").replace("21 CFR ", ""))


def to_example(r: dict) -> TrainingExample:
    ctx = []
    for c in r["context"]:
        st = "ecfr" if c.get("source_type") == "verified_absence" else c.get("source_type", "ecfr")
        ctx.append(ContextItem(
            source_type=st,
            citation=c["citation"],
            text=(c.get("text") or "").strip() or NO_LIVE_ROWS,
            url=c.get("url"),
            section=c.get("section"),
            heading=c.get("heading"),
            document_title=c.get("document_title"),
            docket_number=c.get("docket_number"),
            status=c.get("status"),
            issued_on=c.get("issued_on"),
            source_key=source_key(c),
        ))
    citations = list(r.get("citations") or [])
    extra = dict(r.get("extra") or {})
    extra["benchmark_category"] = r["category"]
    extra["benchmark_question_id"] = r["source_question_id"]
    extra["failure_mode"] = r.get("failure_mode")
    extra["difficulty"] = r.get("difficulty")
    return TrainingExample(
        type="abstention" if (r.get("extra") or {}).get("behaviour") == "abstention" else "regulatory_qa",
        category=CATEGORY_MAP[r["category"]],
        question=r["question"],
        context=ctx,
        answer=r["answer"],
        citations=citations,
        grounded=bool(ctx and citations),
        generator=r.get("generator", "sft/hand_authored/v2"),
        group=r["group"],
        snapshot_date=r.get("snapshot_date"),
        extra=extra,
        split=r["split"],
        id=r["id"],
    )


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    counts, snapshots = {}, set()
    for split in ("train", "validation"):
        rows = [json.loads(l) for l in (SRC / f"{split}.jsonl").read_text().splitlines() if l.strip()]
        examples = [to_example(r) for r in rows]
        for ex in examples:
            if ex.snapshot_date:
                snapshots.add(ex.snapshot_date)
        (OUT / f"{split}.jsonl").write_text(
            "\n".join(json.dumps(ex.to_dict(), ensure_ascii=False) for ex in examples) + "\n")
        counts[split] = len(examples)
    # test := the validation file (see the module docstring); verified, never read
    counts["test"] = counts["validation"]
    split_file = {"train": "train.jsonl", "validation": "validation.jsonl", "test": "validation.jsonl"}

    files, combined = {}, hashlib.sha256()
    for split in ("train", "validation", "test"):
        digest = sha256_file(OUT / split_file[split])
        files[split] = {"path": split_file[split], "sha256": digest, "examples": counts[split]}
        combined.update(digest.encode("ascii"))
    manifest = {
        "dataset_version": DATASET_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_sha256": combined.hexdigest(),
        "files": files,
        "config": {"seed": 42},
        "database": {"snapshot": {"ecfr_snapshot_date": sorted(snapshots)[-1] if snapshots else None}},
        "source": {
            "train": "artifacts/sft2/train.jsonl",
            "validation": "artifacts/sft2/validation.jsonl",
            "train_sha256": sha256_file(SRC / "train.jsonl"),
            "validation_sha256": sha256_file(SRC / "validation.jsonl"),
        },
        "note": ("Converted from SFT v2 by scripts/sft2_to_trainer.py; answers and evidence unchanged. "
                 "The 'test' entry is the validation file: v2 has no test split, the trainer never "
                 "reads one, and the config schema rejects a zero count. It is NOT an independent "
                 "held-out set - that role belongs to the 148 benchmark questions not in this dataset."),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # round-trip: the trainer's own loader must accept every line
    for split in ("train", "validation"):
        loaded = read_jsonl(OUT / f"{split}.jsonl")
        assert len(loaded) == counts[split], split
    print(f"wrote {OUT}")
    print(f"  train {counts['train']}  validation {counts['validation']}  test {counts['test']}")
    print(f"  dataset_sha256 {manifest['dataset_sha256']}")
    print(f"  grounded: {sum(1 for s in ('train','validation') for e in read_jsonl(OUT / f'{s}.jsonl') if e.grounded)}"
          f" of {counts['train'] + counts['validation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
