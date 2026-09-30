"""Stage 5, model-free phases: retrieval, coverage and selection against the
dataset's expectations. Runs the real Stage 1-3 code on the live read-only
database; no generation. Every judgment here is identity-based and
deterministic.

Per example the record says whether the layer did what the expectation
requires:

    retrieval_ok   the plan names exactly the expected requirements, every
                   expected-exact provision has exact evidence, and no
                   expected-missing provision has exact evidence
    coverage_ok    the coverage state and the missing labels match
    selection_ok   every expected-exact provision's exact evidence is in the
                   context, protected, and nothing required was dropped
    deterministic  running selection twice gives identical output
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from regulus.planning import plan_query
from regulus.rag.coverage import STATE_COMPLETE, STATE_INCOMPLETE, STATE_NO_EXPLICIT_REQUIREMENTS, CoverageReport, check_coverage
from regulus.rag.pipeline import RagConfig, RagPipeline
from regulus.rag.selection import Selection
from regulus.retrieval.evidence import TIER_DISCOVERY, TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING
from regulus.retrieval.lexical import LexicalRetriever, PlanRetrieval
from regulus.stage5.dataset import Stage5Example

EXPECTED_STATE = {
    "answer": STATE_COMPLETE,
    "partial": STATE_INCOMPLETE,
    "refuse": None,  # INCOMPLETE when provisions were named, NO_EXPLICIT otherwise
    "general": STATE_NO_EXPLICIT_REQUIREMENTS,
    "guidance": STATE_NO_EXPLICIT_REQUIREMENTS,
}


@dataclass
class EvidenceRecord:
    id: str
    category: str
    question: str
    plan_kind: str
    requirements: list[str]
    retrieval: dict[str, Any]
    coverage: dict[str, Any]
    selection: dict[str, Any]
    retrieval_ok: bool
    coverage_ok: bool
    selection_ok: bool
    deterministic: bool
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def evidence_ok(self) -> bool:
        return self.retrieval_ok and self.coverage_ok and self.selection_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "category": self.category, "question": self.question, "plan_kind": self.plan_kind,
            "requirements": self.requirements, "retrieval": self.retrieval, "coverage": self.coverage,
            "selection": self.selection, "retrieval_ok": self.retrieval_ok, "coverage_ok": self.coverage_ok,
            "selection_ok": self.selection_ok, "deterministic": self.deterministic, "evidence_ok": self.evidence_ok,
            "timings_ms": self.timings_ms,
        }


@dataclass
class EvidenceOutcome:
    record: EvidenceRecord
    retrieval: PlanRetrieval
    coverage: CoverageReport
    selection: Selection


def _expected_state(ex: Stage5Example) -> str:
    state = EXPECTED_STATE[ex.expected_behavior]
    if state is None:
        return STATE_INCOMPLETE if ex.expected_requirements else STATE_NO_EXPLICIT_REQUIREMENTS
    return state


def evaluate_evidence(ex: Stage5Example, retriever: LexicalRetriever, config: RagConfig | None = None) -> EvidenceOutcome:
    config = config or RagConfig()
    helper = RagPipeline(retriever, generator=None, config=config)  # for the usefulness rule only

    t0 = time.perf_counter()
    plan = plan_query(ex.question)
    t1 = time.perf_counter()
    out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k)
    t2 = time.perf_counter()
    registry = out.registry
    coverage = check_coverage(registry)
    # the pipeline's own selection, including its Stage 12 answer-shape rule
    shape = helper.shape_for(plan)
    selection = helper.select(registry, shape)
    t3 = time.perf_counter()
    again = helper.select(registry, shape)
    deterministic = again.to_dict() == selection.to_dict()

    # ---- retrieval
    canon = {r.id: r.canonical for r in plan.requirements}
    retrieved_exact = sorted({canon[r.id] for r in plan.requirements if registry.exact_for(r.id)})
    parsed = sorted(canon.values())
    parse_ok = set(parsed) == set(ex.expected_requirements)
    recall_hits = [lab for lab in ex.expected_exact if lab in retrieved_exact]
    false_exact = [lab for lab in ex.expected_missing if lab in retrieved_exact]
    tier_counts = {t: sum(1 for e in registry.evidence if e.tier == t) for t in (TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY)}
    per_req = {rid: st.to_dict() for rid, st in registry.requirement_state.items()}
    retrieval = {
        "parsed_requirements": parsed,
        "parse_ok": parse_ok,
        "expected_exact": list(ex.expected_exact),
        "retrieved_exact": retrieved_exact,
        "exact_recall": (len(recall_hits) / len(ex.expected_exact)) if ex.expected_exact else None,
        "expected_missing_without_exact": [lab for lab in ex.expected_missing if lab not in retrieved_exact],
        "false_exact_for_missing": false_exact,
        "tier_counts": tier_counts,
        "fallback_used": bool(out.response.diagnostics.get("fallback_used")),
        "retrieval_mode": out.response.diagnostics.get("retrieval_mode"),
        "candidates": out.response.diagnostics.get("plan", {}).get("candidate_count"),
        "per_requirement": per_req,
        "notes": list(out.response.notes),
    }
    retrieval_ok = parse_ok and len(recall_hits) == len(ex.expected_exact) and not false_exact

    # ---- coverage
    expected_state = _expected_state(ex)
    cov_missing = sorted(coverage.missing_labels)
    coverage_ok = coverage.state == expected_state and (set(cov_missing) == set(ex.expected_missing) if ex.explicit else True)
    coverage_d = {
        "state": coverage.state, "expected_state": expected_state, "missing": cov_missing,
        "expected_missing": list(ex.expected_missing), "satisfied": list(coverage.satisfied_ids),
        "counts": coverage.counts(), "requirements": [r.to_dict() for r in coverage.requirements],
    }

    # ---- selection
    exact_by_req = {canon[r.id]: {e.evidence_id for e in registry.exact_for(r.id)} for r in plan.requirements}
    selected_ids = {s.evidence.evidence_id for s in selection.selected}
    protected_ids = {s.evidence.evidence_id for s in selection.protected}
    required_present = {lab: bool(exact_by_req.get(lab, set()) & protected_ids) for lab in ex.expected_exact if lab in retrieved_exact}
    ctx_tiers = {t: sum(1 for s in selection.selected if s.evidence.tier == t) for t in (TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY)}
    required_dropped = list(selection.diagnostics.get("required_dropped", []))
    selection_d = {
        "selected": len(selection.selected), "protected": len(selection.protected), "dropped": len(selection.dropped),
        "context_tiers": ctx_tiers, "total_chars": selection.total_chars, "overflow": selection.overflow,
        "required_dropped": required_dropped, "required_truncated": list(selection.diagnostics.get("required_truncated", [])),
        "optional_truncated": sum(1 for s in selection.selected if s.truncated and not s.protected),
        "required_present_in_context": required_present,
        "structural_in_context": ctx_tiers[TIER_STRUCTURAL], "discovery_in_context": ctx_tiers[TIER_DISCOVERY],
        "dropped_reasons": sorted({d.reason for d in selection.dropped}),
        "selected_ids": sorted(selected_ids),
    }
    selection_ok = all(required_present.values()) and not required_dropped and deterministic

    record = EvidenceRecord(
        id=ex.id, category=ex.category, question=ex.question, plan_kind=plan.kind, requirements=parsed,
        retrieval=retrieval, coverage=coverage_d, selection=selection_d,
        retrieval_ok=retrieval_ok, coverage_ok=coverage_ok, selection_ok=selection_ok, deterministic=deterministic,
        timings_ms={"planning_ms": round((t1 - t0) * 1000, 2), "retrieval_ms": round((t2 - t1) * 1000, 2), "coverage_selection_ms": round((t3 - t2) * 1000, 2)},
    )
    return EvidenceOutcome(record, out, coverage, selection)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def summarise_evidence(records: list[EvidenceRecord], examples: dict[str, Stage5Example]) -> dict[str, dict[str, Any]]:
    """The retrieval_results / coverage_results / selection_results structures."""
    explicit = [r for r in records if examples[r.id].explicit]
    with_exact = [r for r in explicit if examples[r.id].expected_exact]
    multi = [r for r in with_exact if len(examples[r.id].expected_exact) > 1]
    ranges = [r for r in with_exact if examples[r.id].category in ("range", "long") or r.plan_kind == "range"]
    missing = [r for r in explicit if examples[r.id].expected_missing]
    exact_expected_total = sum(len(examples[r.id].expected_exact) for r in with_exact)
    exact_hits_total = sum(len([l for l in examples[r.id].expected_exact if l in r.retrieval["retrieved_exact"]]) for r in with_exact)
    retrieval = {
        "questions": len(records),
        "parse_ok": _rate(sum(1 for r in explicit if r.retrieval["parse_ok"]), len(explicit)),
        "requirement_recall": _rate(exact_hits_total, exact_expected_total),
        "questions_with_full_exact_recall": _rate(sum(1 for r in with_exact if r.retrieval["exact_recall"] == 1.0), len(with_exact)),
        "multi_provision_full_recall": _rate(sum(1 for r in multi if r.retrieval["exact_recall"] == 1.0), len(multi)),
        "range_full_recall": _rate(sum(1 for r in ranges if r.retrieval["exact_recall"] == 1.0), len(ranges)),
        "missing_provisions_correctly_absent": _rate(sum(1 for r in missing if not r.retrieval["false_exact_for_missing"]), len(missing)),
        "structural_present_when_expected": _rate(sum(1 for r in with_exact if r.retrieval["tier_counts"]["structural"] > 0 or examples[r.id].category == "section"), len(with_exact)),
        "supporting_present": _rate(sum(1 for r in records if r.retrieval["tier_counts"]["supporting"] > 0), len(records)),
        "fallback_used": _rate(sum(1 for r in records if r.retrieval["fallback_used"]), len(records)),
        "fallback_used_when_all_exact_found": _rate(sum(1 for r in with_exact if r.retrieval["fallback_used"] and r.retrieval["exact_recall"] == 1.0 and not examples[r.id].expected_missing), len(with_exact)),
        "retrieval_ok": _rate(sum(1 for r in records if r.retrieval_ok), len(records)),
        "failures": [r.id for r in records if not r.retrieval_ok],
        "per_question": [{"id": r.id, "category": r.category, **r.retrieval, "ok": r.retrieval_ok} for r in records],
    }
    coverage = {
        "questions": len(records),
        "coverage_ok": _rate(sum(1 for r in records if r.coverage_ok), len(records)),
        "explicit_state_correct": _rate(sum(1 for r in explicit if r.coverage["state"] == r.coverage["expected_state"]), len(explicit)),
        "incomplete_detected": _rate(sum(1 for r in missing if r.coverage["state"] == STATE_INCOMPLETE), len(missing)),
        "missing_labels_exact_match": _rate(sum(1 for r in missing if set(r.coverage["missing"]) == set(examples[r.id].expected_missing)), len(missing)),
        "multi_provision_complete": _rate(sum(1 for r in multi if r.coverage["state"] == STATE_COMPLETE), [r for r in multi if not examples[r.id].expected_missing].__len__()),
        "range_complete": _rate(sum(1 for r in ranges if r.coverage["state"] == STATE_COMPLETE and not examples[r.id].expected_missing), sum(1 for r in ranges if not examples[r.id].expected_missing)),
        "no_explicit_for_general": _rate(sum(1 for r in records if not examples[r.id].explicit and r.coverage["state"] == STATE_NO_EXPLICIT_REQUIREMENTS), sum(1 for r in records if not examples[r.id].explicit)),
        "failures": [r.id for r in records if not r.coverage_ok],
        "per_question": [{"id": r.id, "category": r.category, **{k: v for k, v in r.coverage.items() if k != "requirements"}, "ok": r.coverage_ok} for r in records],
    }
    selection = {
        "questions": len(records),
        "selection_ok": _rate(sum(1 for r in records if r.selection_ok), len(records)),
        "required_exact_preserved": _rate(sum(1 for r in with_exact if all(r.selection["required_present_in_context"].values())), len(with_exact)),
        "required_dropped_questions": [r.id for r in records if r.selection["required_dropped"]],
        "required_truncated_questions": [r.id for r in records if r.selection["required_truncated"]],
        "overflow_questions": [r.id for r in records if r.selection["overflow"]],
        "structural_kept_when_available": _rate(sum(1 for r in with_exact if r.selection["structural_in_context"] > 0), sum(1 for r in with_exact if r.retrieval["tier_counts"]["structural"] > 0)),
        "discovery_in_context_questions": [r.id for r in records if r.selection["discovery_in_context"] > 0],
        "mean_context_chars": round(sum(r.selection["total_chars"] for r in records) / len(records), 1) if records else None,
        "optional_truncated_total": sum(r.selection["optional_truncated"] for r in records),
        "deterministic": _rate(sum(1 for r in records if r.deterministic), len(records)),
        "failures": [r.id for r in records if not r.selection_ok],
        "per_question": [{"id": r.id, "category": r.category, **{k: v for k, v in r.selection.items() if k != "selected_ids"}, "ok": r.selection_ok} for r in records],
    }
    return {"retrieval_results": retrieval, "coverage_results": coverage, "selection_results": selection}
