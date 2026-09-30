"""Evidence sufficiency (Stage 4, diagnostic only: nothing here changes an answer).

Four different situations look alike from the outside and must be told apart:

    EVIDENCE_SUFFICIENT    the requested provisions are present, and if the question asks for a
                           specific kind of value, the evidence contains values of that kind
    EVIDENCE_PARTIAL       some requested provisions are present, others were not found
    EVIDENCE_INSUFFICIENT  evidence exists but cannot support the requested claim: the question asks
                           for a kind of value (temperature, date, duration, amount, form number, count)
                           that no supplied source contains, or only broad-search sources were found
    EVIDENCE_NOT_FOUND     nothing that is the requested provision was found (or nothing at all)
    UNKNOWN                a general question with ordinary sources: whether they answer it cannot be
                           decided by rule, only by reading

The typed-value test is general (a kind of value, never a particular number or
topic). Its limits are documented: it cannot tell whether a source that
contains *some* date contains *the* date asked for, and it does not judge
whether a topical source answers a general question. SUFFICIENT therefore
means "nothing checkable is missing", not "the evidence answers the question".
"""

from __future__ import annotations

import re
from typing import Any

SUFFICIENT = "EVIDENCE_SUFFICIENT"
PARTIAL = "EVIDENCE_PARTIAL"
INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
NOT_FOUND = "EVIDENCE_NOT_FOUND"
UNKNOWN = "UNKNOWN"
STATES = (SUFFICIENT, PARTIAL, INSUFFICIENT, NOT_FOUND, UNKNOWN)

# The value-kind abstraction is shared with the runtime answerability gate (Stage 5)
from regulus.rag.evidence_values import VALUE_KINDS as _KINDS, evidence_has_value, requested_value_kind  # noqa: E402

# (kind, asks, evidence) triples, kept for existing callers of this module
VALUE_KINDS = tuple((k, a, v) for k, a, v, _ in _KINDS)


def assess(question: str, package, coverage, *, no_context: bool, deterministic_action: str | None = None) -> dict[str, Any]:
    """Sufficiency of the evidence placed in the prompt, with the reasons that decided it."""
    reasons: list[str] = []
    kind = requested_value_kind(question)
    texts = [s.text for s in (package.sources if package is not None else ())]
    has_value = evidence_has_value(kind, texts) if kind and texts else None

    def out(state: str) -> dict[str, Any]:
        return {"state": state, "reasons": reasons, "requested_value_kind": kind, "value_kind_in_evidence": has_value,
                "sources": len(texts)}

    if deterministic_action == "refuse_out_of_scope":
        reasons.append("declined as out of scope before evidence was used")
        return out(UNKNOWN)
    if no_context or not texts:
        reasons.append("no source was placed in the prompt")
        return out(NOT_FOUND)
    explicit = coverage is not None and coverage.explicit
    if explicit:
        if not coverage.satisfied_ids:
            reasons.append("no requested provision has exact evidence: " + ", ".join(coverage.missing_labels))
            return out(NOT_FOUND)
        if coverage.missing_ids:
            reasons.append("requested provisions not found: " + ", ".join(coverage.missing_labels))
            return out(PARTIAL)
    if kind and has_value is False:
        reasons.append(f"the question asks for a {kind.replace('_', ' ')} and no supplied source contains one")
        return out(INSUFFICIENT)
    if not explicit:
        if package is not None and package.sources and all(s.tier == "discovery" for s in package.sources):
            reasons.append("no provision was requested and every source came from a broad (fallback) search")
            return out(INSUFFICIENT)
        reasons.append("general question: whether the retrieved sources answer it is not decidable by rule")
        return out(UNKNOWN)
    reasons.append("every requested provision has exact evidence" + (f"; the evidence contains a {kind}" if kind else ""))
    return out(SUFFICIENT)
