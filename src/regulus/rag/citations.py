"""Answer citations traced to selected evidence (Stage 4).

A citation is listed because the answer used it, or because it is the
authoritative EXACT source of a requested provision the answer addresses.
No other context source is listed, and no marker is ever added to the
answer text. Each citation records the source's tier and the requirements
it relates to, so a claim can be traced:

    [n] in the answer -> SOURCE n -> evidence tier -> requirement(s)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from regulus.rag.generation import GenerationPackage
from regulus.rag.validation import MARK_RE
from regulus.retrieval.evidence import TIER_EXACT

ROLE_CITED = "cited"                 # the answer carries [n] for this source
ROLE_AUTHORITATIVE = "authoritative"  # EXACT source of an addressed provision the answer did not mark
ROLE_CONTEXT = "context"             # legacy path: listed because it was in the context


@dataclass(frozen=True)
class RagCitation:
    index: int                      # first SOURCE number carrying this citation label
    indices: tuple[int, ...]        # every SOURCE number with this label that the citation covers
    label: str
    corpus: str
    url: str | None
    cited_in_answer: bool
    citation: dict[str, Any] = field(default_factory=dict)
    tier: str | None = None
    requirement_ids: tuple[str, ...] = ()
    role: str = ROLE_CONTEXT

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "indices": list(self.indices),
            "label": self.label,
            "corpus": self.corpus,
            "url": self.url,
            "cited_in_answer": self.cited_in_answer,
            "citation": self.citation,
            "tier": self.tier,
            "requirement_ids": list(self.requirement_ids),
            "role": self.role,
        }


def build_answer_citations(answer: str, package: GenerationPackage, addressed: tuple[str, ...] = ()) -> list[RagCitation]:
    """Citations for a Stage 4 answer.

    `addressed` are the requirement ids the validator found the answer
    addresses; their EXACT sources are listed as authoritative even when the
    model omitted the marker, so the requirement -> evidence link survives.
    """
    marks = [int(m) for m in MARK_RE.findall(answer or "")]
    by_index = {s.index: s for s in package.sources}
    cited_indices = [i for i in dict.fromkeys(marks) if i in by_index]
    authoritative = [
        s.index for rid in addressed for s in package.exact_sources_for(rid) if s.index not in cited_indices
    ]
    wanted = cited_indices + [i for i in dict.fromkeys(authoritative)]
    grouped: dict[str, list[int]] = {}
    for i in wanted:
        grouped.setdefault(by_index[i].citation, []).append(i)
    out: list[RagCitation] = []
    for label, indices in grouped.items():
        first = by_index[min(indices)]
        cited = any(i in cited_indices for i in indices)
        rids = tuple(dict.fromkeys(r for i in indices for r in by_index[i].requirement_ids))
        out.append(RagCitation(
            index=min(indices),
            indices=tuple(sorted(indices)),
            label=label,
            corpus=first.corpus,
            url=first.url,
            cited_in_answer=cited,
            citation=dict(first.citation_fields),
            tier=first.tier,
            requirement_ids=rids,
            role=ROLE_CITED if cited else ROLE_AUTHORITATIVE,
        ))
    return sorted(out, key=lambda c: c.index)


def citation_support(answer: str, package: GenerationPackage) -> dict[str, Any]:
    """How the answer's markers relate to the requested provisions: for diagnostics."""
    by_index = {s.index: s for s in package.sources}
    marks = [int(m) for m in MARK_RE.findall(answer or "")]
    counts = {"exact": 0, "structural": 0, "supporting": 0, "discovery": 0, "invalid": 0}
    for i in marks:
        s = by_index.get(i)
        counts["invalid" if s is None else s.tier] += 1
    exact_cited = {
        rid: any(i in by_index and rid in by_index[i].requirement_ids and by_index[i].tier == TIER_EXACT for i in marks)
        for rid in package.satisfied_ids
    }
    return {"markers": marks, "by_tier": counts, "exact_source_cited_for": exact_cited}
