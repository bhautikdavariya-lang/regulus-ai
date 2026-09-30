"""Evidence selection for the generation context (Stage 3).

Turns an EvidenceRegistry into the ordered, bounded set of sources the
model will see. The selector is requirement-aware and works in phases:

    1. required evidence   exact rows that ARE a requested provision (and the
                           chunks of a requested docket): protected, kept in
                           requirement order, full text up to the required
                           per-source cap, bounded only by the hard ceilings
    1b. material evidence  Stage 12, only when the caller passes `material`:
                           evidence it marks as a material part of a requested
                           provision (its child paragraphs) is kept like
                           required evidence - bounded by the hard ceilings,
                           not the soft budget - but is not protected and
                           keeps its tier
    2. structural evidence parent/child paragraphs of requested provisions
    3. supporting evidence the question's full-text hits
    4. discovery evidence  broad-method hits for unresolved requirements

Phases 2 to 4 are optional evidence: they spend whatever the soft budget
(ContextPolicy.max_results / max_chars_per_result / max_total_chars) leaves
after the required evidence, and are dropped before any required source.
Required evidence may exceed the soft budget up to the hard ceilings
(hard_max_results / hard_max_total_chars); a required source that does not
fit even there is dropped with an explicit `overflow` record, never
silently. Every decision is recorded in the selection diagnostics.

No scores are combined across tiers: a score only orders optional evidence
inside its tier, which the registry already did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from regulus.rag.context import ContextPolicy, ContextSource, TRUNCATION_MARK, render_source
from regulus.retrieval.evidence import TIER_DISCOVERY, TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING, Evidence, EvidenceRegistry
from regulus.retrieval.models import METHOD_EXACT_DOCKET, RetrievalResult

REASON_REQUIRED_EXACT = "required_exact"          # tier exact, satisfies a requirement
REASON_REQUIRED_DOCKET = "required_docket"        # the requested guidance document
REASON_STRUCTURAL = "structural_context"
REASON_SUPPORTING = "supporting"
REASON_DISCOVERY = "discovery"
REASON_SUBORDINATE = "subordinate_of_requested"  # Stage 12: a child of a requested provision

DROP_HARD_CEILING_CHARS = "hard_ceiling_chars"    # required evidence exceeded hard_max_total_chars
DROP_HARD_CEILING_COUNT = "hard_ceiling_count"    # required evidence exceeded hard_max_results
DROP_SOFT_BUDGET = "soft_budget"                  # optional evidence: max_total_chars exhausted
DROP_MAX_RESULTS = "max_results"                  # optional evidence: max_results reached
DROP_FILTERED = "filtered"                        # optional evidence excluded by the pipeline's usefulness rule

MIN_SQUEEZED_CHARS = 200  # an optional source is shortened to fit only if at least this much text remains


@dataclass(frozen=True)
class SelectedEvidence:
    index: int                      # 1-based SOURCE number in the prompt
    evidence: Evidence
    text: str                       # cleaned, possibly truncated text placed in the context
    truncated: bool
    protected: bool
    reason: str
    chars: int                      # rendered block length charged to the budget

    @property
    def requirement_ids(self) -> tuple[str, ...]:
        e = self.evidence
        return tuple(dict.fromkeys(e.satisfies + e.structural_for + e.discovered_for))

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "evidence_id": self.evidence.evidence_id,
            "key": self.evidence.key,
            "citation": self.evidence.citation,
            "tier": self.evidence.tier,
            "requirement_ids": list(self.requirement_ids),
            "protected": self.protected,
            "reason": self.reason,
            "chars": len(self.text),
            "block_chars": self.chars,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class DroppedEvidence:
    evidence: Evidence
    reason: str
    required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence.evidence_id,
            "citation": self.evidence.citation,
            "tier": self.evidence.tier,
            "requirement_ids": list(dict.fromkeys(self.evidence.satisfies + self.evidence.structural_for + self.evidence.discovered_for)),
            "reason": self.reason,
            "required": self.required,
        }


@dataclass(frozen=True)
class Selection:
    selected: tuple[SelectedEvidence, ...]
    dropped: tuple[DroppedEvidence, ...]
    policy: ContextPolicy
    total_chars: int
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def protected(self) -> tuple[SelectedEvidence, ...]:
        return tuple(s for s in self.selected if s.protected)

    @property
    def overflow(self) -> bool:
        """True when required evidence had to be dropped or truncated."""
        return bool(self.diagnostics.get("required_dropped")) or bool(self.diagnostics.get("required_truncated"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": [s.to_dict() for s in self.selected],
            "dropped": [d.to_dict() for d in self.dropped],
            "policy": self.policy.to_dict(),
            "total_chars": self.total_chars,
            "overflow": self.overflow,
            **self.diagnostics,
        }


def is_required(evidence: Evidence) -> bool:
    """Exact evidence for an explicit requirement, or the requested docket's chunks."""
    if evidence.tier != TIER_EXACT:
        return False
    return bool(evidence.satisfies) or evidence.retrieval_method == METHOD_EXACT_DOCKET


def _reason(evidence: Evidence) -> str:
    if evidence.tier == TIER_EXACT:
        return REASON_REQUIRED_EXACT if evidence.satisfies else REASON_REQUIRED_DOCKET
    return {TIER_STRUCTURAL: REASON_STRUCTURAL, TIER_SUPPORTING: REASON_SUPPORTING}.get(evidence.tier, REASON_DISCOVERY)


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = max(limit - len(TRUNCATION_MARK), 0)
    return text[:cut].rstrip() + TRUNCATION_MARK, True


def _block_chars(evidence: Evidence, text: str, index: int, truncated: bool) -> int:
    """Length of the rendered SOURCE block, what the budget is charged with."""
    probe = ContextSource(index=index, result=evidence.result, text=text, truncated=truncated)
    return len(render_source(probe))


def select_evidence(
    registry: EvidenceRegistry,
    policy: ContextPolicy | None = None,
    *,
    optional_filter: Callable[[RetrievalResult], bool] | None = None,
    material: Callable[[Evidence], bool] | None = None,
) -> Selection:
    """Deterministic, requirement-aware selection. Same inputs, same output."""
    policy = policy or ContextPolicy()
    selected: list[SelectedEvidence] = []
    dropped: list[DroppedEvidence] = []
    used = 0
    required_truncated: list[str] = []

    def gap() -> int:
        return 2 if selected else 0  # blank line between blocks

    # Phase 1: required evidence, in registry order (requirement order, then document order)
    for e in registry.evidence:
        if not is_required(e):
            continue
        text, truncated = _truncate(_clean(e.text), policy.required_max_chars_per_result)
        index = len(selected) + 1
        chars = _block_chars(e, text, index, truncated)
        if len(selected) >= policy.hard_max_results:
            dropped.append(DroppedEvidence(e, DROP_HARD_CEILING_COUNT, required=True))
            continue
        if used + gap() + chars > policy.hard_max_total_chars:
            dropped.append(DroppedEvidence(e, DROP_HARD_CEILING_CHARS, required=True))
            continue
        if truncated:
            required_truncated.append(e.evidence_id)
        used += gap() + chars
        selected.append(SelectedEvidence(index, e, text, truncated, True, _reason(e), chars))

    required_count = len(selected)
    required_chars = used

    # Phase 1b: material parts of requested provisions, same ceilings as required evidence
    material_ids: list[str] = []
    if material is not None:
        for e in registry.evidence:
            if is_required(e) or not material(e):
                continue
            text, truncated = _truncate(_clean(e.text), policy.required_max_chars_per_result)
            index = len(selected) + 1
            chars = _block_chars(e, text, index, truncated)
            if len(selected) >= policy.hard_max_results:
                dropped.append(DroppedEvidence(e, DROP_HARD_CEILING_COUNT, required=False))
                material_ids.append(e.evidence_id)
                continue
            if used + gap() + chars > policy.hard_max_total_chars:
                dropped.append(DroppedEvidence(e, DROP_HARD_CEILING_CHARS, required=False))
                material_ids.append(e.evidence_id)
                continue
            used += gap() + chars
            selected.append(SelectedEvidence(index, e, text, truncated, False, REASON_SUBORDINATE, chars))
            material_ids.append(e.evidence_id)
    handled = set(material_ids)

    # Phases 2-4: optional evidence within the soft budget, never displacing the above
    for tier in (TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY):
        for e in registry.evidence:
            if e.tier != tier or is_required(e) or e.evidence_id in handled:
                continue
            # structural evidence is identity-based (a parent or child of a requested
            # provision); the usefulness rule targets method-based hits only
            if tier != TIER_STRUCTURAL and optional_filter is not None and not optional_filter(e.result):
                dropped.append(DroppedEvidence(e, DROP_FILTERED, required=False))
                continue
            if len(selected) >= policy.max_results or len(selected) >= policy.hard_max_results:
                dropped.append(DroppedEvidence(e, DROP_MAX_RESULTS, required=False))
                continue
            text, truncated = _truncate(_clean(e.text), policy.max_chars_per_result)
            index = len(selected) + 1
            chars = _block_chars(e, text, index, truncated)
            limit = min(policy.max_total_chars, policy.hard_max_total_chars)
            if used + gap() + chars > limit:
                remaining = limit - used - gap()
                header = chars - len(text)
                if remaining - header >= MIN_SQUEEZED_CHARS:
                    text, truncated = _truncate(text, remaining - header)
                    chars = _block_chars(e, text, index, True)
                    truncated = True
                else:
                    dropped.append(DroppedEvidence(e, DROP_SOFT_BUDGET, required=False))
                    continue
            used += gap() + chars
            selected.append(SelectedEvidence(index, e, text, truncated, False, _reason(e), chars))

    # exact evidence that is not required (docket handled above) cannot exist; any other tier is optional
    diagnostics = {
        "required_count": required_count,
        "required_chars": required_chars,
        "optional_count": len(selected) - required_count,
        **({"material_selected": [s.evidence.evidence_id for s in selected if s.reason == REASON_SUBORDINATE]} if material is not None else {}),
        "required_dropped": [d.evidence.evidence_id for d in dropped if d.required],
        "required_truncated": required_truncated,
        "optional_dropped": [d.evidence.evidence_id for d in dropped if not d.required],
        "soft_budget_exceeded_by_required": required_chars > policy.max_total_chars or required_count > policy.max_results,
        "tier_counts": {t: sum(1 for s in selected if s.evidence.tier == t) for t in (TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY)},
    }
    return Selection(tuple(selected), tuple(dropped), policy, used, diagnostics)


_SENTENCE_END = (".", '."', ".)", "?", "!")


def is_complete_sentence(text: str) -> bool:
    """True when a provision's text ends a sentence. A lead-in ("shall be in terms of:") or a chained
    fragment ("...; or, in the absence thereof,") needs the text around it to be read correctly."""
    return (text or "").rstrip().endswith(_SENTENCE_END)


def required_only(selection: Selection) -> Selection:
    """Only the required (protected) evidence, re-indexed 1..n.

    Stage 6 (docs/generation_quality_stage6.md): used when every requested provision has
    exact evidence that is complete text on its own (see RagPipeline.build_bundle for the
    conditions): related supporting/discovery sources and unrequested parents or children
    are left out, because the 0.6B model is distracted by related material it does not
    need. Also the "perfect evidence" controlled condition of the evaluations."""
    kept = [s for s in selection.selected if s.protected]
    items = tuple(SelectedEvidence(i, s.evidence, s.text, s.truncated, True, s.reason, s.chars) for i, s in enumerate(kept, start=1))
    dropped = selection.dropped + tuple(DroppedEvidence(s.evidence, "optional_not_needed_exact_evidence_complete", False)
                                        for s in selection.selected if not s.protected)
    return Selection(items, dropped, selection.policy, sum(s.chars for s in items),
                     {**selection.diagnostics, "required_only": True, "optional_count": 0})
