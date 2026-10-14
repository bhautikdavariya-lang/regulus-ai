"""Offline evaluation of a finished acceptance run, from its measurement records alone.

    python scripts/run_acceptance_test.py --evaluate-offline artifacts/acceptance_test/<run dir>

Each `answers.jsonl` row is matched by question ID to its measurement record (regulus.traceability.
measurement). The record is integrity-checked, and its SAVED delivered answer is assessed against its
SAVED evidence snapshot by the existing evaluator entry point (`regulus.accuracy.evaluate_safely`, which
verifies the snapshot's fingerprint and labels the evidence EXACT). Nothing is retrieved, generated or
answered: no pipeline, model or database is touched, and the run's own files are only read.

What the evaluator is given, and from where
-------------------------------------------
    question, answer            record.question.text, record.text.delivered_answer.text
    evidence                    record.evidence.snapshot (prompt order; the evaluator re-verifies it)
    package                     a read-only adapter (SavedPackage) holding exactly the four attributes the
                                evaluator reads from a live package: sources (the snapshot's items),
                                requirements (the snapshot's), answer_plan (rebuilt from
                                record.evaluator_inputs.answer_plan) and withheld; None when the live
                                answer had no package
    validation                  a ValidationReport rebuilt from record.validation.final
    coverage                    not passed: the evaluator reads it from the snapshot, as in any replay
    citations, model_called, fallback_type, scope_status, answerability   the record's own values
    repair                      {initial, final, repair} from record.validation: the live UI's
                                RagAnswer.metadata["validation"]; None when validation did not run. A captured
                                validation whose initial report is missing or malformed is NOT EVALUABLE

Both rebuilt objects must serialise back to exactly the saved dict; a record that does not is NOT
EVALUABLE, never approximated.

How this differs from the live evaluation in scripts/serve_ui.py
----------------------------------------------------------------
    aligner           lexical by default; the UI defaults to the semantic aligner (an embedding model).
                      --offline-aligner semantic builds the UI's own semantic aligner from the pinned local
                      embedder, and fails rather than fall back. The aligner only chooses the passage a claim
                      is compared with, but that can change a claim's verdict and the review status.
    identifier_index  not used: it is a lookup in today's database, not part of the saved evidence. A
                      section the answer names outside its evidence is then reported unverifiable, and a
                      refusal is not checked for a reserved section.

Each result records these choices in `result.evaluator`, and in `result.parity` whether each one can change
THIS answer's assessment (measured per answer: see _parity). An offline result measures a saved answer
against saved evidence; it does not show that the original generation is reproducible.

Output (`regulus_offline_evaluation_v1`), one JSON object per answers.jsonl row, in that order
---------------------------------------------------------------------------------------------
    schema, hash_algorithm, canonicalization
    execution     {execution_id, started_utc, elapsed_ms}: this execution only; NOT covered by the hash
    result        {run_id, question_id, ordinal, source, evaluator, outcome, reason,
                   review_status, review_label, score, live_check_score, assessment, review, parity}
    result_sha256 SHA-256 of canonical(result) (regulus.traceability.measurement.canonical)

outcome: `evaluated` (the evaluator returned an assessment: review_status is its PASS / FAIL / NOT
EVALUATED), `not_evaluable` (the saved data cannot support an evaluation: reason says why) or
`evaluation_error` (the evaluator, or this module, failed on a supported record). The assessment is stored
as the evaluator returned it, less `elapsed_ms` (moved to `execution`), so evaluating the same records with
the same code gives the same `result_sha256`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from regulus.accuracy import evaluate_safely
from regulus.accuracy import rubric as R
from regulus.accuracy.alignment import LexicalAligner
from regulus.accuracy.review import LABEL, question_review
from regulus.planning.shape import AnswerShape
from regulus.rag.answer_plan import AnswerPlan, EvidenceGroup, PlannedSource, ValueEntry
from regulus.rag.validation import ValidationProblem, ValidationReport
from regulus.traceability import EXACT, load as load_evidence
from regulus.traceability import measurement as M

OFFLINE_SCHEMA = "regulus_offline_evaluation_v1"
EVALUATED = "evaluated"
NOT_EVALUABLE = "not_evaluable"
EVALUATION_ERROR = "evaluation_error"


class UnsupportedRecord(ValueError):
    """The saved data cannot be turned into the evaluator's inputs without guessing."""


# ------------------------------------------------------------------ lossless rebuilding


def _keys(d: Any, what: str, required: set[str], optional: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(d, dict):
        raise UnsupportedRecord(f"{what} is not an object")
    missing, unknown = required - set(d), set(d) - required - optional
    if missing or unknown:
        raise UnsupportedRecord(f"{what}: missing {sorted(missing)}, unsupported {sorted(unknown)}")
    return d


def validation_report_from_dict(d: dict[str, Any]) -> ValidationReport:
    """The ValidationReport whose to_dict() is exactly `d`. to_dict() spreads `diagnostics` into the top
    level and adds the derived `ok` and `codes`; every other key is a field."""
    if not isinstance(d, dict):
        raise UnsupportedRecord("validation report is not an object")
    own = {f.name for f in fields(ValidationReport)} - {"diagnostics"}
    missing = own - set(d)
    if missing:
        raise UnsupportedRecord(f"validation report: missing {sorted(missing)}")
    problems = []
    for p in d["problems"]:
        _keys(p, "validation problem", {f.name for f in fields(ValidationProblem)})
        problems.append(ValidationProblem(**p))
    report = ValidationReport(
        status=d["status"], problems=tuple(problems), addressed=tuple(d["addressed"]),
        unaddressed=tuple(d["unaddressed"]), cited=tuple(d["cited"]), invalid_citations=tuple(d["invalid_citations"]),
        truncated=d["truncated"], finished=d["finished"], generated_tokens=d["generated_tokens"],
        max_new_tokens=d["max_new_tokens"], answer_class=d["answer_class"],
        diagnostics={k: v for k, v in d.items() if k not in own | {"ok", "codes"}})
    if report.to_dict() != d:
        raise UnsupportedRecord("validation report does not round-trip losslessly (ok/codes inconsistent "
                                "with its problems, or a diagnostics key shadows a field)")
    return report


def answer_plan_from_dict(d: dict[str, Any]) -> AnswerPlan:
    """The AnswerPlan whose to_dict() is exactly `d` (EvidenceGroup.items is derived and checked)."""
    _keys(d, "answer plan", {"shape", "mode", "lead_in", "groups", "context", "related", "sources", "notes"}, {"values"})
    s = _keys(d["shape"], "answer shape", {"mode", "scope", "exhaustive", "requested_units", "focus_terms",
                                           "signals", "rationale"})
    shape = AnswerShape(mode=s["mode"], scope=s["scope"], exhaustive=s["exhaustive"],
                        requested_units=tuple(s["requested_units"]), focus_terms=tuple(s["focus_terms"]),
                        signals=tuple(s["signals"]), rationale=s["rationale"])
    groups = tuple(
        EvidenceGroup(key=g["key"], label=g["label"], heading=g["heading"], kind=g["kind"], head=g["head"],
                      members=tuple(g["members"]), requirement_ids=tuple(g["requirement_ids"]))
        for g in (_keys(g, "evidence group", {"key", "label", "heading", "kind", "head", "members", "items",
                                              "requirement_ids"}) for g in d["groups"]))
    sources = tuple(
        PlannedSource(index=p["index"], citation=p["citation"], tier=p["tier"], role=p["role"], section=p["section"],
                      paragraph=p["paragraph"], heading=p["heading"], qualifiers=tuple(p["qualifiers"]),
                      applicability=p["applicability"], cross_references=tuple(p["cross_references"]),
                      requirement_ids=tuple(p["requirement_ids"]))
        for p in (_keys(p, "planned source", {f.name for f in fields(PlannedSource)}) for p in d["sources"]))
    values = tuple(ValueEntry(**_keys(v, "value entry", {f.name for f in fields(ValueEntry)}))
                   for v in d.get("values", ()))
    plan = AnswerPlan(shape=shape, mode=d["mode"], lead_in=tuple(d["lead_in"]), groups=groups,
                      context=tuple(d["context"]), related=tuple(d["related"]), sources=sources,
                      notes=tuple(d["notes"]), values=values)
    if plan.to_dict() != d:
        raise UnsupportedRecord("answer plan does not round-trip losslessly")
    return plan


class SavedPackage:
    """The generation package as the evaluator reads it, from saved data only.

    Exactly the attributes regulus.accuracy reads from a package (pinned by
    tests/test_offline_evaluation.py): anything else raises AttributeError, as it would on a snapshot."""

    __slots__ = ("sources", "requirements", "answer_plan", "withheld")

    def __init__(self, snapshot, answer_plan: AnswerPlan | None, withheld) -> None:
        self.sources = snapshot.items
        self.requirements = snapshot.requirements
        self.answer_plan = answer_plan
        self.withheld = tuple((str(c), str(t)) for c, t in withheld)


# ------------------------------------------------------------------ one record


def aligner_identity(aligner) -> dict[str, Any]:
    """Which aligner this execution used, and for a semantic one, which embedder."""
    embedder = getattr(aligner, "_embedder", None)
    described = embedder.describe() if embedder is not None and hasattr(embedder, "describe") else None
    return {"method": getattr(aligner, "method", None), "embedder": described}


def semantic_aligner():
    """The live UI's semantic aligner, built exactly as scripts/serve_ui.py Engine.aligner builds it (the pinned
    manifest embedder, local files only) - but with NO lexical fallback: if the embedder is not available
    locally this raises, so a run asked for semantic alignment never silently gets lexical. Loads a ~33M
    parameter encoder; it is never called unless --offline-aligner semantic is given."""
    from regulus.accuracy.alignment import SemanticAligner
    from regulus.config import load_settings
    from regulus.retrieval.semantic import TransformersEmbedder, load_manifest

    embedder = TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir,
                                    local_files_only=True)
    return SemanticAligner(embedder)


def evaluator_identity(root: Path, aligner=None) -> dict[str, Any]:
    """The evaluator code this execution ran, from the repository as it is now (never assumed)."""
    def git(*args: str) -> bytes | None:
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=30, check=True).stdout
        except Exception:  # noqa: BLE001
            return None

    commit, status, diff = git("rev-parse", "HEAD"), git("status", "--porcelain"), git("diff", "HEAD")
    return {"rubric_id": R.RUBRIC_ID, "rubric_version": R.RUBRIC_VERSION, "evaluator_version": None,
            "git_commit": commit.decode().strip() if commit else None,
            "git_dirty": bool(status.strip()) if status is not None else None,
            "tracked_diff_sha256": hashlib.sha256(diff).hexdigest() if diff is not None else None,
            "entry_point": "regulus.accuracy.evaluate_safely",
            "aligner": aligner_identity(aligner or LexicalAligner())["method"],
            "embedder": aligner_identity(aligner or LexicalAligner())["embedder"],
            "identifier_index": "not_used", "repair_argument": "passed"}


# ------------------------------------------------------------------ parity with the live evaluation
#
# The reference is the live evaluation of scripts/serve_ui.py (Engine.assess) in its default configuration.
# Offline differs from it in at most two inputs, and for each one whether the difference can matter for a
# GIVEN answer is measured here, not assumed. (The repair record, the third input that once differed, is now
# passed exactly as the live UI passes it, so its status is always identical.)
#
#   aligner           the UI default is semantic. If no claim of this answer was aligned to any passage (every
#                     align() returned nothing - both aligners apply the same lexical floor first), the aligner
#                     had no effect; otherwise lexical alignment may pick a different passage: LIMITED.
#   identifier_index  the UI looks up, in today's database, CFR provisions the answer names that its evidence
#                     does not account for (and, for a refusal, whether a requested section is reserved). A
#                     probe index records the lookups the live evaluator would make; none means no effect.
#   repair            identical: record.validation {initial, final, repair}, as RagAnswer.metadata["validation"].
#
# Status per input: identical (same input), no_effect (differs, but cannot change this assessment), limited
# (differs and may change it). `live_equivalent` is true only when every input is identical or no_effect: the
# assessment then has the live one's verdicts, claims, dimensions, score and review status, and differs from
# it at most in the recorded configuration flags `checked.aligner` and `checked.identifier_index_used`.

IDENTICAL, NO_EFFECT, LIMITED = "identical", "no_effect", "limited"
LIVE_REFERENCE = {"source": "scripts/serve_ui.py Engine.assess, default configuration", "aligner": "semantic",
                  "identifier_index": "database (DatabaseIdentifierIndex)",
                  "repair": "RagAnswer.metadata['validation'] (initial, final, repair)"}


class _CountingAligner:
    """The aligner, unchanged, counting the claims it aligned to at least one passage."""

    def __init__(self, inner) -> None:
        self._inner, self.method, self.aligned = inner, inner.method, 0

    def prepare(self, claims, candidates) -> None:
        prepare = getattr(self._inner, "prepare", None)
        if prepare is not None:
            prepare(claims, candidates)

    def align(self, claim, candidates, **kwargs):
        out = self._inner.align(claim, candidates, **kwargs)
        self.aligned += bool(out)
        return out


class _IndexProbe:
    """Stands in for the live identifier index to learn which lookups the live evaluator would make. Every
    provision is answered as existing and live; the probe's assessment is discarded. Whether ANY lookup is
    made does not depend on the answers (the first lookup precedes them all), so `lookups` empty is exact;
    the list itself is what the evaluator asks when every answer is (exists, live)."""

    def __init__(self) -> None:
        self.lookups: list[dict[str, str]] = []

    def section_status(self, section: str) -> tuple[bool, bool]:
        self.lookups.append({"kind": "section", "id": str(section)})
        return True, True

    def part_status(self, part: str) -> tuple[bool, bool]:
        self.lookups.append({"kind": "part", "id": str(part)})
        return True, True


def _parity(aligner_method: str, aligned: int, lookups: list[dict[str, str]]) -> dict[str, Any]:
    if aligner_method == LIVE_REFERENCE["aligner"]:
        aligner = {"status": IDENTICAL, "offline": aligner_method}
    else:
        aligner = {"status": LIMITED if aligned else NO_EFFECT, "offline": aligner_method, "claims_aligned": aligned}
    index = {"status": LIMITED if lookups else NO_EFFECT, "lookups": lookups}
    repair = {"status": IDENTICAL, "detail": "the saved validation record (initial, final, repair) is passed as "
                                              "the live UI passes it"}
    parts = {"aligner": aligner, "identifier_index": index, "repair": repair}
    return {"reference": LIVE_REFERENCE, **parts,
            "live_equivalent": all(v["status"] in (IDENTICAL, NO_EFFECT) for v in parts.values())}


def _inputs(record: dict[str, Any], row: dict[str, Any], run_id: str) -> dict[str, Any]:
    """The evaluator's keyword arguments from a record, or UnsupportedRecord saying why there are none."""
    problems = M.verify_record(record)
    if problems:
        raise UnsupportedRecord("measurement record failed its integrity check: " + "; ".join(problems))
    if record.get("status") != M.STATUS_CAPTURED:
        raise UnsupportedRecord(f"measurement record status is {record.get('status')}: {record.get('error')}")
    if (record.get("run") or {}).get("run_id") != run_id:
        raise UnsupportedRecord(f"measurement record belongs to run {(record.get('run') or {}).get('run_id')!r}")
    question, answer = record["question"]["text"], record["text"]["delivered_answer"]["text"]
    if record["question"].get("matches_pipeline_question") is not True:
        raise UnsupportedRecord("the pipeline answered a different question text than the benchmark question")
    if row.get("question") != question:
        raise UnsupportedRecord("answers.jsonl question text differs from the measurement record's")
    if row.get("answer") != answer:
        raise UnsupportedRecord("answers.jsonl answer differs from the measurement record's delivered answer")
    evidence = record["evidence"]
    if evidence.get("provenance") != EXACT or evidence.get("snapshot") is None:
        raise UnsupportedRecord(f"no exact evidence snapshot ({evidence.get('reason')})")
    row_snapshot = row.get("evidence_snapshot")
    if row_snapshot is not None and row_snapshot.get("fingerprint") != evidence["fingerprint"]:
        raise UnsupportedRecord("answers.jsonl evidence snapshot differs from the measurement record's")
    ei = record.get("evaluator_inputs")
    if ei is None:
        raise UnsupportedRecord("the record predates evaluator-input capture (no evaluator_inputs: no answer "
                                "plan, withheld rows or scope status)")
    validation = record["validation"]
    if validation["state"] == M.CAPTURED:
        # the repair-aware completeness check reads the INITIAL report's problems: without a sound one it
        # cannot run, and evaluating anyway could show a completeness PASS the live UI would withdraw
        if not isinstance(validation.get("initial"), dict):
            raise UnsupportedRecord("the saved validation record has no initial report, so the repair-aware "
                                    "completeness check cannot run")
        try:
            validation_report_from_dict(validation["initial"])
        except UnsupportedRecord as exc:
            raise UnsupportedRecord(f"the saved initial validation report is malformed ({exc})") from None
        if not (validation.get("repair") is None or isinstance(validation["repair"], str)):
            raise UnsupportedRecord("the saved repair kind is malformed")
        report = validation_report_from_dict(validation["final"])
        # exactly what the live UI passes: RagAnswer.metadata["validation"] (serve_ui Engine.assess)
        repair = {"initial": validation["initial"], "final": validation["final"], "repair": validation["repair"]}
    elif validation["state"] == M.NOT_APPLICABLE:
        report = repair = None                  # validation did not run: the live UI passes None too
    else:
        raise UnsupportedRecord(f"validation state is {validation['state']}")
    snapshot = load_evidence(evidence["snapshot"])
    package = None
    if ei["package_present"]:
        plan = answer_plan_from_dict(ei["answer_plan"]) if ei["answer_plan"] is not None else None
        package = SavedPackage(snapshot, plan, ei["withheld"])
    return dict(question=question, answer=answer, package=package, evidence=evidence["snapshot"],
                citations=record["citations"], validation=report, model_called=ei["model_called"],
                fallback_type=validation.get("fallback_type"), scope_status=ei["scope_status"],
                answerability=validation.get("answerability"), repair=repair)


def evaluate_record(record: dict[str, Any] | None, row: dict[str, Any], *, run_id: str, ordinal: int,
                    evaluator: dict[str, Any], aligner=None) -> tuple[dict[str, Any], float]:
    """(result, elapsed_ms) for one answers.jsonl row and its measurement record (None: there is none)."""
    t0 = time.perf_counter()
    try:
        row_sha = M.sha256_json(row)
    except ValueError:                           # e.g. a NaN, which json.loads accepts and canonical() refuses
        row_sha = None
    result: dict[str, Any] = {
        "run_id": run_id, "question_id": row.get("question_id"), "ordinal": ordinal,
        "source": {"measurement_record_sha256": (record or {}).get("record_sha256"),
                   "evidence_fingerprint": ((record or {}).get("evidence") or {}).get("fingerprint"),
                   "answers_row_sha256": row_sha},
        "evaluator": evaluator, "outcome": None, "reason": None,
        "review_status": None, "review_label": None, "score": None, "live_check_score": None,
        "assessment": None, "review": None, "parity": None,
    }
    try:
        if record is None:
            legacy = M.legacy_view(row, ordinal)
            raise UnsupportedRecord("no measurement record for this question (a historical row holds evidence "
                                    f"{legacy['evidence']['provenance']}, validation {legacy['validation']['state']}); "
                                    "nothing is reconstructed")
        kwargs = _inputs(record, row, run_id)
    except UnsupportedRecord as exc:
        result.update(outcome=NOT_EVALUABLE, reason=str(exc))
        return result, (time.perf_counter() - t0) * 1000.0
    except Exception as exc:  # noqa: BLE001 - a malformed record is this row's problem only
        result.update(outcome=NOT_EVALUABLE, reason=f"malformed measurement record: {type(exc).__name__}: {exc}")
        return result, (time.perf_counter() - t0) * 1000.0
    try:
        question, answer = kwargs.pop("question"), kwargs.pop("answer")
        counting = _CountingAligner(aligner or LexicalAligner())
        assessment = evaluate_safely(question, answer, aligner=counting, **kwargs).to_dict()
        assessment.pop("elapsed_ms", None)
        assessment = json.loads(json.dumps(assessment, ensure_ascii=False, default=str))
        review = question_review(assessment, question=question)
        probe = _IndexProbe()                    # a second, discarded evaluation: which lookups would live make?
        evaluate_safely(question, answer, aligner=LexicalAligner(), identifier_index=probe, **kwargs)
        result["parity"] = _parity(counting.method, counting.aligned, probe.lookups)
    except Exception as exc:  # noqa: BLE001
        result.update(outcome=EVALUATION_ERROR, reason=f"{type(exc).__name__}: {exc}"[:2000])
        return result, (time.perf_counter() - t0) * 1000.0
    failed = assessment.get("status") == R.ERROR
    result.update(outcome=EVALUATION_ERROR if failed else EVALUATED, reason=assessment.get("reason") if failed else None,
                  review_status=review["status"], review_label=LABEL.get(review["status"]),
                  score=assessment.get("accuracy"), live_check_score=review.get("live_check_score"),
                  assessment=assessment, review=review)
    return result, (time.perf_counter() - t0) * 1000.0


# ------------------------------------------------------------------ a run


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def evaluate_run(run_dir: Path | str, out_path: Path | str, *, root: Path, aligner=None,
                 execution_id: str | None = None) -> dict[str, Any]:
    """Evaluate every answers.jsonl row of `run_dir` into the NEW file `out_path` (refused if it exists).
    Returns a summary; the run's answers.jsonl and measurement.jsonl are verified byte-identical after."""
    run_dir, out_path = Path(run_dir), Path(out_path)
    inputs = [run_dir / "answers.jsonl", run_dir / M.MEASUREMENT_FILE]
    before = {str(p): p.read_bytes() if p.is_file() else None for p in inputs}
    if before[str(inputs[0])] is None:
        raise FileNotFoundError(f"{inputs[0]} does not exist")
    execution_id = execution_id or uuid.uuid4().hex
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    aligner = aligner or LexicalAligner()
    evaluator = evaluator_identity(root, aligner)
    problems: list[str] = []

    records: dict[str, dict[str, Any]] = {}
    unusable: dict[str, str] = {}
    for n, line in enumerate(_lines(inputs[1]), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            qid = rec["question_id"]
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{M.MEASUREMENT_FILE}:{n}: unreadable ({exc})")
            continue
        if qid in records or qid in unusable:
            unusable[qid] = f"{M.MEASUREMENT_FILE} holds more than one record for this question"
            records.pop(qid, None)
            continue
        records[qid] = rec

    rows: list[dict[str, Any]] = []
    for n, line in enumerate(_lines(inputs[0]), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            problems.append(f"answers.jsonl:{n}: unreadable ({exc})")
    seen: dict[Any, int] = {}
    for r in rows:
        seen[r.get("question_id")] = seen.get(r.get("question_id"), 0) + 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with out_path.open("x", encoding="utf-8") as f:            # never overwrites an earlier evaluation
        for ordinal, row in enumerate(rows, start=1):
            qid = row.get("question_id")
            if qid is None or seen[qid] > 1 or qid in unusable:
                why = ("the answers.jsonl row has no question_id" if qid is None else
                       "question_id appears more than once in answers.jsonl" if seen[qid] > 1 else unusable[qid])
                result, ms = evaluate_record(None, row, run_id=run_dir.name, ordinal=ordinal, evaluator=evaluator)
                result.update(outcome=NOT_EVALUABLE, reason=why)
            else:
                result, ms = evaluate_record(records.get(qid), row, run_id=run_dir.name, ordinal=ordinal,
                                             evaluator=evaluator, aligner=aligner)
            line = {"schema": OFFLINE_SCHEMA, "hash_algorithm": M.HASH_ALGORITHM, "canonicalization": M.CANONICALIZATION,
                    "execution": {"execution_id": execution_id, "started_utc": started, "elapsed_ms": round(ms, 3)},
                    "result": result, "result_sha256": M.sha256_json(result)}
            f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            key = result["outcome"] if result["outcome"] != EVALUATED else f"{EVALUATED}:{result['review_label']}"
            counts[key] = counts.get(key, 0) + 1
    orphans = sorted(set(records) - set(seen), key=str)
    if orphans:
        problems.append(f"{M.MEASUREMENT_FILE}: records without an answers.jsonl row: {', '.join(map(str, orphans))}")
    after = {str(p): p.read_bytes() if p.is_file() else None for p in inputs}
    return {"run_dir": str(run_dir), "output": str(out_path), "execution_id": execution_id, "rows": len(rows),
            "counts": counts, "problems": problems, "inputs_unchanged": before == after}


def verify_result(line: dict[str, Any]) -> list[str]:
    """Integrity problems of one output line ([] when result_sha256 matches its result)."""
    if line.get("schema") != OFFLINE_SCHEMA:
        return [f"unknown offline evaluation schema {line.get('schema')!r}"]
    return [] if line.get("result_sha256") == M.sha256_json(line.get("result")) else ["result_sha256 does not match"]
