"""Embed a semantic experiment corpus with the pinned local model and save
the NumPy index. Vectors never go to PostgreSQL.

    python scripts/build_semantic_index.py                                    # Stage 8 corpus
    python scripts/build_semantic_index.py --semantic-corpus semantic_expanded_v1
    python scripts/build_semantic_index.py --semantic-corpus semantic_expanded_v1 --check   # verify only
    python scripts/build_semantic_index.py --semantic-corpus semantic_expanded_v1 --reuse-from <copy of the previous generated/>
        # backfill: embed only items that are new or whose text changed; unchanged items keep their vectors
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from regulus.config import load_settings
from regulus.retrieval.semantic import IndexMismatchError, SemanticIndex, TransformersEmbedder, load_corpus, load_manifest, resolve_paths


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--semantic-corpus", default=None, help="corpus version name (default: Stage 8 layout)")
    p.add_argument("--check", action="store_true")
    p.add_argument("--offline", action="store_true", help="fail instead of downloading the model")
    p.add_argument("--max-items", type=int, default=40000, help="safety limit for this machine (8 GB RAM, CPU)")
    p.add_argument("--reuse-from", type=Path, default=None,
                   help="a previous generated/ folder (corpus.jsonl, vectors.npy, index_meta.json) of the same embedding "
                        "configuration; its vectors are reused for unchanged items")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    paths = resolve_paths(args.semantic_corpus)
    manifest = load_manifest(paths.manifest)
    cfg = manifest.embedding
    if args.check:
        try:
            index = SemanticIndex.load_paths(cfg, paths)
        except IndexMismatchError as exc:
            print(f"INDEX MISMATCH: {exc}")
            return 1
        norms = np.linalg.norm(index.vectors, axis=1)
        print(f"index OK: {len(index)} vectors, dim {index.vectors.shape[1]}, finite={bool(np.all(np.isfinite(index.vectors)))}, "
              f"norm range {norms.min():.4f}-{norms.max():.4f}, corpus {index.meta.corpus_sha256[:12]}, model {index.meta.model_id}@{index.meta.revision[:12]}")
        return 0

    items = load_corpus(paths.corpus)
    if len(items) > args.max_items:
        print(f"REFUSED: corpus has {len(items)} items > --max-items {args.max_items}; reduce the manifest scope", file=sys.stderr)
        return 1
    chars = sum(len(i.text) for i in items)
    est_vectors_mb = len(items) * cfg.dimension * 4 / 1e6
    est_minutes = len(items) * 0.113 / 60  # 113 ms/item measured in Stage 8 on this CPU
    print(f"corpus {paths.name}: {len(items)} items, {chars/1e6:.1f} M chars; vectors ≈ {est_vectors_mb:.0f} MB; "
          f"estimated embedding time ≈ {est_minutes:.0f} min at 113 ms/item (batch {cfg.batch_size})", flush=True)

    cache_dir = str(load_settings().model.cache_dir)
    print(f"Loading {cfg.model_id}@{cfg.revision[:12]} ...", flush=True)
    embedder = TransformersEmbedder(cfg, cache_dir=cache_dir, local_files_only=args.offline)
    print(f"loaded in {embedder.load_seconds}s: {embedder.describe()}")

    reuse = None
    if args.reuse_from is not None:
        src = args.reuse_from
        try:
            reuse = SemanticIndex.load(cfg, corpus_path=src / "corpus.jsonl", vectors_path=src / "vectors.npy", meta_path=src / "index_meta.json")
        except IndexMismatchError as exc:
            print(f"REFUSED: cannot reuse {src}: {exc}", file=sys.stderr)
            return 1
        unchanged = {(i.id, i.content_sha256) for i in reuse.items}
        print(f"reusing {src}: {sum((i.id, i.content_sha256) in unchanged for i in items)} of {len(items)} items unchanged", flush=True)

    sample = [i.text for i in items[:16]]
    t0 = time.perf_counter()
    embedder.embed_batch(sample)
    warm = time.perf_counter() - t0
    print(f"batch of {len(sample)} texts: {warm*1000:.0f} ms ({warm*1000/max(1,len(sample)):.1f} ms/text)", flush=True)

    t0 = time.perf_counter()
    index = SemanticIndex.build(items, embedder, reuse=reuse)
    build = time.perf_counter() - t0
    index.save(paths.vectors, paths.index_meta)
    norms = np.linalg.norm(index.vectors, axis=1)
    print(f"embedded {len(items)} items in {build:.1f}s ({build*1000/len(items):.1f} ms/item)")
    print(f"vectors: {paths.vectors} shape={index.vectors.shape} dtype={index.vectors.dtype} finite={bool(np.all(np.isfinite(index.vectors)))} norm {norms.min():.4f}-{norms.max():.4f}")
    print(f"meta:    {paths.index_meta}")
    print(json.dumps(index.meta.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
