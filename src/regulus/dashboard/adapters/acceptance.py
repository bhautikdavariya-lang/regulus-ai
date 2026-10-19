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

import json
from pathlib import Path
from typing import Any

from regulus.evaluation import acceptance_scoring as S

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
RUBRIC_ID = S.RUBRIC_ID

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

    Read by the canonical reader (regulus.evaluation.acceptance_scoring): a
    malformed line or a repeated id is a validation issue, never skipped and
    never resolved by file order. This view holds the first record per id.
    """
    verdicts = S.read_verdicts(run_dir / "scoring")
    return verdicts.rows(), verdicts.files


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


# The verdict rule is the canonical one; the name is kept for existing callers.
_full_pass = S.full_pass

_SOURCE = "scoring/verdicts_*.jsonl"
_EXCLUDED_NOTE = "denominator: rows with a decided verdict (PASS or FAIL); ERROR, UNDETERMINED and unscored rows excluded"


def _ratio(key: str, name: str, ratio: S.Ratio | None, *, direction: str = HIGHER_IS_BETTER,
           note: str | None = None, refused: str | None = None) -> MetricResult:
    """A rate taken from the canonical score, or - when the records are invalid - no value at all."""
    if ratio is None:
        return MetricResult(key=key, display_name=name, value=None, unit=RATIO, direction=direction,
                            source=_SOURCE, status=INCONSISTENT, note=refused)
    return MetricResult(
        key=key, display_name=name, value=ratio.value,
        unit=RATIO, direction=direction, numerator=ratio.numerator, denominator=ratio.denominator,
        source=_SOURCE, note=note, recomputed_from="per-question verdict records",
    )


def _metrics(score: S.AcceptanceScore | None, rows: dict[str, dict[str, Any]], benchmark,
             issues: tuple[S.VerdictIssue, ...] = ()) -> list[MetricResult]:
    """Rubric aggregates, every one taken from the canonical acceptance score.

    The denominator is the DECIDED rows (PASS or FAIL). A row recorded as ERROR
    produced no answer to judge, and the rubric says ERROR is a technical failure
    and never a bad answer, so counting it as a failure would misstate the
    measurement; it is reported as its own count instead. When the verdict
    records fail validation, no rate is published (`score` is None).
    """
    refused = (f"not published: {len(issues)} verdict record issue(s) failed validation (see the run's problems)"
               if score is None else None)
    dim = (lambda k: score.dimensions.get(k)) if score is not None else (lambda k: None)
    errors = sum(1 for r in rows.values() if r.get("result") == S.ERROR)
    out: list[MetricResult] = [
        _ratio("acceptance_full_pass", "Acceptance Pass Rate", score.pass_rate if score else None,
               note=f"the rubric's whole verdict rule, not any single dimension; {_EXCLUDED_NOTE}", refused=refused),
        _ratio("acceptance_citation_accuracy", "Citation Accuracy (L)", dim("L=1"), refused=refused),
        _ratio("acceptance_fabrication_rate", "Fabricated Citations (M)", dim("M=1"), direction=LOWER_IS_BETTER,
               note="gate G2 is zero, absolute: one fabricated identifier fails the run", refused=refused),
        _ratio("acceptance_substantive_correct", "Substantive Correctness, fully correct (N=2)", dim("N=2"),
               refused=refused),
        _ratio("acceptance_substantive_partial", "Substantive Correctness, directionally right (N>=1)", dim("N>=1"),
               note="N=1 is 'directionally right but could mislead'; it is not a pass", refused=refused),
        _ratio("acceptance_completeness", "Completeness (O>=1)", dim("O>=1"), refused=refused),
        _ratio("acceptance_scope_discipline", "Scope Discipline (P)", dim("P=1"), refused=refused),
        _ratio("acceptance_iso_concordance", "ISO 13485 Concordance (Q)", dim("Q=1"),
               note="scored only on rows the workbook puts in ISO scope (column H is not '—')",
               refused=refused or (None if benchmark is not None else
                                   "not published: ISO scope cannot be established without the benchmark workbook")),
    ]
    if benchmark is not None:
        # G3 is scored PROVISIONALLY on rubric L alone (acceptance_scoring.G3_PROVISIONAL_NOTE); the
        # full row rule is named in the note for comparison.
        readings = score.negative_control_readings if score is not None else None
        rule = readings["rubric_v1_row_rule"] if readings else None
        out.append(_ratio(
            "acceptance_negative_control_pass", "Negative-control Pass Rate",
            readings[S.G3_DEFINITION] if readings else None,
            note=(f"PROVISIONAL (gate G3, rubric L alone, pending contractual confirmation); for comparison, "
                  f"the full row rule gives {rule.numerator}/{rule.denominator}; {_EXCLUDED_NOTE}" if rule else None),
            refused=refused,
        ))
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


def _questions(rows: dict[str, dict[str, Any]], answers: dict[str, dict[str, Any]], benchmark,
               score: S.AcceptanceScore | None = None) -> tuple[QuestionResult, ...]:
    by_id = {q.question_id: q for q in benchmark.questions} if benchmark is not None else {}
    out: list[QuestionResult] = []
    for qid in sorted(set(rows) | set(answers)):
        verdict = rows.get(qid) or {}
        answer = answers.get(qid) or {}
        meta = by_id.get(qid)
        # the validated verdict: True PASS, False FAIL, None for ERROR / UNDETERMINED /
        # unscored, and None for every row while the run's records are invalid
        passed = score.row_verdicts.get(qid) if score is not None else None
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
    verdicts = S.read_verdicts(run_dir / "scoring")
    rows, verdict_files = verdicts.rows(), verdicts.files
    answers = _answers(run_dir)
    workbook = _benchmark_rows(benchmark.path)

    if workbook is not None and benchmark.sha256 and workbook.sha256 != benchmark.sha256:
        workbook = None
        problems.append("the acceptance workbook on disk is not the one this run was scored against "
                        "(its sha256 differs), so the question set and the ISO/negative-control rows "
                        "could not be verified from it")

    # Validate before any number is computed; invalid records publish no metric.
    issues = S.validate(verdicts, workbook)
    score = S.score_run(verdicts, workbook) if rows and not issues else None
    if issues:
        shown = "; ".join(str(i) for i in issues[:5])
        problems.append(f"{len(issues)} verdict record issue(s) failed validation, so no acceptance rate or gate "
                        f"is published for this run: {shown}" + (" ..." if len(issues) > 5 else ""))

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
        metrics=tuple(_metrics(score, rows, workbook, issues)),
        questions=_questions(rows, answers, workbook, score),
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
            "gates": _gates(score, workbook),
            "acceptance": (score.to_dict() if score is not None else None),
            "validation_issues": [i.to_dict() for i in issues],
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


def _gates(score: S.AcceptanceScore | None, benchmark) -> list[dict[str, Any]]:
    """The workbook's own seven gates, as the canonical scorer computed them.

    The thresholds are the workbook's; none is defined here. Without the workbook
    the gates' scopes cannot be established, and with invalid verdict records no
    gate is computed: both report no gates rather than assume a value.
    """
    if benchmark is None or score is None:
        return []
    return [g.to_dict() for g in score.gates]


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
