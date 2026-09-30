"""Adapter for a LoRA training run directory.

A run lives at `models/qwen3-0.6b-lora/<run>/` and, when it finished, holds
`training_summary.json`, `metadata.json`, `training_metrics.json`,
`dataset_manifest.json`, `training_config.yaml`, an `adapter/` directory and
`checkpoints/checkpoint-*/`. A run that died holds only its logs and whatever
checkpoints it had written, and is reported as such rather than omitted.

Everything this adapter produces is a **training-process** measurement. The
metric registry's caveats say plainly that a lower loss is not a better
regulatory model, and the dashboard keeps these numbers in their own family
so they can never be read as accuracy. The only thing that can say whether
answers improved is an evaluation run on a benchmark.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import metrics as M
from ..schemas import (
    COMPLETE,
    FAILED,
    INCOMPLETE,
    KIND_TRAINING,
    MISSING,
    Checkpoint,
    MetricResult,
    ModelIdentity,
    TrainingRun,
    stable_id,
)

SCHEMA = "lora-training/v1"

SUMMARY = "training_summary.json"
METADATA = "metadata.json"
CURVES = "training_metrics.json"
MANIFEST = "dataset_manifest.json"
CONFIG = "training_config.yaml"


def _json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _get(obj: Any, *path: str, default: Any = None) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
    return default if obj is None else obj


def _dir_size(directory: Path) -> int | None:
    try:
        return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
    except OSError:
        return None


# -------------------------------------------------------------------- detect


def detect(path: str | Path) -> bool:
    """True for a directory that looks like a training run.

    A finished run is recognised by its summary or its metrics; a run that
    never got that far is recognised by its checkpoints or its training log,
    so a failed run is still discovered and reported instead of vanishing.
    """
    directory = Path(path)
    if not directory.is_dir():
        return False
    if any((directory / name).is_file() for name in (SUMMARY, CURVES, METADATA, CONFIG)):
        return True
    if (directory / "checkpoints").is_dir() and any(directory.glob("checkpoints/checkpoint-*")):
        return True
    return (directory / "train.log").is_file() or (directory / "train.stalled.log").is_file()


# ------------------------------------------------------------------ identity


def _model(directory: Path, metadata: dict | None, summary: dict | None, best_checkpoint: str | None) -> ModelIdentity:
    adapter_config = _json(directory / "adapter" / "adapter_config.json") or {}
    base = (
        adapter_config.get("base_model_name_or_path")
        or _get(metadata, "base_model_id")
        or _get(metadata, "model")
        or _get(summary, "base_model_id")
    )
    adapter_dir = directory / "adapter"
    return ModelIdentity(
        base_model_id=str(base) if base else "unrecorded",
        revision=None,
        adapter_id=directory.name,
        adapter_path=adapter_dir.as_posix() if adapter_dir.is_dir() else None,
        checkpoint=best_checkpoint,
        dtype=_get(metadata, "dtype") or _get(summary, "hardware", "dtype"),
        device=_get(metadata, "device") or _get(summary, "hardware", "device"),
    )


# -------------------------------------------------------------------- curves


def _curves(history: list[dict]) -> dict[str, list[dict[str, Any]]]:
    """Split the trainer log into one series per quantity.

    Training loss and validation loss share a scale and belong on one axis.
    The learning rate and the gradient norm do not, so they are separate
    series the UI renders as their own charts rather than a second y-axis.
    """
    train, evaluation, lr, grad = [], [], [], []
    for entry in history:
        step = entry.get("step")
        epoch = entry.get("epoch")
        if entry.get("loss") is not None:
            train.append({"step": step, "epoch": epoch, "value": entry["loss"]})
        if entry.get("eval_loss") is not None:
            evaluation.append({"step": step, "epoch": epoch, "value": entry["eval_loss"]})
        if entry.get("learning_rate") is not None:
            lr.append({"step": step, "epoch": epoch, "value": entry["learning_rate"]})
        if entry.get("grad_norm") is not None:
            grad.append({"step": step, "epoch": epoch, "value": entry["grad_norm"]})
    return {"training_loss": train, "validation_loss": evaluation, "learning_rate": lr, "grad_norm": grad}


def _checkpoints(directory: Path, history: list[dict], selected: str | None) -> tuple[Checkpoint, ...]:
    eval_by_step = {e.get("step"): e.get("eval_loss") for e in history if e.get("eval_loss") is not None}
    loss_by_step = {e.get("step"): e.get("loss") for e in history if e.get("loss") is not None}
    out: list[Checkpoint] = []
    for path in sorted((directory / "checkpoints").glob("checkpoint-*")):
        if not path.is_dir():
            continue
        state = _json(path / "trainer_state.json") or {}
        try:
            step = int(path.name.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            step = state.get("global_step")
        out.append(Checkpoint(
            name=path.name,
            step=step,
            training_loss=loss_by_step.get(step),
            validation_loss=eval_by_step.get(step) if eval_by_step.get(step) is not None else state.get("best_metric"),
            created_at=None,
            path=path.as_posix(),
            size_bytes=_dir_size(path),
            is_selected=bool(selected and Path(str(selected)).name == path.name),
        ))
    return tuple(sorted(out, key=lambda c: (c.step is None, c.step)))


# ------------------------------------------------------------------- metrics


def _scalar(key: str, value: Any, *, source: str, note: str | None = None,
            numerator: int | None = None, denominator: int | None = None) -> MetricResult:
    if not isinstance(value, (int, float)):
        return M.make_metric(key, None, source=source, status=MISSING,
                             note=note or "not recorded by this run")
    return M.make_metric(key, float(value), numerator=numerator, denominator=denominator,
                         source=source, note=note)


def _metrics(summary: dict | None, metadata: dict | None, curves: dict | None,
             state: dict | None, history: list[dict]) -> list[MetricResult]:
    final_eval = _get(curves, "final_eval", "eval_loss")
    base_eval = _get(curves, "base_eval", "eval_loss")
    if final_eval is None:
        final_eval = _get(metadata, "best_validation_loss")
    if base_eval is None:
        base_eval = _get(metadata, "base_validation_loss")

    train_loss = next((e.get("train_loss") for e in reversed(history) if e.get("train_loss") is not None), None)
    if train_loss is None:
        train_loss = _get(metadata, "final_training_loss")

    trainable = _get(metadata, "lora", "trainable_parameters") or _get(summary, "lora", "trainable_parameters")
    total_params = _get(metadata, "lora", "total_parameters") or _get(summary, "lora", "total_parameters")

    out = [
        _scalar("final_train_loss", train_loss, source=CURVES),
        _scalar("final_eval_loss", final_eval, source=CURVES),
        _scalar("base_eval_loss", base_eval, source=CURVES),
        _scalar(
            "eval_loss_delta",
            None if final_eval is None or base_eval is None else round(final_eval - base_eval, 6),
            source=CURVES,
            note="movement on the training data's own distribution; not evidence that answers improved",
        ),
        _scalar("best_eval_loss", _get(state, "best_metric") or _get(metadata, "best_validation_loss"),
                source="trainer_state.json"),
        _scalar("total_steps", _get(state, "global_step") or _get(metadata, "training", "steps_completed"),
                source="trainer_state.json"),
        _scalar("planned_steps", _get(state, "max_steps") or _get(metadata, "training", "max_steps"),
                source="trainer_state.json"),
        _scalar("epochs_completed", _get(state, "epoch") or _get(metadata, "training", "epochs"), source=CURVES),
        _scalar("trainable_parameters", trainable, source=METADATA, denominator=total_params),
        _scalar("training_examples", _get(metadata, "dataset", "train_examples_used")
                or _get(metadata, "dataset", "train_examples"), source=METADATA),
        _scalar("validation_examples", _get(metadata, "dataset", "validation_subset_used")
                or _get(metadata, "dataset", "validation_examples"), source=METADATA),
        _scalar("training_duration", _get(summary, "training_duration_seconds")
                or _get(metadata, "training", "duration_seconds"), source=SUMMARY),
    ]
    if isinstance(trainable, int) and isinstance(total_params, int) and total_params:
        out.append(M.ratio_metric("trainable_percent", trainable, total_params, source=METADATA))
    return out


# ---------------------------------------------------------------------- load


def load(path: str | Path, root: Path | None = None) -> TrainingRun:
    """Read a training run directory into a TrainingRun. Read-only."""
    directory = Path(path)
    if not directory.is_dir():
        raise ValueError(f"{directory} is not a training run directory")

    problems: list[str] = []
    present: list[str] = []

    def read(name: str) -> Any | None:
        data = _json(directory / name)
        if data is None:
            if (directory / name).exists():
                problems.append(f"{name} is present but could not be parsed as JSON")
            return None
        present.append(name)
        return data

    summary = read(SUMMARY)
    metadata = read(METADATA)
    curves_raw = read(CURVES)
    manifest = read(MANIFEST)
    if (directory / CONFIG).is_file():
        present.append(CONFIG)

    history = list(_get(curves_raw, "log_history", default=[]) or [])

    # The newest checkpoint's trainer state is the run's own record of where
    # it stopped and which checkpoint it chose.
    states = sorted((directory / "checkpoints").glob("checkpoint-*/trainer_state.json"))
    state = _json(states[-1]) if states else None
    if state:
        present.append(f"checkpoints/{states[-1].parent.name}/trainer_state.json")
    if not history and state:
        history = list(state.get("log_history") or [])
        if history:
            problems.append(
                f"{CURVES} is absent; the loss curves were read from {states[-1].parent.name}/trainer_state.json instead"
            )

    best_checkpoint = _get(metadata, "best_checkpoint") or _get(state, "best_model_checkpoint")
    best_name = Path(str(best_checkpoint)).name if best_checkpoint else None
    checkpoints = _checkpoints(directory, history, best_checkpoint)

    # ---- status, from the artifacts only
    stalled = sorted(p.name for p in directory.glob("*.stalled.log"))
    if summary is None and curves_raw is None and metadata is None:
        status = FAILED if stalled else INCOMPLETE
        problems.append(
            "this run wrote no summary, metadata or metrics file, so it did not finish training. "
            + (f"The directory holds {', '.join(stalled)}, which the harness renames a log to when it "
               "abandons a run that stopped making progress. " if stalled else "")
            + (f"{len(checkpoints)} checkpoint(s) were written before it stopped."
               if checkpoints else "No checkpoint was written.")
        )
    elif summary is None or not _get(summary, "finished_utc"):
        status = INCOMPLETE
        problems.append("no finish timestamp was recorded, so this run did not complete cleanly")
    else:
        status = COMPLETE
        if stalled:
            problems.append(f"the directory also holds {', '.join(stalled)} from an earlier abandoned attempt")

    planned = _get(state, "max_steps") or _get(metadata, "training", "max_steps")
    done = _get(state, "global_step") or _get(metadata, "training", "steps_completed")
    if isinstance(planned, int) and isinstance(done, int) and done < planned:
        problems.append(
            f"training stopped at step {done} of the {planned} it was configured for; "
            "read the loss curve as a partial run"
        )

    if not (directory / "adapter").is_dir():
        problems.append("no adapter directory: this run produced no loadable adapter weights")

    metrics = _metrics(summary, metadata, curves_raw, state, history)
    problems.append(
        "every number here describes the training process. A lower training or validation loss is not "
        "evidence of a better regulatory model: only an evaluation run on a benchmark can show that."
    )

    identifier = directory.relative_to(root).as_posix() if root and _under(directory, root) else directory.as_posix()

    return TrainingRun(
        training_run_id=stable_id(KIND_TRAINING, identifier),
        name=directory.name,
        path=directory.as_posix(),
        model=_model(directory, metadata, summary, best_name),
        status=status,
        started_at=_get(summary, "started_utc"),
        completed_at=_get(summary, "finished_utc") or _get(metadata, "timestamp"),
        duration_seconds=_get(summary, "training_duration_seconds") or _get(metadata, "training", "duration_seconds"),
        dataset={
            "version": _get(metadata, "dataset", "version") or _get(manifest, "dataset_version"),
            "hash": _get(metadata, "dataset", "hash") or _get(summary, "dataset_identity", "dataset_sha256"),
            "seed": _get(metadata, "dataset", "seed"),
            "train_examples": _get(metadata, "dataset", "train_examples"),
            "train_examples_used": _get(metadata, "dataset", "train_examples_used"),
            "validation_examples": _get(metadata, "dataset", "validation_examples"),
            "test_examples": _get(metadata, "dataset", "test_examples"),
            "generated_at_utc": _get(manifest, "generated_at_utc") or _get(summary, "dataset_identity", "generated_at_utc"),
            "database_snapshot": _get(summary, "dataset_identity", "database_snapshot"),
            "files": _get(summary, "dataset_identity", "files", default={}),
            "protected_benchmarks": _get(summary, "protected_files_sha256", default={}),
            "category_distribution": _get(summary, "tokenization", "train", "category_distribution", default={}),
        },
        lora=_get(metadata, "lora", default={}) or _get(summary, "lora", default={}),
        hyperparameters=_get(metadata, "training", default={}),
        curves=_curves(history),
        checkpoints=checkpoints,
        resources={
            **(_get(summary, "hardware", default={}) or {}),
            "dependencies": _get(summary, "dependencies", default={}) or _get(metadata, "dependencies", default={}),
            "tokenization": _get(summary, "tokenization", default={}),
            "total_flos": _get(state, "total_flos"),
            "num_input_tokens_seen": _get(state, "num_input_tokens_seen"),
        },
        losses={
            "base_validation": _get(curves_raw, "base_eval", "eval_loss") or _get(metadata, "base_validation_loss"),
            "best_validation": _get(metadata, "best_validation_loss") or _get(state, "best_metric"),
            "final_validation": _get(curves_raw, "final_eval", "eval_loss"),
            "final_training": _get(metadata, "final_training_loss"),
            "best_checkpoint": best_name,
            "final_eval_note": _get(curves_raw, "final_eval", "note"),
        },
        metrics=tuple(metrics),
        source_artifacts=tuple(sorted(set(present))),
        problems=tuple(problems),
    )


def _under(directory: Path, root: Path) -> bool:
    try:
        directory.relative_to(root)
        return True
    except ValueError:
        return False
