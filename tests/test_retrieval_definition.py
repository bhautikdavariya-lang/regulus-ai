"""Definitional questions retrieve the CFR's own definition of the asked term.

"What does FDA stand for?" names no provision, and its words ("stand for") are
not the words the CFR defines with ("FDA means the Food and Drug
Administration."). Keyword search returned guidance about "good standing" and
none of the 22 snapshot paragraphs that define FDA (measured live, 2026-10-09).
The definition lookup is narrow: one short term, no provision named, and a
paragraph that OPENS with the term followed by "means". When it finds nothing,
retrieval is exactly what it was.

Definition texts are VERBATIM snapshot paragraphs from
tests/fixtures/accuracy_definition_citation_rows.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from regulus.planning import plan_query
from regulus.retrieval import LexicalRetriever
from regulus.retrieval.models import METHOD_DEFINITION, METHOD_FULL_TEXT
from regulus.retrieval.query import definition_term
from tests.test_retrieval_plan import TABLE, TableDatabase, row

TEXT = {p["citation"]: p["text"] for p in json.loads(
    (Path(__file__).parent / "fixtures" / "accuracy_definition_citation_rows.json").read_text(encoding="utf-8"))["paragraphs"]}

FDA_10_3 = row("10.3", "(a)", 1, text=TEXT["21 CFR 10.3(a)"])
FDA_203_3 = row("203.3", "(n)", 14, text=TEXT["21 CFR 203.3(n)"])
LOT_114_3 = row("114.3", "(c)", 3, text=TEXT["21 CFR 114.3(c)"])
MENTIONS_FDA = row("1.379", "(a)", 1, text="FDA may detain an article of food for a reasonable period.")


class DefinitionDatabase(TableDatabase):
    """TableDatabase that also answers ECFR_DEFINITION with the statement's own regular expression."""

    def query(self, statement, params=None):
        from regulus.retrieval import sql as sql_module

        if statement == sql_module.ECFR_DEFINITION:
            self.calls.append(("ECFR_DEFINITION", dict(params)))
            pattern = re.compile(params["pattern"].replace(r"\M", r"\b"), re.I)
            hits = [dict(r) for r in self.table if pattern.search(r["body_text"])]
            return sorted(hits, key=lambda r: (len(r["body_text"]), r["section_number"], r["ordinal"]))[: params["limit"]]
        return super().query(statement, params)


def run(question, table, **canned):
    db = DefinitionDatabase(table, **canned)
    return LexicalRetriever(db).run_plan(plan_query(question), top_k=8), db


# ---------------------------------------------------- which questions are definitional


@pytest.mark.parametrize("question,term", [
    ("What does FDA stand for?", "FDA"),
    ("What does the term Act mean?", "Act"),
    ("What is the meaning of the term 'lot'?", "lot"),
    ("What is the definition of a combination product?", "combination product"),
    ("Define \"batch\".", "batch"),
    ("What is meant by adulterated?", "adulterated"),
])
def test_a_definitional_question_names_its_term(question, term):
    assert definition_term(question) == term


@pytest.mark.parametrize("question", [
    "What does 21 CFR 820.35 mean?",                       # a provision: its own exact retrieval
    "What does FDA require for device labeling?",           # not a definition
    "What are the requirements of 21 CFR 211.25?",
    "What is FDA?",                                         # too open to read as a definition
    "What does it mean?",
    "What does the regulation say about recordkeeping for complaint files and servicing activities?",
])
def test_other_questions_are_not_definitional(question):
    assert definition_term(question) is None


# ---------------------------------------------------- retrieval


def test_the_terms_cfr_definition_is_retrieved_and_keyword_noise_is_not():
    noise = row("1.379", "(a)", 1, text="Importers in good standing may file.", rank=0.2)
    out, db = run("What does FDA stand for?", TABLE + [FDA_10_3, FDA_203_3, MENTIONS_FDA], full_text=[noise])
    labels = [r.citation.label for r in out.response.results]
    assert labels[:2] == ["21 CFR 10.3(a)", "21 CFR 203.3(n)"]
    assert all(r.retrieval_method == METHOD_DEFINITION for r in out.response.results)
    assert "ECFR_FULL_TEXT" not in db.names()                 # the keyword search was not run
    assert "21 CFR 1.379(a)" not in labels                     # mentions FDA, defines nothing
    assert any("definition of \"FDA\"" in n for n in out.response.notes)


def test_without_a_definition_retrieval_is_unchanged():
    hit = row("1.379", "(a)", 1, text="text about standing", rank=0.2)
    out, db = run("What does FDA stand for?", TABLE + [LOT_114_3], full_text=[hit])
    assert "ECFR_FULL_TEXT" in db.names()
    assert [r.retrieval_method for r in out.response.results] == [METHOD_FULL_TEXT]


def test_a_question_that_names_a_provision_never_runs_the_lookup():
    out, db = run("What does 21 CFR 820.10(b)(2) require?", TABLE + [FDA_10_3])
    assert "ECFR_DEFINITION" not in db.names()


def test_a_paragraph_that_only_mentions_the_term_is_not_its_definition():
    out, _ = run("What does lot mean?", TABLE + [LOT_114_3, row("110.3", "(x)", 2, text="Each lot shall be coded.")])
    assert [r.citation.label for r in out.response.results] == ["21 CFR 114.3(c)"]


def test_the_definition_statement_is_read_only_and_parameterised():
    from regulus.retrieval import sql as sql_module

    stmt = sql_module.ECFR_DEFINITION
    assert stmt.lstrip().upper().startswith("SELECT") and "%(query)s" in stmt and "%(pattern)s" in stmt
    assert sql_module.ALL_STATEMENTS["ECFR_DEFINITION"] is stmt
