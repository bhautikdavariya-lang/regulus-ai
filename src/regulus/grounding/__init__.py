"""Stage 13: deterministic grounding of requested regulatory identifiers.

Answers "does this identifier exist in the verified database?" and "does the
retrieved context actually carry it?" without asking the language model.
Read-only; it never writes and never reaches outside the database.
"""

from regulus.grounding.gate import (
    PASS,
    REASON_ABSENT,
    REASON_CONTEXT_MISMATCH,
    REASON_PARAGRAPH_ABSENT,
    REASON_RESERVED,
    REFUSE,
    GroundingConfig,
    GroundingDecision,
    GroundingGate,
    match_results,
    refusal_text,
)
from regulus.grounding.identifiers import (
    DOCKET,
    PARAGRAPH,
    PART,
    SECTION,
    CorpusIdentifierIndex,
    DatabaseIdentifierIndex,
    IdentifierIndex,
    IdentifierVerification,
    RequestedIdentifier,
    extract_identifier,
    extract_identifiers,
    verify_identifier,
    verify_question,
)

__all__ = [
    "CorpusIdentifierIndex",
    "DOCKET",
    "DatabaseIdentifierIndex",
    "GroundingConfig",
    "GroundingDecision",
    "GroundingGate",
    "IdentifierIndex",
    "IdentifierVerification",
    "PARAGRAPH",
    "PART",
    "PASS",
    "REASON_ABSENT",
    "REASON_CONTEXT_MISMATCH",
    "REASON_PARAGRAPH_ABSENT",
    "REASON_RESERVED",
    "REFUSE",
    "RequestedIdentifier",
    "SECTION",
    "extract_identifier",
    "extract_identifiers",
    "match_results",
    "refusal_text",
    "verify_identifier",
    "verify_question",
]
