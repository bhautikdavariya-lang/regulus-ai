"""The laid-out answer on the page (web/index.html answerHtml, regulus.rag.presentation): every field is escaped, the
citation markers become superscripts naming their source, and a result without a layout shows its plain text. The
page's own functions are run under Node, extracted from its script (26 Oct 2026)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from regulus.config import PROJECT_ROOT
from regulus.rag.presentation import present

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _function(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    depth, i = 0, src.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
        if depth == 0:
            return src[start:i]


def render(result: dict) -> str:
    html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = html[html.rindex("<script>") + 8: html.rindex("</script>")]
    esc = next(line for line in script.splitlines() if line.startswith("const esc = "))
    code = "\n".join([esc] + [_function(script, n) for n in ("icon", "citeMarks", "answerHtml")])
    code += f"\nprocess.stdout.write(answerHtml({json.dumps(result)}));"
    return subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30, check=True).stdout


def result_for(answer: str, **kw) -> dict:
    cites = [{"index": 1, "label": "21 CFR 700.14(a)", "url": "u", "cited_in_answer": True}]
    r = {"answer": answer, "citations": cites, "snapshot_date": "2026-09-03", **kw}
    r["presentation"] = present(answer, fallback_type=kw.get("fallback_type"), citations=cites,
                                followup=kw.get("followup")).to_dict()
    return r


def test_a_laid_out_answer_shows_verdict_sections_marks_and_currency():
    out = render(result_for("No, it applies only to aerosol products [1].\n\n"
                            "21 CFR 700.14(a) prohibits vinyl chloride in cosmetic aerosol products [1]."))
    assert 'class="verdict neg">No</span>' in out and "What the regulation says" in out
    assert '<span class="plabel">21 CFR 700.14(a)</span>' in out
    assert '<sup class="cm" title="21 CFR 700.14(a)">1</sup>' in out and "[1]" not in out
    assert "eCFR Title 21 as of 2026-09-03" in out and "not legal advice" in out


def test_every_field_is_escaped():
    evil = "<img src=x onerror=alert(1)>"
    r = result_for(f"Yes, {evil} [1].\n\n21 CFR 700.14(a) says {evil} [1].\nEvidence limit: {evil}.",
                   followup={"followup": {"anchored": True, "anchor": {"cfr": ["700.14"]}, "earlier_question": evil}})
    r["citations"][0]["label"] = evil
    out = render(r)
    assert "<img" not in out and "&lt;img" in out


def test_a_withheld_answer_reads_plainly_and_a_result_without_layout_is_plain_text():
    out = render(result_for("The generated answer could not be validated against the retrieved regulatory evidence, so "
                            "it is not shown. Sources consulted: 21 CFR 700.25(a), 21 CFR 700.25(c).",
                            fallback_type="unvalidated_answer_withheld"))
    assert "could not be verified sentence by sentence" in out and "Provisions consulted" in out
    assert "<li>21 CFR 700.25(c)</li>" in out and "<details" in out
    plain = render({"answer": "Plain <b>text</b> [1].", "citations": []})
    assert plain == '<div class="bubble">Plain &lt;b&gt;text&lt;/b&gt; [1].</div>'


def test_suggested_follow_ups_are_buttons_with_escaped_text():
    r = result_for("Yes, it may be used [1].", followup={"anchor": {"cfr": ["211.22"]}})
    r["presentation"]["suggestions"] = ['Who does <b>this</b> apply to?']
    out = render(r)
    assert 'data-suggest="Who does &lt;b&gt;this&lt;/b&gt; apply to?"' in out and "<b>" not in out
