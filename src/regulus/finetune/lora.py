"""LoRA attachment with programmatic target-module verification."""

from __future__ import annotations

from typing import Any

import torch
from peft import LoraConfig, PeftModel, TaskType, get_peft_model

from regulus.finetune.config import LoraSettings


class LoraTargetError(ValueError):
    """A requested target module does not exist in the loaded architecture."""


def linear_module_names(model: torch.nn.Module) -> set[str]:
    return {name.split(".")[-1] for name, mod in model.named_modules() if isinstance(mod, torch.nn.Linear)}


def verify_target_modules(model: torch.nn.Module, targets: tuple[str, ...]) -> dict[str, int]:
    """Return {target: occurrences}; raise if any target is absent."""
    counts = {t: 0 for t in targets}
    for name, mod in model.named_modules():
        leaf = name.split(".")[-1]
        if leaf in counts and isinstance(mod, torch.nn.Linear):
            counts[leaf] += 1
    missing = [t for t, n in counts.items() if n == 0]
    if missing:
        raise LoraTargetError(f"LoRA target module(s) not found in {type(model).__name__}: {missing}; available linear modules: {sorted(linear_module_names(model))}")
    return counts


def load_lora_for_training(model: torch.nn.Module, settings: LoraSettings, init_adapter=None) -> tuple[PeftModel, dict[str, Any]]:
    """Fresh LoRA weights, or a saved adapter's weights made trainable again.

    Continuing from an adapter only makes sense if its shape matches the
    configured one, so r, alpha and the target modules are compared and a
    mismatch raises rather than silently retraining a different architecture.
    """
    if init_adapter is None:
        return attach_lora(model, settings)
    import json
    from pathlib import Path

    init_adapter = Path(init_adapter)
    cfg_path = init_adapter / "adapter_config.json"
    if not cfg_path.is_file():
        raise LoraTargetError(f"no adapter_config.json in {init_adapter}")
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    mismatches = []
    if int(saved.get("r", -1)) != settings.r:
        mismatches.append(f"r {saved.get('r')} != {settings.r}")
    if int(saved.get("lora_alpha", -1)) != settings.alpha:
        mismatches.append(f"alpha {saved.get('lora_alpha')} != {settings.alpha}")
    if set(saved.get("target_modules") or []) != set(settings.target_modules):
        mismatches.append(f"target_modules {sorted(saved.get('target_modules') or [])} != {sorted(settings.target_modules)}")
    if mismatches:
        raise LoraTargetError(f"init_adapter {init_adapter.name} does not match the configured LoRA: " + "; ".join(mismatches))
    counts = verify_target_modules(model, settings.target_modules)
    peft_model = PeftModel.from_pretrained(model, str(init_adapter), is_trainable=True)
    trainable = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in peft_model.parameters())
    if trainable == 0:
        raise LoraTargetError(f"adapter {init_adapter.name} loaded with no trainable parameters")
    info = {
        "trainable_parameters": trainable,
        "total_parameters": total,
        "trainable_percent": round(100.0 * trainable / total, 3),
        "base_parameters_frozen": all(not p.requires_grad for n, p in peft_model.named_parameters() if "lora_" not in n),
        "target_module_counts": counts,
        "lora": {"r": settings.r, "alpha": settings.alpha, "dropout": settings.dropout, "bias": settings.bias, "task_type": settings.task_type, "target_modules": list(settings.target_modules)},
        "initialised_from": init_adapter.as_posix(),
    }
    return peft_model, info


def attach_lora(model: torch.nn.Module, settings: LoraSettings) -> tuple[PeftModel, dict[str, Any]]:
    counts = verify_target_modules(model, settings.target_modules)
    config = LoraConfig(
        r=settings.r,
        lora_alpha=settings.alpha,
        lora_dropout=settings.dropout,
        bias=settings.bias,
        task_type=TaskType.CAUSAL_LM,
        target_modules=list(settings.target_modules),
    )
    peft_model = get_peft_model(model, config)
    trainable = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in peft_model.parameters())
    frozen_base = all(not p.requires_grad for n, p in peft_model.named_parameters() if "lora_" not in n)
    info = {
        "trainable_parameters": trainable,
        "total_parameters": total,
        "trainable_percent": round(100.0 * trainable / total, 3),
        "base_parameters_frozen": frozen_base,
        "target_module_counts": counts,
        "lora": {"r": settings.r, "alpha": settings.alpha, "dropout": settings.dropout, "bias": settings.bias, "task_type": settings.task_type, "target_modules": list(settings.target_modules)},
    }
    return peft_model, info
