"""Print a summary of the Stage 11 dataset from its manifest and files.

Usage:
    python scripts/report_training_data.py
    python scripts/report_training_data.py --samples 2      # show 2 examples per category
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

from regulus.training import TrainingConfigError, dataset_paths, load_training_config, manifest_path, read_jsonl
from regulus.training.validate import compute_stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--version", default=None)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--samples", type=int, default=0, help="print N sample examples per category")
    p.add_argument("--width", type=int, default=220, help="truncate printed answers to this many characters")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        config = load_training_config(args.config, version=args.version, output_dir=args.output_dir)
    except TrainingConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    paths = dataset_paths(config)
    examples = []
    for split, path in paths.items():
        if path.is_file():
            examples.extend(read_jsonl(path))
    if not examples:
        print("no dataset files found; run scripts/prepare_training_data.py first", file=sys.stderr)
        return 1
    mp = manifest_path(config)
    manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else {}
    stats = compute_stats(examples)

    print("Training dataset report")
    print("=======================")
    if manifest:
        print(f"version            {manifest.get('dataset_version')}")
        print(f"generated (UTC)    {manifest.get('generated_at_utc')}")
        print(f"seed               {manifest.get('config', {}).get('seed')}")
        print(f"dataset sha256     {manifest.get('dataset_sha256')}")
        snap = manifest.get("database", {}).get("snapshot", {})
        print(f"eCFR snapshot      {snap.get('ecfr_snapshot_date')}  guidance last retrieved {snap.get('guidance_last_retrieved')}")
    print()
    print(f"{'total':<28} {stats['total']}")
    for s, n in stats["by_split"].items():
        print(f"{'  ' + s:<28} {n}")
    print()
    print(f"{'category':<28} {'n':>6} {'share':>7}   train/val/test")
    per_split: dict[str, Counter] = defaultdict(Counter)
    for e in examples:
        per_split[e.category][e.split or "?"] += 1
    for cat, n in stats["by_category"].items():
        ps = per_split[cat]
        print(f"{cat:<28} {n:>6} {n / stats['total']:>7.1%}   {ps.get('train', 0)}/{ps.get('validation', 0)}/{ps.get('test', 0)}")
    print()
    print(f"{'examples by source type':<28} {stats['examples_by_source_type']}")
    print(f"{'eCFR examples':<28} {stats['ecfr_examples']}")
    print(f"{'FDA guidance examples':<28} {stats['guidance_examples']}")
    print(f"{'unique CFR citations':<28} {stats['unique_cfr_citations']}")
    print(f"{'unique CFR sections':<28} {stats['unique_cfr_sections']}")
    print(f"{'unique guidance documents':<28} {stats['unique_guidance_documents']}")
    print(f"{'negative/abstention':<28} {stats['negative_examples']}")
    print(f"{'avg question chars':<28} {stats['avg_question_chars']}")
    print(f"{'avg answer chars':<28} {stats['avg_answer_chars']}")
    print(f"{'avg context chars':<28} {stats['avg_context_chars']}  ({stats['avg_context_items']} items)")
    subtypes = Counter((e.category, str(e.extra.get("subtype", ""))) for e in examples)
    print()
    print("subtypes")
    for (cat, st), n in sorted(subtypes.items()):
        print(f"  {cat:<24} {st:<22} {n}")
    if args.samples > 0:
        print()
        print("samples")
        shown: Counter[str] = Counter()
        for e in examples:
            if shown[e.category] >= args.samples:
                continue
            shown[e.category] += 1
            print(f"\n[{e.category} / {e.extra.get('subtype', '')} / {e.split}] {e.id}")
            print(f"Q: {e.question}")
            print(f"C: {[c.citation for c in e.context]}")
            a = e.answer if len(e.answer) <= args.width else e.answer[: args.width] + " ..."
            print(f"A: {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
