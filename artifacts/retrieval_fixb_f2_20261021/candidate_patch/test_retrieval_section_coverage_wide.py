"""REGULUS_SECTION_COVERAGE_WIDE (retrieval repair B, F2 experiment; off by default).

Section coverage keeps at most 2 rows of each of its 4 top sections and 4 rows in all; with the switch on, the same 4
sections give up to 8 rows each and 16 in all. The SQL, the registry order (coverage rows last) and selection are
unchanged. No database, no model: TableDatabase stands in and records the SQL parameters.
"""

import pytest

from regulus.config import load_settings
from regulus.rag.context import ContextPolicy
from regulus.rag.selection import select_evidence
from regulus.retrieval import lexical as L
from regulus.retrieval.evidence import TIER_DISCOVERY
from regulus.system_identity import configured_rag_config, pipeline_config
from tests.test_retrieval_plan import TableDatabase
from tests.test_retrieval_section_coverage import UI12, coverage_row, guidance, run


def _coverage(n_sections=4, per_section=8):
    """n_sections x per_section canned coverage rows, best section first, best row first (as the SQL orders them)."""
    rows = []
    for s in range(n_sections):
        for r in range(per_section):
            rows.append(coverage_row(f"11.{10 + s}", f"({chr(97 + r)})", r, 1.6 - 0.2 * s, 0.5 - 0.05 * r,
                                     body_text=f"({chr(97 + r)}) Records of section {s} paragraph {r} protection retention."))
    return rows


def _coverage_call(db):
    return next(p for name, p in db.calls if name == "ECFR_SECTION_COVERAGE")


@pytest.fixture
def wide(monkeypatch):
    monkeypatch.setattr(L, "SECTION_COVERAGE_WIDE_ENABLED", True)


def test_the_switch_is_off_by_default_and_the_caps_are_unchanged():
    assert L.SECTION_COVERAGE_WIDE_ENABLED is False                      # nothing in the test environment sets it
    assert L.SECTION_COVERAGE_ROWS_PER_SECTION == 2
    db = TableDatabase(coverage=_coverage())
    run(UI12, db)
    p = _coverage_call(db)
    assert (p["sections"], p["rows_per_section"], p["limit"]) == (4, 2, 4)


def test_on_the_same_sections_give_more_rows(wide):
    db = TableDatabase(coverage=_coverage())
    res = run(UI12, db)
    p = _coverage_call(db)
    assert (p["sections"], p["rows_per_section"], p["limit"]) == (4, L.SECTION_COVERAGE_WIDE_ROWS_PER_SECTION, L.SECTION_COVERAGE_WIDE_ROW_LIMIT)
    assert (L.SECTION_COVERAGE_WIDE_ROWS_PER_SECTION, L.SECTION_COVERAGE_WIDE_ROW_LIMIT) == (8, 16)
    cov = [e for e in res.registry.evidence if e.result.retrieval_method == L.METHOD_FULL_TEXT_OR and e.result.corpus == "ecfr"]
    assert len(cov) == 16


def test_default_rows_are_kept_when_wide(wide, monkeypatch):
    db_wide = TableDatabase(coverage=_coverage())
    wide_keys = {e.key for e in run(UI12, db_wide).registry.evidence}
    monkeypatch.setattr(L, "SECTION_COVERAGE_WIDE_ENABLED", False)
    db_default = TableDatabase(coverage=_coverage())
    default_keys = {e.key for e in run(UI12, db_default).registry.evidence}
    assert default_keys <= wide_keys


def test_coverage_rows_still_follow_every_other_piece_of_evidence_ranked_as_before(wide, monkeypatch):
    db = TableDatabase(coverage=_coverage(), or_guidance=[guidance(i) for i in range(4)])
    reg = run(UI12, db).registry
    corpora = [e.result.corpus for e in reg.evidence]
    first_cov = corpora.index("ecfr")
    assert all(c == "ecfr" for c in corpora[first_cov:])                  # coverage rows still last
    scores = [e.score for e in reg.evidence[first_cov:]]
    assert scores == sorted(scores, reverse=True)                          # ranked by score, as by default
    # the four rows the default returns keep their relative order inside the wide list
    monkeypatch.setattr(L, "SECTION_COVERAGE_WIDE_ENABLED", False)
    default = [e.citation for e in run(UI12, TableDatabase(coverage=_coverage(), or_guidance=[guidance(i) for i in range(4)])).registry.evidence
               if e.result.corpus == "ecfr"]
    wide_cov = [e.citation for e in reg.evidence[first_cov:]]
    assert [c for c in wide_cov if c in default] == default


def test_selection_limits_hold_with_sixteen_coverage_rows(wide):
    db = TableDatabase(coverage=_coverage(), or_guidance=[guidance(i) for i in range(8)])
    reg = run(UI12, db).registry
    policy = ContextPolicy()
    sel = select_evidence(reg, policy)
    assert len(sel.selected) <= policy.max_results and sel.total_chars <= policy.max_total_chars
    assert sum(1 for e in reg.evidence if e.tier == TIER_DISCOVERY) == 24


def test_the_fingerprint_names_the_switch_only_when_on(monkeypatch):
    config = configured_rag_config(load_settings(use_dotenv=False))
    assert "section_coverage_wide" not in pipeline_config(config)["retrieval"]
    monkeypatch.setattr(L, "SECTION_COVERAGE_WIDE_ENABLED", True)
    assert pipeline_config(config)["retrieval"]["section_coverage_wide"] is True


def test_a_question_that_names_a_provision_never_calls_section_coverage(wide):
    db = TableDatabase(coverage=_coverage())
    run("What does 21 CFR 820.10 require for the quality management system?", db)
    assert not any(name == "ECFR_SECTION_COVERAGE" for name, _ in db.calls)
