"""The per-question evaluation status shown with a live answer.

A reading of `AccuracyAssessment.to_dict()`, never a second judgement: every
state here is one the evaluator already decided. What this module adds is the
one-word status a reader sees first, and the rule for it is deliberately
stricter than any single dimension:

    PASS            the assessment was evaluated, the answer verdict is correct
                    (or a correct refusal), and EVERY dimension passed or did not
                    apply. Substantive correctness alone is not a pass: a right
                    rule under a wrong citation, or a missing requirement, fails.
    FAIL            the assessment was evaluated and a dimension failed or was
                    only partial, or the answer verdict is incorrect, partial,
                    off-topic or an incorrect refusal.
    NOT EVALUATED   everything else: no assessment, the evaluator abstained or
                    failed, the answer states no regulatory requirement, the
                    metadata is incomplete, or it is not this question's. When
                    nothing failed but some checks could not be decided, it is
                    "not fully evaluated" - never a pass.

The assessment is the live evidence assessment of this one answer
(`regulus_live_evidence_assessment_v2`): it compares the answer with the
regulatory evidence retrieved for it. No reference answer is involved, and it
is not the 300-question acceptance-test result.
"""

from __future__ import annotations

from typing import Any

from regulus.accuracy import rubric as R

PASS = "pass"
FAIL = "fail"
NOT_EVALUATED = "not_evaluated"

LABEL = {PASS: "PASS", FAIL: "FAIL", NOT_EVALUATED: "NOT EVALUATED"}
NOT_FULLY_EVALUATED = "NOT FULLY EVALUATED"

STATE_LABEL = {R.PASS: "Pass", R.FAIL: "Fail", R.PARTIAL: "Partial", R.NOT_ESTABLISHED: "Not established",
               R.NOT_APPLICABLE: "Not applicable"}

_PASSING_VERDICTS = frozenset({"correct", "abstention_correct"})
_FAILING_VERDICTS = frozenset({"incorrect", "partial", "off_topic", "abstention_incorrect"})

BASIS = ("Live evidence assessment of this one answer: it is compared with the regulatory evidence retrieved for "
         "it. No reference answer is used, and this is not the 300-question acceptance-test result.")
_MAX_EXPLANATION = 400


def _dimension(dims: dict[str, dict], name: str) -> dict[str, Any] | None:
    d = dims.get(name)
    if d is None:
        return None
    return {"state": d["state"], "label": STATE_LABEL[d["state"]], "detail": str(d.get("detail") or "")}


def _short(text: Any) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= _MAX_EXPLANATION else text[: _MAX_EXPLANATION - 1].rstrip() + "…"


def question_review(assessment: Any, *, question: str) -> dict[str, Any]:
    """The status to display for `question`, from its own assessment dict."""

    def out(status: str, explanation: str, *, label: str | None = None, dims: dict[str, dict] | None = None,
            score: int | None = None) -> dict[str, Any]:
        dims = dims or {}
        return {
            "question": question,
            "status": status,
            "label": label or LABEL[status],
            "substantive_correctness": _dimension(dims, R.SUBSTANTIVE),
            "citation_correctness": _dimension(dims, R.CITATION),
            "explanation": _short(explanation),
            # the evaluator's own 0-100 deduction score; shown only as a detail, never as accuracy
            "live_check_score": score,
            "rubric_id": R.RUBRIC_ID,
            "basis": BASIS,
        }

    if not isinstance(assessment, dict):
        return out(NOT_EVALUATED, "No evaluation result was returned for this answer.")
    checked = assessment.get("checked") if isinstance(assessment.get("checked"), dict) else {}
    if checked.get("question") is not None and checked.get("question") != question:
        return out(NOT_EVALUATED, "The evaluation result does not belong to this question, so it is not shown.")
    status = assessment.get("status")
    reason = assessment.get("reason") or ""
    if status == R.ERROR:
        return out(NOT_EVALUATED, f"The evaluator failed, so this answer was not evaluated. {reason}")
    if status == R.NOT_SCORED:
        return out(NOT_EVALUATED, reason or "The answer states no regulatory requirement, so there is nothing to evaluate.")
    if status == R.UNABLE:
        return out(NOT_EVALUATED, reason or "Not enough could be established from the retrieved evidence.")
    if status != R.EVALUATED:
        return out(NOT_EVALUATED, "The evaluation result is incomplete, so it is not shown.")

    dims: dict[str, dict] = {}
    for d in assessment.get("dimensions") or ():
        if isinstance(d, dict) and d.get("dimension") in R.DIMENSIONS and d.get("state") in R.STATES:
            dims[d["dimension"]] = d
    verdict = (assessment.get("answer_verdict") or {}).get("verdict") if isinstance(assessment.get("answer_verdict"), dict) else None
    score = assessment.get("accuracy")
    if set(dims) != set(R.DIMENSIONS) or verdict is None or not isinstance(score, int):
        return out(NOT_EVALUATED, "The evaluation result is incomplete, so it is not shown.")

    failed = [d for d in R.DIMENSIONS if dims[d]["state"] in (R.FAIL, R.PARTIAL)]
    if failed or verdict in _FAILING_VERDICTS:
        # the evaluator's reason leads with the answer verdict, which can be
        # "Correct" while a check still failed: name the failed checks instead
        why = reason if verdict in _FAILING_VERDICTS else "; ".join(
            f"{R.LABELS[d]} {STATE_LABEL[dims[d]['state']].lower()}: {dims[d].get('detail') or ''}".rstrip(": ")
            for d in failed)
        return out(FAIL, why, dims=dims, score=score)
    undecided = [R.LABELS[d] for d in R.DIMENSIONS if dims[d]["state"] == R.NOT_ESTABLISHED]
    if undecided or verdict not in _PASSING_VERDICTS:
        why = (f"No check failed, but these could not be decided from the retrieved evidence: {', '.join(undecided)}."
               if undecided else f"No check failed, but the answer verdict is '{verdict}'.")
        return out(NOT_EVALUATED, why, label=NOT_FULLY_EVALUATED, dims=dims, score=score)
    return out(PASS, reason, dims=dims, score=score)
