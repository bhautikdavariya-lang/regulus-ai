"""The UI against a remote GPU inference server (OpenAI-compatible), and the server's exposure safeguards.

A fake OpenAI-compatible server on loopback stands in for the GPU host (no model, no GPU). Pinned: in remote
mode the UI loads no tokenizer and no weights; answers are generated remotely and recorded with the backend
and a hashed endpoint; connection failures, timeouts, HTTP errors and malformed responses become categorised
inference failures recorded as pipeline_error, with neither the endpoint URL nor the API key in the page's
error, the logs, the chat history or the measurement files; local mode is unchanged; the acceptance runner's
load_generator is untouched; and a non-loopback bind is refused unless explicitly acknowledged.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
import urllib.request
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

import regulus.model as MODEL
from regulus.accuracy.alignment import LexicalAligner
from regulus.config import PROJECT_ROOT, load_settings
from regulus.conversations import ConversationStore
from regulus.evaluation import offline_evaluation as O
from regulus.evaluation.ui_sessions import evaluate_ui_session
from regulus.rag import RagPipeline
from regulus.rag.remote_generator import (GuardedRemoteGenerator, InferenceError, OpenAICompatibleGenerator,
                                          load_generator)
from regulus.retrieval import LexicalRetriever
from regulus.traceability import measurement as M
from regulus.traceability.ui_session import UISession
from tests.test_accuracy_evaluation import TABLE
from tests.test_accuracy_observer import CASES
from tests.test_retrieval_plan import TableDatabase

_spec = importlib.util.spec_from_file_location("serve_ui_remote_test", PROJECT_ROOT / "scripts" / "serve_ui.py")
UI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UI)

API_KEY = "sk-test-SECRET-9c1e"
CLEAN_Q, MISSING_Q = CASES[0][0], CASES[3][0]
RESPONSES = {CLEAN_Q: CASES[0][1]}


class FakeGPU:
    """An OpenAI-compatible chat-completions server. `mode`: ok | slow | bad_json | empty | http_500."""

    def __init__(self):
        self.mode, self.auth, self.calls = "ok", [], 0
        gpu = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "Qwen/Qwen3-0.6B", "root": "Qwen/Qwen3-0.6B"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                gpu.calls += 1
                gpu.auth.append(self.headers.get("Authorization"))
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompt = req["messages"][-1]["content"]
                text = next((r for q, r in RESPONSES.items() if q in prompt), "")
                if gpu.mode == "slow":
                    time.sleep(2)
                if gpu.mode == "http_500":
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error": "CUDA out of memory at /srv/gpu/secret-path"}')
                    return
                if req.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for piece in (text[: len(text) // 2], text[len(text) // 2:]):
                        self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n".encode())
                    self.wfile.write(b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
                                     b'"usage": {"prompt_tokens": 50, "completion_tokens": 20}}\n\ndata: [DONE]\n\n')
                    return
                if gpu.mode == "bad_json":
                    body = b"<html>gateway error</html>"
                elif gpu.mode == "empty":
                    body = b"{}"
                else:
                    body = json.dumps({"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                       "usage": {"prompt_tokens": 50, "completion_tokens": 20}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def gpu(monkeypatch):
    monkeypatch.setenv("REGULUS_MODEL_API_KEY", API_KEY)
    g = FakeGPU()
    yield g
    g.close()


def remote_settings(endpoint):
    s = load_settings()
    s.model = replace(s.model, backend="openai_compatible", endpoint=endpoint, adapter=None)
    s.model.validate()
    return s


def remote_engine(endpoint, monkeypatch, *, timeout=None):
    def forbidden(*a, **k):
        raise AssertionError("remote mode loaded local model files")

    monkeypatch.setattr(MODEL, "load_model", forbidden)
    monkeypatch.setattr(MODEL, "load_tokenizer", forbidden)
    e = object.__new__(UI.Engine)
    e.settings = remote_settings(endpoint)
    UI.Engine._init_inference(e, offline=True, inference_timeout=timeout)
    e.db, e.snapshot = None, "2026-01-01"
    e._models, e._adapter_info = {}, {"": {}}
    e._retrieval = (LexicalRetriever(TableDatabase(TABLE)), None)
    e.accuracy, e.accuracy_alignment, e._aligner = True, "lexical", LexicalAligner()
    e._identifier_index = SimpleNamespace(section_status=lambda s: (True, True), part_status=lambda p: (True, True))
    e.answer_shape = None
    return e


def guarded(endpoint, timeout=600.0):
    return GuardedRemoteGenerator(OpenAICompatibleGenerator(endpoint, "Qwen/Qwen3-0.6B", timeout=timeout))


MESSAGES = [{"role": "user", "content": f"QUESTION: {CLEAN_Q}"}]


# ------------------------------------------------------------------ the guarded remote generator


def test_remote_generation_succeeds_and_sends_the_key_only_as_a_header(gpu):
    result = guarded(gpu.endpoint).generate(MESSAGES, max_new_tokens=64)
    assert result.response == CASES[0][1].strip() and result.finished is True and result.generated_tokens == 20
    assert gpu.auth == [f"Bearer {API_KEY}"]


def test_remote_streaming_reports_each_delta(gpu):
    seen = []
    result = guarded(gpu.endpoint).generate(MESSAGES, max_new_tokens=64, on_text=seen.append)
    assert "".join(seen).strip() == result.response and len(seen) == 2 and result.finished is True


@pytest.mark.parametrize("mode,category", [("bad_json", "invalid_response"), ("empty", "invalid_response"),
                                           ("http_500", "http_status")])
def test_remote_failures_are_categorised_and_redacted(gpu, mode, category):
    gpu.mode = mode
    with pytest.raises(InferenceError) as info:
        guarded(gpu.endpoint).generate(MESSAGES)
    message = str(info.value)
    assert info.value.category == category and "127.0.0.1" not in message and "secret-path" not in message
    # the original exception (with its URL and server text) is never chained into a traceback
    assert info.value.__context__ is None or info.value.__suppress_context__


def test_a_connection_failure_is_categorised(gpu):
    endpoint = gpu.endpoint
    gpu.close()
    with pytest.raises(InferenceError) as info:
        guarded(endpoint).generate(MESSAGES)
    assert info.value.category == "connection" and "127.0.0.1" not in str(info.value)
    gpu.httpd = SimpleNamespace(shutdown=lambda: None, server_close=lambda: None)


def test_a_timeout_is_categorised(gpu):
    gpu.mode = "slow"
    with pytest.raises(InferenceError) as info:
        guarded(gpu.endpoint, timeout=0.3).generate(MESSAGES)
    assert info.value.category == "timeout"


def test_a_client_disconnect_passes_through_unchanged(gpu):
    class Gone(Exception):
        pass

    def on_text(_):
        raise Gone()

    g = GuardedRemoteGenerator(OpenAICompatibleGenerator(gpu.endpoint, "Qwen/Qwen3-0.6B"), passthrough=(Gone,))
    with pytest.raises(Gone):
        g.generate(MESSAGES, on_text=on_text)


def test_the_remote_identity_hashes_the_endpoint_and_never_holds_the_key(gpu):
    g = guarded(gpu.endpoint)
    text = json.dumps(g.describe())
    assert gpu.endpoint not in text and "127.0.0.1" not in text and API_KEY not in text
    assert g.describe()["api_key_configured"] is True and g.describe()["model_revision"] is None
    assert g.served_models()["configured_id_served"] is True


def test_the_acceptance_runner_keeps_the_unguarded_generator(gpu):
    assert type(load_generator(remote_settings(gpu.endpoint))) is OpenAICompatibleGenerator


# ------------------------------------------------------------------ the engine in remote mode


def test_remote_mode_loads_no_local_model_and_refuses_local_adapters(gpu, monkeypatch, tmp_path):
    e = remote_engine(gpu.endpoint, monkeypatch)
    assert e.remote is not None and e.tokenizer is None and e.base_model is None
    assert e.available_adapters() == [{"id": "", "label": "Remote: Qwen/Qwen3-0.6B"}]
    with pytest.raises(ValueError):
        e.model_for("stage13_v1")
    s = remote_settings(gpu.endpoint)
    s.model = replace(s.model, adapter=tmp_path)
    e2 = object.__new__(UI.Engine)
    e2.settings = s
    with pytest.raises(SystemExit):
        UI.Engine._init_inference(e2, offline=True)


def test_local_mode_still_loads_the_configured_model(monkeypatch):
    calls = []
    fake = SimpleNamespace(device="cpu", dtype="torch.float32")
    monkeypatch.setattr(MODEL, "load_tokenizer", lambda cfg, local_files_only: calls.append("tokenizer") or object())
    monkeypatch.setattr(MODEL, "load_model", lambda cfg, local_files_only: calls.append("model") or fake)
    e = object.__new__(UI.Engine)
    s = load_settings()
    s.model = replace(s.model, backend="transformers", adapter=None)
    e.settings = s
    UI.Engine._init_inference(e, offline=True)
    assert calls == ["tokenizer", "model"] and e.remote is None and e.base_model is fake


# ------------------------------------------------------------------ end to end through the UI


@pytest.fixture
def remote_ui(gpu, monkeypatch, tmp_path, capsys):
    logs = []
    eng = remote_engine(gpu.endpoint, monkeypatch, timeout=1.0)

    class H(UI.Handler):
        pass

    H.engine, H.store = eng, ConversationStore(tmp_path / "chat.sqlite3")
    H.measure = UISession(tmp_path / "ui_measurements", UI.measurement_run(eng.settings, eng), log=logs.append)
    monkeypatch.setattr(UI.Handler, "engine", eng)                  # safe_error reads the configured endpoint here
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield SimpleNamespace(base=f"http://127.0.0.1:{httpd.server_address[1]}", H=H, gpu=gpu, logs=logs,
                          tmp=tmp_path, capsys=capsys)
    httpd.shutdown()
    httpd.server_close()


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def wait_written(H, n):
    deadline = time.monotonic() + 10
    while H.measure.written + H.measure.write_failures < n and time.monotonic() < deadline:
        time.sleep(0.01)


def everything_written(ctx):
    files = "".join(p.read_text(errors="replace") for p in ctx.tmp.rglob("*") if p.is_file() and p.suffix != ".sqlite3")
    chat = (ctx.tmp / "chat.sqlite3").read_bytes().decode("latin-1")
    return files + chat + "\n".join(ctx.logs) + ctx.capsys.readouterr().out


def test_a_remote_answer_is_delivered_and_recorded_with_its_backend(remote_ui):
    cid = json.loads(post(remote_ui.base, "/api/conversations", {})[1])["conversation"]["id"]
    status, text = post(remote_ui.base, "/api/ask/stream", {"question": CLEAN_Q, "conversation_id": cid,
                                                            "turn_id": str(uuid.uuid4())})
    final = json.loads(text.splitlines()[-1])
    assert final["type"] == "final" and final["result"]["answer"] and remote_ui.gpu.calls == 1
    [rec] = [json.loads(l) for l in (remote_ui.H.measure.dir / M.MEASUREMENT_FILE).read_text().splitlines()]
    assert rec["status"] == M.STATUS_CAPTURED and M.verify_record(rec) == []
    assert rec["origin"]["live"]["inference_backend"] == "openai_compatible"
    assert rec["run"]["model"]["backend"] == "openai_compatible" and rec["run"]["model"]["model_revision"] is None
    assert rec["run"]["model"]["served_models"]["configured_id_served"] is True
    assert rec["run"]["database"]["snapshot_date"] == "2026-01-01"
    assert rec["origin"]["live"]["aligner_used"] == "lexical"
    assert isinstance(rec["origin"]["live"]["identifier_lookups"], list)
    written = everything_written(remote_ui)
    assert remote_ui.gpu.endpoint not in written and API_KEY not in written


@pytest.mark.parametrize("mode", ["down", "bad_json", "empty", "http_500", "slow"])
def test_a_remote_failure_is_an_error_record_with_nothing_secret_anywhere(remote_ui, mode):
    if mode == "down":
        remote_ui.gpu.httpd.shutdown()
        remote_ui.gpu.httpd.server_close()
        remote_ui.gpu.httpd = SimpleNamespace(shutdown=lambda: None, server_close=lambda: None)
    else:
        remote_ui.gpu.mode = mode
    status, text = post(remote_ui.base, "/api/ask", {"question": CLEAN_Q})
    wait_written(remote_ui.H, 1)
    assert status == 500 and "remote inference failed" in json.loads(text)["error"]
    [rec] = [json.loads(l) for l in (remote_ui.H.measure.dir / M.MEASUREMENT_FILE).read_text().splitlines()]
    assert rec["status"] == M.STATUS_PIPELINE_ERROR and not rec["complete"] and "remote inference failed" in rec["error"]
    written = everything_written(remote_ui) + text
    assert remote_ui.gpu.endpoint not in written and API_KEY not in written and "secret-path" not in written


def test_a_remote_session_is_evaluated_offline_without_model_or_database(remote_ui, monkeypatch):
    post(remote_ui.base, "/api/ask", {"question": CLEAN_Q})
    post(remote_ui.base, "/api/ask", {"question": MISSING_Q})
    wait_written(remote_ui.H, 2)
    remote_ui.gpu.close()                                           # the GPU server is gone
    remote_ui.gpu.httpd = SimpleNamespace(shutdown=lambda: None, server_close=lambda: None)

    def forbidden(*a, **k):
        raise AssertionError("offline evaluation reached inference")

    monkeypatch.setattr(RagPipeline, "answer", forbidden)
    monkeypatch.setattr(GuardedRemoteGenerator, "generate", forbidden)
    summary = evaluate_ui_session(remote_ui.H.measure.dir, root=PROJECT_ROOT)
    outcomes = [json.loads(l)["result"]["outcome"] for l in Path(summary["output"]).read_text().splitlines()]
    assert outcomes == [O.EVALUATED, O.EVALUATED] and summary["session_state"] == "running"


def test_config_reports_the_backend_and_measurement_health(remote_ui):
    with urllib.request.urlopen(remote_ui.base + "/api/config", timeout=10) as r:
        cfg = json.loads(r.read())
    assert cfg["inference_backend"] == "openai_compatible" and cfg["device"] == "remote"
    assert cfg["measurement"]["enabled"] is True and cfg["measurement"]["state"] == "open"
    assert remote_ui.gpu.endpoint not in json.dumps(cfg) and API_KEY not in json.dumps(cfg)


# ------------------------------------------------------------------ exposure


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_binds_need_no_acknowledgement(host):
    UI.check_bind(host, allow_remote_clients=False)


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "::", "regulus.example"])
def test_a_non_loopback_bind_is_refused_unless_acknowledged(host, capsys):
    with pytest.raises(SystemExit) as info:
        UI.check_bind(host, allow_remote_clients=False)
    assert "no authentication" in str(info.value)
    UI.check_bind(host, allow_remote_clients=True)
    assert "WARNING" in capsys.readouterr().out
