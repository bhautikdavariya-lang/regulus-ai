"""Tests for Phase B key verification.

The verifier's job is to be right about what it can settle and honest about
what it cannot. Its first draft was wrong in both directions - it called a
reserved provision nonexistent, and it called a disagreement with an internal
crosswalk a defect in the contract's answer key - so these tests pin the
distinctions that were got wrong:

* reserved is not nonexistent;
* a false premise is not a claim that a section is absent;
* a section-level crosswalk cannot settle a question-level "no ISO clause";
* a clause the standard does not contain is a contradiction, while a clause
  the crosswalk maps differently is a conflict for a reviewer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from regulus.evaluation.acceptance_benchmark import BenchmarkQuestion, load_acceptance_benchmark
from regulus.evaluation.key_verification import (
    CONFIRMED,
    CONTRADICTED,
    DIM_CITATION,
    DIM_COMPLETENESS,
    DIM_ISO,
    DIM_NEGATIVE_CONTROL,
    DIM_PARAGRAPH,
    DIM_SUBSTANTIVE,
    DIM_TEMPORAL,
    NOT_APPLICABLE,
    REQUIRES_SME,
    STATUS_AWAITING_SME,
    STATUS_CONTRADICTED,
    STATUS_VERIFIED,
    UNVERIFIABLE,
    classify_draft_key,
    declaration_of,
    verify_benchmark,
    verify_question,
)

WORKBOOK = Path("Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx")
needs_workbook = pytest.mark.skipif(not WORKBOOK.is_file(), reason="workbook not present")


class FakeSources:
    """A tiny stand-in for the snapshot and the approved crosswalk."""

    def __init__(self, sections=None, paragraphs=(), crosswalk=None, clauses=("8.2.2", "4.2.5", "7.3.5")):
        self.sections = sections or {}
        self.paragraphs = set(paragraphs)
        self._crosswalk = crosswalk or {}
        self.clauses = set(clauses)

    def section_state(self, section):
        return self.sections.get(section, {"exists": False, "live": False, "reserved": False, "covered_by": None})

    def paragraph_exists(self, section, paragraph):
        return (section, paragraph) in self.paragraphs

    def crosswalk(self, section):
        return self._crosswalk.get(section, [])

    def iso_clause_exists(self, clause):
        return clause in self.clauses

    def describe(self):
        return {"ecfr_snapshot_date": "2026-09-03", "crosswalk_rows": len(self._crosswalk),
                "iso_clause_index": ["ISO 13485:2016"], "iso_clause_text_available": False}


LIVE = {"exists": True, "live": True, "reserved": False, "covered_by": None}
RESERVED = {"exists": True, "live": False, "reserved": True, "covered_by": "820.20-820.30"}
ABSENT = {"exists": False, "live": False, "reserved": False, "covered_by": None}


def question(**kw) -> BenchmarkQuestion:
    base = dict(question_id="T-1", domain="d", focus="f", question_type="Direct Lookup",
                difficulty="Basic", question="q?", expected_citation_draft="21 CFR 111.1",
                iso_clause_draft="—", iso_clause_title="—", key_answer_elements="e",
                key_verified="unmarked", row=2)
    base.update(kw)
    return BenchmarkQuestion(**base)


def finding(q, sources, dimension):
    return next(f for f in verify_question(q, sources) if f.dimension == dimension)


# ------------------------------------------------------- key classification


def test_a_draft_key_is_not_always_a_citation():
    assert classify_draft_key("21 CFR 111.1") == "plain_citation"
    assert classify_draft_key("NO SUCH SECTION — 21 CFR 111.900 does not exist") == "negative_declaration"
    assert classify_draft_key("TEMPORAL TRAP — 820.198 is [Reserved]") == "temporal_declaration"
    assert classify_draft_key("MUST DECLINE — ISO 13485 is copyrighted") == "scope_declaration"


def test_the_negative_control_declarations_are_distinguished():
    assert declaration_of("NO SUCH SECTION — 111.900") == "NO SUCH SECTION"
    assert declaration_of("FALSE PREMISE — 820.20 is [Reserved]") == "FALSE PREMISE"
    assert declaration_of("REPEALED PROVISION — 820.30 is [Reserved]") == "REPEALED PROVISION"
    assert declaration_of("NO SUCH CLAUSE — ISO 13485:2016 ends at Clause 8") == "NO SUCH CLAUSE"
    assert declaration_of("NO SUCH LIMIT") == "NO SUCH REQUIREMENT-LIKE THING"
    assert declaration_of("21 CFR 111.1") is None


# ------------------------------------------------------------- citations


def test_a_live_citation_is_confirmed():
    q = question(expected_citation_draft="21 CFR 111.1")
    assert finding(q, FakeSources({"111.1": LIVE}), DIM_CITATION).status == CONFIRMED


def test_a_citation_to_something_not_live_is_contradicted():
    """The X-004 case: a key citing a range that runs past the last section."""
    q = question(expected_citation_draft="21 CFR 4.100 through 4.110")
    f = finding(q, FakeSources({"4.100": LIVE, "4.110": ABSENT}), DIM_CITATION)
    assert f.status == CONTRADICTED
    assert "4.110" in f.detail


def test_a_paragraph_that_does_not_exist_is_contradicted():
    q = question(expected_citation_draft="21 CFR 820.10(b)(9)")
    sources = FakeSources({"820.10": LIVE}, paragraphs=[("820.10", "(b)(2)")])
    assert finding(q, sources, DIM_PARAGRAPH).status == CONTRADICTED
    q2 = question(expected_citation_draft="21 CFR 820.10(b)(2)")
    assert finding(q2, sources, DIM_PARAGRAPH).status == CONFIRMED


def test_a_key_with_no_paragraph_claim_is_not_scored_on_paragraphs():
    q = question(expected_citation_draft="21 CFR 111.1")
    assert finding(q, FakeSources({"111.1": LIVE}), DIM_PARAGRAPH).status == NOT_APPLICABLE


# -------------------------------------------------------------- temporal


def test_a_reserved_provision_is_confirmed_not_flagged():
    q = question(question_type="Temporal/Version",
                 expected_citation_draft="TEMPORAL TRAP — 820.198 is [Reserved]; complaint record "
                                         "content is now specified at 21 CFR 820.35(a)")
    sources = FakeSources({"820.198": RESERVED, "820.35": LIVE}, paragraphs=[("820.35", "(a)")])
    assert finding(q, sources, DIM_TEMPORAL).status == CONFIRMED
    # the routing target is the positive expectation and is checked as live
    assert finding(q, sources, DIM_CITATION).status == CONFIRMED


def test_every_provision_a_temporal_key_calls_reserved_is_checked():
    """The first draft dropped only the first reference and wrongly flagged
    keys that listed several reserved provisions."""
    q = question(question_type="Temporal/Version",
                 expected_citation_draft="TEMPORAL TRAP — 820.181, 820.184 and 820.30(j) are "
                                         "[Reserved]; those constructs are not in the current part")
    sources = FakeSources({"820.181": RESERVED, "820.184": RESERVED, "820.30": RESERVED})
    assert finding(q, sources, DIM_TEMPORAL).status == CONFIRMED
    assert finding(q, sources, DIM_CITATION).status == NOT_APPLICABLE
    assert finding(q, sources, DIM_PARAGRAPH).status == NOT_APPLICABLE


def test_a_key_calling_a_live_provision_reserved_is_contradicted():
    q = question(question_type="Temporal/Version",
                 expected_citation_draft="TEMPORAL TRAP — 820.35 is [Reserved]")
    f = finding(q, FakeSources({"820.35": LIVE}), DIM_TEMPORAL)
    assert f.status == CONTRADICTED and "820.35" in f.detail


# ------------------------------------------------------ negative controls


def test_no_such_section_is_confirmed_when_the_section_is_absent():
    q = question(question_type="Negative Control",
                 expected_citation_draft="NO SUCH SECTION — 21 CFR 111.900 does not exist")
    assert finding(q, FakeSources({"111.900": ABSENT}), DIM_NEGATIVE_CONTROL).status == CONFIRMED


def test_no_such_section_is_contradicted_when_the_section_is_there():
    q = question(question_type="Negative Control",
                 expected_citation_draft="NO SUCH SECTION — 21 CFR 111.1 does not exist")
    assert finding(q, FakeSources({"111.1": LIVE}), DIM_NEGATIVE_CONTROL).status == CONTRADICTED


def test_a_reserved_provision_is_not_called_nonexistent():
    """A false premise about a reserved section is not a claim of absence.
    Treating it as one was the verifier's own bug."""
    q = question(question_type="Negative Control",
                 expected_citation_draft="FALSE PREMISE — 21 CFR 820.20 is [Reserved] as of "
                                         "February 2, 2026; no management review frequency is set")
    f = finding(q, FakeSources({"820.20": RESERVED}), DIM_NEGATIVE_CONTROL)
    assert f.status == CONFIRMED
    assert "reserved" in f.detail


def test_a_false_premise_about_a_live_section_goes_to_a_reviewer():
    q = question(question_type="Negative Control",
                 expected_citation_draft="FALSE PREMISE — see 21 CFR 1.505/1.506")
    f = finding(q, FakeSources({"1.505": LIVE, "1.506": LIVE}), DIM_NEGATIVE_CONTROL)
    assert f.status == REQUIRES_SME


def test_an_absence_that_is_not_a_section_goes_to_a_reviewer():
    for draft in ("NO SUCH REQUIREMENT", "NO SUCH LIMIT", "NO SUCH GUIDANCE", "NO SUCH SUBPART"):
        q = question(question_type="Negative Control", expected_citation_draft=draft)
        assert finding(q, FakeSources(), DIM_NEGATIVE_CONTROL).status == REQUIRES_SME, draft


def test_a_nonexistent_iso_clause_is_checked_against_the_index():
    q = question(question_type="Negative Control",
                 question="What does ISO 13485:2016 Clause 9.4 require?",
                 expected_citation_draft="NO SUCH CLAUSE — ISO 13485:2016 ends at Clause 8")
    assert finding(q, FakeSources(), DIM_NEGATIVE_CONTROL).status == CONFIRMED
    present = question(question_type="Negative Control",
                       question="What does ISO 13485:2016 Clause 8.2.2 require?",
                       expected_citation_draft="NO SUCH CLAUSE — ends at Clause 8")
    assert finding(present, FakeSources(), DIM_NEGATIVE_CONTROL).status == CONTRADICTED


# ------------------------------------------------------------ ISO clauses


def test_a_clause_the_crosswalk_agrees_with_is_confirmed():
    q = question(iso_clause_draft="4.2.5", iso_clause_title="Control of records",
                 expected_citation_draft="21 CFR 820.35(a)")
    sources = FakeSources({"820.35": LIVE}, paragraphs=[("820.35", "(a)")],
                          crosswalk={"820.35": [{"clause": "4.2.5", "clause_title": "Control of records",
                                                 "resolution_status": "current"}]})
    assert finding(q, sources, DIM_ISO).status == CONFIRMED


def test_a_clause_outside_the_standard_is_contradicted():
    q = question(iso_clause_draft="9.4", iso_clause_title="x", expected_citation_draft="21 CFR 820.35")
    sources = FakeSources({"820.35": LIVE},
                          crosswalk={"820.35": [{"clause": "4.2.5", "resolution_status": "current"}]})
    f = finding(q, sources, DIM_ISO)
    assert f.status == CONTRADICTED and "9.4" in f.detail


def test_a_crosswalk_disagreement_is_a_reviewer_conflict_not_a_defect():
    """The crosswalk is an internal approved mapping at section granularity;
    the contract's authority is the controlled standard, which is not held."""
    q = question(iso_clause_draft="8.2.2", iso_clause_title="Complaint handling",
                 expected_citation_draft="21 CFR 820.35(a)")
    sources = FakeSources({"820.35": LIVE}, paragraphs=[("820.35", "(a)")],
                          crosswalk={"820.35": [{"clause": "4.2.5", "resolution_status": "current"}]})
    f = finding(q, sources, DIM_ISO)
    assert f.status == REQUIRES_SME
    assert "controlled copy" in f.detail
    assert f.evidence["disputed"] == ["8.2.2"]


def test_a_question_level_no_clause_cannot_be_settled_by_a_section_crosswalk():
    q = question(iso_clause_draft="None", iso_clause_title="—",
                 expected_citation_draft="21 CFR 820.1(a)(2)")
    sources = FakeSources({"820.1": LIVE}, paragraphs=[("820.1", "(a)(2)")],
                          crosswalk={"820.1": [{"clause": "1", "resolution_status": "current"},
                                               {"clause": "4.1", "resolution_status": "current"}]})
    f = finding(q, sources, DIM_ISO)
    assert f.status == REQUIRES_SME
    assert "maps sections, not questions" in f.detail


def test_a_clause_range_is_not_matched_clause_by_clause():
    q = question(iso_clause_draft="1 through 8 (entire standard)", iso_clause_title="x",
                 expected_citation_draft="21 CFR 820.7(b)")
    sources = FakeSources({"820.7": LIVE}, crosswalk={"820.7": [{"clause": "2", "resolution_status": "current"}]})
    assert finding(q, sources, DIM_ISO).status == UNVERIFIABLE


def test_a_clause_outside_the_index_numbering_is_unverifiable_not_wrong():
    q = question(iso_clause_draft="0.1; 3", iso_clause_title="x", expected_citation_draft="21 CFR 820.3(b)")
    sources = FakeSources({"820.3": LIVE}, paragraphs=[("820.3", "(b)")], clauses={"3"},
                          crosswalk={"820.3": [{"clause": "3", "resolution_status": "current"}]})
    f = finding(q, sources, DIM_ISO)
    assert f.status == UNVERIFIABLE and "0.1" in f.detail


def test_rows_outside_g7_are_not_scored_on_iso():
    q = question(iso_clause_draft="—")
    assert finding(q, FakeSources({"111.1": LIVE}), DIM_ISO).status == NOT_APPLICABLE


# ------------------------------------------------------ judgment stays human


def test_substance_and_completeness_are_never_decided_by_this_module():
    q = question(expected_citation_draft="21 CFR 111.1")
    findings = verify_question(q, FakeSources({"111.1": LIVE}))
    for dimension in (DIM_SUBSTANTIVE, DIM_COMPLETENESS):
        assert next(f for f in findings if f.dimension == dimension).status == REQUIRES_SME


# ------------------------------------------------------------- the artifact


class _Bench:
    benchmark_id = "b"
    benchmark_key = "b@0"
    sha256 = "0" * 64
    path = "w.xlsx"

    def __init__(self, questions):
        self.questions = tuple(questions)


def test_a_row_with_an_outstanding_judgment_never_reaches_verified():
    art = verify_benchmark(_Bench([question(expected_citation_draft="21 CFR 111.1")]),
                           FakeSources({"111.1": LIVE}))
    row = art.rows[0]
    assert row.verification_status == STATUS_AWAITING_SME
    assert row.key_verified is False
    assert row.accepted_expectation is None
    assert row.verified_citation is None and row.verified_iso_clause is None


def test_a_contradiction_wins_over_an_outstanding_judgment():
    art = verify_benchmark(_Bench([question(expected_citation_draft="21 CFR 4.110")]),
                           FakeSources({"4.110": ABSENT}))
    assert art.rows[0].verification_status == STATUS_CONTRADICTED
    assert art.rows[0].contradictions
    assert art.rows[0].accepted_expectation is None


def test_the_draft_is_carried_alongside_and_never_replaced():
    art = verify_benchmark(_Bench([question(expected_citation_draft="21 CFR 4.110", iso_clause_draft="8.2.2")]),
                           FakeSources({"4.110": ABSENT}))
    row = art.rows[0]
    assert row.expected_citation_draft == "21 CFR 4.110"
    assert row.expected_iso_clause_draft == "8.2.2"
    assert row.to_dict()["expected_ISO_clause_draft"] == "8.2.2"
    assert row.verification_notes


def test_the_artifact_blocks_scoring_until_the_key_is_locked():
    art = verify_benchmark(_Bench([question(expected_citation_draft="21 CFR 111.1")]),
                           FakeSources({"111.1": LIVE}))
    summary = art.summary()
    assert summary["key_is_locked"] is False
    assert summary["scoring_status"].startswith("BLOCKED")
    assert "invalidates the entire result" in summary["scoring_status"]


def test_the_artifact_serialises_with_the_required_fields():
    art = verify_benchmark(_Bench([question()]), FakeSources({"111.1": LIVE}), verifier="An SME")
    row = art.to_dict()["rows"][0]
    for field in ("benchmark_id", "question_id", "verification_status", "verification_source",
                  "verified_citation", "verified_answer_elements", "verified_ISO_clause",
                  "verification_notes", "verifier", "verification_timestamp"):
        assert field in row, field
    assert row["verifier"] == "An SME"
    assert art.to_dict()["workbook_sha256"] == "0" * 64


# ------------------------------------------------------- the real workbook


@needs_workbook
def test_the_real_workbook_verifies_without_the_file_changing():
    import hashlib

    before = hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()
    bench = load_acceptance_benchmark(WORKBOOK)
    art = verify_benchmark(bench, FakeSources())
    assert len(art.rows) == 300
    assert hashlib.sha256(WORKBOOK.read_bytes()).hexdigest() == before
    # with no sources at all nothing can be confirmed, and nothing is invented
    assert art.summary()["verified_rows"] == 0
    assert all(r.accepted_expectation is None for r in art.rows)
