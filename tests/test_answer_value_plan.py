"""The value plan: a focused question asking for a time period gets the periods paired with what
each applies to, from the pipeline (Priority 2A).

The routing it adds is narrow on purpose. It fires only for a FOCUSED question asking for a time
period whose requested provision's EXACT sources state at least two DIFFERENT periods, each from a
paragraph with its own eCFR heading. A question that names one of those conditions is left alone,
and so is every question that asks for no period, every overview, every comparison of named
provisions, and every provision stating one period. Measured: 0 of the 300 benchmark prompts
change.

Regulatory text: VERBATIM 21 CFR 312.32 and 211.180 from the read-only eCFR snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from regulus.planning import plan_query
from regulus.planning.shape import MODE_FOCUSED, MODE_SYNTHESIS, analyze_shape
from regulus.rag.answer_plan import (
    AnswerPlan,
    ValueEntry,
    format_line,
    plan_lines,
    value_entries,
)
from regulus.rag.evidence_values import selection_value_kind
from regulus.retrieval.evidence import TIER_EXACT, TIER_SUPPORTING

SECTION_HEADING = "IND safety reporting."
C1 = ("(c)(1) IND safety reports. The sponsor must notify FDA and all participating investigators (i.e., all "
      "investigators to whom the sponsor is providing drug under its INDs or under any investigator's IND) in an IND "
      "safety report of potential serious risks, from clinical trials or any other source, as soon as possible, but in "
      "no case later than 15 calendar days after the sponsor determines that the information qualifies for reporting "
      "under paragraph (c)(1)(i), (c)(1)(ii), (c)(1)(iii), or (c)(1)(iv) of this section. In each IND safety report, "
      "the sponsor must identify all IND safety reports previously submitted to FDA concerning a similar suspected "
      "adverse reaction, and must analyze the significance of the suspected adverse reaction in light of previous, "
      "similar reports or any other relevant information.")
C1_V = ("(v) Submission of IND safety reports. The sponsor must submit each IND safety report in a narrative format or "
        "on FDA Form 3500A. Upon request from FDA, the sponsor must submit to FDA any additional data or information "
        "that the agency deems necessary, as soon as possible, but in no case later than 15 calendar days after "
        "receiving the request.")
C2 = ("(2) Unexpected fatal or life-threatening suspected adverse reaction reports. The sponsor must also notify FDA of "
      "any unexpected fatal or life-threatening suspected adverse reaction as soon as possible but in no case later "
      "than 7 calendar days after the sponsor's initial receipt of the information.")
D3 = ("(3) If the results of a sponsor's investigation show that an adverse event not initially determined to be "
      "reportable under paragraph (c) of this section is so reportable, the sponsor must report such suspected adverse "
      "reaction in an IND safety report as soon as possible, but in no case later than 15 calendar days after the "
      "determination is made.")
DEFINITION = ("Suspected adverse reaction means any adverse event for which there is a reasonable possibility that the "
              "drug caused the adverse event.")


@dataclass(frozen=True)
class Src:
    index: int
    text: str
    tier: str = TIER_EXACT
    corpus: str = "ecfr"
    heading: str | None = SECTION_HEADING


SOURCES_312_32 = (Src(1, DEFINITION), Src(2, C1), Src(8, C1_V), Src(9, C2), Src(14, D3))

DIRECT_SEVEN = ("What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction "
                "under 21 CFR 312.32?")
HOW_QUICKLY = "How quickly must IND safety reports be submitted under 21 CFR 312.32?"
TIMEFRAMES = "What are the IND safety reporting timeframes under 21 CFR 312.32?"
BOTH = "What are the 7-day and 15-day IND safety reporting deadlines under 21 CFR 312.32?"
ALL = "What are all the reporting deadlines in 21 CFR 312.32?"
COMPARE = ("What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in "
           "21 CFR 312.32?")
UMBRELLA = [HOW_QUICKLY, TIMEFRAMES, BOTH, ALL, COMPARE]


def entries_for(question, sources=SOURCES_312_32):
    return value_entries(selection_value_kind(question), analyze_shape(plan_query(question)), sources)


# ---------------------------------------------------------------- routing


@pytest.mark.parametrize("question", UMBRELLA)
def test_a_question_about_the_whole_section_gets_each_distinct_period_once(question):
    entries = entries_for(question)
    assert [(e.value, e.index) for e in entries] == [("15 calendar days", 2), ("7 calendar days", 9)]
    assert entries[0].condition == "IND safety reports"
    assert entries[1].condition == "Unexpected fatal or life-threatening suspected adverse reaction reports"


def test_each_period_is_represented_once_not_once_per_source():
    """The 15-day period appears in (c)(1), (c)(1)(v) and (d)(3); listing every one would be listing
    every deadline, which the plan must not do. The first source in document order stands for it."""
    assert [e.index for e in entries_for(HOW_QUICKLY) if e.value == "15 calendar days"] == [2]


def test_a_question_naming_one_condition_is_left_to_the_focused_answer():
    """It names (c)(2)'s heading, so it is about one period; its prompt must not change."""
    assert entries_for(DIRECT_SEVEN) == ()


@pytest.mark.parametrize("question", ["Summarize 21 CFR 312.32.", "What does 21 CFR 312.32 require?"])
def test_a_broad_question_about_the_section_is_untouched(question):
    assert analyze_shape(plan_query(question)).mode == MODE_SYNTHESIS
    assert entries_for(question) == ()


@pytest.mark.parametrize("question", ["What are the IND safety reporting requirements under 21 CFR 312.32?",
                                      "What follow-up does 21 CFR 312.32 require after an IND safety report?"])
def test_a_focused_question_that_asks_for_no_period_is_untouched(question):
    assert analyze_shape(plan_query(question)).mode == MODE_FOCUSED
    assert entries_for(question) == ()


def test_a_provision_stating_one_period_is_untouched():
    assert entries_for(HOW_QUICKLY, (Src(2, C1), Src(8, C1_V))) == ()


def test_a_period_whose_source_has_no_heading_makes_the_plan_abstain():
    """Its heading is what a period is said to apply to; without one the pipeline would have to make
    that description up, so it describes nothing."""
    retention = ("(a) Any production, control, or distribution record ... shall be retained for at least 1 year after the "
                 "expiration date of the batch or, in the case of certain OTC drug products lacking expiration dating, "
                 "3 years after distribution of the batch.")
    q = "How long must records be retained under 21 CFR 211.180?"
    assert value_entries(selection_value_kind(q), analyze_shape(plan_query(q)),
                         (Src(1, retention, heading="General requirements."),)) == ()


def test_only_exact_ecfr_sources_count():
    supporting = (Src(2, C1), Src(9, C2, tier=TIER_SUPPORTING))
    assert entries_for(HOW_QUICKLY, supporting) == ()


# ---------------------------------------------------------------- the clause each period carries


def test_the_fifteen_day_clause_keeps_its_trigger_and_the_four_cross_referenced_conditions():
    clause = entries_for(HOW_QUICKLY)[0].clause
    assert "15 calendar days after the sponsor determines that the information qualifies" in clause
    assert "(c)(1)(i), (c)(1)(ii), (c)(1)(iii), or (c)(1)(iv) of this section" in clause


def test_the_seven_day_clause_keeps_its_condition_and_its_trigger():
    clause = entries_for(HOW_QUICKLY)[1].clause
    assert "unexpected fatal or life-threatening suspected adverse reaction" in clause
    assert "7 calendar days after the sponsor's initial receipt of the information" in clause


@pytest.mark.parametrize("question", UMBRELLA)
def test_every_clause_is_verbatim_source_text(question):
    by_index = {s.index: s.text for s in SOURCES_312_32}
    for e in entries_for(question):
        assert e.clause in by_index[e.index]


# ---------------------------------------------------------------- rendering


def _plan(values=()):
    shape = analyze_shape(plan_query(HOW_QUICKLY))
    return AnswerPlan(shape=shape, mode=shape.mode, lead_in=(), groups=(), context=(), related=(), sources=(),
                      values=tuple(values))


def test_without_values_the_plan_renders_exactly_as_before():
    plan = _plan()
    assert not any("periods stated" in line for line in plan_lines(plan))
    assert format_line(plan).startswith("ANSWER FORMAT: plain sentences stating only what the requested provision says")
    assert "values" not in plan.to_dict()


def test_with_values_each_period_is_paired_with_its_condition_and_source():
    values = entries_for(HOW_QUICKLY)
    plan = _plan(values)
    line = next(line for line in plan_lines(plan) if "periods stated" in line)
    assert "IND safety reports: in no case later than 15 calendar days" in line and "[2]" in line
    assert "Unexpected fatal or life-threatening suspected adverse reaction reports:" in line and "[9]" in line
    assert line.index("[2]") < line.index("[9]"), "periods stay in document order"
    fmt = format_line(plan)
    assert "Do not give a period for any other reports" in fmt
    assert "\n" not in fmt and ";" not in fmt.split("ANSWER FORMAT:")[1].split("Keep")[0], "the final line stays list-free"
    assert [v["index"] for v in plan.to_dict()["values"]] == [2, 9]


def test_a_value_entry_round_trips():
    e = ValueEntry("7 calendar days", 9, "Unexpected fatal reports", "no later than 7 calendar days")
    assert e.to_dict() == {"value": "7 calendar days", "index": 9, "condition": "Unexpected fatal reports",
                           "clause": "no later than 7 calendar days"}
