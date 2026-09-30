"""Read-only lexical retrieval over the regulus PostgreSQL corpus (Stage 5).

Public surface:
    Database, DatabaseConfig            - read-only PostgreSQL access
    LexicalRetriever, SearchResponse    - exact CFR / full-text / trigram retrieval
    PlanRetrieval, EvidenceRegistry     - Stage 2 plan-driven, requirement-level retrieval
    Filters, Retriever                  - filter model and retriever protocol
    RetrievalResult, Citation           - serialisable result model
    classify, parse_cfr_reference       - deterministic query classification
    parse_cfr_references, scan_references - every reference in a question (Stage 1)
"""

from regulus.retrieval.base import Filters, FilterError, Retriever
from regulus.retrieval.citations import build_ecfr_citation, build_guidance_citation
from regulus.retrieval.db import Database, DatabaseConfig, DatabaseConfigError
from regulus.retrieval.evidence import Evidence, EvidenceRegistry, RequirementRetrieval
from regulus.retrieval.hybrid import HybridConfig, HybridRetriever
from regulus.retrieval.lexical import LexicalRetriever, PlanRetrieval, SearchResponse
from regulus.retrieval.models import CORPORA, Citation, RetrievalResult
from regulus.retrieval.query import CfrReference, QueryClassification, QueryType, classify, parse_cfr_reference
from regulus.retrieval.references import ReferenceScan, parse_cfr_references, scan_references

__all__ = [
    "CORPORA",
    "CfrReference",
    "Citation",
    "Database",
    "DatabaseConfig",
    "DatabaseConfigError",
    "Evidence",
    "EvidenceRegistry",
    "FilterError",
    "Filters",
    "HybridConfig",
    "HybridRetriever",
    "LexicalRetriever",
    "PlanRetrieval",
    "QueryClassification",
    "QueryType",
    "ReferenceScan",
    "RequirementRetrieval",
    "RetrievalResult",
    "Retriever",
    "SearchResponse",
    "build_ecfr_citation",
    "build_guidance_citation",
    "classify",
    "parse_cfr_reference",
    "parse_cfr_references",
    "scan_references",
]
