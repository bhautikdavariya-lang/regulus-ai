"""Stage 12 fine-tuning configuration (configs/model_training.yaml)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from regulus.config import PROJECT_ROOT, ModelConfig, load_settings

DEFAULT_FINETUNE_CONFIG_PATH = PROJECT_ROOT / "configs" / "model_training.yaml"
STAGE = 12


class FinetuneConfigError(ValueError):
    """Missing or invalid Stage 12 configuration."""


def _resolve(raw: str | Path) -> Path:
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


@dataclass(frozen=True)
class DatasetConfig:
    train: Path
    validation: Path
    test: Path
    manifest: Path
    expected_hash: str
    expected_counts: dict[str, int]
    seed: int = 42
    eval_subset: int = 64
    eval_stratified: bool = False
    protected: tuple[Path, ...] = ()


@dataclass(frozen=True)
class LoraSettings:
    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    bias: str = "none"
    task_type: str = "CAUSAL_LM"
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


@dataclass(frozen=True)
class TrainSettings:
    learning_rate: float = 2e-4
    num_train_epochs: float = 1.0
    max_steps: int = -1
    per_device_train_batch_size: int = 1
    per_device_eval_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    warmup_steps: int = 4
    weight_decay: float = 0.0
    lr_scheduler_type: str = "cosine"
    logging_steps: int = 2
    eval_strategy: str = "steps"
    eval_steps: int = 20
    save_strategy: str = "steps"
    save_steps: int = 20
    save_total_limit: int = 2
    early_stopping_patience: int = 0
    max_seq_length: int = 1280
    over_length_policy: str = "skip"
    gradient_checkpointing: bool = True
    seed: int = 42
    # Wall-clock stop. "HH:MM" local time today (or tomorrow if already past),
    # or "" for none. Training stops at deadline minus deadline_reserve_seconds,
    # after evaluating and saving a final checkpoint, so the run always finishes
    # with a selectable adapter instead of being killed mid-step.
    deadline_local: str = ""
    deadline_reserve_seconds: int = 1500
    # Stage 6: "legacy" renders examples with the Stage 6 RAG prompt (Stages 12-14
    # reproduce byte for byte); "grounded" renders them with the Stage 4 generation
    # contract the pipeline now uses at inference, so training and inference agree.
    prompt_format: str = "legacy"
    # Stage 6: keep every saved checkpoint (save_total_limit is ignored) so each
    # can be scored on the task afterwards instead of selected by loss alone.
    keep_all_checkpoints: bool = False


@dataclass(frozen=True)
class FinetuneConfig:
    model_name: str
    model: ModelConfig
    dataset: DatasetConfig
    lora: LoraSettings
    training: TrainSettings
    output_dir: Path
    smoke_dir: Path
    source: Path | None = None
    # Optional: start from a saved adapter's weights instead of fresh LoRA
    # initialisation, so a run can continue earlier training on new data.
    # The adapter's LoRA shape must match this config's lora section.
    init_adapter: Path | None = None

    def __post_init__(self) -> None:
        t, l, d = self.training, self.lora, self.dataset
        if t.learning_rate <= 0 or t.per_device_train_batch_size <= 0 or t.gradient_accumulation_steps <= 0:
            raise FinetuneConfigError("learning_rate, batch size and gradient_accumulation_steps must be positive")
        if t.max_seq_length < 64:
            raise FinetuneConfigError("max_seq_length must be at least 64 tokens")
        if t.over_length_policy not in ("skip", "truncate"):
            raise FinetuneConfigError("over_length_policy must be 'skip' or 'truncate'")
        if t.prompt_format not in ("legacy", "grounded"):
            raise FinetuneConfigError("prompt_format must be 'legacy' or 'grounded'")
        if t.eval_strategy not in ("no", "steps", "epoch") or t.save_strategy not in ("no", "steps", "epoch"):
            raise FinetuneConfigError("eval_strategy / save_strategy must be no, steps or epoch")
        if t.max_steps == 0 or t.max_steps < -1:
            raise FinetuneConfigError("max_steps must be -1 (epochs) or a positive step count")
        if t.deadline_local:
            try:
                hh, mm = t.deadline_local.split(":")
                if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                    raise ValueError
            except ValueError:
                raise FinetuneConfigError(f"deadline_local must be 'HH:MM', got {t.deadline_local!r}") from None
        if t.deadline_reserve_seconds < 0:
            raise FinetuneConfigError("deadline_reserve_seconds must be >= 0")
        if l.r <= 0 or l.alpha <= 0 or not (0.0 <= l.dropout < 1.0) or not l.target_modules:
            raise FinetuneConfigError("invalid LoRA settings (r, alpha, dropout, target_modules)")
        if l.task_type != "CAUSAL_LM":
            raise FinetuneConfigError("task_type must be CAUSAL_LM")
        if set(d.expected_counts) != {"train", "validation", "test"} or any(v <= 0 for v in d.expected_counts.values()):
            raise FinetuneConfigError("expected_counts must give positive train/validation/test counts")
        if len(d.expected_hash) != 64:
            raise FinetuneConfigError("expected_hash must be a sha256 hex digest")
        if d.eval_subset <= 0:
            raise FinetuneConfigError("eval_subset must be positive")
        if self.output_dir.resolve() == self.smoke_dir.resolve():
            raise FinetuneConfigError("output and smoke directories must differ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": STAGE,
            "model": {"name": self.model_name, "id": self.model.id, "cache_dir": _rel(self.model.cache_dir), "device": self.model.device, "dtype": self.model.dtype},
            "dataset": {
                "train": _rel(self.dataset.train),
                "validation": _rel(self.dataset.validation),
                "test": _rel(self.dataset.test),
                "manifest": _rel(self.dataset.manifest),
                "expected_hash": self.dataset.expected_hash,
                "expected_counts": dict(self.dataset.expected_counts),
                "seed": self.dataset.seed,
                "eval_subset": self.dataset.eval_subset,
                "eval_stratified": self.dataset.eval_stratified,
                "protected": [_rel(p) for p in self.dataset.protected],
            },
            "lora": {**asdict(self.lora), "target_modules": list(self.lora.target_modules)},
            "training": asdict(self.training),
            "output": {"directory": _rel(self.output_dir), "smoke_directory": _rel(self.smoke_dir)},
            "source": _rel(self.source) if self.source else None,
            "init_adapter": _rel(self.init_adapter) if self.init_adapter else None,
        }


def load_finetune_config(path: str | Path | None = None, **overrides: Any) -> FinetuneConfig:
    """Load the YAML; `overrides` (max_steps, output_dir, eval_subset, ...) win over the file."""
    path = Path(path) if path else DEFAULT_FINETUNE_CONFIG_PATH
    if not path.is_file():
        raise FinetuneConfigError(f"training config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise FinetuneConfigError(f"{path} must contain a mapping")
    for section in ("model", "dataset", "lora", "training", "output"):
        if not isinstance(data.get(section), dict):
            raise FinetuneConfigError(f"{path}: missing section '{section}'")
    m, d, l, t, o = (data[s] for s in ("model", "dataset", "lora", "training", "output"))
    for key in ("train", "validation", "test", "manifest", "expected_hash", "expected_counts"):
        if key not in d:
            raise FinetuneConfigError(f"{path}: dataset.{key} is required")
    if "directory" not in o:
        raise FinetuneConfigError(f"{path}: output.directory is required")
    try:
        settings = load_settings(_resolve(m.get("config", "configs/model.yaml")), use_dotenv=True)
    except Exception as exc:  # ConfigError or file problems
        raise FinetuneConfigError(f"model config: {exc}") from exc

    train_defaults = TrainSettings()
    train_values = {k: type(getattr(train_defaults, k))(t.get(k, getattr(train_defaults, k))) for k in asdict(train_defaults)}
    for key, value in overrides.items():
        if key in train_values and value is not None:
            train_values[key] = type(train_values[key])(value)
    lora_defaults = LoraSettings()
    lora = LoraSettings(
        r=int(l.get("r", lora_defaults.r)),
        alpha=int(l.get("alpha", lora_defaults.alpha)),
        dropout=float(l.get("dropout", lora_defaults.dropout)),
        bias=str(l.get("bias", lora_defaults.bias)),
        task_type=str(l.get("task_type", lora_defaults.task_type)),
        target_modules=tuple(str(x) for x in l.get("target_modules", lora_defaults.target_modules)),
    )
    dataset = DatasetConfig(
        train=_resolve(d["train"]),
        validation=_resolve(d["validation"]),
        test=_resolve(d["test"]),
        manifest=_resolve(d["manifest"]),
        expected_hash=str(d["expected_hash"]).strip(),
        expected_counts={str(k): int(v) for k, v in dict(d["expected_counts"]).items()},
        seed=int(d.get("seed", 42)),
        eval_subset=int(overrides.get("eval_subset") or d.get("eval_subset", 64)),
        eval_stratified=bool(d.get("eval_stratified", False)),
        protected=tuple(_resolve(p) for p in d.get("protected", [])),
    )
    known = set(train_values) | {"eval_subset", "output_dir", "smoke_dir", "init_adapter"}
    unknown = set(overrides) - known
    if unknown:
        raise FinetuneConfigError(f"unknown override(s): {sorted(unknown)}")
    return FinetuneConfig(
        model_name=str(m.get("name", "Qwen3-0.6B")),
        model=settings.model,
        dataset=dataset,
        lora=lora,
        training=TrainSettings(**train_values),
        output_dir=_resolve(overrides.get("output_dir") or o["directory"]),
        smoke_dir=_resolve(overrides.get("smoke_dir") or o.get("smoke_directory", "models/qwen3-0.6b-lora/smoke_tmp")),
        source=path,
        init_adapter=_resolve(init_adapter) if (init_adapter := (overrides.get("init_adapter") or m.get("init_adapter"))) else None,
    )
