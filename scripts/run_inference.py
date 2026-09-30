"""Smoke test: load the configured Qwen model and generate one response.

Usage:
    python scripts/run_inference.py
    python scripts/run_inference.py --prompt "What does the FDA regulate?"
    python scripts/run_inference.py --max-new-tokens 64 --greedy

Exit code 0 means the model loaded and produced text.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from regulus.config import ConfigError, load_settings
from regulus.inference import generate
from regulus.model import ModelLoadError, environment_info, load_model, load_tokenizer

DEFAULT_PROMPT = "In one sentence, what is the purpose of the U.S. Food and Drug Administration?"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="user message to send to the model")
    parser.add_argument("--config", default=None, help="path to a YAML config (default: configs/model.yaml)")
    parser.add_argument("--max-new-tokens", type=int, default=None, help="override generation.max_new_tokens")
    parser.add_argument("--greedy", action="store_true", help="disable sampling (deterministic output)")
    parser.add_argument("--thinking", action="store_true", help="enable Qwen3 thinking mode (slow on CPU)")
    parser.add_argument("--offline", action="store_true", help="fail instead of downloading if not cached")
    parser.add_argument("-v", "--verbose", action="store_true", help="show library logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print("=== Environment ===")
    for key, value in environment_info().items():
        print(f"{key:>16}: {value}")

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"\nCONFIG ERROR: {exc}", file=sys.stderr)
        return 2

    gen = settings.generation
    if args.max_new_tokens is not None:
        gen.max_new_tokens = args.max_new_tokens
    if args.greedy:
        gen.do_sample = False
    if args.thinking:
        gen.enable_thinking = True

    print("\n=== Model ===")
    print(f"{'model id':>16}: {settings.model.id}")
    print(f"{'cache dir':>16}: {settings.model.cache_dir}")

    try:
        t0 = time.perf_counter()
        tokenizer = load_tokenizer(settings.model, local_files_only=args.offline)
        model = load_model(settings.model, local_files_only=args.offline)
        load_seconds = time.perf_counter() - t0
    except ModelLoadError as exc:
        print(f"\nMODEL LOAD ERROR: {exc}", file=sys.stderr)
        return 1

    n_params = sum(p.numel() for p in model.parameters())
    print(f"{'device':>16}: {model.device}")
    print(f"{'dtype':>16}: {model.dtype}")
    print(f"{'parameters':>16}: {n_params / 1e6:.0f}M")
    print(f"{'load time':>16}: {load_seconds:.1f}s")
    print(f"{'thinking':>16}: {gen.enable_thinking}")
    print(f"{'sampling':>16}: {gen.do_sample}")

    print("\n=== Prompt ===")
    print(args.prompt)
    print("\nGenerating...", flush=True)
    try:
        result = generate(model, tokenizer, args.prompt, gen)
    except Exception as exc:  # any generation failure is a smoke-test failure
        print(f"\nGENERATION ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("\n=== Response ===")
    print(result.response)
    print("\n=== Stats ===")
    print(f"{'prompt tokens':>16}: {result.prompt_tokens}")
    print(f"{'new tokens':>16}: {result.generated_tokens}")
    print(f"{'generation':>16}: {result.seconds:.1f}s ({result.tokens_per_second:.2f} tok/s)")
    print(f"\nOK: inference ran on {model.device.type.upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
