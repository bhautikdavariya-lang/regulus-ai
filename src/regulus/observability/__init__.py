"""Failure observatory (Stage 4): taxonomy, evidence sufficiency, traces and diagnosis.

Diagnostic only. Nothing in this package changes an answer; it reads what the
pipeline produced and records where, if anywhere, the answer went wrong.
See docs/failure_observatory_stage4.md.
"""

from regulus.observability.diagnose import diagnose
from regulus.observability.sufficiency import STATES as SUFFICIENCY_STATES, assess as assess_sufficiency
from regulus.observability.taxonomy import FAILURE_CLASSES, FailureRecord
from regulus.observability.trace import build_trace

__all__ = ["FAILURE_CLASSES", "FailureRecord", "SUFFICIENCY_STATES", "assess_sufficiency", "build_trace", "diagnose"]
