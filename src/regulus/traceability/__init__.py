"""Traceability: the exact evidence an answer was generated from.

`regulus.traceability.evidence` captures, persists and replays the evidence
package that was placed in the model's prompt, so that anything judging an
answer afterwards (the accuracy evaluator) judges it against exactly that
text. It imports nothing from `regulus.rag` or `regulus.accuracy`: the
pipeline captures, the evaluator replays, and neither depends on the other.
"""

from regulus.traceability.evidence import (
    EVIDENCE_SCHEMA,
    EXACT,
    LEGACY_RECONSTRUCTED,
    MISSING,
    PROVENANCES,
    EvidenceIntegrityError,
    EvidenceItem,
    EvidenceSnapshot,
    capture,
    capture_safely,
    fingerprint,
    load,
)

__all__ = [
    "EVIDENCE_SCHEMA",
    "EXACT",
    "LEGACY_RECONSTRUCTED",
    "MISSING",
    "PROVENANCES",
    "EvidenceIntegrityError",
    "EvidenceItem",
    "EvidenceSnapshot",
    "capture",
    "capture_safely",
    "fingerprint",
    "load",
]
