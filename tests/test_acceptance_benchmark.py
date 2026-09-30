"""Phase A tests for the acceptance benchmark loader.

The workbook is a contractual acceptance gate, so these tests are mostly
about fidelity: every one of the 300 rows survives the trip, the evaluator's
own terminology and thresholds are preserved, and the things the workbook
says are behavioural classes are still distinguishable afterwards.

Two properties matter more than the rest and have their own tests: the draft
key is never presented as an accepted expectation until an SME has marked
column K, and the workbook file itself is never written to.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest

from regulus.evaluation.acceptance_benchmark import (
    BENCHMARK_ID,
    BENCHMARK_NAME,
    BENCHMARK_VERSION,
    DIFFICULTIES,
    DOMAIN_NEGATIVE_CONTROL,
    DOMAIN_PART_820,
    DOMAIN_SCOPE_DISCIPLINE,
    EXPECTED_QUESTION_COUNT,
    GATE_BY_ID,
    GATES,
    ISO_NAME_NO_CLAUSE,
    ISO_NAMED_CLAUSES,
    ISO_NOT_SCORED,
    KEY_UNMARKED,
    KEY_VERIFIED,
    QUESTION_TYPES,
    RUBRIC_COLUMNS,
    TYPE_ABSTENTION,
    TYPE_NEGATIVE_CONTROL,
    TYPE_SCOPE_BOUNDARY,
    TYPE_TEMPORAL_VERSION,
    AcceptanceBenchmark,
    BenchmarkError,
    leaked_questions,
    load_acceptance_benchmark,
)

WORKBOOK = Path("Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx")
needs_workbook = pytest.mark.skipif(not WORKBOOK.is_file(), reason="the acceptance workbook is not present")


@pytest.fixture(scope="module")
def benchmark() -> AcceptanceBenchmark:
    return load_acceptance_benchmark(WORKBOOK)


# --------------------------------------------------------------- ingestion


@needs_workbook
def test_all_three_hundred_questions_load(benchmark):
    assert len(benchmark) == EXPECTED_QUESTION_COUNT
    assert len(benchmark.questions) == EXPECTED_QUESTION_COUNT
    assert not benchmark.problems, benchmark.problems


@needs_workbook
def test_question_ids_are_unique_and_present(benchmark):
    ids = [q.question_id for q in benchmark]
    assert len(set(ids)) == len(ids) == EXPECTED_QUESTION_COUNT
    assert all(q.question_id.strip() for q in benchmark)
    assert benchmark.get("S-001") is not None
    assert benchmark.get("NOPE-999") is None


@needs_workbook
def test_every_row_keeps_every_field_the_workbook_gave_it(benchmark):
    for q in benchmark:
        assert q.question_id and q.domain and q.focus
        assert q.question_type in QUESTION_TYPES
        assert q.difficulty in DIFFICULTIES
        assert q.question, f"{q.question_id} lost its question text"
        assert q.expected_citation_draft, f"{q.question_id} lost its draft citation key"
        assert q.iso_clause_draft, f"{q.question_id} lost column H"
        assert q.iso_clause_title, f"{q.question_id} lost column I"
        assert q.key_answer_elements, f"{q.question_id} lost its key answer elements"
        assert q.row > 1


@needs_workbook
def test_the_question_text_is_preserved_verbatim(benchmark):
    """The workbook says to submit each question in column F verbatim."""
    q = benchmark.get("M-033")
    assert q.question == "What must a complaint file contain under 21 CFR 820.198?"
    # no truncation anywhere
    assert all(not x.question.endswith("…") for x in benchmark)
    longest = max(benchmark, key=lambda x: len(x.question))
    assert len(longest.question) > 100


@needs_workbook
def test_question_types_are_preserved_with_the_workbook_s_own_counts(benchmark):
    counts = benchmark.counts()["by_question_type"]
    # these are the workbook's own Results Summary figures
    assert counts == {
        "Direct Lookup": 188, "Distinction": 23, "Negative Control": 22,
        "Cross-Reference": 20, "Application": 20, "Scope/Boundary": 15,
        "Temporal/Version": 11, "Abstention": 1,
    }
    assert sum(counts.values()) == EXPECTED_QUESTION_COUNT


@needs_workbook
def test_domains_are_preserved_with_the_workbook_s_own_counts(benchmark):
    domains = benchmark.counts()["by_domain"]
    assert sum(domains.values()) == EXPECTED_QUESTION_COUNT
    assert domains[DOMAIN_PART_820] == 42
    assert domains[DOMAIN_NEGATIVE_CONTROL] == 22
    assert domains[DOMAIN_SCOPE_DISCIPLINE] == 13
    assert len(domains) == 23


# ----------------------------------------------------- behavioural classes


@needs_workbook
def test_negative_controls_are_identified(benchmark):
    controls = benchmark.negative_controls
    assert len(controls) == 22
    assert all(q.is_negative_control for q in controls)
    assert all(q.domain == DOMAIN_NEGATIVE_CONTROL for q in controls)
    assert {q.question_id for q in controls} == {f"NC-{i:03d}" for i in range(1, 23)}
    # the draft key states the absence rather than naming a provision
    assert any("NO SUCH SECTION" in q.expected_citation_draft for q in controls)
    # and they are not accidentally treated as ordinary lookups
    assert all(not q.is_temporal for q in controls)


@needs_workbook
def test_temporal_version_questions_are_identified(benchmark):
    temporal = benchmark.temporal_questions
    assert len(temporal) == 11
    assert all(q.is_temporal for q in temporal)
    ids = {q.question_id for q in temporal}
    assert {f"M-{i:03d}" for i in range(31, 41)} <= ids
    # the workbook's trap: these ask about sections reserved on 2 February 2026
    assert any("[Reserved]" in q.expected_citation_draft for q in temporal)


@needs_workbook
def test_scope_and_abstention_rows_are_identified(benchmark):
    assert len(benchmark.of_type(TYPE_SCOPE_BOUNDARY)) == 15
    assert len(benchmark.of_type(TYPE_ABSTENTION)) == 1
    assert all(q.is_scope_boundary for q in benchmark.of_type(TYPE_SCOPE_BOUNDARY))
    # the boundary *domain* and the boundary *question type* are different axes
    assert len(benchmark.in_domain(DOMAIN_SCOPE_DISCIPLINE)) == 13


@needs_workbook
def test_part_820_rows_carrying_an_iso_key_are_identified(benchmark):
    part_820 = benchmark.in_domain(DOMAIN_PART_820)
    assert len(part_820) == 42
    assert all(q.is_part_820_domain for q in part_820)
    # every Part 820 row is in G7 scope: none of them reads "—"
    assert all(q.in_g7_scope for q in part_820)
    named = [q for q in part_820 if q.iso_state == ISO_NAMED_CLAUSES]
    none_expected = [q for q in part_820 if q.iso_state == ISO_NAME_NO_CLAUSE]
    assert len(named) == 34 and len(none_expected) == 8
    assert all(q.iso_clauses for q in named)
    assert all(q.iso_clauses == () for q in none_expected)


@needs_workbook
def test_g7_scope_follows_column_h_not_the_domain(benchmark):
    """The workbook's rule: column Q is scored on every row whose column H is
    not '—', which is the Part 820 domain plus a few cross-domain rows."""
    scope = benchmark.g7_scope
    assert len(scope) == 51                       # the workbook's own figure
    assert all(q.iso_clause_draft != "—" for q in scope)
    cross = [q for q in scope if not q.is_part_820_domain]
    assert len(cross) == 9
    assert {q.question_id for q in cross} == {
        "X-003", "PB-005", "PB-006", "PB-008", "PB-009", "NC-005", "NC-011", "NC-016", "SD-012"}
    outside = [q for q in benchmark if not q.in_g7_scope]
    assert len(outside) == 249
    assert all(q.iso_state == ISO_NOT_SCORED for q in outside)


@needs_workbook
def test_column_h_has_three_states_not_two(benchmark):
    states = {q.iso_state for q in benchmark}
    assert states == {ISO_NOT_SCORED, ISO_NAME_NO_CLAUSE, ISO_NAMED_CLAUSES}
    # "None" is a real instruction, not an empty cell: naming a clause there is
    # a concordance failure and a fabricated citation
    none_rows = [q for q in benchmark if q.iso_state == ISO_NAME_NO_CLAUSE]
    assert len(none_rows) == 8
    assert all(q.iso_clause_draft == "None" for q in none_rows)
    assert all(q.in_g7_scope for q in none_rows), "H='None' rows are still scored on G7"


@needs_workbook
def test_iso_clause_expressions_are_parsed_without_losing_the_raw_key(benchmark):
    multi = benchmark.get("M-016")
    assert multi.iso_clause_draft == "7.2.3; 8.2.3; 8.3.3"
    assert multi.iso_clauses == ("7.2.3", "8.2.3", "8.3.3")

    # a range is flagged rather than pretended to be two clauses
    ranged = benchmark.get("M-010")
    assert ranged.is_clause_range
    assert "entire standard" in ranged.iso_clause_draft

    # the standard's own number is not read as a clause number
    other = benchmark.get("M-008")
    assert other.references_other_standard
    assert "9000" not in other.iso_clauses


# --------------------------------------------------- the draft key is draft


@needs_workbook
def test_the_draft_key_verification_state_is_preserved(benchmark):
    assert all(q.key_verified == KEY_UNMARKED for q in benchmark)
    assert all(not q.key_is_verified for q in benchmark)
    verification = benchmark.verification()
    assert verification["verified_rows"] == 0
    assert verification["total_rows"] == EXPECTED_QUESTION_COUNT
    assert verification["key_is_locked"] is False
    assert verification["status"] == "WARNING — key not fully verified"
    assert "invalidates the entire result" in verification["requirement"]


@needs_workbook
def test_an_unverified_draft_key_is_never_offered_as_an_expectation(benchmark):
    """The workbook's precondition, enforced in the schema: until an SME marks
    column K, the draft is a draft."""
    for q in benchmark:
        assert q.expected_citation_draft, "the draft is still readable"
        assert q.accepted_expectation is None, f"{q.question_id} promoted a draft key"


def test_a_verified_row_does_offer_its_expectation():
    from regulus.evaluation.acceptance_benchmark import BenchmarkQuestion

    row = BenchmarkQuestion(
        question_id="X-1", domain="d", focus="f", question_type="Direct Lookup",
        difficulty="Basic", question="q?", expected_citation_draft="21 CFR 111.1",
        iso_clause_draft="—", iso_clause_title="—", key_answer_elements="e",
        key_verified=KEY_VERIFIED, row=2)
    assert row.key_is_verified
    assert row.accepted_expectation == "21 CFR 111.1"


@needs_workbook
def test_the_tester_columns_arrive_unscored(benchmark):
    """Columns L-R are the SME's to fill in; the loader must not guess them."""
    for q in benchmark:
        assert q.score.scored is False
        assert q.score.citation_exact is None and q.score.fabricated_citation is None
        assert q.score.substantive is None and q.score.completeness is None
        assert q.score.scope_discipline is None and q.score.iso_clause_concordance is None
        assert q.score.tester_notes is None


# ------------------------------------------------------- gates and rubric


def test_the_seven_gates_carry_the_workbook_s_thresholds():
    assert [g.gate_id for g in GATES] == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert GATE_BY_ID["G1"].threshold == 0.99 and GATE_BY_ID["G1"].comparison == ">="
    assert GATE_BY_ID["G2"].threshold == 0 and GATE_BY_ID["G2"].unit == "count"
    assert GATE_BY_ID["G3"].threshold == 1.0
    assert GATE_BY_ID["G4"].threshold == 0.95
    assert GATE_BY_ID["G5"].threshold == 0.90
    assert GATE_BY_ID["G6"].threshold == 0.98
    assert GATE_BY_ID["G7"].threshold == 0.95


def test_g2_and_g3_are_marked_absolute():
    """'A single failure on either is a failed acceptance test regardless of
    every other score.'"""
    absolute = {g.gate_id for g in GATES if g.absolute}
    assert absolute == {"G2", "G3"}


def test_a_gate_never_guesses_when_it_has_not_been_measured():
    assert GATE_BY_ID["G1"].passes(None) is None
    assert GATE_BY_ID["G1"].passes(0.99) is True
    assert GATE_BY_ID["G1"].passes(0.98) is False
    assert GATE_BY_ID["G2"].passes(0) is True
    assert GATE_BY_ID["G2"].passes(1) is False, "one fabricated citation is a failure"
    assert GATE_BY_ID["G3"].passes(0.99) is False, "the negative-control gate is 100%"


def test_gate_thresholds_render_in_the_workbook_s_own_units():
    assert GATE_BY_ID["G1"].threshold_label == ">= 99%"
    assert GATE_BY_ID["G2"].threshold_label == "== 0"
    assert GATE_BY_ID["G3"].threshold_label == "== 100%"


def test_the_rubric_columns_match_the_workbook_legend():
    by_column = {r.column: r for r in RUBRIC_COLUMNS}
    assert list(by_column) == ["K", "L", "M", "N", "O", "P", "Q", "R"]
    assert by_column["M"].name == "Fabricated Citation"
    assert "1 IS A FAILURE" in by_column["M"].meaning
    assert by_column["N"].allowed == "0, 1, or 2"
    assert by_column["Q"].allowed == "1, 0 or blank"
    assert "Blank only where column H reads '—'" in by_column["Q"].meaning
    assert by_column["R"].meaning.startswith("Quote the exact wrong citation")


@needs_workbook
def test_the_instruction_and_rubric_text_is_carried_through(benchmark):
    instructions = "\n".join(benchmark.instructions)
    assert "REGULUS AI — VENDOR ACCEPTANCE BENCHMARK" in instructions
    assert "An unverified key invalidates the entire result." in instructions
    assert "G2 and G3 are absolute." in instructions
    rubric = "\n".join(benchmark.rubric_text)
    assert "FABRICATED CITATION (column M)" in rubric
    assert "reserved on February 2, 2026" in rubric


# ------------------------------------------------------------- identity


@needs_workbook
def test_benchmark_identity_is_stable_and_content_addressed(benchmark):
    assert benchmark.benchmark_id == BENCHMARK_ID
    assert BENCHMARK_NAME == "Regulus AI Acceptance Benchmark Rev 02"
    assert BENCHMARK_VERSION == "Rev 02"
    assert benchmark.label == "Regulus AI Acceptance Benchmark Rev 02, 300 questions"
    assert benchmark.sha256 == hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()
    assert benchmark.benchmark_key == f"{BENCHMARK_ID}@{benchmark.sha256[:12]}"
    # reloading gives the same identity
    again = load_acceptance_benchmark(WORKBOOK)
    assert again.benchmark_key == benchmark.benchmark_key
    assert [q.question_id for q in again] == [q.question_id for q in benchmark]


@needs_workbook
def test_a_changed_workbook_is_a_different_benchmark(tmp_path, benchmark):
    copy = tmp_path / "copy.xlsx"
    shutil.copy(WORKBOOK, copy)
    assert load_acceptance_benchmark(copy).benchmark_key == benchmark.benchmark_key
    with copy.open("ab") as handle:            # any content change changes the key
        handle.write(b"\0")
    try:
        changed = load_acceptance_benchmark(copy)
    except BenchmarkError:
        return                                  # an unreadable file is also acceptable
    assert changed.benchmark_key != benchmark.benchmark_key


@needs_workbook
def test_loading_never_writes_to_the_workbook(benchmark):
    before = (WORKBOOK.stat().st_mtime_ns, WORKBOOK.stat().st_size,
              hashlib.sha256(WORKBOOK.read_bytes()).hexdigest())
    load_acceptance_benchmark(WORKBOOK)
    after = (WORKBOOK.stat().st_mtime_ns, WORKBOOK.stat().st_size,
             hashlib.sha256(WORKBOOK.read_bytes()).hexdigest())
    assert before == after


@needs_workbook
def test_the_benchmark_serialises_without_losing_anything(benchmark):
    payload = benchmark.to_dict()
    assert payload["benchmark_key"] == benchmark.benchmark_key
    assert payload["counts"]["questions"] == EXPECTED_QUESTION_COUNT
    assert len(payload["gates"]) == 7 and len(payload["rubric_columns"]) == 8
    assert payload["verification"]["key_is_locked"] is False
    row = benchmark.get("M-033").to_dict()
    for field in ("question_id", "domain", "focus", "question_type", "difficulty", "question",
                  "expected_citation_draft", "iso_clause_draft", "iso_clause_title",
                  "key_answer_elements", "key_verified", "iso_state", "in_g7_scope"):
        assert field in row, field


# --------------------------------------------------------------- failures


def test_a_missing_workbook_is_reported_clearly(tmp_path):
    with pytest.raises(BenchmarkError, match="not found"):
        load_acceptance_benchmark(tmp_path / "nope.xlsx")


def test_a_file_that_is_not_a_workbook_is_rejected(tmp_path):
    fake = tmp_path / "fake.xlsx"
    fake.write_text("this is not a zip", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="not a readable"):
        load_acceptance_benchmark(fake)


def test_a_workbook_without_the_acceptance_sheets_is_rejected(tmp_path):
    other = tmp_path / "other.xlsx"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("xl/workbook.xml",
                         '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
                         'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
                         'officeDocument/2006/relationships"><sheets><sheet name="Sheet1" '
                         'sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
                         '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.'
                         'org/package/2006/relationships"><Relationship Id="rId1" '
                         'Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml",
                         '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                         'spreadsheetml/2006/main"><sheetData/></worksheet>')
    with pytest.raises(BenchmarkError, match="missing the sheet"):
        load_acceptance_benchmark(other)


# ---------------------------------------------------------------- leakage


@needs_workbook
def test_leakage_detection_finds_a_copied_question(benchmark):
    sample = benchmark.get("S-001").question
    hits = leaked_questions(benchmark, [f"prompt: {sample}\nanswer: ...", "unrelated text"])
    assert [h["question_id"] for h in hits] == ["S-001"]
    assert hits[0]["matches"] == 1


@needs_workbook
def test_leakage_detection_does_not_fire_on_shared_vocabulary(benchmark):
    noise = ["dietary supplement CGMP requirements are in 21 CFR Part 111",
             "who is subject to something entirely different"]
    assert leaked_questions(benchmark, noise) == []


# ------------------------------------------------- the loader stays light


def test_the_loader_does_not_drag_in_the_model_stack():
    """The dashboard's guarantee is that it loads no model, and it will read
    this benchmark. Importing the loader must not import torch."""
    import subprocess
    import sys

    probe = (
        "import sys;"
        "import regulus.evaluation.acceptance_benchmark as ab;"
        "print('torch' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                            cwd=str(Path.cwd()))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", "importing the benchmark loader pulled in torch"


def test_the_existing_evaluation_exports_still_resolve():
    """Making the package lazy must not break its public surface."""
    import regulus.evaluation as evaluation

    assert "run_evaluation" in dir(evaluation)
    assert "load_dataset" in evaluation.__all__
    with pytest.raises(AttributeError):
        evaluation.no_such_name
