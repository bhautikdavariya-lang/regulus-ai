"""A figure the evidence never states - a period, a quantity with its unit, a date - is not supported
by it (Stage A, 2026-10-13).

"... must be thoroughly investigated within 30 days" agrees with 21 CFR 211.192 S2 on strength and
polarity, and the operators leave the period undetermined because S2 states none, so the claim was
supported. A figure the aligned passage does not state at all now withholds support on every support
path (`verdicts._unstated_figure`): unverifiable, never contradicted. A WRONG figure that the passage
does state is still the operators' quantity/limit conflict, and a figure written as a word in the
source ("thirty") still counts as stated.
"""

from __future__ import annotations

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy import operators as OP
from regulus.accuracy import verdicts as VD
from regulus.accuracy.alignment import LexicalAligner, Passage
from regulus.accuracy.review import PASS
from tests.test_accuracy_pass_integrity import production
from tests.test_accuracy_window_support import FOCUSED, S2, T211, claim_final

INVENTED = ("Any unexplained discrepancy or failure of a batch to meet its specifications must be thoroughly "
            "investigated within 30 days.")


def judged(claim: str, text: str):
    p = Passage(1, "21 CFR 1.1", "exact", text, None, "binding_regulation", 0)
    return VD.judge(claim, LexicalAligner().align(claim, [p]), evidence=[p])


@pytest.mark.parametrize("text, expected", [
    (INVENTED, (("day", "30"),)),
    ("Records must be retained for 2 years after distribution.", (("year", "2"),)),
    ("The report is due on January 1, 2020.", (("date", "2020"),)),
    ("21 CFR 211.192 requires an investigation under paragraph (c)(1).", ()),
    # acceptance row R-004: a form number is an identifier, not a figure
    ("These types of information correspond generally to the elements of Form FDA 3500A.", ()),
])
def test_figures_are_quantities_with_units_and_dates_not_section_numbers(text, expected):
    assert OP.figures(text) == expected


@pytest.mark.parametrize("claim, passage", [
    ("The report must be submitted within 15 calendar days.", "not later than 15 calendar days after receipt"),
    ("The report must be submitted within 30 days.", "within thirty calendar days of the determination"),
    ("The records must be kept for 2 years.", "for at least 2 years after the date of distribution"),
])
def test_a_figure_the_passage_states_is_not_withheld(claim, passage):
    assert VD._unstated_figure(claim, passage) is None


def test_the_invented_period_is_withheld_not_contradicted():
    v = judged(INVENTED, S2)
    assert v.verdict == VD.UNDECIDABLE and "30 day" in v.reason
    assert claim_final(FOCUSED, INVENTED) == AN.UNVERIFIABLE


def test_a_wrong_period_the_passage_states_is_still_a_contradiction():
    text = "The sponsor must notify FDA no later than 15 calendar days after determining the information qualifies."
    claim = "The sponsor must notify FDA no later than 7 calendar days after determining the information qualifies."
    assert judged(claim, text).verdict == VD.CONTRADICTED


def test_a_stated_period_restated_verbatim_is_supported():
    text = "The sponsor must notify FDA no later than 15 calendar days after determining the information qualifies."
    assert judged(text, text).verdict in VD.BORNE_OUT


def test_the_faithful_211_192_answer_still_passes():
    # keeps "whether or not the batch has already been distributed": the version without it drops a condition
    # the question turns on and no longer passes (test_accuracy_scope_extension.py)
    faithful = ("Any unexplained discrepancy or failure of a batch to meet its specifications must be thoroughly "
                "investigated, whether or not the batch has already been distributed.")
    v, _, _ = production(FOCUSED, faithful + " [1]", T211)
    assert v["status"] == PASS and v["live_check_score"] == 100
