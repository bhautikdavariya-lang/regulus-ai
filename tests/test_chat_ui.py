"""The answering page in chat mode (web/index.html), run under Node against a scripted server
(tests/chat_ui_harness.js): conversations start on the first question, survive a refresh, never
mix, retry a failed turn under the same turn id, and leave the plain console untouched when the
server has no history. Answer rendering itself is covered by test_streaming_ui / test_accuracy_ui."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from regulus.config import PROJECT_ROOT

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def page(scenario: str) -> dict:
    out = subprocess.run([NODE, str(PROJECT_ROOT / "tests" / "chat_ui_harness.js"), scenario],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_the_first_question_starts_a_conversation_and_follow_ups_stay_in_it():
    r = page("fresh")
    assert r["after_init"]["chat_enabled"] and "chat" in r["after_init"]["app_class"]
    assert r["after_init"]["posts"] == 0                          # no empty conversation on page load
    first, second = r["after_first"], r["after_second"]
    assert first["posts"] == 1 and second["posts"] == 1           # created once, on the first question
    a, b = second["streams"]
    assert a["conversation_id"] == b["conversation_id"] == first["active"] == first["remembered"]
    assert a["turn_id"] != b["turn_id"]
    assert first["q"] == "" and second["q"] == ""                 # the box is cleared once a question is sent
    t = second["thread"]
    assert t.index("820.10(b)(2) require?") < t.index("Validated answer 1") < t.index("(b)(4)?") < t.index("Validated answer 2")
    assert "Validated answer 2" in second["out"]                  # the evidence panel shows the latest answer


def test_a_refresh_reopens_the_remembered_conversation_with_its_failures_honest():
    r = page("restore")["after_init"]
    assert r["active"] == "conv-bbbb-2222"
    assert "Request failed: model crashed" in r["thread"]
    assert "No answer was recorded for this question." in r["thread"]
    assert r["thread"].count("data-retry=") == 2                  # both unanswered turns offer a retry
    assert r["out"] == ""                                         # no answer is shown where none was delivered


def test_switching_conversations_never_mixes_their_messages():
    r = page("switch")
    a, b = r["after_a"], r["after_b"]
    assert "Part 11" in a["thread"] and "Part 820" not in a["thread"]
    assert "Part 820" in b["thread"] and "Part 11 cover" not in b["thread"]
    assert "Validated answer A" not in b["out"]                   # the evidence panel follows the conversation
    assert a["remembered"] == "conv-aaaa-1111" and b["remembered"] == "conv-bbbb-2222"


def test_a_failed_turn_is_retried_under_the_same_turn_id():
    r = page("retry")
    failed, retried = r["after_error"], r["after_retry"]
    assert "Request failed: model crashed mid-generation" in failed["thread"] and "data-retry=" in failed["thread"]
    first, second = retried["streams"]
    assert first["turn_id"] == second["turn_id"] and first["question"] == second["question"]
    assert retried["thread"].count("820.10(b)(2) require?") == 1  # one question, not two
    assert "Validated answer 2" in retried["thread"] and "Request failed" not in retried["thread"]


def test_without_history_the_page_is_the_plain_console_and_sends_no_conversation_fields():
    r = page("nohistory")
    assert not r["after_first"]["chat_enabled"] and "chat" not in r["after_first"]["app_class"]
    (body,) = r["after_first"]["streams"]
    assert "conversation_id" not in body and "turn_id" not in body
    assert r["after_first"]["thread"] == "" and "Validated answer 1" in r["after_first"]["out"]


def test_a_second_send_while_one_is_in_flight_is_ignored():
    r = page("double")["after"]
    assert len(r["streams"]) == 1 and r["streams"][0]["question"] == "first"
    assert r["q"] == "second"                                     # the ignored text is not lost


# ------------------------------------------------------------- live answer streaming (Phase 1.2)


SETTINGS_FIELDS = ("adapter", "top_k", "max_new_tokens", "grounding", "model")


def test_the_bubble_shows_progress_and_never_the_draft_text():
    r = page("stream")
    pending = [s for s in r["snaps"] if s["pending_in_thread"]]
    assert len(pending) >= 3                                                    # one read at a time, while generating
    phases = [s["phase"] for s in r["snaps"] if s["phase"]]
    assert "Generating the answer…" in phases
    assert phases[-1] == "Checking the answer against the sources…"
    assert all("unexplained" not in s["visible"] and "investigated" not in s["visible"] for s in r["snaps"])  # no draft text, ever
    assert not r["snaps"][-1]["pending_in_thread"]                             # the progress bubble is gone at the end


def test_the_final_answer_is_the_only_answer_text_in_the_thread():
    after = page("stream")["after"]
    assert "Validated answer 1 [1]." in after["thread"]                        # the authoritative answer
    assert "thoroughly investigated." not in after["thread"] and "thoroughly investigated." not in after["out"]
    assert 'id="drafttext"' not in after["thread"]
    assert "21 CFR 820.10(b)(2)" in after["thread"] and "data-show=" in after["thread"]   # citations, evidence intact
    assert "Validated answer 1 [1]." in after["out"]                           # the evidence panel holds the final render


def test_a_failed_stream_shows_no_draft_and_its_retry_shows_none_either():
    r = page("stream_retry")
    assert "Request failed: model crashed mid-generation" in r["after_error"]["thread"]
    assert "OLD-DRAFT" not in r["after_error"]["thread"] and "OLD-DRAFT" not in r["after_error"]["out"]
    assert all("OLD-DRAFT" not in s["visible"] for s in r["first_snaps"] + r["retry_snaps"])
    assert all("NEW-DRAFT" not in s["visible"] for s in r["retry_snaps"])     # the retry's draft is not shown either
    first, second = r["after_retry"]["streams"]
    assert first["turn_id"] == second["turn_id"]                               # same turn: idempotent on the server
    assert "Validated answer 2 [1]." in r["after_retry"]["thread"]
    assert "DRAFT" not in r["after_retry"]["thread"]


def test_stop_mid_stream_shows_a_stopped_turn_and_no_partial_text():
    r = page("stream_stop")
    assert "Generating the answer…" in [s["phase"] for s in r["snaps"]]        # it was generating when stopped
    assert all("Partial" not in s["visible"] for s in r["snaps"])
    t = r["after"]["thread"]
    assert "Stopped before the answer was complete." in t and "data-retry=" in t
    assert "Partial draft words" not in t


@pytest.mark.parametrize("scenario, key", [("stream", "after"), ("nohistory", "after_first")])
def test_the_page_sends_no_model_or_tuning_fields(scenario, key):
    for body in page(scenario)[key]["streams"]:
        assert not set(SETTINGS_FIELDS) & set(body), body    # the server's own defaults apply


# ------------------------------------------------------------- no settings UI; Qwen3 is the configured default


def test_the_page_has_no_settings_or_model_controls():
    html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    # the application answers with Qwen3-1.7B MLX 4-bit only: there is no model to choose
    for gone in ('id="adapter"', 'id="topk"', 'id="tokens"', 'id="grounding"', 'class="settings', "<select",
                 'type="number"', '$("adapter")', '$("topk")', '$("tokens")', '$("grounding")', '$("model")'):
        assert gone not in html, gone
    assert ">Settings<" not in html and "Settings</summary>" not in html


def test_the_configured_default_model_is_qwen3_with_no_adapter():
    import yaml

    model = yaml.safe_load((PROJECT_ROOT / "configs" / "model.yaml").read_text(encoding="utf-8"))["model"]
    assert model["id"].startswith("Qwen/Qwen3-")
    assert not model.get("adapter")                          # no fine-tuned adapter merged by default
