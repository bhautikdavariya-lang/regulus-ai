"""Measure real LoRA training throughput on this machine before committing to
a long run, and report what training budgets are practically reachable.

Stage 13 requires a training budget stated in epochs rather than an arbitrary
step count. On CPU that is only meaningful if the throughput is known, so this
script times actual optimizer steps on actual dataset examples.

Usage:
    python scripts/benchmark_training.py --config configs/model_training_v2.yaml
    python scripts/benchmark_training.py --steps 3 --no-checkpointing
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

import torch

from regulus.finetune import load_finetune_config
from regulus.finetune.data import collate, load_split, tokenize_examples
from regulus.finetune.lora import attach_lora
from regulus.finetune.train import hardware_report
from regulus.model import load_model, load_tokenizer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--steps", type=int, default=3, help="optimizer steps to time")
    p.add_argument("--no-checkpointing", action="store_true", help="time without gradient checkpointing")
    p.add_argument("--max-seq-length", type=int, default=None, help="override for the measurement")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    cfg = load_finetune_config(args.config, max_seq_length=args.max_seq_length)
    t = cfg.training
    hw = hardware_report(cfg.model)
    print(f"Device {hw['device']} / {hw['dtype']} | GPU {hw.get('gpu_name')} | threads {hw['cpu_threads']} | RAM free {hw.get('ram_available_gb')} GB")

    tokenizer = load_tokenizer(cfg.model, local_files_only=True)
    examples = load_split(cfg.dataset.train)
    ds = tokenize_examples(examples, tokenizer, t.max_seq_length, t.over_length_policy)
    s = ds.stats
    print(f"Dataset: {s['examples_used']} usable of {s['examples_in']} | median {s['median_token_length']} p95 {s['p95_token_length']} max {s['max_token_length_observed']} tokens")
    print(f"Skipped over {t.max_seq_length}: {s['skipped_over_length']} ({100 * s['skipped_over_length'] / max(s['examples_in'], 1):.1f}%)")

    model = load_model(cfg.model, local_files_only=True)
    model.config.use_cache = False
    peft_model, info = attach_lora(model, cfg.lora)
    checkpointing = not args.no_checkpointing and t.gradient_checkpointing
    if checkpointing:
        peft_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        peft_model.enable_input_require_grads()
    peft_model.train()
    print(f"LoRA trainable {info['trainable_parameters']:,} ({info['trainable_percent']}%) | gradient checkpointing {'on' if checkpointing else 'off'}")

    opt = torch.optim.AdamW([p for p in peft_model.parameters() if p.requires_grad], lr=t.learning_rate)
    accum = t.gradient_accumulation_steps
    # walk the dataset in order so the measured examples are representative
    times, tokens = [], []
    idx = 0
    peak_rss = 0.0
    try:
        import psutil
        import os

        proc = psutil.Process(os.getpid())
    except Exception:
        proc = None
    for step in range(args.steps):
        t0 = time.perf_counter()
        step_tokens = 0
        for _ in range(accum):
            batch = collate([ds[idx % len(ds)]], tokenizer.pad_token_id)
            idx += 1
            step_tokens += int(batch["input_ids"].numel())
            loss = peft_model(**batch).loss / accum
            loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        dt = time.perf_counter() - t0
        times.append(dt)
        tokens.append(step_tokens)
        if proc:
            peak_rss = max(peak_rss, proc.memory_info().rss / 1e9)
        print(f"  step {step + 1}: {dt:.1f}s for {step_tokens} tokens ({step_tokens / dt:.0f} tok/s)")

    median = statistics.median(times)
    per_example = median / accum
    tok_s = statistics.median(t_ / d for t_, d in zip(tokens, times))
    print()
    print(f"Median step: {median:.1f}s ({per_example:.1f}s per example, {tok_s:.0f} tokens/s) | peak RSS {peak_rss:.2f} GB")
    usable = s["examples_used"]
    steps_per_epoch = usable / (t.per_device_train_batch_size * accum)
    print(f"One epoch = {steps_per_epoch:.0f} steps = {steps_per_epoch * median / 3600:.1f} hours")
    print()
    print("Reachable budgets on this machine:")
    for hours in (2, 4, 8, 12, 24):
        steps = int(hours * 3600 / median)
        seen = steps * t.per_device_train_batch_size * accum
        print(f"  {hours:>3} h -> {steps:>5} steps, {seen:>6} examples, {seen / usable:.3f} epochs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
