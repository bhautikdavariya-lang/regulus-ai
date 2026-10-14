"""A regulated party's duty restated as FDA's is not supported (Stage A, 2026-10-13).

"FDA must thoroughly investigate any unexplained discrepancy ..." against 21 CFR 211.192 S2 ("... shall
be thoroughly investigated ...") agreed on strength and polarity; S2 names no duty-holder, and "fda"
is a framing word for the term checks, so the inversion was supported - PASS 100 in production. It is
now withheld on every support path (`verdicts._agency_duty_unstated`).

The rule is narrow on purpose. Measured on the 299 hand-scored acceptance answers, the obvious form
("the claim's duty-holder is FDA, the evidence's is not") would have withheld four correct statements
of the form "The FDA requires that ...", where FDA speaks the rule and the duty is someone else's; and
a rule against ANY party named for a passive requirement would have withheld ordinary scope
paraphrases ("A dietary supplement manufacturer must establish ..."). Neither is touched here.
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

REASSIGNED = "FDA must thoroughly investigate any unexplained discrepancy or failure of a batch to meet its specifications."


def judged(claim: str, text: str):
    p = Passage(1, "21 CFR 1.1", "exact", text, None, "binding_regulation", 0)
    return VD.judge(claim, LexicalAligner().align(claim, [p]), evidence=[p])


@pytest.mark.parametrize("text, obligated", [
    (REASSIGNED, True),
    ("FDA may withdraw a qualified facility exemption.", True),
    ("FDA shall respond within 30 days.", True),
    # FDA speaking the rule: the duty is someone else's (acceptance rows L-003, E-005)
    ("The FDA requires that ingredients be declared on a food label by their common or usual name.", False),
    ("The FDA requires additional controls for open systems, including integrity.", False),
    ("The manufacturer must investigate any unexplained discrepancy.", False),
])
def test_fda_as_the_obligated_party_is_told_apart_from_fda_speaking_the_rule(text, obligated):
    assert OP.agency_is_obligated(text) is obligated


@pytest.mark.parametrize("claim, passage, withheld", [
    (REASSIGNED, S2, True),
    ("FDA must submit the report.", "The report shall be submitted to FDA.", True),     # FDA as recipient
    ("FDA may withdraw a qualified facility exemption.", "A qualified facility exemption may be withdrawn by FDA.", False),
    ("FDA may withdraw a qualified facility exemption.", "FDA may withdraw a qualified facility exemption.", False),
    ("The FDA requires that ingredients be declared by their common or usual name.",
     "Ingredients shall be declared by their common or usual name.", False),
    ("The manufacturer must thoroughly investigate any unexplained discrepancy.", S2, False),   # scope paraphrase
])
def test_the_rule_withholds_only_an_inverted_role(claim, passage, withheld):
    assert VD._agency_duty_unstated(claim, passage) is withheld


def test_the_211_192_reassignment_is_withheld_not_contradicted():
    v = judged(REASSIGNED, S2)
    assert v.verdict == VD.UNDECIDABLE and "places the requirement on FDA" in v.reason
    assert claim_final(FOCUSED, REASSIGNED) == AN.UNVERIFIABLE


def test_the_reassigned_answer_no_longer_passes_in_production():
    v, _, _ = production(FOCUSED, REASSIGNED + " [1]", T211)
    assert v["status"] != PASS


def test_an_agency_duty_the_passage_states_is_still_supported():
    text = "FDA shall notify the applicant of the decision within 180 days."
    assert judged(text, text).verdict in VD.BORNE_OUT


def test_the_faithful_211_192_answer_still_passes():
    # keeps "whether or not the batch has already been distributed": the version without it drops a condition
    # the question turns on and no longer passes (test_accuracy_scope_extension.py)
    faithful = ("Any unexplained discrepancy or failure of a batch to meet its specifications must be thoroughly "
                "investigated, whether or not the batch has already been distributed.")
    assert claim_final(FOCUSED, faithful) == AN.SUPPORTED
    v, _, _ = production(FOCUSED, faithful + " [1]", T211)
    assert v["status"] == PASS and v["live_check_score"] == 100
