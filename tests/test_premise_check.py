"""Unsupported-premise check (regulus.grounding.premise, OFF unless passed to RagPipeline). Found on the benchmark's
negative controls (2026-10-20): "the requirements of 21 CFR Part 1250 Subpart Q" and "which section of Part 211
requires a Chief Quality Officer to sign every batch record" were answered from whatever the part says. The check
decides from the database, only for a named subpart or a specific thing a "which section of Part N requires X"
question names; ordinary wording is never checked."""

from datetime import date

import pytest

from regulus.accuracy.claims import MODEL, classify
from regulus.evaluation.grounding_eval import split_sentences
from regulus.grounding import premise as P
from regulus.grounding.premise import PremiseCheck, named_things, phrase_pattern
from regulus.rag import RagPipeline
from regulus.rag.fallback import FB_PREMISE_NOT_ESTABLISHED
from regulus.retrieval import LexicalRetriever
from tests.test_rag import FakeGenerator
from tests.test_retrieval_plan import TableDatabase


class FakeDb:
    """Part 211 (subparts A, B; mentions "quality control unit"), Part 1250 (subparts A, B)."""

    TEXT = {"211": "the quality control unit shall review batch records", "1250": "conveyances shall be sanitary"}
    SUBPARTS = {"211": [("A", "General Provisions"), ("B", "Organization and Personnel")],
                "1250": [("A", "General Provisions"), ("B", "Food Service Sanitation")]}

    def __init__(self):
        self.statements = []

    def query(self, statement, params=None):
        import re
        self.statements.append(statement)
        if statement == P.SNAPSHOT:
            return [{"d": date(2026, 9, 3)}]
        if statement == P.PART_EXISTS:
            return [{"n": int(params["part"] in self.TEXT)}]
        if statement == P.SUBPARTS:
            return [{"designation": d, "title": t} for d, t in self.SUBPARTS.get(params["part"], [])]
        if statement == P.PHRASE_IN_PART:
            pattern = params["pattern"].replace(r"\m", r"\b").replace(r"\M", r"\b")
            return [{"n": int(bool(re.search(pattern, self.TEXT.get(params["part"], ""), re.I)))}]
        raise AssertionError(statement)


@pytest.mark.parametrize("asserted,things", [
    ("a Chief Quality Officer to personally sign every batch record", ["Chief Quality Officer"]),
    ("third-party GMP certification of a dietary supplement facility", ["third-party"]),
    ("a manufacturer to hold ISO 13485 certification", ["ISO 13485"]),
    ("the 'Green Facility' program", ["Green Facility"]),
    ("a QA department to review batch records", []),                     # ordinary wording is never checked
])
def test_only_specific_named_things_are_checked(asserted, things):
    assert named_things(asserted) == things


def test_spaces_and_hyphens_are_interchangeable_in_the_phrase_search():
    assert phrase_pattern("third-party") == phrase_pattern("third party") == r"\mthird[\s\-]+party\M"


@pytest.mark.parametrize("question,unsupported,kind", [
    ("What are the requirements of 21 CFR Part 1250 Subpart Q?", True, P.KIND_SUBPART),
    ("Walk me through 21 CFR Part 1250 Subpart B.", False, None),
    ("What are the requirements of 21 CFR Part 9999 Subpart Q?", False, None),      # no such part: not this check's case
    ("Which section of 21 CFR Part 211 requires a Chief Quality Officer to personally sign every batch record?", True, P.KIND_NAMED),
    ("Which section of Part 211 requires a Quality Control Unit to review batch records?", False, None),
    ("Which section of Part 211 requires a QA department to review batch records?", False, None),
    ("What does Part 211 require for batch records?", False, None),
])
def test_decisions_come_from_the_database(question, unsupported, kind):
    d = PremiseCheck(FakeDb()).decide(question)
    assert d.unsupported is unsupported and d.kind == kind


def test_the_answer_states_what_the_database_lacks_and_lists_what_exists():
    d = PremiseCheck(FakeDb()).decide("What are the requirements of 21 CFR Part 1250 Subpart Q?")
    assert d.answer.startswith("The available eCFR data (snapshot 2026-09-03) has no Subpart Q in 21 CFR part 1250")
    assert "Subpart A (General Provisions); Subpart B (Food Service Sanitation)" in d.answer
    named = PremiseCheck(FakeDb()).decide("Cite the section of Part 211 that requires a Chief Quality Officer.")
    assert named.answer.startswith('No provision of 21 CFR part 211 in the available eCFR data (snapshot 2026-09-03) mentions "Chief Quality Officer"')
    for answer in (d.answer, named.answer):
        for sentence in split_sentences(answer):
            assert classify(sentence).origin != MODEL, sentence


def test_every_statement_is_read_only():
    db = FakeDb()
    PremiseCheck(db).decide("What are the requirements of 21 CFR Part 1250 Subpart Q?")
    assert db.statements and all(s.lstrip().upper().startswith("SELECT") for s in db.statements)


class Fired:
    def decide(self, question):
        return P.PremiseDecision(True, P.KIND_SUBPART, "820", ("Subpart Z",), ("Subpart Z",),
                                 "The available eCFR data (snapshot 2026-09-03) has no Subpart Z in 21 CFR part 820, so no "
                                 "requirements of such a subpart can be stated.")


def test_the_pipeline_answers_from_the_check_without_calling_the_model_and_is_unchanged_without_it():
    gen = FakeGenerator("Answer [1].")
    out = RagPipeline(LexicalRetriever(TableDatabase()), gen, premise_check=Fired()).answer("Walk me through 21 CFR Part 820 Subpart Z.")
    assert not out.model_called and not gen.messages
    assert out.metadata["fallback_type"] == FB_PREMISE_NOT_ESTABLISHED and out.answer.startswith("The available eCFR data")
    assert list(out.metadata["premise_check"]["missing"]) == ["Subpart Z"]
    plain = RagPipeline(LexicalRetriever(TableDatabase()), FakeGenerator("Answer [1].")).answer("What does 820.10(b)(1) require?")
    assert plain.metadata["premise_check"] is None


def test_a_premise_answer_carries_no_evidence_limit_notice():
    """The premise answer is decided from the whole part in the database, so the hard ceiling's evidence-gap notice
    (which is about the evidence given to the model) does not apply to it."""
    from tests.test_evidence_gap_notice import TABLE, ceiling
    from regulus.rag import RagConfig
    long_table = [dict(r, body_text="L" * 1500) for r in TABLE]
    out = RagPipeline(LexicalRetriever(TableDatabase(long_table)), FakeGenerator("Answer [1]."), RagConfig(context=ceiling()),
                      premise_check=Fired()).answer("What do 820.10(b)(1) through (b)(4) require?")
    assert "Evidence limit" not in out.answer and out.metadata["evidence_gap"] is None

