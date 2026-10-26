"""The per-question evaluation status (regulus.accuracy.review) and how the
server attaches it to an answer (scripts/serve_ui.py).

Every assessment below is produced by the real evaluator on the in-memory
regulation table of tests/test_accuracy_evaluation.py, or by the real Stage 1-7
pipeline with a scripted generator (tests/test_accuracy_observer.py). No model
and no database are used. What is pinned is the part a reader could be misled
by: PASS only when every check passed, never for a substantive pass alone,
never for an abstention, an evaluator error or incomplete metadata, and never
for another question's result.
"""

from __future__ import annotations

import copy
import importlib.util

import pytest

from regulus.accuracy import evaluate_safely
from regulus.accuracy import rubric as R
from regulus.accuracy.alignment import LexicalAligner
from regulus.accuracy.review import BASIS, FAIL, NOT_EVALUATED, NOT_FULLY_EVALUATED, PASS, question_review
from regulus.config import PROJECT_ROOT
from tests.test_accuracy_evaluation import ONE, PURCHASING, assess

TWO_MISSING = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.99(z) require?"


def review(question, answer):
    a, _ = assess(question, answer)
    d = a.to_dict()
    return d, question_review(d, question=question)


def passing():
    return review(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]")


# ---------------------------------------------------- evaluated answers


def test_a_correct_verbatim_answer_passes_with_every_check_shown():
    d, v = passing()
    assert d["status"] == R.EVALUATED and d["answer_verdict"]["verdict"] == "correct"
    assert (v["status"], v["label"]) == (PASS, "PASS")
    assert v["substantive_correctness"]["state"] == R.PASS and v["citation_correctness"]["state"] == R.PASS
    assert v["question"] == ONE and v["rubric_id"] == R.RUBRIC_ID and v["basis"] == BASIS


def test_an_incorrect_answer_fails_and_says_why():
    _, v = review(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} Suppliers must be re-audited within 45 days of any "
                       "nonconformance [1].")
    assert v["status"] == FAIL and v["substantive_correctness"]["state"] == R.FAIL
    assert v["explanation"].startswith("Incorrect") and "45" in v["explanation"]


def test_substantive_correctness_alone_is_not_a_pass():
    """Correct as far as it goes, but a requested provision is missing: FAIL, with the reason named."""
    d, v = review(TWO_MISSING, f"21 CFR 820.10(b)(2): {PURCHASING} [1]\nNot found in the available eCFR data: "
                               "21 CFR 820.99(z). The answer above covers only the provisions that were retrieved.")
    assert d["answer_verdict"]["verdict"] == "correct"            # the evaluator's own verdict
    assert v["substantive_correctness"]["state"] == R.PASS
    assert v["status"] == FAIL
    assert v["explanation"].startswith("Completeness partial") and "820.99(z)" in v["explanation"]


def test_an_answer_naming_a_provision_nothing_vouches_for_is_never_a_pass():
    """Calibrated rule (23 Oct 2026): without an identifier index the evaluator cannot tell that 21 CFR 820.777 does
    not exist, so the answer is not fully evaluated - never PASS - and the explanation names what was not decided."""
    _, v = review(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1] This duty is restated in 21 CFR 820.777.")
    assert (v["status"], v["label"]) == (NOT_EVALUATED, NOT_FULLY_EVALUATED)
    assert v["substantive_correctness"]["state"] == R.PARTIAL and "820.777" in v["explanation"]


def test_a_section_verified_absent_from_the_snapshot_fails():
    class Index:
        def section_status(self, section):
            return (False, False)      # verified absent in the snapshot

    a, _ = assess(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1] This duty is restated in 21 CFR 820.777.", identifier_index=Index())
    v = question_review(a.to_dict(), question=ONE)
    assert v["status"] == FAIL and "820.777" in v["explanation"]


def _with(d, **states):
    d = copy.deepcopy(d)
    for x in d["dimensions"]:
        if x["dimension"] in states:
            x["state"], x["detail"], x["evidence"] = states[x["dimension"]]
    return d


def _claims(d, finals):
    d = copy.deepcopy(d)
    base = d["checked"]["claims"][0]
    d["checked"]["claims"] = [{**base, "final": f, "relevance": {**base["relevance"], "verdict": "relevant"}} for f in finals]
    return d


def test_uncertainty_is_not_a_failure_a_mostly_verified_answer_passes():
    """A correct paraphrase the aligner cannot fully verify: three statements matched to evidence, one unverifiable.
    The strict rule called such answers FAIL (35 of 37 blind-PASS holdout answers, 22 Oct)."""
    d, _ = passing()
    d = _claims(_with(d, substantive_correctness=(R.PARTIAL, "1 statement(s) could not be verified", []),
                      evidence_support=(R.NOT_ESTABLISHED, "1 of 4 statement(s) that answer the question could not be checked", [])),
                ["supported", "supported", "supported", "unverifiable"])
    v = question_review(d, question=ONE)
    assert v["status"] == PASS and "3 of 4" in v["explanation"] and "1 could not be checked" in v["explanation"]


def test_too_little_verified_is_not_fully_evaluated_never_a_pass():
    d, _ = passing()
    d = _claims(_with(d, evidence_support=(R.NOT_ESTABLISHED, "2 of 3 statement(s) that answer the question could not be checked", [])),
                ["supported", "unverifiable", "unverifiable"])
    v = question_review(d, question=ONE)
    assert (v["status"], v["label"]) == (NOT_EVALUATED, NOT_FULLY_EVALUATED) and "only 1 of 3" in v["explanation"]


def test_a_contradicted_statement_still_fails():
    d, _ = passing()
    d = _with(d, substantive_correctness=(R.FAIL, "1 statement(s) that address the question are contradicted by the evidence", []))
    assert question_review(d, question=ONE)["status"] == FAIL


def test_the_question_subject_alone_is_neither_a_failure_nor_a_pass():
    """'The answer does not address the question's subject' failed 14 blind-PASS holdout answers (noise there), and it
    is also the mark of an answer built on the wrong section (G5 held-out answers): never FAIL on its own, never PASS.
    A named element or a requested provision left out still fails."""
    d, _ = passing()
    subject = _with(d, completeness=(R.FAIL, "the answer does not address: the question's subject", ["the question's subject"]))
    assert (question_review(subject, question=ONE)["status"], question_review(subject, question=ONE)["label"]) == \
        (NOT_EVALUATED, NOT_FULLY_EVALUATED)
    named = _with(d, completeness=(R.FAIL, "the answer does not address: how long", ["how long"]))
    assert question_review(named, question=ONE)["status"] == FAIL


def test_a_decline_is_never_shown_as_a_pass():
    """A decline the retrieved evidence bears out may still be wrong: the evidence can lack the provision that answers
    it (FDCA612-Q2, holdout 22 Oct). Blind scoring fails every decline."""
    d, _ = passing()
    d = copy.deepcopy(d)
    d["answer_verdict"] = {**(d.get("answer_verdict") or {}), "verdict": "abstention_correct"}
    v = question_review(d, question=ONE)
    assert (v["status"], v["label"]) == (NOT_EVALUATED, NOT_FULLY_EVALUATED) and "declined" in v["explanation"]


def test_a_verbatim_fallback_is_never_a_pass():
    d, _ = passing()
    d = copy.deepcopy(d)
    d["checked"]["excluded_sentences"] = [{"origin": "pipeline_sentence",
                                           "text": "The generated answer could not be validated against the retrieved regulatory evidence."}]
    v = question_review(d, question=ONE)
    assert (v["status"], v["label"]) == (NOT_EVALUATED, NOT_FULLY_EVALUATED) and "verbatim" in v["explanation"]


def test_the_strict_rule_is_one_switch_away(monkeypatch):
    from regulus.accuracy import review as RV
    d, _ = passing()
    d = _claims(_with(d, substantive_correctness=(R.PARTIAL, "1 statement(s) could not be verified", [])),
                ["supported", "supported", "supported", "unverifiable"])
    monkeypatch.setattr(RV, "RULE", "strict")
    assert RV.question_review(d, question=ONE)["status"] == FAIL


# ---------------------------------------------------- no legitimate result: never PASS


def test_an_abstention_of_the_evaluator_is_not_evaluated():
    d, v = review(ONE, "21 CFR 820.10(b)(2) obliges a maker to check bought-in goods [1].")
    assert d["status"] == R.UNABLE
    assert (v["status"], v["label"]) == (NOT_EVALUATED, "NOT EVALUATED")
    assert v["live_check_score"] is None


def test_an_evaluator_error_is_not_evaluated_and_never_a_pass():
    class Broken:
        @property
        def sources(self):
            raise RuntimeError("boom")

    d = evaluate_safely(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]", package=Broken()).to_dict()
    assert d["status"] == R.ERROR
    v = question_review(d, question=ONE)
    assert v["status"] == NOT_EVALUATED and "evaluator failed" in v["explanation"]


@pytest.mark.parametrize("damage", ["none", "empty", "status", "dimension", "verdict", "score", "state"])
def test_missing_or_incomplete_metadata_is_not_evaluated(damage):
    d, _ = passing()
    d = copy.deepcopy(d)
    if damage == "none":
        d = None
    elif damage == "empty":
        d = {}
    elif damage == "status":
        d["status"] = "something_else"
    elif damage == "dimension":
        d["dimensions"] = [x for x in d["dimensions"] if x["dimension"] != R.CITATION]
    elif damage == "verdict":
        d["answer_verdict"] = None
    elif damage == "score":
        d["accuracy"] = None
    elif damage == "state":
        d["dimensions"][0]["state"] = "great"
    v = question_review(d, question=ONE)
    assert v["status"] == NOT_EVALUATED and v["label"] == "NOT EVALUATED"


def test_an_undecided_check_makes_it_not_fully_evaluated_never_a_pass():
    d, _ = passing()
    d = copy.deepcopy(d)
    next(x for x in d["dimensions"] if x["dimension"] == R.EVIDENCE_SUPPORT)["state"] = R.NOT_ESTABLISHED
    v = question_review(d, question=ONE)
    assert (v["status"], v["label"]) == (NOT_EVALUATED, NOT_FULLY_EVALUATED)
    assert "Evidence support" in v["explanation"]


def test_another_questions_result_is_not_shown():
    d, _ = passing()
    v = question_review(d, question="What does 21 CFR 820.30(a) require?")
    assert v["status"] == NOT_EVALUATED and "does not belong to this question" in v["explanation"]


def test_reading_an_assessment_does_not_change_it():
    d, _ = passing()
    before = copy.deepcopy(d)
    question_review(d, question=ONE)
    assert d == before


# ---------------------------------------------------- the server attaches it inside the assessment


def _engine():
    spec = importlib.util.spec_from_file_location("serve_ui_for_test", PROJECT_ROOT / "scripts" / "serve_ui.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    engine = object.__new__(mod.Engine)          # no model, no database: only the assessment path is used
    engine.identifier_index = lambda: None
    engine.aligner = lambda: LexicalAligner()
    return engine


def test_the_server_adds_only_the_review_and_only_inside_the_assessment():
    from tests.test_accuracy_observer import answer_one

    engine = _engine()
    for question, response in [(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]"),
                               (ONE, "21 CFR 820.10(b)(2) obliges a maker to check bought-in goods [1]."),
                               ("What is the capital of France?", "Paris is the capital of France.")]:
        out = answer_one(question, response)
        plain = engine.assess(out).to_dict()
        payload = engine.accuracy_payload(out)
        review_ = payload.pop("question_review")
        plain.pop("elapsed_ms"), payload.pop("elapsed_ms")
        assert payload == plain                                      # the evaluator's dict, unchanged
        assert review_["question"] == out.question
        assert review_ == question_review(plain, question=out.question)


# ---------------------------------------------------- the evaluation score passed to the page


def test_the_score_passed_on_is_the_evaluators_own_0_to_100_number():
    d, v = passing()
    assert d["accuracy"] == 100 and v["live_check_score"] == 100
    d, v = review(TWO_MISSING, f"21 CFR 820.10(b)(2): {PURCHASING} [1]\nNot found in the available eCFR data: "
                               "21 CFR 820.99(z). The answer above covers only the provisions that were retrieved.")
    assert d["accuracy"] == R.score({x["dimension"]: x["state"] for x in d["dimensions"]}) == 90
    assert (v["status"], v["live_check_score"]) == (FAIL, 90)          # a high score under FAIL
    d, v = review(ONE, "21 CFR 820.10(b)(2) obliges a maker to check bought-in goods [1].")
    assert d["accuracy"] is None and v["live_check_score"] is None   # no score is issued, none is made up


@pytest.mark.parametrize("bad", [150, -1, True])
def test_an_out_of_scale_score_is_not_passed_on_and_the_status_is_unchanged(bad):
    d, ok = passing()
    d = copy.deepcopy(d)
    d["accuracy"] = bad
    v = question_review(d, question=ONE)
    assert v["live_check_score"] is None
    assert (v["status"], v["label"]) == (ok["status"], ok["label"])


def test_an_answer_quoting_the_provision_is_never_pass_or_fail():
    from regulus.accuracy import review as RV
    for fb in RV.QUOTED_FALLBACKS:
        from regulus.accuracy import rubric as R
        assessment = {"status": R.EVALUATED, "accuracy": 10, "answer_verdict": {"verdict": "off_topic"},
                      "checked": {"fallback_type": fb, "claims": []},
                      "dimensions": [{"dimension": d, "state": R.FAIL, "detail": "x"} for d in R.DIMENSIONS]}
        got = RV.question_review(assessment, question="q")
        assert got["status"] == RV.NOT_EVALUATED and got["label"] == RV.NOT_FULLY_EVALUATED
