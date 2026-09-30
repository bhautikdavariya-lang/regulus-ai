"""Adapter for a Stage 5 evaluation run directory.

A Stage 5 run directory is produced by `scripts/run_stage5.py` and looks like
`artifacts/stage5_stage6/<run_id>/stage5/`. It holds a run manifest, a dozen
aggregate JSON files, three per-question JSONL files and three phase markers.

This adapter opens those files and nothing else. It does not connect to the
database, does not load a model, and does not write anything back.

Two principles run through it:

* Every proportion is recounted from the per-question records and compared
  with the aggregate the evaluator stored. The stored value is what gets
  displayed; a disagreement is surfaced as an `inconsistent` metric with a
  note. A bug in the evaluator is reported, never quietly corrected here.
* Nothing absent from the artifacts is invented. Where Stage 5 does not
  record something, the field stays empty and the run carries a problem
  explaining what is missing and what follows from that.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .. import metrics as M
from ..fingerprint import FINGERPRINT_VERSION, PipelineFingerprint, pipeline_fingerprint, question_set_identity
from ..schemas import (
    COMPLETE,
    INCOMPLETE,
    INCONSISTENT,
    KIND_EVALUATION,
    MISSING,
    UNRECORDED,
    BenchmarkIdentity,
    EvaluationRun,
    MetricResult,
    ModelIdentity,
    QuestionResult,
    stable_id,
)

SCHEMA = "stage5/v1"

MANIFEST = "run_manifest.json"
SUMMARY = "stage5_summary.json"
EVIDENCE = "evidence_records.jsonl"
FULL = "generation_full.jsonl"
CONTROLLED = "generation_controlled.jsonl"

HALLUCINATION_CODES = (
    "asserted_missing_provision", "unsupported_figure",
    "discovery_cited_for_requirement", "citation_mismatch",
    "provision_citation_mismatch",
)
DEGENERATE_CODES = ("degenerate_output", "empty_output")


# --------------------------------------------------------------- file access


def _json(path: Path) -> Any | None:
    """Read a JSON file, or None if it is absent or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file. A truncated final line is skipped, not fatal:
    a run interrupted mid-write still has every complete record before it."""
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _by_id(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in rows if isinstance(r, dict) and "id" in r}


def _get(obj: Any, *path: str, default: Any = None) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
    return default if obj is None else obj


# ------------------------------------------------------------------- metrics


def _count_metric(
    key: str, count: int | None, total: int | None = None, *,
    stored: Any = None, source: str | None = None,
) -> MetricResult:
    """A count, cross-checked against the count the evaluator stored.

    A count out of zero applicable questions (false answers when no question
    expected a refusal) was not measured: it is reported missing, never 0.
    """
    status = None
    note = None
    if count is not None and total == 0:
        count, total = None, None
        status, note = MISSING, "no applicable questions in this run, so this was not measured"
    elif count is None:
        status, note = MISSING, "not recorded by this run"
    elif isinstance(stored, (int, float)) and int(stored) != int(count):
        status = INCONSISTENT
        note = f"stored value {stored} disagrees with {count} recounted from the per-question records"
    return M.make_metric(
        key, None if count is None else float(count),
        numerator=count, denominator=total, source=source, status=status, note=note,
        recomputed_from="per-question records" if count is not None else None,
    )


def _scalar_metric(
    key: str, value: float | None, *, stored: float | None = None,
    tolerance: float = 0.05, source: str | None = None, note: str | None = None,
    recomputed_from: str | None = "per-question records",
) -> MetricResult:
    """A number that is not a proportion (a mean, a percentile, a duration).

    `value` is what the dashboard recomputed from `recomputed_from`; `stored`
    is the evaluator's aggregate. The stored value is displayed; a
    disagreement beyond `tolerance` makes the metric inconsistent.
    """
    status = None
    if value is None and stored is None:
        return M.make_metric(key, None, source=source, status=MISSING, note=note or "not recorded by this run")
    shown = stored if stored is not None else value
    if stored is not None and value is not None and abs(stored - value) > tolerance:
        status = INCONSISTENT
        note = f"stored value {stored} disagrees with {value} recomputed from the {recomputed_from}"
    return M.make_metric(key, shown, source=source, status=status, note=note,
                         recomputed_from=recomputed_from if value is not None else None)


def _ordered(results: Iterable[MetricResult]) -> tuple[MetricResult, ...]:
    """Group the metrics by family so the UI renders a stable order."""
    order = {family: i for i, family in enumerate(M.FAMILY_ORDER)}
    rows = list(results)
    return tuple(sorted(rows, key=lambda m: (order.get(M.definition(m.key).family, 99), rows.index(m))))


# ------------------------------------------------------------------- detect


def detect(path: str | Path) -> bool:
    """True for a directory that looks like a Stage 5 run.

    Detection deliberately needs only the manifest, which the runner writes
    before any work happens. A run that died during generation is therefore
    still detected, and `load` reports it as INCOMPLETE instead of the
    registry filing it as an unknown schema.
    """
    directory = Path(path)
    if not directory.is_dir():
        return False
    manifest = _json(directory / MANIFEST)
    if not isinstance(manifest, dict):
        return False
    return all(k in manifest for k in ("run_id", "dataset_sha256", "config"))


# ---------------------------------------------------------------- identities


def _model_identity(manifest: dict[str, Any], problems: list[str]) -> ModelIdentity:
    """The weights the run evaluated, exactly as its manifest recorded them.

    Manifests from schema version 2 carry a `model` block written from the
    loaded model. Older manifests store the RAG configuration only, and
    `scripts/run_stage5.py --adapter` left no trace, so their identity is
    reported as unrecorded: it is never inferred, never assumed to be the
    base model, and never taken from today's configuration. The base model id
    printed in `STAGE5_FINAL_REPORT.md` is a hard-coded string in the report
    template, not a measurement, so it is not parsed either.
    """
    block = manifest.get("model")
    reason = manifest.get("identity_unrecorded_reason")
    if not isinstance(block, dict) or not block.get("id"):
        problems.append(
            "model identity is not recorded by this Stage 5 run: "
            + (f"{reason}. " if reason else
               "run_manifest.json stores the retrieval and generation configuration only, and the --adapter "
               "option leaves no trace in any structured artifact. ")
            + "This run is therefore not comparable to another run on model identity, and the dashboard must "
            "not present it as a measurement of any particular set of weights."
        )
        return ModelIdentity(base_model_id=UNRECORDED)
    identity = ModelIdentity(
        base_model_id=str(block["id"]),
        revision=block.get("revision"),
        adapter_id=block.get("adapter_name"),
        adapter_path=block.get("adapter_dir"),
        checkpoint=block.get("checkpoint"),
        dtype=block.get("dtype"),
        device=block.get("device"),
    )
    if identity.checkpoint_unresolved:
        problems.append(
            f"the manifest names adapter {identity.adapter_id} but no checkpoint, so the evaluated weights are "
            "unresolved: every checkpoint of an adapter is a different model"
        )
    if not identity.revision:
        problems.append("the manifest records no base-model revision, so the base weights are named but not pinned")
    return identity


def _fingerprint(manifest: dict[str, Any], problems: list[str]) -> dict[str, Any] | None:
    """The recorded pipeline fingerprint, re-derived from the recorded config.

    A fingerprint that does not match its own evaluation_config is still
    shown, marked unverified: the manifest is reported, not corrected.
    """
    recorded = PipelineFingerprint.from_dict(manifest.get("pipeline_fingerprint"))
    if recorded is None:
        if manifest.get("pipeline_fingerprint") is not None:
            problems.append("run_manifest.json has a pipeline_fingerprint this dashboard cannot read")
        return None
    config = manifest.get("evaluation_config")
    verified: bool | None = None
    if isinstance(config, dict) and recorded.version == FINGERPRINT_VERSION:
        verified = pipeline_fingerprint(config).value == recorded.value
        if not verified:
            problems.append(
                f"the recorded pipeline fingerprint {recorded.short} does not match the evaluation_config stored "
                "beside it; the manifest may have been edited or written by a different fingerprint scheme"
            )
    return {**recorded.to_dict(), "verified": verified}


def _question_set(
    evaluated_ids: list[str], source: str, benchmark_rows: list[dict[str, Any]] | None,
    benchmark_total: int | None,
) -> dict[str, Any]:
    """Identity of the questions this run actually produced records for.

    `full_benchmark` is True only when that set equals the benchmark's own id
    set (which needs the verified benchmark file), False when it provably
    does not (fewer questions than the benchmark holds, or a different set),
    and None when it cannot be decided from here.
    """
    evaluated = question_set_identity(evaluated_ids)
    full: bool | None = None
    if benchmark_rows is not None:
        full = evaluated.sha256 == question_set_identity(r["id"] for r in benchmark_rows if "id" in r).sha256
    elif benchmark_total is not None and evaluated.count != benchmark_total:
        full = False
    return {**evaluated.to_dict(), "source": source, "benchmark_questions": benchmark_total, "full_benchmark": full}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None  # a naive time cannot be ordered safely


def _benchmark_identity(
    manifest: dict[str, Any], summary: dict[str, Any] | None, root: Path | None,
    records: list[dict[str, Any]], problems: list[str],
) -> tuple[BenchmarkIdentity, list[dict[str, Any]] | None]:
    """Benchmark identity, and the benchmark rows when they can be verified.

    The manifest carries the dataset path and its sha256, which is enough for
    the benchmark key on its own. The file itself is opened only to enrich
    the identity and to recount the two metrics whose denominators live in
    the question expectations. If its content hash does not match what the
    run recorded, it is a different file and its content is not used.
    """
    declared = str(manifest.get("dataset") or "")
    sha = manifest.get("dataset_sha256")
    name = Path(declared).stem or "unknown"

    candidates = [Path(declared)] if declared else []
    if root is not None and declared:
        candidates.append(root / "data" / "evaluation" / "datasets" / Path(declared).name)
    rows: list[dict[str, Any]] | None = None
    for candidate in candidates:
        if not candidate.is_file():
            continue
        actual = _sha256(candidate)
        if sha and actual != sha:
            problems.append(
                f"benchmark file {candidate.as_posix()} has sha256 {actual} but the run recorded "
                f"{sha}; its content was not used, and the run's own hash identifies the benchmark"
            )
            break
        rows = [json.loads(line) for line in candidate.read_text(encoding="utf-8").splitlines() if line.strip()]
        break
    else:
        if declared:
            problems.append(
                f"benchmark file {declared} is not readable from here, so per-question expectations "
                "could not be reloaded; metrics whose denominator lives in the benchmark are reported "
                "without a numerator and denominator"
            )

    total = _get(summary, "dataset", "questions_total")
    if rows is not None:
        total = len(rows)
    if total is None:
        total = len(manifest.get("questions") or [])
    categories = (
        sorted({str(r.get("category")) for r in rows if r.get("category")}) if rows is not None
        else sorted({str(r.get("category")) for r in records if r.get("category")})
    )
    identity = BenchmarkIdentity(
        benchmark_id=name,
        path=declared or None,
        sha256=sha,
        questions=total,
        categories=tuple(categories),
    )
    return identity, rows


# ------------------------------------------------------- metric construction


def _evidence_metrics(
    records: list[dict[str, Any]], retrieval: dict | None, coverage: dict | None,
    selection: dict | None,
) -> list[MetricResult]:
    if not records:
        return []
    total = len(records)
    out: list[MetricResult] = []

    out.append(M.ratio_metric(
        "retrieval_ok", sum(1 for r in records if r.get("retrieval_ok")), total,
        stored=_get(retrieval, "retrieval_ok"), source="retrieval_results.json",
    ))

    # Requirement recall is pooled over provisions, not questions, exactly as
    # the evaluator pools it: every expected exact label of every question.
    with_exact = [r for r in records if _get(r, "retrieval", "expected_exact", default=[])]
    expected_total = sum(len(_get(r, "retrieval", "expected_exact", default=[])) for r in with_exact)
    hit_total = sum(
        len([lab for lab in _get(r, "retrieval", "expected_exact", default=[])
             if lab in _get(r, "retrieval", "retrieved_exact", default=[])])
        for r in with_exact
    )
    out.append(M.ratio_metric(
        "requirement_recall", hit_total, expected_total,
        stored=_get(retrieval, "requirement_recall"), source="retrieval_results.json",
    ))
    out.append(M.ratio_metric(
        "question_recall",
        sum(1 for r in with_exact if _get(r, "retrieval", "exact_recall") == 1.0), len(with_exact),
        stored=_get(retrieval, "questions_with_full_exact_recall"), source="retrieval_results.json",
    ))

    out.append(M.ratio_metric(
        "coverage_ok", sum(1 for r in records if r.get("coverage_ok")), total,
        stored=_get(coverage, "coverage_ok"), source="coverage_results.json",
    ))
    with_missing = [r for r in records if _get(r, "coverage", "expected_missing", default=[])]
    out.append(M.ratio_metric(
        "coverage_missing_ok",
        sum(1 for r in with_missing
            if set(_get(r, "coverage", "missing", default=[])) == set(_get(r, "coverage", "expected_missing", default=[]))),
        len(with_missing),
        stored=_get(coverage, "missing_labels_exact_match"), source="coverage_results.json",
    ))

    out.append(M.ratio_metric(
        "selection_ok", sum(1 for r in records if r.get("selection_ok")), total,
        stored=_get(selection, "selection_ok"), source="selection_results.json",
    ))
    out.append(M.ratio_metric(
        "protected_preserved",
        sum(1 for r in with_exact
            if all(_get(r, "selection", "required_present_in_context", default={}).values())),
        len(with_exact),
        stored=_get(selection, "required_exact_preserved"), source="selection_results.json",
    ))
    out.append(M.ratio_metric(
        "evidence_deterministic", sum(1 for r in records if r.get("deterministic")), total,
        stored=_get(selection, "deterministic"), source="evidence_records.jsonl",
    ))
    return out


def _generation_metrics(
    full: list[dict[str, Any]], controlled: list[dict[str, Any]], generation: dict | None,
) -> list[MetricResult]:
    if not full:
        return []
    gen = [r for r in full if r.get("generated")]
    stored_full = _get(generation, "modes", "full_pipeline_raw", default={})
    stored_ctrl = _get(generation, "modes", "controlled_evidence_raw", default={})
    out: list[MetricResult] = [
        M.ratio_metric("valid_raw", sum(1 for r in gen if r.get("valid_raw")), len(gen),
                       stored=stored_full.get("valid_raw"), source="generation_full.jsonl"),
        M.ratio_metric("valid_final", sum(1 for r in gen if r.get("valid_final")), len(gen),
                       stored=stored_full.get("valid_final"), source="generation_full.jsonl"),
        _count_metric("generated_count", len(gen), len(full),
                      stored=stored_full.get("generated"), source="generation_full.jsonl"),
        _count_metric("skipped_count", sum(1 for r in full if not r.get("generated")), len(full),
                      source="generation_full.jsonl"),
        _count_metric("truncated_count", sum(1 for r in gen if _get(r, "tokens", "truncated")), len(gen),
                      stored=stored_full.get("truncated"), source="generation_full.jsonl"),
        _count_metric(
            "degenerate_count",
            sum(1 for r in gen if any(c in DEGENERATE_CODES for c in _get(r, "validation_initial", "codes", default=[]))),
            len(gen), source="generation_full.jsonl",
        ),
        _count_metric("questions_evaluated", len(full), None, source="generation_full.jsonl"),
    ]

    tokens = [_get(r, "tokens", "generated") for r in gen]
    tokens = [t for t in tokens if isinstance(t, (int, float))]
    out.append(_scalar_metric(
        "avg_generated_tokens",
        round(sum(tokens) / len(tokens), 1) if tokens else None,
        stored=stored_full.get("mean_generated_tokens"), tolerance=0.1, source="generation_full.jsonl",
    ))

    if controlled:
        cgen = [r for r in controlled if r.get("generated")]
        out.append(M.ratio_metric(
            "valid_raw_controlled", sum(1 for r in cgen if r.get("valid_raw")), len(cgen),
            stored=stored_ctrl.get("valid_raw"), source="generation_controlled.jsonl",
        ))
    return out


def _correctness_metrics(correctness: dict | None) -> list[MetricResult]:
    rows = _get(correctness, "per_question", default=[])
    if not rows:
        return []
    total = len(rows)
    only_after = [r["id"] for r in rows if r.get("final_correct") and not r.get("raw_correct")]
    return [
        M.ratio_metric("correctness_raw", sum(1 for r in rows if r.get("raw_correct")), total,
                       stored=_get(correctness, "raw_correct"), source="correctness_results.json"),
        M.ratio_metric("correctness_final", sum(1 for r in rows if r.get("final_correct")), total,
                       stored=_get(correctness, "final_correct"), source="correctness_results.json"),
        _count_metric("correct_only_after_repair", len(only_after), total,
                      stored=len(_get(correctness, "correct_only_after_repair", default=[])),
                      source="correctness_results.json"),
    ]


def _faithfulness_metrics(faith: dict | None, full: list[dict[str, Any]]) -> list[MetricResult]:
    """Raw and final are read from their own blocks and never merged.

    The evaluator stores the two separately for exactly this reason: the
    final figure is the repair layer's work, not the model's.
    """
    out: list[MetricResult] = []
    gen = [r for r in full if r.get("generated")]
    for stage, block_key, ratio_key, count_key in (
        ("faithfulness", "raw_answer", "faithfulness_raw", "unsupported_sentences_raw"),
        ("faithfulness_final", "final_answer", "faithfulness_final", "unsupported_sentences_final"),
    ):
        stored = _get(faith, block_key, default={}) if faith else {}
        claims = [c for r in gen for c in _get(r, stage, "claims", default=[])]
        judged = [c for c in claims if c.get("supported") in ("YES", "NO", "UNCERTAIN")]
        supported = sum(1 for c in judged if c.get("supported") == "YES")
        unsupported = sum(1 for c in judged if c.get("supported") == "NO")
        out.append(M.ratio_metric(
            ratio_key, supported if judged else None, len(judged) or None,
            stored=stored.get("supported_ratio"), source="semantic_faithfulness_results.json",
        ))
        out.append(_count_metric(
            count_key, unsupported if judged else None, len(judged) or None,
            stored=stored.get("unsupported"), source="semantic_faithfulness_results.json",
        ))
    return out


def _hallucination_metrics(full: list[dict[str, Any]], hall: dict | None) -> list[MetricResult]:
    gen = [r for r in full if r.get("generated")]
    if not gen:
        return []
    return [
        M.ratio_metric("hallucination_raw", sum(1 for r in gen if _get(r, "hallucination", "any_raw")), len(gen),
                       stored=_get(hall, "any_raw"), source="hallucination_results.json"),
        M.ratio_metric("hallucination_final", sum(1 for r in gen if _get(r, "hallucination", "any_final")), len(gen),
                       stored=_get(hall, "any_final"), source="hallucination_results.json"),
    ]


def _citation_metrics(full: list[dict[str, Any]], citation: dict | None) -> list[MetricResult]:
    gen = [r for r in full if r.get("generated")]
    if not gen:
        return []
    explicit = [r for r in gen if _get(r, "completeness", "expected_exact_ids", default=[])]
    satisfied = sum(_get(r, "citations", "requirements_satisfied", default=0) for r in explicit)
    exact_cited = sum(_get(r, "citations", "requirements_with_exact_cited", default=0) for r in explicit)
    return [
        M.ratio_metric("citation_ok", sum(1 for r in gen if _get(r, "citations", "citation_ok")), len(gen),
                       stored=_get(citation, "citation_ok"), source="citation_results.json"),
        M.ratio_metric("exact_source_citation", exact_cited, satisfied,
                       stored=_get(citation, "requirements_with_exact_source_cited"),
                       source="citation_results.json"),
    ]


def _refusal_metrics(full: list[dict[str, Any]], refusal: dict | None) -> list[MetricResult]:
    rows = [r for r in full if "refusal" in r]
    if not rows:
        return []
    expect_refuse = [r for r in rows if r.get("expected_behavior") == "refuse"]
    expect_answer = [r for r in rows if r.get("expected_behavior") != "refuse"]
    return [
        M.ratio_metric("refusal_correct",
                       sum(1 for r in expect_refuse if _get(r, "refusal", "correct_refusal")), len(expect_refuse),
                       stored=_get(refusal, "correct_refusal"), source="refusal_results.json"),
        _count_metric("false_refusal_count",
                      sum(1 for r in expect_answer if _get(r, "refusal", "false_refusal")), len(expect_answer),
                      stored=len(_get(refusal, "false_refusal_raw", default=[])) if refusal else None,
                      source="refusal_results.json"),
        _count_metric("false_answer_count",
                      sum(1 for r in expect_refuse if _get(r, "refusal", "false_answer")), len(expect_refuse),
                      stored=len(_get(refusal, "false_answer", default=[])) if refusal else None,
                      source="refusal_results.json"),
    ]


def _domain_metrics(domain: dict | None) -> list[MetricResult]:
    rows = [r for r in _get(domain, "per_question", default=[]) if r.get("domain") == "out_of_domain"]
    if not rows:
        return []
    return [M.ratio_metric(
        "domain_leak_rate", sum(1 for r in rows if r.get("leak_raw")), len(rows),
        stored=_get(domain, "out_of_domain_leak_raw"), source="domain_boundary_results.json",
    )]


def _behaviour_metrics(
    full: list[dict[str, Any]], behaviour: dict | None, benchmark: list[dict[str, Any]] | None,
) -> list[MetricResult]:
    out: list[MetricResult] = []

    def addressed(categories: tuple[str, ...], key: str, stored_block: str) -> MetricResult | None:
        gen = [r for r in full if r.get("category") in categories and r.get("generated")]
        if not gen:
            return None
        return M.ratio_metric(
            key, sum(1 for r in gen if _get(r, "completeness", "all_addressed_raw")), len(gen),
            stored=_get(behaviour, stored_block, "all_provisions_addressed_raw"),
            source="behaviour_results.json",
        )

    for metric in (
        addressed(("multi",), "multi_provision_accuracy", "multi_provision"),
        addressed(("range", "long"), "range_accuracy", "range"),
    ):
        if metric is not None:
            out.append(metric)

    # The denominator here is "questions that expect a missing provision",
    # which lives in the benchmark, not in the run records. Without a
    # verified benchmark the stored rate is shown with no counts rather than
    # with a guessed denominator.
    stored_partial = _get(behaviour, "partial_or_missing", "absent_provision_named_in_final_answer")
    numerator = denominator = None
    if benchmark is not None:
        expectations = {r["id"]: r.get("expected_missing") or [] for r in benchmark if "id" in r}
        rows = [r for r in full if expectations.get(r["id"])]
        denominator = len(rows) or None
        if denominator:
            numerator = sum(
                1 for r in rows
                if all(label in (r.get("answer_final") or "") for label in expectations[r["id"]])
            )
    if stored_partial is not None or denominator:
        out.append(M.ratio_metric(
            "partial_behaviour_ok", numerator, denominator,
            stored=stored_partial, source="behaviour_results.json",
        ))
    return out


def _repair_metrics(full: list[dict[str, Any]], repair: dict | None) -> list[MetricResult]:
    gen = [r for r in full if r.get("generated")]
    if not gen:
        return []
    repaired = [r for r in gen if r.get("repair")]
    return [
        M.ratio_metric("repair_rate", len(repaired), len(gen),
                       stored=_get(repair, "repair_frequency"), source="repair_results.json"),
        M.ratio_metric("repair_success", sum(1 for r in repaired if r.get("valid_final")), len(repaired) or None,
                       source="repair_results.json"),
    ]


def _latency_metrics(latency: dict | None, full: list[dict[str, Any]]) -> list[MetricResult]:
    """Latency percentiles recomputed from the per-question timings.

    Uses the evaluator's own percentile (`regulus.stage5.report._pct`) over
    the same populations it uses: generation time over generated answers,
    end-to-end time over every question with timings. A question whose
    timing is absent is left out, never counted as zero. The stored aggregate
    is still what is displayed; a disagreement of more than 0.05 s makes the
    metric inconsistent. Stage 5 stores milliseconds; the registry declares
    seconds.
    """
    from regulus.stage5.report import _pct

    populations = {
        "generation": [_get(r, "timings_ms", "generation_ms") for r in full if r.get("generated")],
        "end_to_end": [_get(r, "timings_ms", "total_ms") for r in full if r.get("timings_ms")],
    }
    populations = {k: [v for v in vs if isinstance(v, (int, float))] for k, vs in populations.items()}
    if not latency and not any(populations.values()):
        return []
    out: list[MetricResult] = []
    for key, phase, percentile in (
        ("generation_latency_p50", "generation", "p50"),
        ("generation_latency_p95", "generation", "p95"),
        ("e2e_latency_p50", "end_to_end", "p50"),
        ("e2e_latency_p95", "end_to_end", "p95"),
    ):
        stored_ms = _get(latency, "phases_ms", phase, percentile)
        values = populations[phase]
        recomputed_ms = _pct(values, 50 if percentile == "p50" else 95) if values else None
        out.append(_scalar_metric(
            key, None if recomputed_ms is None else round(recomputed_ms / 1000.0, 3),
            stored=None if stored_ms is None else round(stored_ms / 1000.0, 3),
            tolerance=0.05, source="latency_results.json",
            recomputed_from=f"per-question timings_ms in generation_full.jsonl ({len(values)} questions)",
            note=(f"stored {stored_ms} ms; recomputed from {len(values)} per-question timings"
                  if stored_ms is not None else f"recomputed from {len(values)} per-question timings; no stored aggregate"),
        ))
    return out


# ----------------------------------------------------------- question records


def _question(
    qid: str, benchmark: dict[str, Any] | None, evidence: dict | None, full: dict | None,
    controlled: dict | None, correctness: dict | None, failure: dict | None, domain: dict | None,
) -> QuestionResult:
    ev = evidence or {}
    fr = full or {}
    comp = fr.get("completeness") or {}
    sel = ev.get("selection") or {}
    ret = ev.get("retrieval") or {}
    cov = ev.get("coverage") or {}

    # Evidence ids by tier, taken from the per-requirement coverage record.
    # Stage 5 stores evidence identifiers and counts, not the source text.
    by_tier: dict[str, list[dict[str, Any]]] = {}
    for requirement in cov.get("requirements") or []:
        for tier in ("exact", "structural", "supporting", "discovery"):
            for eid in requirement.get(f"{tier}_evidence_ids") or []:
                by_tier.setdefault(tier, []).append({
                    "evidence_id": eid,
                    "requirement_id": requirement.get("requirement_id"),
                    "provision": requirement.get("canonical"),
                })

    if isinstance(fr.get("selected_ids"), list):
        # Recorded by the generation itself: the sources in the answer's prompt,
        # in prompt order (prompt_index is the [n] the model cites).
        selected = [{"evidence_id": eid, "in_context": True, "prompt_index": i}
                    for i, eid in enumerate(fr["selected_ids"], start=1)]
        selected_source = "generation_full.jsonl selected_ids (the evidence the model was given)"
    elif "selected_ids" in fr:
        # The generation record says explicitly that no model was called, so no
        # evidence was given to one. The evidence phase's selection is not
        # substituted: it would read as evidence the model used.
        selected = []
        selected_source = ("generation_full.jsonl selected_ids is null: the question was answered without calling "
                           "the model, so no evidence was given to it")
    else:
        selected = [{"evidence_id": eid, "in_context": True} for eid in sel.get("selected_ids") or []]
        for dropped in sel.get("dropped_reasons") or []:
            selected.append(dropped if isinstance(dropped, dict) else {"in_context": False, "reason": str(dropped)})
        selected_source = (
            "evidence_records.jsonl (the evidence phase; this generation record does not say which evidence "
            "the model was given)" if selected else None
        )

    latency = dict(fr.get("timings_ms") or {})
    for source_key, target_key in (
        ("planning_ms", "evidence_planning_ms"),
        ("retrieval_ms", "evidence_retrieval_ms"),
        ("coverage_selection_ms", "evidence_coverage_selection_ms"),
    ):
        value = (ev.get("timings_ms") or {}).get(source_key)
        if value is not None:
            latency[target_key] = value

    expected_requirements = comp.get("expected_exact_labels") or ret.get("expected_exact") or []
    domain_label = (benchmark or {}).get("domain") or (domain or {}).get("domain")

    return QuestionResult(
        id=qid,
        question=ev.get("question") or (benchmark or {}).get("question") or "",
        category=fr.get("category") or ev.get("category") or (benchmark or {}).get("category"),
        expected_behavior=fr.get("expected_behavior") or (benchmark or {}).get("expected_behavior"),
        expected_requirements=tuple(expected_requirements),
        expected_terms=tuple(comp.get("terms_expected") or (benchmark or {}).get("expected_terms") or []),
        domain=domain_label,
        plan_kind=ev.get("plan_kind"),
        detected_requirements=tuple(ret.get("parsed_requirements") or ev.get("requirements") or []),
        requirement_status={
            "retrieval": ret,
            "coverage_counts": cov.get("counts") or {},
            "requirements": cov.get("requirements") or [],
            "satisfied": cov.get("satisfied") or [],
            "missing": cov.get("missing") or [],
            "expected_missing": cov.get("expected_missing") or [],
            "selection": {k: v for k, v in sel.items() if k not in ("selected_ids", "dropped_reasons")},
            "checks": {k: ev.get(k) for k in ("retrieval_ok", "coverage_ok", "selection_ok", "deterministic", "evidence_ok") if k in ev},
        },
        coverage_state=cov.get("state"),
        evidence_by_tier=by_tier,
        selected_evidence=selected,
        generated=bool(fr.get("generated")),
        skipped_reason=fr.get("skipped_reason"),
        answer_raw=fr.get("answer_raw"),
        answer_final=fr.get("answer_final"),
        repair=fr.get("repair"),
        validation_raw=fr.get("validation_initial") or {},
        validation_final=fr.get("validation_final") or {},
        citations=list(_get(fr, "citations", "listed", default=[])),
        claims_raw=list(_get(fr, "faithfulness", "claims", default=[])),
        claims_final=list(_get(fr, "faithfulness_final", "claims", default=[])),
        correct_raw=(correctness or {}).get("raw_correct"),
        correct_final=(correctness or {}).get("final_correct"),
        correct_reasons_raw=tuple((correctness or {}).get("raw_reasons") or []),
        correct_reasons_final=tuple((correctness or {}).get("final_reasons") or []),
        hallucination_raw=_get(fr, "hallucination", "any_raw"),
        hallucination_final=_get(fr, "hallucination", "any_final"),
        citation_ok=_get(fr, "citations", "citation_ok"),
        truncated=_get(fr, "tokens", "truncated"),
        refusal=fr.get("refusal") or {},
        failure_layer=(failure or {}).get("layer"),
        failure_reasons=tuple((failure or {}).get("reasons") or []),
        controlled_generated=None if controlled is None else bool(controlled.get("generated")),
        controlled_valid_raw=None if controlled is None else controlled.get("valid_raw"),
        controlled_answer_raw=None if controlled is None else controlled.get("answer_raw"),
        latency_ms=latency,
        tokens=fr.get("tokens") or {},
        extra={
            "completeness": comp,
            "hallucination": fr.get("hallucination") or {},
            "citation_summary": {k: v for k, v in (fr.get("citations") or {}).items() if k != "listed"},
            "faithfulness_counts": _get(fr, "faithfulness", "counts", default={}),
            "faithfulness_final_counts": _get(fr, "faithfulness_final", "counts", default={}),
            "domain_flags": fr.get("domain") or {},
            "domain_boundary": domain or {},
            "coverage_action": fr.get("coverage_action"),
            "shape": fr.get("shape"),
            # Stage 12 answer shape and evidence plan (absent in earlier runs)
            "answer_shape": fr.get("answer_shape"),
            "evidence_plan": fr.get("evidence_plan"),
            "prompt_chars": fr.get("prompt_chars"),
            "wall_s": fr.get("wall_s"),
            "failure_soft": bool((failure or {}).get("soft")),
            "selected_evidence_source": selected_source,
            "controlled": {
                k: (controlled or {}).get(k)
                for k in ("validation_initial", "validation_final", "tokens", "timings_ms", "completeness", "hallucination")
                if controlled is not None
            },
        },
    )


# ---------------------------------------------------------------------- load


def load(path: str | Path, root: Path | None = None) -> EvaluationRun:
    """Read a Stage 5 run directory into an EvaluationRun. Read-only."""
    directory = Path(path)
    manifest = _json(directory / MANIFEST)
    if not isinstance(manifest, dict):
        raise ValueError(f"{directory} is not a Stage 5 run directory: {MANIFEST} is missing or unreadable")

    problems: list[str] = []
    present: list[str] = []

    def read(name: str) -> Any | None:
        data = _json(directory / name)
        if data is None:
            if (directory / name).exists():
                problems.append(f"{name} is present but could not be parsed as JSON")
            return None
        present.append(name)
        return data

    def read_rows(name: str) -> list[dict[str, Any]]:
        rows = _jsonl(directory / name)
        if rows:
            present.append(name)
        return rows

    present.append(MANIFEST)
    summary = read(SUMMARY)
    evidence_rows = read_rows(EVIDENCE)
    full_rows = read_rows(FULL)
    controlled_rows = read_rows(CONTROLLED)

    retrieval = read("retrieval_results.json")
    coverage = read("coverage_results.json")
    selection = read("selection_results.json")
    generation = read("generation_results.json")
    correctness = read("correctness_results.json")
    faith = read("semantic_faithfulness_results.json")
    citation = read("citation_results.json")
    hallucination = read("hallucination_results.json")
    refusal = read("refusal_results.json")
    domain = read("domain_boundary_results.json")
    behaviour = read("behaviour_results.json")
    repair = read("repair_results.json")
    latency = read("latency_results.json")
    failures = read("failure_analysis.json")
    phases = {}
    for name in ("evidence", "generation", "report"):
        marker = _json(directory / f"phase_{name}.json")
        phases[name] = marker
        if marker is not None:
            present.append(f"phase_{name}.json")

    run_id = str(manifest.get("run_id") or directory.name)

    # ---- status: only what the artifacts say, never what we hope
    status = COMPLETE
    if not evidence_rows:
        status = INCOMPLETE
        problems.append("no evidence records: the evidence phase did not produce output")
    for name in ("evidence", "generation"):
        marker = phases.get(name)
        if marker is None:
            status = INCOMPLETE
            problems.append(f"phase marker phase_{name}.json is missing, so the {name} phase did not finish")
        elif str(marker.get("status")) != "done":
            status = INCOMPLETE
            problems.append(f"the {name} phase reported status {marker.get('status')!r}")
    expected_questions = len(manifest.get("questions") or [])
    if full_rows and expected_questions and len(full_rows) < expected_questions:
        status = INCOMPLETE
        problems.append(
            f"generation records cover {len(full_rows)} of the {expected_questions} questions the run was started with"
        )

    model = _model_identity(manifest, problems)
    fingerprint = _fingerprint(manifest, problems)
    benchmark, benchmark_rows = _benchmark_identity(manifest, summary, root, evidence_rows or full_rows, problems)

    # The questions this run produced records for: the full-pipeline answers
    # when generation ran, the evidence records otherwise.
    evaluated_ids = [r["id"] for r in (full_rows or evidence_rows) if "id" in r]
    question_set = _question_set(
        evaluated_ids, FULL if full_rows else EVIDENCE, benchmark_rows, benchmark.questions,
    )
    if question_set["full_benchmark"] is False:
        problems.append(
            f"partial benchmark: records exist for {question_set['count']} of the {benchmark.questions} benchmark "
            "questions. The process may have completed, but the benchmark was not evaluated in full"
        )

    if manifest.get("skip_generation") and full_rows:
        problems.append(
            "run_manifest.json records skip_generation=true although generation records exist: the "
            "manifest reflects the most recent invocation for this run directory (a report rebuild), "
            "not the invocation that produced the answers"
        )

    # ---- metrics
    collected: list[MetricResult] = []
    collected += _evidence_metrics(evidence_rows, retrieval, coverage, selection)
    collected += _generation_metrics(full_rows, controlled_rows, generation)
    collected += _correctness_metrics(correctness)
    collected += _faithfulness_metrics(faith, full_rows)
    collected += _hallucination_metrics(full_rows, hallucination)
    collected += _citation_metrics(full_rows, citation)
    collected += _refusal_metrics(full_rows, refusal)
    collected += _domain_metrics(domain)
    collected += _behaviour_metrics(full_rows, behaviour, benchmark_rows)
    collected += _repair_metrics(full_rows, repair)
    collected += _latency_metrics(latency, full_rows)
    if benchmark.questions is not None:
        collected.append(_count_metric("benchmark_questions", benchmark.questions, source=MANIFEST))

    started_at = manifest.get("started_at") if _parse_time(manifest.get("started_at")) else None
    completed_at = manifest.get("completed_at") if _parse_time(manifest.get("completed_at")) else None
    if completed_at is None:
        completed_at = _get(summary, "generated_at_utc")
    if completed_at is None:
        finished = [str(m.get("finished_at")) for m in phases.values() if m and m.get("finished_at")]
        completed_at = max(finished) if finished else None
    duration = None
    start_t, end_t = _parse_time(started_at), _parse_time(completed_at)
    if start_t and end_t and end_t >= start_t:
        duration = round((end_t - start_t).total_seconds(), 1)
    collected.append(M.make_metric(
        "run_duration", duration, source=MANIFEST, status=None if duration is not None else MISSING,
        note=("from started_at to completed_at in run_manifest.json" if duration is not None else
              "this run records no start time, so its wall-clock duration cannot be derived from its artifacts"),
    ))

    inconsistent = [m.key for m in collected if m.status == INCONSISTENT]
    if inconsistent:
        problems.append(
            "recounted from the per-question records, these metrics disagree with the aggregate the "
            f"evaluator stored: {', '.join(inconsistent)}. The stored value is displayed unchanged; "
            "the disagreement is a bug to investigate in the evaluator, not here"
        )

    # ---- per-question records
    ev_by_id = _by_id(evidence_rows)
    full_by_id = _by_id(full_rows)
    ctrl_by_id = _by_id(controlled_rows)
    corr_by_id = _by_id(_get(correctness, "per_question", default=[]))
    fail_by_id = _by_id(_get(failures, "per_question", default=[]))
    domain_by_id = _by_id(_get(domain, "per_question", default=[]))
    bench_by_id = _by_id(benchmark_rows or [])

    ordered_ids = [qid for qid in (manifest.get("questions") or []) if isinstance(qid, str)]
    seen = set(ordered_ids)
    for source in (full_by_id, ev_by_id):
        for qid in source:
            if qid not in seen:
                ordered_ids.append(qid)
                seen.add(qid)

    questions = tuple(
        _question(
            qid, bench_by_id.get(qid), ev_by_id.get(qid), full_by_id.get(qid), ctrl_by_id.get(qid),
            corr_by_id.get(qid), fail_by_id.get(qid), domain_by_id.get(qid),
        )
        for qid in ordered_ids
        if qid in ev_by_id or qid in full_by_id
    )

    failure_summary = {
        "by_layer": _get(failures, "by_layer", default={}),
        "by_layer_and_category": _get(failures, "by_layer_and_category", default={}),
        "failures": _get(failures, "failures", default=[]),
        "soft": _get(failures, "soft", default=[]),
        "incorrect_after_repair": _get(correctness, "incorrect_after_repair", default=[]),
        "correct_only_after_repair": _get(correctness, "correct_only_after_repair", default=[]),
        "false_refusal_raw": _get(refusal, "false_refusal_raw", default=[]),
        "false_refusal_final": _get(refusal, "false_refusal_final", default=[]),
        "false_answer": _get(refusal, "false_answer", default=[]),
        "hallucination_questions_raw": _get(hallucination, "questions_raw", default=[]),
        "hallucination_questions_final": _get(hallucination, "questions_final", default=[]),
        "fabricated_identifiers": _get(hallucination, "fabricated_identifiers", default=[]),
        "repair_failed": _get(repair, "repair_failed", default=[]),
        "retrieval_failures": _get(retrieval, "failures", default=[]),
        "coverage_failures": _get(coverage, "failures", default=[]),
        "selection_failures": _get(selection, "failures", default=[]),
        "fails_with_context_but_not_with_exact_only": _get(generation, "fails_with_context_but_not_with_exact_only", default=[]),
        "fails_even_with_exact_only": _get(generation, "fails_even_with_exact_only", default=[]),
        "questions_with_unsupported_claim_raw": _get(faith, "raw_answer", "questions_with_unsupported_claim", default=[]),
        "questions_with_unsupported_claim_final": _get(faith, "final_answer", "questions_with_unsupported_claim", default=[]),
    }

    breakdowns = {
        "validation_status_raw": _get(generation, "modes", "full_pipeline_raw", "status_raw", default={}),
        "validation_status_final": _get(generation, "modes", "full_pipeline_raw", "status_final", default={}),
        "generation_by_category": _get(generation, "modes", "full_pipeline_raw", "by_category", default={}),
        "controlled_by_category": _get(generation, "modes", "controlled_evidence_raw", "by_category", default={}),
        "localisation": _get(generation, "localisation", default=[]),
        "repair_kinds": _get(repair, "by_repair", default={}),
        "faithfulness_by_category": _get(faith, "by_category", default={}),
        "faithfulness_raw_block": {k: v for k, v in (_get(faith, "raw_answer", default={}) or {}).items() if k != "unsupported_claims"},
        "faithfulness_final_block": {k: v for k, v in (_get(faith, "final_answer", default={}) or {}).items() if k != "unsupported_claims"},
        "faithfulness_methodology": _get(faith, "methodology"),
        "faithfulness_limitations": _get(faith, "limitations"),
        "hallucination_by_code_raw": _get(hallucination, "by_code_raw", default={}),
        "hallucination_by_category_raw": _get(hallucination, "by_category_raw", default={}),
        "citation_roles": _get(citation, "listed_citation_roles", default={}),
        "citation_detail": {
            k: _get(citation, k) for k in
            ("invalid_markers_questions", "mismatch_questions", "discovery_cited_questions",
             "irrelevant_markers_total", "uncited_requirement_statements", "answers_without_any_marker")
            if citation and k in citation
        },
        "refusal_by_expected_behavior": _get(refusal, "by_expected_behavior", default={}),
        "deterministic_refusals": _get(refusal, "deterministic_refusals", default=[]),
        "domain_attribution": _get(domain, "attribution", default={}),
        "behaviour": behaviour or {},
        "latency_phases_ms": _get(latency, "phases_ms", default={}),
        "latency_by_group_total_ms": _get(latency, "by_group_total_ms", default={}),
        "tokens_per_second": _get(latency, "tokens_per_second"),
        "retrieval_detail": {
            k: _get(retrieval, k) for k in
            ("parse_ok", "multi_provision_full_recall", "range_full_recall",
             "missing_provisions_correctly_absent", "structural_present_when_expected",
             "supporting_present", "fallback_used", "fallback_used_when_all_exact_found")
            if retrieval and k in retrieval
        },
        "coverage_detail": {
            k: _get(coverage, k) for k in
            ("explicit_state_correct", "incomplete_detected", "multi_provision_complete",
             "range_complete", "no_explicit_for_general")
            if coverage and k in coverage
        },
        "selection_detail": {
            k: _get(selection, k) for k in
            ("mean_context_chars", "optional_truncated_total", "overflow_questions",
             "discovery_in_context_questions", "required_dropped_questions",
             "required_truncated_questions", "structural_kept_when_available")
            if selection and k in selection
        },
        "correctness_definition": _get(correctness, "definition"),
        "phase_markers": {name: marker for name, marker in phases.items() if marker},
    }

    configuration = dict(manifest.get("config") or {})
    configuration.update({
        "skip_generation": manifest.get("skip_generation"),
        "controlled": manifest.get("controlled"),
        "questions_requested": expected_questions,
    })

    return EvaluationRun(
        evaluation_run_id=stable_id(
            KIND_EVALUATION,
            directory.relative_to(root).as_posix() if root and _under(directory, root) else directory.as_posix(),
        ),
        name=run_id,
        path=directory.as_posix(),
        schema=SCHEMA,
        model=model,
        benchmark=benchmark,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration,
        configuration=configuration,
        question_set=question_set,
        pipeline_fingerprint=fingerprint,
        metrics=_ordered(collected),
        questions=questions,
        failure_summary=failure_summary,
        breakdowns=breakdowns,
        source_artifacts=tuple(sorted(set(present))),
        problems=tuple(problems),
        git_revision=None,
    )


def _under(directory: Path, root: Path) -> bool:
    try:
        directory.relative_to(root)
        return True
    except ValueError:
        return False
