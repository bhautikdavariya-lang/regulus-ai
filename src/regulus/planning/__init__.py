"""Question understanding (Stage 1).

Public surface:
    plan_query(question) -> QueryPlan   what the question asks for, as ordered Requirements
    expand_section_ranges(plan, lookup) the same plan with a cross-section range
                                        ("50.50 through 50.56") filled in from a corpus
                                        section listing, which the parser cannot do alone
    QueryPlan, Requirement              frozen, serialisable structures
    PLAN_KINDS                          single_provision | range | multi_provision |
                                        multiple_reference | general | unknown
"""

from regulus.planning.ranges import expand_section_ranges  # noqa: F401  (re-exported)
from regulus.planning.plan import (
    KIND_GENERAL,
    KIND_MULTI,
    KIND_MULTIPLE_REFERENCE,
    KIND_RANGE,
    KIND_SINGLE,
    KIND_UNKNOWN,
    PLAN_KINDS,
    QueryPlan,
    Requirement,
    plan_query,
)

__all__ = [
    "KIND_GENERAL",
    "KIND_MULTI",
    "KIND_MULTIPLE_REFERENCE",
    "KIND_RANGE",
    "KIND_SINGLE",
    "KIND_UNKNOWN",
    "PLAN_KINDS",
    "QueryPlan",
    "Requirement",
    "plan_query",
]
