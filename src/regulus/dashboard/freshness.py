"""The one place that decides whether an evaluation is CURRENT.

"CURRENT" means: this evaluation measured the system that is configured to
run today, on the whole of its benchmark. Adapters report what their
artifacts say (COMPLETE, INCOMPLETE, FAILED); this module turns that into
CURRENT, STALE or HISTORICAL against the resolved `CurrentSystem`, and gives
every decision a machine-readable code and a sentence.

An evaluation is CURRENT only if all of these hold:

1. the run completed (adapter status COMPLETE) and is an evaluation;
2. it evaluated the benchmark's entire question set
   (`question_set.full_benchmark is True`);
3. its model identity is recorded and resolved, including the checkpoint
   when an adapter is involved;
4. the current system is resolved (weights and pipeline);
5. base model id, revision, adapter and checkpoint all equal the current
   system's. A revision missing on either side is not a match;
6. it recorded a pipeline fingerprint that re-derives from its own stored
   configuration (`verified is True`), and that fingerprint equals the
   current system's, with the same fingerprint version;
7. among the runs that satisfy 1-6 on the same benchmark content (benchmark
   id and sha256), it is the latest by completion time. Ties and missing
   times are broken by artifact path, so the choice is deterministic. The
   others are STALE with code `superseded`.

Nothing here falls back: a run that misses one condition is not CURRENT, and
if no run meets them all, there is no current evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from .schemas import (
    COMPLETE,
    CURRENT,
    FAILED,
    HISTORICAL,
    INCOMPLETE,
    KIND_TRAINING,
    STALE,
    UNSUPPORTED_SCHEMA,
    CurrentSystem,
    Experiment,
)

# code -> the status it implies
CODES: dict[str, str] = {
    "current": CURRENT,
    "superseded": STALE,
    "pipeline_fingerprint_mismatch": STALE,
    "run_incomplete": INCOMPLETE,
    "run_failed": FAILED,
    "unsupported_schema": UNSUPPORTED_SCHEMA,
    "question_set_is_subset": INCOMPLETE,
    "training_run": COMPLETE,
    "no_answer_model": HISTORICAL,
    "checkpoint_unresolved": HISTORICAL,
    "model_identity_unrecorded": HISTORICAL,
    "current_system_unresolved": HISTORICAL,
    "model_mismatch": HISTORICAL,
    "model_revision_unrecorded": HISTORICAL,
    "pipeline_fingerprint_missing": HISTORICAL,
    "pipeline_fingerprint_unverified": HISTORICAL,
    "benchmark_unknown": HISTORICAL,
    "question_set_unverified": HISTORICAL,
}

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class FreshnessResult:
    status: str
    code: str
    reason: str
    checks: dict[str, Any] = field(default_factory=dict)


def completion_time(experiment: Experiment) -> datetime:
    """A timezone-aware completion time, or the epoch when there is none.

    A naive or unparseable time sorts as the oldest: it cannot be placed
    against the others safely.
    """
    value = experiment.completed_at
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return _EPOCH
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    return _EPOCH


def selection_key(experiment: Experiment) -> tuple:
    """Deterministic order among eligible runs: latest completion, then path."""
    return (completion_time(experiment), experiment.path)


def _model_check(run, current) -> tuple[str, str | None]:
    """'match', or a mismatch code and sentence."""
    differences = []
    if run.base_model_id != current.base_model_id:
        differences.append(f"base model {run.base_model_id} vs {current.base_model_id}")
    if (run.adapter_id or None) != (current.adapter_id or None):
        differences.append(f"adapter {run.adapter_id or 'none'} vs {current.adapter_id or 'none'}")
    elif (run.checkpoint or None) != (current.checkpoint or None):
        differences.append(f"checkpoint {run.checkpoint} vs {current.checkpoint}")
    if differences:
        return "model_mismatch", (
            f"evaluated {run.label}, which is not the configured model ({current.label}): " + "; ".join(differences)
        )
    if not run.revision:
        return "model_revision_unrecorded", (
            "the run does not record the base-model revision, so it cannot be shown to be the configured weights"
        )
    if run.revision != current.revision:
        return "model_mismatch", (
            f"evaluated base revision {run.revision[:12]}, but the configured model resolves to "
            f"{(current.revision or 'unknown')[:12]}"
        )
    return "match", None


def assess(experiment: Experiment, current: CurrentSystem) -> FreshnessResult:
    """Eligibility of one run, before supersession among eligible runs."""
    checks: dict[str, Any] = {}

    def result(code: str, reason: str) -> FreshnessResult:
        return FreshnessResult(CODES[code], code, reason, checks)

    if experiment.kind == KIND_TRAINING:
        if experiment.status == FAILED:
            return result("run_failed", "the run failed; it is kept so the failure stays visible")
        if experiment.status == INCOMPLETE:
            return result("run_incomplete", "the run did not finish; it is listed but never used as a current result")
        return result("training_run", "a training run measures the training process, not the current model's answers")
    if experiment.status == INCOMPLETE:
        return result("run_incomplete", "the run did not finish; it is listed but never used as a current result")
    if experiment.status == FAILED:
        return result("run_failed", "the run failed; it is kept so the failure stays visible")
    if experiment.status == UNSUPPORTED_SCHEMA:
        return result("unsupported_schema", "no adapter understands this artifact")

    qs = experiment.question_set or {}
    checks["question_set"] = {True: "full", False: "subset", None: "unverified"}[qs.get("full_benchmark")]
    if qs.get("full_benchmark") is False:
        return result("question_set_is_subset", (
            f"partial benchmark: it evaluated {qs.get('count')} of {qs.get('benchmark_questions')} questions "
            "(the process completed; the benchmark did not), so it is never the current model's performance"
        ))

    model = experiment.model
    if not model.applicable:
        checks["model"] = "not_applicable"
        return result("no_answer_model", "retrieval-only run: it measures no model")
    if model.checkpoint_unresolved:
        checks["model"] = "checkpoint_unresolved"
        return result("checkpoint_unresolved", (
            f"the artifacts name adapter {model.adapter_id} but not which checkpoint was loaded, "
            "so the weights it evaluated cannot be identified"
        ))
    if not model.recorded:
        checks["model"] = "unrecorded"
        return result("model_identity_unrecorded", (
            "the artifacts do not record which weights were evaluated, so this run cannot be "
            "presented as the current model's performance"
        ))
    if not current.resolved:
        checks["model"] = "current_unresolved"
        why = "; ".join(current.unresolved) or "the configured model or pipeline could not be resolved"
        return result("current_system_unresolved", f"the configured system is not fully resolved ({why})")

    code, reason = _model_check(model, current.model)
    checks["model"] = code
    if code != "match":
        return result(code, reason)

    recorded = experiment.pipeline_fingerprint
    configured = current.pipeline_fingerprint or {}
    if not recorded:
        checks["pipeline"] = "missing"
        return result("pipeline_fingerprint_missing", (
            "the run records no pipeline fingerprint, so it cannot be shown to measure the configured pipeline, "
            "even though its weights match"
        ))
    if recorded.get("verified") is not True:
        checks["pipeline"] = "unverified"
        return result("pipeline_fingerprint_unverified", (
            "the run's pipeline fingerprint does not re-derive from its own recorded configuration, so it is not evidence"
        ))
    if (recorded.get("version"), recorded.get("value")) != (configured.get("version"), configured.get("value")):
        checks["pipeline"] = "mismatch"
        return result("pipeline_fingerprint_mismatch", (
            f"same weights, different pipeline: the run's fingerprint {str(recorded.get('value'))[:12]} "
            f"(v{recorded.get('version')}) is not the configured {str(configured.get('value'))[:12]} "
            f"(v{configured.get('version')})"
        ))
    checks["pipeline"] = "match"

    if experiment.benchmark is None:
        return result("benchmark_unknown", "the run does not identify its benchmark")
    if qs.get("full_benchmark") is not True:
        return result("question_set_unverified", (
            "whether the run covered the whole benchmark cannot be verified from its artifacts"
        ))
    return result("current", "measures the configured model and pipeline on the whole benchmark")


def resolve(experiments: Iterable[Experiment], current: CurrentSystem) -> list[Experiment]:
    """Assess every run, then keep one CURRENT per benchmark content."""
    assessed = [(e, assess(e, current)) for e in experiments]
    winners: dict[str, Experiment] = {}
    for experiment, verdict in assessed:
        if verdict.code != "current":
            continue
        bucket = experiment.benchmark.key
        best = winners.get(bucket)
        if best is None or selection_key(experiment) > selection_key(best):
            winners[bucket] = experiment

    out: list[Experiment] = []
    for experiment, verdict in assessed:
        if verdict.code == "current" and winners[experiment.benchmark.key] is not experiment:
            winner = winners[experiment.benchmark.key]
            verdict = FreshnessResult(STALE, "superseded", (
                f"superseded by {winner.name} ({winner.completed_at or 'no timestamp'}), a later evaluation of the "
                "same configured system on the same benchmark"
            ), verdict.checks)
        out.append(replace(experiment, status=verdict.status, status_reason=verdict.reason,
                           freshness_code=verdict.code, freshness_checks=dict(verdict.checks)))
    return out
