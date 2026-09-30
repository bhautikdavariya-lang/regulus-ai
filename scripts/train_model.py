"""Stage 12: train the first Qwen3-0.6B LoRA adapter on the Stage 11 dataset.

Usage:
    python scripts/train_model.py --smoke                          # tiny end-to-end check (temporary output)
    python scripts/train_model.py --config configs/model_training.yaml
    python scripts/train_model.py --max-steps 40 --output-dir models/qwen3-0.6b-lora/stage12_v1

Training only happens through this command. The database is never touched;
the test split is never read.
"""

from __future__ import annotations

import argparse
import logging
import sys

from regulus.finetune import DatasetIdentityError, FinetuneConfigError, LoraTargetError, load_finetune_config
from regulus.finetune.train import run_training
from regulus.model import ModelLoadError


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None, help="YAML (default: configs/model_training.yaml)")
    p.add_argument("--smoke", action="store_true", help="4 examples, 1 step, temporary output directory")
    p.add_argument("--finalize", action="store_true", help="no training: select the best checkpoint of a stopped run, copy its adapter, write metadata, run the reload + inference check")
    p.add_argument("--max-steps", type=int, default=None, help="override training.max_steps (-1 = full epochs)")
    p.add_argument("--eval-subset", type=int, default=None, help="override dataset.eval_subset")
    p.add_argument("--output-dir", default=None, help="override output.directory")
    p.add_argument("--init-adapter", default=None, help="continue training from this saved adapter instead of fresh LoRA weights")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--allow-unverified-key", action="store_true",
                   help="bypass the acceptance-benchmark key gate; for smoke tests "
                        "only, never for a real training run")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        # line-buffered so progress lines reach a redirected log file immediately
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if not args.allow_unverified_key:
        from pathlib import Path as _Path

        from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
        from regulus.evaluation.acceptance_gate import AcceptanceGateError, require_locked_key

        workbook = _Path(DEFAULT_WORKBOOK)
        if workbook.is_file():
            try:
                require_locked_key(load_acceptance_benchmark(workbook).benchmark_key, "Training")
            except AcceptanceGateError as exc:
                print("BLOCKED", file=sys.stderr)
                print(exc, file=sys.stderr)
                return 3

    try:
        cfg = load_finetune_config(args.config, max_steps=args.max_steps, eval_subset=args.eval_subset, output_dir=args.output_dir, init_adapter=args.init_adapter)
    except FinetuneConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Stage 12 {'SMOKE TEST' if args.smoke else 'training run'}: config={cfg.source} model={cfg.model.id} output={(cfg.smoke_dir if args.smoke else cfg.output_dir)}")

    def log(msg: str) -> None:
        print(msg, flush=True)

    try:
        if args.finalize:
            from regulus.finetune.train import finalize_from_checkpoints

            summary = finalize_from_checkpoints(cfg, log=log)
        else:
            summary = run_training(cfg, smoke=args.smoke, log=log)
    except DatasetIdentityError as exc:
        print(f"DATASET IDENTITY ERROR: {exc} -- refusing to train on data that is not the Stage 11 artifact", file=sys.stderr)
        return 3
    except (LoraTargetError, ModelLoadError) as exc:
        print(f"MODEL ERROR: {exc}", file=sys.stderr)
        return 1
    print()
    print(f"steps={summary['steps_completed']} examples_seen={summary['examples_seen']} duration={summary['training_duration_seconds'] / 60:.1f} min")
    print(f"validation loss: base={summary['base_validation_loss']} best={summary['best_validation_loss']} ({summary['best_checkpoint']}) selected={summary['selected_checkpoint_validation_loss']}")
    print(f"final training loss: {summary['final_training_loss']}")
    print(f"adapter: {summary['adapter_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
