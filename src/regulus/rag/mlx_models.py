"""The MLX models the application may answer with, identified by their config.json (22 Oct 2026).

Qwen3-4B-Instruct-2507 has the widths of the hybrid Qwen3-4B; its context length and rope base tell them apart, and the
Thinking-2507 variant (same config) is refused at start because its template opens a reasoning block. One table for
scripts/serve_ui.py and scripts/run_cosmetics_eval.py, so a benchmark answer records the model the UI would serve.
"""
from __future__ import annotations

SUPPORTED_MLX_MODELS = {
    "qwen3-1.7b": {"model_id": "Qwen/Qwen3-1.7B", "label": "Qwen3-1.7B (MLX 4-bit)",
                   "config": {"model_type": "qwen3", "hidden_size": 2048, "num_hidden_layers": 28, "intermediate_size": 6144}},
    "qwen3-4b-2507": {"model_id": "Qwen/Qwen3-4B-Instruct-2507", "label": "Qwen3-4B-Instruct-2507 (MLX 4-bit)",
                      "config": {"model_type": "qwen3", "hidden_size": 2560, "num_hidden_layers": 36, "intermediate_size": 9728,
                                 "max_position_embeddings": 262144, "rope_theta": 5000000}},
}
EXPECTED_BITS = 4


THINKING_MLX_MODELS = {
    # same config.json as Qwen3-4B-Instruct-2507; told apart by its template, which opens a reasoning block. Used only
    # when REGULUS_ALLOW_THINKING=1 (22 Oct 2026 experiment: reasoning for questions the instruct model misapplies)
    "qwen3-4b-2507": {"key": "qwen3-4b-thinking-2507", "model_id": "Qwen/Qwen3-4B-Thinking-2507",
                      "label": "Qwen3-4B-Thinking-2507 (MLX 4-bit)"},
}


def identify_mlx_model(cfg: dict) -> str | None:
    """The SUPPORTED_MLX_MODELS key whose config.json values `cfg` has, or None."""
    return next((key for key, spec in SUPPORTED_MLX_MODELS.items()
                 if all(cfg.get(k) == v for k, v in spec["config"].items())), None)


def thinking_allowed() -> bool:
    import os

    return (os.environ.get("REGULUS_ALLOW_THINKING") or "").strip() in ("1", "true", "yes")


def opens_reasoning(prefix: str) -> bool:
    """True when the text a template puts after the assistant header opens a reasoning block the model must fill
    ("<think>\\n"). Qwen3-1.7B's non-thinking prompt ends with an empty, closed "<think></think>": not a thinking model."""
    p = (prefix or "").strip()
    return p.startswith("<think>") and "</think>" not in p
