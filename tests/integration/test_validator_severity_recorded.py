"""The validator severity fix on the recorded benchmark rows, against the real (read-only) database. No model:
each row's recorded raw draft is handed back by a scripted generator, as in the paired offline experiment
(~/regulus_eval_runs/severity_experiment_20261016T115314Z, work/replay_arm.py).

Pinned (tests/fixtures/validator_severity_recorded_rows.json): the 7 delivered PASS answers (D-013 through
its existing repair) and the 5 not-generated PASS rows unchanged; every negative control unchanged; D-015
(fabricated citation), PB-008 (false premise endorsed) and SD-012 (must-decline answered) withheld; M-002,
S-018 and SD-007 still withheld (S-018 and SD-007 carry none of the three findings: this fix does not catch
them); D-019, H-002, M-017 and M-022 now withheld instead of repaired in place. Rubric verdicts are blind
subagent scores, not SME-verified.

Run:  pytest -m integration tests/integration/test_validator_severity_recorded.py
"""

import hashlib
import json
from pathlib import Path

import psycopg
import pytest

from regulus.config import load_settings
from regulus.inference.types import GenerationResult
from regulus.rag import RagPipeline
from regulus.retrieval import Database, DatabaseConfigError
from regulus.retrieval.factory import build_retriever
from regulus.system_identity import configured_rag_config

pytestmark = [pytest.mark.integration]

ROWS = {r["id"]: r for r in json.loads((Path(__file__).parents[1] / "fixtures" / "validator_severity_recorded_rows.json")
                                       .read_text(encoding="utf-8"))["rows"]}
WITHHELD = "could not be validated"


class Scripted:
    next = None

    def generate(self, messages, max_new_tokens=None):
        return self.next

    def describe(self):
        return {"model_id": "scripted-replay"}


def delivery(out) -> str:
    if not out.model_called:
        return "not_generated"
    if WITHHELD in (out.answer or ""):
        return "withheld"
    return f"fallback:{out.metadata['fallback_type']}" if out.metadata.get("fallback_type") else "delivered"


@pytest.fixture(scope="module")
def replay():
    try:
        db = Database.from_env()
        db.connect()
    except DatabaseConfigError as exc:
        pytest.skip(str(exc))
    except psycopg.OperationalError as exc:
        pytest.skip(f"database unavailable: {type(exc).__name__}")
    config = configured_rag_config(load_settings())
    retriever, scope = build_retriever(db, config)
    gen = Scripted()
    pipe = RagPipeline(retriever, gen, config, scope_policy=scope)

    def run(row):
        gen.next = (GenerationResult(prompt="", response=row["raw_model_output"], prompt_tokens=0,
                                     generated_tokens=row["generated_tokens"], seconds=1.0, finished=row["finished"],
                                     stop_reason=row["stop_reason"]) if row["model_called"] else None)
        out = pipe.answer(row["question"])
        fingerprint = out.evidence_snapshot.fingerprint if out.evidence_snapshot is not None else None
        if fingerprint != row["evidence_fingerprint"]:
            pytest.fail(f"{row['id']}: evidence differs from the recording (database or retrieval changed); "
                        "the expected outcome no longer applies")
        return out

    yield run
    db.close()


@pytest.mark.parametrize("qid", sorted(ROWS))
def test_recorded_row_reaches_the_experiment_outcome(replay, qid):
    row = ROWS[qid]
    out = replay(row)
    expected = row["expected"]
    assert delivery(out) == expected["delivery"]
    # P1 (2026-10-20, regulus.rag.prompt.withheld_evidence_statement): when the hard ceiling cut retrieved text of a
    # requested provision, one evidence-gap line is appended after everything else. The recording predates it, so
    # the answer before that line must still be the recorded one, byte for byte, and the line is there exactly when
    # the run recorded an evidence gap.
    body, notice, _ = (out.answer or "").partition("\nEvidence limit:")
    gap = out.metadata.get("evidence_gap")
    assert bool(notice) == bool(gap and gap["notice_appended"])
    assert hashlib.sha256(body.encode()).hexdigest() == expected["delivered_sha256"]
    assert str((out.metadata.get("validation") or {}).get("repair")) == str(expected["repair"])


@pytest.mark.parametrize("qid", sorted(q for q, r in ROWS.items() if {"pass_delivered", "pass_not_generated", "negative_control"} & set(r["groups"])))
def test_no_correct_answer_and_no_negative_control_changes(qid):
    row = ROWS[qid]
    assert row["before"] == {k: row["expected"][k] for k in row["before"]}


def test_the_fixture_pins_the_safety_cases():
    for qid in ("D-015", "PB-008", "SD-012", "D-019", "H-002", "M-017", "M-022"):
        assert (ROWS[qid]["before"]["delivery"], ROWS[qid]["expected"]["delivery"]) == ("delivered", "withheld"), qid
        assert ROWS[qid]["expected"]["treated_initial_errors"], qid
    for qid in ("M-002", "S-018", "SD-007"):
        assert ROWS[qid]["expected"]["delivery"] == "withheld", qid
    assert not ROWS["S-018"]["expected"]["treated_initial_errors"] and not ROWS["SD-007"]["expected"]["treated_initial_errors"]
    assert ROWS["D-013"]["expected"]["repair"] == "invented_conditions_removed" and ROWS["D-013"]["expected"]["delivery"] == "delivered"
