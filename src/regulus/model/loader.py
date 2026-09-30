"""Tokenizer / model loading from the Hugging Face Hub with a fixed cache dir."""

from __future__ import annotations

import logging
import time

import torch
from huggingface_hub.errors import (
    GatedRepoError,
    HfHubHTTPError,
    LocalEntryNotFoundError,
    RepositoryNotFoundError,
)
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedModel,
    PreTrainedTokenizerBase,
)

from regulus.config import ModelConfig
from regulus.model.device import resolve_device, resolve_dtype

log = logging.getLogger(__name__)


class ModelLoadError(RuntimeError):
    """Raised with a human-readable explanation when loading fails."""


def _explain(exc: Exception, model_id: str) -> str:
    if isinstance(exc, RepositoryNotFoundError):
        return f"Model '{model_id}' was not found on the Hugging Face Hub. Check the model id."
    if isinstance(exc, GatedRepoError):
        return f"Model '{model_id}' is gated. Accept its license on huggingface.co and set HF_TOKEN."
    if isinstance(exc, LocalEntryNotFoundError):
        return (
            f"Model '{model_id}' is not in the local cache and the Hub could not be reached. "
            "Check your network or run scripts/download_model.py first."
        )
    if isinstance(exc, HfHubHTTPError):
        return f"Hugging Face Hub request failed for '{model_id}': {exc}"
    if isinstance(exc, (MemoryError, torch.cuda.OutOfMemoryError)):
        return (
            f"Out of memory while loading '{model_id}'. Close other applications, choose a "
            "smaller model, or use a lower-precision dtype."
        )
    if isinstance(exc, OSError):
        return f"Could not load '{model_id}': {exc}"
    return f"Unexpected error while loading '{model_id}': {type(exc).__name__}: {exc}"


def load_tokenizer(cfg: ModelConfig, *, local_files_only: bool = False) -> PreTrainedTokenizerBase:
    try:
        return AutoTokenizer.from_pretrained(
            cfg.id, cache_dir=str(cfg.cache_dir), local_files_only=local_files_only
        )
    except Exception as exc:  # re-raised with a readable explanation
        raise ModelLoadError(_explain(exc, cfg.id)) from exc


def load_model(cfg: ModelConfig, *, local_files_only: bool = False) -> PreTrainedModel:
    try:
        device = resolve_device(cfg.device)
        dtype = resolve_dtype(cfg.dtype, device)
    except (RuntimeError, ValueError) as exc:
        raise ModelLoadError(str(exc)) from exc
    log.info("Loading %s (device=%s, dtype=%s, cache=%s)", cfg.id, device, dtype, cfg.cache_dir)
    start = time.perf_counter()
    try:
        model = AutoModelForCausalLM.from_pretrained(
            cfg.id,
            cache_dir=str(cfg.cache_dir),
            dtype=dtype,
            local_files_only=local_files_only,
        )
        model.to(device)
        model.eval()
    except Exception as exc:  # re-raised with a readable explanation
        raise ModelLoadError(_explain(exc, cfg.id)) from exc
    log.info("Model loaded in %.1fs", time.perf_counter() - start)
    return model
