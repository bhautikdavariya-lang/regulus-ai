"""Live answer-accuracy assessment (observer only).

An answer that has already been produced, validated and delivered is compared
against the authoritative regulatory evidence that was retrieved for its own
question. Nothing here retrieves, generates, repairs or suppresses: the
evaluator takes the finished answer and the pipeline's own reports and returns
an assessment object.

    from regulus.accuracy import evaluate_safely
    assessment = evaluate_safely(question, out.answer, package=out.package,
                                 validation=out.validation, coverage=out.coverage)

The rubric it applies, `regulus_live_evidence_assessment_v2`, is NOT the
acceptance benchmark's `regulus_substantive_rubric_v1`; see rubric.py for the
difference and for why this evaluator abstains as often as it does.
"""

from regulus.accuracy.rubric import (
    EVALUATED,
    FAIL,
    NOT_APPLICABLE,
    NOT_ESTABLISHED,
    NOT_SCORED,
    PARTIAL,
    PASS,
    RUBRIC_ID,
    UNABLE,
    ERROR as EVALUATOR_ERROR,
)
from regulus.accuracy.attribution import ATTRIBUTED_EXACT, ATTRIBUTED_OTHER, UNATTRIBUTED, attribute
from regulus.accuracy.evaluator import AccuracyAssessment, DimensionResult, evaluate, evaluate_safely

__all__ = [
    "ATTRIBUTED_EXACT",
    "ATTRIBUTED_OTHER",
    "UNATTRIBUTED",
    "AccuracyAssessment",
    "DimensionResult",
    "EVALUATED",
    "EVALUATOR_ERROR",
    "FAIL",
    "NOT_APPLICABLE",
    "NOT_ESTABLISHED",
    "NOT_SCORED",
    "PARTIAL",
    "PASS",
    "RUBRIC_ID",
    "UNABLE",
    "attribute",
    "evaluate",
    "evaluate_safely",
]
