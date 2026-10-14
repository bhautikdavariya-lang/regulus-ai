"""A requirement narrowed with "only" / "solely" / "exclusively" / "limited to" is not supported
by evidence that states no restriction of its own (Stage A, 2026-10-13).

The 211.192 claim "Only a failure of a batch that has not been distributed ... must be thoroughly
investigated" agrees with S2 ("... shall be thoroughly investigated, whether or not the batch has
already been distributed") on strength and polarity and on nearly every term, and was supported -
PASS 100 through the production pipeline. The narrowing is now withheld on every support path
(`verdicts._unstated_narrowing`): the claim becomes unverifiable, never contradicted, and a
restriction the evidence does state is still supported.
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

NARROWED = ("Only a failure of a batch that has not been distributed to meet its specifications must be thoroughly "
            "investigated.")


def judged(claim: str, text: str):
    p = Passage(1, "21 CFR 1.1", "exact", text, None, "binding_regulation", 0)
    return VD.judge(claim, LexicalAligner().align(claim, [p]), evidence=[p])


# ------------------------------------------------------------- what counts as a narrowing


@pytest.mark.parametrize("text, word", [
    (NARROWED, "only"),
    ("The requirement applies solely to sponsors of investigational drugs.", "solely"),
    ("These records are kept exclusively by the quality control unit.", "exclusively"),
    ("The exemption is limited to drugs intended for export.", "limited to"),
])
def test_a_restrictive_word_is_recognised(text, word):
    assert OP.restrictive_scope(text) == word


@pytest.mark.parametrize("text", [
    "Records must not only be kept but also reviewed by the quality control unit.",
    "If only the batch had met its specifications, no investigation would follow.",
    # acceptance row M-001: a non-exhaustive list, the opposite of a restriction
    "Manufacturers subject to this part include, but are not limited to, manufacturers of components.",
    "The investigation shall extend to other batches of the same drug product.",
])
def test_additive_and_unrestricted_wording_is_not_a_narrowing(text):
    assert OP.restrictive_scope(text) is None


# ------------------------------------------------------------- evidence that states a restriction itself


@pytest.mark.parametrize("evidence", [
    "A prescription drug shall be dispensed only upon a valid prescription.",
    "This section applies solely to positron emission tomography drugs.",
    "All records shall be retained for 2 years, except records of distribution.",
    "No person other than the sponsor may submit the report.",
    "The batch shall not be released until the quality control unit approves it.",
    "The batch may be distributed unless it fails to meet its specifications.",
])
def test_evidence_with_its_own_restriction_does_not_block(evidence):
    assert OP.states_a_restriction(evidence)
    assert VD._unstated_narrowing("Only approved batches may be distributed.", evidence) is None


def test_the_conditional_form_is_left_to_the_operators():
    # "only if/when ..." is a condition (operators.RESTRICTIVE_ONLY), compared and reported there
    claim = "The batch must be investigated only if it fails to meet its specifications."
    assert OP.RESTRICTIVE_ONLY in OP.conditions(claim)
    assert VD._unstated_narrowing(claim, S2) is None


# ------------------------------------------------------------- the verdicts


def test_the_211_192_narrowing_is_withheld_not_contradicted():
    v = judged(NARROWED, S2)
    assert v.verdict == VD.UNDECIDABLE
    assert "narrows the requirement with 'only'" in v.reason
    assert claim_final(FOCUSED, NARROWED) == AN.UNVERIFIABLE


def test_a_restriction_the_evidence_states_is_still_supported():
    text = "A prescription drug shall be dispensed only upon a valid prescription."
    assert judged(text, text).verdict in VD.BORNE_OUT


def test_an_additive_not_only_claim_is_not_withheld():
    claim = "Records must not only be kept but also reviewed by the quality control unit."
    assert VD._unstated_narrowing(claim, S2) is None


def test_the_faithful_211_192_answer_still_passes():
    # keeps "whether or not the batch has already been distributed": the version without it drops a condition
    # the question turns on and no longer passes (test_accuracy_scope_extension.py)
    faithful = ("Any unexplained discrepancy or failure of a batch to meet its specifications must be thoroughly "
                "investigated, whether or not the batch has already been distributed.")
    assert claim_final(FOCUSED, faithful) == AN.SUPPORTED
    v, _, _ = production(FOCUSED, faithful + " [1]", T211)
    assert v["status"] == PASS and v["live_check_score"] == 100


def test_the_narrowed_answer_no_longer_passes_in_production():
    v, _, _ = production(FOCUSED, NARROWED + " [1]", T211)
    assert v["status"] != PASS
