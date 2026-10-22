"""Live, read-only: REGULUS_SECTION_COVERAGE_WIDE keeps every row the default section-coverage leg returns and adds rows
of the same top sections (retrieval repair B, F2 experiment). Questions from the cosmetics benchmark whose required
paragraphs sit beyond a section's first two rows. Skipped without the database."""

import pytest

from regulus.planning import plan_query
from regulus.retrieval import lexical as L

pytestmark = pytest.mark.integration

QUESTIONS = {
    "74.2602a(c)": "We're a small skincare brand formulating a tinted nail enamel. Our supplier offers Ext. D&C Violet No. 2. "
                   "Can we use it, is there a use limit, and does the color need FDA certification?",
    "700.25(d)": "Our vaginal product's container can't accept a seal. Can we get an exemption from the tamper-resistant rule, and how?",
}


@pytest.fixture(scope="module")
def db():
    from regulus.retrieval.db import Database
    try:
        database = Database.from_env()
        database.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unavailable: {type(exc).__name__}")
    yield database
    database.close()


def _coverage_rows(db, question, monkeypatch, wide):
    monkeypatch.setattr(L, "SECTION_COVERAGE_WIDE_ENABLED", wide)
    out = L.LexicalRetriever(db).run_plan(plan_query(question), top_k=8)
    return [e.citation for e in out.registry.evidence if e.result.metadata and "section_coverage" in e.result.metadata]


@pytest.mark.parametrize("target", sorted(QUESTIONS))
def test_wide_keeps_the_default_rows_and_adds_rows_of_the_same_sections(db, monkeypatch, target):
    q = QUESTIONS[target]
    default = _coverage_rows(db, q, monkeypatch, False)
    wide = _coverage_rows(db, q, monkeypatch, True)
    assert default and len(default) <= 4
    assert set(default) <= set(wide) and len(wide) > len(default)
    sections = lambda rows: {c.split(" ")[2].split("(")[0] for c in rows}
    assert len(sections(wide)) <= 4                                      # still at most the 4 top sections


def test_wide_makes_the_target_paragraph_a_candidate(db, monkeypatch):
    wide = _coverage_rows(db, QUESTIONS["700.25(d)"], monkeypatch, True)
    assert any(c.startswith("21 CFR 700.25(d)") for c in wide)
