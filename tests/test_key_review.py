"""Tests for the controlled SME key-review workflow and the hard gates.

The system's whole purpose is to make one thing impossible: scoring or
training against an answer key nobody has verified. So most of these tests
try to do exactly that, in every way a hurried person might: with no review,
with a partial review, with decisions but no sign-off, with judgments missing,
and by editing history. Each must fail safely.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.evaluation.acceptance_gate import (
    AcceptanceGateError,
    gate_status,
    locked_key_for,
    require_benchmark_not_in_training,
    require_locked_key,
)
from regulus.evaluation.key_review import (
    JUDGMENT_DIMENSIONS,
    STATE_ACCEPTED,
    STATE_CORRECTED,
    STATE_NEEDS_RESEARCH,
    STATE_REJECTED,
    STATE_REQUIRES_SME,
    STATE_UNREVIEWED,
    STATE_VERIFIED,
    Decision,
    Judgment,
    KeyReview,
    ReviewError,
    append_decision,
    load_review,
    read_decisions,
    write_baseline,
    write_locked_key,
    write_signoff,
)
from regulus.evaluation.key_verification import (
    CONTRADICTED,
    REQUIRES_SME,
    Finding,
    RowVerification,
    VerificationArtifact,
)

from .test_key_verification import question as make_question

RUN_ID = "20260101T000000Z"


# ------------------------------------------------------------------ fixtures


class FakeBenchmark:
    benchmark_id = "regulus_acceptance_rev02"
    sha256 = "a" * 64
    path = "workbook.xlsx"

    def __init__(self, questions):
        self.questions = tuple(questions)

    @property
    def benchmark_key(self):
        return f"{self.benchmark_id}@{self.sha256[:12]}"

    @property
    def label(self):
        return f"benchmark, {len(self.questions)} questions"

    def get(self, question_id):
        return next((q for q in self.questions if q.question_id == question_id), None)


def _row(question_id, status="AWAITING_SME", findings=()):
    return RowVerification(
        benchmark_id="regulus_acceptance_rev02", question_id=question_id,
        verification_status=status, verification_source="eCFR snapshot 2026-09-03",
        verified_citation=None, verified_answer_elements=None, verified_iso_clause=None,
        verification_notes="", verifier=None, verification_timestamp="2026-01-01T00:00:00+00:00",
        findings=tuple(findings), expected_citation_draft="21 CFR 111.1", expected_iso_clause_draft="—",
    )


def make_review(question_ids=("Q-1", "Q-2"), rows=None) -> KeyReview:
    questions = [make_question(question_id=q) for q in question_ids]
    benchmark = FakeBenchmark(questions)
    verification = VerificationArtifact(
        benchmark_id=benchmark.benchmark_id, benchmark_key=benchmark.benchmark_key,
        workbook_sha256=benchmark.sha256, workbook_path=benchmark.path,
        generated_at="2026-01-01T00:00:00+00:00", sources={},
        rows=tuple(rows or [_row(q) for q in question_ids]),
    )
    return KeyReview(benchmark=benchmark, verification=verification, verification_run_id=RUN_ID)


def judgments(value="correct"):
    return [Judgment(d, value, "reviewed against the provision text") for d in JUDGMENT_DIMENSIONS]


def resolve_all(review, reviewer="SME"):
    for q in review.benchmark.questions:
        review.decide(q.question_id, STATE_ACCEPTED, reviewer, "checked", judgments=judgments())


# ------------------------------------------- 1-2 immutability and versioning


def test_the_baseline_is_frozen_and_recoverable(tmp_path):
    review = make_review()
    path = write_baseline(review.benchmark, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["workbook_sha256"] == review.benchmark.sha256
    assert payload["benchmark_key"] == review.benchmark.benchmark_key
    assert len(payload["questions"]) == len(review.benchmark.questions)
    # writing the same baseline again is a no-op, not a corruption
    write_baseline(review.benchmark, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_a_different_workbook_cannot_overwrite_the_baseline(tmp_path):
    review = make_review()
    write_baseline(review.benchmark, tmp_path)
    other = make_review()
    other.benchmark.sha256 = "b" * 64
    with pytest.raises(ReviewError, match="new version, not an overwrite"):
        write_baseline(other.benchmark, tmp_path)


def test_the_locked_key_carries_its_own_content_hash():
    review = make_review()
    resolve_all(review)
    review.sign_off("SME", "Director", "2026-09-03", "ISO 13485:2016(E)")
    locked = review.locked_key()
    assert len(locked["key_version_sha256"]) == 64
    assert locked["benchmark_key"] == review.benchmark.benchmark_key
    assert locked["workbook_sha256"] == review.benchmark.sha256


# ---------------------------------------------------- 3-7 state transitions


def test_an_unreviewed_row_starts_as_requires_sme_not_verified():
    review = make_review()
    assert review.state("Q-1") == STATE_REQUIRES_SME
    assert review.state("Q-1") != STATE_VERIFIED


def test_accept_correct_reject_and_research_are_all_recordable():
    review = make_review(("Q-1", "Q-2", "Q-3", "Q-4"))
    review.decide("Q-1", STATE_ACCEPTED, "SME", "key is right", judgments=judgments())
    review.decide("Q-2", STATE_CORRECTED, "SME", "range overruns", judgments=judgments(),
                  corrected_citation="21 CFR 4.100 through 4.105")
    review.decide("Q-3", STATE_REJECTED, "SME", "question is ambiguous")
    review.decide("Q-4", STATE_NEEDS_RESEARCH, "SME", "needs the controlled ISO copy")
    assert review.state("Q-1") == STATE_ACCEPTED
    assert review.state("Q-2") == STATE_CORRECTED
    assert review.state("Q-3") == STATE_REJECTED
    assert review.state("Q-4") == STATE_NEEDS_RESEARCH


def test_a_reviewer_cannot_declare_a_row_verified():
    """VERIFIED is derived at sign-off. Asserting it directly is refused."""
    review = make_review()
    with pytest.raises(ReviewError, match="derived at sign-off"):
        review.decide("Q-1", STATE_VERIFIED, "SME", "looks fine")


def test_a_correction_must_say_what_the_key_should_be():
    review = make_review()
    with pytest.raises(ReviewError, match="must record what the key should say"):
        review.decide("Q-1", STATE_CORRECTED, "SME", "wrong", judgments=judgments())


def test_only_a_correction_may_carry_a_corrected_key():
    review = make_review()
    with pytest.raises(ReviewError, match="only a CORRECTED decision"):
        review.decide("Q-1", STATE_ACCEPTED, "SME", "fine", corrected_citation="21 CFR 1.1")


def test_every_decision_names_a_reviewer_and_a_rationale():
    review = make_review()
    with pytest.raises(ReviewError, match="name its reviewer"):
        review.decide("Q-1", STATE_ACCEPTED, "  ", "why")
    with pytest.raises(ReviewError, match="carry a rationale"):
        review.decide("Q-1", STATE_ACCEPTED, "SME", "   ")


# ------------------------------------------------- 8 audit and provenance


def test_decisions_are_append_only_and_keep_their_history(tmp_path):
    review = make_review()
    first = review.decide("Q-1", STATE_NEEDS_RESEARCH, "SME", "parked")
    append_decision(first, tmp_path)
    second = review.decide("Q-1", STATE_ACCEPTED, "SME", "resolved", judgments=judgments())
    append_decision(second, tmp_path)

    assert review.state("Q-1") == STATE_ACCEPTED           # latest wins
    assert [d.state for d in review.history("Q-1")] == [STATE_NEEDS_RESEARCH, STATE_ACCEPTED]
    on_disk = read_decisions(tmp_path)
    assert [d.state for d in on_disk] == [STATE_NEEDS_RESEARCH, STATE_ACCEPTED], "history is kept"


def test_a_decision_records_who_when_and_why(tmp_path):
    review = make_review()
    decision = review.decide("Q-1", STATE_ACCEPTED, "A. Reviewer", "checked against 111.1",
                             judgments=judgments(), evidence_refs=["ecfr:111.1"])
    payload = decision.to_dict()
    for field in ("reviewer", "decided_at", "rationale", "evidence_refs", "verification_run_id",
                  "benchmark_key", "review_version", "original_citation"):
        assert payload[field] not in (None, "", [])
    assert payload["judgments"][0]["rationale"]


def test_a_decision_against_a_different_benchmark_is_refused():
    review = make_review()
    stray = Decision(
        benchmark_id="x", benchmark_key="other@0", verification_run_id=RUN_ID, question_id="Q-1",
        state=STATE_ACCEPTED, reviewer="SME", rationale="r", decided_at="2026-01-01T00:00:00+00:00",
        original_citation="c", original_iso_clause="—")
    with pytest.raises(ReviewError, match="this review is of"):
        review.record(stray)


def test_a_decision_for_an_unknown_question_is_refused():
    review = make_review()
    with pytest.raises(ReviewError, match="not a question in this benchmark"):
        review.decide("NOPE", STATE_ACCEPTED, "SME", "r", judgments=judgments())


# ------------------------------------------------- 19 no silent key mutation


def test_a_correction_never_replaces_the_original_key():
    review = make_review()
    original = review.benchmark.get("Q-1").expected_citation_draft
    review.decide("Q-1", STATE_CORRECTED, "SME", "overruns", judgments=judgments(),
                  corrected_citation="21 CFR 4.100 through 4.105")
    decision = review.latest("Q-1")
    assert decision.original_citation == original
    assert decision.corrected_citation == "21 CFR 4.100 through 4.105"
    assert review.benchmark.get("Q-1").expected_citation_draft == original, "the benchmark is untouched"


def test_a_signed_review_is_sealed_against_further_decisions():
    review = make_review()
    resolve_all(review)
    review.sign_off("SME", "Director", "2026-09-03", "ISO")
    with pytest.raises(ReviewError, match="sealed"):
        review.decide("Q-1", STATE_ACCEPTED, "SME", "second thoughts", judgments=judgments())


def test_a_locked_key_file_cannot_be_overwritten(tmp_path):
    write_locked_key({"benchmark_key": "b@0"}, tmp_path)
    with pytest.raises(ReviewError, match="immutable"):
        write_locked_key({"benchmark_key": "b@0"}, tmp_path)


def test_a_signoff_file_cannot_be_overwritten(tmp_path):
    write_signoff({"reviewer": "SME"}, tmp_path)
    with pytest.raises(ReviewError, match="sealed"):
        write_signoff({"reviewer": "Someone else"}, tmp_path)


# ------------------------------------------------------ 9-13 the real cases


def test_x004_is_an_sme_decision_carrying_the_automated_evidence():
    """X-004's key cites 4.110; the snapshot's Part 4 ends at 4.105."""
    finding = Finding("citation", CONTRADICTED,
                      "the draft key cites a provision that is not live in the current snapshot: "
                      "21 CFR 4.110", {"sections": [{"citation": "21 CFR 4.110", "exists": False}]})
    review = make_review(("X-004",), rows=[_row("X-004", "CONTRADICTED", [finding])])
    packet = review.packet("X-004")
    assert packet.automated_state == "CONTRADICTED"
    assert any("4.110" in r for r in packet.referral_reasons)
    assert any("Resolve the contradiction" in q for q in packet.open_questions)
    # it is not auto-corrected: the row is still open until a person decides
    assert review.state("X-004") == STATE_REQUIRES_SME


def test_x004_correction_preserves_both_the_original_and_the_disposition():
    review = make_review(("X-004",))
    review.decide("X-004", STATE_CORRECTED, "SME", "Part 4 ends at 4.105",
                  corrected_citation="21 CFR 4.100 through 4.105", judgments=judgments())
    review.sign_off("SME", "Director", "2026-09-03", "ISO")
    row = next(r for r in review.locked_key()["rows"] if r["question_id"] == "X-004")
    assert row["original_citation"] == "21 CFR 111.1"       # the fixture's draft
    assert row["accepted_citation"] == "21 CFR 4.100 through 4.105"
    assert row["was_corrected"] is True
    assert row["state"] == STATE_VERIFIED


def test_an_iso_conflict_is_presented_as_a_conflict_not_a_correction():
    finding = Finding("iso_clause", REQUIRES_SME,
                      "the draft key and the approved crosswalk disagree: the draft names 8.2.2 and "
                      "the crosswalk maps these sections to 4.2.5. Both clause numbers exist in the "
                      "standard, so the controlled copy of ISO 13485:2016 has to settle which "
                      "mapping is right", {"disputed": ["8.2.2"]})
    question = make_question(question_id="M-021", iso_clause_draft="8.2.2",
                             iso_clause_title="Complaint handling")
    review = make_review()
    review.benchmark = FakeBenchmark([question])
    review.verification = VerificationArtifact(
        benchmark_id="b", benchmark_key=review.benchmark.benchmark_key, workbook_sha256="a" * 64,
        workbook_path="w", generated_at="t", sources={}, rows=(_row("M-021", "AWAITING_SME", [finding]),))
    packet = review.packet("M-021")
    crosswalk = next(e for e in packet.evidence if e["kind"] == "iso_crosswalk")
    assert "NOT the ISO standard" in crosswalk["establishes"]
    assert "controlled copy of ISO 13485:2016 decides" in crosswalk["establishes"]
    assert any("controlled copy" in q for q in packet.open_questions)


def test_an_absence_claim_requires_an_explicit_decision():
    finding = Finding("negative_control", REQUIRES_SME,
                      "the key declares no such requirement-like thing, which is not a "
                      "section-existence claim", {})
    review = make_review(("NC-004",), rows=[_row("NC-004", "AWAITING_SME", [finding])])
    packet = review.packet("NC-004")
    evidence = next(e for e in packet.evidence if e["dimension"] == "negative_control")
    assert "says nothing about what the section requires" in evidence["establishes"]
    assert review.state("NC-004") == STATE_REQUIRES_SME


def test_substantive_and_completeness_judgments_are_recorded_on_the_row():
    review = make_review(("Q-1",))
    review.decide("Q-1", STATE_ACCEPTED, "SME", "checked",
                  judgments=[Judgment("substantive_elements", "correct", "provision says this"),
                             Judgment("completeness", "partially_correct", "one cross-ref missing")])
    values = review.latest("Q-1").judgment_values
    assert values == {"substantive_elements": "correct", "completeness": "partially_correct"}
    review.sign_off("SME", "Director", "2026-09-03", "ISO")
    row = review.locked_key()["rows"][0]
    assert row["judgments"]["completeness"] == "partially_correct"


def test_a_judgment_needs_a_rationale_and_a_known_value():
    with pytest.raises(ReviewError, match="needs a rationale"):
        Judgment("substantive_elements", "correct", "  ")
    with pytest.raises(ReviewError, match="judgment value"):
        Judgment("substantive_elements", "probably", "hmm")
    with pytest.raises(ReviewError, match="judgment dimension"):
        Judgment("vibes", "correct", "hmm")


# ------------------------------------------------------------ 3 sign-off


def test_signoff_refuses_while_any_row_is_open():
    review = make_review(("Q-1", "Q-2"))
    review.decide("Q-1", STATE_ACCEPTED, "SME", "fine", judgments=judgments())
    with pytest.raises(ReviewError, match="still unresolved"):
        review.sign_off("SME", "Director", "2026-09-03", "ISO")


def test_signoff_refuses_when_a_judgment_is_missing():
    review = make_review(("Q-1",))
    review.decide("Q-1", STATE_ACCEPTED, "SME", "fine")      # no judgments
    with pytest.raises(ReviewError, match="no substantive/completeness judgment"):
        review.sign_off("SME", "Director", "2026-09-03", "ISO")


def test_signoff_requires_the_reviewer_title_and_ecfr_date():
    review = make_review(("Q-1",))
    resolve_all(review)
    with pytest.raises(ReviewError, match="reviewer and their title"):
        review.sign_off("", "Director", "2026-09-03", "ISO")
    with pytest.raises(ReviewError, match="eCFR revision date"):
        review.sign_off("SME", "Director", "  ", "ISO")


def test_a_rejected_row_is_withdrawn_rather_than_scored():
    review = make_review(("Q-1", "Q-2"))
    review.decide("Q-1", STATE_ACCEPTED, "SME", "fine", judgments=judgments())
    review.decide("Q-2", STATE_REJECTED, "SME", "question is unusable")
    review.sign_off("SME", "Director", "2026-09-03", "ISO")
    locked = review.locked_key()
    assert locked["scoring_rows"] == 1
    assert locked["withdrawn_rows"] == ["Q-2"]


# ------------------------------------------------------ 14-17 the hard gates


def _lock(tmp_path, review, version=1):
    review.sign_off("SME", "Director", "2026-09-03", "ISO 13485:2016(E)")
    locked = review.locked_key()
    root = tmp_path / review.benchmark.benchmark_key.replace("@", "_") / "locked" / f"v{version}"
    write_locked_key(locked, root)
    return locked


def test_scoring_is_blocked_with_no_review_at_all(tmp_path):
    review = make_review()
    with pytest.raises(AcceptanceGateError, match="no locked key exists"):
        require_locked_key(review.benchmark.benchmark_key, "Scoring", tmp_path)


def test_training_is_blocked_with_no_review_at_all(tmp_path):
    review = make_review()
    with pytest.raises(AcceptanceGateError) as excinfo:
        require_locked_key(review.benchmark.benchmark_key, "Training", tmp_path)
    assert "Training is blocked" in str(excinfo.value)
    assert "invalidates the entire result" in str(excinfo.value)


def test_scoring_is_blocked_after_only_a_partial_review(tmp_path):
    review = make_review(("Q-1", "Q-2"))
    review.decide("Q-1", STATE_ACCEPTED, "SME", "fine", judgments=judgments())
    with pytest.raises(ReviewError):
        review.sign_off("SME", "Director", "2026-09-03", "ISO")   # cannot even lock
    with pytest.raises(AcceptanceGateError):
        require_locked_key(review.benchmark.benchmark_key, "Scoring", tmp_path)


def test_training_is_blocked_after_only_a_partial_review(tmp_path):
    review = make_review(("Q-1", "Q-2"))
    review.decide("Q-1", STATE_CORRECTED, "SME", "fixed", corrected_citation="21 CFR 1.1",
                  judgments=judgments())
    with pytest.raises(AcceptanceGateError):
        require_locked_key(review.benchmark.benchmark_key, "Training", tmp_path)


def test_a_locked_key_with_an_unverified_row_still_blocks(tmp_path):
    """A hand-made locked key cannot open the gate if a row is unverified."""
    root = tmp_path / "b_0" / "locked" / "v1"
    write_locked_key({
        "benchmark_key": "regulus_acceptance_rev02@aaaaaaaaaaaa",
        "review_version": 1, "signoff": {"reviewer": "SME"},
        "rows": [{"question_id": "Q-1", "state": "ACCEPTED", "in_scope_for_scoring": True},
                 {"question_id": "Q-2", "state": "NEEDS_RESEARCH", "in_scope_for_scoring": False}],
    }, root)
    status = gate_status("regulus_acceptance_rev02@aaaaaaaaaaaa", tmp_path)
    assert status["open"] is False
    assert "not verified" in status["reason"]


def test_a_locked_key_without_a_signoff_still_blocks(tmp_path):
    root = tmp_path / "b_0" / "locked" / "v1"
    write_locked_key({"benchmark_key": "b@0", "review_version": 1, "signoff": {}, "rows": []}, root)
    assert gate_status("b@0", tmp_path)["open"] is False


def test_scoring_and_training_unlock_only_once_the_key_is_locked(tmp_path):
    review = make_review(("Q-1", "Q-2"))
    resolve_all(review)
    _lock(tmp_path, review)
    for action in ("Scoring", "Training"):
        locked = require_locked_key(review.benchmark.benchmark_key, action, tmp_path)
        assert locked["scoring_rows"] == 2
    status = gate_status(review.benchmark.benchmark_key, tmp_path)
    assert status["open"] is True and status["reviewer"] == "SME"


def test_a_key_locked_for_another_benchmark_does_not_unlock_this_one(tmp_path):
    review = make_review()
    resolve_all(review)
    _lock(tmp_path, review)
    with pytest.raises(AcceptanceGateError, match="no locked key exists"):
        require_locked_key("regulus_acceptance_rev02@ffffffffffff", "Scoring", tmp_path)


# ------------------------------------------- 20 benchmark stays out of training


def test_a_benchmark_question_in_training_text_blocks_preparation():
    from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark

    workbook = Path("Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx")
    if not workbook.is_file():
        pytest.skip("workbook not present")
    benchmark = load_acceptance_benchmark(workbook)
    leaked = benchmark.questions[0].question
    with pytest.raises(AcceptanceGateError, match="must stay completely held out"):
        require_benchmark_not_in_training([f"prompt: {leaked}"], benchmark)
    # and clean training text passes
    require_benchmark_not_in_training(["an unrelated training example"], benchmark)


# ------------------------------------------------ 18 historical reproducibility


def test_a_review_rebuilds_exactly_from_its_append_only_record(tmp_path):
    review = make_review(("Q-1", "Q-2"))
    for decision in (
        review.decide("Q-1", STATE_NEEDS_RESEARCH, "SME", "parked"),
        review.decide("Q-1", STATE_ACCEPTED, "SME", "resolved", judgments=judgments()),
        review.decide("Q-2", STATE_CORRECTED, "SME", "fixed", corrected_citation="21 CFR 1.1",
                      judgments=judgments()),
    ):
        append_decision(decision, tmp_path)

    rebuilt = load_review(review.benchmark, review.verification, RUN_ID, tmp_path)
    assert [d.to_dict() for d in rebuilt.decisions] == [d.to_dict() for d in review.decisions]
    assert rebuilt.state("Q-1") == STATE_ACCEPTED
    assert rebuilt.state("Q-2") == STATE_CORRECTED
    assert rebuilt.latest("Q-2").corrected_citation == "21 CFR 1.1"


def test_a_second_review_version_does_not_disturb_the_first(tmp_path):
    first = make_review(("Q-1",))
    resolve_all(first)
    locked_v1 = _lock(tmp_path, first, version=1)

    second = make_review(("Q-1",))
    second.review_version = 2
    second.decide("Q-1", STATE_CORRECTED, "SME", "later correction",
                  corrected_citation="21 CFR 9.9", judgments=judgments())
    second.sign_off("SME", "Director", "2026-10-01", "ISO")
    locked_v2 = second.locked_key()
    root = tmp_path / second.benchmark.benchmark_key.replace("@", "_") / "locked" / "v2"
    write_locked_key(locked_v2, root)

    assert locked_v1["key_version_sha256"] != locked_v2["key_version_sha256"]
    # v1 on disk is untouched
    v1_path = tmp_path / first.benchmark.benchmark_key.replace("@", "_") / "locked" / "v1" / "locked_key.json"
    assert json.loads(v1_path.read_text(encoding="utf-8"))["key_version_sha256"] == locked_v1["key_version_sha256"]
    # and the gate takes the newest version
    assert locked_key_for(second.benchmark.benchmark_key, tmp_path)["review_version"] == 2


def test_the_summary_reports_what_still_needs_a_person():
    finding = Finding("iso_clause", REQUIRES_SME, "crosswalk disagreement", {})
    review = make_review(("Q-1", "Q-2"), rows=[_row("Q-1", "AWAITING_SME", [finding]), _row("Q-2")])
    summary = review.summary()
    assert summary["questions"] == 2
    assert summary["open_rows"] == 2
    assert summary["iso_conflicts"] == ["Q-1"]
    assert summary["signed_off"] is False
    assert summary["key_locked"] is False


# ------------------------------------------------ packet evidence for the SME


class TextSources:
    """A source that can also return provision text and part searches."""

    def __init__(self, text=None, hits=None):
        self._text = text or {}
        self._hits = hits or []

    def provision_text(self, section, paragraph_path=""):
        return self._text.get((section, paragraph_path), self._text.get((section, ""), []))

    def search_part(self, part, terms, limit=8):
        return self._hits


def test_a_packet_carries_the_provision_s_own_text():
    """Without it an SME cannot judge substance without leaving the tool."""
    from regulus.evaluation.key_review import gather_provision_text

    question = make_question(expected_citation_draft="21 CFR 111.1")
    sources = TextSources(text={("111.1", ""): [
        {"section": "111.1", "paragraph_path": "(a)", "heading": "Who is subject",
         "text": "you are subject to this part if you manufacture...", "effective_date": "2026-01-01"}]})
    blocks = gather_provision_text(question, sources)
    assert len(blocks) == 1
    assert blocks[0]["citation"] == "21 CFR 111.1"
    assert "US Government work" in blocks[0]["source"]
    assert blocks[0]["records"][0]["text"].startswith("you are subject")


def test_provision_text_is_absent_when_no_source_is_supplied():
    review = make_review(("Q-1",))
    packet = review.packet("Q-1")
    assert packet.provision_text == () and packet.absence_search == ()


def test_absence_evidence_is_gathered_only_for_negative_controls():
    from regulus.evaluation.key_review import gather_absence_search

    hits = [{"section": "211.100", "paragraph_path": "(a)", "snippet": "written procedures"}]
    ordinary = make_question(question="What does 21 CFR Part 211 require?")
    assert gather_absence_search(ordinary, TextSources(hits=hits)) == ()

    control = make_question(question_type="Negative Control",
                            question="Which section of 21 CFR Part 211 requires a Chief Quality "
                                     "Officer to personally sign every batch record?",
                            expected_citation_draft="NO SUCH REQUIREMENT")
    blocks = gather_absence_search(control, TextSources(hits=hits))
    assert len(blocks) == 1 and blocks[0]["part"] == "211"
    assert "chief" in blocks[0]["terms"]


def test_absence_evidence_never_claims_to_prove_the_absence():
    """An empty search is consistent with the claim; it does not establish it."""
    from regulus.evaluation.key_review import gather_absence_search

    control = make_question(question_type="Negative Control",
                            question="Which section of 21 CFR Part 211 requires a quarterly audit?",
                            expected_citation_draft="NO SUCH REQUIREMENT")
    block = gather_absence_search(control, TextSources(hits=[]))[0]
    assert block["hits"] == []
    assert "does not prove it" in block["reading"]
    assert "The reviewer decides" in block["reading"]


def test_the_packet_never_carries_iso_standard_text():
    """Clause numbers and titles may be identified; the standard's text may not
    be reproduced. Nothing in the packet pipeline returns ISO prose."""
    from regulus.evaluation.key_review import gather_provision_text

    question = make_question(iso_clause_draft="8.2.2", iso_clause_title="Complaint handling",
                             expected_citation_draft="21 CFR 820.35(a)")
    sources = TextSources(text={("820.35", "(a)"): [
        {"section": "820.35", "paragraph_path": "(a)", "heading": "Records",
         "text": "In addition to the requirements of...", "effective_date": None}]})
    blocks = gather_provision_text(question, sources)
    serialised = json.dumps(blocks)
    assert "820.35" in serialised
    assert "ISO 13485" not in serialised, "no ISO text may be reproduced"


def test_search_terms_skip_the_grammar_and_keep_the_subject():
    from regulus.evaluation.key_review import _search_terms

    question = make_question(question="Which section of 21 CFR Part 211 requires a Chief Quality "
                                      "Officer to personally sign every batch record?")
    terms = _search_terms(question)
    assert "chief" in terms and "quality" in terms
    for stop in ("which", "section", "part", "requires", "every", "cfr"):
        assert stop not in terms
