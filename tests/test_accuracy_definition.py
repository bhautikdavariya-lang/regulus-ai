"""A definitional answer is decided by the CFR's own definition, and by nothing looser.

"The FDA stands for the Food and Drug Administration [1]" against 21 CFR 10.3(a)
"FDA means the Food and Drug Administration." was NOT EVALUATED (measured live,
2026-10-09): the paraphrase ladder needs two agreeing operators and a
definition has none, the descriptive standard needs a 6-word verbatim run a
short definition cannot reach, and the question's topic was read as "stand"
(its frame) instead of "FDA" (its term). The fix decides it by identity - the
passage defines the same term, and the answer's definiens is that definiens
word for word - and reads a definitional question as being about its term.

Evidence: VERBATIM snapshot paragraphs (tests/fixtures/accuracy_definition_citation_rows.json).
Answers: CONSTRUCTED, except the first, which is the live answer captured on 2026-10-09.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy.claims import classify
from regulus.accuracy.intent import analyze
from regulus.accuracy.review import FAIL, NOT_EVALUATED, PASS, question_review
from tests.test_accuracy_claim_extraction import judge

TEXT = {p["citation"]: p["text"] for p in json.loads(
    (Path(__file__).parent / "fixtures" / "accuracy_definition_citation_rows.json").read_text(encoding="utf-8"))["paragraphs"]}
Q = "What does FDA stand for?"
SOURCES = [("21 CFR 10.3(a)", TEXT["21 CFR 10.3(a)"]), ("21 CFR 203.3(n)", TEXT["21 CFR 203.3(n)"]),
           ("21 CFR 114.3(c)", TEXT["21 CFR 114.3(c)"])]


def status(answer, question=Q, sources=SOURCES):
    a = judge(question, answer, sources)
    d = a.to_dict()
    return question_review(d, question=question), d


def test_the_live_answer_is_a_verified_pass():
    v, d = status("The FDA stands for the Food and Drug Administration. [1]")
    assert (v["status"], v["live_check_score"]) == (PASS, 100)
    (claim,) = d["checked"]["claims"]
    assert claim["support_basis"] == "definition" and claim["final"] == AN.SUPPORTED
    assert claim["operator_trace"]["evidence_citation"] == "21 CFR 10.3(a)"


def test_each_definition_supports_only_its_own_wording():
    # 203.3(n) says "the U.S. Food and Drug Administration": credited by IT, not by 10.3(a)
    v, d = status("FDA means the U.S. Food and Drug Administration [2].")
    assert v["status"] == PASS and d["checked"]["claims"][0]["operator_trace"]["evidence_citation"] == "21 CFR 203.3(n)"
    v, _ = status("FDA means the U.S. Food and Drug Administration [1].")     # cites 10.3(a), which does not say "U.S."
    assert v["status"] == FAIL and v["citation_correctness"]["state"] == "fail"


@pytest.mark.parametrize("answer", [
    "The FDA stands for the Federal Drug Agency. [1]",                         # a wrong expansion
    "The FDA stands for the Food and Drug Agency. [1]",                        # plausible, one word wrong
    "The FDA stands for Food and Drug. [1]",                                   # partial
])
def test_a_wrong_or_partial_expansion_never_passes(answer):
    v, d = status(answer)
    assert v["status"] != PASS
    assert not any(c["support_basis"] == "definition" for c in d["checked"]["claims"])


def test_a_correct_definition_with_a_wrong_citation_fails_on_citation():
    v, _ = status("The FDA stands for the Food and Drug Administration. [3]")  # 114.3(c) defines "lot"
    assert v["status"] == FAIL and v["substantive_correctness"]["state"] == "pass"
    assert v["citation_correctness"]["state"] == "fail"


def test_a_correct_definition_without_a_citation_does_not_pass():
    v, _ = status("FDA stands for the Food and Drug Administration.")
    assert v["status"] != PASS


def test_an_unsupported_statement_beside_a_correct_definition_does_not_pass():
    v, d = status("The FDA stands for the Food and Drug Administration. It regulates all food sold worldwide. [1]")
    assert v["status"] != PASS
    assert any(c["final"] == AN.UNVERIFIABLE for c in d["checked"]["claims"])


def test_another_term_is_decided_the_same_way():
    v, _ = status("Lot means the product produced during a period indicated by a specific code [3].", question="What does lot mean?")
    assert v["status"] == PASS
    v, _ = status("A lot is any amount of product made on one day [3].", question="What does lot mean?")
    assert v["status"] != PASS


# ---------------------------------------------------- the reading of the question


def test_a_definitional_question_is_about_its_term():
    i = analyze("What does FDA stand for?")
    assert i.topic == ("fda",) and "definition_term" in i.signals and [e.label for e in i.elements] == ["the term FDA"]


def test_other_questions_are_read_as_before():
    i = analyze("What does FDA require for labeling?")
    assert "definition_term" not in i.signals and "fda" not in i.topic


# ---------------------------------------------------- short sentences are claims unless they are headings


@pytest.mark.parametrize("sentence", ["It regulates all food sold worldwide.", "FDA stands for the Federal Drug Agency.",
                                      "They oversee every recall of imported food."])
def test_a_short_sentence_with_a_subject_or_a_definitional_verb_is_a_claim(sentence):
    assert classify(sentence).is_claim


@pytest.mark.parametrize("sentence", ["Postmarketing reporting of adverse experiences [10].", "Purchasing controls."])
def test_a_verbless_label_is_still_a_heading(sentence):
    assert classify(sentence).origin == "heading_fragment"
