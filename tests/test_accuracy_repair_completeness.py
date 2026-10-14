"""Completeness after repair: what post-processing removed, the evaluator must be able to see.

Repair (`RagPipeline.repair_answer`) removes a statement validation flagged - one carrying a condition no
supplied source contains (`invented_conditions_removed`), or one cited to the wrong source - and the evaluator
only ever assessed what was left. On 21 CFR 211.192 (one paragraph, four obligations, one completeness unit) a
broad answer whose S2 carried an invented "unless" lost the whole investigation duty with it and still scored
PASS 100: the three remaining sentences "covered" the paragraph.

Pinned: when a removed statement carried text of a requested provision that the delivered answer no longer
states, completeness is NOT ESTABLISHED (never a failure: a repair is not proof of an omission); a repair that
removed only fabricated text, or content the answer still states, changes nothing; and supplying the repair
record can only ever withdraw a PASS, never grant one.
"""

from __future__ import annotations

import pytest

from regulus.accuracy import evaluate_safely
from regulus.accuracy.alignment import LexicalAligner
from regulus.accuracy.review import FAIL, NOT_EVALUATED, PASS, question_review
from regulus.rag import RagConfig, RagPipeline
from regulus.retrieval import LexicalRetriever
from tests.test_accuracy_pass_integrity import completeness, production
from tests.test_accuracy_window_support import BROAD, FOCUSED, S1, S2, S3, S4, T211
from tests.test_answer_validation import TWO, ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, guidance_row

INVENTED = ", unless the batch was destroyed"


def with_invented(sentence: str) -> str:
    return sentence[:-1] + INVENTED + "."


def assess(out, *, repair: bool):
    d = evaluate_safely(out.question, out.answer, package=out.package, evidence=out.evidence_snapshot,
                        citations=out.citations, validation=out.validation, coverage=out.coverage,
                        model_called=out.model_called, fallback_type=out.metadata.get("fallback_type"),
                        answerability=out.metadata.get("answerability"),
                        repair=out.metadata.get("validation") if repair else None, aligner=LexicalAligner()).to_dict()
    return question_review(d, question=out.question), d


RANK = {PASS: 2, NOT_EVALUATED: 1, FAIL: 0}


# ------------------------------------------------------------- the defect: removed, nothing restored

@pytest.mark.parametrize("which", [0, 1, 3])
def test_a_removed_statement_takes_an_obligation_and_completeness_is_not_established(which):
    sentences = [S1, S2, S3, S4]
    lost = sentences[which]
    sentences[which] = with_invented(lost)
    v, d, out = production(BROAD, " ".join(f"{s} [1]" for s in sentences), T211)
    assert out.metadata["validation"]["repair"] == "invented_conditions_removed"
    assert lost[:-1] not in out.answer                          # the obligation is gone from what was delivered
    assert out.validation.ok and not out.validation.unaddressed  # and the pipeline's own check cannot see it
    assert completeness(d)["state"] == "not_established" and "21 CFR 211.192" in completeness(d)["detail"]
    assert v["status"] == NOT_EVALUATED                          # not PASS - and not a failure either


# ------------------------------------------------------------- a repair is not an omission

def test_removing_a_wholly_fabricated_statement_changes_nothing():
    v, d, out = production(BROAD, f"{S1} [1] {S2} [1] {S3} [1] {S4} [1] Records are exempt unless the batch was destroyed. [1]",
                           T211)
    assert out.metadata["validation"]["repair"] == "invented_conditions_removed"
    assert v["status"] == PASS and v["live_check_score"] == 100


def test_a_removed_statement_whose_content_the_answer_still_states_changes_nothing():
    v, d, out = production(BROAD, f"{S1} [1] {with_invented(S2)} [1] {S2} [1] {S3} [1] {S4} [1]", T211)
    assert out.metadata["validation"]["repair"] == "invented_conditions_removed"
    assert v["status"] == PASS and v["live_check_score"] == 100


def test_a_replaced_mismatched_statement_keeps_its_completeness():
    """The mismatch repair puts the provision's verbatim text in place of the statement it removes."""
    fake = "21 CFR 820.10(b)(2): traceability procedures. [1]\n\n21 CFR 820.10(b)(4): a UDI system for every device. [4]"
    out = RagPipeline(LexicalRetriever(TableDatabase(guidance=[guidance_row(0, rank=0.4)])), ScriptedGenerator(fake),
                      RagConfig(optional_context="always")).answer(TWO)
    assert out.metadata["validation"]["repair"] == "mismatched_statements_replaced"
    (with_repair, d1), (without, d0) = assess(out, repair=True), assess(out, repair=False)
    assert completeness(d1) == completeness(d0)
    assert with_repair["status"] == without["status"]


# ------------------------------------------------------------- unchanged outcomes

def test_the_complete_answer_still_passes():
    v, _, out = production(BROAD, f"{S1} [1] {S2} [1] {S3} [1] {S4} [1]", T211)
    assert out.metadata["validation"]["repair"] is None
    assert v["status"] == PASS and v["live_check_score"] == 100


@pytest.mark.parametrize("question, draft", [
    (BROAD, f"{S1} [1] {with_invented(S2)} [1] {S3} [1] {S4} [1]"),
    (BROAD, f"{S1} [1] {S2} [1] {S3} [1] {S4} [1] Records are exempt unless the batch was destroyed. [1]"),
    (BROAD, f"{S2} {S3} {S4} [1]"),
    (FOCUSED, f"{with_invented(S2)} [1]"),
    (FOCUSED, "Any failure of a batch must be investigated within 30 days. [1]"),
    ("What must the written record of an investigation under 21 CFR 211.192 include?", f"{S1} [1]"),
])
def test_the_repair_record_never_raises_an_outcome(question, draft):
    v, _, out = production(question, draft, T211)
    without, _ = assess(out, repair=False)
    with_repair, _ = assess(out, repair=True)
    assert RANK[with_repair["status"]] <= RANK[without["status"]]
    assert with_repair["status"] == v["status"]                 # production() passes the record, as serve_ui does
