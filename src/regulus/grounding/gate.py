"""The Stage 13 grounding gate: decide, before the model is called, whether
the retrieved context can support an answer about the requested identifier.

The gate is deliberately narrow. It acts only when a question names an
identifier the Stage 5 parser recognises, and it makes exactly two kinds of
decision:

  * the identifier is verified absent from the database -> refuse
  * the identifier exists but nothing retrieved carries that identifier ->
    refuse (configurable)

Everything else passes through untouched, so natural-language questions keep
the existing Stage 7 retrieval behaviour. Structured identifiers are compared
structurally: similarity scores never decide source identity, because
21 CFR 112.45 is not 21 CFR 314.999 however similar their text.

The gate does not replace what the model must learn. Stage 13 training data
teaches the same judgments; the gate removes the failure mode that Stage 12
showed the model cannot be trusted with on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from regulus.grounding.identifiers import (
    DOCKET,
    NOT_IN_SNAPSHOT,
    OUTSIDE_TITLE_21,
    PARAGRAPH,
    PARAGRAPH_NOT_IN_SECTION,
    PART,
    RESERVED,
    IdentifierIndex,
    IdentifierVerification,
    RequestedIdentifier,
    extract_identifier,
    verify_identifier,
)

PASS = "pass"
REFUSE = "refuse"

# why the gate refused
REASON_ABSENT = "identifier_not_in_snapshot"
REASON_RESERVED = "identifier_reserved"
REASON_PARAGRAPH_ABSENT = "paragraph_not_in_section"
REASON_CONTEXT_MISMATCH = "context_does_not_establish_identifier"


@dataclass(frozen=True)
class GroundingConfig:
    """Off by default so existing pipelines are bit-for-bit unchanged until a
    caller opts in."""

    enabled: bool = False
    # refuse when the database shows the requested identifier is not live content
    refuse_unverified_identifier: bool = True
    # refuse when the identifier exists but no retrieved passage carries it
    refuse_context_mismatch: bool = True
    # only apply the mismatch rule to section/paragraph/docket requests; a
    # part-level question ("what does Part 211 cover") is answerable from any
    # section of that part, which the matcher already accepts
    mismatch_kinds: tuple[str, ...] = ("section", "paragraph", "docket")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "refuse_unverified_identifier": self.refuse_unverified_identifier,
            "refuse_context_mismatch": self.refuse_context_mismatch,
            "mismatch_kinds": list(self.mismatch_kinds),
        }


@dataclass(frozen=True)
class GroundingDecision:
    action: str
    reason: str | None = None
    answer: str | None = None
    verification: IdentifierVerification | None = None
    matched_keys: tuple[str, ...] = ()
    checked: bool = False

    @property
    def refused(self) -> bool:
        return self.action == REFUSE

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "action": self.action,
            "reason": self.reason,
            "matched_keys": list(self.matched_keys),
            "verification": self.verification.to_dict() if self.verification else None,
        }


# ------------------------------------------------------------- matching


def _paragraph_covers(requested: str, found: str) -> bool:
    """Does a retrieved paragraph establish the requested one?

    "(b)" is established by "(b)", "(b)(1)", "(b)(2)(i)"; "(b)(2)" is not
    established by "(b)" alone, because the parent does not contain the child's
    text. This is the Stage 13 partial-context rule.
    """
    if not requested:
        return True
    return found == requested or found.startswith(requested)


def match_results(identifier: RequestedIdentifier, results) -> tuple[str, ...]:
    """Keys of the retrieved passages that actually carry the requested
    identifier. Structural comparison only."""
    matched = []
    for r in results:
        c = r.citation
        if identifier.kind == DOCKET:
            if (c.docket_number or "").upper() == str(identifier.docket).upper():
                matched.append(r.key)
            continue
        if r.corpus != "ecfr":
            continue
        if identifier.kind == PART:
            if c.part == identifier.part:
                matched.append(r.key)
            continue
        if c.section != identifier.section:
            continue
        if identifier.kind == PARAGRAPH and not _paragraph_covers(identifier.paragraph, c.paragraph or ""):
            continue
        matched.append(r.key)
    return tuple(matched)


# ------------------------------------------------------------- refusals


def refusal_text(verification: IdentifierVerification, reason: str, snapshot_date: str | None = None) -> str:
    """Refusal wording in the project's existing register, matching the
    phrasing the Stage 11/13 training answers use."""
    label = verification.normalized_identifier
    snap = f" (Title 21 snapshot dated {snapshot_date})" if snapshot_date else ""
    if reason == REASON_ABSENT:
        if verification.identifier.kind == DOCKET:
            return (
                f"I could not find an FDA guidance document with docket number {label} in the available "
                "guidance data, so I cannot summarize it or state what it recommends."
            )
        return (
            f"I could not verify {label} in the available eCFR data{snap}, so I cannot provide a reliable "
            "statement of its requirements."
        )
    if reason == REASON_RESERVED:
        return (
            f"{label} is reserved in the available eCFR data{snap}: it carries no regulatory text, "
            "so there are no requirements to state."
        )
    if reason == REASON_PARAGRAPH_ABSENT:
        facts = verification.record or {}
        paragraphs = ", ".join(facts.get("paragraphs", [])[:12])
        listing = f" Its paragraphs are {paragraphs}." if paragraphs else ""
        section = verification.identifier.section
        return (
            f"The available eCFR data contains 21 CFR {section} but no paragraph "
            f"{verification.identifier.paragraph}.{listing} I cannot provide a requirement for {label}."
        )
    return (
        f"The retrieved sources do not include {label}, so they do not establish what it provides. "
        "I cannot answer this from the available context."
    )


# ----------------------------------------------------------------- gate


class GroundingGate:
    """Applies the grounding rules. Holds no state beyond its index."""

    def __init__(self, index: IdentifierIndex, config: GroundingConfig | None = None, snapshot_date: str | None = None) -> None:
        self.index = index
        self.config = config or GroundingConfig(enabled=True)
        self.snapshot_date = snapshot_date

    def check_identifier(self, question: str) -> tuple[IdentifierVerification | None, GroundingDecision]:
        """Pre-retrieval check: can this identifier be answered about at all?"""
        if not self.config.enabled:
            return None, GroundingDecision(PASS, checked=False)
        identifier = extract_identifier(question)
        if identifier is None:
            return None, GroundingDecision(PASS, reason="no_identifier_in_question", checked=True)
        verification = verify_identifier(identifier, self.index)
        if verification is None or not self.config.refuse_unverified_identifier:
            return verification, GroundingDecision(PASS, checked=True, verification=verification)
        if verification.reason == OUTSIDE_TITLE_21:
            # absence cannot be established for titles outside the corpus
            return verification, GroundingDecision(PASS, reason=OUTSIDE_TITLE_21, checked=True, verification=verification)
        if verification.verified_absent:
            reason = {
                NOT_IN_SNAPSHOT: REASON_ABSENT,
                RESERVED: REASON_RESERVED,
                PARAGRAPH_NOT_IN_SECTION: REASON_PARAGRAPH_ABSENT,
            }.get(verification.reason, REASON_ABSENT)
            return verification, GroundingDecision(
                REFUSE,
                reason=reason,
                answer=refusal_text(verification, reason, self.snapshot_date),
                verification=verification,
                checked=True,
            )
        return verification, GroundingDecision(PASS, reason="identifier_verified", checked=True, verification=verification)

    def check_context(self, verification: IdentifierVerification | None, results) -> GroundingDecision:
        """Post-retrieval check: does anything retrieved carry the identifier?"""
        if not self.config.enabled or verification is None or not verification.exists:
            return GroundingDecision(PASS, checked=False)
        identifier = verification.identifier
        matched = match_results(identifier, results)
        if matched:
            return GroundingDecision(PASS, reason="context_matches_identifier", matched_keys=matched, verification=verification, checked=True)
        if not self.config.refuse_context_mismatch or identifier.kind not in self.config.mismatch_kinds:
            return GroundingDecision(PASS, reason="mismatch_allowed_for_kind", verification=verification, checked=True)
        return GroundingDecision(
            REFUSE,
            reason=REASON_CONTEXT_MISMATCH,
            answer=refusal_text(verification, REASON_CONTEXT_MISMATCH, self.snapshot_date),
            verification=verification,
            checked=True,
        )

    def describe(self) -> dict[str, Any]:
        return {"grounding": self.config.to_dict(), "index": type(self.index).__name__, "snapshot_date": self.snapshot_date}
