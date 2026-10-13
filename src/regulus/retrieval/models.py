"""Serialisable result model for retrieved regulatory passages.

Deliberately contains no database identifiers, no user or session data and
no credentials. Everything here is safe to display, log at debug level, or
hand to an evaluation or generation pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CORPORA = ("ecfr", "fda_guidance")

METHOD_EXACT_CFR = "exact_cfr"
METHOD_EXACT_DOCKET = "exact_docket"
METHOD_FULL_TEXT = "full_text"
METHOD_FULL_TEXT_OR = "full_text_or"  # Stage 7 controlled OR fallback
METHOD_TRIGRAM = "trigram"
METHOD_DEFINITION = "definition"  # the CFR's own definition of a term a definitional question asks about
METHOD_SEMANTIC = "semantic"  # Stage 8 experiment; never used by LexicalRetriever
METHODS = (METHOD_EXACT_CFR, METHOD_EXACT_DOCKET, METHOD_FULL_TEXT, METHOD_FULL_TEXT_OR, METHOD_TRIGRAM, METHOD_SEMANTIC,
           METHOD_DEFINITION)


@dataclass(frozen=True)
class Citation:
    """Citation built from stored metadata only. Absent fields stay None."""

    corpus: str
    label: str
    url: str | None = None
    # eCFR
    title: str | None = None
    part: str | None = None
    section: str | None = None
    paragraph: str | None = None
    heading: str | None = None
    # FDA guidance
    document_title: str | None = None
    docket_number: str | None = None
    status: str | None = None
    issued_on: str | None = None
    center: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    corpus: str
    text: str
    heading: str | None
    relevance_score: float
    retrieval_method: str
    source_url: str | None
    citation: Citation
    metadata: dict[str, Any] = field(default_factory=dict)
    # every method that surfaced this passage; retrieval_method is the strongest
    methods: tuple[str, ...] = ()
    # natural, non-secret identity used for de-duplication (e.g. "ecfr:820.10:(b)(1):0")
    key: str = ""

    def __post_init__(self) -> None:
        if self.corpus not in CORPORA:
            raise ValueError(f"unknown corpus {self.corpus!r}")
        if self.retrieval_method not in METHODS:
            raise ValueError(f"unknown retrieval method {self.retrieval_method!r}")
        if not self.methods:
            self.methods = (self.retrieval_method,)
        if not self.key:
            raise ValueError("result key must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "text": self.text,
            "heading": self.heading,
            "relevance_score": round(float(self.relevance_score), 4),
            "retrieval_method": self.retrieval_method,
            "methods": list(self.methods),
            "source_url": self.source_url,
            "citation": self.citation.to_dict(),
            "metadata": dict(self.metadata),
            "key": self.key,
        }
