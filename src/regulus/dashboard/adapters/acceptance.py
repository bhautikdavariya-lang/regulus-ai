"""The 300-question vendor acceptance test, as the dashboard sees it.

One run directory, `artifacts/acceptance_test/<label>_<timestamp>/`:

    run_metadata.json   benchmark identity and sha256, the active model, the
                        full reproducibility record (revision, weights hash,
                        device, dtype, decoding, pipeline_config, git commit)
    answers.jsonl       one delivered answer per question, as the user saw it
    scoring/verdicts_*.jsonl   the hand-applied rubric: L, M, N, O, P, Q and a
                        verdict per row, under `regulus_substantive_rubric_v1`
    provenance.json     optional per-question evidence provenance

Why this adapter exists
-----------------------
Before it, these runs were invisible. The registry's `artifacts/*/*/*` root is
three levels deep and a run directory sits two levels down, so only its
`scoring/` subdirectory was ever a candidate, and no adapter claimed that. A
hand-scored 300-question evaluation sat on disk while the Overview said "this
model has not been evaluated" without naming it.

What this adapter does NOT do
-----------------------------
It does not score anything. The rubric is applied by a human reading each
answer against the verified corpus; this adapter tabulates the verdicts that
were recorded and reports how each one was arrived at. It computes no
correctness of its own, and it never writes.

Two caveats are attached to every run as `problems`, because the numbers are
meaningless without them:

* **the answer key is a draft.** The workbook requires columns G/H/I to be
  verified by an SME and marked in column K before the test is administered,
  and states that an unverified key invalidates the entire result. Every run so
  far was scored against an unverified key.
* **inherited verdicts.** A comparative run may carry a row's verdict over from
  an earlier run when the delivered answer did not change. That is a legitimate
  protocol and it is not a hand reading of this run, so the split is counted and
  reported rather than averaged away.

Freshness is not decided here. This adapter reports what the artifacts say; the
registry decides CURRENT / HISTORICAL / STALE. Note that the pipeline
fingerprint is *derived* from the run's own recorded configuration, because the
acceptance harness records the configuration but no fingerprint of its own;
`pipeline_fingerprint["derived"]` says so.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

from ..fingerprint import pipeline_fingerprint, question_set_identity
from ..schemas import (
    COMPLETE,
    COUNT,
    HIGHER_IS_BETTER,
    INCOMPLETE,
    INCONSISTENT,
    KIND_EVALUATION,
    LOWER_IS_BETTER,
    MISSING,
    OK,
    RATIO,
    BenchmarkIdentity,
    EvaluationRun,
    MetricResult,
    ModelIdentity,
    QuestionResult,
    stable_id,
)

SCHEMA = "acceptance/v1"
RUBRIC_ID = "regulus_substantive_rubric_v1"

# Basis values the scoring files use, and whether the row was read by hand for
# THIS run. Anything unrecognised is counted as "other" and named in problems.
_HAND_READ = ("manual_rubric_read",)
_NOT_HAND_READ = ("inherited",)


def _json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def detect(path: str | Path) -> bool:
    """True for an acceptance-test run directory."""
    d = Path(path)
    if not d.is_dir() or not (d / "answers.jsonl").is_file():
        return False
    metadata = _json(d / "run_metadata.json")
    if not isinstance(metadata, dict):
        return False
    benchmark = metadata.get("benchmark")
    return isinstance(benchmark, dict) and bool(benchmark.get("benchmark_key"))


# ------------------------------------------------------------------ identity


def _model(metadata: dict[str, Any]) -> ModelIdentity:
    active = metadata.get("active_model") or {}
    repro = metadata.get("reproducibility") or {}
    adapter = active.get("adapter")
    adapter_path = None
    adapter_id = None
    checkpoint = None
    if adapter:
        adapter_path = Path(str(adapter)).as_posix()
        parts = Path(str(adapter))
        # ".../models/qwen3-0.6b-lora/<run>/adapter" -> the run is the adapter's name
        adapter_id = parts.parent.name if parts.name == "adapter" else parts.name
        checkpoint = repro.get("adapter_checkpoint") or active.get("checkpoint")
    return ModelIdentity(
        base_model_id=str(repro.get("model_id") or active.get("model_id") or "unknown"),
        revision=repro.get("model_revision"),
        adapter_id=adapter_id,
        adapter_path=adapter_path,
        checkpoint=checkpoint,
        dtype=repro.get("dtype"),
        device=repro.get("device"),
    )


def _benchmark(metadata: dict[str, Any]) -> BenchmarkIdentity:
    b = metadata.get("benchmark") or {}
    key = str(b.get("benchmark_key") or "")
    return BenchmarkIdentity(
        benchmark_id=key.split("@")[0] or "regulus_acceptance",
        version=b.get("version"),
        path=b.get("file"),
        sha256=b.get("sha256_after") or b.get("sha256_before"),
        questions=b.get("questions"),
        protected=True,            # the workbook is a contractual, read-only artifact
    )


def _fingerprint(metadata: dict[str, Any], problems: list[str]) -> dict[str, Any] | None:
    """The pipeline fingerprint, DERIVED from the run's own recorded configuration.

    The acceptance harness records `pipeline_config` and `decoding` but no
    fingerprint, so there is no stored hash to cross-check. Deriving it with the
    canonical function is what makes the run comparable at all; `derived` marks
    it so nobody mistakes it for an attestation the run itself made.
    """
    repro = metadata.get("reproducibility") or {}
    config = repro.get("pipeline_config")
    if not isinstance(config, dict):
        problems.append("run_metadata.json records no pipeline_config, so the pipeline this run measured "
                        "cannot be identified and it can never be shown as the current system's result")
        return None
    decoding = repro.get("decoding")
    full = {**config, "decoding": decoding if isinstance(decoding, dict) else None}
    recorded = pipeline_fingerprint(full)
    missing = [name for name in ("repetition_penalty", "no_repeat_ngram_size")
               if isinstance(decoding, dict) and name not in decoding]
    if missing:
        problems.append(
            f"the run does not record decoding.{' or decoding.'.join(missing)}, so those settings hash as "
            "null and this run's fingerprint cannot equal a current system that records them"
        )
    return {**recorded.to_dict(), "verified": True, "derived": True,
            "derived_from": "run_metadata.json reproducibility.pipeline_config + reproducibility.decoding"}


def _verdicts(run_dir: Path) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    """Every recorded verdict by question id, and the files they came from.

    Later files win on a repeated id, which is how a re-scoring pass is applied;
    the file order is sorted, so the result does not depend on the filesystem.
    """
    rows: dict[str, dict[str, Any]] = {}
    files: list[str] = []
    for name in sorted(glob.glob(str(run_dir / "scoring" / "verdicts_*.jsonl"))):
        files.append(Path(name).name)
        with open(name, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("id"):
                    rows[str(record["id"])] = record
    return rows, tuple(files)


def _answers(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    path = run_dir / "answers.jsonl"
    if not path.is_file():
        return out
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("question_id"):
                out[str(record["question_id"])] = record
    return out


def _benchmark_rows(path: Any) -> Any | None:
    """The workbook, when it is readable. Used only to verify the question set
    and to find the negative-control and ISO-scope rows; never to score."""
    try:
        from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark

        workbook = Path(path) if path and Path(path).is_file() else DEFAULT_WORKBOOK
        if not Path(workbook).is_file():
            return None
        return load_acceptance_benchmark(workbook)
    except Exception:
        return None


# ------------------------------------------------------------------ metrics


def _full_pass(r: dict[str, Any]) -> bool:
    """The rubric's verdict rule: L=1 and M=0 and N=2 and O>=1 and P=1 and Q in {1, blank}."""
    return (r.get("L") == 1 and r.get("M") == 0 and r.get("N") == 2
            and (r.get("O") or 0) >= 1 and r.get("P") == 1 and r.get("Q") in (1, None))


def _ratio(key: str, name: str, numerator: int, denominator: int, *,
           direction: str = HIGHER_IS_BETTER, source: str = "scoring/verdicts_*.jsonl",
           note: str | None = None) -> MetricResult:
    return MetricResult(
        key=key, display_name=name, value=(numerator / denominator) if denominator else None,
        unit=RATIO, direction=direction, numerator=numerator, denominator=denominator,
        source=source, note=note, recomputed_from="per-question verdict records",
    )


def _metrics(rows: dict[str, dict[str, Any]], benchmark) -> list[MetricResult]:
    """Rubric aggregates, every one recomputed from the verdict records.

    The denominator is the SCORED rows: a row recorded as ERROR produced no
    answer to judge, and the rubric says ERROR is a technical failure and never
    a bad answer, so counting it as a failure would misstate the measurement.
    It is reported as its own count instead.
    """
    scored = {i: r for i, r in rows.items() if r.get("result") != "ERROR"}
    n = len(scored)
    errors = len(rows) - n
    out: list[MetricResult] = [
        _ratio("acceptance_full_pass", "Acceptance Pass Rate",
               sum(1 for r in scored.values() if _full_pass(r)), n,
               note="the rubric's whole verdict rule, not any single dimension"),
        _ratio("acceptance_citation_accuracy", "Citation Accuracy (L)",
               sum(1 for r in scored.values() if r.get("L") == 1), n),
        _ratio("acceptance_fabrication_rate", "Fabricated Citations (M)",
               sum(1 for r in scored.values() if r.get("M") == 1), n, direction=LOWER_IS_BETTER,
               note="gate G2 is zero, absolute: one fabricated identifier fails the run"),
        _ratio("acceptance_substantive_correct", "Substantive Correctness, fully correct (N=2)",
               sum(1 for r in scored.values() if r.get("N") == 2), n),
        _ratio("acceptance_substantive_partial", "Substantive Correctness, directionally right (N>=1)",
               sum(1 for r in scored.values() if (r.get("N") or 0) >= 1), n,
               note="N=1 is 'directionally right but could mislead'; it is not a pass"),
        _ratio("acceptance_completeness", "Completeness (O>=1)",
               sum(1 for r in scored.values() if (r.get("O") or 0) >= 1), n),
        _ratio("acceptance_scope_discipline", "Scope Discipline (P)",
               sum(1 for r in scored.values() if r.get("P") == 1), n),
    ]
    iso = {i: r for i, r in scored.items() if r.get("Q") is not None}
    out.append(_ratio("acceptance_iso_concordance", "ISO 13485 Concordance (Q)",
               sum(1 for r in iso.values() if r.get("Q") == 1), len(iso),
                      note="scored only on rows the workbook puts in ISO scope"))
    if benchmark is not None:
        controls = [q.question_id for q in benchmark.negative_controls]
        present = {i: r for i, r in scored.items() if i in set(controls)}
        out.append(_ratio("acceptance_negative_control_pass", "Negative-control Pass Rate",
               sum(1 for r in present.values() if _full_pass(r)), len(present),
                          note="gate G3 is 100%, absolute: the system must refuse what does not exist"))
    hand = sum(1 for r in rows.values() if r.get("scoring_basis") in _HAND_READ)
    inherited = sum(1 for r in rows.values() if r.get("scoring_basis") in _NOT_HAND_READ)
    unrecorded = sum(1 for r in rows.values() if r.get("scoring_basis") is None)
    if unrecorded == len(rows) and rows:
        # The first hand-scoring pass predates the scoring_basis field. Reporting
        # 0 rows read by hand would be a false statement about a run that was
        # read by hand in full; the honest value is "not recorded".
        out.append(MetricResult(
            key="acceptance_rows_hand_scored", display_name="Rows Read by Hand for This Run",
            value=None, unit=COUNT, direction=HIGHER_IS_BETTER, status=MISSING,
            source="scoring/verdicts_*.jsonl",
            note="this run's verdicts do not record how each one was arrived at, so how many rows were read by "
                 "hand cannot be stated; it is not zero, it is unrecorded",
        ))
    else:
        out.append(MetricResult(
            key="acceptance_rows_hand_scored", display_name="Rows Read by Hand for This Run",
            value=float(hand), unit=COUNT, direction=HIGHER_IS_BETTER, numerator=hand, denominator=len(rows),
            source="scoring/verdicts_*.jsonl", recomputed_from="per-question verdict records",
            status=INCONSISTENT if unrecorded else OK,
            note="; ".join(part for part in (
                f"{inherited} row(s) carry a verdict inherited from an earlier run whose answer was identical" if inherited else "",
                f"{unrecorded} row(s) do not record how their verdict was arrived at" if unrecorded else "",
            ) if part) or None,
        ))
    out.append(MetricResult(
        key="acceptance_rows_errored", display_name="Rows With No Answer to Judge",
        value=float(errors), unit=COUNT, direction=LOWER_IS_BETTER, numerator=errors, denominator=len(rows),
        source="scoring/verdicts_*.jsonl", recomputed_from="per-question verdict records",
        note="recorded ERROR: a technical execution failure, excluded from every rate above",
    ))
    return out


def _questions(rows: dict[str, dict[str, Any]], answers: dict[str, dict[str, Any]], benchmark) -> tuple[QuestionResult, ...]:
    by_id = {q.question_id: q for q in benchmark.questions} if benchmark is not None else {}
    out: list[QuestionResult] = []
    for qid in sorted(set(rows) | set(answers)):
        verdict = rows.get(qid) or {}
        answer = answers.get(qid) or {}
        meta = by_id.get(qid)
        passed = _full_pass(verdict) if verdict else None
        out.append(QuestionResult(
            id=qid,
            question=str(answer.get("question") or (meta.question if meta else "")),
            category=(meta.question_type if meta else None),
            domain=(meta.domain if meta else None),
            expected_behavior=(meta.accepted_expectation if meta else None),
            generated=bool(answer.get("model_called")),
            skipped_reason=answer.get("fallback_type"),
            answer_final=answer.get("answer"),
            answer_raw=answer.get("raw_model_output"),
            repair=answer.get("repair"),
            validation_raw={"status": answer.get("validation_initial"), "codes": answer.get("validation_initial_codes") or []},
            validation_final={"status": answer.get("validation_final")},
            correct_final=passed,
            citation_ok=(verdict.get("L") == 1) if verdict.get("L") is not None else None,
            hallucination_final=(verdict.get("M") == 1) if verdict.get("M") is not None else None,
            latency_ms={"total_ms": float(answer["seconds"]) * 1000} if answer.get("seconds") is not None else {},
            tokens={"generated": answer.get("generated_tokens")},
            extra={
                "rubric_id": RUBRIC_ID,
                "verdict": verdict.get("result"),
                "scores": {c: verdict.get(c) for c in ("L", "M", "N", "O", "P", "Q")},
                "scoring_basis": verdict.get("scoring_basis"),
                "scorer_notes": verdict.get("notes"),
                "evaluation_note": verdict.get("eval"),
                "comparative_note": verdict.get("c123"),
                "is_negative_control": (meta.is_negative_control if meta else None),
                "in_iso_scope": (meta.in_g7_scope if meta else None),
                "key_verified": (meta.key_is_verified if meta else None),
                "execution_status": answer.get("execution_status"),
                "stop_reason": answer.get("stop_reason"),
                "evidence": answer.get("evidence") or [],
                "citations": answer.get("citations") or [],
            },
        ))
    return tuple(out)


# ------------------------------------------------------------------ load


def load(path: str | Path, root: Path | None = None) -> EvaluationRun:
    """Read one acceptance-test run directory into an EvaluationRun. Read-only."""
    run_dir = Path(path)
    metadata = _json(run_dir / "run_metadata.json")
    if not isinstance(metadata, dict):
        raise ValueError(f"{run_dir} is not an acceptance-test run directory")
    problems: list[str] = []

    model = _model(metadata)
    benchmark = _benchmark(metadata)
    fingerprint = _fingerprint(metadata, problems)
    rows, verdict_files = _verdicts(run_dir)
    answers = _answers(run_dir)
    workbook = _benchmark_rows(benchmark.path)

    if workbook is not None and benchmark.sha256 and workbook.sha256 != benchmark.sha256:
        workbook = None
        problems.append("the acceptance workbook on disk is not the one this run was scored against "
                        "(its sha256 differs), so the question set and the ISO/negative-control rows "
                        "could not be verified from it")

    evaluated = question_set_identity(rows)
    full: bool | None = None
    if workbook is not None:
        full = evaluated.sha256 == question_set_identity(q.question_id for q in workbook.questions).sha256
    elif benchmark.questions is not None and evaluated.count != benchmark.questions:
        full = False
    question_set = {**evaluated.to_dict(), "source": "scoring/verdicts_*.jsonl",
                    "benchmark_questions": benchmark.questions, "full_benchmark": full}

    # `status` is about the RUN: did the process produce an answer for every
    # question? Whether the SCORING covered the benchmark is a different fact,
    # and it belongs in question_set.full_benchmark -- which is what makes
    # freshness say "the process completed; the benchmark did not" instead of
    # the false "the run did not finish".
    status = COMPLETE
    if benchmark.questions is not None and len(answers) < benchmark.questions:
        status = INCOMPLETE
        problems.append(f"the run produced {len(answers)} of the {benchmark.questions} answers the benchmark asks "
                        "for, so the run itself did not finish")
    if not rows:
        problems.append("no scoring verdicts exist for this run: the answers were produced but the rubric was "
                        "never applied, so there is no result to report")
    elif full is False:
        problems.append(f"partial scoring: {evaluated.count} of the {benchmark.questions} benchmark rows carry a "
                        "verdict, so this is a result for those rows and not for the benchmark")
    missing_answers = sorted(set(rows) - set(answers))
    if missing_answers:
        problems.append(f"{len(missing_answers)} scored row(s) have no recorded answer: {', '.join(missing_answers[:5])}")

    # the caveats that make or break the meaning of these numbers
    verification = (metadata.get("benchmark") or {}).get("key_verification") or {}
    if verification.get("key_is_locked") is not True:
        problems.append(
            f"the answer key was not verified when this run was scored ({verification.get('verified_rows', 0)} of "
            f"{verification.get('total_rows', benchmark.questions)} rows marked verified). The workbook's own terms "
            "state that an unverified key invalidates the entire result, so these numbers are indicative, not contractual"
        )
    inherited = sum(1 for r in rows.values() if r.get("scoring_basis") in _NOT_HAND_READ)
    if inherited:
        problems.append(
            f"{inherited} of {len(rows)} verdicts were inherited from an earlier run on the grounds that the "
            "delivered answer did not change; they are not a hand reading of this run"
        )
    other_basis = sorted({str(r.get("scoring_basis")) for r in rows.values()
                          if r.get("scoring_basis") not in (*_HAND_READ, *_NOT_HAND_READ, None)})
    if other_basis:
        problems.append(f"{sum(1 for r in rows.values() if str(r.get('scoring_basis')) in other_basis)} verdict(s) "
                        f"record a scoring basis that is neither a full manual read nor an inheritance "
                        f"({', '.join(other_basis)}); they are counted as neither")
    repro = metadata.get("reproducibility") or {}
    if repro.get("git_dirty"):
        problems.append(f"the working tree was dirty at commit {str(repro.get('git_commit'))[:12]}, so the exact "
                        "code that produced these answers is not identified by the commit alone")

    identifier = run_dir.relative_to(root).as_posix() if root and _under(run_dir, root) else run_dir.as_posix()
    return EvaluationRun(
        evaluation_run_id=stable_id(KIND_EVALUATION, identifier),
        name=run_dir.name,
        path=run_dir.as_posix(),
        schema=SCHEMA,
        model=model,
        benchmark=benchmark,
        status=status,
        started_at=metadata.get("started_utc"),
        completed_at=metadata.get("finished_utc"),
        duration_seconds=None,
        configuration={
            "rubric_id": RUBRIC_ID,
            "protocol": metadata.get("protocol"),
            "command": metadata.get("command"),
            "evaluation_config": {**(repro.get("pipeline_config") or {}), "decoding": repro.get("decoding")},
            "weights_sha256": repro.get("weights_sha256"),
            "system_prompt_sha256": repro.get("system_prompt_sha256"),
            "git_commit": repro.get("git_commit"),
            "git_dirty": repro.get("git_dirty"),
            "retriever": repro.get("retriever"),
            "hardware": metadata.get("hardware"),
        },
        metrics=tuple(_metrics(rows, workbook)),
        questions=_questions(rows, answers, workbook),
        failure_summary={
            "failed_ids": sorted(i for i, r in rows.items() if r.get("result") == "ERROR"),
            "misses": sorted(i for i, r in rows.items() if r.get("result") == "FAIL")[:50],
        },
        breakdowns={
            "rubric": {"rubric_id": RUBRIC_ID, "columns": ["L", "M", "N", "O", "P", "Q"],
                       "verdict_rule": "PASS iff L=1 and M=0 and N=2 and O>=1 and P=1 and Q in {1, blank}"},
            "verdict_counts": _counts(r.get("result") for r in rows.values()),
            "scoring_basis": _counts(r.get("scoring_basis") for r in rows.values()),
            "score_distribution": {column: _counts(r.get(column) for r in rows.values())
                                   for column in ("L", "M", "N", "O", "P", "Q")},
            "key_verification": verification,
            "gates": _gates(rows, workbook),
        },
        source_artifacts=("run_metadata.json", "answers.jsonl", *verdict_files),
        problems=tuple(problems),
        git_revision=repro.get("git_commit"),
        question_set=question_set,
        pipeline_fingerprint=fingerprint,
    )


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = "blank" if value is None else str(value)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _gates(rows: dict[str, dict[str, Any]], benchmark) -> list[dict[str, Any]]:
    """The workbook's own seven gates, evaluated against these verdicts.

    The thresholds are the workbook's, read from it; none is defined here. A
    gate whose scope cannot be established without the workbook is reported as
    undetermined rather than assumed to pass.
    """
    if benchmark is None:
        return []
    scored = {i: r for i, r in rows.items() if r.get("result") != "ERROR"}
    n = len(scored)
    iso = [r for r in scored.values() if r.get("Q") is not None]
    controls = {q.question_id for q in benchmark.negative_controls}
    control_rows = [r for i, r in scored.items() if i in controls]
    # N and O are 0-2 scales; the workbook scores those gates on points earned
    # out of the maximum, which is not the same as the share of perfect rows.
    measured: dict[str, float | None] = {
        "G1": (sum(1 for r in scored.values() if r.get("L") == 1) / n) if n else None,
        "G2": float(sum(1 for r in scored.values() if r.get("M") == 1)),
        "G3": (sum(1 for r in control_rows if _full_pass(r)) / len(control_rows)) if control_rows else None,
        "G4": (sum(r.get("N") or 0 for r in scored.values()) / (2 * n)) if n else None,
        "G5": (sum(r.get("O") or 0 for r in scored.values()) / (2 * n)) if n else None,
        "G6": (sum(1 for r in scored.values() if r.get("P") == 1) / n) if n else None,
        "G7": (sum(1 for r in iso if r.get("Q") == 1) / len(iso)) if iso else None,
    }
    out: list[dict[str, Any]] = []
    for gate in benchmark.gates:
        value = measured.get(gate.gate_id)
        passed = None
        if value is not None:
            passed = value >= gate.threshold if gate.comparison == ">=" else value == gate.threshold
        out.append({
            "gate_id": gate.gate_id, "metric": gate.metric, "threshold": gate.threshold,
            "comparison": gate.comparison, "unit": gate.unit, "absolute": gate.absolute,
            "scored_on": gate.scored_on, "why_it_matters": gate.why_it_matters,
            "measured": value, "passed": passed,
        })
    return out


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
