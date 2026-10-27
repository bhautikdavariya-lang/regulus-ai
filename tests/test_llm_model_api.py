"""llm-model API (regulus.api.llm_model, 27 Oct 2026): a real HTTP server on a free port, with a fake engine."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from regulus.api import llm_model as L

SECRET = "s" * 32
RELEASE = {"revision": "abc1234", "switches": ["A1"]}


class FakeDb:
    def __init__(self):
        self.down = False

    def query(self, sql, params=None):
        if self.down:
            raise ConnectionError("db down")
        return [{"ok": 1}]


class FakeEngine:
    snapshot = "2026-10-20"

    def __init__(self):
        self.db = FakeDb()
        self.calls = []

    def model_identity(self):
        return {"model_id": "Qwen/Qwen3-4B-Instruct-2507", "model_revision": "50d4277", "dtype": "4bit", "backend": "mlx"}

    def ask(self, question, *, context=None, focus=None, on_event=None):
        self.calls.append((question, context, focus))
        if on_event is not None:
            on_event("delta", {"text": "DRAFT TEXT"})
        fb = {"out of scope?": "out_of_scope", "withheld?": "unvalidated_answer_withheld",
              "removed?": "composed_qmsr"}.get(question)
        answer = ("21 CFR 820.30 (\"Design controls\") is not in the current eCFR: it belonged to the former Quality System "
                  "regulation" if fb == "composed_qmsr" else "Answer text [1].")
        return {"answer": answer, "fallback_type": fb, "snapshot_date": self.snapshot, "focus": focus,
                "citations": [{"index": 1, "label": "21 CFR 70.3(f)", "url": "https://ecfr.gov", "corpus": "ecfr",
                               "cited_in_answer": True}],
                "followup": {"anchor": {"cfr": ["70.3"], "statute": [], "parts": []}},
                "accuracy": {"question_review": {"status": "PASS", "score": 92}},
                "model": {"id": "qwen3-4b-2507", "label": "Qwen3-4B", "model_revision": "50d4277"},
                "server_timings_ms": {"pipeline_answer_ms": 10.0}, "raw_model_output": "DRAFT TEXT"}


@pytest.fixture
def api():
    engine = FakeEngine()
    config = L.ApiConfig(keys=(("backend", SECRET),), rate_per_min=5)
    service = L.Service(engine, config, RELEASE, log=lambda *_: None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), L.make_handler(service))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    def call(method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        h = {"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json", **(headers or {})}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, L.PREFIX + path, body=data, headers={k: v for k, v in h.items() if v is not None})
        r = conn.getresponse()
        text = r.read().decode()
        conn.close()
        return r.status, dict(r.getheaders()), text

    yield call, engine, service
    server.shutdown()
    server.server_close()


def test_health_is_public_and_info_needs_a_key(api):
    call, _, _ = api
    assert call("GET", "/health", headers={"Authorization": None})[0] == 200
    status, headers, _ = call("GET", "/info", headers={"Authorization": None})
    assert status == 401 and "Bearer" in headers.get("WWW-Authenticate", "")
    status, _, text = call("GET", "/info")
    assert status == 200 and json.loads(text)["release"] == RELEASE


def test_ready_reports_the_database(api):
    call, engine, _ = api
    assert call("GET", "/ready")[0] == 200
    engine.db.down = True
    assert call("GET", "/ready")[0] == 503


def test_an_answer_carries_state_citations_and_anchor_but_no_draft(api):
    call, engine, _ = api
    status, headers, text = call("POST", "/answer", {"question": "Is mica a color additive?", "focus": "cosmetics"})
    body = json.loads(text)
    assert status == 200 and body["state"] == "VERIFIED" and body["answer"] == "Answer text [1]."
    assert body["citations"][0] == {"index": 1, "label": "21 CFR 70.3(f)", "url": "https://ecfr.gov", "corpus": "ecfr",
                                    "citedInAnswer": True}
    assert body["conversation"]["anchor"]["cfr"] == ["70.3"] and body["evaluation"] == {"status": "PASS", "score": 92}
    assert "DRAFT" not in text and headers.get("X-Request-Id")
    assert engine.calls[-1] == ("Is mica a color additive?", None, "cosmetics")


def test_a_follow_up_is_answered_with_its_earlier_turns(api):
    call, engine, _ = api
    turn = {"question": "Is mica a color additive?", "anchor": {"cfr": ["70.3"], "statute": [], "parts": []}}
    assert call("POST", "/answer", {"question": "Can we use it near the eye?", "conversation": [turn]})[0] == 200
    ctx = engine.calls[-1][1]
    assert ctx is not None and ctx.turns[0].question == "Is mica a color additive?" and ctx.turns[0].anchor.cfr == ("70.3",)


def test_schema_errors_name_every_field(api):
    call, _, _ = api
    status, _, text = call("POST", "/answer", {"question": "", "focus": "drugs", "extra": 1,
                                               "conversation": [{"question": "q", "anchor": {"cfr": ["'; drop"]}}]})
    body = json.loads(text)
    assert status == 422 and body["code"] == "validation_error"
    assert set(body["fieldErrors"]) == {"question", "focus", "extra", "conversation[0].anchor"}


def test_malformed_bodies(api):
    call, _, _ = api
    assert call("POST", "/answer", raw=b"{not json")[0] == 400
    assert call("POST", "/answer", {"question": "x"}, headers={"Content-Type": "text/plain"})[0] == 415
    assert call("POST", "/answer", raw=b"x" * (64 * 1024 + 1))[0] == 413
    assert call("POST", "/answer", {"question": "x"}, headers={"Authorization": "Bearer wrong"})[0] == 401
    assert call("POST", "/nowhere", {"question": "x"})[0] == 404


def test_states_and_out_of_scope_is_422(api):
    call, _, _ = api
    status, _, text = call("POST", "/answer", {"question": "out of scope?"})
    assert status == 422 and json.loads(text)["code"] == "out_of_scope" and json.loads(text)["state"] == "OUT_OF_SCOPE"
    assert json.loads(call("POST", "/answer", {"question": "withheld?"})[2])["state"] == "GATE_FAILURE"
    assert json.loads(call("POST", "/answer", {"question": "removed?"})[2])["state"] == "SECTION_REMOVED"


def test_idempotency_replays_and_refuses_a_different_body(api):
    call, engine, _ = api
    h = {"X-Idempotency-Key": "req-00000001"}
    first = call("POST", "/answer", {"question": "Is mica a color additive?"}, headers=h)
    again = call("POST", "/answer", {"question": "Is mica a color additive?"}, headers=h)
    assert first[0] == again[0] == 200 and again[1].get("Idempotent-Replayed") == "true" and len(engine.calls) == 1
    assert json.loads(first[2])["answer"] == json.loads(again[2])["answer"]
    assert call("POST", "/answer", {"question": "Something else?"}, headers=h)[0] == 409


def test_rate_limit_is_429_with_retry_after(api):
    call, _, _ = api
    codes = [call("POST", "/answer", {"question": f"Question {i}?"})[0] for i in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    status, headers, _ = call("POST", "/answer", {"question": "Question 7?"})
    assert status == 429 and int(headers["Retry-After"]) >= 1


def test_the_stream_sends_progress_without_text_then_the_final_answer(api):
    call, _, _ = api
    status, headers, text = call("POST", "/answer/stream", {"question": "Is mica a color additive?"})
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert status == 200 and headers["Content-Type"].startswith("application/x-ndjson")
    assert [e["type"] for e in events] == ["start", "progress", "final"]
    assert events[-1]["result"]["state"] == "VERIFIED" and "DRAFT" not in text


def test_keys_come_from_the_environment_and_are_required():
    with pytest.raises(ValueError):
        L.ApiConfig.from_env({})
    with pytest.raises(ValueError):
        L.ApiConfig.from_env({"LLM_MODEL_API_KEYS": "backend:short"})
    cfg = L.ApiConfig.from_env({"LLM_MODEL_API_KEYS": f"backend:{SECRET}, {'t' * 30}"})
    assert cfg.key_id(f"Bearer {SECRET}") == "backend" and cfg.key_id("Bearer " + "t" * 30).startswith("key-")
    assert cfg.key_id(SECRET) is None and cfg.key_id(None) is None
