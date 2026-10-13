"""Synthesis completeness through the REAL model and the answering UI's own engine (greedy, configured
adapter, read-only database). Slow and needs the database: `pytest -m "slow and integration"`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.integration]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def engine():
    if not os.environ.get("REGULUS_DATABASE_URL"):
        pytest.skip("REGULUS_DATABASE_URL is not configured")
    sys.path.insert(0, str(ROOT / "scripts"))
    from serve_ui import Engine
    from regulus.config import load_settings

    return Engine(load_settings(), offline=True)


def _completeness(r):
    return next(x for x in r["accuracy"]["dimensions"] if x["dimension"] == "completeness")


def test_a_synthesis_of_312_32_is_not_a_full_pass_when_its_obligations_were_not_all_in_the_evidence(engine):
    """The ceiling keeps (c)(2), the 7-day rule, and (d)(1)-(3) out of this question's evidence."""
    r = engine.ask("What does 21 CFR 312.32 require?", accuracy=True)
    assert r["accuracy"]["question_review"]["label"] != "PASS"
    assert _completeness(r)["state"] != "pass"


def test_a_complete_real_synthesis_still_passes(engine):
    r = engine.ask("What does 21 CFR 211.25 require?", accuracy=True)
    review = r["accuracy"]["question_review"]
    assert (review["label"], review["live_check_score"]) == ("PASS", 100)


@pytest.mark.parametrize("question", ["What does 21 CFR 312.32 require?", "What does 21 CFR 211.25 require?"])
def test_evaluation_on_and_off_give_byte_identical_answers_and_citations(engine, question):
    off = engine.ask(question, accuracy=False)
    on = engine.ask(question, accuracy=True)
    assert on["answer"] == off["answer"] and on["citations"] == off["citations"]
