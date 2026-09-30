"""Print Python / PyTorch / CUDA environment information and the resolved config.

Usage:
    python scripts/check_env.py
"""

from __future__ import annotations

import sys

from regulus.config import load_settings
from regulus.model import environment_info, resolve_device, resolve_dtype


def main() -> int:
    info = environment_info()
    print("=== Environment ===")
    for key, value in info.items():
        print(f"{key:>16}: {value}")

    settings = load_settings()
    device = resolve_device(settings.model.device)
    dtype = resolve_dtype(settings.model.dtype, device)
    print("\n=== Resolved model config ===")
    print(f"{'config file':>16}: {settings.source}")
    print(f"{'model id':>16}: {settings.model.id}")
    print(f"{'cache dir':>16}: {settings.model.cache_dir}")
    print(f"{'device':>16}: {device}  (config: {settings.model.device})")
    print(f"{'dtype':>16}: {dtype}  (config: {settings.model.dtype})")

    if not info["cuda_available"]:
        print("\nNOTE: CUDA not available - running in CPU-only mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
