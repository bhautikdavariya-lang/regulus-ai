"""The canonical acceptance scorer (regulus.evaluation.acceptance_scoring) and its verdict validator.

What these tests pin:

A. parity - the results-workbook builder and the dashboard adapter compute the same pass rate, gate
   values, numerators, denominators, exclusions and per-row verdicts from the same verdict records,
   because both call the one scorer. G3 is asserted UNRESOLVED in both, never a guessed value;
B. invalid records - every scoring-critical defect is an issue naming the file, line, question and
   field, and no metric is computed while one exists;
C. the repository's own valid runs score exactly as the two old implementations did, wherever those
   two agreed;
D. ERROR, UNDETERMINED, unscored and out-of-scope rows are counted, never folded into a numerator, and
   can never make a gate or the acceptance decision pass;
E. scoring is deterministic.

Synthetic data only, except the tests named `real_` which read (never write) artifacts/acceptance_test.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from regulus.config import PROJECT_ROOT
from regulus.dashboard.adapters import acceptance
from regulus.dashboard.schemas import INCONSISTENT
from regulus.evaluation import acceptance_scoring as S
from regulus.evaluation.acceptance_benchmark import GATES

_spec = importlib.util.spec_from_file_location("build_acceptance_results",
                                               PROJECT_ROOT / "scripts" / "build_acceptance_results.py")
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

# ------------------------------------------------------------------ a small benchmark

IDS = [f"Q-{i:03d}" for i in range(10)]
CONTROLS = {"Q-008", "Q-009"}
ISO = {"Q-006", "Q-007"}


class Bench(SimpleNamespace):
    """The parts of an AcceptanceBenchmark the scorer reads; iterable like the real one."""

    def __iter__(self):
        return iter(self.questions)


def make_bench(ids=IDS, controls=CONTROLS, iso=ISO, sha="c" * 64) -> Bench:
    questions = tuple(SimpleNamespace(question_id=q, in_g7_scope=q in iso, is_negative_control=q in controls,
                                      question=q, question_type="t", domain="d", accepted_expectation=None,
                                      key_is_verified=False)
                      for q in ids)
    return Bench(questions=questions, negative_controls=tuple(q for q in questions if q.is_negative_control),
                 gates=GATES, sha256=sha)


def row(qid, result="PASS", **scores):
    base = {"L": 1, "M": 0, "N": 2, "O": 2, "P": 1, "Q": (1 if qid in ISO else None)} if result != "ERROR" else {}
    if result == "FAIL" and not scores:
        base.update(L=0, N=0, O=0)
    base.update(scores)
    return {"id": qid, "result": result, **base, "notes": "scored", "scoring_basis": "manual_rubric_read"}


def write(directory: Path, files: dict[str, list]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, lines in files.items():
        with (directory / name).open("w", encoding="utf-8") as handle:
            for line in lines:
                handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
    return directory


def mixed_rows():
    """Every verdict kind, all valid: 4 PASS, 3 FAIL, 1 ERROR, 1 UNDETERMINED (+ a control of each)."""
    return [
        row("Q-000"), row("Q-001"), row("Q-002"),
        row("Q-003", "FAIL"), row("Q-004", "FAIL", L=1, N=1, O=1), row("Q-005", "ERROR"),
        row("Q-006"), row("Q-007", "FAIL", Q=0),
        row("Q-008", "FAIL", L=1, N=1, O=1),          # a control that declined (L=1) but fails the row rule
        {**row("Q-009", "UNDETERMINED"), "notes": "draft key in doubt"},
    ]


def issues_for(tmp_path, lines, *, b=None, files=None):
    d = write(tmp_path / "scoring", files or {"verdicts_01.jsonl": lines})
    return S.validate(S.read_verdicts(d), make_bench() if b is None else b)


# ------------------------------------------------------------------ the rule


def test_the_verdict_rule_is_the_rubric_s_and_only_exact_integers_satisfy_it():
    ok = {"L": 1, "M": 0, "N": 2, "O": 1, "P": 1, "Q": None}
    assert S.full_pass(ok) and S.full_pass({**ok, "Q": 1}) and S.full_pass({**ok, "O": 2})
    for change in ({"L": 0}, {"M": 1}, {"N": 1}, {"O": 0}, {"P": 0}, {"Q": 0},
                   {"N": "2"}, {"L": True}, {"N": 2.0}, {"O": None}):
        assert not S.full_pass({**ok, **change}), change


def test_the_adapter_and_builder_use_the_canonical_rule():
    assert acceptance._full_pass is S.full_pass
    assert acceptance.RUBRIC_ID == S.RUBRIC_ID == "regulus_substantive_rubric_v1"
    assert builder.S is S


# ------------------------------------------------------------------ B. invalid records


@pytest.mark.parametrize("record,field,reason", [
    (row("Q-000", N=3), "N", "out of range"),
    (row("Q-000", N="2"), "N", "not an integer score"),
    (row("Q-000", L=True), "L", "not an integer score"),
    ({k: v for k, v in row("Q-000").items() if k != "L"}, "L", "required on a PASS row"),
    ({k: v for k, v in row("Q-003", "FAIL").items() if k != "O"}, "O", "required on a FAIL row"),
    (row("Q-000", "MAYBE"), "result", "is not a verdict"),
    ({**row("Q-000"), "result": None}, "result", "is not a verdict"),
    (row("Q-000", N=1), "result", "recorded PASS, but the scores fail the verdict rule"),
    (row("Q-003", "FAIL", L=1, N=2, O=2), "result", "recorded FAIL, but the scores satisfy the verdict rule"),
    (row("Q-006", Q=None), "Q", "required: the row is in ISO scope"),
    (row("Q-000", Q=1), "Q", "must be blank: the row is outside ISO scope"),
    ({**row("Q-005", "ERROR"), "L": 0}, "L", "carries no rubric score"),
    ({**row("Q-009", "UNDETERMINED"), "notes": ""}, "notes", "recorded with its reason"),
    ({**row("Q-009", "UNDETERMINED", M=1, L=0, N=0, O=0), "notes": "x"}, "M", "cannot be UNDETERMINED"),
    (row("Q-999"), "id", "not a question id of this benchmark"),
    ({**row("Q-000"), "n": 2}, "n", "only by case"),
    ({**row("Q-000"), "K": "Y"}, "K", "not part of a verdict record"),
])
def test_an_invalid_record_is_an_issue_naming_file_line_question_and_field(tmp_path, record, field, reason):
    found = issues_for(tmp_path, [row("Q-001"), record])
    assert any(i.field == field and reason in i.reason for i in found), [str(i) for i in found]
    hit = next(i for i in found if i.field == field and reason in i.reason)
    assert (hit.source, hit.line) == ("verdicts_01.jsonl", 2)
    with pytest.raises(S.VerdictValidationError) as err:
        S.score_run(S.read_verdicts(tmp_path / "scoring"), make_bench())
    assert "verdicts_01.jsonl:2" in str(err.value) and "no acceptance metric is computed" in str(err.value)


def test_a_malformed_line_is_reported_never_skipped(tmp_path):
    found = issues_for(tmp_path, [row("Q-000"), '{"id": "Q-001", "result": "PASS", ', row("Q-002")])
    assert [(i.line, i.field) for i in found] == [(2, None)] and "malformed JSON" in found[0].reason


@pytest.mark.parametrize("line,reason", [('["Q-000"]', "must be a JSON object"), ('{"result": "PASS"}', "missing or invalid")])
def test_a_line_that_is_not_a_verdict_record_is_reported(tmp_path, line, reason):
    found = issues_for(tmp_path, [line])
    assert len(found) == 1 and reason in found[0].reason


@pytest.mark.parametrize("second,word", [(row("Q-000"), "identical to"), (row("Q-000", "FAIL"), "conflicts with")])
def test_a_duplicate_verdict_is_an_issue_and_a_later_file_never_wins(tmp_path, second, word):
    d = write(tmp_path / "scoring", {"verdicts_01.jsonl": [row("Q-000")], "verdicts_02.jsonl": [second]})
    verdicts = S.read_verdicts(d)
    assert verdicts.records["Q-000"].source == "verdicts_01.jsonl", "the first record is kept, not the later one"
    dup = [i for i in S.validate(verdicts, make_bench()) if i.field == "id"]
    assert len(dup) == 1 and word in dup[0].reason and "verdicts_01.jsonl:1" in dup[0].reason
    assert (dup[0].source, dup[0].line) == ("verdicts_02.jsonl", 1)


def test_an_undetermined_row_with_qualifying_scores_is_never_a_pass(tmp_path):
    """The rubric records scores whatever the verdict, so a reasoned UNDETERMINED row with qualifying
    scores is a valid record - and it never counts as a PASS anywhere."""
    lines = [row(q) for q in IDS[:9]] + [{**row("Q-009", "UNDETERMINED"), "notes": "draft key in doubt"}]
    assert S.full_pass(lines[-1]), "the scores alone would qualify"
    score = S.score_run(S.read_verdicts(write(tmp_path / "scoring", {"verdicts_01.jsonl": lines})), make_bench())
    assert score.row_verdicts["Q-009"] is None
    assert (score.pass_rate.numerator, score.pass_rate.denominator) == (9, 9)
    assert score.counts[S.UNDETERMINED] == 1 and score.acceptance != S.ACCEPTED
    # reported separately, with its documented reason and where it is recorded
    assert score.unresolved == ({"id": "Q-009", "reason": "draft key in doubt", "source": "verdicts_01.jsonl",
                                 "line": 10},)
    assert score.to_dict()["unresolved_records"][0]["reason"] == "draft key in doubt"
    assert score.gate("G3").status == S.GATE_INCOMPLETE, "an UNDETERMINED control blocks G3; it never passes it"


def test_the_dashboard_publishes_no_metric_or_gate_for_invalid_records(tmp_path, monkeypatch):
    run = synthetic_run(tmp_path, [row("Q-000", N=3)] + [row(q) for q in IDS[1:]], monkeypatch)
    loaded = acceptance.load(run, tmp_path)
    rate = loaded.metric("acceptance_full_pass")
    assert rate.value is None and rate.status == INCONSISTENT and "failed validation" in rate.note
    assert all(m.value is None for m in loaded.metrics if m.unit == "ratio")
    assert loaded.breakdowns["gates"] == [] and loaded.breakdowns["acceptance"] is None
    assert loaded.breakdowns["validation_issues"][0]["field"] == "N"
    assert any("failed validation" in p and "Q-000" in p for p in loaded.problems)
    assert all(q.correct_final is None for q in loaded.questions)


def test_the_workbook_builder_refuses_invalid_records(tmp_path):
    d = write(tmp_path / "scoring", {"verdicts_01.jsonl": [row("Q-000", N=3)] + [row(q) for q in IDS[1:]]})
    with pytest.raises(S.VerdictValidationError):
        builder.score_for_workbook(d, make_bench())


def test_the_workbook_builder_still_refuses_a_verdict_set_with_unscored_rows(tmp_path):
    d = write(tmp_path / "scoring", {"verdicts_01.jsonl": [row(q) for q in IDS[:9]]})
    with pytest.raises(SystemExit, match="verdicts missing for 1 questions"):
        builder.score_for_workbook(d, make_bench())


# ------------------------------------------------------------------ A. parity


def synthetic_run(tmp_path: Path, lines, monkeypatch, b=None) -> Path:
    run = tmp_path / "acc_20260101T000000Z"
    write(run / "scoring", {"verdicts_01.jsonl": lines})
    (run / "run_metadata.json").write_text(json.dumps({
        "started_utc": "2026-01-01T00:00:00+00:00", "finished_utc": "2026-01-01T00:00:00+00:00",
        "benchmark": {"file": "bench.xlsx", "benchmark_key": "synthetic@cccccccccccc", "questions": len(IDS),
                      "sha256_before": "c" * 64, "sha256_after": "c" * 64},
        "active_model": {"model_id": "m"}, "reproducibility": {"model_id": "m"},
    }), encoding="utf-8")
    with (run / "answers.jsonl").open("w", encoding="utf-8") as handle:
        for q in IDS:
            handle.write(json.dumps({"question_id": q, "question": q, "answer": "a", "execution_status": "OK"}) + "\n")
    monkeypatch.setattr(acceptance, "_benchmark_rows", lambda path: b or make_bench())
    return run


def test_parity_the_workbook_and_the_dashboard_agree_on_every_number(tmp_path, monkeypatch):
    run = synthetic_run(tmp_path, mixed_rows(), monkeypatch)
    dashboard = acceptance.load(run, tmp_path)
    score = builder.score_for_workbook(run / "scoring", make_bench())
    sheet = {name.split()[0]: (value, status) for name, value, _t, status, _s, _f in builder.gate_rows(score)}
    gates = {g["gate_id"]: g for g in dashboard.breakdowns["gates"]}
    assert set(sheet) == set(gates) == {f"G{i}" for i in range(1, 8)}
    for gid in sorted(gates):
        assert gates[gid]["measured"] == pytest.approx(sheet[gid][0]), gid
        assert builder.GATE_STATUS[gates[gid]["status"]] == sheet[gid][1], gid
        assert gates[gid]["definition_resolved"] is (gid != "G3")
    # numerators, denominators and exclusions, the same object in both outputs
    assert dashboard.breakdowns["acceptance"] == score.to_dict()
    rate = dashboard.metric("acceptance_full_pass")
    assert (rate.numerator, rate.denominator) == (score.pass_rate.numerator, score.pass_rate.denominator) == (4, 8)
    assert score.counts == {"PASS": 4, "FAIL": 4, "ERROR": 1, "UNDETERMINED": 1, "unscored": 0}
    assert {q.id: q.correct_final for q in dashboard.questions} == score.row_verdicts
    # G3: provisional rubric-L value (Q-008 declined: 1/1), the row rule beside it (0/1), and Q-009
    # UNDETERMINED excluded - so the gate is BLOCKED / INCOMPLETE, never PASS
    g3 = gates["G3"]
    assert (g3["measured"], g3["numerator"], g3["denominator"]) == (1.0, 1, 1) and g3["provisional"] is True
    assert g3["readings"]["rubric_v1_row_rule"]["value"] == 0.0 and g3["status"] == S.GATE_INCOMPLETE
    assert sheet["G3"][1] == "BLOCKED / INCOMPLETE"
    control = dashboard.metric("acceptance_negative_control_pass")
    assert control.value == 1.0 and "PROVISIONAL" in control.note and "full row rule gives 0/1" in control.note


def test_g3_is_scored_provisionally_on_rubric_l_and_is_never_a_pass(tmp_path):
    def g3(lines):
        return S.score_run(S.read_verdicts(write(tmp_path / f"s{len(list(tmp_path.iterdir()))}",
                                                 {"verdicts_01.jsonl": lines})), make_bench()).gate("G3")
    perfect = [row(q) for q in IDS]
    declined_not_passed = [row(q) for q in IDS[:8]] + [row(q, "FAIL", L=1, N=1, O=1) for q in ("Q-008", "Q-009")]
    answered_trap = [row(q) for q in IDS[:8]] + [row("Q-008", "FAIL"), row("Q-009")]
    gate = g3(perfect)
    assert (gate.value, gate.passed, gate.status) == (1.0, None, S.GATE_PROVISIONAL), "met, but not yet confirmed"
    gate = g3(declined_not_passed)
    assert gate.value == 1.0 and gate.readings["rubric_L"]["value"] == 1.0, "the value IS the rubric-L reading"
    assert gate.readings["rubric_v1_row_rule"]["value"] == 0.0, "the row rule is still reported for comparison"
    assert (gate.passed, gate.status) == (None, S.GATE_PROVISIONAL)
    gate = g3(answered_trap)
    assert (gate.value, gate.passed, gate.status) == (0.5, False, S.GATE_FAIL), "L=0 on a control fails G3"
    assert S.G3_DEFINITION == "rubric_L" and "pending contractual confirmation" in gate.note


# ------------------------------------------------------------------ D. denominators and exclusions


def test_excluded_rows_are_counted_and_never_in_a_numerator(tmp_path):
    d = write(tmp_path / "scoring", {"verdicts_01.jsonl": mixed_rows()[:-1]})      # Q-009 left unscored
    score = S.score_run(S.read_verdicts(d), make_bench())
    assert score.counts == {"PASS": 4, "FAIL": 4, "ERROR": 1, "UNDETERMINED": 0, "unscored": 1}
    assert (score.pass_rate.numerator, score.pass_rate.denominator) == (4, 8)
    assert score.excluded == {"ERROR": 1, "UNDETERMINED": 0, "unscored": 1}
    g1 = score.gate("G1")
    # decided rows with L=1: Q-000, Q-001, Q-002, Q-004, Q-006, Q-007, Q-008 (a FAIL row may still cite correctly)
    assert (g1.numerator, g1.denominator) == (7, 8) and g1.excluded == {"ERROR": 1, "UNDETERMINED": 0, "unscored": 1}
    g7 = score.gate("G7")
    assert (g7.numerator, g7.denominator) == (1, 2), "only the ISO-scope rows, never the out-of-scope ones"


def test_a_perfect_partial_run_passes_no_gate_and_is_not_accepted(tmp_path):
    """Every decided row perfect, one ERROR and one unscored row: no gate whose scope holds them may read
    PASS, and the run is not accepted. G7's scope (Q-006, Q-007) holds neither, so G7 alone is decided."""
    lines = [row(q) for q in IDS[:8]] + [row("Q-008", "ERROR")]
    score = S.score_run(S.read_verdicts(write(tmp_path / "s", {"verdicts_01.jsonl": lines})), make_bench())
    assert score.pass_rate.value == 1.0
    assert {g.gate.gate_id: g.passed for g in score.gates} == {
        "G1": None, "G2": None, "G3": None, "G4": None, "G5": None, "G6": None, "G7": True}
    assert {g.gate.gate_id: g.status for g in score.gates} == {
        **{gid: S.GATE_INCOMPLETE for gid in ("G1", "G2", "G3", "G4", "G5", "G6")}, "G7": S.GATE_PASS}
    assert [builder.GATE_STATUS[g.status] for g in score.gates][:6] == ["BLOCKED / INCOMPLETE"] * 6
    assert score.acceptance == S.NOT_DETERMINABLE
    assert any("partial runs do not satisfy the gates" in r for r in score.acceptance_reasons)


def test_a_gate_that_fails_even_if_every_excluded_row_were_perfect_is_failed(tmp_path):
    lines = [row(q, "FAIL") for q in IDS[:8]] + [row("Q-008", "ERROR")]
    score = S.score_run(S.read_verdicts(write(tmp_path / "s", {"verdicts_01.jsonl": lines})), make_bench())
    assert score.gate("G1").passed is False and score.acceptance == S.NOT_ACCEPTED


def test_a_fabricated_citation_fails_g2_whatever_else_is_pending(tmp_path):
    lines = [row("Q-000", "FAIL", M=1)] + [row(q) for q in IDS[1:5]]
    score = S.score_run(S.read_verdicts(write(tmp_path / "s", {"verdicts_01.jsonl": lines})), make_bench())
    assert score.gate("G2").passed is False and score.acceptance == S.NOT_ACCEPTED


def test_a_complete_perfect_run_is_still_not_accepted_while_g3_is_undecided(tmp_path):
    score = S.score_run(S.read_verdicts(write(tmp_path / "s", {"verdicts_01.jsonl": [row(q) for q in IDS]})),
                        make_bench())
    assert [g.passed for g in score.gates if g.gate.gate_id != "G3"] == [True] * 6
    assert score.gate("G3").passed is None and score.gate("G3").status == S.GATE_PROVISIONAL
    assert score.acceptance == S.NOT_DETERMINABLE
    assert "G3 provisional pending contractual confirmation" in score.acceptance_reasons


def test_without_the_benchmark_the_scope_gates_are_not_computed(tmp_path):
    score = S.score_run(S.read_verdicts(write(tmp_path / "s", {"verdicts_01.jsonl": [row(q) for q in IDS[:6]]})))
    assert score.counts["unscored"] is None and score.gate("G7").passed is None and score.gate("G3").passed is None
    assert score.acceptance == S.NOT_DETERMINABLE


# ------------------------------------------------------------------ E. determinism


def test_scoring_is_deterministic(tmp_path):
    d = write(tmp_path / "scoring", {"verdicts_02.jsonl": mixed_rows()[5:], "verdicts_01.jsonl": mixed_rows()[:5]})
    first = S.score_run(S.read_verdicts(d), make_bench()).to_dict()
    assert all(S.score_run(S.read_verdicts(d), make_bench()).to_dict() == first for _ in range(3))
    assert json.dumps(first, sort_keys=True) == json.dumps(S.score_run(S.read_verdicts(d), make_bench()).to_dict(),
                                                           sort_keys=True)


# ------------------------------------------------------------------ C. the repository's own runs


REAL = PROJECT_ROOT / "artifacts" / "acceptance_test"
VALID_RUNS = ("acceptance_rev02_20261001T083958Z", "acceptance_c123_20261007T062913Z")


@pytest.fixture(scope="module")
def real_bench():
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark

    if not (PROJECT_ROOT / DEFAULT_WORKBOOK).is_file() or not REAL.is_dir():
        pytest.skip("the benchmark workbook or the acceptance runs are not in this checkout")
    return load_acceptance_benchmark()


def _old_workbook_gates(rows, bench):
    """The removed sheet formulas, re-stated: COUNT() skips blank cells; G3 summed column L over controls."""
    def col(c):
        return [r[c] for r in rows.values() if r.get(c) is not None]
    controls = {q.question_id for q in bench.negative_controls}
    return {"G1": sum(col("L")) / len(col("L")), "G2": float(sum(col("M"))),
            "G3": sum(r["L"] for i, r in rows.items() if i in controls) / len(controls),
            "G4": sum(col("N")) / (2 * len(col("N"))), "G5": sum(col("O")) / (2 * len(col("O"))),
            "G6": sum(col("P")) / len(col("P")), "G7": sum(col("Q")) / len(col("Q"))}


@pytest.mark.parametrize("run", VALID_RUNS)
def test_real_valid_runs_score_as_both_old_implementations_did(real_bench, run):
    verdicts = S.read_verdicts(REAL / run / "scoring")
    assert S.validate(verdicts, real_bench) == ()
    score = S.score_run(verdicts, real_bench)
    old = _old_workbook_gates(verdicts.rows(), real_bench)
    for gid in ("G1", "G2", "G4", "G5", "G6", "G7"):
        assert score.gate(gid).value == pytest.approx(old[gid]), gid
    g3 = score.gate("G3")
    assert g3.value == pytest.approx(old["G3"]), "provisional G3 is the old workbook's rubric-L value"
    assert g3.readings["rubric_L"]["value"] == pytest.approx(old["G3"]) and g3.status == S.GATE_FAIL
    assert all(g.status == S.GATE_FAIL for g in score.gates)
    old_dashboard = sum(1 for r in verdicts.rows().values() if r["result"] != "ERROR" and S.full_pass(r))
    assert score.pass_rate.numerator == old_dashboard
    assert score.acceptance == S.NOT_ACCEPTED


@pytest.mark.parametrize("run", VALID_RUNS)
def test_real_parity_workbook_and_dashboard_on_the_repository_runs(real_bench, run, tmp_path):
    dashboard = acceptance.load(REAL / run, PROJECT_ROOT)
    score = builder.score_for_workbook(REAL / run / "scoring", real_bench)
    assert dashboard.breakdowns["acceptance"] == score.to_dict()
    sheet = {name.split()[0]: (value, status) for name, value, _t, status, *_ in builder.gate_rows(score)}
    for gate in dashboard.breakdowns["gates"]:
        assert gate["measured"] == pytest.approx(sheet[gate["gate_id"]][0])
        assert builder.GATE_STATUS[gate["status"]] == sheet[gate["gate_id"]][1]


def test_real_sft2_run_is_refused_with_its_exact_reasons(real_bench):
    run = REAL / "acceptance_sft2_v1_20261006T095516Z"
    if not run.is_dir():
        pytest.skip("sft2_v1 run not in this checkout")
    issues = S.validate(S.read_verdicts(run / "scoring"), real_bench)
    reasons = {(i.field, i.reason.split(":")[0]) for i in issues}
    assert len(issues) == 72
    assert reasons == {("N", "required on a FAIL row (the rubric scores every judged row)"),
                       ("O", "required on a FAIL row (the rubric scores every judged row)"),
                       ("Q", "required")}
