"""Download the cross-encoder rerankers (regulus.retrieval.rerank.RERANKERS) into models/ at their pinned revisions.

    .venv/bin/python scripts/fetch_rerankers.py [bge-m3 ...]     (default: bge-m3, the production reranker)

Weights are never committed (models/ is git-ignored). The pipeline loads them with local_files_only, so a machine
without this download simply runs without the reranker veto (the picker's choice stands)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.retrieval.rerank import MODEL_CACHE, RERANKERS  # noqa: E402


def main() -> None:
    from huggingface_hub import snapshot_download

    for name in sys.argv[1:] or ["bge-m3"]:
        spec = RERANKERS[name]
        path = snapshot_download(spec["repo"], revision=spec["revision"], cache_dir=str(MODEL_CACHE),
                                 allow_patterns=["*.json", "*.txt", "*.model", "model.safetensors", "merges.txt", "vocab*"])
        print(name, spec["repo"], spec["revision"], path, flush=True)


if __name__ == "__main__":
    main()
