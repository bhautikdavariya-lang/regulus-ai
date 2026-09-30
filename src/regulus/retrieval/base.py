"""Retriever protocol and filter model shared by all retriever implementations."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from typing import Any, Protocol

from regulus.retrieval.models import CORPORA, RetrievalResult


class FilterError(ValueError):
    """Raised for unknown filter names or malformed filter values."""


_PART_RE = re.compile(r"^\d{1,4}$")
_SECTION_RE = re.compile(r"^\d{1,4}\.\d{1,4}[a-z]?$")
_SUBCHAPTER_RE = re.compile(r"^[A-L]$")

ECFR_FILTERS = ("part", "section", "subchapter")
GUIDANCE_FILTERS = ("retrievable", "sector", "center", "status", "anchor_part", "anchor_section")


@dataclass(frozen=True)
class Filters:
    """Optional metadata filters. Every field maps to a real, indexed column.

    eCFR (cfr_records):      part, section, subchapter
    Guidance (fda_guidance): retrievable, sector, center, status, anchor_part, anchor_section

    retrievable defaults to True so held-out guidance documents are excluded
    unless the caller asks for them (None = no filter).
    """

    part: str | None = None
    section: str | None = None
    subchapter: str | None = None
    retrievable: bool | None = True
    sector: str | None = None
    center: str | None = None
    status: str | None = None
    anchor_part: str | None = None
    anchor_section: str | None = None

    def __post_init__(self) -> None:
        for name in ("part", "section", "subchapter", "sector", "center", "status", "anchor_part", "anchor_section"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise FilterError(f"filter {name!r} must be a non-empty string or None")
            object.__setattr__(self, name, value.strip())
        if self.part is not None and not _PART_RE.match(self.part):
            raise FilterError(f"filter 'part' must be a part number such as '820', got {self.part!r}")
        if self.anchor_part is not None and not _PART_RE.match(self.anchor_part):
            raise FilterError(f"filter 'anchor_part' must be a part number such as '820', got {self.anchor_part!r}")
        if self.section is not None and not _SECTION_RE.match(self.section):
            raise FilterError(f"filter 'section' must look like '820.10', got {self.section!r}")
        if self.anchor_section is not None and not _SECTION_RE.match(self.anchor_section):
            raise FilterError(f"filter 'anchor_section' must look like '820.10', got {self.anchor_section!r}")
        if self.subchapter is not None:
            object.__setattr__(self, "subchapter", self.subchapter.upper())
            if not _SUBCHAPTER_RE.match(self.subchapter):
                raise FilterError(f"filter 'subchapter' must be a single letter A-L, got {self.subchapter!r}")
        if self.retrievable is not None and not isinstance(self.retrievable, bool):
            raise FilterError("filter 'retrievable' must be True, False or None")

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "Filters":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(kwargs) - known)
        if unknown:
            raise FilterError(f"unknown filter(s): {', '.join(unknown)}; allowed: {', '.join(sorted(known))}")
        return cls(**kwargs)

    def has_ecfr_filters(self) -> bool:
        return any(getattr(self, n) is not None for n in ECFR_FILTERS)

    def has_guidance_filters(self) -> bool:
        return any(getattr(self, n) is not None for n in ("sector", "center", "status", "anchor_part", "anchor_section")) or self.retrievable is not True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise_corpus(corpus: str | None) -> tuple[str, ...]:
    """None -> all corpora; a name -> that corpus; validates the name."""
    if corpus is None or corpus == "all":
        return CORPORA
    if corpus not in CORPORA:
        raise ValueError(f"unknown corpus {corpus!r}; expected one of {CORPORA} or None")
    return (corpus,)


class Retriever(Protocol):
    """Pipeline-agnostic search interface. Semantic and hybrid retrievers
    implement the same signature later."""

    def search(
        self,
        query: str,
        *,
        corpus: str | None = None,
        top_k: int = 10,
        filters: Filters | None = None,
    ) -> list[RetrievalResult]: ...
