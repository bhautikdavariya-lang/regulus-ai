"""Integration tests against the local regulus PostgreSQL database.

Run:  pytest -m integration
Skipped when REGULUS_DATABASE_URL is not configured or the server is down.
Read-only: the session-level write counters are asserted unchanged.
"""

import psycopg
import pytest

from regulus.retrieval import Database, DatabaseConfigError, Filters, LexicalRetriever, QueryType
from regulus.retrieval.models import METHOD_EXACT_CFR, METHOD_EXACT_DOCKET, METHOD_FULL_TEXT, METHOD_TRIGRAM

pytestmark = pytest.mark.integration

WRITE_COUNTERS = "SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) AS writes FROM pg_stat_user_tables"


@pytest.fixture(scope="module")
def db():
    try:
        database = Database.from_env()
        database.connect()
    except DatabaseConfigError as exc:
        pytest.skip(str(exc))
    except psycopg.OperationalError as exc:
        pytest.skip(f"database unavailable: {type(exc).__name__}")
    before = database.query(WRITE_COUNTERS)[0]["writes"]
    yield database
    after = database.query(WRITE_COUNTERS)[0]["writes"]
    database.close()
    assert after == before, "write counters changed during the integration tests"


@pytest.fixture(scope="module")
def retriever(db):
    return LexicalRetriever(db)


def test_connection_and_read_only_flags(db):
    s = db.status()
    assert s["server_version"].startswith("18.")
    assert s["database"] == "regulus"
    assert s["transaction_read_only"] == "on" and s["default_transaction_read_only"] == "on"
    assert "***" in s["url"] or "@" not in s["url"]


@pytest.mark.parametrize("stmt", ["INSERT INTO cfr_records (id) VALUES (gen_random_uuid())", "UPDATE cfr_records SET updated_at = now() WHERE false", "DELETE FROM fda_guidance_chunks WHERE false", "CREATE TEMP TABLE t (x int)"])
def test_writes_are_rejected_by_the_server(db, stmt):
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        db.query(stmt)


def test_exact_cfr_section_lookup(retriever):
    resp = retriever.run("21 CFR 820.10", corpus="ecfr", top_k=20)
    assert resp.query_type is QueryType.EXACT_CFR
    exact = [r for r in resp.results if r.retrieval_method == METHOD_EXACT_CFR]
    assert len(exact) == 12
    assert exact[0].citation.label == "21 CFR 820.10" and exact[0].relevance_score == 100.0
    assert exact[1].citation.label == "21 CFR 820.10(a)"
    assert exact[0].source_url.startswith("https://www.ecfr.gov/current/title-21/")
    assert exact[0].citation.heading == "Requirements for a quality management system."
    assert exact[0].metadata["part_title"]


def test_exact_cfr_paragraph_lookup_with_descendants(retriever):
    res = retriever.search("Explain 21 CFR 820.10(b)", corpus="ecfr", top_k=10)
    labels = [r.citation.label for r in res if r.retrieval_method == METHOD_EXACT_CFR]
    assert labels[0] == "21 CFR 820.10(b)"
    assert labels[1:] == ["21 CFR 820.10(b)(1)", "21 CFR 820.10(b)(2)", "21 CFR 820.10(b)(3)", "21 CFR 820.10(b)(4)"]
    assert res[0].metadata["match_kind"] == "exact" and res[1].metadata["match_kind"] == "descendant"


def test_reserved_section_returns_no_exact_hit(retriever):
    res = retriever.search("21 CFR 820.30(b)(1)", corpus="ecfr")
    assert not any(r.retrieval_method == METHOD_EXACT_CFR for r in res)


def test_full_text_ecfr(retriever):
    res = retriever.search("tamper-evident packaging requirements", corpus="ecfr", top_k=5)
    assert res and res[0].retrieval_method == METHOD_FULL_TEXT
    assert any(r.citation.section == "211.132" for r in res)
    assert all(r.relevance_score > 0 for r in res)


def test_full_text_guidance_and_citation(retriever):
    res = retriever.search("process validation general principles", corpus="fda_guidance", top_k=5)
    assert res and all(r.corpus == "fda_guidance" for r in res)
    hit = next(r for r in res if r.citation.docket_number == "FDA-2008-D-0559")
    assert hit.citation.status == "final" and hit.citation.issued_on == "2011-01-25" and hit.citation.url.startswith("https://")
    assert hit.citation.label.startswith("FDA Guidance: Process Validation")
    assert hit.metadata["retrievable"] is True


def test_exact_docket_lookup(retriever):
    res = retriever.search("FDA-2016-D-2565", corpus="fda_guidance")
    assert res[0].retrieval_method == METHOD_EXACT_DOCKET and res[0].citation.docket_number == "FDA-2016-D-2565"


def test_trigram_fallback_on_identifier_and_misspelling(retriever):
    res = retriever.search("820.3", corpus="ecfr", methods=[METHOD_TRIGRAM], top_k=5)
    assert res and res[0].citation.section == "820.3" and res[0].retrieval_method == METHOD_TRIGRAM
    res = retriever.search("informd consent", corpus="ecfr", methods=[METHOD_TRIGRAM], top_k=5)
    assert any("consent" in (r.heading or "").lower() for r in res)


def test_metadata_filters(retriever):
    res = retriever.search("labeling", corpus="ecfr", filters=Filters(part="801"), top_k=10)
    assert res and all(r.metadata["part"] == "801" for r in res)
    res = retriever.search("labeling", corpus="ecfr", filters=Filters(section="801.109"), top_k=10)
    assert res and all(r.citation.section == "801.109" for r in res)
    res = retriever.search("quality system", corpus="fda_guidance", filters=Filters(sector="device", status="final"), top_k=10)
    assert res and all(r.metadata["sector"] == "device" and r.metadata["status"] == "final" for r in res)
    res = retriever.search("quality system", corpus="fda_guidance", filters=Filters(center="CDER"), top_k=5)
    assert res and all(r.metadata["center"] == "CDER" for r in res)
    res_all = retriever.search("labeling", corpus="ecfr", filters=Filters(subchapter="H"), top_k=10)
    assert res_all and all(r.metadata["subchapter"] == "H" for r in res_all)


def test_cross_corpus_dedup_and_determinism(retriever):
    a = retriever.search("recall policy", top_k=10)
    b = retriever.search("recall policy", top_k=10)
    assert [r.key for r in a] == [r.key for r in b]
    assert len({r.key for r in a}) == len(a)
    assert {r.corpus for r in a} == {"ecfr", "fda_guidance"}


LONG_QUESTION = "Explain to someone with no medical background why a new drug must be approved before it can be sold."


def test_stage7_fallback_recovers_long_question_and_stage5_mode_returns_nothing(db):
    stage5 = LexicalRetriever(db, enable_or_fallback=False).run(LONG_QUESTION, top_k=8)
    assert stage5.results == [] and stage5.diagnostics["fallback_used"] is False and stage5.diagnostics["retrieval_mode"] == "none"
    stage7 = LexicalRetriever(db).run(LONG_QUESTION, top_k=8)
    d = stage7.diagnostics
    assert d["primary_result_count"] == 0 and d["fallback_used"] is True and d["retrieval_mode"] == "fallback"
    assert 0 < len(stage7.results) <= 8 and d["fallback_candidate_count"] <= 16
    assert all(r.retrieval_method == "full_text_or" for r in stage7.results)
    assert all(r.relevance_score < 50 for r in stage7.results)
    again = LexicalRetriever(db).run(LONG_QUESTION, top_k=8)
    assert [r.key for r in again.results] == [r.key for r in stage7.results]


def test_stage7_does_not_change_exact_and_sufficient_primary_queries(db):
    for q in ("21 CFR 820.10", "tamper-evident packaging requirements", "FDA-2016-D-2565"):
        a = LexicalRetriever(db, enable_or_fallback=False).run(q, top_k=10)
        b = LexicalRetriever(db).run(q, top_k=10)
        assert [r.key for r in a.results] == [r.key for r in b.results], q
        assert b.diagnostics["fallback_used"] is False, q


def test_stage7_negative_control_stays_free_of_exact_hits(db):
    resp = LexicalRetriever(db).run("21 CFR 820.30(b)(1)", top_k=10)
    assert not any(r.retrieval_method == METHOD_EXACT_CFR for r in resp.results)
    assert resp.diagnostics["fallback_terms"] in ([], ["820.30"])


def test_results_serialise_without_internal_ids(retriever):
    payload = retriever.run("21 CFR 801.109(a)", top_k=3).to_dict()
    text = str(payload)
    assert "guidance_id" not in text and "password" not in text
    assert payload["results"][0]["citation"]["label"] == "21 CFR 801.109(a)"
