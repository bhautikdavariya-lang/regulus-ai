"""Stage A: the deterministic regulatory question plan (regulus.planning.regulatory_plan). No model call; it guides
retrieval and coverage and states nothing about what the regulation requires."""

import pytest

from regulus.planning.regulatory_plan import PlanElement, build_regulatory_plan, keys_of

PETITION = ("We're a small cosmetic pigment maker and want FDA to list a new color additive for our makeup line. "
            "Can we propose it ourselves, and how must the petition be submitted?")
NOEL = ("Our animal study for a new cosmetic colorant shows a no-effect level of 500 mg/kg in the most sensitive species. "
        "How will FDA use that to set a tolerance?")


def test_each_question_clause_is_an_element_and_statements_give_it_a_subject():
    plan = build_regulatory_plan(PETITION)
    asks = [e for e in plan.elements if e.kind == "ask"]
    assert [e.text for e in asks] == ["Can we propose it ourselves", "how must the petition be submitted"]
    assert asks[1].keys == ("petiti", "submit") and "color" in asks[1].subject_keys
    assert plan.question_type == "procedure" and not plan.non_fda


def test_quantities_dates_and_the_temporal_reading_are_recorded():
    assert build_regulatory_plan(NOEL).quantities == ("500 mg/kg",)
    old = build_regulatory_plan("How did the old Quality System Regulation define design controls before 2026?")
    assert old.temporal == "historical" and old.dates == ("2026",)
    assert build_regulatory_plan("What does 21 CFR 211.100 require?").temporal == "current"


@pytest.mark.parametrize("question,references,non_fda", [
    ("What does FAA Part 107 require for a remote drone pilot certificate?", ("14 CFR part 107",), True),
    ("What does 21 CFR 820.30 require?", ("21 CFR 820.30",), False),
    ("What does Part 107 require?", ("21 CFR part 107",), False),
    ("What do OSHA rules say about scaffolding guardrails?", (), True),
    ("What does FDA require for food facility registration?", (), False),
])
def test_references_carry_the_title_an_explicit_agency_gives_them(question, references, non_fda):
    plan = build_regulatory_plan(question)
    assert plan.references == references and plan.non_fda is non_fda


def test_comparison_sides_named_things_and_quoted_terms_are_elements():
    plan = build_regulatory_plan("What is the difference between a recall, a market withdrawal, and a stock recovery?")
    assert [e.text for e in plan.elements if e.kind == "comparison_side"] == ["recall", "market withdrawal", "stock recovery"]
    named = build_regulatory_plan("Which section of 21 CFR Part 211 requires a Chief Quality Officer to sign batch records?")
    assert [e.text for e in named.elements if e.kind == "named_thing"] == ["Chief Quality Officer"]   # never "CFR Part"
    quoted = build_regulatory_plan("Are these 'color additives' in FDA's sense?")
    assert quoted.defined_terms == ("color additive", "color additives")


def test_question_words_are_not_keys():
    assert keys_of("How is a combination product defined") == ("combin",)


def test_an_element_is_covered_by_its_own_words_and_its_subject():
    e = PlanElement("ask2", "ask", "how must the petition be submitted", ("petiti", "submit"), ("color", "cosmet"))
    assert e.covered_by("Petitions shall include the following data and be submitted in the following form:", "Color Additive Petitions")
    assert not e.covered_by("Petitions shall be submitted in triplicate.", "Food Additive Petitions")      # no subject
    assert not e.covered_by("A color additive petition is a request.", "")                               # one own key of two
    named = PlanElement("named1", "named_thing", "third-party", ("third", "party"))
    assert named.covered_by("an accredited third party certification body") and not named.covered_by("a party to the contract")
