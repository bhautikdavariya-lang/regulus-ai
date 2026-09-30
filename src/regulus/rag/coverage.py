"""Requirement coverage (Stage 3).

Answers one question per explicit requirement in the QueryPlan: does the
EvidenceRegistry hold evidence that IS that provision? Only tier-exact
evidence associated to the requirement counts. Parent, child, sibling,
guidance, full-text and discovery evidence never satisfy an explicit
request, however relevant it is.

The overall state is conservative and has no thresholds:

    NO_EXPLICIT_REQUIREMENTS   the plan names no CFR provision (general or
                               docket/guidance question)
    COMPLETE                   every explicit requirement has exact evidence
    INCOMPLETE                 at least one explicit requirement has none

Coverage is computed from the registry alone: no database access, no
scores, no model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from regulus.retrieval.evidence import REL_SIBLING, TIER_DISCOVERY, TIER_SUPPORTING, EvidenceRegistry

STATE_NO_EXPLICIT_REQUIREMENTS = "NO_EXPLICIT_REQUIREMENTS"
STATE_COMPLETE = "COMPLETE"
STATE_INCOMPLETE = "INCOMPLETE"

# per-requirement status, in decreasing strength; only STATUS_EXACT satisfies
STATUS_EXACT = "exact"
STATUS_STRUCTURAL_ONLY = "structural_only"
STATUS_SUPPORTING_ONLY = "supporting_only"
STATUS_DISCOVERY_ONLY = "discovery_only"
STATUS_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class RequirementCoverage:
    requirement_id: str
    canonical: str
    status: str
    exact_evidence_ids: tuple[str, ...]
    structural_evidence_ids: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]   # same-section siblings found by any method
    discovery_evidence_ids: tuple[str, ...]
    note: str | None = None                    # retrieval's explanation when nothing exact was found

    @property
    def satisfied(self) -> bool:
        return self.status == STATUS_EXACT

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "canonical": self.canonical,
            "status": self.status,
            "satisfied": self.satisfied,
            "exact_evidence_ids": list(self.exact_evidence_ids),
            "structural_evidence_ids": list(self.structural_evidence_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "discovery_evidence_ids": list(self.discovery_evidence_ids),
            "note": self.note,
        }


@dataclass(frozen=True)
class CoverageReport:
    state: str
    requirements: tuple[RequirementCoverage, ...]

    @property
    def complete(self) -> bool:
        """True only when every explicit requirement has exact evidence (or there are none)."""
        return self.state in (STATE_COMPLETE, STATE_NO_EXPLICIT_REQUIREMENTS)

    @property
    def explicit(self) -> bool:
        return self.state != STATE_NO_EXPLICIT_REQUIREMENTS

    @property
    def satisfied_ids(self) -> tuple[str, ...]:
        return tuple(r.requirement_id for r in self.requirements if r.satisfied)

    @property
    def missing_ids(self) -> tuple[str, ...]:
        return tuple(r.requirement_id for r in self.requirements if not r.satisfied)

    @property
    def missing_labels(self) -> tuple[str, ...]:
        return tuple(r.canonical for r in self.requirements if not r.satisfied)

    def for_requirement(self, requirement_id: str) -> RequirementCoverage:
        return next(r for r in self.requirements if r.requirement_id == requirement_id)

    def counts(self) -> dict[str, int]:
        by_status = {s: 0 for s in (STATUS_EXACT, STATUS_STRUCTURAL_ONLY, STATUS_SUPPORTING_ONLY, STATUS_DISCOVERY_ONLY, STATUS_UNRESOLVED)}
        for r in self.requirements:
            by_status[r.status] += 1
        return {
            "total_requirements": len(self.requirements),
            "exact_requirements": by_status[STATUS_EXACT],
            "structural_only_requirements": by_status[STATUS_STRUCTURAL_ONLY],
            "supporting_only_requirements": by_status[STATUS_SUPPORTING_ONLY],
            "discovery_only_requirements": by_status[STATUS_DISCOVERY_ONLY],
            "unresolved_requirements": by_status[STATUS_UNRESOLVED],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "complete": self.complete,
            "missing": list(self.missing_ids),
            "missing_labels": list(self.missing_labels),
            **self.counts(),
            "requirements": [r.to_dict() for r in self.requirements],
        }


def check_coverage(registry: EvidenceRegistry) -> CoverageReport:
    """Coverage of every explicit requirement, from Stage 2 evidence tiers only."""
    rows: list[RequirementCoverage] = []
    for req in registry.plan.requirements:
        rid = req.id
        exact = tuple(e.evidence_id for e in registry.exact_for(rid))
        structural = tuple(e.evidence_id for e in registry.structural_for(rid))
        supporting = tuple(
            e.evidence_id for e in registry.evidence
            if e.relations.get(rid) == REL_SIBLING and e.tier in (TIER_SUPPORTING, TIER_DISCOVERY)
        )
        discovery = tuple(e.evidence_id for e in registry.discovered_for(rid))
        if exact:
            status = STATUS_EXACT
        elif structural:
            status = STATUS_STRUCTURAL_ONLY
        elif supporting:
            status = STATUS_SUPPORTING_ONLY
        elif discovery:
            status = STATUS_DISCOVERY_ONLY
        else:
            status = STATUS_UNRESOLVED
        state = registry.requirement_state.get(rid)
        rows.append(RequirementCoverage(rid, req.canonical, status, exact, structural, supporting, discovery,
                                        note=state.note if state is not None else None))
    if not rows:
        state_name = STATE_NO_EXPLICIT_REQUIREMENTS
    elif all(r.satisfied for r in rows):
        state_name = STATE_COMPLETE
    else:
        state_name = STATE_INCOMPLETE
    return CoverageReport(state=state_name, requirements=tuple(rows))
