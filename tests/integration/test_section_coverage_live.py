"""RC1 section coverage against the real (read-only) database. No model.

Run:  pytest -m integration tests/integration/test_section_coverage_live.py
"""

import psycopg
import pytest

from regulus.planning import plan_query
from regulus.retrieval import Database, DatabaseConfigError, Filters, LexicalRetriever
from regulus.retrieval.query import content_terms

pytestmark = [pytest.mark.integration]

# The forensic case (UI-12). 21 CFR 11.10 answers it across (b)-(e); no single paragraph does.
UI12 = ("What requirements apply to protecting and retaining electronic records so they remain accurate, "
        "accessible, and readable throughout the required retention period?")


@pytest.fixture(scope="module")
def db():
    try:
        database = Database.from_env()
        database.connect()
    except DatabaseConfigError as exc:
        pytest.skip(str(exc))
    except psycopg.OperationalError as exc:
        pytest.skip(f"database unavailable: {type(exc).__name__}")
    yield database
    database.close()


def test_section_coverage_credits_a_section_for_words_spread_over_its_paragraphs(db):
    rows = LexicalRetriever(db).section_coverage_ecfr(" ".join(content_terms(UI12)), Filters(), 4)
    assert rows, "the statement returned nothing"
    top = rows[0].metadata
    # union over the section's paragraphs plus its best paragraph: strictly more than the paragraph alone
    assert top["section_coverage"] > 2 * top["paragraph_coverage"] - 1e-9
    assert top["section"] == "11.10"
    assert len({r.citation.label for r in rows if r.metadata["section"] == "11.10"}) == 2


def test_no_identifier_question_reaches_the_section_its_AND_search_misses(db):
    out = LexicalRetriever(db).run_plan(plan_query(UI12), top_k=8)
    assert out.response.timings_ms.get("full_text:ecfr") is not None
    assert out.response.diagnostics["section_coverage"]["run"] is True
    assert any(r.metadata.get("section") == "11.10" for r in out.response.results)


def test_identifier_question_does_not_run_section_coverage(db):
    out = LexicalRetriever(db).run_plan(plan_query("What does 21 CFR 11.10 require?"), top_k=8)
    assert out.response.diagnostics["section_coverage"]["run"] is False
