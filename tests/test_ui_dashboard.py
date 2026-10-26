"""The redesigned answering page (web/index.html): deleting a conversation, the conversation filter,
the evaluation card under each answer, the theme button and the Evaluation view (dashboard), run by
the page's own <script> under Node against a scripted server (tests/chat_ui_harness.js).

Pinned: a delete is asked for first and never sent on the first click; deleting the open
conversation returns to a new chat; a conversation that is answering cannot be deleted; a refused
delete keeps the row and says so; the dashboard counts, labels the measured and projected benchmark
numbers for what they are, shows no percentage and no "accuracy", escapes every server text, has an
empty and an unavailable state, opens a recent evaluation at its turn, and is fetched only when it is
opened (and fetched again when a delete or an answer lands, even mid-load). Redraws keep a keyboard user's
focus, narrow-screen drawers make the page behind them inert, and no focus ever goes to a hidden control.
The page stays self-contained and keeps the markup contracts the other UI tests read.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from regulus.config import PROJECT_ROOT

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
HTML = PROJECT_ROOT / "web" / "index.html"


def page(scenario: str) -> dict:
    out = subprocess.run([NODE, str(PROJECT_ROOT / "tests" / "chat_ui_harness.js"), scenario],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


# ------------------------------------------------------------- deleting a conversation


def test_delete_asks_first_and_cancel_sends_nothing():
    r = page("delete_cancel")
    asked, after = r["after_ask"], r["after"]
    assert 'data-delok="conv-aaaa-1111"' in asked["sidebar"] and "Delete this chat from history?" in asked["sidebar"]
    # the confirm step says what a delete does not remove, and names the chat for a screen reader
    assert "measurement log keeps its own copy" in asked["sidebar"]
    assert 'role="group" aria-label="Delete “About Part 11” from history?"' in asked["sidebar"]
    assert 'role="presentation"' not in asked["sidebar"] and '<li class="conv-row confirming">' in asked["sidebar"]
    assert 'data-delno="conv-aaaa-1111"' in asked["sidebar"] and asked["deletes"] == []
    assert "data-delok" not in after["sidebar"] and after["deletes"] == []
    assert 'data-id="conv-aaaa-1111"' in after["sidebar"]                  # the row is back as it was


def test_deleting_another_conversation_keeps_the_open_one():
    r = page("delete")
    after = r["after"]
    assert r["after_ask"]["deletes"] == []                                   # the first click only asks
    assert after["deletes"] == ["/api/conversations/conv-aaaa-1111"]
    assert "conv-aaaa-1111" not in after["sidebar"] and "conv-bbbb-2222" in after["sidebar"]
    assert after["active"] == after["remembered"] == "conv-bbbb-2222"
    assert "Part 820" in after["thread"]
    assert after["toast"] == "Chat deleted from history. The server's measurement log keeps its own copy."
    assert after["announce"] == after["toast"]                               # spoken: #toast itself is visual only
    assert after["requests"].count("GET /api/conversations") == 1           # no list redraw under the moved focus


def test_deleting_the_open_conversation_returns_to_a_new_chat():
    after = page("delete_active")["after"]
    assert after["deletes"] == ["/api/conversations/conv-bbbb-2222"]
    assert after["active"] is None and after["remembered"] is None
    assert after["thread"] == "" and after["out"] == ""
    assert after["convtitle"] == "New conversation" and after["posts"] == 0
    assert "conv-bbbb-2222" not in after["sidebar"] and "conv-aaaa-1111" in after["sidebar"]


def test_the_open_conversation_cannot_be_deleted_while_it_is_answering():
    r = page("delete_busy")
    during = r["during"]
    assert during["deletes"] == []
    assert "Wait for the answer to finish" in during["toast"]
    assert "data-delok" not in during["sidebar"]                              # no confirm step while answering
    assert re.search(r'data-del="conv-bbbb-2222"[^>]*disabled', during["sidebar"])
    after = r["after"]
    assert after["deletes"] == [] and "A question that is still being answered" in after["thread"]
    assert not re.search(r'data-del="conv-bbbb-2222"[^>]*disabled', after["sidebar"])   # unlocked once answered


def test_a_failed_delete_keeps_the_row_and_says_so():
    after = page("delete_fail")["after"]
    assert after["deletes"] == ["/api/conversations/conv-aaaa-1111"]
    assert 'data-id="conv-aaaa-1111"' in after["sidebar"] and "data-delok" not in after["sidebar"]
    assert "Could not delete the conversation" in after["toast"] and "disk full" in after["toast"]
    assert after["active"] == "conv-bbbb-2222"


def test_search_filters_the_list():
    r = page("search")
    assert "conv-bbbb-2222" in r["after_820"]["sidebar"] and "conv-aaaa-1111" not in r["after_820"]["sidebar"]
    assert "No conversations match" in r["after_zzz"]["sidebar"] and "zzz" in r["after_zzz"]["sidebar"]
    assert "conv-aaaa-1111" in r["after_clear"]["sidebar"] and "conv-bbbb-2222" in r["after_clear"]["sidebar"]
    assert r["after_820"]["thread"] == r["after_init"]["thread"]             # filtering never touches the thread


def test_conversations_are_grouped_and_each_row_has_a_named_delete_button():
    sidebar = page("restore")["after_init"]["sidebar"]
    assert 'class="grp"' in sidebar
    assert 'aria-label="Delete conversation: About Part 11"' in sidebar
    assert 'aria-label="Delete conversation: About Part 820"' in sidebar


# ------------------------------------------------------------- the evaluation card in the thread


def test_each_answer_carries_its_evaluation_card_without_repeating_the_question():
    thread = page("evalcard")["after_init"]["thread"]
    assert "FAIL</span>" in thread and "Evaluation score 40/100" in thread
    assert "Completeness fail: 82.5(c) was not addressed in the answer." in thread
    assert "Not the 300-question acceptance-test score." in thread
    # a PASS the page must refuse (the assessment is not "evaluated") is NOT EVALUATED here too
    assert "NOT EVALUATED</span>" in thread and "PASS</span>" not in thread and "Score unavailable" in thread
    assert thread.count("What does 82.5 require for certification?") == 1
    assert thread.count("Is 740.17 a warning statement?") == 1
    assert "%" not in thread and "Accuracy" not in thread
    assert thread.count("data-retry=") == 0                                   # no "Regenerate" on delivered answers
    assert "data-copy=" in thread and "data-show=" in thread


def test_the_pending_reply_is_a_progress_card_with_no_answer_text():
    snaps = page("stream")["snaps"]
    pending = [s for s in snaps if s["pending_in_thread"]]
    assert pending and all("Retrieve" in s["visible"] and "Check" in s["visible"] for s in pending)
    assert all("unexplained" not in s["visible"] for s in snaps)


# ------------------------------------------------------------- the Evaluation view


def test_the_dashboard_shows_counts_scores_and_honest_labels():
    r = page("dashboard")
    after = r["after"]
    body = after["evalbody"]
    assert "dash" in after["app_class"] and r["view_hidden"] == {"chat": True, "eval": False}
    for text in ("3 of 35 with a result", "23 of 35 with a result", "9 of 35 · 2 not fully evaluated", "of 36 answered",
                 "Answers with a live result", "PASS of 100, measured 22 Oct",
                 "Median evaluation score", "/100", "not the 300-question acceptance-test score",
                 "MEASURED", "PROJECTION · 26 Oct 2026", "not a full re-run", "RECALIBRATED · 23 Oct 2026",
                 "Good answers shown FAIL", "8 (was 44)", "Misleading answers shown PASS", "0/37", "23/35",
                 "Labeling 700-740", "Specs/definitions (82.3, 82.5, 82.51)", "PASS of 100, projected",
                 "37 measured on 22 Oct", "A projection is not a measurement", "Checks by dimension",
                 "Score distribution", "Recent evaluations", "LIVE · this server's history",
                 "data/reference/benchmark_summary_v1.json"):
        assert text in body, text
    assert "%" not in body and "Accuracy" not in body and "accuracy" not in body
    assert 'class="seg p-proj"' in body                                        # the projection is drawn dashed
    assert 'class="big proj"' in body                                          # ... and its number is the secondary one
    assert "assessed" not in body                                              # NOT EVALUATED is not "assessed"
    # the dimension matrix: per-column ramps (no light-on-dark switch) in a keyboard-scrollable region
    assert 'class="hc h-pass"' in body and 'class="hc h-fail"' in body and " hi\"" not in body
    assert 'role="region" aria-label="Checks by dimension"' in body and 'class="dgrid live"' in body
    assert body.count('data-open="') == 3


def test_the_status_filter_and_the_way_back_to_chat():
    r = page("dashboard")
    filtered = r["after_filter"]["evalbody"]
    assert filtered.count('data-open="') == 1 and 'data-open="conv-bbbb-2222/t-b1"' in filtered
    assert re.search(r'data-filter="fail" aria-pressed="true"', filtered)
    assert "dash" not in r["after_back"]["app_class"] and "chat" in r["after_back"]["app_class"]
    assert r["view_back"] == {"chat": False, "eval": True}


def test_dashboard_text_is_escaped():
    body = page("dashboard")["after"]["evalbody"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in body
    assert "<img" not in body


def test_an_empty_history_shows_the_empty_state_and_the_benchmark():
    body = page("dashboard_empty")["after"]["evalbody"]
    assert "No evaluated answers yet" in body and 'data-goto="chat"' in body
    assert "<b>37</b> PASS" in body and "MEASURED" in body
    assert "%" not in body


def test_unavailable_history_still_shows_the_benchmark():
    r = page("dashboard_unavailable")
    after = r["after"]
    assert not after["chat_enabled"] and "chat" not in after["app_class"] and "dash" in after["app_class"]
    body = after["evalbody"]
    assert "conversation history, which is unavailable" in body
    assert "MEASURED" in body and "0/37" in body and "%" not in body


def test_a_recent_evaluation_opens_that_conversation_at_that_turn():
    r = page("dashboard_open")
    assert r["dash"]["active"] is None and "dash" in r["dash"]["app_class"]
    after = r["after"]
    assert after["active"] == "conv-aaaa-1111" and after["remembered"] == "conv-aaaa-1111"
    assert "dash" not in after["app_class"]
    assert 'class="turn target"' in after["thread"] and 'id="turn-t-a1"' in after["thread"]
    assert "Validated answer A" in after["out"]
    assert after["turn_focused"] == 1 and after["announce"] == "Opened the conversation at the selected answer"
    side = r["after_sidebar"]                          # a conversation picked from the sidebar while on the dashboard
    assert side["active"] == "conv-bbbb-2222" and "dash" not in side["app_class"]
    assert "Part 820" in side["thread"] and 'class="turn target"' not in side["thread"]
    assert side["q_focused"] >= 1                      # picked from the list: the question box takes the focus


def test_a_delete_while_the_dashboard_is_open_refreshes_it():
    r = page("evaldelete")
    assert 'data-open="conv-aaaa-1111/t-a1"' in r["dash"]["evalbody"] and r["dash"]["summaries"] == 1
    after = r["after"]
    assert after["deletes"] == ["/api/conversations/conv-aaaa-1111"]
    assert after["summaries"] == 2                                        # reloaded at once, not on the next visit
    assert "conv-aaaa-1111" not in after["evalbody"] and 'data-open="conv-bbbb-2222/t-b1"' in after["evalbody"]
    assert after["active"] == after["remembered"] == "conv-bbbb-2222"
    stale = r["after_stale_open"]                                         # a row whose conversation is gone
    assert "Could not open that conversation" in stale["toast"] and stale["announce"] == stale["toast"]
    assert stale["active"] == stale["remembered"] == "conv-bbbb-2222"     # the open chat is neither lost nor forgotten
    assert "Part 820" in stale["thread"]


def test_a_delete_during_the_first_summary_load_fetches_it_again():
    r = page("evalrace")
    assert r["during"]["summaries"] == 1 and r["during"]["deletes"] == ["/api/conversations/conv-aaaa-1111"]
    after = r["after"]
    assert after["summaries"] == 2                     # the summary in flight predates the delete: one more is fetched
    assert "conv-aaaa-1111" not in after["evalbody"] and 'data-open="conv-bbbb-2222/t-b1"' in after["evalbody"]


def test_deleting_the_open_conversation_from_the_dashboard_never_focuses_the_hidden_composer():
    after = page("evaldelete_active")["after"]
    assert after["deletes"] == ["/api/conversations/conv-bbbb-2222"] and after["active"] is None
    assert "dash" in after["app_class"] and after["summaries"] == 2     # still on the dashboard, refreshed
    assert after["q_focus_delta"] == 0 and after["newchat_focus_delta"] == 1


def test_a_redraw_puts_the_keyboard_focus_back_on_the_same_button():
    r = page("focuskeep")
    assert r["list"] == ['button[data-id="conv-aaaa-1111"]']             # the conversation list, after an answer
    assert r["dash"] == ['button[data-open="conv-bbbb-2222/t-b1"]']      # the dashboard, after a quiet reload


def test_narrow_screen_drawers_make_the_page_inert_and_give_the_focus_back():
    r = page("drawer")
    behind = ["sidebar", "topbar", "empty", "thread", "composer"]
    side = r["side_open"]
    assert side["inert"]["main"] is True and side["focus"]["newchat"] == 1 and side["expanded"] == "true"
    closed = r["side_closed"]                                              # Escape
    assert not any(closed["inert"].values()) and closed["focus"]["sidetoggle"] == 1 and closed["expanded"] == "false"
    ev = r["ev_open"]                                                      # the evidence overlay below 1280px
    assert ev["inert"]["main"] is False and all(ev["inert"][k] for k in behind) and ev["focus"]["evclose"] == 1
    back = r["ev_closed"]
    assert not any(back["inert"].values()) and back["focus"]["evtoggle"] == 1
    assert r["eval_side_open"]["inert"]["main"] is True and r["eval_side_open"]["focus"]["newchat"] == 2
    gone = r["eval_deleted"]                       # the open chat deleted from the drawer on the Evaluation view
    assert gone["deletes"] == ["/api/conversations/conv-bbbb-2222"] and gone["active"] is None
    assert not any(gone["inert"].values())
    assert gone["focus"]["sidetoggle"] == 2 and gone["focus"]["newchat"] == 2 and gone["focus"]["q"] == 0


def test_a_conversation_deleted_elsewhere_does_not_trap_the_tab():
    r = page("gone")
    first, second = r["after_first"], r["after_second"]
    assert first["streams"][0]["conversation_id"] == "conv-bbbb-2222"     # still posted to the deleted one ...
    assert "conversation not found" in first["thread"]
    assert first["active"] is None and first["remembered"] is None        # ... once: then the stale id is dropped
    assert "deleted elsewhere" in first["toast"] and first["posts"] == 0
    assert second["posts"] == 1 and second["streams"][1]["conversation_id"] == second["active"] != "conv-bbbb-2222"
    assert "Validated answer 2" in second["thread"]


def test_the_model_badge_names_the_model_the_worker_reports():
    r = page("badge")["after"]                     # a 1.7B worker; the configured label names the 4B model
    assert "1.7B" in r["env"] and "4B" not in r["env"]
    assert r["badge_title"].startswith("Qwen/Qwen3-1.7B")
    ok = page("badge_match")["after"]              # the label names the reported model: the label is shown
    assert ok["env"] == "Qwen3-4B-Instruct-2507 (MLX 4-bit)"


def test_chat_mode_status_line_is_plain_and_keeps_the_timings_on_hover():
    second = page("gone")["after_second"]
    assert second["status"].startswith("Answered in ") and "progress events" not in second["status"]
    assert "progress events" in second["status_title"]


def test_switching_views_keeps_the_reading_position():
    r = page("scrollkeep")
    assert r["kept"] == 300                            # back where the reader was, not at the first turn
    assert r["changed"] == 2000                        # the thread changed while hidden: its end is shown


def test_the_dashboard_is_fetched_lazily():
    for scenario, key in (("fresh", "after_second"), ("restore", "after_init"), ("nohistory", "after_first")):
        requests = page(scenario)[key]["requests"]
        assert not any("/api/evaluation/summary" in x or "/api/benchmark/summary" in x for x in requests), scenario
    requests = page("dashboard")["after"]["requests"]
    assert "GET /api/evaluation/summary?recent=25" in requests and "GET /api/benchmark/summary" in requests


def test_theme_cycles_and_is_remembered_without_a_document_element():
    # every click changes what is shown: with a light system theme (the harness has no matchMedia),
    # system -> dark -> system -> dark; "light" would look the same as "system" and is skipped
    r = page("theme")
    assert r["themes"] == ["dark", None, "dark"]
    assert r["theme_label"] == "Theme: dark. Switch to system"


# ------------------------------------------------------------- the page itself


def _app_script(html: str) -> str:
    return html[html.rindex("<script>") + 8: html.rindex("</script>")]


def test_the_page_is_self_contained_and_keeps_its_contracts():
    html = HTML.read_text(encoding="utf-8")
    for external in ("<link", 'src="http', "src='http", "@import", "url(http", "url('http", 'url("http'):
        assert external not in html, external
    script = _app_script(html)
    assert "<script" not in script and "</script" not in script
    assert html[html.rindex("</script>"):].split() == ["</script>", "</body>", "</html>"]
    assert html.count("<script>") == 2 and "<script " not in html                  # head theme bootstrap + the app
    for el in ("app", "thread", "out", "status", "q", "stop", "ask", "convlist", "evalbody", "tabchat", "tabeval",
               "sidebar", "sidetoggle", "newchat", "convsearch", "evidence", "evtoggle", "evclose", "env",
               "chatview", "evalview", "evalrefresh", "evalupdated", "announce", "toast", "themetoggle", "keys",
               "examples", "empty", "scroll", "backdrop", "chatnote", "convtitle"):
        assert f'id="{el}"' in html, el
    for contract in ('<div class="acc">', "<label>Citations</label>", '<div class="answer">${esc(r.answer)}</div>',
                     "<details>", 'id="draftphase"'):
        assert contract in script, contract
    # landmarks: one main, no stray contentinfo, the toast is not a live region of its own
    assert html.count('<main class="main" id="main">') == 1 and "<footer" not in html
    assert '<div id="toast" class="toast" aria-hidden="true" hidden></div>' in html
    assert '<section class="evc' not in script and 'role="group" aria-label="Evaluation of this answer"' in script
    for fn in ("ask", "evaluationOf", "evaluationScore", "renderEvaluation", "setView", "deleteConversation",
               "loadDashboard", "cycleTheme"):
        assert re.search(rf"^(async )?function {fn}\(", script, re.M), fn
    assert re.search(r"^const chat = ", script, re.M) and re.search(r"^const dash = ", script, re.M)
    assert "window.confirm" not in script and "confirm(" not in script.replace("confirming", "")


def test_the_page_offers_light_and_dark_themes_and_respects_reduced_motion():
    html = HTML.read_text(encoding="utf-8")
    assert '@media (prefers-color-scheme: dark)' in html and ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html and "prefers-reduced-motion: reduce" in html
    assert "forced-colors: active" in html and 'name="color-scheme"' in html


def test_the_accessibility_fixes_stay_in_the_stylesheet():
    html = HTML.read_text(encoding="utf-8")
    style = html[html.index("<style>"): html.index("</style>")]

    def block(media: str) -> str:
        start = style.index(media)
        nxt = style.find("@media", start + len(media))
        return style[start: nxt if nxt >= 0 else len(style)]

    # focus rings a 3:1 indicator can see, and tables that scroll inside their card at every width
    assert "#convsearch:focus { border-color: var(--accent);" in style
    assert ".composer:focus-within { border-color: var(--accent);" in style
    assert ".table-wrap { min-width: 0; overflow-x: auto; }" in style
    assert "#convsearch, .composer textarea { font-size: 16px; }" in block("@media (max-width: 559px)")   # no iOS zoom
    assert ".turn.target { animation: none !important; box-shadow:" in block("@media (prefers-reduced-motion: reduce)")
    assert ".flexbar, .sw, .meter { forced-color-adjust: none; }" in block("@media (forced-colors: active)")
