"""The acceptance evaluation the dashboard is entitled to show, and its provenance.

The Overview's headline answers "has the configured system been evaluated?" and
its answer is decided by `freshness`. This module answers a different and
narrower question:

    of the acceptance-test runs on disk, which one is the authoritative result
    for the 300-question benchmark, and exactly what produced it?

Those are separate because an acceptance run can be the authoritative result
for the benchmark while NOT being the configured system's current performance
-- which is the situation today. Both facts are reported, neither is allowed to
stand in for the other, and the payload always carries `is_current`.

Selection, and why it is not "the newest file"
----------------------------------------------
Recency is the last tie-break, never the first test. A run is a candidate only
if it clears every substantive condition, in this order:

1. the acceptance adapter claimed it, so its artifacts are the shape this
   rubric is recorded in;
2. its scoring covers the WHOLE benchmark (`question_set.full_benchmark` is
   True). A run scored on 224 of 300 rows is a result for those rows and is
   never offered as the benchmark result, however recent it is;
3. the run itself completed, so there is an answer behind every verdict;
4. it records which weights it evaluated.

Only among the runs that clear all four does completion time decide, with the
artifact path as a deterministic tie-break (`freshness.selection_key`). Runs
that fail a condition are reported in `rejected`, each with the condition it
failed, so the choice is auditable rather than asserted.

Preferring the configured model is applied as a *filter before* recency too: a
run of a different adapter is not the current system's benchmark result even if
it is newer. When no run matches the configured model, the newest fully scored
run is offered instead and `matches_configured_model` is False.

Nothing here scores, and nothing here overrides freshness: `is_current` is
copied from the registry's own verdict on that run.
"""

from __future__ import annotations

from typing import Any

from . import freshness as F
from .adapters import acceptance
from .schemas import CURRENT, Experiment

# the five conditions, in the order they are applied
WHOLE_BENCHMARK = "scoring_does_not_cover_the_benchmark"
RUN_INCOMPLETE = "the_run_did_not_finish"
MODEL_UNRECORDED = "the_weights_are_not_recorded"

REVALIDATION_WARNING = (
    "Metrics require revalidation. This evaluation was not produced by the system as it is configured "
    "today, so it is not this model's current performance."
)
KEY_WARNING = (
    "Scored against a DRAFT answer key. The benchmark workbook requires its answer key to be verified by "
    "a subject-matter expert before the test is administered, and states that an unverified key "
    "invalidates the entire result. These numbers are indicative, not contractual."
)
QUESTION_SET_UNVERIFIED = (
    "The benchmark workbook was not available to check WHICH questions this run scored. The number of scored "
    "rows matches the number the run recorded, but that they are the benchmark's own questions could not be "
    "verified here."
)
NOT_THE_LIVE_INDICATOR = (
    "This is the controlled 300-question benchmark, scored by hand under regulus_substantive_rubric_v1. "
    "It is not the per-answer accuracy indicator shown beside a live answer, which measures one answer "
    "against its own retrieved evidence under a different rubric, and the two must never be combined."
)


def _is_acceptance(experiment: Experiment, schema_of=None) -> bool:
    """Whether this experiment is an acceptance run.

    `Experiment` carries no schema -- the schema belongs to the EvaluationRun --
    so the caller passes a lookup when it has one. Without a lookup, the
    adapter's own `detect` decides, which is the same question asked of the same
    authority rather than a second guess at it.
    """
    if schema_of is not None:
        return schema_of(experiment) == acceptance.SCHEMA
    return acceptance.detect(experiment.path)


def _reject(experiment: Experiment, reason: str) -> dict[str, Any]:
    return {"run": experiment.name, "experiment_id": experiment.experiment_id,
            "completed_at": experiment.completed_at, "rejected_because": reason,
            "status": experiment.status, "status_reason": experiment.status_reason}


def candidates(experiments, schema_of=None) -> tuple[list[Experiment], list[dict[str, Any]]]:
    """The runs eligible to be the benchmark result, and why the others are not."""
    eligible: list[Experiment] = []
    rejected: list[dict[str, Any]] = []
    for experiment in experiments:
        if not _is_acceptance(experiment, schema_of):
            continue
        question_set = experiment.question_set or {}
        full = question_set.get("full_benchmark")
        count, total = question_set.get("count"), question_set.get("benchmark_questions")
        # True  = the scored ids ARE the benchmark's own id set, verified against the workbook.
        # None  = the workbook was not on disk to compare against. The count can still
        #         be compared with the number the run recorded, which proves the right
        #         NUMBER of rows but not the right rows; that is accepted here and
        #         declared in `question_set_verified`, because going silent about a
        #         300-row result over a missing spreadsheet would hide more than it protects.
        # False = provably not the benchmark.
        if full is False or (full is None and (total is None or count != total)):
            rejected.append({**_reject(experiment, WHOLE_BENCHMARK),
                             "detail": f"{count} of {total} benchmark rows carry a verdict"
                                       if total is not None else
                                       "the run does not record how many questions the benchmark holds"})
        elif experiment.status == "INCOMPLETE":
            rejected.append(_reject(experiment, RUN_INCOMPLETE))
        elif not experiment.model.recorded:
            rejected.append(_reject(experiment, MODEL_UNRECORDED))
        else:
            eligible.append(experiment)
    return eligible, rejected


def select(experiments, current, schema_of=None) -> tuple[Experiment | None, list[dict[str, Any]], bool]:
    """(the authoritative run, the rejected runs, whether it is the configured model)."""
    eligible, rejected = candidates(experiments, schema_of)
    if not eligible:
        return None, rejected, False
    same_model = [e for e in eligible if e.model.key == current.model.key]
    pool, matches = (same_model, True) if same_model else (eligible, False)
    chosen = max(pool, key=F.selection_key)
    for other in eligible:
        if other is not chosen:
            rejected.append({**_reject(other, "superseded_by_a_later_fully_scored_run"
                                       if other in pool else "evaluated_different_weights"),
                             "detail": f"{chosen.name} is the selected run"})
    return chosen, rejected, matches


def payload(registry) -> dict[str, Any]:
    """Everything the UI needs to show the benchmark result and stand behind it."""
    current = registry.current_system
    schema_of = lambda experiment: getattr(registry.evaluation(experiment.experiment_id), "schema", None)
    chosen, rejected, matches_model = select(registry.experiments, current, schema_of)
    out: dict[str, Any] = {
        "available": chosen is not None,
        "rubric_id": acceptance.RUBRIC_ID,
        "not_the_live_indicator": NOT_THE_LIVE_INDICATOR,
        "rejected": rejected,
        "configured_system": {
            "model": current.model.to_dict(),
            "pipeline_fingerprint": current.pipeline_fingerprint,
            "resolved": current.resolved,
        },
    }
    if chosen is None:
        out["reason"] = (
            "No acceptance-test run on this machine has a verdict for every one of the benchmark's questions, "
            "so there is no benchmark result to show. A partially scored run is not a benchmark result."
            if rejected else
            "No acceptance-test run was found on this machine, so the 300-question benchmark has never been run here."
        )
        return out

    run = registry.evaluation(chosen.experiment_id)
    is_current = chosen.status == CURRENT
    warnings = [] if is_current else [REVALIDATION_WARNING]
    key_verification = (run.breakdowns.get("key_verification") if run else {}) or {}
    if key_verification.get("key_is_locked") is not True:
        warnings.append(KEY_WARNING)
    if (chosen.question_set or {}).get("full_benchmark") is not True:
        warnings.append(QUESTION_SET_UNVERIFIED)

    # §3: the provenance every displayed metric is tied to.
    out.update({
        "is_current": is_current,
        "freshness": {"status": chosen.status, "code": chosen.freshness_code, "reason": chosen.status_reason,
                      "checks": chosen.freshness_checks or {}},
        "matches_configured_model": matches_model,
        "question_set_verified": (chosen.question_set or {}).get("full_benchmark") is True,
        "warnings": warnings,
        "provenance": {
            "evaluation": (chosen.benchmark.label if chosen.benchmark else None),
            "benchmark_id": (chosen.benchmark.benchmark_id if chosen.benchmark else None),
            "benchmark_key": (chosen.benchmark.key if chosen.benchmark else None),
            "benchmark_sha256": (chosen.benchmark.sha256 if chosen.benchmark else None),
            "benchmark_file": (chosen.benchmark.path if chosen.benchmark else None),
            "run_id": chosen.name,
            "experiment_id": chosen.experiment_id,
            "artifact": chosen.path,
            "started_at": chosen.created_at,
            "evaluated_at": chosen.completed_at,
            "model": chosen.model.base_model_id,
            "model_revision": chosen.model.revision,
            "adapter": chosen.model.adapter_id or "none",
            "adapter_checkpoint": chosen.model.checkpoint,
            "model_label": chosen.model.label,
            "device": chosen.model.device,
            "dtype": chosen.model.dtype,
            "retrieval": _retrieval_label(run),
            "pipeline_fingerprint": chosen.pipeline_fingerprint,
            "rubric": acceptance.RUBRIC_ID,
            "questions": (chosen.question_set or {}).get("count"),
            "benchmark_questions": (chosen.question_set or {}).get("benchmark_questions"),
            "question_set_sha256": (chosen.question_set or {}).get("sha256"),
            "evaluation_status": chosen.status,
            "git_commit": (run.configuration.get("git_commit") if run else None),
            "git_dirty": (run.configuration.get("git_dirty") if run else None),
            "scoring_basis": (run.breakdowns.get("scoring_basis") if run else {}),
            "key_verification": key_verification,
            "protocol": (run.configuration.get("protocol") if run else None),
            "command": (run.configuration.get("command") if run else None),
        },
        "headline": _headline(run),
        "metrics": [m.to_dict() for m in (run.metrics if run else ())],
        "gates": (run.breakdowns.get("gates") if run else []) or [],
        "verdict_counts": (run.breakdowns.get("verdict_counts") if run else {}) or {},
        "score_distribution": (run.breakdowns.get("score_distribution") if run else {}) or {},
        "caveats": list(run.problems) if run else [],
        "source_artifacts": list(run.source_artifacts) if run else [],
    })
    return out


def _headline(run) -> dict[str, Any] | None:
    """The one number, with its counts. Never a bare percentage."""
    if run is None:
        return None
    metric = run.metric("acceptance_full_pass")
    if metric is None or metric.value is None:
        return None
    return {"key": metric.key, "label": metric.display_name, "value": metric.value,
            "numerator": metric.numerator, "denominator": metric.denominator,
            "sample_note": metric.sample_note, "definition_key": metric.definition_key or metric.key}


def _retrieval_label(run) -> str | None:
    """The retrieval configuration in one line, from what the run recorded."""
    if run is None:
        return None
    config = (run.configuration or {}).get("evaluation_config") or {}
    retrieval = config.get("retrieval") or {}
    retriever = ((run.configuration or {}).get("retriever") or {}).get("retriever") or retrieval.get("retriever")
    if not retriever:
        return None
    bits = [str(retriever)]
    if retrieval.get("top_k") is not None:
        bits.append(f"top_k={retrieval['top_k']}")
    if retrieval.get("semantic_fallback"):
        bits.append(f"semantic_fallback={retrieval['semantic_fallback']}")
    coverage = config.get("coverage") or {}
    for name in ("answerability", "scope_policy", "evidence_consolidation", "optional_context"):
        if coverage.get(name):
            bits.append(f"{name}={coverage[name]}")
    return ", ".join(bits)
