"""Streaming (performance Stage 1): draft text streamed during the single
generation, the validated answer delivered as the final event.

Three levels, no model weights:
* the streamer on the real Qwen tokenizer (skipped if it is not cached);
* the pipeline's `on_event` hook with scripted generators that call `on_text`
  the way the streamer does;
* the real `scripts/serve_ui.py` HTTP handler on a local port, with the
  pipeline behind a stand-in engine, read as a client would read it.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from regulus.config import PROJECT_ROOT
from regulus.inference.types import GenerationResult
from regulus.rag import RagConfig, RagPipeline
from regulus.rag.generation import UNVALIDATED_GENERAL
from regulus.retrieval import LexicalRetriever
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase

QUESTION = "What does 21 CFR 820.10(b)(2) require?"
GOOD = "21 CFR 820.10(b)(2) requires what its body text sets out, as the source states [1]."  # the fixture text is "820.10(b)(2) body text"


class StreamingGenerator(ScriptedGenerator):
    """Calls on_text word by word, like TextCallbackStreamer; can fail or be slow."""

    def __init__(self, response, *, fail_after=None, delay=0.0, **kw):
        super().__init__(response, **kw)
        self.fail_after, self.delay = fail_after, delay
        self.emitted = 0

    def generate(self, messages, max_new_tokens=None, on_text=None):
        self.calls.append({"messages": messages, "max_new_tokens": max_new_tokens, "streamed": on_text is not None})
        words = self.response.split(" ")
        for n, word in enumerate(words):
            if self.fail_after is not None and n == self.fail_after:
                raise RuntimeError("model crashed mid-generation")
            if on_text is not None:
                on_text(word + (" " if n < len(words) - 1 else ""))
                self.emitted += 1
            if self.delay:
                time.sleep(self.delay)
        return GenerationResult("p", self.response, 500, self.tokens, 1.0, finished=self.finished)


def pipeline(generator, db=None):
    return RagPipeline(LexicalRetriever(db or TableDatabase()), generator, RagConfig())


def run(generator, question=QUESTION):
    events = []
    out = pipeline(generator).answer(question, on_event=lambda kind, data: events.append((kind, data)))
    return out, events


# ------------------------------------------------------------ the streamer


@pytest.fixture(scope="module")
def tokenizer(settings):
    from regulus.model import load_tokenizer

    try:
        return load_tokenizer(settings.model, local_files_only=True)
    except Exception as exc:  # pragma: no cover - depends on the local cache
        pytest.skip(f"Qwen tokenizer not cached: {exc}")


def test_streamer_emits_word_chunks_that_add_up_to_the_decoded_text(tokenizer):
    import torch

    from regulus.inference.streaming import TextCallbackStreamer

    text = "21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [1].\nSecond line."
    ids = tokenizer(text, add_special_tokens=False)["input_ids"]
    chunks: list[str] = []
    s = TextCallbackStreamer(tokenizer, chunks.append)
    s.put(torch.tensor([[1, 2, 3]]))           # the prompt: skipped
    for i in ids:
        s.put(torch.tensor([i]))
    s.end()
    assert len(chunks) > 5 and s.chunks == len(chunks)
    assert "".join(chunks) == tokenizer.decode(ids, skip_special_tokens=True)


def test_a_failing_callback_stops_the_streamer(tokenizer):
    import torch

    from regulus.inference.streaming import TextCallbackStreamer

    def gone(_text):
        raise ConnectionResetError("client went away")

    s = TextCallbackStreamer(tokenizer, gone)
    s.put(torch.tensor([[1]]))
    with pytest.raises(ConnectionResetError):
        for i in tokenizer("one two three four", add_special_tokens=False)["input_ids"]:
            s.put(torch.tensor([i]))


# ------------------------------------------------------------ the pipeline


def test_1_2_3_a_normal_answer_streams_in_several_chunks_and_completes():
    out, events = run(StreamingGenerator(GOOD))
    kinds = [k for k, _ in events]
    assert kinds[0] == "context" and kinds[1] == "generation_started" and kinds[-1] == "generation_finished"
    deltas = [d["text"] for k, d in events if k == "delta"]
    assert len(deltas) > 3                                   # multiple chunks
    assert "".join(deltas) == GOOD                           # the draft is the generated text
    assert events[0][1]["sources"][0]["citation"] == "21 CFR 820.10(b)(2)"
    assert out.answer == GOOD and out.model_called


def test_7_final_validation_still_runs_and_may_change_the_draft():
    # an invalid marker [9] is streamed as generated; the final answer is repaired
    bad = "21 CFR 820.10(b)(2) requires what its body text sets out, as the source states [9]."
    out, events = run(StreamingGenerator(bad))
    draft = "".join(d["text"] for k, d in events if k == "delta")
    assert "[9]" in draft
    assert "[9]" not in out.answer                           # repair ran on the complete text
    v = out.metadata["validation"]
    assert v["initial"]["status"] == "citation_invalid" and v["repair"] == "invalid_citations_removed"


def test_8_streaming_changes_nothing_in_the_final_answer_citations_or_validation():
    streamed, _ = run(StreamingGenerator(GOOD))
    plain = pipeline(ScriptedGenerator(GOOD)).answer(QUESTION)
    assert streamed.answer == plain.answer
    assert [c.to_dict() for c in streamed.citations] == [c.to_dict() for c in plain.citations]
    assert streamed.metadata["validation"] == plain.metadata["validation"]
    assert streamed.metadata["generation"]["sources"] == plain.metadata["generation"]["sources"]


def test_9_without_a_listener_the_generator_is_called_exactly_as_before():
    g = StreamingGenerator(GOOD)
    pipeline(g).answer(QUESTION)
    assert g.calls[0]["streamed"] is False and g.emitted == 0
    plain = ScriptedGenerator(GOOD)                         # generators without on_text still work with a listener
    out = pipeline(plain).answer(QUESTION, on_event=lambda *a: None)
    assert out.answer == GOOD


def test_4_a_generation_error_propagates_after_the_draft_so_far():
    events = []
    with pytest.raises(RuntimeError, match="crashed"):
        pipeline(StreamingGenerator(GOOD, fail_after=3)).answer(QUESTION, on_event=lambda k, d: events.append(k))
    assert events.count("delta") == 3 and "generation_finished" not in events


def test_5_an_empty_answer_streams_nothing_and_is_replaced_as_before():
    out, events = run(StreamingGenerator(""))
    assert [d for k, d in events if k == "delta" and d["text"]] == []
    assert out.metadata["validation"]["initial"]["status"] == "empty"
    assert out.answer.startswith(UNVALIDATED_GENERAL.split(".")[0])


def test_6_a_listener_that_raises_cancels_generation():
    class Gone(Exception):
        pass

    g = StreamingGenerator(" ".join(["word"] * 200))
    seen = []

    def listener(kind, data):
        if kind == "delta":
            seen.append(data)
            if len(seen) == 2:
                raise Gone()

    with pytest.raises(Gone):
        pipeline(g).answer(QUESTION, on_event=listener)
    assert g.emitted == 1  # the second on_text raised: nothing after it was generated


def test_no_model_call_means_no_generation_events():
    events = []
    out = pipeline(StreamingGenerator(GOOD)).answer("What does 21 CFR 820.999 require?",
                                                     on_event=lambda k, d: events.append(k))
    assert not out.model_called and events == ["context"]


# ------------------------------------------------------------ the HTTP endpoint


def _serve_ui():
    spec = importlib.util.spec_from_file_location("serve_ui_under_test", PROJECT_ROOT / "scripts" / "serve_ui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StandInEngine:
    """Engine.ask's contract (question, **options, on_event) -> result dict, over the real pipeline."""

    def __init__(self, generator):
        self.generator = generator

    def ask(self, question, *, adapter="", grounding=False, top_k=8, max_new_tokens=None, on_event=None):
        out = pipeline(self.generator).answer(question, on_event=on_event)
        return {"question": out.question, "answer": out.answer, "citations": [c.to_dict() for c in out.citations],
                "validation": out.metadata.get("validation"), "server_timings_ms": {}}


@pytest.fixture
def server():
    ui = _serve_ui()
    started = []

    def start(engine):
        handler = type("H", (ui.Handler,), {"engine": engine, "log_message": lambda *a: None})
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


def post(base, path, payload):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=10)


def stream_events(base, question=QUESTION):
    with post(base, "/api/ask/stream", {"question": question}) as res:
        assert res.status == 200 and res.headers["Content-Type"].startswith("application/x-ndjson")
        assert res.headers.get("Content-Length") is None
        return [json.loads(line) for line in res.read().decode("utf-8").splitlines() if line.strip()]


def test_http_stream_delivers_start_context_deltas_and_one_final_event(server):
    base = server(StandInEngine(StreamingGenerator(GOOD)))
    events = stream_events(base)
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "final" and types.count("final") == 1 and "error" not in types
    assert types.count("delta") > 3 and types.index("context") < types.index("delta")
    final = events[-1]["result"]
    assert final["answer"] == GOOD and final["citations"][0]["label"] == "21 CFR 820.10(b)(2)"
    stats = final["stream"]
    assert stats["deltas"] == types.count("delta") and stats["first_delta_ms"] <= stats["final_ms"]


def test_http_final_event_equals_the_non_streaming_response(server):
    base = server(StandInEngine(StreamingGenerator(GOOD)))
    with post(base, "/api/ask", {"question": QUESTION}) as res:
        plain = json.loads(res.read())
    final = stream_events(base)[-1]["result"]
    for key in ("answer", "citations", "validation"):
        assert final[key] == plain[key]


def test_http_generation_error_ends_the_stream_with_an_error_event(server):
    base = server(StandInEngine(StreamingGenerator(GOOD, fail_after=2)))
    events = stream_events(base)
    assert events[-1]["type"] == "error" and "final" not in [e["type"] for e in events]
    assert "crashed" in events[-1]["error"] and [e["type"] for e in events].count("delta") == 2


def test_http_empty_question_is_rejected_before_streaming(server):
    base = server(StandInEngine(StreamingGenerator(GOOD)))
    with pytest.raises(urllib.error.HTTPError) as err:
        post(base, "/api/ask/stream", {"question": "  "})
    assert err.value.code == 400


def test_http_client_disconnect_stops_generation_and_frees_the_server(server):
    g = StreamingGenerator(" ".join(["word"] * 400), delay=0.01)   # about 4 s if it ran to the end
    base = server(StandInEngine(g))
    host, port = base.rsplit(":", 1)[0].split("//")[1], int(base.rsplit(":", 1)[1])
    body = json.dumps({"question": QUESTION}).encode()
    s = socket.create_connection((host, port))
    s.sendall(b"POST /api/ask/stream HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
              + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    received = b""
    while b'"delta"' not in received:
        received += s.recv(4096)
    s.close()                                                    # the reader goes away mid-answer
    deadline = time.time() + 5
    while g.emitted < 400 and time.time() < deadline:
        before = g.emitted
        time.sleep(0.2)
        if g.emitted == before:
            break
    assert g.emitted < 400                                       # generation stopped early
    # and the lock was released: the next request is served normally
    ok = server(StandInEngine(StreamingGenerator(GOOD)))
    assert stream_events(ok)[-1]["type"] == "final"
