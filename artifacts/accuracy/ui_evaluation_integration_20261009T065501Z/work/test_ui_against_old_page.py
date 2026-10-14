"""The per-question evaluation shown with an answer in web/index.html, rendered
by the page's own <script> under Node against scripted /api/ask/stream responses.

The evaluation payloads are produced by the REAL evaluator and the real
per-question review (regulus.accuracy.review) in Python, then rendered by the
page; only the answer text and sources around them are the harness's own.

What these pin is the part a user could be misled by: PASS appears only for a
complete, consistent result that belongs to this question; a substantive pass
is not a PASS; an abstention, an evaluator error or a malformed payload reads
as NOT EVALUATED, never as a pass and never as a number; no accuracy
percentage is shown; the result is never presented as the acceptance-test
score; and the answer is shown whatever the evaluation block does.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess

import pytest

from regulus.accuracy import evaluate_safely
from regulus.accuracy.review import question_review
from regulus.config import PROJECT_ROOT
from tests.test_accuracy_evaluation import ONE, PURCHASING, assess

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
HARNESS = "/Users/sensussoftsoftware/Desktop/Prachi Patel/Regulus AI.nosync/artifacts/accuracy/ui_evaluation_integration_20261009T065501Z/work/harness_old_page.js"
TWO_MISSING = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.99(z) require?"


def page(scenario: str) -> dict:
    out = subprocess.run([NODE, HARNESS, scenario], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def shown(tmp_path, accuracy, *, question=ONE, result_question=None) -> dict:
    """Render a final result whose `accuracy` is `accuracy`, asked as `question`."""
    payload = {"page_question": question, "result": {"question": result_question or question, "accuracy": accuracy}}
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    out = subprocess.run([NODE, HARNESS, "file", str(path)], capture_output=True, text=True, timeout=30, check=True)
    r = json.loads(out.stdout)
    html = r["final_out"]
    # the evaluation block alone (the raw-JSON diagnostics panel further down echoes everything)
    r["block"] = html.split('<div class="acc">', 1)[1].split("<label>Citations</label>", 1)[0] if '<div class="acc">' in html else ""
    r["header"] = html.split('<div class="answer">', 1)[0]
    return r


def evaluated(question, answer):
    a, _ = assess(question, answer)
    d = a.to_dict()
    d["question_review"] = question_review(d, question=question)     # exactly what the server attaches
    return d


def correct():
    return evaluated(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]")


def assert_never_a_pass(r):
    assert "PASS" not in r["block"] and "evaluation: PASS" not in r["header"]
    assert not re.search(r"\d+\s*%", r["block"])


# ---------------------------------------------------- 1-3: evaluated answers


def test_an_evaluated_passing_answer_shows_pass_and_its_checks(tmp_path):
    r = shown(tmp_path, correct())
    assert r["answer_shown"]
    assert "evaluation: PASS" in r["header"] and ">PASS<" in r["block"]
    assert "Substantive correctness" in r["block"] and "Citation correctness" in r["block"]
    assert r["block"].count("Pass —") >= 2
    # what it is and what it is not, every time
    assert "No reference answer is used" in r["block"]
    assert "not the 300-question acceptance-test result" in r["block"]
    # no accuracy percentage; the check score only as a labelled detail
    assert not re.search(r"\d+\s*%", r["block"]) and "Answer Accuracy" not in r["final_out"]
    assert "Live check score 100/100" in r["block"] and "not an accuracy percentage" in r["block"]


def test_an_evaluated_failing_answer_shows_fail_and_says_why(tmp_path):
    r = shown(tmp_path, evaluated(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} Suppliers must be re-audited within 45 "
                                       "days of any nonconformance [1]."))
    assert r["answer_shown"]
    assert "evaluation: FAIL" in r["header"] and ">FAIL<" in r["block"]
    assert "Incorrect: figure(s) not found in any supplied source: 45" in r["block"]
    assert "✗" in r["block"]


def test_a_substantively_correct_but_incomplete_answer_fails_the_full_rubric(tmp_path):
    r = shown(tmp_path, evaluated(TWO_MISSING, f"21 CFR 820.10(b)(2): {PURCHASING} [1]\nNot found in the available "
                                               "eCFR data: 21 CFR 820.99(z). The answer above covers only the "
                                               "provisions that were retrieved."), question=TWO_MISSING)
    assert "evaluation: FAIL" in r["header"] and ">FAIL<" in r["block"]
    assert "Substantive correctness</td>" in r["block"] and "Pass —" in r["block"]     # shown, but not as a PASS
    assert "Completeness partial" in r["block"]
    assert ">PASS<" not in r["block"]


def test_a_partially_correct_answer_fails(tmp_path):
    r = shown(tmp_path, evaluated(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1] This duty is restated in 21 CFR 820.777."))
    assert ">FAIL<" in r["block"] and "Partial —" in r["block"] and "Partially correct" in r["block"]


# ---------------------------------------------------- 4: no evaluation result


def test_without_evaluation_the_page_is_the_page_it_was():
    off = page("normal")
    assert off["answer_shown"] and '<div class="acc">' not in off["final_out"]
    assert "evaluation:" not in off["final_out"] and "PASS" not in off["final_out"]
    assert '<div class="answer">Validated answer [1].</div>' in off["final_out"]


def test_an_abstaining_evaluator_reads_as_not_evaluated_never_as_zero(tmp_path):
    r = shown(tmp_path, evaluated(ONE, "21 CFR 820.10(b)(2) obliges a maker to check bought-in goods [1]."))
    assert r["answer_shown"]
    assert "evaluation: NOT EVALUATED" in r["header"] and ">NOT EVALUATED<" in r["block"]
    assert "Cannot be verified" in r["block"]
    assert_never_a_pass(r)
    assert "Live check score" not in r["block"]


# ---------------------------------------------------- 5: missing or incomplete metadata


@pytest.mark.parametrize("damage", ["null", "no_review", "review_not_object", "unknown_status",
                                    "pass_without_substantive", "pass_but_not_evaluated", "pass_with_failed_citation"])
def test_missing_or_inconsistent_metadata_is_never_shown_as_pass(tmp_path, damage):
    a = copy.deepcopy(correct())
    if damage == "null":
        a = None
    elif damage == "no_review":
        del a["question_review"]
    elif damage == "review_not_object":
        a["question_review"] = "PASS"
    elif damage == "unknown_status":
        a["question_review"]["status"] = "great"
    elif damage == "pass_without_substantive":
        a["question_review"]["substantive_correctness"] = None
    elif damage == "pass_but_not_evaluated":
        a["status"] = "evaluator_error"
    elif damage == "pass_with_failed_citation":
        a["question_review"]["citation_correctness"]["state"] = "fail"
    r = shown(tmp_path, a)
    assert r["answer_shown"]
    assert ">NOT EVALUATED<" in r["block"] and "evaluation: NOT EVALUATED" in r["header"]
    assert_never_a_pass(r)


def test_a_label_the_page_does_not_recognise_is_not_displayed(tmp_path):
    a = copy.deepcopy(correct())
    a["question_review"]["status"], a["question_review"]["label"] = "fail", "PASS"
    r = shown(tmp_path, a)
    assert ">FAIL<" in r["block"] and "PASS" not in r["block"]


# ---------------------------------------------------- 6: an evaluator error


def test_an_evaluator_error_is_not_evaluated_and_the_answer_is_shown(tmp_path):
    class Broken:
        @property
        def sources(self):
            raise RuntimeError("boom")

    d = evaluate_safely(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]", package=Broken()).to_dict()
    d["question_review"] = question_review(d, question=ONE)
    r = shown(tmp_path, d)
    assert r["answer_shown"]
    assert ">NOT EVALUATED<" in r["block"] and "evaluator failed" in r["block"]
    assert_never_a_pass(r)


# ---------------------------------------------------- 7: this question's own result


def test_a_result_for_another_question_is_not_shown_as_this_ones(tmp_path):
    # the server answered (and evaluated) a different question than the one this page asked
    r = shown(tmp_path, correct(), question="What does 21 CFR 820.30(a) require?", result_question=ONE)
    assert ">NOT EVALUATED<" in r["block"] and "not for this question" in r["block"]
    assert_never_a_pass(r)


def test_an_evaluation_of_another_question_attached_to_this_answer_is_not_shown(tmp_path):
    a = correct()
    a["question_review"]["question"] = "What does 21 CFR 820.30(a) require?"
    r = shown(tmp_path, a)
    assert ">NOT EVALUATED<" in r["block"] and "not for this question" in r["block"]
    assert_never_a_pass(r)


def test_each_question_shows_its_own_result(tmp_path):
    q2 = TWO_MISSING
    first = shown(tmp_path, correct())
    second = shown(tmp_path, evaluated(q2, f"21 CFR 820.10(b)(2): {PURCHASING} [1]\nNot found in the available "
                                           "eCFR data: 21 CFR 820.99(z). The answer above covers only the "
                                           "provisions that were retrieved."), question=q2)
    assert ">PASS<" in first["block"] and ">FAIL<" in second["block"]
    assert "820.99(z)" in second["block"] and "820.99(z)" not in first["block"]
