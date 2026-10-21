"""A general question the model DECLINES although the CFR definitions of its terms were retrieved gets those
definitions, verbatim and cited, plus an explicit statement that they are not applied to the question's facts.

Measured 2026-10-20 (Qwen3-1.7B, MLX 4-bit): with 21 CFR 70.3(f) in the prompt the model still answered "The
available regulatory sources do not provide enough information to answer this." to the client's color additive
question; seven prompt variants and thinking mode did not change that without breaking other answers. The decline
is replaced only when (a) the answer is nothing but that sentence, (b) the defined-terms retrieval step supplied the
definitions, and (c) the quoted text validates. Anything else is untouched.
"""
from __future__ import annotations

import pytest

from regulus.inference.types import GenerationResult
from regulus.rag import RagConfig, RagPipeline
from regulus.rag.fallback import FB_DEFINITIONS_QUOTED
from regulus.rag.generation import DEFINITIONS_LEAD, DEFINITIONS_TAIL, whole_sentences
from regulus.retrieval import LexicalRetriever
from tests.test_retrieval_defined_terms import CLIENT_1, NOISE, TABLE, DefinedTermsDatabase

DECLINE = "The available regulatory sources do not provide enough information to answer this."


class Fixed:
    def __init__(self, response):
        self.response = response

    def generate(self, messages, max_new_tokens=None, on_text=None):
        return GenerationResult("p", self.response, 500, 20, 1.0, finished=True)

    def describe(self):
        return {"model_id": "fixed"}


def answer(question, response, *, defined_terms=True):
    db = DefinedTermsDatabase(TABLE, or_guidance=NOISE)
    pipe = RagPipeline(LexicalRetriever(db, defined_terms=defined_terms), Fixed(response), RagConfig())
    return pipe.answer(question)


def test_a_declined_definitional_question_gets_its_definitions_quoted_and_not_applied():
    out = answer(CLIENT_1, DECLINE)
    assert out.metadata["fallback_type"] == FB_DEFINITIONS_QUOTED
    assert out.answer.startswith(DEFINITIONS_LEAD) and out.answer.rstrip().endswith(DEFINITIONS_TAIL)
    assert "21 CFR 70.3(f): (f) A color additive is any material" in out.answer
    assert "[1]" in out.answer and "21 CFR 70.3(f)" in [c.label for c in out.citations]
    assert out.validation.ok                                           # the quoted text passed the unchanged validator


def test_the_decline_repeated_counts_as_a_decline():
    out = answer(CLIENT_1, f"{DECLINE}\n\n{DECLINE}")
    assert out.metadata["fallback_type"] == FB_DEFINITIONS_QUOTED


def test_without_retrieved_definitions_the_decline_stands():
    out = answer(CLIENT_1, DECLINE, defined_terms=False)
    assert out.answer == DECLINE and out.metadata["fallback_type"] is None


def test_a_general_question_that_is_not_definitional_keeps_its_decline():
    out = answer("Can a mica pigment coated with iron oxides be used in a body lotion?", DECLINE)
    assert out.answer == DECLINE and out.metadata["fallback_type"] is None


@pytest.mark.parametrize("response", [
    "Mica is a color additive under 21 CFR 70.3(f) [1].",                     # an answer: never replaced
    f"{DECLINE} Mica is a pigment derived from a mineral source [1].",       # a decline plus content: not bare
])
def test_an_answer_that_says_anything_else_is_never_replaced(response):
    out = answer(CLIENT_1, response)
    assert out.metadata["fallback_type"] != FB_DEFINITIONS_QUOTED


def test_a_truncated_source_is_quoted_only_up_to_its_last_whole_sentence():
    assert whole_sentences("First rule applies. Second rule appl [... truncated]") == "First rule applies."
    assert whole_sentences("Complete text.") == "Complete text."
    assert whole_sentences("no sentence end at all [... truncated]") == ""
