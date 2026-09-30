"""Model health: what the dashboard shows first.

The rest of the dashboard answers "what experiments exist?". This module
answers the only question most people open it for:

    How good is the model we are running right now?

Three rules shape everything here, and each exists because the obvious
alternative would mislead:

* **Only the current model's own evaluation is used.** If the configured
  model has no current evaluation, the answer is "it has not been evaluated",
  not some other model's numbers. A historical result is never promoted.
* **A metric that the current evaluation does not measure is reported as not
  measured.** It is never filled in from a different run, a different
  benchmark or a different set of weights.
* **No composite score.** Independent dimensions stay independent; a single
  number would hide which one moved.

Sections and their contents are derived from the canonical metric registry,
so a metric added to an adapter appears here without anyone editing a list of
names. The section copy is written for someone who does not know what a LoRA
checkpoint is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from . import metrics as M
from .freshness import selection_key
from .schemas import (
    CURRENT,
    STALE,
    INCONSISTENT,
    KIND_EVALUATION,
    KIND_TRAINING,
    MISSING,
    EvaluationRun,
    Experiment,
    MetricResult,
)

# Neutral by design. The project defines no quality thresholds, and inventing
# one - deciding that 70% is "good" - would be a judgment the artifacts do not
# support. A threshold map can be set in the registry store, and only then
# does a metric get a good/attention/poor state. See `metric_state`.
STATE_AVAILABLE = "available"
STATE_MISSING = "missing"
STATE_INCONSISTENT = "inconsistent"
STATE_INFORMATIONAL = "informational"
STATE_GOOD = "good"
STATE_ATTENTION = "attention"
STATE_POOR = "poor"


@dataclass(frozen=True)
class Section:
    """One block of the health page.

    `families` pulls in every metric of those registry families; `keys` names
    metrics that belong here regardless of their family (completion rate is a
    generation metric but reads as performance). `headline` is the order the
    most important few are shown in.
    """

    key: str
    title: str
    question: str
    explanation: str
    families: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    headline: tuple[str, ...] = ()
    # optional split inside a section, by metric family: (title, families).
    # Used where two different things must not read as one, e.g. "retrieval
    # found the source" versus "the answer cited what it was given".
    subgroups: tuple[tuple[str, tuple[str, ...]], ...] = ()


SECTIONS: tuple[Section, ...] = (
    Section(
        key="answer_quality",
        title="Answer quality",
        question="Was the answer right, grounded and appropriately declined?",
        explanation=(
            "Whether each answer met every checkable correctness condition, stayed within what the "
            "supplied sources say, and declined only when it should have. “Raw” is the model's "
            "own text. “Final” is after the system's automatic repair step, so it describes the "
            "product rather than the model alone."
        ),
        families=(M.CORRECTNESS, M.FAITHFULNESS, M.BEHAVIOUR),
        headline=("correctness_final", "correctness_raw", "refusal_correct", "hallucination_final",
                  "faithfulness_final"),
    ),
    Section(
        key="retrieval",
        title="Retrieval and evidence",
        question="Did the system find the right regulation, and did the answer cite it?",
        explanation=(
            "Two separate questions. First, whether retrieval found the correct source text and kept "
            "it in front of the model. Second, whether the answer's citations point at sources it "
            "was actually given. A retrieval success followed by a wrong answer means the model did "
            "not use good evidence; it is not a retrieval failure."
        ),
        families=(M.EVIDENCE, M.RETRIEVAL, M.CITATION),
        headline=("retrieval_ok", "requirement_recall", "citation_ok", "recall_at_1", "mrr"),
        subgroups=(("Found by retrieval", (M.EVIDENCE, M.RETRIEVAL)),
                   ("Used in the answer", (M.CITATION,))),
    ),
    Section(
        key="validation_repair",
        title="Validation and repair",
        question="Did the system catch and repair bad answers?",
        explanation=(
            "The deterministic checks run on every generated answer, how often the repair step "
            "rewrote one, and whether the rewritten answer then passed. An answer that is correct "
            "only after repair was fixed by the pipeline, not produced by the model."
        ),
        families=(M.REPAIR,),
        keys=("valid_raw", "valid_final", "valid_raw_controlled", "correct_only_after_repair"),
        headline=("valid_final", "valid_raw", "repair_rate", "repair_success", "correct_only_after_repair"),
    ),
    Section(
        key="performance",
        title="Performance",
        question="How long did answers take, and did they finish?",
        explanation=(
            "Timing and output length. Timing depends on the machine and its load when the "
            "evaluation ran, so it is comparable only between runs on the same machine, and it "
            "is not a measure of answer quality."
        ),
        families=(M.COST,),
        keys=("completion_rate", "failed_count", "truncated_count", "degenerate_count"),
        headline=("generation_latency_p50", "generation_latency_p95", "e2e_latency_p50", "e2e_latency_p95",
                  "avg_generated_tokens"),
    ),
    Section(
        key="composition",
        title="What was measured",
        question="How big was the test, and what was left out?",
        explanation=(
            "The size and shape of the evaluation behind every number above. A percentage means "
            "little without knowing how many questions produced it."
        ),
        families=(M.DATASET,),
        headline=("questions_evaluated", "benchmark_questions", "generated_count", "skipped_count"),
    ),
    Section(
        key="human",
        title="Human review",
        question="What did a person think?",
        explanation=(
            "Scores a reviewer entered by hand. Recorded for provenance, not treated as a "
            "measurement, and not comparable across runs scored by different people."
        ),
        families=(M.HUMAN,),
        headline=("manual_score_mean",),
    ),
)

# Training metrics never appear on the health page: a loss is not an accuracy.
# Anything else without a home lands in the final catch-all so that no metric
# an adapter produced is invisible.
EXCLUDED_FAMILIES = (M.TRAINING,)
OTHER = Section(
    key="other",
    title="Other measurements",
    question="What else did this evaluation record?",
    explanation="Metrics this run reports that do not belong to one of the groups above.",
)


def _section_index() -> dict[str, str]:
    """metric key -> section key. Explicit keys win over family membership."""
    index: dict[str, str] = {}
    for section in SECTIONS:
        for family in section.families:
            for d in M.all_definitions():
                if d.family == family:
                    index.setdefault(d.key, section.key)
    for section in SECTIONS:          # explicit placements override the family default
        for key in section.keys:
            index[key] = section.key
    return index


SECTION_OF = _section_index()


# ------------------------------------------------------------------- states


def metric_state(metric: MetricResult, thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    """The state badge for one metric.

    Without a configured threshold the state is descriptive, never a verdict:
    the dashboard says the number is present, missing or internally
    inconsistent, and leaves "is that good?" to a person.
    """
    if metric.status == MISSING or metric.value is None:
        return {"state": STATE_MISSING, "reason": "not measured by this evaluation"}
    if metric.status == INCONSISTENT:
        return {"state": STATE_INCONSISTENT, "reason": metric.note or "stored value disagrees with the records"}

    rule = (thresholds or {}).get(metric.key)
    if not rule:
        if metric.direction == M.INFORMATIONAL:
            return {"state": STATE_INFORMATIONAL, "reason": "neither direction is better"}
        return {"state": STATE_AVAILABLE, "reason": "no quality threshold is configured for this metric"}

    good, attention = rule.get("good"), rule.get("attention")
    if good is None:
        return {"state": STATE_AVAILABLE, "reason": "threshold is incomplete"}
    higher = metric.direction == M.HIGHER_IS_BETTER
    meets_good = metric.value >= good if higher else metric.value <= good
    if meets_good:
        state = STATE_GOOD
    elif attention is None:
        state = STATE_POOR
    else:
        meets_attention = metric.value >= attention if higher else metric.value <= attention
        state = STATE_ATTENTION if meets_attention else STATE_POOR
    return {"state": state, "reason": f"configured threshold: good {good}, attention {attention}"}


# ----------------------------------------------------------------- sections


def build_sections(run: EvaluationRun, thresholds: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every metric the run reports, grouped, with the missing ones named."""
    have = {m.key: m for m in run.metrics}
    placed: set[str] = set()
    out: list[dict[str, Any]] = []

    for section in SECTIONS:
        keys = [k for k, s in SECTION_OF.items() if s == section.key]
        present = [have[k] for k in keys if k in have]
        order = {k: i for i, k in enumerate(section.headline)}
        present.sort(key=lambda m: (order.get(m.key, len(order)), m.key))
        placed.update(m.key for m in present)
        # named so the page can say what this evaluation does not measure,
        # instead of quietly showing a shorter list
        not_measured = sorted(k for k in keys if k not in have)
        subgroup_of = {family: title for title, families in section.subgroups for family in families}

        def grouped(payload: dict[str, Any]) -> dict[str, Any]:
            return {**payload, "subgroup": subgroup_of.get(payload["family"])}

        out.append({
            "key": section.key,
            "title": section.title,
            "question": section.question,
            "explanation": section.explanation,
            "available": len(present),
            "defined": len(keys),
            "subgroups": [title for title, _ in section.subgroups],
            "metrics": [grouped(_metric_payload(m, thresholds, section.headline)) for m in present],
            "not_measured": [grouped(_definition_stub(k)) for k in not_measured],
        })

    leftovers = [m for m in run.metrics if m.key not in placed
                 and M.definition(m.key).family not in EXCLUDED_FAMILIES]
    if leftovers:
        out.append({
            "key": OTHER.key, "title": OTHER.title, "question": OTHER.question,
            "explanation": OTHER.explanation, "available": len(leftovers), "defined": len(leftovers),
            "subgroups": [],
            "metrics": [{**_metric_payload(m, thresholds, ()), "subgroup": None} for m in leftovers],
            "not_measured": [],
        })
    return out


def _metric_payload(metric: MetricResult, thresholds: dict[str, Any] | None, headline: Iterable[str]) -> dict[str, Any]:
    d = M.definition(metric.key)
    measured = metric.value is not None and metric.status != MISSING
    return {
        **metric.to_dict(),
        "state": metric_state(metric, thresholds),
        "headline": metric.key in tuple(headline),
        "heuristic": d.heuristic,
        "family": d.family,
        "measured": measured,
        # what a reader sees when there is no number: never "0" or "0%"
        "display": None if measured else NOT_MEASURED,
    }


NOT_MEASURED = "Not measured"


def _definition_stub(key: str) -> dict[str, Any]:
    """A defined metric this evaluation did not produce: no value, and says so."""
    d = M.definition(key)
    return {"key": key, "display_name": d.name, "family": d.family, "unit": d.unit,
            "direction": d.direction, "heuristic": d.heuristic,
            "value": None, "numerator": None, "denominator": None,
            "status": MISSING, "measured": False, "display": NOT_MEASURED,
            "reason": "not measured by this evaluation"}


# ---------------------------------------------------------------- attention


@dataclass(frozen=True)
class Attention:
    """One factual count worth an engineer's look.

    `filter` is a question filter of the questions view
    (regulus.dashboard.observatory.FILTERS, plus "slow"). The count is computed
    by that filter's own predicate, so the number shown and the list the link
    opens are the same set of questions by construction.
    """

    code: str
    label: str
    filter: str
    section: str
    severity: str = "warning"


ATTENTION_RULES: tuple[Attention, ...] = (
    Attention("failed_final", "questions not marked correct in the final answer",
              "incorrect", "answer_quality", "serious"),
    Attention("failed_raw", "questions not marked correct before repair",
              "raw_incorrect", "answer_quality"),
    Attention("hallucination", "raw answers containing content found in no supplied source",
              "hallucination", "answer_quality", "serious"),
    Attention("false_refusal", "answerable questions that were declined",
              "false_refusal", "answer_quality", "serious"),
    Attention("not_generated", "questions answered without a model call (refusal or no context)",
              "no_model_answer", "answer_quality", "info"),
    Attention("retrieval_failed", "questions whose retrieval check failed",
              "retrieval_issue", "retrieval"),
    Attention("citation_failed", "answers with a citation problem",
              "citation_issue", "retrieval"),
    Attention("validation_failed", "raw answers that failed a deterministic validation check",
              "validation_failure", "validation_repair"),
    Attention("repaired", "answers changed by the repair step",
              "repaired", "validation_repair"),
    Attention("only_repair", "questions marked correct only after repair",
              "only_after_repair", "validation_repair"),
    Attention("still_invalid", "final answers still failing validation after repair",
              "still_invalid", "validation_repair"),
    Attention("truncated", "answers that reached their token allowance",
              "truncated", "performance"),
    Attention("slow", "questions at or above this run's 90th-percentile end-to-end time",
              "slow", "performance", "info"),
)


def build_attention(run: EvaluationRun) -> dict[str, Any]:
    """What needs a look, counted from the question records themselves.

    Nothing here is read from an aggregate: every count is the number of
    questions the linked filter selects, computed by the questions view's own
    predicates, so a count and the questions behind it can never disagree.
    Items keep the order of ATTENTION_RULES (grouped by section); nothing is
    ranked.
    """
    from .observatory import question_list

    listing = question_list(run)
    offered = {f["key"]: f for f in listing["filters"] if f["available"]}
    total = len(run.questions)
    items: list[dict[str, Any]] = []
    for rule in ATTENTION_RULES:
        if rule.filter not in offered:
            continue
        ids = [r["id"] for r in listing["questions"] if rule.filter in r["flags"]]
        if not ids:
            continue
        items.append({
            "code": rule.code, "label": rule.label, "count": len(ids), "denominator": total,
            "severity": rule.severity, "filter": rule.filter, "section": rule.section,
            "filter_label": offered[rule.filter]["label"],
            "description": offered[rule.filter]["description"],
            "question_ids": ids[:50],
        })

    inconsistent = [{"code": "inconsistent_metric", "label": f"{m.display_name}: {m.note}",
                     "count": 1, "denominator": None, "severity": "serious",
                     "filter": None, "section": None, "filter_label": None,
                     "description": "a stored aggregate disagrees with the question records",
                     "question_ids": []}
                    for m in run.metrics if m.status == INCONSISTENT]

    # A run that measures nothing has nothing to report, which is itself the
    # thing worth saying.
    measurable = any(
        any(getattr(q, f) is not None for q in run.questions)
        for f in ("correct_final", "correct_raw", "citation_ok", "hallucination_raw", "truncated")
    )
    return {
        # a run that measured no answer quality flags nothing (not even
        # timing): the note below is the whole finding
        "items": (items if measurable else []) + inconsistent,
        "total_questions": total,
        "measurable": measurable,
        "note": None if measurable else (
            "This evaluation records whether each question produced an answer, but not whether the "
            "answer was correct, grounded or properly cited, so there is nothing here to flag."
        ),
    }


# ------------------------------------------------------------------ summary
#
# The home page shows a few measurements in plain English. Which ones, what
# they are called there, and the sentence under each are decided here, from
# the canonical metric objects: the numerator, denominator and value are the
# metric's own, never recomputed. Everything else stays on the details page.


@dataclass(frozen=True)
class SummaryMetric:
    key: str             # canonical metric key
    label: str           # plain-English name for the home page
    population: str      # what the denominator counts, as the metric definition says
    predicate: str       # completes "<n> of <d> <population> ..." into a sentence
    section: str         # where the details live
    filter: str | None   # the questions that did not meet it (a questions-view filter)
    filter_label: str | None = None


SUMMARY_METRICS: tuple[SummaryMetric, ...] = (
    SummaryMetric("correctness_final", "Correct answers", "questions",
                  "were marked correct in the final answer.",
                  "answer_quality", "incorrect", "not marked correct"),
    SummaryMetric("valid_final", "Validation", "generated answers",
                  "passed validation after repair.",
                  "validation_repair", "still_invalid", "still failing validation"),
    SummaryMetric("citation_ok", "Citations", "generated answers",
                  "cited only sources they were given, in a valid format.",
                  "retrieval", "citation_issue", "with a citation problem"),
    SummaryMetric("retrieval_ok", "Retrieval", "questions",
                  "had the exact provisions they asked about retrieved.",
                  "retrieval", "retrieval_issue", "where retrieval missed"),
)

# The attention items the home page lists; the details page lists them all.
HOME_ATTENTION = ("failed_final", "retrieval_failed", "still_invalid", "false_refusal")

NOT_RECORDED = "No measurement was recorded for this experiment."


def _count(metric: MetricResult | None) -> tuple[int | None, int | None]:
    if metric is None or metric.value is None or metric.status == MISSING:
        return None, None
    n = metric.numerator if metric.numerator is not None else metric.value
    return (int(n) if n is not None else None,
            int(metric.denominator) if metric.denominator is not None else None)


def _summary_card(spec: SummaryMetric, metric: MetricResult | None, offered: dict[str, Any]) -> dict[str, Any]:
    measured = metric is not None and metric.value is not None and metric.status != MISSING
    n, d = _count(metric)
    link = offered.get(spec.filter) if spec.filter else None
    return {
        "key": spec.key,
        "label": spec.label,
        "definition_name": M.definition(spec.key).name,
        "unit": M.definition(spec.key).unit,
        "measured": measured,
        "value": metric.value if measured else None,
        "numerator": n if measured else None,
        "denominator": d if measured else None,
        "population": spec.population,
        "sample": f"{n} of {d} {spec.population}" if measured and n is not None and d is not None else None,
        "predicate": spec.predicate if measured and n is not None and d is not None else None,
        "sentence": (f"{n} of {d} {spec.population} {spec.predicate}" if measured and n is not None and d is not None
                     else None if measured else NOT_RECORDED),
        "display": None if measured else NOT_MEASURED,
        "section": spec.section,
        # the questions behind the shortfall, when the questions view can select them
        "filter": spec.filter if link and link["count"] else None,
        "filter_count": link["count"] if link else None,
        "filter_label": spec.filter_label,
    }


def _fact(text: str | None, keys: tuple[str, ...], filter_key: str | None, offered: dict[str, Any]) -> dict[str, Any]:
    measured = text is not None
    link = offered.get(filter_key) if filter_key else None
    return {"keys": list(keys), "measured": measured,
            "text": text if measured else f"{M.definition(keys[0]).name}: not measured in this experiment.",
            "filter": filter_key if measured and link and link["count"] else None}


def build_summary(run: EvaluationRun, attention: dict[str, Any]) -> dict[str, Any]:
    """The home page: four headline measurements, the answer pipeline in a few
    sentences, the attention items worth a first look, and response time."""
    from .observatory import question_list

    have = {m.key: m for m in run.metrics}
    offered = {f["key"]: f for f in question_list(run)["filters"] if f["available"]}

    generated, total = _count(have.get("generated_count"))
    total = total if total is not None else len(run.questions)
    repaired, answers = _count(have.get("repair_rate"))
    fixed, repairs = _count(have.get("repair_success"))
    only_repair, _ = _count(have.get("correct_only_after_repair"))
    h_raw, h_raw_d = _count(have.get("hallucination_raw"))
    h_final, h_final_d = _count(have.get("hallucination_final"))
    def were(n: int) -> str:
        return "was" if n == 1 else "were"

    def answered() -> str | None:
        if generated is None:
            return None
        if generated == total:
            return f"All {total} questions were answered by the model."
        rest = total - generated
        return (f"{generated} of {total} questions were answered by the model; the other {rest} "
                f"{were(rest)} answered by the pipeline without calling it.")

    pipeline = [
        _fact(answered(), ("generated_count",), "no_model_answer", offered),
        _fact(f"{repaired} of {answers} generated answers {were(repaired)} changed by the repair step."
              if repaired is not None else None, ("repair_rate",), "repaired", offered),
        _fact(f"{fixed} of the {repairs} repaired answer{'s' if repairs != 1 else ''} then passed validation."
              if fixed is not None and repairs else None, ("repair_success",), None, offered),
        _fact(f"{only_repair} question{'s' if only_repair != 1 else ''} {were(only_repair)} marked correct "
              "only because of the repair."
              if only_repair is not None else None, ("correct_only_after_repair",), "only_after_repair", offered),
        _fact(f"{h_raw} of {h_raw_d} answers contained content found in no supplied source before repair; "
              f"{h_final} of {h_final_d} after." if h_raw is not None and h_final is not None else None,
              ("hallucination_raw", "hallucination_final"), "hallucination", offered),
    ]

    items = {i["code"]: i for i in (attention or {}).get("items", [])}
    timing = []
    for key, label in (("e2e_latency_p50", "Median response time"), ("e2e_latency_p95", "95th percentile")):
        m = have.get(key)
        measured = m is not None and m.value is not None and m.status != MISSING
        timing.append({"key": key, "label": label, "unit": M.definition(key).unit, "measured": measured,
                       "value": m.value if measured else None, "display": None if measured else NOT_MEASURED})
    return {
        "metrics": [_summary_card(spec, have.get(spec.key), offered) for spec in SUMMARY_METRICS],
        "pipeline": pipeline,
        "attention": [items[code] for code in HOME_ATTENTION if code in items],
        "attention_total": len([i for i in items.values() if i.get("filter")]),
        "timing": timing,
        "timing_note": ("Measured on the machine that ran the evaluation. Response time is not a measure of "
                        "answer quality."),
        "questions": len(run.questions),
    }


def build_failure_breakdown(run: EvaluationRun) -> dict[str, Any]:
    """The per-layer attribution, when the evaluation produced one."""
    by_layer = dict((run.failure_summary or {}).get("by_layer") or {})
    if not by_layer:
        return {"available": False,
                "reason": "this evaluation does not attribute failures to a pipeline layer",
                "layers": [], "total": 0}
    total = sum(by_layer.values())
    layers = [{"layer": layer, "count": count, "total": total,
               "share": (count / total) if total else None,
               "filter": layer, "is_clean": layer == "none"}
              for layer, count in sorted(by_layer.items(), key=lambda kv: -kv[1])]
    return {"available": True, "reason": None, "layers": layers, "total": total,
            "by_layer_and_category": (run.failure_summary or {}).get("by_layer_and_category") or {}}


# ------------------------------------------------------------- the payload


def _model_payload(experiment: Experiment) -> dict[str, Any]:
    """Plain identity first; paths, hashes and ids behind `technical`."""
    model = experiment.model
    return {
        "label": model.label,
        "base_model": model.base_model_id if model.recorded else None,
        "adapter": model.adapter_id,
        "checkpoint": model.checkpoint,
        "revision": model.revision,
        "recorded": model.recorded,
        "applicable": model.applicable,
        "runtime": " / ".join(x for x in (model.dtype, model.device) if x) or None,
        "technical": {
            "model_key": model.key,
            "adapter_path": model.adapter_path,
            "experiment_id": experiment.experiment_id,
            "artifact_path": experiment.path,
            "source_artifacts": list(experiment.source_artifacts),
            "git_revision": experiment.git_revision,
        },
    }


def _benchmark_payload(run: EvaluationRun) -> dict[str, Any] | None:
    b = run.benchmark
    if b is None:
        return None
    return {
        "name": b.benchmark_id,
        "version": b.version,
        "questions": b.questions,
        "categories": list(b.categories),
        "label": b.label,
        "technical": {"benchmark_key": b.key, "sha256": b.sha256, "path": b.path},
    }


def _training_provenance(registry, experiment: Experiment) -> dict[str, Any]:
    """Which training run produced these weights, in one line."""
    adapter = experiment.model.adapter_id
    if not adapter:
        return {"trained": False,
                "note": "This is the base model as published; no fine-tuning was applied."}
    source = next((e for e in registry.experiments
                   if e.kind == KIND_TRAINING and e.model.adapter_id == adapter), None)
    if source is None:
        return {"trained": True, "adapter": adapter, "checkpoint": experiment.model.checkpoint,
                "training_run": None,
                "note": f"Produced by adapter {adapter}, whose training run is not on this machine."}
    run = registry.training(source.experiment_id)
    return {
        "trained": True,
        "adapter": adapter,
        "checkpoint": experiment.model.checkpoint,
        "training_run": {"experiment_id": source.experiment_id, "name": source.name,
                         "status": source.status, "completed_at": source.completed_at},
        "dataset": {k: (run.dataset or {}).get(k) for k in ("version", "train_examples_used", "generated_at_utc")} if run else {},
        "note": ("Training numbers describe how the model was fitted, not how well it answers. "
                 "They are on the Training page and are never mixed with the figures above."),
    }


def _current_evaluations(registry) -> list[Experiment]:
    """CURRENT evaluations, latest first, in the freshness engine's own order.

    There is at most one per benchmark content (the engine guarantees it), so
    this list is also the list of benchmarks the current system has a
    measurement for.
    """
    evaluations = [e for e in registry.experiments if e.kind == KIND_EVALUATION and e.status == CURRENT]
    return sorted(evaluations, key=selection_key, reverse=True)


def _coverage(sections: list[dict[str, Any]], run: EvaluationRun | None = None) -> dict[str, Any]:
    from .observatory import evidence_coverage

    available = sum(s["available"] for s in sections)
    measured = sum(1 for s in sections for m in s["metrics"] if m.get("measured"))
    not_measured = sum(len(s["not_measured"]) for s in sections) + sum(
        1 for s in sections for m in s["metrics"] if not m.get("measured"))
    families_present = sorted({m["family"] for s in sections for m in s["metrics"]})
    families_absent = [f for f in M.FAMILY_ORDER
                       if f not in families_present and f not in EXCLUDED_FAMILIES]
    return {
        "defined": len(M.all_definitions()),
        "available": available,
        # the health-relevant definitions (training excluded), split by whether
        # this evaluation produced a value for them
        "measured": measured,
        "not_measured": not_measured,
        "health_defined": measured + not_measured,
        "question_evidence": evidence_coverage(run) if run is not None else None,
        "families_present": families_present,
        "families_absent": [{"key": f, "title": M.FAMILY_TITLES[f]} for f in families_absent],
        "note": (
            f"This evaluation reports {available} of the {len(M.all_definitions())} metrics the "
            "system can measure. The rest are not shown as zero or borrowed from another run; "
            "they were simply not measured here."
        ),
    }


def _evaluation_payload(experiment: Experiment, run: EvaluationRun) -> dict[str, Any]:
    return {
        "experiment_id": experiment.experiment_id,
        "name": experiment.name,
        "status": experiment.status,
        "status_reason": experiment.status_reason,
        "freshness_code": experiment.freshness_code,
        # the freshness engine's own per-check outcomes (model, pipeline,
        # question set); the page displays them and decides nothing
        "freshness_checks": dict(experiment.freshness_checks),
        "completed_at": experiment.completed_at,
        "started_at": run.started_at,
        "duration_seconds": run.duration_seconds,
        "path": experiment.path,
        "questions_evaluated": len(run.questions),
        "question_set": dict(experiment.question_set),
        "pipeline_fingerprint": experiment.pipeline_fingerprint,
        "schema": run.schema,
        "problems": list(run.problems),
    }


def benchmark_health(registry, experiment: Experiment, thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    """One benchmark's block: only that evaluation's own numbers."""
    run = registry.evaluation(experiment.experiment_id)
    sections = build_sections(run, thresholds)
    attention = build_attention(run)
    return {
        "benchmark": _benchmark_payload(run),
        "evaluation": _evaluation_payload(experiment, run),
        "sections": sections,
        "attention": attention,
        "summary": build_summary(run, attention),
        "failure_breakdown": build_failure_breakdown(run),
        "coverage": _coverage(sections, run),
    }


def _why_not_current(registry) -> dict[str, int]:
    """How many evaluations fell at each freshness check: the answer to
    'why is nothing current?' in counts, not prose."""
    counts: dict[str, int] = {}
    for e in registry.experiments:
        if e.kind == KIND_EVALUATION:
            code = e.freshness_code or "unknown"
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def current_health(registry, thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the health page shows, for the currently configured system.

    Only CURRENT evaluations are used: those the freshness engine proved
    measure the configured weights and pipeline on a whole benchmark. With
    none, the answer is `not_evaluated`, never another run's numbers.
    """
    current = registry.current_model()
    configured = current["model"]
    evaluations = _current_evaluations(registry)
    common = {
        "configured_model": configured,
        "current_model": configured,
        "current_system": current["system"],
        "effective_model_key": current["effective_model_key"],
        "evaluations_by_freshness": _why_not_current(registry),
    }

    if not evaluations:
        return {
            **common,
            "state": "not_evaluated",
            "status": "not_evaluated",
            "reason": "no_current_evaluation" if current["resolved"] else "current_system_unresolved",
            "headline": "This model has not been evaluated",
            "explanation": (
                "No evaluation on this machine measured the model the system is configured to run. "
                "Every result on the other pages was produced by different weights, a different "
                "adapter or checkpoint, a different pipeline configuration, or only part of a "
                "benchmark, and none of them describes what this system does today."
            ),
            "evaluation": None,
            "benchmarks": [],
            "latest_available": _latest_available(registry),
            "sections": [], "attention": None, "failure_breakdown": None,
            "coverage": {"defined": len(M.all_definitions()), "available": 0},
        }

    # One block per benchmark the current system was measured on. Nothing is
    # pooled across them: a different question set is a different measurement.
    # The latest leads the page; the others are named, not hidden.
    blocks = [benchmark_health(registry, e, thresholds) for e in evaluations]
    lead, experiment = blocks[0], evaluations[0]
    others = evaluations[1:]
    return {
        **common,
        "state": "evaluated",
        "status": "evaluated",
        "reason": "current_evaluation",
        "headline": None,
        "is_current": True,
        "current_evaluation": _evaluation_ref(experiment),
        "model": _model_payload(experiment),
        "evaluation": lead["evaluation"],
        "benchmark": lead["benchmark"],
        "sections": lead["sections"],
        "attention": lead["attention"],
        "summary": lead["summary"],
        "failure_breakdown": lead["failure_breakdown"],
        "coverage": lead["coverage"],
        "benchmarks": blocks,
        "training": _training_provenance(registry, experiment),
        "thresholds_configured": bool(thresholds),
        "other_current_evaluations": [
            {"experiment_id": e.experiment_id, "name": e.name,
             "benchmark": e.benchmark.label if e.benchmark else None,
             "benchmark_key": e.benchmark.key if e.benchmark else None,
             "completed_at": e.completed_at}
            for e in others
        ],
        "other_current_note": (
            "This model also has a current evaluation on a different benchmark. Its numbers are not "
            "mixed into these: a different question set is a different measurement, not a second opinion."
            if others else None
        ),
    }


def _evaluation_ref(experiment: Experiment | None) -> dict[str, Any] | None:
    if experiment is None:
        return None
    return {"experiment_id": experiment.experiment_id, "name": experiment.name,
            "status": experiment.status, "completed_at": experiment.completed_at}


def experiment_analysis(registry, experiment_id: str, thresholds: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The model-analysis payload for one evaluation, current or not.

    The same blocks as the current-model page (identity, sections, attention,
    failure breakdown, coverage), built by the same functions from that one
    evaluation's own records. Whether it is the current model's evaluation is
    the freshness engine's verdict, reported here, never inferred by the page.
    None when the id is not an evaluation.
    """
    experiment = registry.experiment(experiment_id)
    if experiment is None or experiment.kind != KIND_EVALUATION or registry.evaluation(experiment_id) is None:
        return None
    current = registry.current_model()
    lead = next(iter(_current_evaluations(registry)), None)
    is_current = experiment.status == CURRENT
    return {
        "state": "evaluated",
        "is_current": is_current,
        "current_evaluation": _evaluation_ref(lead),
        "current_model": current["model"],
        "current_system": current["system"],
        "effective_model_key": current["effective_model_key"],
        "model": _model_payload(experiment),
        "training": _training_provenance(registry, experiment),
        **benchmark_health(registry, experiment, thresholds),
        "note": None if is_current else (
            "This is not the current model's evaluation. Its numbers describe what it measured and are "
            "shown only because it was opened explicitly; they are not the current model's results."
        ),
    }


def _latest_available(registry) -> dict[str, Any] | None:
    """The newest evaluation there is, labelled with its real status.

    Offered so the page is not a dead end, and deliberately without its
    metrics: it did not measure the current model.
    """
    candidates = [e for e in registry.experiments if e.kind == KIND_EVALUATION and e.completed_at]
    if not candidates:
        return None
    latest = max(candidates, key=lambda e: e.completed_at)
    return {
        "experiment_id": latest.experiment_id,
        "name": latest.name,
        "status": latest.status,
        "status_reason": latest.status_reason,
        "completed_at": latest.completed_at,
        "model": latest.model.to_dict(),
        "benchmark": latest.benchmark.to_dict() if latest.benchmark else None,
        "warning": (
            "These are not the current model's results. The metrics are deliberately not shown "
            "here; open the experiment if you want to see what it measured."
        ),
    }


# ------------------------------------------------------------------ history


HISTORY_KEYS = (
    "correctness_final", "correctness_raw", "valid_raw", "retrieval_ok", "requirement_recall",
    "recall_at_1", "mrr", "citation_ok", "faithfulness_raw", "hallucination_raw", "repair_rate",
    "completion_rate", "e2e_latency_p50", "avg_generation_seconds", "avg_generated_tokens",
    "tokens_per_second",
)


def current_history(registry) -> dict[str, Any]:
    """How the current model has moved, on one benchmark, over time.

    Only runs that share both the current model's identity and its benchmark
    content are plotted: a different checkpoint or a different question set is
    a different measurement, not a later point on the same line. Runs of other
    models on the same benchmark are returned separately, as markers, so the
    page can say "the model changed here" without drawing them as one series.
    """
    evaluations = _current_evaluations(registry)
    if not evaluations:
        return {"available": False, "reason": "the current model has no evaluation to anchor a history to",
                "points": [], "series": [], "model_changes": []}

    anchor = evaluations[0]
    model_key = anchor.model.key
    benchmark_key = anchor.benchmark.key if anchor.benchmark else None
    fingerprint = (anchor.pipeline_fingerprint or {}).get("value")

    # One line = the same weights, the same benchmark content, the same
    # pipeline fingerprint and the whole benchmark: only CURRENT runs and the
    # earlier runs they superseded qualify.
    same = [e for e in registry.experiments
            if e.kind == KIND_EVALUATION and e.completed_at
            and e.status in (CURRENT, STALE) and e.freshness_code in ("current", "superseded")
            and e.model.key == model_key
            and (e.benchmark.key if e.benchmark else None) == benchmark_key
            and (e.pipeline_fingerprint or {}).get("value") == fingerprint]
    same.sort(key=selection_key)

    points: list[dict[str, Any]] = []
    for experiment in same:
        run = registry.evaluation(experiment.experiment_id)
        if run is None:
            continue
        values = {m.key: {"value": m.value, "numerator": m.numerator, "denominator": m.denominator,
                          "unit": m.unit, "direction": m.direction, "status": m.status}
                  for m in run.metrics if m.key in HISTORY_KEYS and m.value is not None}
        points.append({
            "experiment_id": experiment.experiment_id, "name": experiment.name,
            "status": experiment.status, "completed_at": experiment.completed_at,
            "is_current": experiment.experiment_id == anchor.experiment_id,
            "questions": len(run.questions), "metrics": values,
        })

    keys = [k for k in HISTORY_KEYS if any(k in p["metrics"] for p in points)]
    series = [{
        "key": key,
        "display_name": M.definition(key).name,
        "unit": M.definition(key).unit,
        "direction": M.definition(key).direction,
        "heuristic": M.definition(key).heuristic,
        "points": [{"completed_at": p["completed_at"], "name": p["name"],
                    "experiment_id": p["experiment_id"], "is_current": p["is_current"],
                    **p["metrics"][key]}
                   for p in points if key in p["metrics"]],
    } for key in keys]

    changes = [{
        "experiment_id": e.experiment_id, "name": e.name, "completed_at": e.completed_at,
        "model": e.model.label, "model_key": e.model.key, "status": e.status,
        "note": "a different model on the same benchmark: a separate series, not a later point",
    } for e in registry.experiments
        if e.kind == KIND_EVALUATION and e.completed_at and e.model.key != model_key
        and (e.benchmark.key if e.benchmark else None) == benchmark_key]
    changes.sort(key=lambda c: c["completed_at"])

    return {
        "available": bool(points),
        "reason": None if points else "no run shares this model and benchmark",
        "model": anchor.model.to_dict(),
        "benchmark": anchor.benchmark.to_dict() if anchor.benchmark else None,
        "points": points,
        "series": series,
        "model_changes": changes,
        "note": (
            "Every point measures the same weights, pipeline configuration and whole benchmark. A run "
            "with a different adapter, checkpoint, pipeline or question set is not on this line."
        ),
    }
