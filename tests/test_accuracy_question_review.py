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


def test_a_partially_correct_answer_fails_the_full_rubric():
    _, v = review(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1] This duty is restated in 21 CFR 820.777.")
    assert v["status"] == FAIL and v["substantive_correctness"]["state"] == R.PARTIAL
    assert v["explanation"].startswith("Partially correct")


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
