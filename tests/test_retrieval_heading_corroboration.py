"""Heading corroboration (lexical, general questions only): an eCFR candidate the retriever ALREADY found whose
specific section heading occurs verbatim in the question is kept for the prompt.

Measured 2026-10-20 on the 300 benchmark questions (draft keys, unverified): sections such as 58.33 "Study director."
and 121.126 "Food defense plan." were retrieved for questions that name them, then lost before the prompt (trigram
cut-off at 0.4; guidance chunks ahead of them in the soft budget). Safeguards, each from a measured failure: the
heading must be specific (several words, few sections, a rare word), and the section's part must be corroborated by
another candidate that is not itself a heading match (a food "statement of identity" question must not promote the
drug and device sections of that name). Nothing new is retrieved.
"""
from __future__ import annotations

import re

import pytest

from regulus.planning import plan_query
from regulus.retrieval import LexicalRetriever
from regulus.retrieval import sql as sql_module
from regulus.retrieval.query import heading_in_question
from tests.test_retrieval_plan import TableDatabase, guidance_row, row

Q_STUDY = "What are the responsibilities of the study director under the GLP regulation?"


def trigram(section, para, ordinal, heading, similarity=0.32, text=None):
    return row(section, para, ordinal, text=text or f"{section}{para} text", section_heading=heading, sim=similarity)


STUDY_DIRECTOR = trigram("58.33", "", 0, "Study director.")
GLP_NEIGHBOUR = trigram("58.35", "(b)", 1, "Quality assurance unit.")
GUIDANCE = [guidance_row(i, title_text=f"Guidance {i}", body_text="x " * 550, rank=0.5) for i in range(3)]


class HeadingDatabase(TableDatabase):
    """Answers the heading statistics from a small heading table (count of headings matching the regex)."""

    HEADINGS = ["Study director.", "Quality assurance unit.", "Statement of identity.", "Statement of identity.",
                "Definitions.", "Definitions.", "Definitions.", "Definitions.", "Definitions."]

    def query(self, statement, params=None):
        if statement == sql_module.ECFR_HEADING_COUNT:
            self.calls.append(("ECFR_HEADING_COUNT", dict(params)))
            pattern = re.compile(params["query"].replace(r"\m", r"\b").replace(r"\M", r"\b"))
            return [{"n": sum(1 for h in self.HEADINGS if pattern.search(h.lower()))}]
        return super().query(statement, params)


def run(question, trigram_rows, *, heading_corroboration=True, guidance=GUIDANCE):
    db = HeadingDatabase([], trigram=trigram_rows, or_guidance=guidance, guidance=guidance)
    # the defined-terms leg is covered by its own module; off here so a question saying "definitions" stays in scope
    out = LexicalRetriever(db, heading_corroboration=heading_corroboration, defined_terms=False).run_plan(
        plan_query(question), top_k=8)
    return out, db


def first_ecfr(out):
    return next(e for e in out.registry.evidence if e.result.corpus == "ecfr")


@pytest.mark.parametrize("heading,question,expected", [
    ("Study director.", Q_STUDY, True),
    ("Food defense plan.", "What does the intentional adulteration rule require in a food defense plan?", True),
    ("Production record review.", "What must the production record review include?", True),
    ("Records.", "What records must be kept?", False),                        # one word: never
    ("Study director.", "Who directs the study?", False),                    # not as a phrase
])
def test_a_heading_counts_only_as_a_whole_multi_word_phrase(heading, question, expected):
    assert heading_in_question(heading, question) is expected


def test_a_retrieved_section_named_by_its_heading_goes_ahead_of_guidance_and_past_the_trigram_cut():
    out, _ = run(Q_STUDY, [STUDY_DIRECTOR, GLP_NEIGHBOUR])
    e = first_ecfr(out)
    assert e.result.citation.section == "58.33" and e.result.metadata.get("heading_match") is True
    assert e.tier == "supporting"
    keys = [x.result.key for x in out.registry.evidence]
    assert keys.index(e.result.key) < min(keys.index(x.result.key) for x in out.registry.evidence if x.result.corpus != "ecfr")


def test_without_a_neighbour_from_its_own_part_nothing_is_promoted():
    out, _ = run(Q_STUDY, [STUDY_DIRECTOR])
    assert not any((e.result.metadata or {}).get("heading_match") for e in out.registry.evidence)


def test_two_sections_of_the_same_heading_do_not_corroborate_each_other():
    q = "How must the statement of identity appear on a food label?"
    drug = trigram("201.50", "(a)", 1, "Statement of identity.")
    drug2 = trigram("201.61", "(a)", 1, "Statement of identity.")
    out, _ = run(q, [drug, drug2])
    assert not any((e.result.metadata or {}).get("heading_match") for e in out.registry.evidence)


def test_a_generic_heading_is_never_promoted():
    q = "Which definitions apply to the dietary supplement rule?"
    out, _ = run(q, [trigram("111.3", "", 0, "Definitions."), trigram("111.5", "", 0, "Scope.")])
    assert not any((e.result.metadata or {}).get("heading_match") for e in out.registry.evidence)


def test_with_the_flag_off_the_registry_is_unchanged():
    on, _ = run(Q_STUDY, [STUDY_DIRECTOR, GLP_NEIGHBOUR], heading_corroboration=False)
    assert not any((e.result.metadata or {}).get("heading_match") for e in on.registry.evidence)


def test_a_question_that_names_a_provision_is_untouched():
    out, db = run("What does 21 CFR 58.33 require of the study director?", [STUDY_DIRECTOR, GLP_NEIGHBOUR])
    assert "ECFR_HEADING_COUNT" not in db.names()


def test_the_pipeline_keeps_a_promoted_trigram_hit_below_the_cut_off():
    from regulus.rag import RagConfig, RagPipeline
    pipe = RagPipeline(LexicalRetriever(HeadingDatabase([], trigram=[STUDY_DIRECTOR, GLP_NEIGHBOUR])), None, RagConfig())
    promoted = first_ecfr(run(Q_STUDY, [STUDY_DIRECTOR, GLP_NEIGHBOUR])[0]).result
    assert promoted.metadata["similarity"] < 0.4 and pipe.is_useful(promoted)
    unpromoted = first_ecfr(run(Q_STUDY, [STUDY_DIRECTOR, GLP_NEIGHBOUR], heading_corroboration=False)[0]).result
    assert unpromoted.metadata["similarity"] < 0.4 and not pipe.is_useful(unpromoted)   # the cut-off still applies


def test_the_heading_statement_is_read_only_and_registered():
    stmt = sql_module.ALL_STATEMENTS["ECFR_HEADING_COUNT"]
    assert stmt.lstrip().upper().startswith("SELECT") and "%(query)s" in stmt
