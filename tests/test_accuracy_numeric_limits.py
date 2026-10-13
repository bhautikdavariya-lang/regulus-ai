"""Numeric limits: direction, boundary, and what a number measures (controlled numeric fix, 2026-10-09).

A matching number is not agreement. "Not more than 0.1 percent" of an impurity is
not "0.1 percent" of the finished level; "15 calendar days" is not "15 business
days"; "143 °F" is not "143 °C"; and "at least 1 year" is the opposite of "less
than 1 year". Before this change the quantity operator agreed on every one of
those pairs, and the claims were credited.

Evidence: VERBATIM 21 CFR text from the local read-only eCFR snapshot (citation,
snapshot date and content hash per row in tests/fixtures/accuracy_numeric_limit_rows.json).
It is snapshot text, not the exact evidence of a model prompt.
Claims: CONSTRUCTED for testing (one bound phrase, number, unit or qualifier
changed) unless the row says VERBATIM, and are NOT regulatory text.

Expectations:
  conflict    a reversed limit: a `limit_direction` conflict, and the claim is contradicted
  equivalent  the same limit in other words: no numeric finding, not contradicted, and a
              claim the evaluator credited before this change is still credited
  boundary    the same direction with a different inclusive/strict boundary: support is
              blocked, the claim is neither credited nor contradicted
  blocked     the same number for a different quantity, day-count convention, temperature
              scale or population: support is blocked, never a contradiction
  no_finding  nothing comparable, or the reading is ambiguous: the check abstains
  not_the_same_limit
              the same number bounding a different event: never a limit conflict and never
              support; the final verdict is left to the other operators (these rows are
              contradicted today by the strength/polarity reading of "may not", which this
              change does not touch)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy import operators as OP
from tests.test_accuracy_claim_extraction import judge

ROWS = {r["id"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures" / "accuracy_numeric_limit_rows.json").read_text(encoding="utf-8"))["rows"]}

CREDITED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}


def decide(row_id):
    r = ROWS[row_id]
    comparison = OP.compare(r["claim"], r["evidence"])
    a = judge(f"What does {r['citation']} require?", r["claim"] + " [1]", [(r["citation"], r["evidence"])])
    return comparison, a.checked["claims"][0]


def by(expect):
    return sorted(i for i, r in ROWS.items() if r["expect"] == expect)


def test_fixture_rows_are_sourced_and_labelled():
    assert len(ROWS) == 38
    for r in ROWS.values():
        assert r["claim_provenance"].startswith(("CONSTRUCTED", "VERBATIM")) and len(r["content_sha256"]) == 64
        assert r["evidence"].strip() and r["expect"] in {"conflict", "equivalent", "boundary", "blocked", "no_finding", "not_the_same_limit"}


# ---------------------------------------------------- a reversed limit is a contradiction


@pytest.mark.parametrize("row_id", by("conflict"))
def test_a_reversed_limit_is_contradicted(row_id):
    comparison, c = decide(row_id)
    assert OP.CONFLICT_LIMIT in [x["operator"] for x in comparison.conflicts]
    assert c["support_basis"] not in CREDITED
    assert c["final"] == AN.CONTRADICTED


# ---------------------------------------------------- the same limit in other words is not


@pytest.mark.parametrize("row_id", by("equivalent"))
def test_an_equivalent_limit_is_not_contradicted_and_keeps_its_credit(row_id):
    comparison, c = decide(row_id)
    assert OP.CONFLICT_LIMIT not in [x["operator"] for x in comparison.conflicts]
    assert comparison.support_blocked is None
    assert c["final"] != AN.CONTRADICTED
    if ROWS[row_id]["credited_before"]:
        assert c["support_basis"] in CREDITED


# ---------------------------------------------------- a different boundary, quantity, convention, scale or population


@pytest.mark.parametrize("row_id", by("boundary") + by("blocked"))
def test_a_matching_number_that_is_not_the_same_limit_is_neither_credited_nor_contradicted(row_id):
    comparison, c = decide(row_id)
    assert OP.CONFLICT_LIMIT not in [x["operator"] for x in comparison.conflicts]
    assert comparison.support_blocked
    assert c["support_basis"] not in CREDITED
    assert c["final"] != AN.CONTRADICTED


# ---------------------------------------------------- abstention


@pytest.mark.parametrize("row_id", by("no_finding"))
def test_nothing_comparable_or_ambiguous_gives_no_numeric_finding(row_id):
    comparison, _ = decide(row_id)
    assert OP.CONFLICT_LIMIT not in [x["operator"] for x in comparison.conflicts]
    assert comparison.support_blocked is None


@pytest.mark.parametrize("row_id", by("not_the_same_limit"))
def test_the_same_number_for_a_different_event_is_never_a_limit_conflict_nor_support(row_id):
    comparison, c = decide(row_id)
    assert OP.CONFLICT_LIMIT not in [x["operator"] for x in comparison.conflicts]
    assert comparison.support_blocked
    assert c["support_basis"] not in CREDITED


# ---------------------------------------------------- how a limit is read


def test_a_limit_is_read_with_its_direction_unit_and_scale():
    (limit,) = [x for x in OP.numeric_limits("held at a temperature of not less than 143 °F for a period") if x.value == "143"]
    assert (limit.relation, limit.unit) == (">=", "degree f")
    (days,) = OP.numeric_limits("Appeal the order within 15 calendar days of the date of receipt")
    assert (days.relation, days.value, days.unit) == ("<=", "15", "calendar day")
    (share,) = OP.numeric_limits("containing not more than 0.1% by weight of glycol")
    assert (share.relation, share.value, share.unit) == ("<=", "0.1", "percent")


def test_a_negated_verb_turns_a_limit_around_only_when_it_directly_governs_it():
    (limit,) = OP.numeric_limits("Records shall not be retained for more than 1 year after expiration.")
    assert (limit.relation, limit.value, limit.unit) == ("<=", "1", "year")
    # a quantifier ("No record") or a second negation leaves the scope unclear: the reading abstains
    for text in ("No record shall be retained for less than 1 year.",
                 "Records that are not exempt shall not be retained for more than 1 year."):
        limits = OP.numeric_limits(text)
        assert limits and all(x.ambiguous for x in limits)


def test_a_negation_inside_another_limit_does_not_make_the_next_one_ambiguous():
    text = ("Polyethylene glycol (400) monolaurate containing not more than 0.1 percent by weight of ethylene and/or "
            "diethylene glycol may be used at a level not to exceed 0.3 percent by weight of twine")
    assert [(x.relation, x.value) for x in OP.numeric_limits(text)] == [("<=", "0.1"), ("<=", "0.3")]


def test_within_bounds_only_a_duration():
    assert OP.numeric_limits("within 5 percent of the declared value") == []
