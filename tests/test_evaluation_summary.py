"""The Evaluation dashboard's backend: the summary of stored per-question evaluations
(regulus.conversations.evaluation_summary over ConversationStore.evaluation_rows), the
GET /api/evaluation/summary route and the static benchmark reference (GET /api/benchmark/summary).

The accuracy payloads are built by hand in the shape regulus.accuracy.review.question_review emits,
so these tests do not move when the evaluator is recalibrated. Pinned: the dashboard counts exactly
what the page would show (a PASS the chat refuses to show is NOT EVALUATED here too, checked against
the page's own evaluationOf()); invalid scores are never counted; no answer or draft text reaches the
summary; a malformed stored result is skipped, not fatal; and the benchmark file holds exactly the
measured and projected facts, labelled as such.
"""

from __future__ import annotations

import copy
import json
import math
import shutil
import sqlite3
import subprocess
import uuid

import pytest

from regulus.config import PROJECT_ROOT
from regulus.conversations import ConversationStore
from regulus.conversations.evaluation_summary import BASIS, BUCKETS, displayed, page_score, summarize
from tests.test_conversation_server import UI, call, server  # noqa: F401  (fixture)

NODE = shutil.which("node")
HARNESS = str(PROJECT_ROOT / "tests" / "answer_ui_stream_harness.js")
RUBRIC = "regulus_live_evidence_assessment_v2"
Q = "What does 21 CFR 820.10(b)(2) require?"
OTHER = "What does 21 CFR 820.30(a) require?"
DIMS = ("question_relevance", "substantive_correctness", "evidence_support", "citation_correctness",
        "fabrication_free", "completeness", "scope_correct")
LABEL = {"pass": "PASS", "fail": "FAIL", "not_evaluated": "NOT EVALUATED"}
_MISSING = object()


def dims(**states) -> list[dict]:
    """All seven dimensions, pass unless named."""
    return [{"dimension": d, "label": d.replace("_", " ").title(), "state": states.get(d, "pass"),
             "glyph": "✓", "detail": f"{d} detail", "claim": "c", "evidence": []} for d in DIMS]


def review(status="pass", *, label=None, score=100, question=Q, sub="pass", cite="pass", explanation="why"):
    return {"question": question, "status": status, "label": label or LABEL[status],
            "substantive_correctness": {"state": sub, "label": sub.title(), "detail": "d"} if sub else None,
            "citation_correctness": {"state": cite, "label": cite.title(), "detail": "d"} if cite else None,
            "explanation": explanation, "live_check_score": score, "rubric_id": RUBRIC, "basis": "b"}


def accuracy(rev, *, status="evaluated", dimensions=None):
    return {"status": status, "accuracy": rev.get("live_check_score") if isinstance(rev, dict) else None,
            "rubric_id": RUBRIC, "dimensions": dims() if dimensions is None else dimensions, "question_review": rev}


def result(question=Q, acc=_MISSING, **extra):
    r = {"question": question, "answer": "Validated answer [1].", "model_called": True,
         "citations": [{"index": 1, "label": "21 CFR 820.10(b)(2)"}], **extra}
    if acc is not _MISSING:
        r["accuracy"] = acc
    return r


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "chat.sqlite3")


def put(store, r, asked=Q, cid=None):
    """One answered turn; returns (conversation id, turn id)."""
    cid = cid or store.create_conversation()["id"]
    t = uuid.uuid4().hex
    store.add_user_message(cid, t, asked)
    store.record_answer(cid, t, "ok", (r or {}).get("answer", ""), r)
    return cid, t


# ------------------------------------------------------------- counting


def test_zero_history_gives_an_empty_summary(store):
    s = store.evaluation_summary()
    assert s["basis"] == BASIS and "not the 300-question acceptance-test score" in s["basis"]
    assert s["turns"] == {"answered": 0, "assessed": 0, "without_evaluation": 0, "failed": 0, "unreadable": 0,
                          "limit": 5000, "truncated": False}
    assert s["status"] == {"pass": 0, "fail": 0, "not_evaluated": 0, "not_fully_evaluated": 0}
    assert len(s["scores"]["buckets"]) == 11 and all(
        b["pass"] == b["fail"] == b["not_evaluated"] == 0 for b in s["scores"]["buckets"])
    assert s["scores"]["buckets"][-1]["label"] == "100" and s["scores"]["buckets"][0]["label"] == "0–9"
    assert s["scores"]["median"] is None and s["scores"]["min"] is None and s["scores"]["max"] is None
    assert [r["dimension"] for r in s["dimensions"]["rows"]] == list(DIMS)          # the rubric's order, zeros
    assert all(r["total"] == 0 for r in s["dimensions"]["rows"])
    assert s["recent"] == [] and s["rubrics"] == {}


def test_counts_by_status_scores_and_buckets(store):
    put(store, result(acc=accuracy(review("pass", score=100))))
    put(store, result(acc=accuracy(review("fail", score=40), dimensions=dims(completeness="fail"))))
    put(store, result(acc=accuracy(review("not_evaluated", label="NOT FULLY EVALUATED", score=5),
                                   dimensions=dims(completeness="not_established"))))
    put(store, result())                                                  # evaluation off: no accuracy key
    cid = store.create_conversation()["id"]
    t = uuid.uuid4().hex
    store.add_user_message(cid, t, Q)
    store.record_answer(cid, t, "error", "Request failed: boom", None)    # a failed turn is not an answer
    s = store.evaluation_summary()
    assert s["turns"]["answered"] == 4 and s["turns"]["assessed"] == 3 and s["turns"]["without_evaluation"] == 1
    assert s["turns"]["failed"] == 1
    assert s["status"] == {"pass": 1, "fail": 1, "not_evaluated": 1, "not_fully_evaluated": 1}
    by = {b["label"]: b for b in s["scores"]["buckets"]}
    assert by["40–49"]["fail"] == 1 and by["100"]["pass"] == 1 and by["0–9"]["not_evaluated"] == 1
    assert (s["scores"]["scored"], s["scores"]["median"], s["scores"]["min"], s["scores"]["max"]) == (3, 40, 5, 100)
    assert s["rubrics"] == {RUBRIC: 3}
    completeness = next(r for r in s["dimensions"]["rows"] if r["dimension"] == "completeness")
    assert (completeness["pass"], completeness["fail"], completeness["not_established"]) == (1, 1, 1)
    assert s["dimensions"]["basis"] == 3


def _damaged(name):
    a = accuracy(review("pass"))
    q, asked = Q, Q
    if name == "null":
        a = None
    elif name == "no_review":
        del a["question_review"]
    elif name == "review_not_object":
        a["question_review"] = "PASS"
    elif name == "unknown_status":
        a["question_review"]["status"] = "great"
    elif name == "pass_without_substantive":
        a["question_review"]["substantive_correctness"] = None
    elif name == "pass_but_not_evaluated":
        a["status"] = "evaluator_error"
    elif name == "pass_with_failed_citation":
        a["question_review"]["citation_correctness"]["state"] = "fail"
    elif name == "pass_with_failed_substantive":
        a["question_review"]["substantive_correctness"]["state"] = "fail"
    elif name == "review_for_another_question":
        a["question_review"]["question"] = OTHER
    elif name == "result_for_another_question":
        asked = OTHER                                                     # the page asked something else
    return result(q, a), asked


DAMAGE = ["null", "no_review", "review_not_object", "unknown_status", "pass_without_substantive",
          "pass_but_not_evaluated", "pass_with_failed_citation", "pass_with_failed_substantive",
          "review_for_another_question", "result_for_another_question"]


@pytest.mark.parametrize("damage", DAMAGE)
def test_a_pass_the_page_would_not_show_is_counted_not_evaluated(store, damage):
    r, asked = _damaged(damage)
    put(store, r, asked=asked)
    s = store.evaluation_summary()
    assert s["status"]["pass"] == 0 and s["status"]["not_evaluated"] == 1
    assert s["scores"]["scored"] == 0                                    # no score without an accepted result
    assert s["dimensions"]["basis"] == 0 and s["recent"][0]["label"] == "NOT EVALUATED"


def test_a_calibrated_pass_with_a_partly_verified_answer_counts_as_pass(store):
    # the calibrated rule (regulus.accuracy.review, 23 Oct) passes with substantive correctness "partial" (statements
    # the verifier could not decide); the page shows that PASS, so the dashboard counts it as one
    a = accuracy(review("pass"))
    a["question_review"]["substantive_correctness"]["state"] = "partial"
    put(store, result(acc=a))
    assert store.evaluation_summary()["status"]["pass"] == 1


@pytest.mark.parametrize("bad", [None, "90", 150, -1, 90.5, True, [90], {"v": 90}])
def test_invalid_scores_are_not_counted(store, bad):
    put(store, result(acc=accuracy(review("pass", score=bad))))
    s = store.evaluation_summary()
    assert s["status"]["pass"] == 1 and s["scores"]["scored"] == 0 and s["recent"][0]["score"] is None


def test_a_whole_float_score_counts_as_the_page_counts_it(store):
    put(store, result(acc=accuracy(review("fail", score=90.0))))
    s = store.evaluation_summary()
    assert s["scores"]["scored"] == 1 and s["scores"]["median"] == 90 and s["recent"][0]["score"] == 90


def test_page_score_rejects_what_evaluation_score_rejects():
    for bad in (math.nan, math.inf, -math.inf, None, -1, 101, 99.9, "58", True, False, [1]):
        assert page_score(bad) is None, bad
    assert (page_score(57), page_score(0), page_score(100), page_score(90.0)) == (57, 0, 100, 90)


def test_dimensions_are_counted_only_for_decided_results(store):
    put(store, result(acc=accuracy(review("not_evaluated", score=None),
                                   dimensions=dims(**{d: "not_established" for d in DIMS}))))   # an abstention
    put(store, result(acc=accuracy(review("fail", score=0), dimensions=dims(fabrication_free="fail"))))
    s = store.evaluation_summary()
    assert s["dimensions"]["basis"] == 1
    rows = {r["dimension"]: r for r in s["dimensions"]["rows"]}
    assert [r["dimension"] for r in s["dimensions"]["rows"]] == list(DIMS)
    assert rows["fabrication_free"]["fail"] == 1 and rows["fabrication_free"]["total"] == 1
    assert all(r["not_established"] == 0 for r in s["dimensions"]["rows"])        # the abstention is excluded
    assert rows["fabrication_free"]["label"] == "Unsupported claims"               # the rubric's own label


def test_recent_is_newest_first_and_truncated(store):
    long_q = "Explain " + "the requirement " * 30 + "in full?"
    a, _ = put(store, result(acc=accuracy(review("pass"))))
    b, _ = put(store, result(acc=accuracy(review("fail", score=40, question=long_q)), question=long_q), asked=long_q)
    c, tc = put(store, result(acc=accuracy(review("fail", score=0, explanation="  many   spaces\n here "))))
    s = store.evaluation_summary(recent=2)
    assert [r["conversation_id"] for r in s["recent"]] == [c, b]
    assert s["recent"][0]["turn_id"] == tc and s["recent"][0]["explanation"] == "many spaces here"
    q = s["recent"][1]["question"]
    assert len(q) <= 200 and q.endswith("…") and "  " not in q
    assert s["turns"]["assessed"] == 3                                 # recent limits the list, not the counts


def test_no_draft_text_or_answer_text_reaches_the_summary(store):
    secret = "DRAFT-SECRET"
    r = result(acc=accuracy(review("fail", score=40)), answer=secret, raw_model_output=secret, repair_input=secret,
               repair_output=secret,
               validation={"initial": {"problems": [{"code": "X", "sentence": secret, "detail": secret}]}})
    put(store, r)
    s = store.evaluation_summary()
    assert s["status"]["fail"] == 1
    assert secret not in json.dumps(s, ensure_ascii=False)
    rows = store.evaluation_rows()["rows"]
    assert secret not in json.dumps(rows, ensure_ascii=False)          # not even in what the query hands Python


def test_only_the_evaluation_scalars_reach_python(store):
    """evaluation_rows extracts the fields the summary reads, in SQL: not the dimensions' details, claims or
    evidence, nor the review's basis, so a 5000-answer summary does not load megabytes of text per request."""
    marked = [{**d, "detail": "DETAIL-MARKER", "claim": "CLAIM-MARKER", "evidence": ["EVIDENCE-MARKER"]} for d in dims(completeness="fail")]
    marked += ["not a dimension", {"dimension": 7, "state": True, "label": None}]       # skipped, never a crash
    rev = {**review("fail", score=40), "basis": "BASIS-MARKER", "extra": {"x": "EXTRA-MARKER"}}
    put(store, result(acc=accuracy(rev, dimensions=marked)))
    rows = store.evaluation_rows()["rows"]
    text = json.dumps(rows, ensure_ascii=False)
    for marker in ("DETAIL-MARKER", "CLAIM-MARKER", "EVIDENCE-MARKER", "BASIS-MARKER", "EXTRA-MARKER", "Validated answer"):
        assert marker not in text, marker
    assert all(set(d) == {"dimension", "state", "label"} for d in rows[0]["dims"])
    assert set(rows[0]["review"]) == {"status", "label", "question", "explanation", "live_check_score",
                                      "substantive_correctness", "citation_correctness"}
    s = store.evaluation_summary()
    assert s["status"]["fail"] == 1 and s["scores"]["median"] == 40 and s["recent"][0]["explanation"] == "why"
    counted = {r["dimension"]: r for r in s["dimensions"]["rows"]}
    assert counted["completeness"]["fail"] == 1 and sum(r["total"] for r in s["dimensions"]["rows"]) == len(DIMS)


def test_a_malformed_stored_result_is_skipped_not_fatal(store):
    put(store, result(acc=accuracy(review("pass"))))
    cid, t = put(store, result(acc=accuracy(review("fail", score=0))))
    db = sqlite3.connect(store.path)
    try:
        db.execute("UPDATE messages SET result_json = '{bad' WHERE conversation_id = ? AND role = 'assistant'", (cid,))
        db.commit()
    finally:
        db.close()
    s = store.evaluation_summary()
    assert s["turns"]["unreadable"] == 1 and s["turns"]["assessed"] == 1 and s["status"]["pass"] == 1


def test_summarize_is_pure_and_takes_the_given_time():
    from datetime import datetime, timezone

    s = summarize({"rows": [], "answered": 0, "failed": 0, "limit": 10}, now=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert s["generated_at"].startswith("2026-10-23T00:00:00") and s["turns"]["limit"] == 10
    assert [lo for lo, _, _ in BUCKETS] == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]


# ------------------------------------------------------------- the page and its mirror agree


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_summary_status_matches_the_page(store, tmp_path):
    cases = [_damaged(name) for name in DAMAGE]
    cases += [
        (result(acc=accuracy(review("pass", score=100))), Q),
        (result(acc=accuracy(review("pass", score=90.0))), Q),
        (result(acc=accuracy(review("fail", score=40))), Q),
        (result(acc=accuracy(review("fail", label="PASS", score=40))), Q),          # unrecognised label
        (result(acc=accuracy(review("not_evaluated", label="NOT FULLY EVALUATED", score=5))), Q),
        (result(acc=accuracy(review("not_evaluated", score=None))), Q),
        (result(acc=accuracy(review("pass", score="90"))), Q),
        (result(acc=accuracy(review("pass", cite="not_applicable", score=True))), Q),
        (result(), Q),                                                              # evaluation off
    ]
    for r, asked in cases:
        put(store, copy.deepcopy(r), asked=asked)
    rows = list(reversed(store.evaluation_rows()["rows"]))                         # back in insertion order
    mine = []
    for row in rows:
        d = displayed(row)
        mine.append(None if d is None else {"status": d["status"], "label": d["label"], "score": d["score"]})
    path = tmp_path / "payloads.json"
    path.write_text(json.dumps([{"result": r, "asked": asked} for r, asked in cases]), encoding="utf-8")
    out = subprocess.run([NODE, HARNESS, "evalof", str(path)], capture_output=True, text=True, timeout=30, check=True)
    page = json.loads(out.stdout)
    assert len(page) == len(mine) == len(cases)
    assert mine == page


# ------------------------------------------------------------- GET /api/evaluation/summary


def test_summary_route_and_unavailable_and_bad_recent(server):
    base, engine, H = server
    put(H.store, result(acc=accuracy(review("fail", score=40))))
    put(H.store, result(acc=accuracy(review("pass"))))
    status, text = call(base, "/api/evaluation/summary")
    assert status == 200
    s = json.loads(text)["summary"]
    assert s["status"]["pass"] == 1 and s["status"]["fail"] == 1 and len(s["recent"]) == 2
    status, text = call(base, "/api/evaluation/summary?recent=1")
    assert status == 200 and len(json.loads(text)["summary"]["recent"]) == 1
    for bad in ("0", "x", "101", "-1", "2.5", "", "%C2%B2", "0100"):
        status, text = call(base, f"/api/evaluation/summary?recent={bad}")
        assert status == 400 and json.loads(text)["error"] == "recent must be a whole number from 1 to 100", bad
    H.store = None
    status, text = call(base, "/api/evaluation/summary")
    assert status == 503 and "unavailable" in json.loads(text)["error"] and "Traceback" not in text


def test_a_summary_failure_is_reported_without_a_traceback(server, monkeypatch):
    base, engine, H = server

    def broken(**kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(H.store, "evaluation_summary", broken)
    status, text = call(base, "/api/evaluation/summary")
    assert status == 500 and json.loads(text) == {"error": "the evaluation summary could not be computed"}
    assert "disk on fire" not in text and "Traceback" not in text


def test_the_summary_route_is_not_a_conversation_id(server):
    base, engine, H = server
    status, text = call(base, "/api/conversations/summary")       # never shadowed by the dashboard routes
    assert status == 400 and "error" in json.loads(text)


# ------------------------------------------------------------- the benchmark reference

GOLDEN = {
    "version": "benchmark_summary_v1",
    "about": ("Static reference numbers for the Evaluation dashboard, copied from the 22-26 Oct 2026 benchmark "
              "records. Not computed by this server and not changed by live answers."),
    "holdout_100_measured_2026-10-22": {
        "model": "Qwen3-4B-Instruct-2507 (MLX 4-bit)",
        "PASS": 37, "partly_pass": 8, "partly_fail": 26, "FAIL": 29,
        "by_category": {"Colour listings": "23/35", "Procedure": "7/16", "Statute": "4/19",
                        "Labeling 700-740": "3/27", "Specs/definitions (82.3, 82.5, 82.51)": "0/3"},
        "scoring": "blind two-lens scoring (plain + skeptic) with adjudication",
    },
    "holdout_100_projected": {
        "as_of": "2026-10-26",
        "PASS": 51,
        "note": "projection, not a full re-run: 22 Oct verdicts (37) updated with the blind A/B results of the 23 Oct retrieval changes (39), the 23 Oct answer-stage fixes (+7: 740.17, 82.1602, 710.3, 82.1328, 82.1330, 82.705, 82.706) and the 26 Oct practice-silence answers (+5: UC-004, UC-005, UC-008, UC-010, UC-012)"
    },
    "evaluator_agreement": {
        "as_of": "2026-10-23",
        "note": "live evaluator status vs blind verdicts on 182 blind-scored answers (holdout and dev), after the 23 Oct recalibration; most correct answers are shown NOT FULLY EVALUATED, because without a reference answer the evaluator cannot establish that the retrieved section is the right one",
        "before": {
            "blind_pass_called_pass": "0/37"
        },
        "after": {
            "blind_pass_shown_fail": "8 (was 44)",
            "pass_shown": "13, of which 11 blind PASS",
            "misleading_shown_pass": "0"
        }
    },
}


def test_benchmark_file_holds_exactly_the_measured_facts():
    data = json.loads((PROJECT_ROOT / "data" / "reference" / "benchmark_summary_v1.json").read_text(encoding="utf-8"))
    assert data == GOLDEN
    m = data["holdout_100_measured_2026-10-22"]
    assert m["PASS"] + m["partly_pass"] + m["partly_fail"] + m["FAIL"] == 100
    fractions = [tuple(int(x) for x in v.split("/")) for v in m["by_category"].values()]
    assert sum(n for n, _ in fractions) == m["PASS"] == 37 and sum(d for _, d in fractions) == 100
    assert list(m["by_category"]) == ["Colour listings", "Procedure", "Statute", "Labeling 700-740",
                                      "Specs/definitions (82.3, 82.5, 82.51)"]
    assert "not a full re-run" in data["holdout_100_projected"]["note"]     # labelled a projection


def test_benchmark_route_serves_the_file_and_reports_a_missing_one(server, monkeypatch, tmp_path):
    base, engine, H = server
    H.store = None                                               # independent of chat history
    status, text = call(base, "/api/benchmark/summary")
    assert status == 200 and json.loads(text) == {"benchmark": GOLDEN}
    monkeypatch.setattr(UI, "BENCHMARK_FILE", tmp_path / "missing.json")
    status, text = call(base, "/api/benchmark/summary")
    assert status == 404 and json.loads(text) == {"error": "the benchmark summary is not available on this server"}
    for content in ("{bad", "[1, 2]"):
        bad = tmp_path / "bad.json"
        bad.write_text(content, encoding="utf-8")
        monkeypatch.setattr(UI, "BENCHMARK_FILE", bad)
        status, text = call(base, "/api/benchmark/summary")
        assert status == 500 and json.loads(text) == {"error": "the benchmark summary file is unreadable"}
        assert "Traceback" not in text
