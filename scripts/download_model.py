"""Download the configured model into the configured cache directory.

Uses huggingface_hub.snapshot_download, so re-running is a no-op when the
files are already present (no duplicate copies).

Usage:
    python scripts/download_model.py
    REGULUS_MODEL_ID=Qwen/Qwen3-1.7B python scripts/download_model.py
"""

from __future__ import annotations

import sys

from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from regulus.config import load_settings

# Only fetch what Transformers needs; skips duplicate .bin / GGUF variants.
ALLOW_PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja", "LICENSE*"]


def main() -> int:
    settings = load_settings()
    cfg = settings.model
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {cfg.id} -> {cfg.cache_dir}")
    try:
        path = snapshot_download(cfg.id, cache_dir=str(cfg.cache_dir), allow_patterns=ALLOW_PATTERNS)
    except RepositoryNotFoundError:
        print(f"ERROR: model '{cfg.id}' not found on the Hugging Face Hub.", file=sys.stderr)
        return 1
    except GatedRepoError:
        print(f"ERROR: '{cfg.id}' is gated; accept its license and set HF_TOKEN.", file=sys.stderr)
        return 1
    except HfHubHTTPError as exc:
        print(f"ERROR: Hub request failed: {exc}", file=sys.stderr)
        return 1
    print(f"Snapshot ready at: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
