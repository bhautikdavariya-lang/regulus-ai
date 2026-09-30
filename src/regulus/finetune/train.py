"""Stage 12 training run: dataset identity -> tokenisation -> LoRA -> Trainer
-> adapter + metadata. Importing this module never trains; `run_training`
is called only by scripts/train_model.py.
"""

from __future__ import annotations

import json
import math
import platform
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import torch
import yaml
from transformers import TrainerCallback

from regulus.config import GenerationConfig
from regulus.finetune.adapter import inference_check, load_adapter_model
from regulus.finetune.config import STAGE, FinetuneConfig
from regulus.finetune.data import collate, eval_subset, example_messages, load_split, protected_hashes, subset_distribution, tokenize_examples, verify_dataset
from regulus.finetune.lora import attach_lora, load_lora_for_training
from regulus.model import environment_info, load_model, load_tokenizer
from regulus.model.device import resolve_device, resolve_dtype
from regulus.training.models import to_messages

Log = Callable[[str], None]


def resolve_deadline(hhmm: str, now: datetime | None = None) -> datetime | None:
    """'18:30' -> that time today in local time, or tomorrow if already past."""
    if not hhmm:
        return None
    now = now or datetime.now().astimezone()
    hh, mm = (int(x) for x in hhmm.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


class DeadlineCallback(TrainerCallback):
    """Stop training in time to finish the run, not in the middle of it.

    CPU step time varies with example length, so a step count chosen in advance
    cannot be turned into a reliable finishing time. This watches the clock
    instead: when the projected end of the next step would leave less than the
    reserve before the deadline, it asks the Trainer to evaluate, save and stop.
    The run therefore always ends with an evaluated checkpoint.
    """

    def __init__(self, deadline: datetime, reserve_seconds: int, log: Log = print) -> None:
        self.deadline = deadline
        self.reserve = reserve_seconds
        self.log = log
        self.step_times: list[float] = []
        self._last = time.perf_counter()
        self.stopped_early = False
        self.hard_stopped = False
        self.stop_step: int | None = None

    def _past_hard_stop(self) -> bool:
        """True once the deadline itself has passed, reserve included.

        The Stage 14 overnight run stalled inside the pre-training evaluation
        and ran 14 hours past its deadline, because a step-end callback cannot
        fire when no step ever completes. This is checked from the evaluation
        hooks as well so a stall anywhere is bounded by the clock.
        """
        return (self.deadline - datetime.now().astimezone()).total_seconds() <= 0

    def on_prediction_step(self, args, state, control, **kwargs):
        if self._past_hard_stop() and not control.should_training_stop:
            self.stopped_early = True
            self.hard_stopped = True
            self.log(f"Deadline passed during evaluation; stopping at step {state.global_step}.")
            control.should_training_stop = True
        return control

    def on_evaluate(self, args, state, control, **kwargs):
        return self.on_prediction_step(args, state, control, **kwargs)

    def on_step_end(self, args, state, control, **kwargs):
        now = time.perf_counter()
        self.step_times.append(now - self._last)
        self._last = now
        recent = self.step_times[-5:]
        projected_step = max(recent) if recent else 0.0
        remaining = (self.deadline - datetime.now().astimezone()).total_seconds()
        if remaining - self.reserve < projected_step and not control.should_training_stop:
            self.stopped_early = True
            self.stop_step = state.global_step
            self.log(
                f"Deadline: {remaining / 60:.0f} min left, reserving {self.reserve / 60:.0f} min for the final "
                f"evaluation and save; stopping after step {state.global_step}."
            )
            control.should_evaluate = True
            control.should_save = True
            control.should_training_stop = True
        return control

    def summary(self) -> dict[str, Any]:
        return {
            "deadline_local": self.deadline.isoformat(timespec="seconds"),
            "reserve_seconds": self.reserve,
            "stopped_early": self.stopped_early,
            "hard_stopped_past_deadline": self.hard_stopped,
            "stop_step": self.stop_step,
            "median_step_seconds": round(sorted(self.step_times)[len(self.step_times) // 2], 1) if self.step_times else None,
            "steps_timed": len(self.step_times),
        }


def hardware_report(model_cfg) -> dict[str, Any]:
    device = resolve_device(model_cfg.device)
    dtype = resolve_dtype(model_cfg.dtype, device)
    info = environment_info()
    info.update({"device": str(device), "dtype": str(dtype).replace("torch.", ""), "cpu_count": torch.get_num_threads()})
    try:
        import psutil

        vm = psutil.virtual_memory()
        info["ram_total_gb"] = round(vm.total / 1024**3, 2)
        info["ram_available_gb"] = round(vm.available / 1024**3, 2)
    except Exception:  # psutil is optional at runtime
        pass
    if info.get("cuda_available"):
        free, total = torch.cuda.mem_get_info(0)
        info["gpu_memory_free_gb"] = round(free / 1024**3, 2)
    return info


def dependency_versions() -> dict[str, str]:
    import accelerate
    import numpy
    import peft
    import safetensors
    import tokenizers
    import transformers

    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "peft": peft.__version__,
        "accelerate": accelerate.__version__,
        "safetensors": safetensors.__version__,
        "tokenizers": tokenizers.__version__,
        "numpy": numpy.__version__,
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def run_training(cfg: FinetuneConfig, *, smoke: bool = False, log: Log = print) -> dict[str, Any]:
    """Execute the run described by `cfg`. In smoke mode: 4 training and 2
    validation examples, one optimizer step, output under cfg.smoke_dir."""
    from transformers import EarlyStoppingCallback, Trainer, TrainingArguments, set_seed

    t = cfg.training
    out_dir = cfg.smoke_dir if smoke else cfg.output_dir
    if smoke and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    set_seed(t.seed)

    hw = hardware_report(cfg.model)
    log(f"Hardware: device={hw['device']} dtype={hw['dtype']} gpu={hw.get('gpu_name')} gpu_mem_gb={hw.get('gpu_memory_gb')} cpu_threads={hw['cpu_threads']} ram_available_gb={hw.get('ram_available_gb')}")
    if hw["device"] == "cpu":
        log("NOTE: CPU training is slow (about 45 s per 640-token example on the development machine); the run is step-bounded by training.max_steps.")

    identity = verify_dataset(cfg.dataset)
    protected_before = protected_hashes(cfg.dataset.protected)
    log(f"Dataset verified: {identity['dataset_version']} sha256={identity['dataset_sha256'][:16]}... counts={ {k: v['examples'] for k, v in identity['files'].items()} }")

    tokenizer = load_tokenizer(cfg.model, local_files_only=True)
    model = load_model(cfg.model, local_files_only=True)
    model.config.use_cache = False

    train_examples = load_split(cfg.dataset.train)
    val_examples = load_split(cfg.dataset.validation)
    if smoke:
        train_examples, val_examples = train_examples[:4], val_examples[:2]
    val_examples = eval_subset(val_examples, cfg.dataset.eval_subset, cfg.dataset.seed, cfg.dataset.eval_stratified)
    train_ds = tokenize_examples(train_examples, tokenizer, t.max_seq_length, t.over_length_policy, t.prompt_format)
    eval_ds = tokenize_examples(val_examples, tokenizer, t.max_seq_length, t.over_length_policy, t.prompt_format)
    eval_ds.stats["category_distribution"] = subset_distribution(val_examples)
    eval_ds.stats["stratified"] = cfg.dataset.eval_stratified
    train_ds.stats["category_distribution"] = subset_distribution(train_examples)
    log(f"Tokenised: train {train_ds.stats['examples_used']}/{train_ds.stats['examples_in']} (skipped over {t.max_seq_length}: {train_ds.stats['skipped_over_length']}, truncated: {train_ds.stats['truncated']}, max observed {train_ds.stats['max_token_length_observed']}, median {train_ds.stats['median_token_length']}); eval subset {eval_ds.stats['examples_used']}/{eval_ds.stats['examples_in']}")

    peft_model, lora_info = load_lora_for_training(model, cfg.lora, cfg.init_adapter)
    if cfg.init_adapter:
        log(f"LoRA initialised from the saved adapter {cfg.init_adapter} (continuing earlier training)")
    log(f"LoRA: trainable {lora_info['trainable_parameters']:,} / {lora_info['total_parameters']:,} ({lora_info['trainable_percent']}%), targets {lora_info['target_module_counts']}")
    if t.gradient_checkpointing:
        peft_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        peft_model.enable_input_require_grads()

    max_steps = 1 if smoke else t.max_steps
    ckpt_dir = out_dir / "checkpoints"
    use_cpu = hw["device"] == "cpu"
    args = TrainingArguments(
        output_dir=str(ckpt_dir),
        learning_rate=t.learning_rate,
        num_train_epochs=t.num_train_epochs,
        max_steps=max_steps,
        per_device_train_batch_size=t.per_device_train_batch_size,
        per_device_eval_batch_size=t.per_device_eval_batch_size,
        gradient_accumulation_steps=1 if smoke else t.gradient_accumulation_steps,
        warmup_steps=0 if smoke else t.warmup_steps,
        weight_decay=t.weight_decay,
        lr_scheduler_type=t.lr_scheduler_type,
        logging_steps=1 if smoke else t.logging_steps,
        logging_first_step=True,
        eval_strategy="steps" if smoke else t.eval_strategy,
        eval_steps=1 if smoke else t.eval_steps,
        save_strategy="steps" if smoke else t.save_strategy,
        save_steps=1 if smoke else t.save_steps,
        save_total_limit=None if t.keep_all_checkpoints else t.save_total_limit,
        load_best_model_at_end=(t.eval_strategy != "no" and t.save_strategy == t.eval_strategy) or smoke,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        seed=t.seed,
        data_seed=t.seed,
        use_cpu=use_cpu,
        bf16=(hw["dtype"] == "bfloat16"),
        fp16=(hw["dtype"] == "float16"),
        dataloader_pin_memory=not use_cpu,
        dataloader_num_workers=0,
        remove_unused_columns=False,
        report_to=[],
        disable_tqdm=True,
        gradient_checkpointing=False,  # enabled on the PEFT model above
    )
    callbacks = [EarlyStoppingCallback(early_stopping_patience=t.early_stopping_patience)] if (t.early_stopping_patience > 0 and not smoke) else []
    deadline_cb = None
    if t.deadline_local and not smoke:
        deadline = resolve_deadline(t.deadline_local)
        reserve = t.deadline_reserve_seconds
        available = (deadline - datetime.now().astimezone()).total_seconds()
        log(f"Deadline {deadline.strftime('%Y-%m-%d %H:%M')} local: {available / 3600:.2f} h from now, reserving {reserve / 60:.0f} min for the final evaluation, save and inference check.")
        if available <= reserve:
            raise PipelineError(f"deadline {t.deadline_local} leaves {available / 60:.0f} min, less than the {reserve / 60:.0f} min reserve")
        deadline_cb = DeadlineCallback(deadline, reserve, log)
        callbacks.append(deadline_cb)
    trainer = Trainer(
        model=peft_model,
        args=args,
        data_collator=lambda batch: collate(batch, tokenizer.pad_token_id),
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        processing_class=tokenizer,
        callbacks=callbacks,
    )

    log("Evaluating the base model (no trained adapter yet) on the validation subset ...")
    base_eval = trainer.evaluate()
    log(f"  base eval_loss = {base_eval.get('eval_loss'):.4f}")

    log(f"Training: max_steps={max_steps} batch={t.per_device_train_batch_size} x accum={1 if smoke else t.gradient_accumulation_steps} lr={t.learning_rate} scheduler={t.lr_scheduler_type} eval every {args.eval_steps} steps")
    t0 = time.perf_counter()
    train_result = trainer.train()
    duration = time.perf_counter() - t0
    log(f"Training finished in {duration / 60:.1f} min: {train_result.metrics}")

    state = trainer.state
    last_eval = next((h for h in reversed(state.log_history) if "eval_loss" in h), None)
    best_is_last = bool(state.best_model_checkpoint) and last_eval is not None and Path(state.best_model_checkpoint).name == f"checkpoint-{last_eval.get('step')}"
    if best_is_last or smoke:
        final_eval = {"eval_loss": state.best_metric, "note": "selected checkpoint is the last evaluated one; its logged eval_loss is reused"}
    else:
        final_eval = trainer.evaluate()  # the reloaded best checkpoint differs from the last evaluated model
    log(f"  selected-checkpoint eval_loss = {final_eval.get('eval_loss'):.4f}")

    adapter_dir = out_dir / "adapter"
    trainer.model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(out_dir / "tokenizer"))
    history = list(state.log_history)
    train_losses = [h["loss"] for h in history if "loss" in h]
    eval_losses = [h["eval_loss"] for h in history if "eval_loss" in h]
    best_checkpoint = state.best_model_checkpoint
    best_metric = state.best_metric
    protected_after = protected_hashes(cfg.dataset.protected)
    if protected_after != protected_before:
        raise RuntimeError("protected evaluation datasets changed during training")

    summary = {
        "stage": STAGE,
        "mode": "smoke" if smoke else "full",
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_duration_seconds": round(duration, 1),
        "hardware": hw,
        "dependencies": dependency_versions(),
        "dataset_identity": identity,
        "protected_files_sha256": protected_after,
        "tokenization": {"train": train_ds.stats, "eval_subset": eval_ds.stats},
        "lora": lora_info,
        "training_arguments": {k: args.to_dict()[k] for k in ("learning_rate", "num_train_epochs", "max_steps", "per_device_train_batch_size", "gradient_accumulation_steps", "warmup_steps", "weight_decay", "lr_scheduler_type", "eval_steps", "save_steps", "save_total_limit", "seed", "use_cpu", "bf16", "fp16")},
        "steps_completed": state.global_step,
        "epochs_completed": round(float(state.epoch or 0.0), 4),
        "examples_seen": state.global_step * t.per_device_train_batch_size * (1 if smoke else t.gradient_accumulation_steps),
        "final_training_loss": train_losses[-1] if train_losses else None,
        "training_losses": train_losses,
        "eval_losses": eval_losses,
        "base_validation_loss": base_eval.get("eval_loss"),
        "best_validation_loss": best_metric,
        "selected_checkpoint_validation_loss": final_eval.get("eval_loss"),
        "best_checkpoint": Path(best_checkpoint).name if best_checkpoint else None,
        "adapter_dir": adapter_dir.as_posix(),
        "train_metrics": train_result.metrics,
        "deadline": deadline_cb.summary() if deadline_cb is not None else None,
    }
    _write_json(out_dir / "training_metrics.json", {"log_history": history, "base_eval": base_eval, "final_eval": final_eval})
    _write_json(out_dir / "training_summary.json", summary)
    _write_json(out_dir / "metadata.json", build_metadata(cfg, summary, identity, lora_info))
    (out_dir / "training_config.yaml").write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=False), encoding="utf-8")
    shutil.copyfile(cfg.dataset.manifest, out_dir / "dataset_manifest.json")
    (out_dir / "README.md").write_text(render_readme(cfg, summary), encoding="utf-8")

    # release the training model, then prove the saved adapter reloads and generates
    del trainer, peft_model, model
    log("Reloading the saved adapter on a fresh base model for the inference check ...")
    infer_model, ident = load_adapter_model(cfg.model, adapter_dir, merge=True, local_files_only=True)
    probe = val_examples[0]
    gen = GenerationConfig(max_new_tokens=96, do_sample=False, enable_thinking=False)
    artifact = inference_check(infer_model, tokenizer, example_messages(probe, t.prompt_format)[:-1], gen, model_id=cfg.model.id, identity=ident, out_path=out_dir / "inference_check.json")
    artifact["reference_answer"] = probe.answer
    artifact["example_id"] = probe.id
    _write_json(out_dir / "inference_check.json", artifact)
    log(f"Inference check: {artifact['generated_tokens']} tokens in {artifact['seconds']}s -> {artifact['generated_answer'][:120]!r}")
    summary["inference_check"] = {"example_id": probe.id, "generated_tokens": artifact["generated_tokens"], "seconds": artifact["seconds"]}
    _write_json(out_dir / "training_summary.json", summary)
    return summary


def finalize_from_checkpoints(cfg: FinetuneConfig, *, log: Log = print) -> dict[str, Any]:
    """Complete a run that was stopped after its last checkpoint was written:
    pick the best checkpoint from trainer_state.json, copy its adapter, write
    metadata and run the reload + inference check. No training happens."""
    from safetensors import safe_open

    out_dir = cfg.output_dir
    ckpt_dir = out_dir / "checkpoints"
    checkpoints = sorted((p for p in ckpt_dir.glob("checkpoint-*") if (p / "trainer_state.json").is_file()), key=lambda p: int(p.name.split("-")[1]))
    if not checkpoints:
        raise RuntimeError(f"no complete checkpoint under {ckpt_dir}")
    last = checkpoints[-1]
    state = json.loads((last / "trainer_state.json").read_text(encoding="utf-8"))
    history = list(state.get("log_history", []))
    evals = [h for h in history if "eval_loss" in h]
    best_name = Path(state["best_model_checkpoint"]).name if state.get("best_model_checkpoint") else None
    if best_name is None or not (ckpt_dir / best_name / "adapter_model.safetensors").is_file():
        best = min((h for h in evals if h.get("step")), key=lambda h: h["eval_loss"], default=None)
        best_name = f"checkpoint-{best['step']}" if best else last.name
    best_dir = ckpt_dir / best_name
    best_eval = next((h["eval_loss"] for h in evals if h.get("step") == int(best_name.split("-")[1])), state.get("best_metric"))
    base_eval = next((h for h in evals if not h.get("step") or h.get("epoch") == 0), {})
    if not base_eval:
        # the pre-training evaluation is logged before Trainer.train() resets its state,
        # so it lives only in the run log, not in trainer_state.json
        log_file = out_dir / "train.log"
        if log_file.is_file():
            m = re.search(r"base eval_loss = ([0-9.]+)", log_file.read_text(encoding="utf-8", errors="replace"))
            if m:
                base_eval = {"eval_loss": float(m.group(1)), "source": "train.log (pre-training evaluation)"}
    log(f"Checkpoints: {[c.name for c in checkpoints]}; best {best_name} (eval_loss {best_eval}); base eval_loss {base_eval.get('eval_loss')}")

    identity = verify_dataset(cfg.dataset)
    hw = hardware_report(cfg.model)
    t = cfg.training
    tokenizer = load_tokenizer(cfg.model, local_files_only=True)
    train_examples = load_split(cfg.dataset.train)
    val_examples = eval_subset(load_split(cfg.dataset.validation), cfg.dataset.eval_subset, cfg.dataset.seed, cfg.dataset.eval_stratified)
    train_ds = tokenize_examples(train_examples, tokenizer, t.max_seq_length, t.over_length_policy)
    eval_ds = tokenize_examples(val_examples, tokenizer, t.max_seq_length, t.over_length_policy)

    adapter_dir = out_dir / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    for name in ("adapter_config.json", "adapter_model.safetensors", "README.md"):
        if (best_dir / name).is_file():
            shutil.copyfile(best_dir / name, adapter_dir / name)
    tokenizer.save_pretrained(str(out_dir / "tokenizer"))
    with safe_open(str(adapter_dir / "adapter_model.safetensors"), framework="pt") as f:
        trainable = sum(math.prod(f.get_slice(k).get_shape()) for k in f.keys())
    infer_model, ident = load_adapter_model(cfg.model, adapter_dir, merge=True, local_files_only=True)
    total_base = sum(p.numel() for p in infer_model.parameters())
    lora_info = {
        "trainable_parameters": trainable,
        "total_parameters": total_base + trainable,
        "trainable_percent": round(100.0 * trainable / (total_base + trainable), 3),
        "base_parameters_frozen": True,
        "target_module_counts": "see adapter_config.json (verified at training time)",
        "lora": {"r": cfg.lora.r, "alpha": cfg.lora.alpha, "dropout": cfg.lora.dropout, "bias": cfg.lora.bias, "task_type": cfg.lora.task_type, "target_modules": list(cfg.lora.target_modules)},
    }
    started_ts = ckpt_dir.stat().st_ctime
    finished_ts = (last / "trainer_state.json").stat().st_mtime
    train_losses = [h["loss"] for h in history if "loss" in h]
    protected_after = protected_hashes(cfg.dataset.protected)
    summary = {
        "stage": STAGE,
        "mode": "full (finalized from checkpoints after a manual stop following the last checkpoint)",
        "started_utc": datetime.fromtimestamp(started_ts, tz=timezone.utc).isoformat(timespec="seconds"),
        "finished_utc": datetime.fromtimestamp(finished_ts, tz=timezone.utc).isoformat(timespec="seconds"),
        "training_duration_seconds": round(finished_ts - started_ts, 1),
        "training_duration_note": "checkpoint directory creation to last checkpoint write; includes the initial base-model validation pass and the checkpoint validation passes",
        "hardware": hw,
        "dependencies": dependency_versions(),
        "dataset_identity": identity,
        "protected_files_sha256": protected_after,
        "tokenization": {"train": train_ds.stats, "eval_subset": eval_ds.stats},
        "lora": lora_info,
        "training_arguments": {"learning_rate": t.learning_rate, "num_train_epochs": t.num_train_epochs, "max_steps": t.max_steps, "per_device_train_batch_size": t.per_device_train_batch_size, "gradient_accumulation_steps": t.gradient_accumulation_steps, "warmup_steps": t.warmup_steps, "weight_decay": t.weight_decay, "lr_scheduler_type": t.lr_scheduler_type, "eval_steps": t.eval_steps, "save_steps": t.save_steps, "save_total_limit": t.save_total_limit, "seed": t.seed, "use_cpu": hw["device"] == "cpu", "bf16": hw["dtype"] == "bfloat16", "fp16": hw["dtype"] == "float16"},
        "steps_completed": int(state.get("global_step", 0)),
        "epochs_completed": round(float(state.get("epoch") or 0.0), 4),
        "examples_seen": int(state.get("global_step", 0)) * t.per_device_train_batch_size * t.gradient_accumulation_steps,
        "final_training_loss": train_losses[-1] if train_losses else None,
        "training_losses": train_losses,
        "eval_losses": [h["eval_loss"] for h in evals if h.get("step")],
        "base_validation_loss": base_eval.get("eval_loss"),
        "best_validation_loss": best_eval,
        "selected_checkpoint_validation_loss": best_eval,
        "best_checkpoint": best_name,
        "adapter_dir": adapter_dir.as_posix(),
        "train_metrics": {"note": "process stopped after the last checkpoint; Trainer end-of-run metrics were not produced"},
    }
    _write_json(out_dir / "training_metrics.json", {"log_history": history, "base_eval": base_eval, "final_eval": {"eval_loss": best_eval, "note": f"logged eval_loss of the selected {best_name}"}})
    _write_json(out_dir / "training_summary.json", summary)
    _write_json(out_dir / "metadata.json", build_metadata(cfg, summary, identity, lora_info))
    (out_dir / "training_config.yaml").write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=False), encoding="utf-8")
    shutil.copyfile(cfg.dataset.manifest, out_dir / "dataset_manifest.json")
    (out_dir / "README.md").write_text(render_readme(cfg, summary), encoding="utf-8")

    probe = val_examples[0]
    gen = GenerationConfig(max_new_tokens=96, do_sample=False, enable_thinking=False)
    artifact = inference_check(infer_model, tokenizer, to_messages(probe)[:-1], gen, model_id=cfg.model.id, identity=ident, out_path=out_dir / "inference_check.json")
    artifact["reference_answer"] = probe.answer
    artifact["example_id"] = probe.id
    _write_json(out_dir / "inference_check.json", artifact)
    log(f"Inference check: {artifact['generated_tokens']} tokens in {artifact['seconds']}s -> {artifact['generated_answer'][:120]!r}")
    summary["inference_check"] = {"example_id": probe.id, "generated_tokens": artifact["generated_tokens"], "seconds": artifact["seconds"]}
    _write_json(out_dir / "training_summary.json", summary)
    return summary


def build_metadata(cfg: FinetuneConfig, summary: dict[str, Any], identity: dict[str, Any], lora_info: dict[str, Any]) -> dict[str, Any]:
    t = cfg.training
    return {
        "stage": STAGE,
        "model": cfg.model_name,
        "base_model_id": cfg.model.id,
        "method": "LoRA",
        "dataset": {
            "train_examples": identity["files"]["train"]["examples"],
            "validation_examples": identity["files"]["validation"]["examples"],
            "test_examples": identity["files"]["test"]["examples"],
            "seed": identity.get("seed"),
            "hash": identity["dataset_sha256"],
            "version": identity.get("dataset_version"),
            "train_examples_used": summary["tokenization"]["train"]["examples_used"],
            "validation_subset_used": summary["tokenization"]["eval_subset"]["examples_used"],
        },
        "lora": {"r": cfg.lora.r, "alpha": cfg.lora.alpha, "dropout": cfg.lora.dropout, "target_modules": list(cfg.lora.target_modules), "trainable_parameters": lora_info["trainable_parameters"], "total_parameters": lora_info["total_parameters"]},
        "training": {
            "learning_rate": t.learning_rate,
            "epochs": summary["epochs_completed"],
            "max_steps": summary["training_arguments"]["max_steps"],
            "steps_completed": summary["steps_completed"],
            "batch_size": t.per_device_train_batch_size,
            "gradient_accumulation": summary["training_arguments"]["gradient_accumulation_steps"],
            "max_seq_length": t.max_seq_length,
            "scheduler": t.lr_scheduler_type,
            "warmup_steps": summary["training_arguments"]["warmup_steps"],
            "duration_seconds": summary["training_duration_seconds"],
        },
        "best_checkpoint": summary["best_checkpoint"],
        "best_validation_loss": summary["best_validation_loss"],
        "base_validation_loss": summary["base_validation_loss"],
        "final_training_loss": summary["final_training_loss"],
        "device": summary["hardware"]["device"],
        "dtype": summary["hardware"]["dtype"],
        "dependencies": summary["dependencies"],
        "timestamp": summary["finished_utc"],
    }


def render_readme(cfg: FinetuneConfig, s: dict[str, Any]) -> str:
    return (
        f"# Stage 12 LoRA adapter ({s['mode']} run)\n\n"
        f"Base model: `{cfg.model.id}` | method: LoRA r={cfg.lora.r} alpha={cfg.lora.alpha} dropout={cfg.lora.dropout} on {', '.join(cfg.lora.target_modules)}\n\n"
        f"Dataset: Stage 11 `{s['dataset_identity']['dataset_version']}` sha256 `{s['dataset_identity']['dataset_sha256']}` (train/validation/test {s['dataset_identity']['files']['train']['examples']}/{s['dataset_identity']['files']['validation']['examples']}/{s['dataset_identity']['files']['test']['examples']}); test split never read.\n\n"
        f"Run: {s['steps_completed']} optimizer steps ({s['examples_seen']} examples, {s['epochs_completed']} epochs) on {s['hardware']['device']} ({s['hardware']['dtype']}) in {s['training_duration_seconds'] / 60:.1f} min; "
        f"validation loss base {s['base_validation_loss']} -> selected checkpoint {s['selected_checkpoint_validation_loss']} (best {s['best_validation_loss']}, {s['best_checkpoint']}).\n\n"
        "Files: `adapter/` (PEFT adapter weights + config), `tokenizer/`, `training_config.yaml`, `training_metrics.json` (log history), "
        "`training_summary.json`, `metadata.json`, `dataset_manifest.json` (copy of the Stage 11 manifest), `inference_check.json`, `checkpoints/`.\n\n"
        "Load: `from regulus.finetune import load_adapter_model` or `python scripts/evaluate_stage12.py`.\n"
    )
