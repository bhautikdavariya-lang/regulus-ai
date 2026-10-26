"""The Evaluation dashboard's summary of the live per-question evaluations stored with answered turns.

A MIRROR of the page: `displayed()` is `evaluationOf()` and `page_score()` is `evaluationScore()` in
web/index.html, so the dashboard can never count a PASS that the chat would refuse to show. They must
change only together (tests/test_evaluation_summary.py runs the page's own functions to pin this).

What it is: a count of what the live evaluator said about answers stored in this server's history.
Each evaluation is an evidence-based assessment of one answer; the summary is not the 300-question
acceptance-test score, and its scores are evaluation scores out of 100, never accuracy percentages.

Input is `ConversationStore.evaluation_rows()`, which extracts evaluation fields only: no answer text
and no draft text can reach this module or its output. Standard library only; the rubric
(regulus.accuracy.rubric) is imported lazily and only read.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any

LABELS = {"pass": ("PASS",), "fail": ("FAIL",), "not_evaluated": ("NOT EVALUATED", "NOT FULLY EVALUATED")}
NFE = "NOT FULLY EVALUATED"
STATUSES = ("pass", "fail", "not_evaluated")
DIM_STATES = ("pass", "partial", "fail", "not_established", "not_applicable")
# 11 buckets: 0-9 ... 90-99, then 100 on its own (an en dash in the labels)
BUCKETS = [(lo, lo + 9, f"{lo}–{lo + 9}") for lo in range(0, 100, 10)] + [(100, 100, "100")]
BASIS = ("Live evaluations of answers stored in this server's history. Each is an evidence-based assessment of one "
         "answer; not the 300-question acceptance-test score.")
QUESTION_CHARS = 200
EXPLANATION_CHARS = 240


def page_score(value: Any) -> int | None:
    """evaluationScore(): a whole number 0..100 (JSON 90.0 counts, as Number.isInteger does), never a bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not float(value).is_integer() or not 0 <= value <= 100:
        return None
    return int(value)


def displayed(row: dict[str, Any]) -> dict[str, Any] | None:
    """What the page shows for this stored answer: None when the result has no "accuracy" key (evaluation off)."""
    if not row.get("has_accuracy"):
        return None
    review = row.get("review")                  # dict or None (None also when accuracy itself is null/not an object)

    def none(why: str) -> dict[str, Any]:
        return {"status": "not_evaluated", "label": "NOT EVALUATED", "explanation": why, "score": None,
                "accepted": False}

    if not isinstance(review, dict) or review.get("status") not in LABELS:
        return none("No usable evaluation result was returned for this answer.")
    asked, rq = row.get("asked"), row.get("result_question")
    if review.get("question") != rq or (asked is not None and rq != asked):
        return none("The evaluation result is not for this question, so it is not shown.")
    sub, cite = review.get("substantive_correctness"), review.get("citation_correctness")
    if review["status"] == "pass" and not (
            row.get("acc_status") == "evaluated" and isinstance(sub, dict) and sub.get("state") in ("pass", "partial")
            and isinstance(cite, dict) and cite.get("state") in ("pass", "not_applicable")):
        return none("The evaluation result is inconsistent, so it is not shown.")
    label = review.get("label") if review.get("label") in LABELS[review["status"]] else LABELS[review["status"]][0]
    return {"status": review["status"], "label": label, "explanation": str(review.get("explanation") or ""),
            "score": page_score(review.get("live_check_score")), "accepted": True}


def _cut(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _bucket_index(score: int) -> int:
    return 10 if score >= 100 else score // 10


def _median(values: list[int]) -> int | float | None:
    if not values:
        return None
    m = round(float(statistics.median(values)), 1)
    return int(m) if m.is_integer() else m


def _rubric() -> tuple[tuple[str, ...], dict[str, str]]:
    """The rubric's dimension order and labels, read lazily; ((), {}) when it cannot be imported."""
    try:
        from regulus.accuracy import rubric as R

        return tuple(R.DIMENSIONS), dict(R.LABELS)
    except Exception:  # noqa: BLE001 - the summary falls back to the stored labels
        return (), {}


def summarize(payload: dict[str, Any], *, recent: int = 25, now: datetime | None = None) -> dict[str, Any]:
    """The dashboard summary of `ConversationStore.evaluation_rows()` output (rows newest first)."""
    rows = list(payload.get("rows") or ())
    limit = int(payload.get("limit") or len(rows) or 1)
    answered = int(payload.get("answered") or 0)
    recent = max(0, int(recent))
    order, rubric_labels = _rubric()

    status = {s: 0 for s in STATUSES}
    nfe = assessed = without = unreadable = 0
    buckets = [{"label": label, "lo": lo, "hi": hi, **{s: 0 for s in STATUSES}} for lo, hi, label in BUCKETS]
    scores: list[int] = []
    dim_counts: dict[str, dict[str, int]] = {}
    dim_labels: dict[str, str] = {}
    dims_basis = 0
    rubrics: dict[str, int] = {}
    recent_rows: list[dict[str, Any]] = []

    for row in rows:
        if row.get("has_result") and not row.get("valid"):
            unreadable += 1                     # counted, never classified
            continue
        shown = displayed(row)
        if shown is None:
            without += 1                        # evaluation off for this answer, or no stored result at all
            continue
        assessed += 1
        st = shown["status"]
        status[st] += 1
        if shown["label"] == NFE:
            nfe += 1
        rid = row.get("rubric_id") if isinstance(row.get("rubric_id"), str) and row.get("rubric_id") else "unknown"
        rubrics[rid] = rubrics.get(rid, 0) + 1
        if shown["accepted"] and shown["score"] is not None:
            scores.append(shown["score"])
            buckets[_bucket_index(shown["score"])][st] += 1
        # the page's `decided` rule: the individual checks belong with a decided (or partly decided) result only
        if shown["accepted"] and (st in ("pass", "fail") or shown["label"] == NFE):
            dims_basis += 1
            for d in row.get("dims") or ():
                if not isinstance(d, dict) or not isinstance(d.get("dimension"), str) or d.get("state") not in DIM_STATES:
                    continue
                key = d["dimension"]
                counts = dim_counts.setdefault(key, {s: 0 for s in DIM_STATES})
                counts[d["state"]] += 1
                if key not in dim_labels and isinstance(d.get("label"), str) and d["label"]:
                    dim_labels[key] = d["label"]        # rows are newest first: the first label seen is the latest
        if len(recent_rows) < recent:
            recent_rows.append({
                "conversation_id": row.get("conversation_id"), "turn_id": row.get("turn_id"),
                "question": _cut(row.get("asked") if row.get("asked") is not None else row.get("result_question"),
                                 QUESTION_CHARS),
                "status": st, "label": shown["label"], "score": shown["score"],
                "explanation": _cut(shown["explanation"], EXPLANATION_CHARS), "created_at": row.get("created_at"),
            })

    keys = [k for k in order] + sorted(k for k in dim_counts if k not in order)
    dim_rows = []
    for key in keys:
        counts = dim_counts.get(key, {s: 0 for s in DIM_STATES})
        dim_rows.append({"dimension": key, "label": rubric_labels.get(key) or dim_labels.get(key) or key,
                         **counts, "total": sum(counts.values())})

    when = now or datetime.now(timezone.utc)
    return {
        "version": 1,
        "generated_at": when.isoformat(timespec="milliseconds"),
        "basis": BASIS,
        "turns": {"answered": answered, "assessed": assessed, "without_evaluation": without,
                  "failed": int(payload.get("failed") or 0), "unreadable": unreadable, "limit": limit,
                  "truncated": answered > len(rows)},
        "status": {**status, "not_fully_evaluated": nfe},
        "scores": {"scored": len(scores), "median": _median(scores), "min": min(scores) if scores else None,
                   "max": max(scores) if scores else None, "buckets": buckets},
        "dimensions": {"basis": dims_basis, "states": list(DIM_STATES), "rows": dim_rows},
        "rubrics": rubrics,
        "recent": recent_rows,
    }
