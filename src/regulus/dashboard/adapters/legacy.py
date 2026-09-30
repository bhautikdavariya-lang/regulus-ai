"""Adapter for the legacy evaluation result files.

`data/evaluation/results/*.json` holds two different kinds of run, both
written by the older evaluation scripts and both shaped
`{schema_version, run, summary, results}`:

* **answer evaluations** (`baseline_*`, `rag*`) ran the model over a question
  set and recorded an answer, timings, token counts and, for some runs, a
  human reviewer's score;
* **retrieval evaluations** (`retrieval-*`) ran no model at all and recorded
  recall at k, mean reciprocal rank and per-query rankings.

They are kept in one adapter because they share a file shape, and kept
distinct inside it because they measure different things. A retrieval run is
not a weaker answer run: it has no answer model, and its benchmark is a
different file, so the comparison rules will refuse to put the two side by
side.

These runs are the project's history. They are read exactly as they are;
nothing is recomputed into a modern metric it never measured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import metrics as M
from ..schemas import (
    COMPLETE,
    INCOMPLETE,
    KIND_EVALUATION,
    MISSING,
    NOT_APPLICABLE,
    BenchmarkIdentity,
    EvaluationRun,
    MetricResult,
    ModelIdentity,
    QuestionResult,
    stable_id,
)

SCHEMA_ANSWER = "legacy-answer/v1"
SCHEMA_RETRIEVAL = "legacy-retrieval/v1"


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


def _is_retrieval(payload: dict[str, Any]) -> bool:
    """A retrieval run is the one that reports recall, and names no model."""
    summary = payload.get("summary") or {}
    return "recall@1" in summary or "mrr" in summary


# -------------------------------------------------------------------- detect


def detect(path: str | Path) -> bool:
    """True for a single legacy evaluation JSON file."""
    file = Path(path)
    if not file.is_file() or file.suffix != ".json":
        return False
    payload = _json(file)
    if not isinstance(payload, dict):
        return False
    if not all(k in payload for k in ("run", "summary", "results")):
        return False
    return isinstance(payload.get("run"), dict) and "evaluation_run_id" in payload["run"]


# ------------------------------------------------------------------ identity


def _model(run: dict[str, Any], retrieval: bool) -> ModelIdentity:
    if retrieval:
        # Not a gap in the record: a retrieval evaluation has no answer model.
        return ModelIdentity(base_model_id=NOT_APPLICABLE)
    # These runs do record their adapter, which is what makes them traceable
    # back to the training run that produced it.
    adapter = run.get("adapter") or {}
    return ModelIdentity(
        base_model_id=str(run.get("model_id") or adapter.get("base_model_name_or_path") or "unknown"),
        revision=run.get("model_revision"),
        adapter_id=adapter.get("adapter_name"),
        adapter_path=adapter.get("adapter_dir"),
        checkpoint=adapter.get("best_checkpoint"),
        dtype=run.get("dtype"),
        device=run.get("device"),
    )


def _benchmark(run: dict[str, Any]) -> BenchmarkIdentity:
    dataset = run.get("dataset") or {}
    return BenchmarkIdentity(
        benchmark_id=str(dataset.get("name") or Path(str(dataset.get("path") or "unknown")).stem),
        path=dataset.get("path"),
        sha256=dataset.get("sha256"),
        questions=dataset.get("num_examples") or dataset.get("num_queries") or run.get("num_questions"),
    )


# ------------------------------------------------------------------- metrics


def _mean(values: list[float]) -> float | None:
    clean = [v for v in values if isinstance(v, (int, float))]
    return round(sum(clean) / len(clean), 4) if clean else None


def _answer_metrics(summary: dict, results: list[dict], problems: list[str]) -> list[MetricResult]:
    total = summary.get("total") or len(results)
    completed = [r for r in results if r.get("status") == "completed"]
    out: list[MetricResult] = [
        M.ratio_metric("completion_rate", len(completed), total,
                       stored=None if not total else (summary.get("completed") or 0) / total,
                       source="summary.completed"),
        M.make_metric("failed_count", float(len(results) - len(completed)),
                      numerator=len(results) - len(completed), denominator=total, source="summary.failed"),
        M.make_metric("questions_evaluated", float(len(results)), numerator=len(results), source="results[]"),
    ]

    generated = _mean([r.get("output_tokens") for r in completed])
    prompt = _mean([r.get("input_tokens") for r in completed])
    seconds = _mean([r.get("generation_seconds") for r in completed])
    throughput = _mean([r.get("tokens_per_second") for r in completed])
    for key, value, stored in (
        ("avg_generated_tokens", generated, summary.get("avg_output_tokens")),
        ("avg_prompt_tokens", prompt, summary.get("avg_input_tokens")),
        ("avg_generation_seconds", seconds, summary.get("avg_generation_seconds")),
        ("tokens_per_second", throughput, summary.get("avg_tokens_per_second")),
    ):
        shown = stored if stored is not None else value
        note = None
        status = None
        if shown is None:
            status, note = MISSING, "not recorded by this run"
        elif value is not None and stored is not None and abs(stored - value) > max(0.05, abs(stored) * 0.02):
            status = "inconsistent"
            note = f"stored value {stored} disagrees with {value} recomputed from the per-question records"
        out.append(M.make_metric(key, shown, source="summary", status=status, note=note))

    manual = summary.get("manual_evaluation") or {}
    scored = manual.get("scored")
    if manual.get("mean_score") is not None:
        out.append(M.make_metric(
            "manual_score_mean", manual.get("mean_score"),
            numerator=None, denominator=scored, source="summary.manual_evaluation",
            note="a human reviewer's judgment, not a measurement; not comparable across reviewers",
        ))
        reviewers = sorted({
            str(_get(r, "manual_evaluation", "reviewer"))
            for r in results if _get(r, "manual_evaluation", "reviewer")
        })
        if reviewers:
            problems.append(
                "this run carries manual reviewer scores, entered by "
                + "; ".join(reviewers)
                + ". They are recorded for provenance and must not be compared across runs scored by different people."
            )
    return out


def _retrieval_metrics(summary: dict, results: list[dict]) -> list[MetricResult]:
    scored = summary.get("scored")
    out: list[MetricResult] = []
    for key, stored_key, k in (
        ("recall_at_1", "recall@1", 1), ("recall_at_3", "recall@3", 3),
        ("recall_at_5", "recall@5", 5), ("recall_at_10", "recall@10", 10),
    ):
        hits = None
        pool = [r for r in results if not r.get("negative_control")]
        if pool:
            hits = sum(1 for r in pool if isinstance(r.get("first_hit_rank"), int) and r["first_hit_rank"] <= k)
        out.append(M.ratio_metric(key, hits, len(pool) or scored, stored=summary.get(stored_key), source="summary"))

    ranks = [r.get("first_hit_rank") for r in results if not r.get("negative_control")]
    reciprocal = _mean([1.0 / r if isinstance(r, int) and r > 0 else 0.0 for r in ranks])
    stored_mrr = summary.get("mrr")
    status = note = None
    if stored_mrr is not None and reciprocal is not None and abs(stored_mrr - reciprocal) > 0.005:
        status, note = "inconsistent", f"stored value {stored_mrr} disagrees with {reciprocal} recomputed from the per-query ranks"
    out.append(M.make_metric("mrr", stored_mrr if stored_mrr is not None else reciprocal,
                             denominator=len(ranks) or None, source="summary", status=status, note=note))

    controls = [r for r in results if r.get("negative_control")]
    if controls or summary.get("negative_controls"):
        out.append(M.ratio_metric(
            "negative_control_pass",
            sum(1 for r in controls if r.get("negative_control_passed")) if controls else summary.get("negative_controls_passed"),
            len(controls) or summary.get("negative_controls"), source="summary",
        ))
    out.append(M.make_metric("retrieval_queries", float(len(results)), numerator=len(results), source="results[]"))

    for key, stored_key, values in (
        ("retrieval_latency_avg", "avg_total_ms", [r.get("total_ms") for r in results]),
        ("retrieval_latency_max", "max_total_ms", [r.get("total_ms") for r in results]),
    ):
        stored_ms = summary.get(stored_key)
        out.append(M.make_metric(
            key, None if stored_ms is None else round(stored_ms / 1000.0, 3), source="summary",
            status=None if stored_ms is not None else MISSING,
            note=None if stored_ms is None else f"converted from {stored_ms} ms recorded by the run",
        ))
    return out


# ----------------------------------------------------------------- questions


def _answer_questions(results: list[dict]) -> tuple[QuestionResult, ...]:
    out = []
    for r in results:
        manual = r.get("manual_evaluation") or {}
        out.append(QuestionResult(
            id=str(r.get("question_id")),
            question=str(r.get("question") or ""),
            category=r.get("category"),
            expected_behavior=r.get("expected_behavior"),
            generated=r.get("status") == "completed",
            skipped_reason=None if r.get("status") == "completed" else (r.get("error") or r.get("status")),
            # The legacy runs had no repair layer: the answer the model
            # produced is the answer that was shown. Recording it as both raw
            # and final would invent a distinction the run never made, so
            # only the raw answer is populated.
            answer_raw=r.get("model_answer"),
            answer_final=None,
            citations=list(r.get("citations") or []),
            # an unrecorded time stays unrecorded; it is never a 0 ms answer
            latency_ms=({"generation_ms": r["generation_seconds"] * 1000.0, "total_ms": r["generation_seconds"] * 1000.0}
                        if isinstance(r.get("generation_seconds"), (int, float)) else {}),
            tokens={"prompt_tokens": r.get("input_tokens"), "generated": r.get("output_tokens"),
                    "tokens_per_second": r.get("tokens_per_second")},
            extra={
                "reference_answer": r.get("reference_answer"),
                "evaluation_notes": r.get("evaluation_notes"),
                "quality_score": r.get("quality_score"),
                "manual_evaluation": manual,
                "diagnostics": r.get("diagnostics"),
                "error": r.get("error"),
                "no_repair_layer": True,
            },
        ))
    return tuple(out)


def _retrieval_questions(results: list[dict]) -> tuple[QuestionResult, ...]:
    out = []
    for r in results:
        rank = r.get("first_hit_rank")
        out.append(QuestionResult(
            id=str(r.get("id")),
            question=str(r.get("query") or ""),
            category=r.get("category"),
            expected_requirements=tuple(r.get("expected") or []),
            generated=False,
            skipped_reason="retrieval-only evaluation: no answer was generated",
            correct_raw=(bool(r.get("negative_control_passed")) if r.get("negative_control")
                         else (isinstance(rank, int) and rank == 1)),
            latency_ms={"total_ms": r.get("total_ms")} if r.get("total_ms") is not None else {},
            extra={
                "first_hit_rank": rank,
                "negative_control": r.get("negative_control"),
                "negative_control_passed": r.get("negative_control_passed"),
                "top_results": r.get("top_results") or [],
                "timings_ms": r.get("timings_ms") or {},
                "retrieval": r.get("retrieval") or {},
                "error": r.get("error"),
            },
        ))
    return tuple(out)


# ---------------------------------------------------------------------- load


def load(path: str | Path, root: Path | None = None) -> EvaluationRun:
    """Read one legacy evaluation file into an EvaluationRun. Read-only."""
    file = Path(path)
    payload = _json(file)
    if not isinstance(payload, dict) or "run" not in payload:
        raise ValueError(f"{file} is not a legacy evaluation result file")

    run = payload.get("run") or {}
    summary = payload.get("summary") or {}
    results = [r for r in (payload.get("results") or []) if isinstance(r, dict)]
    retrieval = _is_retrieval(payload)
    problems: list[str] = []

    if retrieval:
        metrics = _retrieval_metrics(summary, results)
        questions = _retrieval_questions(results)
        problems.append(
            "this is a retrieval-only evaluation: no answer model was involved, so it measures the "
            "retriever alone and cannot be compared with an answer evaluation"
        )
    else:
        metrics = _answer_metrics(summary, results, problems)
        questions = _answer_questions(results)
        problems.append(
            "this run predates the deterministic validation and repair layers, so it records one answer "
            "per question with no raw-versus-final distinction and no machine-checked correctness. Its "
            "numbers are throughput and human judgment, not the Stage 5 quality measures."
        )

    expected = run.get("num_questions") or _get(run, "dataset", "num_examples") or _get(run, "dataset", "num_queries")
    status = COMPLETE
    if expected and len(results) < int(expected):
        status = INCOMPLETE
        problems.append(f"the file holds {len(results)} of the {expected} records the run was started with")
    if summary.get("failed"):
        problems.append(
            f"{summary['failed']} question(s) failed during the run: {', '.join(map(str, summary.get('failed_ids') or [])) or 'ids not recorded'}"
        )

    duration = run.get("duration_seconds")
    identifier = file.relative_to(root).as_posix() if root and _under(file, root) else file.as_posix()

    return EvaluationRun(
        evaluation_run_id=stable_id(KIND_EVALUATION, identifier),
        name=str(run.get("pipeline") or file.stem),
        path=file.as_posix(),
        schema=SCHEMA_RETRIEVAL if retrieval else SCHEMA_ANSWER,
        model=_model(run, retrieval),
        benchmark=_benchmark(run),
        status=status,
        started_at=None,
        completed_at=run.get("timestamp_utc"),
        duration_seconds=duration,
        configuration={
            k: v for k, v in run.items()
            if k not in ("evaluation_run_id", "timestamp_utc", "dataset", "duration_seconds")
        },
        metrics=tuple(metrics),
        questions=questions,
        failure_summary={
            "failed_ids": summary.get("failed_ids") or [],
            "misses": summary.get("misses") or [],
        },
        breakdowns={
            "by_category": summary.get("by_category") or {},
            "manual_evaluation": summary.get("manual_evaluation") or {},
            "fallback": summary.get("fallback") or {},
            "environment": run.get("environment") or {},
            "retriever": run.get("retriever") or {},
            "database": run.get("database") or {},
            "schema_version": payload.get("schema_version"),
            "legacy_run_id": run.get("evaluation_run_id"),
            # Traceability back to the training run: the adapter name is the
            # training run's directory name, and the dataset hash identifies
            # the data it was trained on.
            "adapter": run.get("adapter") or {},
            "trained_from": {
                "training_run": _get(run, "adapter", "adapter_name"),
                "checkpoint": _get(run, "adapter", "best_checkpoint"),
                "dataset_hash": _get(run, "adapter", "dataset_hash"),
                "stage": _get(run, "adapter", "stage"),
                "adapter_built_at": _get(run, "adapter", "timestamp"),
            } if run.get("adapter") else {},
        },
        source_artifacts=(file.name,),
        problems=tuple(problems),
        git_revision=None,
    )


def _under(file: Path, root: Path) -> bool:
    try:
        file.relative_to(root)
        return True
    except ValueError:
        return False
