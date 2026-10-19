"""The ONE implementation of contractual acceptance scoring, and the verdict validator in front of it.

Every acceptance number - the per-row verdict rule, the pass rate, the rubric dimension shares and the
workbook's seven gates - is computed here and nowhere else. The results-workbook builder
(scripts/build_acceptance_results.py) and the dashboard adapter (regulus.dashboard.adapters.acceptance)
both call this module, so the same verdict records cannot produce two different gate values.

Sources of every rule (nothing here is invented):

* the benchmark workbook, `Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx`, tabs *Instructions &
  Gates* and *Scoring Rubric*: the columns L-Q and their allowed values, the gates and their
  thresholds (transcribed as `acceptance_benchmark.GATES`), "Column Q is scored on every row whose
  column H is not '—'" (§3g), "Partial runs do not satisfy the gate" (§3e), and "G2 and G3 are
  absolute. A single failure on either is a failed acceptance test regardless of every other score";
* `docs/STAGE_A_RUBRIC.md` (`regulus_substantive_rubric_v1`): the row verdict rule (§5), the four
  verdicts, "a row's rubric scores are recorded whatever the verdict", UNDETERMINED "never used as a
  soft FAIL or a soft PASS", and "any invented identifier sets M=1, which fails the row outright".

Validation comes first and is strict. A record that is malformed, duplicated, out of range, missing a
score its verdict requires, or whose recorded verdict contradicts the rule is an ISSUE with its file,
line, question id and field, and `score_run` refuses to compute any metric while an issue exists. Nothing
is repaired, truncated, relabelled or skipped.

Exclusions are explicit. A gate is computed over DECIDED rows (PASS or FAIL). ERROR, UNDETERMINED and
unscored rows are counted, never folded into a numerator, and never allowed to make a gate pass: while
any exist the gate can be FAILED (it fails even if every excluded row were perfect) but never PASSED.

Gate statuses: PASS, FAIL, INCOMPLETE (blocked: excluded rows could still decide it), PROVISIONAL (met
under a definition still awaiting contractual confirmation) and NOT_MEASURED (its scope cannot be
established). Only PASS counts towards acceptance; an incomplete run is never accepted.

Gate G3 is PROVISIONAL. The contract names it "Negative control pass rate" and defines no per-row pass.
By decision (2026-10-14) it is scored provisionally on rubric L alone - the contract's L legend reads
"for negative controls, 1 = correctly declined" - and the full row rule is reported beside it for
comparison. G3 can be FAILED or INCOMPLETE but never PASS, and so the run never accepted, until the
contractual definition is approved.
"""

from __future__ import annotations

import glob
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from regulus.evaluation.acceptance_benchmark import GATES, Gate

RUBRIC_ID = "regulus_substantive_rubric_v1"

PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"
UNDETERMINED = "UNDETERMINED"
RESULTS = (PASS, FAIL, ERROR, UNDETERMINED)
DECIDED = (PASS, FAIL)

COLUMNS = ("L", "M", "N", "O", "P", "Q")
ALLOWED: dict[str, tuple[int, ...]] = {"L": (0, 1), "M": (0, 1), "N": (0, 1, 2), "O": (0, 1, 2), "P": (0, 1), "Q": (0, 1)}
REQUIRED_ON_JUDGED = ("L", "M", "N", "O", "P")      # Q depends on ISO scope

# Field names that, misspelt or case-shifted, would silently drop a score or a verdict.
_SEMANTIC = {name.lower(): name for name in (*COLUMNS, "id", "result")}
# Workbook columns that are not part of the verdict record; their presence means a mis-keyed score.
_FOREIGN_COLUMNS = ("K", "R")

VERDICT_GLOB = "verdicts_*.jsonl"

# Overall acceptance
ACCEPTED = "PASS"
NOT_ACCEPTED = "FAIL"
NOT_DETERMINABLE = "NOT_DETERMINABLE"

# Gate statuses
GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_INCOMPLETE = "INCOMPLETE"
GATE_PROVISIONAL = "PROVISIONAL"
GATE_NOT_MEASURED = "NOT_MEASURED"

G3_DEFINITION = "rubric_L"           # provisional, pending contractual confirmation
G3_PROVISIONAL_NOTE = (
    "PROVISIONAL, pending contractual confirmation: G3 is scored on rubric L alone (the contract's L legend: "
    "'for negative controls, 1 = correctly declined'). The full row rule of regulus_substantive_rubric_v1 is "
    "reported for comparison. G3 is never PASS - and the run never accepted - until the definition is approved."
)
G3_UNRESOLVED_NOTE = G3_PROVISIONAL_NOTE     # former name, kept for callers


# ------------------------------------------------------------------ issues


@dataclass(frozen=True)
class VerdictIssue:
    """One validation failure, located precisely enough to fix."""

    source: str
    line: int | None
    question_id: str | None
    field: str | None
    reason: str

    def __str__(self) -> str:
        where = self.source + (f":{self.line}" if self.line is not None else "")
        who = f" [{self.question_id}]" if self.question_id else ""
        what = f" {self.field}:" if self.field else ""
        return f"{where}{who}{what} {self.reason}"

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "line": self.line, "question_id": self.question_id,
                "field": self.field, "reason": self.reason}


class VerdictValidationError(ValueError):
    """Raised instead of publishing a metric computed from invalid verdict records."""

    def __init__(self, issues: Sequence[VerdictIssue]):
        self.issues = tuple(issues)
        shown = "\n  ".join(str(i) for i in self.issues[:25])
        more = f"\n  ... and {len(self.issues) - 25} more" if len(self.issues) > 25 else ""
        super().__init__(f"{len(self.issues)} verdict record issue(s); no acceptance metric is computed:\n  {shown}{more}")


# ------------------------------------------------------------------ records


@dataclass(frozen=True)
class VerdictRecord:
    question_id: str
    result: Any
    raw: Mapping[str, Any]
    source: str
    line: int

    def score(self, column: str) -> Any:
        return self.raw.get(column)


@dataclass(frozen=True)
class VerdictSet:
    """Every verdict record read, the files they came from, and every reading problem.

    `records` holds the FIRST record per id. A repeated id is never resolved by file order: it is an
    issue, whether or not the two records agree."""

    records: dict[str, VerdictRecord]
    files: tuple[str, ...]
    read_issues: tuple[VerdictIssue, ...] = ()

    def rows(self) -> dict[str, dict[str, Any]]:
        return {qid: dict(r.raw) for qid, r in self.records.items()}


def read_verdict_files(paths: Iterable[str | Path]) -> VerdictSet:
    """Parse verdict JSONL files in the order given. Never skips a line silently."""
    records: dict[str, VerdictRecord] = {}
    files: list[str] = []
    issues: list[VerdictIssue] = []
    for path in paths:
        path = Path(path)
        files.append(path.name)
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError as exc:
                    issues.append(VerdictIssue(path.name, number, None, None, f"malformed JSON ({exc.msg})"))
                    continue
                if not isinstance(record, dict):
                    issues.append(VerdictIssue(path.name, number, None, None,
                                               f"a verdict record must be a JSON object, not {type(record).__name__}"))
                    continue
                qid = record.get("id")
                if not isinstance(qid, str) or not qid.strip():
                    issues.append(VerdictIssue(path.name, number, None, "id", f"missing or invalid question id {qid!r}"))
                    continue
                if qid in records:
                    first = records[qid]
                    same = dict(first.raw) == record
                    issues.append(VerdictIssue(
                        path.name, number, qid, "id",
                        f"duplicate verdict ({'identical to' if same else 'conflicts with'} {first.source}:{first.line}); "
                        "a later record never replaces an earlier one silently - remove one, or supersede it explicitly"))
                    continue
                records[qid] = VerdictRecord(qid, record.get("result"), record, path.name, number)
    return VerdictSet(records, tuple(files), tuple(issues))


def read_verdicts(directory: str | Path) -> VerdictSet:
    """Every `verdicts_*.jsonl` in `directory` (a run's scoring/ folder), in sorted order."""
    return read_verdict_files(sorted(glob.glob(str(Path(directory) / VERDICT_GLOB))))


# ------------------------------------------------------------------ the rule


def full_pass(scores: Mapping[str, Any]) -> bool:
    """regulus_substantive_rubric_v1 §5: PASS iff L=1 and M=0 and N=2 and O>=1 and P=1 and Q in {1, blank}.

    Exact integer comparison: a string "2" or a boolean is not a score and never satisfies the rule."""

    def is_(column: str, *values: int) -> bool:
        v = scores.get(column)
        return type(v) is int and v in values

    q = scores.get("Q")
    return (is_("L", 1) and is_("M", 0) and is_("N", 2) and is_("O", 1, 2) and is_("P", 1)
            and (q is None or is_("Q", 1)))


# ------------------------------------------------------------------ validation


def _scope(benchmark) -> tuple[set[str] | None, set[str] | None, set[str] | None]:
    if benchmark is None:
        return None, None, None
    ids = {q.question_id for q in benchmark.questions}
    return ids, {q.question_id for q in benchmark.questions if q.in_g7_scope}, \
        {q.question_id for q in benchmark.negative_controls}


def validate(verdicts: VerdictSet, benchmark=None) -> tuple[VerdictIssue, ...]:
    """Every issue that makes these records unfit to score. Empty means valid.

    Without the benchmark (`benchmark=None`) the id and ISO-scope checks cannot be made; they are not
    assumed to pass - the metrics that need them (G3, G7, unscored rows) are then not computed."""
    issues = list(verdicts.read_issues)
    ids, iso, _ = _scope(benchmark)
    for qid, rec in verdicts.records.items():
        raw = rec.raw

        def bad(fld: str | None, reason: str) -> None:
            issues.append(VerdictIssue(rec.source, rec.line, qid, fld, reason))

        if ids is not None and qid not in ids:
            bad("id", "not a question id of this benchmark")
        for key in raw:
            if key in _FOREIGN_COLUMNS:
                bad(key, f"workbook column {key} is not part of a verdict record (a mis-keyed score?)")
            elif key not in _SEMANTIC.values() and key.lower() in _SEMANTIC:
                bad(key, f"field name differs from the scoring field {_SEMANTIC[key.lower()]!r} only by case; "
                         "it would be ignored")
        result = raw.get("result")
        if result not in RESULTS:
            bad("result", f"{result!r} is not a verdict; allowed: {', '.join(RESULTS)}")
            continue
        for column in COLUMNS:
            value = raw.get(column)
            if value is None:
                continue
            if type(value) is not int:
                bad(column, f"{value!r} ({type(value).__name__}) is not an integer score; allowed: "
                            f"{', '.join(map(str, ALLOWED[column]))}")
            elif value not in ALLOWED[column]:
                bad(column, f"{value} is out of range; allowed: {', '.join(map(str, ALLOWED[column]))}")
        if result == ERROR:
            scored = [c for c in COLUMNS if raw.get(c) is not None]
            if scored:
                bad(",".join(scored), "an ERROR row produced no answer to judge, so it carries no rubric score")
            continue
        # PASS, FAIL and UNDETERMINED: "a row's rubric scores are recorded whatever the verdict"
        for column in REQUIRED_ON_JUDGED:
            if raw.get(column) is None:
                bad(column, f"required on a {result} row (the rubric scores every judged row)")
        if iso is not None:
            if qid in iso and raw.get("Q") is None:
                bad("Q", "required: the row is in ISO scope (column H is not '—')")
            elif qid not in iso and raw.get("Q") is not None:
                bad("Q", "must be blank: the row is outside ISO scope (column H reads '—')")
        if result == UNDETERMINED:
            notes = raw.get("notes")
            if not isinstance(notes, str) or not notes.strip():
                bad("notes", "an UNDETERMINED verdict is recorded with its reason")
            if raw.get("M") == 1:
                bad("M", "M=1 fails the row outright; it cannot be UNDETERMINED")
        typed = all(raw.get(c) is None or (type(raw.get(c)) is int and raw.get(c) in ALLOWED[c]) for c in COLUMNS)
        complete = all(raw.get(c) is not None for c in REQUIRED_ON_JUDGED)
        if result in DECIDED and typed and complete:
            rule = full_pass(raw)
            if result == PASS and not rule:
                bad("result", "recorded PASS, but the scores fail the verdict rule "
                              "(L=1, M=0, N=2, O>=1, P=1, Q in {1, blank})")
            elif result == FAIL and rule:
                bad("result", "recorded FAIL, but the scores satisfy the verdict rule")
    return tuple(issues)


# ------------------------------------------------------------------ scoring


@dataclass(frozen=True)
class Ratio:
    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        return self.numerator / self.denominator if self.denominator else None

    def to_dict(self) -> dict[str, Any]:
        return {"numerator": self.numerator, "denominator": self.denominator, "value": self.value}


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    value: float | None
    numerator: float | None
    denominator: int | None
    excluded: dict[str, int]
    passed: bool | None
    resolved: bool = True
    readings: dict[str, dict[str, Any]] = field(default_factory=dict)
    note: str | None = None
    status: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            object.__setattr__(self, "status", _status(self))

    @property
    def provisional(self) -> bool:
        return not self.resolved

    def to_dict(self) -> dict[str, Any]:
        g = self.gate
        return {
            "gate_id": g.gate_id, "metric": g.metric, "threshold": g.threshold, "comparison": g.comparison,
            "unit": g.unit, "absolute": g.absolute, "scored_on": g.scored_on, "why_it_matters": g.why_it_matters,
            "measured": self.value, "numerator": self.numerator, "denominator": self.denominator,
            "excluded": dict(self.excluded), "passed": self.passed, "status": self.status,
            "definition_resolved": self.resolved, "provisional": self.provisional,
            "readings": {k: dict(v) for k, v in self.readings.items()}, "note": self.note,
        }


def _status(g: "GateResult") -> str:
    """PASS only for a decided pass under a confirmed definition; FAIL only for a decided failure."""
    if g.passed is True:
        return GATE_PASS
    if g.passed is False:
        return GATE_FAIL
    if any(g.excluded.values()):
        return GATE_INCOMPLETE
    if g.value is None:
        return GATE_NOT_MEASURED
    return GATE_PROVISIONAL if not g.resolved else GATE_INCOMPLETE


@dataclass(frozen=True)
class AcceptanceScore:
    """Everything a report may state about one run's verdicts, with every denominator explicit."""

    rubric_id: str
    benchmark_questions: int | None
    counts: dict[str, int | None]          # PASS, FAIL, ERROR, UNDETERMINED, unscored (None: no benchmark)
    pass_rate: Ratio                      # PASS / (PASS + FAIL)
    dimensions: dict[str, Ratio]
    negative_control_readings: dict[str, Ratio] | None
    gates: tuple[GateResult, ...]
    acceptance: str
    acceptance_reasons: tuple[str, ...]
    row_verdicts: dict[str, bool | None]   # True PASS, False FAIL, None ERROR/UNDETERMINED
    unresolved: tuple[dict[str, Any], ...] = ()   # every UNDETERMINED record, with its documented reason

    @property
    def excluded(self) -> dict[str, int | None]:
        return {k: self.counts[k] for k in (ERROR, UNDETERMINED, "unscored")}

    def gate(self, gate_id: str) -> GateResult | None:
        return next((g for g in self.gates if g.gate.gate_id == gate_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rubric_id": self.rubric_id, "benchmark_questions": self.benchmark_questions,
            "counts": dict(self.counts), "pass_rate": self.pass_rate.to_dict(),
            "pass_rate_excludes": dict(self.excluded),
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "negative_control_readings": ({k: v.to_dict() for k, v in self.negative_control_readings.items()}
                                          if self.negative_control_readings is not None else None),
            "gates": [g.to_dict() for g in self.gates],
            "acceptance": self.acceptance, "acceptance_reasons": list(self.acceptance_reasons),
            "unresolved_records": [dict(u) for u in self.unresolved],
        }


def _meets(gate: Gate, value: float) -> bool:
    return value >= gate.threshold if gate.comparison == ">=" else value == gate.threshold


def _ratio_gate(gate: Gate, numerator: float, denominator: int, excluded: dict[str, int], best_numerator: float,
                best_denominator: int) -> GateResult:
    """A ratio gate. `best_*` is the value if every excluded row were perfect: the gate is FAILED only when
    even that misses the threshold, and PASSED only when nothing is excluded."""
    value = numerator / denominator if denominator else None
    pending = sum(excluded.values())
    passed: bool | None
    if value is None and not pending:
        passed = None
    elif pending:
        best = best_numerator / best_denominator if best_denominator else None
        passed = False if best is not None and not _meets(gate, best) else None
    else:
        passed = _meets(gate, value)
    return GateResult(gate, value, numerator, denominator, excluded, passed)


def score_run(verdicts: VerdictSet, benchmark=None, *, gates: Sequence[Gate] | None = None) -> AcceptanceScore:
    """Score validated verdicts. Raises VerdictValidationError rather than score invalid records."""
    issues = validate(verdicts, benchmark)
    if issues:
        raise VerdictValidationError(issues)
    gates = tuple(gates if gates is not None else (benchmark.gates if benchmark is not None else GATES))
    ids, iso, controls = _scope(benchmark)
    rows = verdicts.records
    by_result = {r: {q for q, rec in rows.items() if rec.result == r} for r in RESULTS}
    decided = by_result[PASS] | by_result[FAIL]
    unscored = (ids - set(rows)) if ids is not None else None
    counts: dict[str, int | None] = {r: len(by_result[r]) for r in RESULTS}
    counts["unscored"] = len(unscored) if unscored is not None else None
    pending_ids = by_result[ERROR] | by_result[UNDETERMINED] | (unscored or set())

    def raw(q: str) -> Mapping[str, Any]:
        return rows[q].raw

    def share(test, among: set[str]) -> Ratio:
        return Ratio(sum(1 for q in among if test(raw(q))), len(among))

    dimensions = {
        "L=1": share(lambda r: r["L"] == 1, decided),
        "M=1": share(lambda r: r["M"] == 1, decided),
        "N=2": share(lambda r: r["N"] == 2, decided),
        "N>=1": share(lambda r: r["N"] >= 1, decided),
        "O>=1": share(lambda r: r["O"] >= 1, decided),
        "P=1": share(lambda r: r["P"] == 1, decided),
    }
    if iso is not None:
        dimensions["Q=1"] = share(lambda r: r["Q"] == 1, decided & iso)

    def excluded_in(scope: set[str] | None) -> dict[str, int]:
        pool = scope if scope is not None else set(rows) | (unscored or set())
        return {ERROR: len(by_result[ERROR] & pool), UNDETERMINED: len(by_result[UNDETERMINED] & pool),
                "unscored": len((unscored or set()) & pool)}

    readings = None
    results: list[GateResult] = []
    for gate in gates:
        gid = gate.gate_id
        if gid in ("G1", "G6"):
            column = "L" if gid == "G1" else "P"
            r = share(lambda x, c=column: x[c] == 1, decided)
            ex = excluded_in(None)
            n = sum(ex.values())
            results.append(_ratio_gate(gate, r.numerator, r.denominator, ex, r.numerator + n, r.denominator + n))
        elif gid in ("G4", "G5"):
            column = "N" if gid == "G4" else "O"
            points = sum(raw(q)[column] for q in decided)
            ex = excluded_in(None)
            n = sum(ex.values())
            results.append(_ratio_gate(gate, points, 2 * len(decided), ex, points + 2 * n, 2 * (len(decided) + n)))
        elif gid == "G2":
            count = sum(1 for q in decided if raw(q)["M"] == 1)
            ex = excluded_in(None)
            passed = False if count else (None if sum(ex.values()) else True)
            results.append(GateResult(gate, float(count), float(count), len(decided), ex, passed,
                                      note="absolute: one fabricated citation fails the acceptance test"))
        elif gid == "G7":
            if iso is None:
                results.append(GateResult(gate, None, None, None, {}, None,
                                          note="ISO scope cannot be established without the benchmark workbook"))
                continue
            r = share(lambda x: x["Q"] == 1, decided & iso)
            ex = excluded_in(iso)
            n = sum(ex.values())
            results.append(_ratio_gate(gate, r.numerator, r.denominator, ex, r.numerator + n, r.denominator + n))
        elif gid == "G3":
            if controls is None:
                results.append(GateResult(gate, None, None, None, {}, None, resolved=False,
                                          note="negative-control rows cannot be established without the benchmark "
                                               "workbook. " + G3_PROVISIONAL_NOTE))
                continue
            among = decided & controls
            readings = {"rubric_L": share(lambda x: x["L"] == 1, among),
                        "rubric_v1_row_rule": share(full_pass, among)}
            provisional = readings[G3_DEFINITION]
            ex = excluded_in(controls)
            n = sum(ex.values())
            measured = _ratio_gate(gate, provisional.numerator, provisional.denominator, ex,
                                   provisional.numerator + n, provisional.denominator + n)
            # a decided failure stands under the provisional definition (and, since L=1 is necessary for
            # a full pass, under the row rule too); a met threshold is never a PASS until confirmed
            results.append(GateResult(
                gate, measured.value, measured.numerator, measured.denominator, ex,
                False if measured.passed is False else None, resolved=False,
                readings={k: v.to_dict() for k, v in readings.items()}, note=G3_PROVISIONAL_NOTE))
        else:
            results.append(GateResult(gate, None, None, None, {}, None, resolved=False,
                                      note=f"no canonical definition for gate {gid}"))

    reasons: list[str] = []
    if any(g.passed is False for g in results):
        acceptance = NOT_ACCEPTED
        reasons.append("failed: " + ", ".join(g.gate.gate_id for g in results if g.passed is False))
    elif all(g.passed is True for g in results) and results:
        acceptance = ACCEPTED
    else:
        acceptance = NOT_DETERMINABLE
        undecided = [f"{g.gate.gate_id} {g.status}" for g in results if g.passed is None]
        reasons.append("not determinable: " + ", ".join(undecided))
    if any(not g.resolved for g in results):
        reasons.append("G3 provisional pending contractual confirmation")
    if pending_ids:
        reasons.append(f"{len(pending_ids)} row(s) without a decided verdict "
                       f"(ERROR {counts[ERROR]}, UNDETERMINED {counts[UNDETERMINED]}, "
                       f"unscored {counts['unscored'] if counts['unscored'] is not None else 'unknown'}); "
                       "partial runs do not satisfy the gates")
    if counts["unscored"] is None:
        reasons.append("the benchmark question set was not available, so unscored rows cannot be counted")

    row_verdicts = {q: (True if rec.result == PASS else False if rec.result == FAIL else None)
                    for q, rec in rows.items()}
    return AcceptanceScore(
        rubric_id=RUBRIC_ID,
        benchmark_questions=len(ids) if ids is not None else None,
        counts=counts,
        pass_rate=Ratio(len(by_result[PASS]), len(decided)),
        dimensions=dimensions,
        negative_control_readings=readings,
        gates=tuple(results),
        acceptance=acceptance,
        acceptance_reasons=tuple(reasons),
        row_verdicts=row_verdicts,
        unresolved=tuple({"id": q, "reason": rows[q].raw.get("notes"), "source": rows[q].source, "line": rows[q].line}
                         for q in sorted(by_result[UNDETERMINED])),
    )
