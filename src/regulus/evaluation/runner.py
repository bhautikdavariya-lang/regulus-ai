"""Pipeline-agnostic evaluation loop.

The runner knows nothing about Qwen. It takes an ``answer_fn`` that maps a
question string to a GenerationResult, so the same loop serves the base
model now and RAG / fine-tuned pipelines later.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from regulus.config import PROJECT_ROOT, GenerationConfig, Settings
from regulus.evaluation.dataset import EvalDataset, EvalExample
from regulus.evaluation.results import EvaluationRun, QuestionResult, aggregate
from regulus.inference.generate import GenerationResult

AnswerFn = Callable[[str], GenerationResult]
ProgressFn = Callable[[int, int, QuestionResult], None]

_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s'\"<>|]+")
_POSIX_PATH_RE = re.compile(r"(?<![\w.])/(?:[\w.-]+/)+[\w.-]*")
_MAX_ERROR_LEN = 500


def sanitize_error(exc: BaseException) -> str:
    """Short error text safe to store: type + message, file-system paths removed."""
    text = f"{type(exc).__name__}: {exc}".strip()
    for known in (str(Path.home()), str(PROJECT_ROOT)):
        if known:
            text = text.replace(known, "<redacted>")
    text = _WIN_PATH_RE.sub("<path>", text)
    text = _POSIX_PATH_RE.sub("<path>", text)
    if len(text) > _MAX_ERROR_LEN:
        text = text[:_MAX_ERROR_LEN] + "..."
    return text


def new_run_id() -> str:
    return uuid.uuid4().hex[:8]


def build_run_metadata(
    *,
    run_id: str,
    pipeline: str,
    started_at: datetime,
    settings: Settings,
    gen: GenerationConfig,
    dataset: EvalDataset,
    device: str,
    dtype: str,
    model_revision: str | None,
    environment: dict[str, Any],
    seed: int | None,
    num_questions: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything needed to reproduce or compare this run. No secrets, no paths.
    `extra` carries pipeline-specific configuration (e.g. RAG retrieval and
    context limits) under its own keys."""
    meta = {
        "evaluation_run_id": run_id,
        "pipeline": pipeline,
        "timestamp_utc": started_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "model_id": settings.model.id,
        "model_revision": model_revision,
        "device": device,
        "dtype": dtype,
        "decoding_mode": "sampling" if gen.do_sample else "greedy",
        "seed": seed,
        "generation": {
            "max_new_tokens": gen.max_new_tokens,
            "do_sample": gen.do_sample,
            "temperature": gen.temperature if gen.do_sample else None,
            "top_p": gen.top_p if gen.do_sample else None,
            "top_k": gen.top_k if gen.do_sample else None,
            "enable_thinking": gen.enable_thinking,
        },
        "dataset": {
            "name": dataset.name,
            "path": dataset.relative_path(),
            "sha256": dataset.sha256,
            "num_examples": len(dataset),
        },
        "num_questions": num_questions,
        "environment": {
            key: environment.get(key)
            for key in ("python", "platform", "torch", "transformers", "cuda_available", "cuda_version", "gpu_name")
        },
    }
    if extra:
        meta.update(extra)
    return meta


def evaluate_example(ex: EvalExample, answer_fn: AnswerFn) -> QuestionResult:
    try:
        out = answer_fn(ex.question)
    except Exception as exc:  # one bad question must not end the run
        return QuestionResult.from_example(ex, status="failed", error=sanitize_error(exc))
    return QuestionResult.from_example(
        ex,
        status="completed",
        model_answer=out.response,
        generation_seconds=round(out.seconds, 3),
        input_tokens=out.prompt_tokens,
        output_tokens=out.generated_tokens,
        tokens_per_second=round(out.tokens_per_second, 3),
        diagnostics=getattr(out, "diagnostics", None) or None,
        citations=getattr(out, "citations", None) or None,
    )


def run_evaluation(
    examples: list[EvalExample],
    answer_fn: AnswerFn,
    run_metadata: dict[str, Any],
    on_progress: ProgressFn | None = None,
) -> EvaluationRun:
    """Answer every example, never abort on a single failure, return the full run."""
    started = time.perf_counter()
    results: list[QuestionResult] = []
    for index, ex in enumerate(examples, start=1):
        result = evaluate_example(ex, answer_fn)
        results.append(result)
        if on_progress:
            on_progress(index, len(examples), result)
    run = dict(run_metadata)
    run["duration_seconds"] = round(time.perf_counter() - started, 3)
    return EvaluationRun(run=run, results=results, summary=aggregate(results))
