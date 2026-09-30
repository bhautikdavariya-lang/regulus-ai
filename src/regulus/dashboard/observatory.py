"""Phase 3 observability: questions, forensics, history and comparison.

Everything here is derived from the canonical objects the adapters build
(`EvaluationRun`, `QuestionResult`, `Experiment`) and from the freshness
engine's decisions. The browser receives the result and decides nothing:
which questions match a filter, whether two runs are comparable and which
runs form one history line are all decided here.

Three rules run through the module:

* A field the artifacts do not record stays None and is reported as not
  measured. It is never 0, never False, never borrowed from another run.
* Distinct concepts stay distinct. A failure layer of "none" is not final
  correctness; citation validity is not semantic citation correctness.
* No composite: nothing here ranks runs, scores them or names a winner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from . import metrics as M
from .compare import compatibility, question_rows as moved_questions
from .freshness import selection_key
from .schemas import (
    CURRENT,
    INCOMPLETE,
    FAILED,
    KIND_EVALUATION,
    MISSING,
    RATIO,
    EvaluationRun,
    Experiment,
    QuestionResult,
)

NOT_MEASURED = "Not measured"
EVIDENCE_SCOPE = (
    "question-local evidence registry ids: e1, e2, ... are assigned per question by the evidence registry, "
    "so they identify evidence only within this question's own evidence record. They are not global document ids."
)
SEMANTIC_CITATION = {
    "status": MISSING, "value": None, "display": NOT_MEASURED,
    "reason": ("no evaluator in this project checks that a cited source supports the sentence it is attached to. "
               "Citation validity only checks that each marker points at a source that was supplied."),
}


# ------------------------------------------------------------------ questions


def _validation_ok(block: dict[str, Any] | None) -> bool | None:
    ok = (block or {}).get("ok")
    return ok if isinstance(ok, bool) else None


def _retrieval_ok(q: QuestionResult) -> bool | None:
    value = ((q.requirement_status or {}).get("checks") or {}).get("retrieval_ok")
    return value if isinstance(value, bool) else None


def _nearest_rank(values: list[float], p: float) -> float | None:
    """The same nearest-rank percentile the Stage 5 evaluator uses."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(round(p / 100.0 * (len(ordered) - 1)))))]


def question_row(q: QuestionResult) -> dict[str, Any]:
    """The compact, canonical row for one question. Unrecorded fields are None."""
    row = q.summary_row()
    generation_selected = [e for e in q.selected_evidence if "prompt_index" in e]
    row.update({
        "retrieval_ok": _retrieval_ok(q),
        "validation_raw_ok": _validation_ok(q.validation_raw) if q.generated else None,
        "validation_final_ok": _validation_ok(q.validation_final) if q.generated else None,
        "refusal_raw_class": (q.refusal or {}).get("raw_class"),
        "deterministic_refusal": (q.refusal or {}).get("deterministic_refusal"),
        "selected_evidence_count": len(generation_selected) if generation_selected else None,
        "generation_ms": (q.latency_ms or {}).get("generation_ms"),
    })
    row["trajectory"] = trajectory(row)["code"]
    return row


# How one question travelled from the model's own answer to the final one.
# Read only from recorded fields; a field the run did not record is never
# guessed, it makes the trajectory "not measured".
TRAJECTORIES: dict[str, str] = {
    "correct_throughout": "Marked correct before repair and after repair",
    "recovered_by_repair": "Not marked correct before repair; marked correct after repair",
    "incorrect_after_repair": "Not marked correct before repair; repair ran; still not marked correct",
    "incorrect_unrepaired": "Not marked correct; no repair was applied",
    "changed_by_repair": "Marked correct before repair; not marked correct after repair",
    "no_model_call": "No model call: the pipeline answered without the model (refusal or no context)",
    "not_measured": "Correctness was not measured for this question",
}


def trajectory(row: dict[str, Any]) -> dict[str, Any]:
    """The raw -> final path of one question row, as a code and a factual label."""
    raw, final, repaired = row.get("correct_raw"), row.get("correct_final"), bool(row.get("repair"))
    if row.get("generated") is False:
        code = "no_model_call"
    elif raw is None or final is None:
        code = "not_measured"
    elif raw and final:
        code = "correct_throughout"
    elif not raw and final:
        code = "recovered_by_repair"
    elif raw and not final:
        code = "changed_by_repair"
    else:
        code = "incorrect_after_repair" if repaired else "incorrect_unrepaired"
    return {
        "code": code,
        "label": TRAJECTORIES[code],
        "generated": row.get("generated"),
        "retrieval_ok": row.get("retrieval_ok"),
        "validation_raw_ok": row.get("validation_raw_ok"),
        "repair_applied": repaired,
        "validation_final_ok": row.get("validation_final_ok"),
        "correct_raw": raw,
        "correct_final": final,
    }


@dataclass(frozen=True)
class QuestionFilter:
    key: str
    label: str
    predicate: Callable[[dict[str, Any]], bool]
    # the row fields this filter reads; it is offered only if at least one
    # question records one of them
    needs: tuple[str, ...]
    description: str


FILTERS: tuple[QuestionFilter, ...] = (
    QuestionFilter("correct", "Correct (final)", lambda r: r["correct_final"] is True, ("correct_final",),
                   "final answer met every composite correctness condition"),
    QuestionFilter("incorrect", "Incorrect (final)", lambda r: r["correct_final"] is False, ("correct_final",),
                   "final answer failed at least one composite correctness condition"),
    QuestionFilter("raw_incorrect", "Incorrect before repair", lambda r: r["correct_raw"] is False, ("correct_raw",),
                   "the model's own answer, before repair, failed composite correctness"),
    QuestionFilter("only_after_repair", "Correct only after repair",
                   lambda r: r["correct_raw"] is False and r["correct_final"] is True, ("correct_raw", "correct_final"),
                   "correct because the deterministic repair layer rewrote the answer"),
    QuestionFilter("validation_failure", "Validation failure (raw)", lambda r: r["validation_raw_ok"] is False,
                   ("validation_raw_ok",), "the raw answer failed at least one deterministic validation check"),
    QuestionFilter("still_invalid", "Still invalid after repair", lambda r: r["validation_final_ok"] is False,
                   ("validation_final_ok",), "the final answer still fails deterministic validation"),
    QuestionFilter("repaired", "Repaired", lambda r: bool(r["repair"]), ("repair", "validation_raw_ok"),
                   "the deterministic repair layer modified the answer"),
    QuestionFilter("unrepaired", "Not repaired", lambda r: r["generated"] and not r["repair"],
                   ("repair", "validation_raw_ok"), "an answer was generated and repair did not change it"),
    QuestionFilter("retrieval_issue", "Retrieval issue", lambda r: r["retrieval_ok"] is False, ("retrieval_ok",),
                   "the evidence phase did not retrieve what the question needed"),
    QuestionFilter("citation_issue", "Citation issue", lambda r: r["citation_ok"] is False, ("citation_ok",),
                   "an invalid, malformed or mismatched citation marker"),
    QuestionFilter("hallucination", "Unsupported content (raw)", lambda r: r["hallucination_raw"] is True,
                   ("hallucination_raw",), "an identifier, figure or provision in no supplied source"),
    QuestionFilter("refused", "Refused / unsupported", lambda r: (not r["generated"])
                   or r["refusal_raw_class"] == "refusal", ("refusal_raw_class", "deterministic_refusal"),
                   "no model answer (deterministic refusal or no context) or the model declined"),
    QuestionFilter("false_refusal", "False refusal", lambda r: r["false_refusal"] is True, ("false_refusal",),
                   "an answerable question was declined"),
    QuestionFilter("truncated", "Truncated", lambda r: r["truncated"] is True, ("truncated",),
                   "the answer hit its token allowance"),
    QuestionFilter("no_model_answer", "No model answer", lambda r: r["generated"] is False, ("generated",),
                   "the pipeline answered without calling the model (deterministic refusal or no context)"),
    QuestionFilter("not_measured", "Correctness not measured", lambda r: r["correct_final"] is None, ("id",),
                   "the run records no final correctness verdict for the question"),
)
FILTER_KEYS = frozenset(f.key for f in FILTERS) | {"slow"}


def question_list(run: EvaluationRun, *, filter_key: str | None = None, layer: str | None = None,
                  category: str | None = None, search: str | None = None) -> dict[str, Any]:
    """Rows, the filters this run's data supports (with counts), and the filtered view.

    Raises ValueError for a filter, layer or category this run cannot answer,
    so a caller asking for "slow" on a run without timings gets an error, not
    an empty list that reads as "no slow questions".
    """
    rows = [question_row(q) for q in run.questions]
    filters: list[dict[str, Any]] = []
    predicates: dict[str, Callable[[dict[str, Any]], bool]] = {}
    for f in FILTERS:
        available = any(r.get(field) is not None for r in rows for field in f.needs)
        if available:
            predicates[f.key] = f.predicate
        filters.append({"key": f.key, "label": f.label, "description": f.description, "available": available,
                        "count": sum(1 for r in rows if f.predicate(r)) if available else None})

    # "slow" is relative to this run: at or above its own 90th-percentile time
    totals = [r["total_ms"] for r in rows if isinstance(r.get("total_ms"), (int, float))]
    threshold = _nearest_rank(totals, 90)
    if threshold is not None:
        predicates["slow"] = lambda r, t=threshold: isinstance(r.get("total_ms"), (int, float)) and r["total_ms"] >= t
        filters.append({"key": "slow", "label": f"Slow (≥ {threshold / 1000:.0f} s)", "available": True,
                        "description": f"at or above this run's 90th-percentile end-to-end time ({threshold / 1000:.1f} s)",
                        "count": sum(1 for r in rows if predicates["slow"](r)), "threshold_ms": threshold})
    else:
        filters.append({"key": "slow", "label": "Slow", "available": False, "count": None,
                        "description": "this run records no per-question timings"})

    for r in rows:
        r["flags"] = [key for key, p in predicates.items() if p(r)]

    layers = sorted({r["failure_layer"] for r in rows if r.get("failure_layer")})
    categories = sorted({r["category"] for r in rows if r.get("category")})
    if filter_key and filter_key not in predicates:
        known = {f["key"] for f in filters}
        raise ValueError(f"unknown filter {filter_key!r}" if filter_key not in known
                         else f"filter {filter_key!r} is not available: this run does not record the data it needs")
    if layer and layer not in layers:
        raise ValueError(f"this run records no failure layer {layer!r}")
    if category and category not in categories:
        raise ValueError(f"this run has no category {category!r}")

    needle = (search or "").strip().lower()
    shown = [r for r in rows
             if (not filter_key or filter_key in r["flags"])
             and (not layer or r.get("failure_layer") == layer)
             and (not category or r.get("category") == category)
             and (not needle or needle in f"{r['id']} {r['question']}".lower())]
    return {
        "total": len(rows),
        "matched": len(shown),
        "applied": {"filter": filter_key, "layer": layer, "category": category, "search": search or None},
        "filters": filters,
        "layers": [{"key": l, "count": sum(1 for r in rows if r.get("failure_layer") == l)} for l in layers],
        "categories": categories,
        "trajectories": dict(TRAJECTORIES),
        "questions": shown,
        "notes": {
            "failure_layer": ("The failure layer and final correctness are separate evaluator outputs with different "
                              "definitions. A layer of 'none' does not mean the final answer is correct."),
            "evidence": EVIDENCE_SCOPE,
        },
    }


def question_detail(run: EvaluationRun, question_id: str) -> dict[str, Any] | None:
    """Everything the artifacts record for one question, with forensic structure on top."""
    q = next((x for x in run.questions if x.id == question_id), None)
    if q is None:
        return None
    extra = q.extra or {}
    citation_summary = extra.get("citation_summary") or {}

    # tiers, requirements and provisions per question-local evidence id
    known: dict[str, dict[str, Any]] = {}
    for tier, items in (q.evidence_by_tier or {}).items():
        for item in items:
            entry = known.setdefault(item["evidence_id"], {"tiers": [], "requirement_ids": [], "provisions": []})
            if tier not in entry["tiers"]:
                entry["tiers"].append(tier)
            for field, value in (("requirement_ids", item.get("requirement_id")), ("provisions", item.get("provision"))):
                if value and value not in entry[field]:
                    entry[field].append(value)
    by_prompt_index = {c.get("index"): c for c in q.citations or [] if isinstance(c, dict) and c.get("index") is not None}
    selected = []
    for item in q.selected_evidence or []:
        eid = item.get("evidence_id")
        if eid is None:
            continue
        index = item.get("prompt_index")
        cited = by_prompt_index.get(index) if index is not None else None
        selected.append({
            "evidence_id": eid,
            "prompt_index": index,
            "in_context": item.get("in_context"),
            **(known.get(eid) or {"tiers": [], "requirement_ids": [], "provisions": []}),
            "source_label": cited.get("label") if cited else None,
            "source_url": cited.get("url") if cited else None,
            "cited_in_answer": cited.get("cited_in_answer") if cited else (False if index is not None else None),
        })

    reference = extra.get("reference_answer")
    repair_kinds = [k for k in (q.repair or "").split("+") if k]
    return {
        **q.to_dict(),
        "forensics": {
            "trajectory": trajectory(question_row(q)),
            "expected": {
                "behavior": q.expected_behavior,
                "requirements": list(q.expected_requirements),
                "terms": list(q.expected_terms),
                "reference_answer": reference,
                "reference_answer_display": reference if reference else "Not provided by the benchmark",
            },
            "answers": {"raw": q.answer_raw, "final": q.answer_final,
                        "controlled_raw": q.controlled_answer_raw,
                        "final_differs_from_raw": (q.answer_final is not None and q.answer_raw is not None
                                                   and q.answer_final != q.answer_raw)},
            "evidence": {
                "scope": EVIDENCE_SCOPE,
                "source": extra.get("selected_evidence_source"),
                "selected": selected,
                "selected_count": len(selected),
                "by_tier": q.evidence_by_tier,
            },
            "validation": {
                "raw": {k: (q.validation_raw or {}).get(k) for k in ("status", "ok", "codes", "problems")} if q.validation_raw else None,
                "final": {k: (q.validation_final or {}).get(k) for k in ("status", "ok", "codes", "problems")} if q.validation_final else None,
            },
            "repair": {"applied": bool(q.repair), "kinds": repair_kinds, "raw": q.repair},
            "citations": {
                "markers": citation_summary.get("markers"),
                "invalid": citation_summary.get("invalid"),
                "validity": q.citation_ok,
                "listed": q.citations,
                "semantic_correctness": SEMANTIC_CITATION,
            },
            "retrieval": {"ok": _retrieval_ok(q), "detail": (q.requirement_status or {}).get("retrieval")},
            "outcome": {
                "correct_raw": q.correct_raw, "correct_final": q.correct_final,
                "reasons_raw": list(q.correct_reasons_raw), "reasons_final": list(q.correct_reasons_final),
                "failure_layer": q.failure_layer, "failure_reasons": list(q.failure_reasons),
                "note": ("Failure layer and final correctness come from different evaluator outputs with different "
                         "definitions; they are shown side by side, never merged."),
            },
            "timing_ms": q.latency_ms,
            "tokens": q.tokens,
            # Stage 12: None for runs recorded before answer shaping existed
            "answer_shape": ({
                "shape": extra.get("answer_shape"),
                "plan": extra.get("evidence_plan"),
                "checks_raw": (q.validation_raw or {}).get("shape"),
                "checks_final": (q.validation_final or {}).get("shape"),
            } if extra.get("answer_shape") else None),
        },
    }


# -------------------------------------------------------------------- history

HISTORY_METRICS = (
    "correctness_final", "correctness_raw", "valid_raw", "valid_final", "repair_rate", "citation_ok",
    "hallucination_raw", "retrieval_ok", "e2e_latency_p50", "e2e_latency_p95", "generation_latency_p50",
    "avg_generated_tokens",
)

COMPATIBILITY_CLASSES = {
    "reference": "the CURRENT evaluation of the configured system on this benchmark",
    "comparable": "same weights, same pipeline fingerprint, same whole benchmark: a point on the same line",
    "different_model": "same benchmark, different weights: a different evaluation identity",
    "different_pipeline": "same weights and benchmark, different pipeline fingerprint: conditions differ",
    "different_benchmark": "no current evaluation on this benchmark to compare it with",
    "incomplete": "the run did not finish or evaluated only part of its benchmark",
    "insufficient_identity": "the artifacts do not record the weights or the pipeline, so comparison is limited",
    "not_applicable": "retrieval-only run: it measures no answer model",
}


def _identity(e: Experiment) -> dict[str, Any]:
    fp = e.pipeline_fingerprint or {}
    qs = e.question_set or {}
    return {
        "model_key": e.model.key, "model_label": e.model.label, "model_recorded": e.model.recorded,
        "benchmark_key": e.benchmark.key if e.benchmark else None,
        "benchmark_label": e.benchmark.label if e.benchmark else None,
        "pipeline_fingerprint": fp.get("value"), "pipeline_fingerprint_version": fp.get("version"),
        "pipeline_verified": fp.get("verified"),
        "question_count": qs.get("count"), "question_set_sha256": qs.get("sha256"),
        "full_benchmark": qs.get("full_benchmark"),
    }


def _metric_values(run: EvaluationRun | None) -> dict[str, Any]:
    """Every history metric, always present: a value, or explicitly Not measured."""
    have = {m.key: m for m in run.metrics} if run is not None else {}
    out = {}
    for key in HISTORY_METRICS:
        m = have.get(key)
        measured = m is not None and m.value is not None and m.status != MISSING
        out[key] = {"value": m.value if measured else None,
                    "numerator": m.numerator if measured else None,
                    "denominator": m.denominator if measured else None,
                    "unit": M.definition(key).unit, "status": m.status if m is not None else MISSING,
                    "display": None if measured else NOT_MEASURED}
    return out


def _classify(e: Experiment, references: dict[str | None, Experiment]) -> str:
    if e.status == CURRENT:
        return "reference"
    if e.status in (INCOMPLETE, FAILED) or (e.question_set or {}).get("full_benchmark") is False:
        return "incomplete"
    if not e.model.applicable:
        return "not_applicable"
    if not e.model.recorded or not (e.pipeline_fingerprint or {}).get("value"):
        return "insufficient_identity"
    reference = references.get(e.benchmark.key if e.benchmark else None)
    if reference is None:
        return "different_benchmark"
    if e.model.key != reference.model.key:
        return "different_model"
    if (e.pipeline_fingerprint or {}).get("value") != (reference.pipeline_fingerprint or {}).get("value"):
        return "different_pipeline"
    return "comparable"


def evaluation_history(registry) -> dict[str, Any]:
    """Every evaluation with its identity, and the compatible lines they form.

    A line is the set of evaluations that share model key, benchmark content,
    pipeline fingerprint and the whole question set, with recorded identity.
    Nothing outside a line is ever drawn on it.
    """
    evaluations = [e for e in registry.experiments if e.kind == KIND_EVALUATION]
    references = {e.benchmark.key: e for e in evaluations if e.status == CURRENT and e.benchmark}
    runs = []
    for e in sorted(evaluations, key=selection_key, reverse=True):
        cls = _classify(e, references)
        runs.append({
            "experiment_id": e.experiment_id, "name": e.name, "status": e.status,
            "freshness_code": e.freshness_code, "status_reason": e.status_reason,
            "completed_at": e.completed_at, "compatibility": cls,
            "compatibility_reason": COMPATIBILITY_CLASSES[cls],
            "identity": _identity(e),
            "metrics": _metric_values(registry.evaluation(e.experiment_id)),
        })

    lines: dict[tuple, list[dict[str, Any]]] = {}
    for r in runs:
        i = r["identity"]
        if not (i["model_recorded"] and i["pipeline_fingerprint"] and i["full_benchmark"] is True
                and i["benchmark_key"] and r["status"] not in (INCOMPLETE, FAILED)):
            continue
        key = (i["model_key"], i["benchmark_key"], i["pipeline_fingerprint"], i["pipeline_fingerprint_version"])
        lines.setdefault(key, []).append(r)

    groups = []
    for (model_key, benchmark_key, fingerprint, version), members in lines.items():
        members = sorted(members, key=lambda r: (r["completed_at"] or "", r["experiment_id"]))
        current = any(m["status"] == CURRENT for m in members)
        series = []
        for key in HISTORY_METRICS:
            points = [{"experiment_id": m["experiment_id"], "name": m["name"], "completed_at": m["completed_at"],
                       **m["metrics"][key]} for m in members if key in m["metrics"] and m["metrics"][key]["value"] is not None]
            if points:
                d = M.definition(key)
                series.append({"key": key, "display_name": d.name, "unit": d.unit, "direction": d.direction,
                               "heuristic": d.heuristic, "points": points})
        groups.append({
            "model_key": model_key, "model_label": members[0]["identity"]["model_label"],
            "benchmark_key": benchmark_key, "benchmark_label": members[0]["identity"]["benchmark_label"],
            "pipeline_fingerprint": fingerprint, "pipeline_fingerprint_version": version,
            "contains_current": current, "runs": [m["experiment_id"] for m in members],
            "trend_available": len(members) >= 2,
            "trend_note": (None if len(members) >= 2 else
                           "History unavailable: only one compatible evaluation."),
            "series": series,
        })
    groups.sort(key=lambda g: (not g["contains_current"], g["benchmark_key"] or "", g["model_key"]))
    counts: dict[str, int] = {}
    for r in runs:
        counts[r["compatibility"]] = counts.get(r["compatibility"], 0) + 1
    return {
        "runs": runs,
        "groups": groups,
        "counts": counts,
        "classes": COMPATIBILITY_CLASSES,
        "note": ("A line joins only evaluations with the same weights, benchmark content, pipeline fingerprint and "
                 "whole question set. Everything else is listed with the reason it is not on a line."),
    }


# ----------------------------------------------------------------- comparison

MAX_COMPARE = 6


def compare_runs(pairs: list[tuple[Experiment, EvaluationRun]]) -> dict[str, Any]:
    """Two or more runs side by side, against the first as the reference.

    Per pair the existing compatibility rules decide; a pair with a blocking
    reason gets no differences. Per metric a value is shown only where the run
    measured it; otherwise "Not measured". There is no winner and no tally.
    """
    if len(pairs) < 2:
        raise ValueError("comparison needs at least two runs")
    reference_exp, reference = pairs[0]
    columns = []
    for exp, run in pairs:
        blocking, warnings = compatibility(reference, run) if run is not reference else ([], [])
        columns.append({
            "experiment_id": exp.experiment_id, "name": exp.name, "status": exp.status,
            "freshness_code": exp.freshness_code, "completed_at": exp.completed_at,
            "is_reference": run is reference, "comparable": not blocking,
            "blocking": blocking, "warnings": warnings, "identity": _identity(exp),
            "questions": len(run.questions),
        })

    by_run = [{m.key: m for m in run.metrics} for _, run in pairs]
    keys: list[str] = []
    for d in M.all_definitions():
        if any(d.key in metrics for metrics in by_run):
            keys.append(d.key)
    rows = []
    for key in keys:
        d = M.definition(key)
        ref = by_run[0].get(key)
        cells = []
        for column, metrics in zip(columns, by_run):
            m = metrics.get(key)
            measured = m is not None and m.value is not None and m.status != MISSING
            cell = {
                "experiment_id": column["experiment_id"],
                "value": m.value if measured else None, "numerator": m.numerator if measured else None,
                "denominator": m.denominator if measured else None, "status": m.status if m else MISSING,
                "sample_note": m.sample_note if measured else None,
                "display": None if measured else NOT_MEASURED,
                "delta": None, "delta_percentage_points": None, "delta_note": None,
            }
            if column["is_reference"]:
                cell["delta_note"] = "reference"
            elif not column["comparable"]:
                cell["delta_note"] = "Not directly comparable"
            elif not measured or ref is None or ref.value is None or ref.status == MISSING:
                cell["delta_note"] = "Not measured by both runs"
            else:
                delta = m.value - ref.value
                cell["delta"] = round(delta, 6)
                if d.unit == RATIO:
                    cell["delta_percentage_points"] = round(delta * 100, 2)
            cells.append(cell)
        rows.append({"key": key, "display_name": d.name, "family": d.family, "unit": d.unit,
                     "direction": d.direction, "heuristic": d.heuristic, "cells": cells})

    payload = {
        "reference": columns[0]["experiment_id"],
        "runs": columns,
        "rows": rows,
        "note": ("Each run is compared with the first. No overall winner, score or tally is computed: metrics move "
                 "in different directions for different reasons."),
    }
    if len(pairs) == 2:
        blocked = bool(columns[1]["blocking"])
        payload["questions"] = ({"available": False, "reason": "the runs are not comparable, so their questions are "
                                 "not differenced"} if blocked else moved_questions(reference, pairs[1][1]))
    return payload


# --------------------------------------------------------------- coverage


def evidence_coverage(run: EvaluationRun) -> dict[str, Any]:
    """How many questions carry question-level evidence provenance."""
    generated = [q for q in run.questions if q.generated]
    from_generation = [q for q in generated if any("prompt_index" in e for e in q.selected_evidence or [])]
    return {
        "questions": len(run.questions),
        "generated": len(generated),
        "with_generation_selected_ids": len(from_generation),
        "note": ("Selected evidence ids recorded by the generation itself (which evidence the model was given). "
                 "Older runs only have the evidence phase's selection."),
    }


def iter_evaluation_pairs(registry, ids: Iterable[str]) -> list[tuple[Experiment, EvaluationRun]]:
    out = []
    for experiment_id in ids:
        exp, run = registry.experiment(experiment_id), registry.evaluation(experiment_id)
        if exp is None or run is None:
            raise LookupError(f"no evaluation experiment {experiment_id}")
        out.append((exp, run))
    return out
