"""Stage 12: LoRA fine-tuning of Qwen3-0.6B on the Stage 11 dataset.
Importing this package never starts training; use scripts/train_model.py."""

from regulus.finetune.adapter import AdapterError, adapter_identity, attach_saved_adapter, inference_check, load_adapter_model
from regulus.finetune.config import FinetuneConfig, FinetuneConfigError, LoraSettings, TrainSettings, load_finetune_config
from regulus.finetune.data import DatasetIdentityError, collate, render_example, tokenize_examples, verify_dataset
from regulus.finetune.lora import LoraTargetError, attach_lora, verify_target_modules
from regulus.config import PROJECT_ROOT

DEFAULT_ADAPTER_DIR = PROJECT_ROOT / "models" / "qwen3-0.6b-lora" / "stage12_v1" / "adapter"

__all__ = [
    "DEFAULT_ADAPTER_DIR",
    "AdapterError",
    "DatasetIdentityError",
    "FinetuneConfig",
    "FinetuneConfigError",
    "LoraSettings",
    "LoraTargetError",
    "TrainSettings",
    "adapter_identity",
    "attach_lora",
    "attach_saved_adapter",
    "collate",
    "inference_check",
    "load_adapter_model",
    "load_finetune_config",
    "render_example",
    "tokenize_examples",
    "verify_dataset",
    "verify_target_modules",
]
