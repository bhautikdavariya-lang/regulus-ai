"""Relative-clause negation: a qualifier is not the duty's polarity (Measurement Audit Phase 2I/2J).

A negation inside a relative clause usually restricts WHICH things a rule covers
("labels ... that do not meet applicable requirements shall be destroyed"); it
does not negate the rule. But sometimes the negated clause IS the rule's
substance ("levels that do not exceed 0.003 percent"), and a claim that inverts
it is wrong even though every other word matches. These seven cases, built in
Phase 2I from verbatim eCFR text, pin both sides.

Evidence: VERBATIM 21 CFR text from the local read-only eCFR snapshot (citation,
snapshot date and content hash in tests/fixtures/accuracy_relative_clause_rows.json).
Claims: CONSTRUCTED for testing - one qualifier or modal changed - and are NOT
regulatory text.

Each test asserts the CLAIM-level decision (support basis, conflicts, final), with
a question that makes the claim relevant, so a relevance or scoring gate cannot
hide a wrong support decision.

Three cases fail on the current evaluator; they are marked xfail(strict=True)
with the measured reason, so the expectation is kept and the suite reports them
as known failures - and fails loudly the day one starts passing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.accuracy import answer as AN
from tests.test_accuracy_claim_extraction import judge

ROWS = {r["id"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures" / "accuracy_relative_clause_rows.json").read_text(encoding="utf-8"))["rows"]}

CREDITED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}


def decide(row_id):
    r = ROWS[row_id]
    a = judge(f"What does {r['citation']} require?", r["claim"] + " [1]", [(r["citation"], r["evidence"])])
    c = a.checked["claims"][0]
    return c, [x["operator"] for x in (c["operator_trace"] or {}).get("conflicts", [])]


def test_fixture_rows_are_the_phase_2i_set():
    assert [r for r in ROWS] == ["RC1", "RC2", "RC3", "RC4", "RC5", "RC6", "RC7"]
    for r in ROWS.values():
        assert r["claim_provenance"].startswith("CONSTRUCTED") and len(r["content_sha256"]) == 64


# ---------------------------------------------------- a qualifier must not negate the duty


@pytest.mark.xfail(strict=True, reason="current evaluator: the relative-clause 'that do not meet' makes 213.122(e) read "
                                       "NEGATE, so a correct narrower claim is CONTRADICTED (Phase 2I T1a)")
def test_RC1_213_122e_a_negated_qualifier_narrows_the_items_it_does_not_negate_the_rule():
    c, conflicts = decide("RC1")
    assert "polarity" not in conflicts
    assert c["final"] != AN.CONTRADICTED


# ---------------------------------------------------- a genuine negated duty stays a contradiction


@pytest.mark.xfail(strict=True, reason="current evaluator: the claim's 'that does not meet' and the rule's 'must not' both "
                                       "read NEGATE, so 'must use' vs 'must not use' AGREES and is given partial credit "
                                       "(Phase 2I T2b)")
def test_RC2_212_40c_must_use_is_not_must_not_use():
    c, conflicts = decide("RC2")
    assert "polarity" in conflicts
    assert c["support_basis"] not in CREDITED
    assert c["final"] == AN.CONTRADICTED


@pytest.mark.xfail(strict=True, reason="current evaluator: the claim's 'that are not present' makes it read NEGATE, so "
                                       "'shall be declared' vs 'shall not be declared' AGREES and is credited as "
                                       "paraphrase support (Phase 2I T2c)")
def test_RC3_101_36b2i_shall_be_declared_is_not_shall_not_be_declared():
    c, conflicts = decide("RC3")
    assert "polarity" in conflicts
    assert c["support_basis"] not in CREDITED
    assert c["final"] == AN.CONTRADICTED


# ---------------------------------------------------- a material qualifier that the claim inverts


def test_RC4_211_115a_batches_that_conform_are_not_batches_that_do_not_conform():
    c, conflicts = decide("RC4")
    assert conflicts
    assert c["support_basis"] not in CREDITED


def test_RC5_109_15b2i_a_fluid_that_contains_pcbs_is_not_one_that_does_not():
    c, conflicts = decide("RC5")
    assert conflicts
    assert c["support_basis"] not in CREDITED


def test_RC6_73_3110c1_levels_exceeding_the_limit_are_not_levels_that_do_not_exceed_it():
    c, conflicts = decide("RC6")
    assert conflicts
    assert c["support_basis"] not in CREDITED


# ---------------------------------------------------- a negated rule in another sentence of the passage


def test_RC7_701_13d_a_decimal_fraction_may_not_be_carried_beyond_two_places():
    c, conflicts = decide("RC7")
    assert conflicts
    assert c["support_basis"] not in CREDITED
