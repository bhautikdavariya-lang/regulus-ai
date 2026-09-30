"""Question understanding (Stage 1).

Public surface:
    plan_query(question) -> QueryPlan   what the question asks for, as ordered Requirements
    QueryPlan, Requirement              frozen, serialisable structures
    PLAN_KINDS                          single_provision | range | multi_provision |
                                        multiple_reference | general | unknown
"""

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
