"""Failure taxonomy (Stage 4 failure observatory).

One place that names every way an answer can go wrong, the pipeline module
that owns it, and how a failure is recorded. A diagnosis is a claim about the
pipeline and must carry its evidence; when the evidence does not decide it,
the class is UNKNOWN / NEEDS_REVIEW, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# pipeline order: a failure's "first point of failure" is the earliest of these
MODULES = ("intent", "scope", "retrieval", "selection", "sufficiency", "answerability", "prompt", "generation", "validation",
           "repair", "citations", "presentation", "evaluation", "inference", "pipeline")


@dataclass(frozen=True)
class FailureClass:
    code: str
    name: str
    module: str
    definition: str


FAILURE_CLASSES: dict[str, FailureClass] = {c.code: c for c in (
    FailureClass("F01", "Intent classification failure", "intent", "The question type was misread, so the answer was organised for a different question."),
    FailureClass("F02", "Scope classification failure", "scope", "An out-of-scope question was treated as in scope, or the reverse."),
    FailureClass("F03", "Retrieval miss", "retrieval", "Evidence that answers the question exists in the database but was not among the retrieved candidates."),
    FailureClass("F04", "Retrieval ranking failure", "selection", "Relevant evidence was retrieved but not placed in the prompt (ordering, budget)."),
    FailureClass("F05", "Evidence insufficiency detection failure", "sufficiency", "The evidence could not support the requested answer and nothing detected that before or after generation."),
    FailureClass("F06", "Evidence interpretation failure", "generation", "Correct evidence was in the prompt but the model misread or misattributed it."),
    FailureClass("F07", "Unsupported generation", "generation", "The raw answer contains claims (figures, requirements, facts) not supported by the evidence given."),
    FailureClass("F08", "Regulatory qualifier failure", "generation", "A condition, exception or applicability limit was dropped or attached to the wrong requirement."),
    FailureClass("F09", "Citation attribution failure", "citations", "A claim cites a source that does not support it."),
    FailureClass("F10", "Validation false positive", "validation", "Validation rejected an acceptable answer."),
    FailureClass("F11", "Validation false negative", "validation", "Validation passed an answer that fails a checkable expectation."),
    FailureClass("F12", "Repair failure", "repair", "Repair ran and the result still fails, or is worse than the input."),
    FailureClass("F13", "Safe-fallback failure", "repair", "A fallback answer does not address the question (e.g. quotes unrelated text) or answers when it should decline."),
    FailureClass("F14", "Answer-structure failure", "presentation", "The answer is organised badly: row-by-row dumps, echoed question, misplaced markers."),
    FailureClass("F15", "Completeness failure", "generation", "A requested provision or an expected element is missing from the answer."),
    FailureClass("F16", "Model capability limitation", "generation", "The model fails even with exact evidence only (controlled condition), so context is not the cause."),
    FailureClass("F17", "Evaluation/data integrity issue", "evaluation", "The expectation or label itself is doubtful; the answer may be right."),
    FailureClass("F18", "Performance/inference failure", "inference", "Truncation, timeouts or degenerate decoding."),
    FailureClass("F19", "Pipeline/state/transformation failure", "pipeline", "A deterministic transformation changed a correct text into an incorrect one."),
    FailureClass("F20", "UI/presentation failure", "presentation", "The final answer is shown misleadingly (e.g. irrelevant text labelled as the requested provision)."),
    # Stage 5: the gate declined a question that was keyed to be answered, and its fallback does not meet the key
    FailureClass("F21", "Answerability false block", "answerability", "The answerability gate blocked generation for a question the evidence could answer."),
    FailureClass("UNKNOWN", "Unknown / needs review", "evaluation", "The evidence does not establish a cause; a person must look."),
)}

SEVERITIES = ("critical", "major", "minor")
# critical: an unsupported regulatory claim or out-of-scope content reaches the final answer
# major:    the final answer is wrong, misleading or incomplete for the question
# minor:    presentation or internal issues that do not change the final answer's substance

CONFIDENCE = ("proven", "probable", "needs_review")


@dataclass
class FailureRecord:
    question_id: str
    failure_class: str
    severity: str
    confidence: str
    evidence: list[str]
    module: str = ""
    primary: bool = False
    reproducible: bool | None = None
    regression_status: str = "baseline"
    notes: str = ""
    secondary_causes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.failure_class not in FAILURE_CLASSES:
            raise ValueError(f"unknown failure class {self.failure_class}")
        if self.severity not in SEVERITIES or self.confidence not in CONFIDENCE:
            raise ValueError("invalid severity or confidence")
        if not self.evidence:
            raise ValueError("a failure record must carry evidence")
        self.module = self.module or FAILURE_CLASSES[self.failure_class].module

    def to_dict(self) -> dict[str, Any]:
        c = FAILURE_CLASSES[self.failure_class]
        return {"question_id": self.question_id, "failure_class": self.failure_class, "name": c.name, "severity": self.severity,
                "confidence": self.confidence, "primary": self.primary, "module": self.module, "evidence": self.evidence,
                "secondary_causes": self.secondary_causes, "reproducible": self.reproducible,
                "regression_status": self.regression_status, "notes": self.notes}


def module_rank(code: str) -> int:
    return MODULES.index(FAILURE_CLASSES[code].module)
