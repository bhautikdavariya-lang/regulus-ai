"""Real database + real Qwen, one question. Slow and integration.

Run:  pytest -m "slow and integration" tests/integration/test_rag_slow.py
"""

import psycopg
import pytest

from regulus.rag import RagConfig, RagPipeline, load_qwen_generator
from regulus.retrieval import Database, DatabaseConfigError, LexicalRetriever

pytestmark = [pytest.mark.slow, pytest.mark.integration]

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
    assert after == before


def test_rag_end_to_end_one_question(db, settings):
    settings.generation.do_sample = False
    settings.generation.max_new_tokens = 48
    generator = load_qwen_generator(settings)
    pipeline = RagPipeline(LexicalRetriever(db), generator, RagConfig(top_k=6))
    out = pipeline.answer("What does 21 CFR 820.10 cover?")

    assert out.model_called and not out.no_context
    assert out.answer.strip()
    assert out.input_tokens and out.input_tokens > 200 and out.output_tokens and out.output_tokens > 0
    assert out.context.sources and len(out.context.text) <= 3600
    # every citation is one of the retrieved results
    retrieved_labels = {r.citation.label for r in out.retrieved_results}
    assert out.citations and all(c.label in retrieved_labels for c in out.citations)
    assert out.citations[0].label == "21 CFR 820.10" and out.citations[0].url.startswith("https://www.ecfr.gov/")
    for k in ("retrieval_ms", "context_ms", "generation_ms", "total_ms"):
        assert out.timings_ms[k] >= 0
    d = out.to_dict()
    assert "password" not in str(d) and "guidance_id" not in str(d)

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        db.query("INSERT INTO cfr_records (id) VALUES (gen_random_uuid())")
