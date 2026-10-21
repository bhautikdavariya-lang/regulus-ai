"""Remote GPU inference (OpenAI-compatible), the answering UI's refusal of it, and the server's exposure safeguards.

A fake OpenAI-compatible server on loopback stands in for the GPU host (no model, no GPU). Pinned: the remote
generator streams, and categorises connection failures, timeouts, HTTP errors and malformed responses without
the endpoint URL or the API key; the acceptance runner's load_generator is untouched; the answering UI, which
answers with Qwen3-1.7B MLX 4-bit only, refuses a remote backend at start-up without contacting it and has no
backend override; and a non-loopback bind is refused unless explicitly acknowledged.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

import regulus.model as MODEL
from regulus.config import PROJECT_ROOT, load_settings
from regulus.rag.remote_generator import (GuardedRemoteGenerator, InferenceError, OpenAICompatibleGenerator,
                                          load_generator)
from tests.test_accuracy_observer import CASES

_spec = importlib.util.spec_from_file_location("serve_ui_remote_test", PROJECT_ROOT / "scripts" / "serve_ui.py")
UI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UI)

API_KEY = "sk-test-SECRET-9c1e"
CLEAN_Q = CASES[0][0]
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


# ------------------------------------------------------------------ the answering UI refuses remote inference


def test_the_answering_ui_refuses_a_remote_backend_before_contacting_it(gpu, monkeypatch):
    """The application answers with Qwen3-1.7B MLX 4-bit only (tests/test_ui_model_selector.py). A remote server
    would answer with whatever model it serves, so start-up stops instead: nothing is loaded locally, nothing is
    sent to the server, and neither the endpoint nor the key is in the message."""
    def forbidden(*a, **k):
        raise AssertionError("a model was loaded although start-up was refused")

    monkeypatch.setattr(MODEL, "load_model", forbidden)
    monkeypatch.setattr(MODEL, "load_tokenizer", forbidden)
    e = object.__new__(UI.Engine)
    e.settings = remote_settings(gpu.endpoint)
    with pytest.raises(SystemExit, match="openai_compatible") as stop:
        UI.Engine._init_inference(e, offline=True)
    assert gpu.calls == 0 and gpu.endpoint not in str(stop.value) and API_KEY not in str(stop.value)


def test_the_ui_has_no_backend_override(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["serve_ui.py", "--backend", "openai_compatible"])
    with pytest.raises(SystemExit) as stop:
        UI.main()
    assert stop.value.code == 2 and "--backend" in capsys.readouterr().err


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
