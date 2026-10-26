"""Measurement records for UI answers (regulus.traceability.ui_session, scripts/serve_ui.py).

The REAL Handler serves on loopback, backed by the REAL Engine.ask; only the model (a scripted generator)
and the database (the in-memory table) are replaced, and every session lives in a temporary directory.
Pinned: each request through /api/ask or /api/ask/stream is written exactly once - a full record when its
answer was delivered, pipeline_error or cancelled otherwise, never as an answer it was not; a replayed turn
is not written again; measurement and chat-history failures never touch the answer; --no-measure writes
nothing; and a session can be evaluated offline through the existing evaluator.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from regulus.accuracy.alignment import LexicalAligner
from regulus.config import PROJECT_ROOT, load_settings
from regulus.conversations import ConversationStore
from regulus.evaluation import offline_evaluation as O
from regulus.evaluation.ui_sessions import NotASession, evaluate_ui_session
from regulus.retrieval import LexicalRetriever
from regulus.traceability import measurement as M
from regulus.traceability.ui_session import DELIVERED, NOT_DELIVERED, SESSION_FILE, UISession
from tests.test_accuracy_evaluation import TABLE
from tests.test_accuracy_observer import CASES, Scripted, answer_one
from tests.test_retrieval_plan import TableDatabase

_spec = importlib.util.spec_from_file_location("serve_ui_measurement_test", PROJECT_ROOT / "scripts" / "serve_ui.py")
UI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UI)

CLEAN_Q, REPAIR_Q, MISSING_Q, OFFSCOPE_Q = CASES[0][0], CASES[2][0], CASES[3][0], CASES[6][0]
RESPONSES = {CLEAN_Q: CASES[0][1], REPAIR_Q: CASES[2][1], MISSING_Q: CASES[3][1], OFFSCOPE_Q: CASES[6][1]}
RUN = {"source": "ui", "model": {"model_id": "scripted"}, "code_revision": {"git_commit": None}}
# "followup": a second turn of the same conversation is read against the first (regulus.rag.conversation)
VOLATILE = ("wall_seconds", "server_timings_ms", "timings_ms", "stream", "conversation", "generation", "accuracy",
            "followup")


class Index:
    def section_status(self, s):
        return (True, True)

    def part_status(self, p):
        return (True, True)


FAKE_MLX = {"model_id": "Qwen/Qwen3-1.7B", "model_revision": "rev-1.7b", "backend": "mlx", "device": "mlx-gpu",
            "dtype": "mlx-4bit-g128", "quantization": {"bits": 4, "group_size": 128}, "runtime_versions": {"mlx": "fake"},
            "generation": {"do_sample": False}}


class FakeMlx(Scripted):
    """Stands in for the MLX worker, the application's one generator."""

    def describe(self):
        return dict(FAKE_MLX)


def engine():
    e = object.__new__(UI.Engine)
    e.settings, e.tokenizer, e.snapshot, e.db = load_settings(), None, "2026-01-01", None
    e._mlx, e._tokenizer_sha256 = FakeMlx(""), "fake-tokenizer-sha"
    e._retrieval = (LexicalRetriever(TableDatabase(TABLE)), None)
    e.accuracy, e.accuracy_alignment, e._aligner, e._identifier_index = True, "lexical", LexicalAligner(), Index()
    e.answer_shape = None
    e.raise_in_generation = None
    return e


@pytest.fixture
def ui(tmp_path, monkeypatch):
    eng = engine()

    class G(FakeMlx):
        def generate(self, messages, max_new_tokens=None):
            if eng.raise_in_generation is not None:
                raise eng.raise_in_generation
            prompt = messages[-1]["content"]
            matches = [r for q, r in RESPONSES.items() if q in prompt]
            assert len(matches) == 1
            self.response = matches[0]
            return super().generate(messages, max_new_tokens)

    eng._mlx = G("")

    class H(UI.Handler):
        pass

    H.engine = eng
    H.store = ConversationStore(tmp_path / "chat.sqlite3")
    H.measure = UISession(tmp_path / "ui_measurements", RUN, log=lambda m: None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield SimpleUI(f"http://127.0.0.1:{httpd.server_address[1]}", H)
    httpd.shutdown()
    httpd.server_close()


class SimpleUI:
    def __init__(self, base, H):
        self.base, self.H = base, H

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def ask(self, question):
        """/api/ask writes its record AFTER the response is sent (delivery is then known), so the client can
        return first: wait for that one record, as a later reader would."""
        n = self._count()
        status, text = self.post("/api/ask", {"question": question})
        if self.H.measure is not None:
            deadline = time.monotonic() + 10
            while self._count() <= n and time.monotonic() < deadline:
                time.sleep(0.01)
        return status, json.loads(text)

    def _count(self):
        if self.H.measure is None:
            return 0
        return self.H.measure.written + self.H.measure.write_failures

    def conversation(self):
        return json.loads(self.post("/api/conversations", {})[1])["conversation"]["id"]

    def stream(self, question, cid=None, tid=None):
        body = {"question": question, **({"conversation_id": cid, "turn_id": tid} if cid else {})}
        status, text = self.post("/api/ask/stream", body)
        return [json.loads(l) for l in text.splitlines() if l.strip()][-1]

    @property
    def records(self):
        path = self.H.measure.dir / M.MEASUREMENT_FILE
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    @property
    def rows(self):
        path = self.H.measure.dir / "answers.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def comparable(result):
    return {k: v for k, v in result.items() if k not in VOLATILE}


# ------------------------------------------------------------------ answered: both endpoints, every pipeline path


@pytest.mark.parametrize("endpoint", ["/api/ask", "/api/ask/stream"])
def test_a_delivered_answer_is_recorded_once_through_either_endpoint(ui, endpoint):
    if endpoint == "/api/ask":
        status, result = ui.ask(CLEAN_Q)
        assert status == 200
    else:
        cid, tid = ui.conversation(), str(uuid.uuid4())
        result = ui.stream(CLEAN_Q, cid, tid)["result"]
    [rec], [row] = ui.records, ui.rows
    assert rec["status"] == M.STATUS_CAPTURED and rec["complete"] and M.verify_record(rec) == []
    assert rec["text"]["delivered_answer"]["text"] == result["answer"] == row["answer"]
    assert rec["text"]["raw_model_output"]["text"] == RESPONSES[CLEAN_Q]
    assert rec["evidence"]["fingerprint"] == result["evidence_snapshot"]["fingerprint"]
    assert rec["evaluation"]["state"] == M.CAPTURED
    assert rec["evaluation"]["review"] == result["accuracy"]["question_review"]
    assert rec["evaluation"]["assessment"] == {k: v for k, v in result["accuracy"].items() if k != "question_review"}
    origin = rec["origin"]
    assert (origin["source"], origin["endpoint"], origin["delivery"]) == ("ui", endpoint, DELIVERED)
    if endpoint == "/api/ask/stream":
        assert (origin["conversation_id"], origin["turn_id"]) == (cid, tid) == (row["conversation_id"], row["turn_id"])
    assert rec["question_id"] == row["question_id"] and rec["question_id"].startswith("ui-")
    assert rec["run"]["run_id"] == ui.H.measure.session_id


@pytest.mark.parametrize("question,model_called", [(MISSING_Q, False), (OFFSCOPE_Q, False)],
                         ids=["provision-not-found", "out-of-scope"])
def test_a_refusal_without_generation_is_recorded(ui, question, model_called):
    result = ui.stream(question)["result"]
    [rec] = ui.records
    assert result["model_called"] is model_called and rec["status"] == M.STATUS_CAPTURED and rec["complete"]
    assert rec["text"]["raw_model_output"]["state"] == M.NOT_APPLICABLE
    assert rec["text"]["delivered_answer"]["text"] == result["answer"]
    assert rec["evaluator_inputs"]["model_called"] is False


def test_a_repaired_answer_is_recorded_with_its_repair(ui):
    result = ui.stream(REPAIR_Q)["result"]
    [rec] = ui.records
    assert rec["validation"]["repair"] == result["validation"]["repair"] == "appended_missing_provisions"
    # the local record keeps the initial (draft) report whole; the page gets it through the delivery
    # boundary, which keeps its codes and statuses but not the draft's sentences
    assert UI.browser_safe({"validation": rec["validation"]})["validation"]["initial"] == result["validation"]["initial"]
    assert rec["validation"]["initial"]["problems"] and all("sentence" in p for p in rec["validation"]["initial"]["problems"])
    assert rec["text"]["validation_input"]["state"] == rec["text"]["repair_output"]["state"] == M.CAPTURED
    assert rec["evaluator_inputs"]["answer_plan"] is not None or rec["evaluator_inputs"]["package_present"]


# ------------------------------------------------------------------ chat history off or failing


def test_with_history_unavailable_answers_are_still_recorded(ui):
    ui.H.store = None
    final = ui.stream(CLEAN_Q)
    assert final["type"] == "final"
    [rec] = ui.records
    assert rec["status"] == M.STATUS_CAPTURED and rec["origin"]["conversation_id"] is None


def test_a_chat_history_write_failure_leaves_the_record_and_the_answer(ui, monkeypatch):
    monkeypatch.setattr(ui.H.store, "record_answer", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    cid = ui.conversation()
    final = ui.stream(CLEAN_Q, cid, str(uuid.uuid4()))
    assert final["type"] == "final" and final["result"]["conversation"]["saved"] is False
    assert [r["status"] for r in ui.records] == [M.STATUS_CAPTURED]


# ------------------------------------------------------------------ measurement failure is isolated


def test_a_measurement_write_failure_changes_neither_answer_stream_nor_history(ui, tmp_path):
    cid = ui.conversation()
    good = ui.stream(CLEAN_Q, cid, str(uuid.uuid4()))
    (ui.H.measure.dir / M.MEASUREMENT_FILE).unlink()
    (ui.H.measure.dir / M.MEASUREMENT_FILE).mkdir()             # every later append now raises
    tid = str(uuid.uuid4())
    broken = ui.stream(CLEAN_Q, cid, tid)
    assert broken["type"] == "final" and comparable(broken["result"]) == comparable(good["result"])
    assert broken["result"]["accuracy"]["question_review"] == good["result"]["accuracy"]["question_review"]
    assert broken["result"]["conversation"]["saved"] is True
    assert ui.H.store.answer_for(cid, tid)["status"] == "ok"
    assert ui.H.measure.write_failures == 1
    status, plain = ui.ask(CLEAN_Q)
    assert status == 200 and plain["answer"] == good["result"]["answer"]


def test_a_record_that_cannot_be_built_is_a_visible_capture_error(ui, monkeypatch):
    monkeypatch.setattr(M, "build_record", lambda **k: (_ for _ in ()).throw(ValueError("defect")))
    final = ui.stream(CLEAN_Q)
    assert final["type"] == "final" and final["result"]["answer"]
    [rec], [row] = ui.records, ui.rows
    assert rec["status"] == M.STATUS_CAPTURE_ERROR and not rec["complete"] and M.verify_record(rec) == []
    assert row["execution_status"] == "CAPTURE_ERROR"


# ------------------------------------------------------------------ errors, cancellation, replay


@pytest.mark.parametrize("endpoint", ["/api/ask", "/api/ask/stream"])
def test_an_error_is_recorded_as_an_error_never_as_an_answer(ui, endpoint):
    ui.H.engine.raise_in_generation = RuntimeError("generator failed")
    if endpoint == "/api/ask":
        status, body = ui.ask(CLEAN_Q)
        assert status == 500
    else:
        assert ui.stream(CLEAN_Q)["type"] == "error"
    [rec], [row] = ui.records, ui.rows
    assert rec["status"] == M.STATUS_PIPELINE_ERROR and not rec["complete"] and "text" not in rec
    assert (row["execution_status"], row["answer"]) == ("ERROR", None)
    assert rec["origin"]["delivery"] == NOT_DELIVERED


def test_a_client_disconnect_during_generation_is_recorded_as_cancelled(ui):
    ui.H.engine.raise_in_generation = UI.ClientDisconnected()   # what send() raises when the socket is gone
    cid, tid = ui.conversation(), str(uuid.uuid4())
    ui.post("/api/ask/stream", {"question": CLEAN_Q, "conversation_id": cid, "turn_id": tid})
    [rec], [row] = ui.records, ui.rows
    assert rec["status"] == M.STATUS_CANCELLED and not rec["complete"]
    assert (row["execution_status"], row["answer"], row["turn_id"]) == ("CANCELLED", None, tid)
    assert ui.H.store.answer_for(cid, tid)["status"] == "cancelled"


def test_a_complete_answer_that_was_not_delivered_is_not_recorded_as_answered(tmp_path):
    session = UISession(tmp_path, RUN, log=lambda m: None)
    turn = session.turn(CLEAN_Q, endpoint="/api/ask/stream")
    turn.answered(answer_one(*CASES[0]), evaluation=None, review=None)
    turn.finish(NOT_DELIVERED)
    turn.finish(DELIVERED)                                       # written once: the first outcome stands
    [rec] = [json.loads(l) for l in (session.dir / M.MEASUREMENT_FILE).read_text().splitlines()]
    assert rec["status"] == M.STATUS_CANCELLED and "not delivered" in rec["error"]


def test_a_replayed_turn_is_not_recorded_twice_and_a_retry_is_a_new_attempt(ui):
    cid, tid = ui.conversation(), str(uuid.uuid4())
    ui.H.engine.raise_in_generation = RuntimeError("first attempt fails")
    assert ui.stream(CLEAN_Q, cid, tid)["type"] == "error"
    ui.H.engine.raise_in_generation = None
    first = ui.stream(CLEAN_Q, cid, tid)                         # retried: answered
    replay = ui.stream(CLEAN_Q, cid, tid)                        # answered already: replayed from history
    assert replay["result"]["conversation"]["replayed"] is True and replay["result"]["answer"] == first["result"]["answer"]
    recs = ui.records
    assert [r["status"] for r in recs] == [M.STATUS_PIPELINE_ERROR, M.STATUS_CAPTURED]
    assert {r["origin"]["turn_id"] for r in recs} == {tid} and recs[0]["question_id"] != recs[1]["question_id"]


def test_ids_are_unique_and_ordinals_follow_the_session(ui):
    ui.ask(CLEAN_Q)
    ui.stream(MISSING_Q)
    ui.stream(REPAIR_Q, ui.conversation(), str(uuid.uuid4()))
    ui.ask(OFFSCOPE_Q)
    recs, rows = ui.records, ui.rows
    assert [r["ordinal"] for r in recs] == [r["ordinal"] for r in rows] == [1, 2, 3, 4]
    assert len({r["question_id"] for r in recs}) == 4
    assert [r["question_id"] for r in recs] == [r["question_id"] for r in rows]
    assert all(M.verify_record(r) == [] for r in recs)          # the ordinal is covered by the hash
    loaded = M.load_run(ui.H.measure.dir)
    assert loaded["problems"] == [] and all(r["verified"] for r in loaded["rows"])


# ------------------------------------------------------------------ opt-out


def test_without_measurement_nothing_is_written_and_the_response_is_the_same(ui, tmp_path):
    measured = ui.stream(CLEAN_Q)["result"]
    session_dir = ui.H.measure.dir
    before = sorted(p.name for p in session_dir.iterdir())
    rows_before = (session_dir / "answers.jsonl").read_bytes()
    ui.H.measure = None                                          # --no-measure
    plain = ui.stream(CLEAN_Q)["result"]
    _, plain_ask = ui.ask(CLEAN_Q)
    assert comparable(plain) == comparable(measured) and plain["accuracy"]["question_review"] == \
        measured["accuracy"]["question_review"]
    assert plain_ask["answer"] == measured["answer"]
    time.sleep(0.2)                                              # nothing late either
    assert sorted(p.name for p in session_dir.iterdir()) == before
    assert (session_dir / "answers.jsonl").read_bytes() == rows_before


def test_the_session_is_closed_with_a_finish_time(tmp_path):
    session = UISession(tmp_path, RUN, log=lambda m: None)
    meta = json.loads((session.dir / SESSION_FILE).read_text())
    assert meta["finished_utc"] is None and meta["run"]["run_id"] == session.session_id
    session.close()
    assert json.loads((session.dir / SESSION_FILE).read_text())["finished_utc"] is not None


def test_the_session_identity_carries_no_secret_and_is_json(monkeypatch):
    monkeypatch.setenv("REGULUS_DATABASE_URL", "postgresql://user:SECRET-PASSWORD@host/db")
    run = UI.measurement_run(load_settings(), engine())
    text = json.dumps(run)
    assert "SECRET-PASSWORD" not in text and "postgresql://" not in text
    assert run["evaluator"]["accuracy_enabled"] is True and run["code_revision"]["git_commit"]


def test_acceptance_records_keep_their_shape():
    rec = M.build_record(question_id="Q-1", ordinal=1, question=CLEAN_Q, out=answer_one(*CASES[0]),
                         run={"run_id": "r"}, captured_utc="2026-01-01T00:00:00+00:00")
    assert "origin" not in rec and rec["evaluation"]["reason"] == M.NOT_RUN_BY_RUNNER


# ------------------------------------------------------------------ offline evaluation of a session


def test_a_session_is_evaluated_offline_through_the_existing_evaluator(ui, tmp_path):
    ui.ask(CLEAN_Q)
    ui.stream(REPAIR_Q)
    ui.stream(MISSING_Q)
    ui.H.engine.raise_in_generation = RuntimeError("boom")
    ui.ask(CLEAN_Q)                                              # an error row: refused, not evaluated
    session_dir = ui.H.measure.dir
    files = {n: (session_dir / n).read_bytes() for n in ("answers.jsonl", M.MEASUREMENT_FILE)}
    first = evaluate_ui_session(session_dir, root=PROJECT_ROOT)
    second = evaluate_ui_session(session_dir, root=PROJECT_ROOT)
    assert first["output"] != second["output"] and Path(first["output"]).is_file()      # never overwritten
    assert Path(first["output"]).parent == session_dir / "evaluations"
    assert not any(p.name.startswith(".snapshot") for p in (session_dir / "evaluations").iterdir())
    assert {n: (session_dir / n).read_bytes() for n in files} == files and first["session_files_only_appended"]
    results = [json.loads(l)["result"] for l in Path(first["output"]).read_text().splitlines()]
    assert [r["outcome"] for r in results] == [O.EVALUATED] * 3 + [O.NOT_EVALUABLE]
    assert "pipeline_error" in results[3]["reason"]
    assert all(r["run_id"] == session_dir.name for r in results)
    # the live assessment the user saw, against the offline one: lexical both, index probe aside
    assert first["live_vs_offline"]["compared"] == 3
    assert first["live_vs_offline"]["same_review_status"] + len(first["live_vs_offline"]["different"]) == 3


def test_a_session_still_being_written_is_evaluated_as_a_snapshot(ui):
    ui.ask(CLEAN_Q)
    session_dir = ui.H.measure.dir
    summary = evaluate_ui_session(session_dir, root=PROJECT_ROOT)
    ui.ask(MISSING_Q)                                            # appended after the snapshot
    assert summary["rows_in_snapshot"] == 1 and summary["session_finished"] is False
    later = evaluate_ui_session(session_dir, root=PROJECT_ROOT)
    assert later["rows_in_snapshot"] == 2 and later["session_files_only_appended"]


@pytest.mark.parametrize("tamper,why", [
    (lambda r: r["validation"].update(initial=None), "no initial report"),
    (lambda r: r["evidence"].update(snapshot=None, provenance=M.MISSING), "no exact evidence"),
    (lambda r: r.pop("evaluator_inputs"), "predates evaluator-input capture"),
])
def test_missing_or_malformed_session_records_are_refused(ui, tamper, why):
    ui.stream(REPAIR_Q)
    path = ui.H.measure.dir / M.MEASUREMENT_FILE
    rec = json.loads(path.read_text())
    tamper(rec)
    rec["record_sha256"] = M.record_hash(rec)
    path.write_text(json.dumps(rec) + "\n")
    summary = evaluate_ui_session(ui.H.measure.dir, root=PROJECT_ROOT)
    [result] = [json.loads(l)["result"] for l in Path(summary["output"]).read_text().splitlines()]
    assert result["outcome"] == O.NOT_EVALUABLE and why in result["reason"] and result["review_status"] is None


def test_a_corrupted_line_is_reported_and_the_rest_evaluated(ui):
    ui.ask(CLEAN_Q)
    ui.ask(MISSING_Q)
    path = ui.H.measure.dir / M.MEASUREMENT_FILE
    lines = path.read_text().splitlines()
    path.write_text(lines[0][:-40] + "\n" + lines[1] + "\n")
    summary = evaluate_ui_session(ui.H.measure.dir, root=PROJECT_ROOT)
    results = [json.loads(l)["result"] for l in Path(summary["output"]).read_text().splitlines()]
    assert [r["outcome"] for r in results] == [O.NOT_EVALUABLE, O.EVALUATED]
    assert any("unreadable" in p for p in summary["problems"])


def test_an_acceptance_run_is_not_a_ui_session(tmp_path):
    archived = sorted((PROJECT_ROOT / "artifacts/acceptance_test").glob("acceptance_*"))[0]
    with pytest.raises(NotASession):
        evaluate_ui_session(archived, tmp_path / "x.jsonl", root=PROJECT_ROOT)
    assert not (tmp_path / "x.jsonl").exists() and not (archived / "evaluations").exists()
