"""Device / dtype detection. Works with or without CUDA."""

from __future__ import annotations

import platform
import sys
from typing import Any

import torch


def resolve_device(requested: str = "auto") -> torch.device:
    """Turn a config value (auto, cpu, mps, cuda, cuda:1) into a torch.device.

    "auto" never picks MPS: the Apple GPU is opt-in (device: mps) until it is
    validated as a default, so "auto" keeps resolving exactly as it always did.
    An explicitly requested device that is not available is an error, never a
    silent fallback, so the device in use is always the one asked for.
    """
    requested = (requested or "auto").lower()
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError(
            "Device 'mps' requested but the Apple GPU (MPS) is not available. "
            "Set device to 'cpu' in configs/model.yaml (or REGULUS_DEVICE=cpu)."
        )
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            f"Device {requested!r} requested but CUDA is not available. "
            "Set device to 'auto' or 'cpu' in configs/model.yaml (or REGULUS_DEVICE)."
        )
    return torch.device(requested)


def resolve_dtype(requested: str, device: torch.device) -> torch.dtype:
    """Map a config dtype string to torch.dtype, choosing sensibly for "auto"."""
    requested = (requested or "auto").lower()
    if requested == "auto":
        if device.type == "cuda":
            return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        # CPU: float32 is the fast, numerically safe choice on most CPUs.
        # MPS: also float32 unless float16 is asked for explicitly.
        return torch.float32
    mapping = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
    try:
        return mapping[requested]
    except KeyError as exc:
        raise ValueError(f"Unsupported dtype {requested!r}") from exc


def environment_info() -> dict[str, Any]:
    """Collect environment facts for logging / diagnostics."""
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "mps_available": torch.backends.mps.is_available(),
        "cpu_threads": torch.get_num_threads(),
        "gpu_name": None,
    }
    if info["cuda_available"]:
        props = torch.cuda.get_device_properties(0)
        info["gpu_name"] = props.name
        info["gpu_memory_gb"] = round(props.total_memory / 1024**3, 2)
        info["gpu_count"] = torch.cuda.device_count()
    return info
