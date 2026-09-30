"""Stage 12: run the existing Stage 7 RAG evaluation with the trained adapter.

Thin wrapper around scripts/evaluate_baseline.py (same dataset, retriever,
prompt, decoding and metrics); it only fixes the adapter, the run label and
a Stage 12-specific output directory.

Usage:
    python scripts/evaluate_stage12.py                       # adapter from models/qwen3-0.6b-lora/stage12_v1/adapter
    python scripts/evaluate_stage12.py --base                # same pipeline, base model (fresh comparison run)
    python scripts/evaluate_stage12.py --adapter PATH --limit 3
Any other evaluate_baseline.py option can be appended (e.g. --ids, --offline).
Results: data/evaluation/results/stage12_v1/<label>_<timestamp>_<run_id>.json
"""

from __future__ import annotations

import sys
from pathlib import Path

from regulus.config import PROJECT_ROOT

DEFAULT_ADAPTER = PROJECT_ROOT / "models" / "qwen3-0.6b-lora" / "stage12_v1" / "adapter"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "results" / "stage12_v1"


def main() -> int:
    argv = sys.argv[1:]
    base = "--base" in argv
    argv = [a for a in argv if a != "--base"]
    if "--adapter" not in argv and not base:
        argv += ["--adapter", str(DEFAULT_ADAPTER)]
    if "--output-dir" not in argv:
        argv += ["--output-dir", str(DEFAULT_OUTPUT)]
    if "--pipeline" not in argv:
        argv += ["--pipeline", "rag"]
    if "--run-label" not in argv:
        argv += ["--run-label", "rag-stage12-base" if base else "rag-stage12-lora"]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import evaluate_baseline

    sys.argv = [sys.argv[0], *argv]
    return evaluate_baseline.main()


if __name__ == "__main__":
    sys.exit(main())
