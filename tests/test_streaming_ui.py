"""The answering page's stream reader (web/index.html), run under Node with a
scripted /api/ask/stream response split at awkward network boundaries."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from regulus.config import PROJECT_ROOT

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def page(scenario: str) -> dict:
    out = subprocess.run([NODE, str(PROJECT_ROOT / "tests" / "answer_ui_stream_harness.js"), scenario],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_draft_appears_while_generating_then_the_validated_answer_replaces_it():
    r = page("normal")
    assert r["draft_seen"]                                        # progressive text, labelled as a draft
    assert "Validated answer [1]." in r["final_out"]               # the final event is what is shown
    assert "Draft answer" not in r["final_out"] and "draft · generating" not in r["final_out"]
    assert "21 CFR 820.10(b)(2)" in r["final_out"] and "https://example/1" in r["final_out"]  # citations and sources
    assert "3 chunks" in r["status"] and r["stop_hidden"] and not r["ask_disabled"]


def test_a_generation_error_is_shown_with_the_unvalidated_draft():
    r = page("error")
    assert "Request failed: model crashed mid-generation" in r["final_out"]
    assert "Unvalidated draft" in r["final_out"] and "Draft answer [9]." in r["final_out"]


def test_a_connection_that_closes_without_a_final_event_is_an_error_not_an_answer():
    r = page("truncated")
    assert "closed before the answer was complete" in r["final_out"]
    assert "Validated" not in r["final_out"]
