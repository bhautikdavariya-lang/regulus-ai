"""A citation marker is renumbered only to the one source that states its words verbatim.

Measured live on 2026-10-09: the model cited by PARAGRAPH number rather than by
SOURCE number ("the nature and details of the complaint [5]" for 21 CFR
820.35(a)(5), which is SOURCE 7), or put one marker after three quoted
paragraphs so the 211.25(c) sentence carried 211.25(a)'s number. The evaluator
correctly failed citation correctness on every one. The repair is identity
only: the text a marker is attached to must be stated verbatim by exactly one
supplied source and by none of the cited ones.

Source texts: VERBATIM snapshot paragraphs (tests/fixtures/accuracy_definition_citation_rows.json).
Answers: the three live shapes reproduced, and CONSTRUCTED negatives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.rag.citation_repair import MIN_WORDS, repoint_citations

TEXT = {p["citation"]: p["text"] for p in json.loads(
    (Path(__file__).parent / "fixtures" / "accuracy_definition_citation_rows.json").read_text(encoding="utf-8"))["paragraphs"]}


def sources(*citations):
    return [(i, TEXT[c]) for i, c in enumerate(citations, start=1)]


def body(citation):
    """A paragraph's text without its own label, as an answer quotes it."""
    t = TEXT[citation]
    return t.split(") ", 1)[1] if t.startswith("(") else t


S211 = sources("21 CFR 211.25(a)", "21 CFR 211.25(b)", "21 CFR 211.25(c)")
S820 = sources("21 CFR 820.35", "21 CFR 820.35(a)", "21 CFR 820.35(a)(1)", "21 CFR 820.35(a)(2)", "21 CFR 820.35(a)(3)",
               "21 CFR 820.35(a)(4)", "21 CFR 820.35(a)(5)", "21 CFR 820.35(a)(6)", "21 CFR 820.35(a)(7)", "21 CFR 820.35(b)",
               "21 CFR 820.35(b)(1)", "21 CFR 820.35(b)(2)", "21 CFR 820.35(b)(3)")
S314 = sources("21 CFR 314.50", "21 CFR 314.50(a)(1)", "21 CFR 314.50(a)(2)", "21 CFR 314.50(a)(3)")


# ---------------------------------------------------- the three live shapes


def test_one_trailing_marker_moves_to_the_paragraph_its_sentence_quotes():
    answer = f"{TEXT['21 CFR 211.25(a)'][4:]}\n\n{body('21 CFR 211.25(b)')}\n\n{body('21 CFR 211.25(c)')} [1]"
    new, changes = repoint_citations(answer, S211)
    assert new.endswith("each drug product. [3]") and [(c.old, c.new) for c in changes] == [((1,), 3)]
    assert new.replace("[3]", "[1]") == answer                        # nothing but the number changed


def test_paragraph_numbers_used_as_source_numbers_are_corrected():
    answer = ("21 CFR 820.35 adds the date the complaint was received [4], the nature and details of the complaint [5], "
              "any correction or corrective action taken [7], and any reply to the complainant [8].")
    new, changes = repoint_citations(answer, S820)
    assert [(c.old, c.new) for c in changes] == [((5,), 7), ((7,), 8), ((8,), 9)]
    assert "received [4]" in new                                      # already right: left alone
    assert "the complaint [7]" in new and "action taken [8]" in new and "complainant [9]" in new


def test_list_items_carrying_the_lead_ins_number_are_corrected():
    answer = (f"Under 21 CFR 314.50, an NDA must contain the following information:\n"
              f"- {body('21 CFR 314.50(a)(2)')} [1]\n- {body('21 CFR 314.50(a)(3)')} [1]")
    new, changes = repoint_citations(answer, S314)
    assert [(c.old, c.new) for c in changes] == [((1,), 3), ((1,), 4)]


# ---------------------------------------------------- when nothing may change


@pytest.mark.parametrize("answer", [
    # the cited source states it
    "21 CFR 820.35 adds the nature and details of the complaint [7].",
    # a paraphrase: no source states it verbatim
    "Records must capture what the complainant said about the device failure [5].",
    # stated by two sources ((a)(1) and (b)(1)): not decidable by identity
    "21 CFR 820.35 adds the name of the device [11].",
    # a marker naming a source that does not exist is validation's finding
    "21 CFR 820.35 adds the nature and details of the complaint [99].",
    # fewer than MIN_WORDS words attached to the marker
    "It adds the UDI [3].",
    # a coincidental verbatim tail under a long sentence of the model's own
    "Manufacturers that receive any oral or written report about devices in distribution should always record "
    "the nature and details of the complaint [5].",
    # no markers at all
    "21 CFR 820.35 adds the nature and details of the complaint.",
])
def test_anything_short_of_identity_is_left_for_validation_and_the_evaluator(answer):
    new, changes = repoint_citations(answer, S820)
    assert new == answer and changes == []


def test_a_single_source_is_never_renumbered():
    answer = f"{body('21 CFR 211.25(c)')} [1]"
    assert repoint_citations(answer, sources("21 CFR 211.25(a)")) == (answer, [])


def test_the_minimum_run_is_the_documented_one():
    assert MIN_WORDS == 5


# ---------------------------------------------------- in the pipeline


def test_the_pipeline_delivers_and_cites_the_corrected_number():
    from tests.test_accuracy_evaluation import PURCHASING
    from tests.test_accuracy_observer import answer_one

    question = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.10(b)(4) require?"
    probe = answer_one(question, "probe")
    index = {s.citation: s.index for s in probe.package.sources}
    right, wrong = index["21 CFR 820.10(b)(2)"], index["21 CFR 820.10(b)(4)"]

    out = answer_one(question, f"21 CFR 820.10(b)(2): {PURCHASING} [{wrong}]")
    first = out.answer.splitlines()[0]                # the model's sentence (the pipeline then adds (b)(4) itself)
    assert first.endswith(f"conform to specified requirements. [{right}]")
    assert out.metadata["generation"]["citations_repointed"] == [
        {"from": [wrong], "to": right, "text": PURCHASING[:160]}]
    assert right in [c.index for c in out.citations if c.cited_in_answer]

    same = answer_one(question, f"21 CFR 820.10(b)(2): {PURCHASING} [{right}]")
    assert "citations_repointed" not in same.metadata["generation"]


# ---------------------------------------------------- ambiguity is left alone; corrections never hide a defect


def test_a_sentence_drawing_on_two_sources_keeps_the_marker_of_the_part_it_cites():
    # the first clause is 211.25(a)'s, the rest is 211.25(c)'s; [1] supports the first part, so it is not moved
    answer = ("Training shall be in the particular operations that the employee performs, and there shall be an adequate "
              "number of qualified personnel to perform and supervise the manufacture, processing, packing, or holding of "
              "each drug product [1].")
    assert repoint_citations(answer, S211) == (answer, [])


def test_a_marker_group_that_already_names_the_stating_source_is_unchanged():
    answer = "21 CFR 820.35 adds the nature and details of the complaint [5][7]."
    assert repoint_citations(answer, S820) == (answer, [])


def test_a_partial_quotation_unique_to_one_source_is_corrected():
    answer = "Records must hold the nature and details of the complaint [5]."      # "the nature ... complaint": 7 of 10 words
    new, changes = repoint_citations(answer, S820)
    assert [(c.old, c.new) for c in changes] == [((5,), 7)]


def test_a_corrected_marker_does_not_hide_a_contradiction():
    from tests.test_accuracy_evaluation import PURCHASING
    from tests.test_accuracy_observer import answer_one, payload

    question = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.10(b)(4) require?"
    negated = PURCHASING.replace("shall establish", "shall not establish")
    out = answer_one(question, f"21 CFR 820.10(b)(2): {negated} [2]")
    review = payload(out, accuracy=True)["accuracy"]
    from regulus.accuracy.review import question_review

    v = question_review(review, question=out.question)
    assert v["status"] != "pass"
