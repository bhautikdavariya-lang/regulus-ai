"""The answer-accuracy indicator in web/index.html, rendered by the page's own
<script> under Node against scripted /api/ask/stream responses.

What these pin is the part a user could be misled by: that a number appears
only when the server sent one, that an abstention reads as an abstention rather
than as 0%, that the live score is never presented as the acceptance-test
score, and that the answer is shown whatever the accuracy block does.
"""

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


def test_a_scored_answer_shows_the_percentage_and_the_components():
    r = page("accuracy_scored")
    assert r["answer_shown"]
    assert "Answer Accuracy" in r["final_out"] and ">90%<" in r["final_out"]
    assert "accuracy 90%" in r["final_out"]                      # the pill in the header row
    for label in ("Substantive correctness", "Evidence support", "Citation correctness",
                  "Unsupported claims", "Completeness", "Scope"):
        assert label in r["final_out"]
    assert "&#x2713;" in r["final_out"] or "✓" in r["final_out"]
    assert "⚠" in r["final_out"]                            # the partial completeness glyph
    assert "Score 100 − deductions (completeness partial −10) = 90%" in r["final_out"]


def test_the_score_is_not_presented_as_the_acceptance_test_score():
    """§8: the live indicator must state the distinction, every time."""
    r = page("accuracy_scored")
    assert "not the 300-question acceptance-test score" in r["final_out"]
    assert "regulus_live_evidence_assessment_v1" in r["final_out"]
    assert "regulus_substantive_rubric_v1" not in r["final_out"]
    assert "passed" not in r["final_out"].lower().replace("acceptance-test score", "")


def test_an_abstention_reads_as_an_abstention_and_never_as_zero():
    """§6: no misleading percentage when nothing could be established."""
    r = page("accuracy_unknown")
    assert r["answer_shown"]
    assert "Unable to determine" in r["final_out"]
    assert "0%" not in r["final_out"] and "100%" not in r["final_out"]
    assert "accuracy unknown" in r["final_out"]
    assert "not decidable from this evidence" in r["final_out"]


def test_a_measured_failure_shows_zero_and_says_why():
    r = page("accuracy_failed")
    assert r["answer_shown"]
    assert ">0%<" in r["final_out"] and "figure 45 is in no source" in r["final_out"]
    assert "✗" in r["final_out"]


def test_the_answer_renders_unchanged_when_the_server_sends_no_assessment():
    """§12 / §14: with the feature off the page is the page it was."""
    off, on = page("normal"), page("accuracy_scored")
    assert off["answer_shown"] and "Answer Accuracy" not in off["final_out"]
    assert "accuracy" not in off["final_out"].lower().replace("accuracy_ms", "")
    # the answer markup itself is identical; only the extra block differs
    answer_block = '<div class="answer">Validated answer [1].</div>'
    assert answer_block in off["final_out"] and answer_block in on["final_out"]
