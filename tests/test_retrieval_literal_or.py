"""The literal-"or" switch (REGULUS_ECFR_LITERAL_OR; off by default).

websearch_to_tsquery reads a standalone "or" as its OR operator. Checked against PostgreSQL on 2026-10-21:
"certification or labeling" / "OR" / "Or" / ", or" / "or," / "(... or ...)" all parse to 'certif' | 'label';
"and/or" and "either-or" stay ordinary tokens; a leading or trailing "or" is dropped. Pinned:
  * literal_or removes exactly those operator forms and leaves every other text byte-identical;
  * a question offering real alternatives becomes an all-words query (the documented limit);
  * with the switch on, only a general question's eCFR all-words search changes: questions that name a provision
    or a docket, the guidance search and the question the pipeline answers are unchanged; off, nothing changes;
  * the pipeline fingerprint names the switch only when it is on.
"""
from __future__ import annotations

import os

import pytest

from regulus.planning import plan_query
from regulus.rag import RagConfig
from regulus.retrieval import lexical as L
from regulus.retrieval.lexical import LexicalRetriever
from regulus.retrieval.query import literal_or
from regulus.system_identity import pipeline_config
from tests.test_retrieval_plan import TableDatabase

PART73 = "We make an eye shadow with ultramarine blue. What restrictions, certification or labeling apply?"


# ------------------------------------------------------------------ the helper


@pytest.mark.parametrize("text, words", [
    ("What restrictions, certification or labeling apply?", ["What", "restrictions,", "certification", "labeling", "apply?"]),
    ("certification OR labeling", ["certification", "labeling"]),
    ("certification Or labeling", ["certification", "labeling"]),
    ("certification, or labeling", ["certification,", "labeling"]),
    ("certification or, labeling", ["certification", ",", "labeling"]),
    ("(certification or labeling)", ["(certification", "labeling)"]),
    ("or labeling", ["labeling"]),
    ("labeling or?", ["labeling", "?"]),
])
def test_each_standalone_or_operator_is_removed(text, words):
    assert literal_or(text).split() == words


@pytest.mark.parametrize("text", [
    "lipstick and/or lip balm",          # PostgreSQL keeps 'and/or' as a token
    "either-or rule",                    # and 'either-or'
    "color for vendors order",           # words that contain "or"
    "Oral care products for minors",
    "What labeling applies to a hair dye?",
    "",
])
def test_text_without_an_operator_is_byte_identical(text):
    assert literal_or(text) == text


def test_real_alternatives_become_all_words_the_documented_limit():
    # "a lipstick or a lip balm" asks about either; without the operator every word must match one row
    assert literal_or("Is a lipstick or a lip balm a cosmetic?").split() == \
        ["Is", "a", "lipstick", "a", "lip", "balm", "a", "cosmetic?"]


# ------------------------------------------------------------------ where it applies


class Recording(LexicalRetriever):
    """Records the text each full-text leg receives; finds nothing, so every later leg runs as it would."""

    def __init__(self):
        super().__init__(TableDatabase())
        self.ecfr, self.guidance = [], []

    def full_text_ecfr(self, query, filters, limit):
        self.ecfr.append(query)
        return []

    def full_text_guidance(self, query, filters, limit):
        self.guidance.append(query)
        return []


def legs(question, monkeypatch, enabled):
    monkeypatch.setattr(L, "ECFR_LITERAL_OR_ENABLED", enabled)
    r = Recording()
    plan = plan_query(question)
    r.run_plan(plan, top_k=8)
    return r, plan.normalized_question or plan.question


def test_the_switch_is_on_unless_set_to_0():
    # default on since 22 Oct (artifacts/cosmetics_benchmark/q17_fix_20261022); REGULUS_ECFR_LITERAL_OR=0 turns it off
    if os.environ.get("REGULUS_ECFR_LITERAL_OR") == "0":
        pytest.skip("REGULUS_ECFR_LITERAL_OR=0 is set in this environment")
    assert L.ECFR_LITERAL_OR_ENABLED is True


def test_off_the_general_question_is_searched_as_asked(monkeypatch):
    r, question = legs(PART73, monkeypatch, enabled=False)
    assert r.ecfr == [question] and r.guidance == [question]


def test_on_only_the_general_ecfr_search_loses_the_operator(monkeypatch):
    r, question = legs(PART73, monkeypatch, enabled=True)
    assert r.ecfr == [literal_or(question)] and r.ecfr != [question]
    assert r.guidance == [question]                                  # guidance search unchanged


@pytest.mark.parametrize("question", [
    "Does 21 CFR 73.2725 restrict certification or labeling?",      # names a provision
    "Summarise FDA-2016-D-2565 labeling or certification",           # names a docket
])
def test_on_questions_that_name_a_provision_or_docket_are_unchanged(monkeypatch, question):
    off, _ = legs(question, monkeypatch, enabled=False)
    on, _ = legs(question, monkeypatch, enabled=True)
    assert on.ecfr == off.ecfr and on.guidance == off.guidance


def test_on_a_general_question_without_or_is_unchanged(monkeypatch):
    off, _ = legs("What labeling applies to a hair dye?", monkeypatch, enabled=False)
    on, _ = legs("What labeling applies to a hair dye?", monkeypatch, enabled=True)
    assert on.ecfr == off.ecfr and on.guidance == off.guidance


def test_the_question_itself_is_never_rewritten(monkeypatch):
    monkeypatch.setattr(L, "ECFR_LITERAL_OR_ENABLED", True)
    plan = plan_query(PART73)
    before = (plan.question, plan.normalized_question)
    Recording().run_plan(plan, top_k=8)
    assert (plan.question, plan.normalized_question) == before and " or " in plan.question


# ------------------------------------------------------------------ the fingerprint


def test_the_pipeline_fingerprint_names_the_switch_only_when_on(monkeypatch):
    monkeypatch.setattr(L, "ECFR_LITERAL_OR_ENABLED", False)
    off = pipeline_config(RagConfig())
    assert "ecfr_literal_or" not in off["retrieval"]
    monkeypatch.setattr(L, "ECFR_LITERAL_OR_ENABLED", True)
    on = pipeline_config(RagConfig())
    assert on["retrieval"]["ecfr_literal_or"] is True
    assert {**on, "retrieval": {k: v for k, v in on["retrieval"].items() if k != "ecfr_literal_or"}} == off
