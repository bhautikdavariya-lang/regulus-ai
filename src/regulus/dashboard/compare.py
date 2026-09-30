"""Comparing two evaluation runs.

Comparison is where a dashboard is most likely to mislead, so the rules are
explicit and the refusals are loud:

* two runs are comparable only if they were measured on the same benchmark
  content. A different question set, or the same file with different content,
  is a blocking incompatibility, not a footnote;
* a difference is called an improvement or a regression only by consulting
  the metric's declared direction. Nothing is an improvement because a number
  went up;
* ratios are differenced in percentage points, never in "percent change",
  which would turn 2% -> 4% into "+100%";
* a metric present on one side and absent on the other is listed as such and
  never treated as zero;
* there is no overall winner, no score and no ranking. The dashboard lays the
  two runs side by side; a person decides.
"""

from __future__ import annotations

from typing import Any

from .schemas import (
    HIGHER_IS_BETTER,
    INFORMATIONAL,
    LOWER_IS_BETTER,
    RATIO,
    EvaluationRun,
)

IMPROVED = "improved"
REGRESSED = "regressed"
UNCHANGED = "unchanged"
CHANGED = "changed"
INCOMPARABLE = "incomparable"

RATIO_EPSILON = 0.0005  # half a tenth of a percentage point
ABSOLUTE_EPSILON = 1e-9

# Configuration keys whose difference changes what a number means, even on
# the same benchmark. A difference here is a warning, not a block.
CONFIG_KEYS = (
    "retriever", "top_k", "corpus", "min_trigram_similarity", "no_context_behavior",
    "exclude_contextual_only", "incomplete_behavior", "validation_behavior",
    "generation_budget", "context", "decoding_mode", "seed", "generation", "controlled",
)


def _blocking(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "severity": "blocking"}


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "severity": "warning"}


def compatibility(a: EvaluationRun, b: EvaluationRun) -> tuple[list[dict], list[dict]]:
    """What must stop a comparison, and what must merely be said out loud."""
    blocking: list[dict] = []
    warnings: list[dict] = []

    key_a = a.benchmark.key if a.benchmark else None
    key_b = b.benchmark.key if b.benchmark else None
    if key_a != key_b:
        blocking.append(_blocking(
            "benchmark_mismatch",
            f"different benchmarks: {a.benchmark.label if a.benchmark else 'unknown'} ({key_a}) "
            f"against {b.benchmark.label if b.benchmark else 'unknown'} ({key_b}). "
            "These numbers were produced by answering different questions and cannot be differenced.",
        ))

    # Same benchmark file is not enough: the runs must have answered the same
    # questions, all of them. A subset is a different population.
    for run, side in ((a, "left"), (b, "right")):
        if (run.question_set or {}).get("full_benchmark") is False:
            qs = run.question_set
            blocking.append(_blocking(
                "partial_benchmark",
                f"the {side} run evaluated {qs.get('count')} of {qs.get('benchmark_questions')} benchmark questions; "
                "a subset is a different population and cannot be differenced against another run.",
            ))
    sha_a = (a.question_set or {}).get("sha256")
    sha_b = (b.question_set or {}).get("sha256")
    if sha_a and sha_b and sha_a != sha_b:
        blocking.append(_blocking(
            "question_set_mismatch",
            f"the runs evaluated different question sets ({sha_a[:12]} against {sha_b[:12]}).",
        ))

    if a.schema != b.schema:
        blocking.append(_blocking(
            "schema_mismatch",
            f"different evaluation schemas ({a.schema} against {b.schema}): the two runs measured "
            "different things, so a metric that shares a name does not share a definition.",
        ))

    for run, side in ((a, "left"), (b, "right")):
        if not run.model.applicable:
            blocking.append(_blocking(
                "no_model",
                f"the {side} run is a retrieval-only evaluation with no answer model, so a change "
                "between the two cannot be attributed to a model.",
            ))
        elif not run.model.recorded:
            blocking.append(_blocking(
                "model_unrecorded",
                f"the {side} run does not record which weights it evaluated, so a difference cannot "
                "be attributed to a model change rather than to an unknown change of weights.",
            ))

    if a.model.recorded and b.model.recorded:
        if a.model.base_model_id != b.model.base_model_id:
            warnings.append(_warning(
                "base_model_differs",
                f"different base models: {a.model.base_model_id} against {b.model.base_model_id}.",
            ))
        if (a.model.adapter_id or None) != (b.model.adapter_id or None):
            warnings.append(_warning(
                "adapter_differs",
                f"different adapters: {a.model.adapter_id or 'none'} against {b.model.adapter_id or 'none'}. "
                "This is usually the point of the comparison; it is stated so it is never assumed.",
            ))
        elif (a.model.checkpoint or None) != (b.model.checkpoint or None):
            warnings.append(_warning(
                "checkpoint_differs",
                f"same adapter, different checkpoints: {a.model.checkpoint} against {b.model.checkpoint}.",
            ))
        if a.model.revision != b.model.revision:
            warnings.append(_warning(
                "revision_differs",
                f"different base-model revisions: {a.model.revision or 'unpinned'} against "
                f"{b.model.revision or 'unpinned'}.",
            ))
        if (a.model.dtype, a.model.device) != (b.model.dtype, b.model.device):
            warnings.append(_warning(
                "runtime_differs",
                f"different runtime: {a.model.dtype}/{a.model.device} against {b.model.dtype}/{b.model.device}. "
                "Latency is not comparable across these.",
            ))

    fp_a = (a.pipeline_fingerprint or {}).get("value")
    fp_b = (b.pipeline_fingerprint or {}).get("value")
    if fp_a and fp_b and fp_a != fp_b:
        warnings.append(_warning(
            "pipeline_differs",
            f"different pipeline fingerprints ({fp_a[:12]} against {fp_b[:12]}): the evaluation conditions differ, "
            "so a change may come from the pipeline configuration rather than from the model.",
        ))
    elif bool(fp_a) != bool(fp_b) or not (fp_a or fp_b):
        warnings.append(_warning(
            "pipeline_unrecorded",
            "at least one run records no pipeline fingerprint, so whether the evaluation conditions match "
            "cannot be verified.",
        ))

    differing = [
        key for key in CONFIG_KEYS
        if key in a.configuration or key in b.configuration
        if a.configuration.get(key) != b.configuration.get(key)
    ]
    if differing:
        warnings.append(_warning(
            "configuration_differs",
            "the evaluation configuration differs in: " + ", ".join(differing)
            + ". A change may come from the configuration rather than from the model.",
        ))

    for run, side in ((a, "left"), (b, "right")):
        if run.status in ("INCOMPLETE", "FAILED"):
            warnings.append(_warning(
                "run_not_complete",
                f"the {side} run is {run.status}: it covers only part of the benchmark, so its rates "
                "rest on a smaller sample.",
            ))

    if a.git_revision != b.git_revision and (a.git_revision or b.git_revision):
        warnings.append(_warning(
            "pipeline_revision_differs",
            f"different pipeline revisions: {a.git_revision or 'unrecorded'} against {b.git_revision or 'unrecorded'}.",
        ))

    return blocking, warnings


def _classify(direction: str, delta: float, unit: str) -> str:
    epsilon = RATIO_EPSILON if unit == RATIO else ABSOLUTE_EPSILON
    if abs(delta) <= epsilon:
        return UNCHANGED
    if direction == HIGHER_IS_BETTER:
        return IMPROVED if delta > 0 else REGRESSED
    if direction == LOWER_IS_BETTER:
        return IMPROVED if delta < 0 else REGRESSED
    return CHANGED


def metric_rows(a: EvaluationRun, b: EvaluationRun) -> list[dict[str, Any]]:
    """One row per metric either run reports, in the left run's order."""
    left = {m.key: m for m in a.metrics}
    right = {m.key: m for m in b.metrics}
    order = list(left) + [k for k in right if k not in left]
    rows: list[dict[str, Any]] = []
    for key in order:
        ma, mb = left.get(key), right.get(key)
        template = ma or mb
        row: dict[str, Any] = {
            "key": key,
            "display_name": template.display_name,
            "unit": template.unit,
            "direction": template.direction,
            "a": ma.to_dict() if ma else None,
            "b": mb.to_dict() if mb else None,
            "delta": None,
            "delta_percentage_points": None,
            "change": INCOMPARABLE,
            "note": None,
        }
        if ma is None or mb is None:
            row["note"] = f"reported only by the {'right' if ma is None else 'left'} run; it is not treated as zero"
        elif ma.value is None or mb.value is None:
            row["note"] = "not recorded by both runs"
        elif ma.unit != mb.unit:
            row["note"] = f"different units ({ma.unit} against {mb.unit})"
        else:
            delta = mb.value - ma.value
            row["delta"] = round(delta, 6)
            if ma.unit == RATIO:
                row["delta_percentage_points"] = round(delta * 100, 2)
            row["change"] = _classify(ma.direction, delta, ma.unit)
            if INFORMATIONAL == ma.direction:
                row["note"] = "informational: neither direction is better"
            if "inconsistent" in (ma.status, mb.status):
                row["note"] = ((row["note"] + "; ") if row["note"] else "") + (
                    "one side's stored aggregate disagrees with its own per-question records"
                )
        rows.append(row)
    return rows


def question_rows(a: EvaluationRun, b: EvaluationRun) -> dict[str, Any]:
    """Which individual questions moved, when both runs judged correctness."""
    left = {q.id: q for q in a.questions}
    right = {q.id: q for q in b.questions}
    shared = [qid for qid in left if qid in right]
    if not shared:
        return {"available": False, "reason": "the two runs share no question ids"}

    def moved(field: str) -> dict[str, list[dict[str, Any]]]:
        improved, regressed = [], []
        for qid in shared:
            before, after = getattr(left[qid], field), getattr(right[qid], field)
            if before is None or after is None or before == after:
                continue
            row = {"id": qid, "category": left[qid].category, "question": left[qid].question,
                   "before": before, "after": after}
            (improved if after else regressed).append(row)
        return {"improved": improved, "regressed": regressed}

    raw = moved("correct_raw")
    final = moved("correct_final")
    return {
        "available": True,
        "shared_questions": len(shared),
        "only_in_left": sorted(set(left) - set(right)),
        "only_in_right": sorted(set(right) - set(left)),
        "raw": raw,
        "final": final,
        "note": (
            "Raw and final are listed separately on purpose. A question that is correct only after "
            "repair moved because of the deterministic layer, not because of the model."
        ),
    }


def compare(a: EvaluationRun, b: EvaluationRun) -> dict[str, Any]:
    """Two runs side by side. No winner is chosen."""
    blocking, warnings = compatibility(a, b)
    rows = metric_rows(a, b)
    counts = {state: sum(1 for r in rows if r["change"] == state)
              for state in (IMPROVED, REGRESSED, UNCHANGED, CHANGED, INCOMPARABLE)}
    return {
        "left": _side(a),
        "right": _side(b),
        "comparable": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "metrics": rows,
        "counts": counts,
        "questions": question_rows(a, b) if not blocking else {
            "available": False, "reason": "the runs are not comparable, so their questions are not differenced",
        },
        "note": (
            "No overall winner is computed. Metrics move in different directions for different reasons, "
            "and a single number would hide which."
        ),
    }


def _side(run: EvaluationRun) -> dict[str, Any]:
    return {
        "evaluation_run_id": run.evaluation_run_id,
        "name": run.name,
        "path": run.path,
        "schema": run.schema,
        "status": run.status,
        "completed_at": run.completed_at,
        "model": run.model.to_dict(),
        "benchmark": run.benchmark.to_dict() if run.benchmark else None,
        "configuration": run.configuration,
        "questions": len(run.questions),
        "problems": list(run.problems),
    }
