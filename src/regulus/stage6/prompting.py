"""Render training examples with the Stage 4 generation contract.

At inference the model sees REQUESTED PROVISIONS, tiered SOURCE blocks and
an ANSWER FORMAT line (regulus.rag.generation). Training on the legacy
prompt would teach a different interface, so Stage 6 renders every example
through the same package builder: the question is parsed with the Stage 1
planner, each context item's tier comes from its identity against the
requested provisions (exact / structural / supporting, or the requested
docket), and the prompt text is produced by build_grounded_messages.
"""

from __future__ import annotations

from regulus.inference.generate import Message
from regulus.planning import plan_query
from regulus.rag.coverage import STATE_COMPLETE, STATE_INCOMPLETE, STATE_NO_EXPLICIT_REQUIREMENTS
from regulus.rag.generation import GenerationBudget, GenerationPackage, PackagedSource, SHAPE_DOCKET, SHAPE_GENERAL, SHAPE_PER_PROVISION, SHAPE_SINGLE, build_grounded_messages
from regulus.rag.prompt import coverage_note
from regulus.retrieval.evidence import TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING
from regulus.training.models import ContextItem, TrainingExample


def _relation(req_section: str | None, req_para: str, req_part: str, item: ContextItem) -> str:
    if item.source_type == "fda_guidance" or not item.section:
        if req_section is None and item.part == req_part and item.source_type != "fda_guidance":
            return "exact"
        return "none"
    if req_section is None:
        return "exact" if item.part == req_part else "none"
    if item.section != req_section:
        return "none"
    have = item.paragraph or ""
    if not req_para or have == req_para:
        return "exact"
    if not have or req_para.startswith(have + "("):
        return "parent"
    if have.startswith(req_para + "("):
        return "child"
    return "sibling"


def example_package(example: TrainingExample, budget: GenerationBudget | None = None) -> GenerationPackage:
    plan = plan_query(example.question)
    reqs = tuple((r.id, r.canonical) for r in plan.requirements)
    sources: list[PackagedSource] = []
    satisfied: set[str] = set()
    for i, item in enumerate(example.context, start=1):
        rids_exact: list[str] = []
        rids_struct: list[str] = []
        for r in plan.requirements:
            rel = _relation(r.section, r.paragraph_path, r.part, item)
            if rel == "exact":
                rids_exact.append(r.id)
            elif rel in ("parent", "child"):
                rids_struct.append(r.id)
        is_docket = bool(plan.docket and item.docket_number and item.docket_number.upper() == plan.docket.upper())
        if rids_exact:
            tier, rids = TIER_EXACT, tuple(rids_exact)
            satisfied.update(rids_exact)
        elif rids_struct:
            tier, rids = TIER_STRUCTURAL, tuple(rids_struct)
        elif is_docket:
            tier, rids = TIER_EXACT, ()
        else:
            tier, rids = TIER_SUPPORTING, ()
        corpus = "fda_guidance" if item.source_type == "fda_guidance" else "ecfr"
        sources.append(PackagedSource(
            index=i, tier=tier, requirement_ids=rids, protected=tier == TIER_EXACT, corpus=corpus, citation=item.citation,
            heading=item.heading if corpus == "ecfr" else None, url=item.url, text=item.text, truncated=False,
            evidence_id=f"t{i}", key=item.source_key,
            citation_fields={"title": "21", "part": item.part, "section": item.section, "paragraph": item.paragraph or None, "label": item.citation,
                             "docket_number": item.docket_number, "document_title": item.document_title},
            is_docket=is_docket,
        ))
    ordered_sat = tuple(r.id for r in plan.requirements if r.id in satisfied)
    missing = tuple(r.canonical for r in plan.requirements if r.id not in satisfied)
    if not reqs:
        state = STATE_NO_EXPLICIT_REQUIREMENTS
        shape = SHAPE_DOCKET if any(s.is_docket for s in sources) else SHAPE_GENERAL
    else:
        state = STATE_COMPLETE if not missing else STATE_INCOMPLETE
        shape = SHAPE_PER_PROVISION if len(reqs) > 1 else SHAPE_SINGLE
    notes = (coverage_note(missing),) if missing else ()
    budget = budget or GenerationBudget()
    return GenerationPackage(
        question=plan.normalized_question or plan.question, requirements=reqs, satisfied_ids=ordered_sat, missing_labels=missing,
        sources=tuple(sources), notes=notes, shape=shape, max_new_tokens=budget.hard_max_tokens, coverage_state=state, budget=budget,
    )


def to_grounded_messages(example: TrainingExample) -> list[Message]:
    """system / user (Stage 4 contract) / assistant turns for SFT."""
    messages = build_grounded_messages(example_package(example))
    return [*messages, {"role": "assistant", "content": example.answer}]
