"""Cross-section range expansion (Stage 1, corpus-aware).

`regulus.retrieval.references` parses "21 CFR 50.50 through 50.56" into its two
endpoints and records a note: a PARAGRAPH range can be enumerated from the
identifiers alone, but a SECTION range cannot. Nothing in the text says which of
50.51..50.55 the CFR actually prints, and inventing them would put provisions
that do not exist in front of the model. So the scanner stops there, and this
module finishes the job for callers that can see the corpus.

It is still database-free: `expand_section_ranges` takes a `sections_in_part`
callable, so the enumeration rule is unit-testable on a list and the only thing
that touches PostgreSQL is the retriever that supplies the listing.

What it does, for each range the scanner left unexpanded:

    * ask the corpus for the sections of that part, in document order;
    * keep those strictly between the two endpoints;
    * insert them as ordinary Requirements with origin `range_expansion`,
      directly after the requirement the range starts at.

What it deliberately does not do: invent a section, widen the range past the
endpoints the question named, reorder anything, or touch a plan with no
cross-section range in it. Everything downstream - exact-section retrieval, the
EvidenceRegistry, coverage, selection and its ceilings - then treats these
requirements exactly like any other requested provision.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Iterable, Sequence

from regulus.planning.plan import QueryPlan, Requirement, _plan_kind
from regulus.retrieval.references import (
    MAX_RANGE_EXPANSION,
    ORIGIN_RANGE,
    CfrReference,
    section_range_endpoints,
    section_sort_key,
)

# (number, sort_order) per section, as the corpus stores it
SectionListing = Sequence[tuple[str, int]]
SectionsInPart = Callable[[str], SectionListing]


def sections_between(listing: SectionListing, lo: tuple[int, str], hi: tuple[int, str]) -> list[str]:
    """Section numbers of one part strictly between two sort keys, in document order.

    `sort_order` is the corpus's own document order and is authoritative here; the
    parsed key only decides the bounds, so an endpoint the corpus does not have
    (Part 820 holds a consolidated "820.20-820.30", not a standalone 820.30) still
    bounds the range correctly. The two orderings cannot disagree: `sort_order`
    matches the numeric key in every part of this corpus.
    """
    inner = [(order, number) for number, order in listing
             if (key := section_sort_key(number)) is not None and lo < key < hi]
    return [number for _, number in sorted(inner)]


def _requirements_with(refs: Iterable[tuple[CfrReference, str, str, int]]) -> tuple[Requirement, ...]:
    """Renumber a requirement list so ids stay r1..rn in question order."""
    return tuple(
        Requirement(id=f"r{i}", order=i, reference=ref, raw=raw, origin=origin, mention=mention)
        for i, (ref, raw, origin, mention) in enumerate(refs, start=1)
    )


def expand_section_ranges(plan: QueryPlan, sections_in_part: SectionsInPart) -> tuple[QueryPlan, tuple[str, ...]]:
    """`plan` with every cross-section range filled in from the corpus, and the notes added.

    Returns the plan unchanged (and no notes) when the question names no
    cross-section range, which is every question but an explicit range one.
    """
    scan = plan.scan
    if not plan.requirements or not scan.ranges:
        return plan, ()

    # requirement index by reference key, so an expansion is inserted after its start
    by_key = {r.key: r for r in plan.requirements}
    inserted: dict[str, list[tuple[CfrReference, str, str, int]]] = {}
    notes: list[str] = []
    for span in scan.ranges:
        if span.expanded:
            continue  # a paragraph range the scanner already enumerated
        start_m, end_m = scan.mentions[span.start_mention], scan.mentions[span.end_mention]
        bounds = section_range_endpoints(start_m.reference, end_m.reference)
        if bounds is None:
            continue  # not a cross-section range: leave the scanner's own note standing
        lo, hi = bounds
        start = by_key.get(start_m.reference.key)
        if start is None:
            continue
        raw = f"{start_m.text} {span.connector} {end_m.text}"
        numbers = sections_between(sections_in_part(start_m.reference.part), lo, hi)
        if len(numbers) + 2 > MAX_RANGE_EXPANSION:
            notes.append(
                f"range {start_m.reference.canonical} {span.connector} {end_m.reference.canonical} "
                f"spans {len(numbers) + 2} sections, above the limit of {MAX_RANGE_EXPANSION}; "
                "only the endpoints were requested"
            )
            continue
        new = [
            (replace(start_m.reference, section=number, paragraph_path="", raw=raw), raw, ORIGIN_RANGE, start_m.index)
            for number in numbers
            if replace(start_m.reference, section=number, paragraph_path="").key not in by_key
        ]
        if not new:
            notes.append(
                f"range {start_m.reference.canonical} {span.connector} {end_m.reference.canonical}: "
                "this snapshot has no section between the endpoints"
            )
            continue
        inserted[start.id] = new
        notes.append(
            f"range {start_m.reference.canonical} {span.connector} {end_m.reference.canonical} expanded to "
            f"{len(numbers) + 2} sections from the corpus: {', '.join(numbers)}"
        )

    if not inserted:
        return (plan if not notes else replace(plan, notes=plan.notes + tuple(notes))), tuple(notes)

    ordered: list[tuple[CfrReference, str, str, int]] = []
    for req in plan.requirements:
        ordered.append((req.reference, req.raw, req.origin, req.mention))
        ordered.extend(inserted.get(req.id, ()))
    requirements = _requirements_with(ordered)
    return replace(plan, requirements=requirements,
                   kind=_plan_kind(plan.query_type, requirements, scan),
                   notes=plan.notes + tuple(notes)), tuple(notes)
