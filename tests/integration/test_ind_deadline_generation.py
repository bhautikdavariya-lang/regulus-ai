"""IND safety-reporting deadlines through the REAL model and the answering UI's own engine.

Greedy decoding with thinking off (`system_identity.configured_generation_config`), the configured
adapter, the read-only database: exactly how a live answer is produced. Decoding is greedy, so each
answer is reproducible run to run; the assertions are on content, never on exact wording.

Slow (loads the model) and needs the database: `pytest -m "slow and integration"`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.integration]

ROOT = Path(__file__).resolve().parents[2]
SEVEN_DAY = ("What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction "
             "under 21 CFR 312.32?")
TIMEFRAMES = "What are the IND safety reporting timeframes under 21 CFR 312.32?"
HOW_QUICKLY = "How quickly must IND safety reports be submitted under 21 CFR 312.32?"
BOTH = "What are the 7-day and 15-day IND safety reporting deadlines under 21 CFR 312.32?"
COMPARE = ("What is the difference between the 15-calendar-day and 7-calendar-day IND safety reporting deadlines in "
           "21 CFR 312.32?")
BROAD = "Summarize 21 CFR 312.32."
CONTROL = "What are the personnel qualification requirements in 21 CFR 211.25?"


@pytest.fixture(scope="module")
def engine():
    if not os.environ.get("REGULUS_DATABASE_URL"):
        pytest.skip("REGULUS_DATABASE_URL is not configured")
    sys.path.insert(0, str(ROOT / "scripts"))
    from serve_ui import Engine
    from regulus.config import load_settings

    return Engine(load_settings(), offline=True)


def _cited(r):
    return [c["label"] for c in r.get("citations") or [] if c.get("cited_in_answer")]


SEVEN_DAY_SUBJECT = "fatal or life-threatening"
CONDITIONS_15 = "(c)(1)(i), (c)(1)(ii), (c)(1)(iii), or (c)(1)(iv)"


def _sentences(answer):
    import re
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", answer or "") if s.strip()]


def _assert_no_misassignment(answer):
    """Every sentence giving 7 calendar days is about unexpected fatal or life-threatening reactions,
    and no sentence gives that subject 15 calendar days: the two errors the earlier prompts produced."""
    for sentence in _sentences(answer):
        if "7 calendar days" in sentence:
            assert SEVEN_DAY_SUBJECT in sentence, f"7 days given to another category: {sentence!r}"
        if "15 calendar days" in sentence:
            assert SEVEN_DAY_SUBJECT not in sentence, f"15 days given to the 7-day category: {sentence!r}"


def test_a_direct_seven_day_question_gets_the_seven_day_rule_from_c2(engine):
    r = engine.ask(SEVEN_DAY, accuracy=False)
    assert "7 calendar days" in r["answer"]
    assert "15 calendar days" not in r["answer"], "the 15-day rule is not the answer to this question"
    assert "21 CFR 312.32(c)(2)" in _cited(r)


@pytest.mark.parametrize("question", [TIMEFRAMES, BOTH])
def test_a_question_asking_for_both_timeframes_states_both_correctly(engine, question):
    r = engine.ask(question, accuracy=False)
    assert "7 calendar days" in r["answer"] and "15 calendar days" in r["answer"]
    assert {"21 CFR 312.32(c)(1)", "21 CFR 312.32(c)(2)"} <= set(_cited(r))
    assert CONDITIONS_15 in r["answer"], "the 15-day rule keeps the four conditions it runs from"
    _assert_no_misassignment(r["answer"])


def test_a_comparison_of_the_two_deadlines_assigns_each_to_its_own_category(engine):
    r = engine.ask(COMPARE, accuracy=False)
    assert "7 calendar days" in r["answer"] and "15 calendar days" in r["answer"]
    assert {"21 CFR 312.32(c)(1)", "21 CFR 312.32(c)(2)"} <= set(_cited(r))
    _assert_no_misassignment(r["answer"])


@pytest.mark.parametrize("question", [SEVEN_DAY, HOW_QUICKLY, TIMEFRAMES, BOTH, COMPARE])
def test_no_deadline_wording_assigns_a_deadline_to_the_wrong_category(engine, question):
    _assert_no_misassignment(engine.ask(question, accuracy=False)["answer"])


def test_a_broad_question_about_the_section_is_answered_without_the_value_plan(engine):
    """Summarize asks for no period: its prompt is unchanged, and it is still answered."""
    r = engine.ask(BROAD, accuracy=False)
    assert r["answer"].strip() and r.get("fallback_type") is None
    assert "periods stated" not in str(r.get("answer_shape") or "")


def test_the_how_quickly_wording_is_given_the_seven_day_paragraph(engine):
    """The evidence half of the "How quickly" case, which Priority 1 fixed and must not regress."""
    r = engine.ask(HOW_QUICKLY, accuracy=False)
    assert "21 CFR 312.32(c)(2)" in [s["citation"] for s in r["sources"]]


def test_the_how_quickly_wording_states_both_rules_each_with_its_own_source(engine):
    """Was a strict xfail (Priority 2): the focused answer stated (c)(1)'s 15 days alone. Flipped by
    the value plan (Priority 2A), and now asserted more strongly than the xfail did."""
    r = engine.ask(HOW_QUICKLY, accuracy=False)
    assert "7 calendar days" in r["answer"] and "15 calendar days" in r["answer"]
    assert {"21 CFR 312.32(c)(1)", "21 CFR 312.32(c)(2)"} <= set(_cited(r))
    assert "21 CFR 312.32(a)" not in _cited(r), "the definitions support neither deadline"
    _assert_no_misassignment(r["answer"])


@pytest.mark.parametrize("question", [SEVEN_DAY, HOW_QUICKLY, COMPARE, CONTROL])
def test_evaluation_on_and_off_give_byte_identical_answers_and_citations(engine, question):
    off = engine.ask(question, accuracy=False)
    on = engine.ask(question, accuracy=True)
    assert on["answer"] == off["answer"]
    assert on["citations"] == off["citations"]
    assert "accuracy" in on and "accuracy" not in off


def test_the_correct_direct_seven_day_answer_passes_evaluation(engine):
    """Was a strict xfail (Priority 2A): the focused completeness check demanded 21 CFR 312.32(d), follow-up,
    of a question about the 7-day deadline, because (d)(3) shares report / suspected / adverse / reaction
    with it. Fixed by requiring a demanded group to carry one of the question's distinguishing words."""
    r = engine.ask(SEVEN_DAY, accuracy=True)
    review = r["accuracy"]["question_review"]
    assert (review["label"], review["live_check_score"]) == ("PASS", 100)
