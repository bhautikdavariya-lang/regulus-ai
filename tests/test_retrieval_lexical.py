"""Citations, result model, filters, ranking, de-duplication and SQL safety.
Uses a fake Database so nothing connects to PostgreSQL."""

import ast
import inspect
import json
import re
from datetime import date
from pathlib import Path

import pytest

from regulus.retrieval import (
    Citation,
    DatabaseConfig,
    FilterError,
    Filters,
    LexicalRetriever,
    RetrievalResult,
    build_ecfr_citation,
    build_guidance_citation,
)
from regulus.retrieval import db as db_module
from regulus.retrieval import lexical as lexical_module
from regulus.retrieval import sql as sql_module
from regulus.retrieval.models import METHOD_EXACT_CFR, METHOD_FULL_TEXT, METHOD_TRIGRAM
from regulus.retrieval.ranking import EXACT_DESCENDANT_SCORE, EXACT_SCORE, exact_score, full_text_score, merge, trigram_score

# ------------------------------------------------------------------ fixtures


def ecfr_row(section="820.10", para="(b)(1)", ordinal=3, **over):
    row = {
        "title": "21", "chapter": "I", "subchapter_code": "H", "part_number": "820", "section_number": section,
        "paragraph_path": para, "path_ordinal": 0, "ordinal": ordinal, "section_heading": "Requirements for a quality management system.",
        "parent_headings": ["Medical Devices", "Part 820 - Quality Management System Regulation"],
        "body_text": f"({para}) body text", "ecfr_permalink": f"https://www.ecfr.gov/current/title-21/section-{section}",
        "govinfo_pdf_url": "https://www.govinfo.gov/x.pdf", "snapshot_date": date(2026, 9, 3),
        "effective_date": None, "last_amended_date": None, "is_reserved": False, "part_title": "Quality Management System Regulation",
    }
    row.update(over)
    return row


def guidance_row(docket="FDA-2016-D-2565", ordinal=0, **over):
    row = {
        "body_text": "chunk text", "title_text": "510(k) Third Party Review Program", "ordinal": ordinal, "start_offset": 0,
        "title": "510(k) Third Party Review Program", "docket_number": docket, "status": "final", "center": "CDRH",
        "sector": "device", "issued_on": date(2024, 11, 21), "source_url": "https://www.fda.gov/media/1.pdf",
        "anchor_part": "807", "anchor_section": None, "doc_class": "guidance", "retrievable": True,
    }
    row.update(over)
    return row


class FakeDatabase:
    """Returns canned rows per SQL statement and records every call."""

    def __init__(self, responses):
        self.responses = responses  # {statement_name: rows}
        self.calls = []

    def query(self, sql, params=None):
        name = next(n for n, s in sql_module.ALL_STATEMENTS.items() if s == sql)
        self.calls.append((name, dict(params or {})))
        return [dict(r) for r in self.responses.get(name, [])]


# ----------------------------------------------------------------- citations


def test_ecfr_citation_paragraph():
    c = build_ecfr_citation(ecfr_row())
    assert c.label == "21 CFR 820.10(b)(1)"
    assert c.section == "820.10" and c.paragraph == "(b)(1)" and c.part == "820"
    assert c.url.startswith("https://www.ecfr.gov/") and c.heading.startswith("Requirements")


def test_ecfr_citation_section_level_and_part_level():
    assert build_ecfr_citation(ecfr_row(para="", ordinal=0)).label == "21 CFR 820.10"
    assert build_ecfr_citation(ecfr_row(para="", ordinal=0)).paragraph is None
    c = build_ecfr_citation({"part_number": "820"})
    assert c.label == "21 CFR part 820" and c.url is None and c.section is None


def test_guidance_citation_full():
    c = build_guidance_citation(guidance_row())
    assert c.label == "FDA Guidance: 510(k) Third Party Review Program (final, 2024-11-21, Docket FDA-2016-D-2565)"
    assert c.docket_number == "FDA-2016-D-2565" and c.issued_on == "2024-11-21" and c.center == "CDRH"
    assert c.url == "https://www.fda.gov/media/1.pdf"


def test_guidance_citation_missing_docket_and_optional_fields():
    c = build_guidance_citation(guidance_row(docket=None, issued_on=None, status=None, center=None))
    assert c.label == "FDA Guidance: 510(k) Third Party Review Program"
    assert c.docket_number is None and c.issued_on is None and c.status is None and c.center is None


def test_guidance_citation_blank_docket_treated_as_missing():
    assert build_guidance_citation(guidance_row(docket="  ")).docket_number is None


# -------------------------------------------------------------- result model


def test_result_serialisation_and_required_fields():
    r = LexicalRetriever._ecfr_result(ecfr_row(), METHOD_FULL_TEXT, 1.5, {"ts_rank_cd": 0.15})
    d = r.to_dict()
    for k in ("corpus", "text", "heading", "relevance_score", "retrieval_method", "methods", "source_url", "citation", "metadata", "key"):
        assert k in d
    assert d["citation"]["label"] == "21 CFR 820.10(b)(1)"
    assert d["key"] == "ecfr:820.10:(b)(1):0"
    json.dumps(d)  # must be JSON-serialisable
    text = json.dumps(d).lower()
    for forbidden in ("password", "user_id", "session", "api_key", "guidance_id", "\"id\""):
        assert forbidden not in text


def test_result_null_optional_fields():
    r = LexicalRetriever._guidance_result(guidance_row(docket=None, anchor_section=None), METHOD_FULL_TEXT, 0.2, {})
    d = r.to_dict()
    assert d["citation"]["docket_number"] is None and d["metadata"]["anchor_section"] is None
    assert d["key"] == "fda_guidance:https://www.fda.gov/media/1.pdf#0"


def test_result_validation():
    cit = Citation(corpus="ecfr", label="x")
    with pytest.raises(ValueError):
        RetrievalResult("nope", "t", None, 1.0, METHOD_FULL_TEXT, None, cit, key="k")
    with pytest.raises(ValueError):
        RetrievalResult("ecfr", "t", None, 1.0, "vector", None, cit, key="k")
    with pytest.raises(ValueError):
        RetrievalResult("ecfr", "t", None, 1.0, METHOD_FULL_TEXT, None, cit, key="")


# ------------------------------------------------------------------ filters


def test_filters_defaults_and_validation():
    f = Filters()
    assert f.retrievable is True and not f.has_ecfr_filters() and not f.has_guidance_filters()
    f = Filters(part="820", section="820.10", subchapter="h", sector="device")
    assert f.subchapter == "H" and f.has_ecfr_filters() and f.has_guidance_filters()


@pytest.mark.parametrize("kwargs", [{"part": "abc"}, {"part": ""}, {"section": "820"}, {"subchapter": "Z"}, {"subchapter": "HH"}, {"anchor_part": "8x"}, {"anchor_section": "8.x"}, {"retrievable": "yes"}, {"sector": "   "}])
def test_invalid_filters(kwargs):
    with pytest.raises(FilterError):
        Filters(**kwargs)


def test_unknown_filter_name():
    with pytest.raises(FilterError, match="unknown filter"):
        Filters.from_kwargs(colour="red")


def test_filters_are_passed_as_parameters():
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("quality system", filters=Filters(part="820", sector="device", status="final"))
    ecfr = next(p for n, p in fake.calls if n == "ECFR_FULL_TEXT")
    guid = next(p for n, p in fake.calls if n == "GUIDANCE_FULL_TEXT")
    assert ecfr["part"] == "820" and ecfr["section"] is None
    assert guid["sector"] == "device" and guid["status"] == "final" and guid["retrievable"] is True


def test_corpus_filter_limits_statements():
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("21 CFR 820.10", corpus="fda_guidance")
    names = [n for n, _ in fake.calls]
    assert "ECFR_EXACT_SECTION" not in names and "ECFR_FULL_TEXT" not in names and "GUIDANCE_FULL_TEXT" in names
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("quality system", corpus="ecfr")
    assert all(n.startswith("ECFR_") for n, _ in fake.calls)
    with pytest.raises(ValueError):
        LexicalRetriever(fake).search("x", corpus="pubmed")


def test_section_filter_passed_to_exact_and_fts():
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("21 CFR 820.10(b)", filters=Filters(section="820.10"))
    exact = next(p for n, p in fake.calls if n == "ECFR_EXACT_SECTION")
    assert exact["section"] == "820.10" and exact["paragraph"] == "(b)" and exact["paragraph_prefix"] == "(b)(%"


# ------------------------------------------------------------------ ranking


def test_score_components():
    assert exact_score("exact", 0) == EXACT_SCORE
    assert exact_score("descendant", 2) == EXACT_DESCENDANT_SCORE - 0.002
    assert full_text_score(0.38) == pytest.approx(19.0)
    assert trigram_score(0.5) == 2.5


def test_exact_outranks_full_text_and_order_is_deterministic():
    fake = FakeDatabase({
        "ECFR_EXACT_SECTION": [ecfr_row(para="", ordinal=0, match_kind="exact"), ecfr_row(para="(a)", ordinal=1, match_kind="exact")],
        "ECFR_FULL_TEXT": [ecfr_row(section="211.1", para="(a)", ordinal=1, rank=0.9), ecfr_row(section="820.10", para="(a)", ordinal=1, rank=0.7)],
        "GUIDANCE_FULL_TEXT": [guidance_row(rank=0.8)],
    })
    r = LexicalRetriever(fake)
    first = r.search("21 CFR 820.10", top_k=10)
    second = r.search("21 CFR 820.10", top_k=10)
    assert [x.key for x in first] == [x.key for x in second]
    assert first[0].retrieval_method == METHOD_EXACT_CFR and first[0].citation.label == "21 CFR 820.10"
    assert first[1].citation.label == "21 CFR 820.10(a)"
    assert all(x.relevance_score < 50 for x in first[2:])
    assert first[2].citation.label == "21 CFR 211.1(a)"  # 9.0 > 8.0 guidance


def test_duplicates_merge_keeping_strongest_method():
    exact = LexicalRetriever._ecfr_result(ecfr_row(para="(a)", ordinal=1), METHOD_EXACT_CFR, 100.0, {})
    fts = LexicalRetriever._ecfr_result(ecfr_row(para="(a)", ordinal=1), METHOD_FULL_TEXT, 4.0, {})
    trg = LexicalRetriever._ecfr_result(ecfr_row(para="(a)", ordinal=1), METHOD_TRIGRAM, 2.0, {})
    merged = merge([trg, fts, exact])
    assert len(merged) == 1
    m = merged[0]
    assert m.retrieval_method == METHOD_EXACT_CFR and m.relevance_score == 100.0
    assert m.methods == (METHOD_EXACT_CFR, METHOD_FULL_TEXT, METHOD_TRIGRAM)
    assert set(m.metadata["scores"]) == {METHOD_EXACT_CFR, METHOD_FULL_TEXT, METHOD_TRIGRAM}


def test_merge_orders_by_score_then_key_and_truncates():
    a = LexicalRetriever._ecfr_result(ecfr_row(section="1.1", para="(a)", ordinal=1), METHOD_FULL_TEXT, 3.0, {})
    b = LexicalRetriever._ecfr_result(ecfr_row(section="1.1", para="(b)", ordinal=2), METHOD_FULL_TEXT, 3.0, {})
    c = LexicalRetriever._ecfr_result(ecfr_row(section="1.1", para="(c)", ordinal=3), METHOD_FULL_TEXT, 5.0, {})
    assert [r.key for r in merge([b, a, c])] == [c.key, a.key, b.key]
    assert len(merge([b, a, c], top_k=2)) == 2


def test_trigram_runs_only_for_short_or_identifier_or_sparse_queries():
    fake = FakeDatabase({"ECFR_FULL_TEXT": [ecfr_row(section=f"1.{i}", para="", ordinal=0, rank=0.1) for i in range(12)]})
    LexicalRetriever(fake).search("a long descriptive regulatory question about labeling requirements", top_k=10)
    assert "ECFR_TRIGRAM" not in [n for n, _ in fake.calls]
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("a long descriptive regulatory question about labeling requirements", top_k=10)
    assert "ECFR_TRIGRAM" in [n for n, _ in fake.calls]  # sparse full-text -> fallback
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("820.3", corpus="ecfr")
    assert "ECFR_TRIGRAM" in [n for n, _ in fake.calls]


def test_part_level_reference_uses_part_lookup():
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("21 CFR part 820", corpus="ecfr")
    assert "ECFR_EXACT_PART" in [n for n, _ in fake.calls]


def test_non_title_21_reference_skips_exact_lookup():
    fake = FakeDatabase({})
    LexicalRetriever(fake).search("42 CFR 493.1", corpus="ecfr")
    assert not any(n.startswith("ECFR_EXACT") for n, _ in fake.calls)


def test_docket_query_uses_exact_docket():
    fake = FakeDatabase({"GUIDANCE_EXACT_DOCKET": [guidance_row(ordinal=0), guidance_row(ordinal=1)]})
    res = LexicalRetriever(fake).search("FDA-2016-D-2565")
    assert res[0].retrieval_method == "exact_docket" and res[0].relevance_score == 100.0
    assert res[1].metadata["chunk_ordinal"] == 1


def test_empty_query_and_bad_top_k_and_method():
    r = LexicalRetriever(FakeDatabase({}))
    with pytest.raises(ValueError):
        r.search("   ")
    with pytest.raises(ValueError):
        r.search("x", top_k=0)
    with pytest.raises(ValueError):
        r.search("x", methods=["vector"])


def test_note_when_exact_lookup_finds_nothing():
    resp = LexicalRetriever(FakeDatabase({})).run("21 CFR 820.30(b)(1)", corpus="ecfr")
    assert resp.notes and "820.30(b)(1)" in resp.notes[0]
    assert "notes" in resp.to_dict()


def test_run_reports_timings_and_counts():
    fake = FakeDatabase({"ECFR_FULL_TEXT": [ecfr_row(rank=0.2)]})
    resp = LexicalRetriever(fake).run("quality", corpus="ecfr")
    assert resp.counts["full_text:ecfr"] == 1 and "full_text:ecfr" in resp.timings_ms and resp.total_ms >= 0
    assert resp.to_dict()["query_type"] == "GENERAL_REGULATORY_SEARCH"


# --------------------------------------------------------------- SQL safety

WRITE_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|ALTER|DROP|GRANT|REVOKE|COPY|VACUUM|REINDEX|CLUSTER)\b", re.IGNORECASE)


def test_sql_statements_are_read_only_and_parameterised():
    for name, stmt in sql_module.ALL_STATEMENTS.items():
        assert stmt.lstrip().upper().startswith("SELECT"), name
        assert not WRITE_RE.search(stmt), f"{name} contains a write keyword"
        assert "%(query)s" in stmt or "%(section_number)s" in stmt or "%(part_number)s" in stmt or "%(docket)s" in stmt
        assert "{" not in stmt and "}" not in stmt, f"{name} still has an unformatted placeholder"


def test_retrieval_code_never_formats_sql_with_user_input():
    """No f-strings, %-formatting or .format() touching SQL in lexical.py / db.py."""
    for module in (lexical_module, db_module):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                text = ast.unparse(node)
                assert "SELECT" not in text.upper(), f"f-string SQL in {module.__name__}: {text[:80]}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                assert "sql" not in ast.unparse(node).lower()
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant):
                assert "SELECT" not in str(node.left.value).upper()
    assert not hasattr(db_module.Database, "execute") and not hasattr(db_module.Database, "write")


def test_database_module_forces_read_only_and_redacts_url():
    source = Path(inspect.getsourcefile(db_module)).read_text(encoding="utf-8")
    assert "default_transaction_read_only=on" in source and "read_only = True" in source
    cfg = DatabaseConfig(url="postgresql://alice:s3cret@localhost:5432/regulus")
    assert cfg.redacted() == "postgresql://alice:***@localhost:5432/regulus"
    assert "s3cret" not in repr(cfg)


def test_database_config_from_env(monkeypatch):
    monkeypatch.delenv("REGULUS_DATABASE_URL", raising=False)
    with pytest.raises(db_module.DatabaseConfigError):
        DatabaseConfig.from_env(use_dotenv=False)
    monkeypatch.setenv("REGULUS_DATABASE_URL", "mysql://x")
    with pytest.raises(db_module.DatabaseConfigError):
        DatabaseConfig.from_env(use_dotenv=False)
    monkeypatch.setenv("REGULUS_DATABASE_URL", "postgresql://u:p@h/db")
    assert DatabaseConfig.from_env(use_dotenv=False).redacted() == "postgresql://u:***@h/db"
