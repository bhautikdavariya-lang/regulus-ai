"""Chat history in the answering server (scripts/serve_ui.py), end to end over HTTP.

The real Handler serves on a loopback port with a scripted engine (no model, no database) and a
conversation store in a temporary file. Pinned: a request without conversation fields takes the
path it always did; a conversation turn records its question first and its outcome last; a
retried turn replays its stored answer instead of generating - and storing - it again.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest

from regulus.config import PROJECT_ROOT
from regulus.conversations import ConversationStore

_spec = importlib.util.spec_from_file_location("serve_ui_chat_test", PROJECT_ROOT / "scripts" / "serve_ui.py")
UI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UI)


class ScriptedEngine:
    """Stands in for serve_ui.Engine.ask: emits stream events and returns a result, or fails."""

    def __init__(self):
        self.calls = 0
        self.fail: Exception | None = None

    def ask(self, question, *, on_event=None, **kwargs):
        self.calls += 1
        if on_event is not None:
            on_event("context", {"sources": [], "no_context": False})
            on_event("delta", {"text": "draft "})
        if self.fail is not None:
            raise self.fail
        return {"question": question, "answer": f"Answer to: {question} [1]", "model_called": True,
                "citations": [{"index": 1, "label": "21 CFR 820.10(b)(2)", "url": "https://example/1"}],
                "accuracy": {"question_review": {"status": "pass", "label": "PASS"}},
                "server_timings_ms": {}}


@pytest.fixture
def server(tmp_path):
    engine = ScriptedEngine()

    class H(UI.Handler):
        pass

    H.engine = engine
    H.store = ConversationStore(tmp_path / "chat.sqlite3")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", engine, H
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def stream(base, body):
    status, text = call(base, "/api/ask/stream", body)
    return status, [json.loads(line) for line in text.splitlines() if line.strip()] if status == 200 else json.loads(text)


def new_conversation(base):
    status, text = call(base, "/api/conversations", {})
    assert status == 201
    return json.loads(text)["conversation"]["id"]


def final_of(events):
    finals = [e for e in events if e["type"] == "final"]
    assert len(finals) == 1
    return finals[0]["result"]


# ------------------------------------------------------------- the ordinary path is unchanged


def test_a_request_without_a_conversation_is_answered_as_before_and_stores_nothing(server):
    base, engine, H = server
    status, events = stream(base, {"question": "What does 21 CFR 820.10(b)(2) require?"})
    assert status == 200 and [e["type"] for e in events] == ["start", "context", "progress", "final"]   # progress: never draft text
    assert "conversation" not in final_of(events)
    assert engine.calls == 1 and H.store.list_conversations() == []


def test_without_a_store_answering_still_works_and_history_says_unavailable(server):
    base, engine, H = server
    H.store = None
    status, events = stream(base, {"question": "q"})
    assert status == 200 and final_of(events)["answer"] == "Answer to: q [1]"
    assert call(base, "/api/conversations")[0] == 503
    assert stream(base, {"question": "q", "conversation_id": uuid.uuid4().hex, "turn_id": uuid.uuid4().hex})[0] == 503


# ------------------------------------------------------------- a conversation turn


def test_a_turn_is_answered_recorded_and_reloadable(server):
    base, engine, H = server
    cid, tid = new_conversation(base), uuid.uuid4().hex
    status, events = stream(base, {"question": "What does Part 11 cover?", "conversation_id": cid, "turn_id": tid})
    result = final_of(events)
    assert result["conversation"] == {"id": cid, "turn_id": tid, "saved": True}
    status, text = call(base, f"/api/conversations/{cid}")
    conv = json.loads(text)["conversation"]
    assert conv["title"] == "What does Part 11 cover?"
    assert [(m["role"], m["status"]) for m in conv["messages"]] == [("user", "ok"), ("assistant", "ok")]
    stored = conv["messages"][1]["result"]
    assert stored["citations"] == result["citations"] and stored["accuracy"] == result["accuracy"]


def test_a_retried_turn_replays_its_answer_and_stores_it_once(server):
    base, engine, H = server
    cid, tid = new_conversation(base), uuid.uuid4().hex
    body = {"question": "What does Part 11 cover?", "conversation_id": cid, "turn_id": tid}
    first = final_of(stream(base, body)[1])
    second = final_of(stream(base, body)[1])
    assert engine.calls == 1                                   # not generated again
    assert second["answer"] == first["answer"] and second["conversation"]["replayed"] is True
    assert len(H.store.get_conversation(cid)["messages"]) == 2


def test_a_failed_turn_is_recorded_as_failed_and_a_retry_replaces_it(server):
    base, engine, H = server
    cid, tid = new_conversation(base), uuid.uuid4().hex
    body = {"question": "q", "conversation_id": cid, "turn_id": tid}
    engine.fail = RuntimeError("model crashed")
    events = stream(base, body)[1]
    assert events[-1]["type"] == "error" and not [e for e in events if e["type"] == "final"]
    reply = H.store.get_conversation(cid)["messages"][1]
    assert reply["status"] == "error" and reply["result"] is None and reply["content"].startswith("Request failed")
    engine.fail = None
    assert final_of(stream(base, body)[1])["conversation"]["saved"] is True
    msgs = H.store.get_conversation(cid)["messages"]
    assert [(m["role"], m["status"]) for m in msgs] == [("user", "ok"), ("assistant", "ok")]


def test_a_stopped_turn_is_recorded_as_cancelled(server):
    base, engine, H = server
    cid, tid = new_conversation(base), uuid.uuid4().hex
    engine.fail = UI.ClientDisconnected()                     # what a closed browser connection raises
    call(base, "/api/ask/stream", {"question": "q", "conversation_id": cid, "turn_id": tid})
    assert H.store.answer_for(cid, tid)["status"] == "cancelled"


def test_two_conversations_stay_apart_over_http(server):
    base, engine, H = server
    c1, c2 = new_conversation(base), new_conversation(base)
    stream(base, {"question": "about part 11", "conversation_id": c1, "turn_id": uuid.uuid4().hex})
    stream(base, {"question": "about part 820", "conversation_id": c2, "turn_id": uuid.uuid4().hex})
    m1 = json.loads(call(base, f"/api/conversations/{c1}")[1])["conversation"]["messages"]
    m2 = json.loads(call(base, f"/api/conversations/{c2}")[1])["conversation"]["messages"]
    assert [m["content"] for m in m1 if m["role"] == "user"] == ["about part 11"]
    assert [m["content"] for m in m2 if m["role"] == "user"] == ["about part 820"]
    listed = json.loads(call(base, "/api/conversations")[1])["conversations"]
    assert [c["id"] for c in listed] == [c2, c1]


# ------------------------------------------------------------- refused before anything is generated


@pytest.mark.parametrize("body, code", [
    ({"question": "q", "conversation_id": uuid.uuid4().hex, "turn_id": uuid.uuid4().hex}, 404),   # no such conversation
    ({"question": "q", "conversation_id": "bad id!", "turn_id": uuid.uuid4().hex}, 400),
    ({"question": "q", "turn_id": uuid.uuid4().hex}, 400),                                        # turn without conversation
])
def test_an_invalid_turn_is_refused_without_generating(server, body, code):
    base, engine, H = server
    status, payload = stream(base, body)
    assert status == code and "error" in payload and engine.calls == 0


def test_an_oversized_question_in_a_conversation_is_refused(server):
    base, engine, H = server
    cid = new_conversation(base)
    status, payload = stream(base, {"question": "x" * 5000, "conversation_id": cid, "turn_id": uuid.uuid4().hex})
    assert status == 400 and engine.calls == 0 and H.store.get_conversation(cid)["messages"] == []


@pytest.mark.parametrize("path, code", [("/api/conversations/" + uuid.uuid4().hex, 404),
                                        ("/api/conversations/short", 400)])
def test_reading_a_missing_or_malformed_conversation(server, path, code):
    base, _, _ = server
    status, text = call(base, path)
    assert status == code and "error" in json.loads(text) and "Traceback" not in text


# ------------------------------------------------------------- deleting a conversation


def test_delete_removes_a_conversation_over_http(server):
    base, engine, H = server
    cid = new_conversation(base)
    stream(base, {"question": "What does Part 11 cover?", "conversation_id": cid, "turn_id": uuid.uuid4().hex})
    status, text = call(base, f"/api/conversations/{cid}", method="DELETE")
    assert status == 200 and json.loads(text) == {"deleted": cid, "messages_deleted": 2}
    assert call(base, f"/api/conversations/{cid}")[0] == 404
    listed = json.loads(call(base, "/api/conversations")[1])["conversations"]
    assert cid not in [c["id"] for c in listed]


@pytest.mark.parametrize("path, code", [("/api/conversations/" + uuid.uuid4().hex, 404),
                                        ("/api/conversations/short", 400),
                                        ("/api/conversations", 404),
                                        ("/api/conversations/bad%20id", 404),
                                        ("/api/evaluation/summary", 404)])
def test_deleting_a_missing_or_malformed_conversation(server, path, code):
    base, _, _ = server
    status, text = call(base, path, method="DELETE")
    assert status == code and "error" in json.loads(text) and "Traceback" not in text


def test_delete_without_a_store_is_unavailable(server):
    base, _, H = server
    H.store = None
    status, text = call(base, f"/api/conversations/{uuid.uuid4().hex}", method="DELETE")
    assert status == 503 and "unavailable" in json.loads(text)["error"]


def _raw(base, path, method="GET", headers=None, body=None):
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


def test_delete_has_no_cors_preflight_answer(server):
    base, _, H = server
    cid = new_conversation(base)
    # the base handler answers OPTIONS (and PUT) with 501: a response, not a dropped connection (log_message used to
    # raise a TypeError on send_error's HTTPStatus argument), and never a preflight grant
    for method in ("OPTIONS", "PUT"):
        status, headers, _ = _raw(base, f"/api/conversations/{cid}", method,
                                  {"Origin": "https://elsewhere.example", "Access-Control-Request-Method": "DELETE"})
        assert status == 501, method
        assert not [k for k in headers if k.lower().startswith("access-control-")], method
    # a DELETE from another site's page is refused before anything is deleted, and grants nothing either
    status, headers, text = _raw(base, f"/api/conversations/{cid}", "DELETE", {"Origin": "https://elsewhere.example"})
    assert status == 403 and json.loads(text)["error"] == "forbidden origin"
    assert headers.get("Access-Control-Allow-Origin") is None and headers.get("Access-Control-Allow-Methods") is None
    assert cid in [c["id"] for c in H.store.list_conversations()]


# ------------------------------------------------------------- DNS rebinding, cross-site requests, framing


def test_a_foreign_host_is_refused_on_every_route(server):
    """A page on evil.example whose DNS was re-pointed at 127.0.0.1 is same-origin to the browser, but its
    requests carry Host: evil.example: none of them reaches history or the model."""
    base, engine, H = server
    cid = new_conversation(base)
    port = base.rsplit(":", 1)[1]
    evil = {"Host": f"evil.example:{port}", "Origin": f"http://evil.example:{port}"}
    for method, path, body in (("GET", "/api/conversations", None), ("GET", "/api/evaluation/summary", None),
                               ("GET", f"/api/conversations/{cid}", None), ("GET", "/", None),
                               ("DELETE", f"/api/conversations/{cid}", None),
                               ("POST", "/api/conversations", b"{}"),
                               ("POST", "/api/ask/stream", json.dumps({"question": "q"}).encode())):
        status, _, text = _raw(base, path, method, {**evil, "Content-Type": "application/json"}, body)
        assert status == 403 and json.loads(text)["error"] == "forbidden host", (method, path)
    assert [c["id"] for c in H.store.list_conversations()] == [cid]      # nothing deleted, nothing created
    assert engine.calls == 0                                              # no answer was started


def test_a_cross_site_simple_post_is_refused(server):
    """A form or a text/plain fetch from another site needs no preflight; its Origin header gives it away."""
    base, engine, H = server
    for path, body in (("/api/conversations", b"{}"), ("/api/ask/stream", b'{"question": "q"}'),
                       ("/api/ask", b'{"question": "q"}')):
        status, _, text = _raw(base, path, "POST", {"Content-Type": "text/plain", "Origin": "http://evil.example"}, body)
        assert status == 403 and json.loads(text)["error"] == "forbidden origin", path
    status, _, _ = _raw(base, "/api/conversations", "POST", {"Origin": "null"}, b"{}")   # a sandboxed or file:// page
    assert status == 403
    assert H.store.list_conversations() == [] and engine.calls == 0


def test_the_page_itself_is_still_served_and_answered(server):
    """The page's own requests: loopback Host, and an Origin equal to it on POST and DELETE."""
    base, _, H = server
    port = base.rsplit(":", 1)[1]
    for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"):
        origin = f"http://{host}"
        status, _, text = _raw(base, "/api/conversations", "POST",
                               {"Host": host, "Origin": origin, "Content-Type": "application/json"}, b"{}")
        assert status == 201, host
        cid = json.loads(text)["conversation"]["id"]
        assert _raw(base, "/api/conversations", "GET", {"Host": host})[0] == 200
        assert _raw(base, f"/api/conversations/{cid}", "DELETE", {"Host": host, "Origin": origin})[0] == 200
    assert H.store.list_conversations() == []


def test_an_allowed_host_name_is_accepted(server):
    """--allowed-host: the name a reverse proxy forwards, with or without this server's port."""
    base, _, H = server
    port = base.rsplit(":", 1)[1]
    assert _raw(base, "/api/conversations", "GET", {"Host": "regulus.internal"})[0] == 403
    H.allowed_hosts = ("regulus.internal",)
    assert _raw(base, "/api/conversations", "GET", {"Host": "regulus.internal"})[0] == 200
    assert _raw(base, "/api/conversations", "GET", {"Host": f"regulus.internal:{port}"})[0] == 200
    status, _, _ = _raw(base, "/api/conversations", "POST",
                        {"Host": "regulus.internal", "Origin": "https://regulus.internal"}, b"{}")
    assert status == 201
    assert _raw(base, "/api/conversations", "GET", {"Host": "other.internal"})[0] == 403


def test_responses_forbid_framing(server):
    base, _, _ = server
    for path in ("/", "/api/conversations", "/api/nothing-here"):
        _, headers, _ = _raw(base, path)
        assert headers.get("X-Frame-Options") == "DENY", path
        assert headers.get("Content-Security-Policy") == "frame-ancestors 'none'", path
        assert headers.get("X-Content-Type-Options") == "nosniff", path
