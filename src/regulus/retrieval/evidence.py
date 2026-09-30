"""Evidence model and registry for plan-driven retrieval (Stage 2).

Retrieval used to answer "what are the top-k passages for this question?".
It now answers "for each requirement in the QueryPlan, what evidence did we
find, and how does each piece relate to what was asked?". This module holds
that answer.

Tiers (how a piece of evidence relates to the plan):

    exact        the row IS a requested provision (same section and paragraph
                 identity; for a section- or part-level requirement, a row of
                 that section or part)
    structural   a parent or child paragraph of a requested provision: useful
                 context, never a substitute for the provision itself
    supporting   found by the question's full-text search, not one of the
                 requested provisions (other sections, guidance chunks)
    discovery    found by a broad method (OR fallback, trigram) while looking
                 for an unresolved requirement; provenance is kept and it is
                 never promoted to exact by score

Association is deterministic and identity-based: the retrieved row's
normalised (section, paragraph) is compared with the requirement's. Text
similarity and retrieval scores play no part in deciding what satisfies a
requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from regulus.retrieval.models import METHOD_EXACT_DOCKET, RetrievalResult

if TYPE_CHECKING:  # avoid an import cycle at runtime
    from regulus.planning.plan import QueryPlan, Requirement
    from regulus.retrieval.references import CfrReference

TIER_EXACT = "exact"
TIER_STRUCTURAL = "structural"
TIER_SUPPORTING = "supporting"
TIER_DISCOVERY = "discovery"
TIERS = (TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY)
_TIER_RANK = {t: i for i, t in enumerate(TIERS)}

# relation of one retrieved row to one requirement
REL_EXACT = "exact"
REL_PARENT = "parent"
REL_CHILD = "child"
REL_SIBLING = "sibling"     # same section, neither ancestor nor descendant
REL_NONE = "none"


# ---------------------------------------------------------------- relation


def relate(reference: "CfrReference", result: RetrievalResult) -> str:
    """How an eCFR row relates to a requested reference, by identity only.

    Paragraph-level request: only the identical (section, paragraph) row is
    exact; an ancestor paragraph or the section row is a parent; a descendant
    is a child; another paragraph of the section is a sibling.
    Section-level request: every row of the section is exact, because the
    database stores a section as its paragraph rows and has no other
    representation of it. Part-level request: every row of the part is exact.
    """
    if result.corpus != "ecfr":
        return REL_NONE
    c = result.citation
    title = c.title or "21"
    if title != reference.title:
        return REL_NONE
    if reference.section is None:
        part = c.part or result.metadata.get("part")
        return REL_EXACT if part == reference.part else REL_NONE
    if c.section != reference.section:
        return REL_NONE
    have = c.paragraph or ""
    want = reference.paragraph_path
    if not want:
        return REL_EXACT
    if have == want:
        return REL_EXACT
    if not have or want.startswith(have + "("):
        return REL_PARENT
    if have.startswith(want + "("):
        return REL_CHILD
    return REL_SIBLING


# ---------------------------------------------------------------- evidence


@dataclass(frozen=True)
class Evidence:
    """One retrieved passage with its tier and its relation to the plan."""

    evidence_id: str
    result: RetrievalResult
    tier: str
    satisfies: tuple[str, ...] = ()       # requirement ids this row is exact evidence for
    structural_for: tuple[str, ...] = ()  # requirement ids this row is a parent/child of
    discovered_for: tuple[str, ...] = ()  # requirement ids whose targeted fallback found it
    relations: dict[str, str] = field(default_factory=dict)  # requirement id -> relation

    @property
    def key(self) -> str:
        return self.result.key

    @property
    def corpus(self) -> str:
        return self.result.corpus

    @property
    def citation(self) -> str:
        return self.result.citation.label

    @property
    def text(self) -> str:
        return self.result.text

    @property
    def retrieval_method(self) -> str:
        return self.result.retrieval_method

    @property
    def score(self) -> float:
        return self.result.relevance_score

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "key": self.key,
            "corpus": self.corpus,
            "citation": self.citation,
            "tier": self.tier,
            "satisfies": list(self.satisfies),
            "structural_for": list(self.structural_for),
            "discovered_for": list(self.discovered_for),
            "relations": dict(self.relations),
            "retrieval_method": self.retrieval_method,
            "methods": list(self.result.methods),
            "score": round(self.score, 4),
            "chars": len(self.text),
        }


@dataclass(frozen=True)
class RequirementRetrieval:
    """What retrieval did for one requirement, and what it found."""

    requirement_id: str
    canonical: str
    exact_attempted: bool
    exact_hits: int
    structural_hits: int
    discovery_hits: int
    fallback_run: bool
    fallback_terms: tuple[str, ...] = ()
    note: str | None = None

    @property
    def resolved(self) -> bool:
        return self.exact_hits > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "canonical": self.canonical,
            "exact_attempted": self.exact_attempted,
            "exact_hits": self.exact_hits,
            "structural_hits": self.structural_hits,
            "discovery_hits": self.discovery_hits,
            "resolved": self.resolved,
            "fallback_run": self.fallback_run,
            "fallback_terms": list(self.fallback_terms),
            "note": self.note,
        }


@dataclass(frozen=True)
class EvidenceRegistry:
    """All evidence for a plan, indexed by requirement.

    `evidence` is in final order: exact evidence first (in requirement order,
    then document order), then structural, then supporting and discovery by
    score. That order is what downstream consumers see; nothing here is cut
    by a global top-k.
    """

    plan: "QueryPlan"
    evidence: tuple[Evidence, ...]
    requirement_state: dict[str, RequirementRetrieval]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    # -- lookups -----------------------------------------------------------

    def all_evidence(self) -> tuple[Evidence, ...]:
        return self.evidence

    def by_tier(self, tier: str) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidence if e.tier == tier)

    def exact_for(self, requirement_id: str) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidence if requirement_id in e.satisfies)

    def structural_for(self, requirement_id: str) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidence if requirement_id in e.structural_for)

    def discovered_for(self, requirement_id: str) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidence if requirement_id in e.discovered_for)

    def evidence_for(self, requirement_id: str) -> tuple[Evidence, ...]:
        """Everything associated with a requirement: exact, structural, discovery."""
        return tuple(
            e for e in self.evidence
            if requirement_id in e.satisfies or requirement_id in e.structural_for or requirement_id in e.discovered_for
        )

    def resolved_requirements(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.plan.requirements if self.requirement_state[r.id].resolved)

    def unresolved_requirements(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.plan.requirements if not self.requirement_state[r.id].resolved)

    @property
    def protected(self) -> tuple[Evidence, ...]:
        """Evidence that global ranking must never remove: exact and structural."""
        return tuple(e for e in self.evidence if e.tier in (TIER_EXACT, TIER_STRUCTURAL))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_kind": self.plan.kind,
            "requirements": [r.to_dict() for r in self.plan.requirements],
            "evidence": [e.to_dict() for e in self.evidence],
            "requirement_state": {rid: s.to_dict() for rid, s in self.requirement_state.items()},
            "resolved": list(self.resolved_requirements()),
            "unresolved": list(self.unresolved_requirements()),
            "diagnostics": dict(self.diagnostics),
        }


# ---------------------------------------------------------------- assembly


def _tier_from_method(method: str, discovery_methods: tuple[str, ...]) -> str:
    """Tier for a row that is not a requested CFR provision or its parent/child.

    A docket hit is the requested guidance document itself (exact by identity of
    the docket, satisfying no CFR requirement); OR/trigram hits are discovery.
    """
    if method == METHOD_EXACT_DOCKET:
        return TIER_EXACT
    return TIER_DISCOVERY if method in discovery_methods else TIER_SUPPORTING


def classify_result(
    result: RetrievalResult,
    requirements: tuple["Requirement", ...],
    *,
    discovered_for: tuple[str, ...],
    discovery_methods: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[str, ...], dict[str, str]]:
    """Tier and associations for one merged result.

    Identity decides exact and structural; only when the row is neither is
    the tier taken from how it was retrieved.
    """
    satisfies: list[str] = []
    structural: list[str] = []
    relations: dict[str, str] = {}
    for req in requirements:
        rel = relate(req.reference, result)
        if rel == REL_NONE:
            continue
        relations[req.id] = rel
        if rel == REL_EXACT:
            satisfies.append(req.id)
        elif rel in (REL_PARENT, REL_CHILD):
            structural.append(req.id)
    if satisfies:
        tier = TIER_EXACT
    elif structural:
        tier = TIER_STRUCTURAL
    else:
        tier = _tier_from_method(result.retrieval_method, discovery_methods)
    return tier, tuple(satisfies), tuple(structural), relations


def order_evidence(evidence: list[Evidence], requirements: tuple["Requirement", ...]) -> list[Evidence]:
    """Exact (requirement order, then document order), structural, then the rest by score."""
    order = {r.id: r.order for r in requirements}

    def first_order(ids: tuple[str, ...]) -> int:
        return min((order[i] for i in ids), default=len(order) + 1)

    def sort_key(e: Evidence):
        ordinal = e.result.metadata.get("ordinal")
        ordinal = int(ordinal) if isinstance(ordinal, int) else 0
        if e.tier == TIER_EXACT:
            return (0, first_order(e.satisfies), ordinal, e.key)
        if e.tier == TIER_STRUCTURAL:
            return (1, first_order(e.structural_for), ordinal, e.key)
        return (2 if e.tier == TIER_SUPPORTING else 3, -e.score, 0, e.key)

    return sorted(evidence, key=sort_key)
