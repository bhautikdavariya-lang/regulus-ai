"""Stage 11 integration test: source loading and a small end-to-end build
against the local read-only database. Skipped without REGULUS_DATABASE_URL.

Run:  pytest -m integration tests/integration/test_training_db.py
"""

import psycopg
import pytest

from regulus.retrieval import Database, DatabaseConfigError
from regulus.training import TrainingConfig, prepare_dataset, validate_dataset
from regulus.training.pipeline import dataset_paths
from regulus.training.sources import assert_read_only, load_corpus, source_counts

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
    assert after == before, "write counters changed during the training-data integration tests"


def test_session_is_read_only(db):
    status = assert_read_only(db)
    assert status["default_transaction_read_only"] == "on" and status["transaction_read_only"] == "on"


def test_small_build_validates_against_database(db, tmp_path):
    config = TrainingConfig(target_examples=300, output_dir=tmp_path)
    corpus = load_corpus(db, config)
    counts = source_counts(corpus)
    assert counts["sections"] > 7000 and counts["records"] > 60000 and counts["definitions"] > 1000 and counts["guidance_documents"] > 1000
    assert corpus.snapshot_date == "2026-09-03"
    result = prepare_dataset(config, db)
    assert result.manifest["database"]["default_transaction_read_only"] == "on"
    assert 200 <= len(result.examples) <= 300
    assert {e.category for e in result.examples} >= {"direct_cfr", "definition", "fda_guidance", "abstention"}
    report = validate_dataset(dataset_paths(config), config, db)
    assert report.ok, report.errors[:5]
    assert report.checks["provenance"] == "verified" and report.checks["invalid_source_count"] == 0
    assert report.checks["invalid_citation_count"] == 0 and report.checks["negative_validation_failures"] == 0
