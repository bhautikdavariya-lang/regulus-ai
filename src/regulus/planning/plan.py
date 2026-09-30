"""QueryPlan: the structured statement of what a question asks for (Stage 1).

The plan is built from the deterministic reference scanner
(regulus.retrieval.references) and the existing query classification. It
holds one Requirement per requested provision, in the order the user named
them, with ranges expanded and duplicates removed. It says nothing about
whether those provisions exist or what evidence supports them: retrieval,
coverage, grounding and generation consume the plan in later stages.

Plan kinds (deterministic, from the requirements alone):
    single_provision    one requirement
    range               several requirements in one section, at least one from a range
    multi_provision     several requirements in one section (a list)
    multiple_reference  requirements spanning more than one section or part
    general             a question with no CFR reference
    unknown             an empty question
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from regulus.retrieval.query import QueryType, classify, parse_docket, _GUIDANCE_RE
from regulus.retrieval.references import CfrReference, ReferenceScan, normalise_text, scan_references

KIND_SINGLE = "single_provision"
KIND_RANGE = "range"
KIND_MULTI = "multi_provision"
KIND_MULTIPLE_REFERENCE = "multiple_reference"
KIND_GENERAL = "general"
KIND_UNKNOWN = "unknown"
PLAN_KINDS = (KIND_SINGLE, KIND_RANGE, KIND_MULTI, KIND_MULTIPLE_REFERENCE, KIND_GENERAL, KIND_UNKNOWN)


@dataclass(frozen=True)
class Requirement:
    """One atomic requested provision."""

    id: str                     # "r1", "r2", ... in question order
    order: int                  # 1-based position among the requirements
    reference: CfrReference     # normalised identifier (title, part, section, paragraph)
    raw: str                    # the text it came from: the mention, or the whole range for expansions
    origin: str                 # "explicit" | "continuation" | "range_expansion"
    mention: int                # index into QueryPlan.scan.mentions

    @property
    def canonical(self) -> str:
        return self.reference.canonical

    @property
    def key(self) -> tuple[str, str, str | None, str]:
        return self.reference.key

    @property
    def title(self) -> str:
        return self.reference.title

    @property
    def part(self) -> str:
        return self.reference.part

    @property
    def section(self) -> str | None:
        return self.reference.section

    @property
    def paragraph_path(self) -> str:
        return self.reference.paragraph_path

    @property
    def level(self) -> str:
        return self.reference.level

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "order": self.order,
            "canonical": self.canonical,
            "title": self.title,
            "part": self.part,
            "section": self.section,
            "paragraph_path": self.paragraph_path,
            "level": self.level,
            "raw": self.raw,
            "origin": self.origin,
            "mention": self.mention,
        }


@dataclass(frozen=True)
class QueryPlan:
    question: str                           # as received
    normalized_question: str                # whitespace-normalised; scan spans refer to this
    query_type: QueryType                   # existing classification (EXACT_CFR, GUIDANCE_SEARCH, ...)
    kind: str                               # one of PLAN_KINDS
    requirements: tuple[Requirement, ...]   # ordered, de-duplicated, ranges expanded
    docket: str | None
    guidance_requested: bool
    scan: ReferenceScan                     # mentions, ranges and notes, for inspection
    notes: tuple[str, ...]

    @property
    def references(self) -> tuple[CfrReference, ...]:
        return tuple(r.reference for r in self.requirements)

    @property
    def sections(self) -> tuple[str, ...]:
        """Distinct sections (or "part N") the requirements fall under, in order."""
        out: list[str] = []
        for r in self.requirements:
            label = r.section if r.section is not None else f"part {r.part}"
            label = f"{r.title}:{label}"
            if label not in out:
                out.append(label)
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "normalized_question": self.normalized_question,
            "query_type": self.query_type.value,
            "kind": self.kind,
            "requirements": [r.to_dict() for r in self.requirements],
            "docket": self.docket,
            "guidance_requested": self.guidance_requested,
            "scan": self.scan.to_dict(),
            "notes": list(self.notes),
        }

    def explain(self) -> str:
        """Human-readable trace: question → mentions → ranges → requirements."""
        lines = [f"question: {self.question!r}"]
        if self.normalized_question != self.question:
            lines.append(f"normalized: {self.normalized_question!r}")
        lines.append(f"query_type: {self.query_type.value}   kind: {self.kind}")
        if self.docket or self.guidance_requested:
            lines.append(f"docket: {self.docket}   guidance_requested: {self.guidance_requested}")
        lines.append(f"mentions: {len(self.scan.mentions)}")
        for m in self.scan.mentions:
            lines.append(f"  [{m.index}] {m.form:<13} {m.text!r:<32} -> {m.reference.canonical}")
        lines.append(f"ranges: {len(self.scan.ranges)}")
        for r in self.scan.ranges:
            a, b = self.scan.mentions[r.start_mention], self.scan.mentions[r.end_mention]
            state = f"expanded to {r.count}" if r.expanded else f"not expanded ({r.reason})"
            lines.append(f"  {a.reference.canonical} {r.connector} {b.reference.canonical}: {state}")
        lines.append(f"requirements: {len(self.requirements)}")
        for req in self.requirements:
            lines.append(f"  {req.id:<3} {req.canonical:<28} origin={req.origin:<16} raw={req.raw!r}")
        for n in self.notes:
            lines.append(f"note: {n}")
        return "\n".join(lines)


def _plan_kind(query_type: QueryType, requirements: tuple[Requirement, ...], scan: ReferenceScan) -> str:
    if query_type is QueryType.EMPTY:
        return KIND_UNKNOWN
    if not requirements:
        return KIND_GENERAL
    if len(requirements) == 1:
        return KIND_SINGLE
    scopes = {(r.title, r.section if r.section is not None else f"part {r.part}") for r in requirements}
    if len(scopes) > 1:
        return KIND_MULTIPLE_REFERENCE
    if any(r.expanded for r in scan.ranges):
        return KIND_RANGE
    return KIND_MULTI


def plan_query(question: str) -> QueryPlan:
    """Build the QueryPlan for a question. Deterministic; no database, no model."""
    original = question if question is not None else ""
    normalized = normalise_text(original)
    classification = classify(original)
    scan = scan_references(original)
    requirements = tuple(
        Requirement(id=f"r{i}", order=i, reference=res.reference, raw=res.reference.raw, origin=res.origin, mention=res.mention)
        for i, res in enumerate(scan.resolved, start=1)
    )
    kind = _plan_kind(classification.query_type, requirements, scan)
    return QueryPlan(
        question=original,
        normalized_question=normalized,
        query_type=classification.query_type,
        kind=kind,
        requirements=requirements,
        docket=classification.docket if classification.docket is not None else parse_docket(original),
        guidance_requested=bool(_GUIDANCE_RE.search(original)),
        scan=scan,
        notes=scan.notes,
    )
