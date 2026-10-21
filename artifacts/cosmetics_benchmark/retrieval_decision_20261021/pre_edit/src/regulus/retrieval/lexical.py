"""LexicalRetriever: exact CFR lookup + full-text + trigram over PostgreSQL.

Two entry points share the same SQL legs:

run_plan(plan)  Stage 2, the canonical path. Every Requirement in the
                QueryPlan is retrieved on its own (exact row + descendants,
                then its parent paragraph as structural context); the
                question's full-text search adds supporting material; broad
                methods (OR fallback, trigram) run only per *unresolved*
                requirement, on that requirement's identifier. Results are
                classified by identity into an EvidenceRegistry, and exact
                and structural evidence is never cut by top_k.

run(query)      Stage 5-7 query-level path, kept unchanged for the hybrid
                retriever, scripts and the evaluation baselines:

    query ─► classify ─► exact lookup (first CFR ref / docket only)
                     ├─► full-text on each selected corpus
                     └─► trigram on eCFR sections (short/identifier queries,
                         or when full-text under-delivers)
          ─► merge (de-duplicate, strongest method, deterministic order) ─► top_k
"""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

from regulus.retrieval.base import Filters, normalise_corpus
from regulus.retrieval.citations import build_ecfr_citation, build_guidance_citation
from regulus.retrieval.db import Database
from regulus.retrieval.models import (
    METHOD_CROSS_REFERENCE,
    METHOD_DEFINITION,
    METHOD_EXACT_CFR,
    METHOD_EXACT_DOCKET,
    METHOD_FULL_TEXT,
    METHOD_FULL_TEXT_OR,
    METHOD_TRIGRAM,
    RetrievalResult,
)
from regulus.retrieval.evidence import (
    TIER_DISCOVERY,
    TIER_EXACT,
    TIER_STRUCTURAL,
    TIER_SUPPORTING,
    Evidence,
    EvidenceRegistry,
    RequirementRetrieval,
    classify_result,
    order_evidence,
)
from regulus.retrieval.query import (
    QueryType,
    choose_defining_section,
    classify,
    content_terms,
    defined_term_pattern,
    definition_term,
    question_words,
    definitional_terms,
    fallback_terms,
    HEADING_MAX_SECTIONS,
    HEADING_MAX_WORD_DF,
    heading_in_question,
    heading_words,
    looks_like_identifier,
)
from regulus.retrieval.ranking import (
    definition_score,
    exact_score,
    full_text_or_score,
    full_text_score,
    merge,
    part_stem_score,
    section_coverage_score,
    structural_score,
    trigram_score,
)
from regulus.retrieval.references import CfrReference, _PARA_TOKEN_RE
from regulus.retrieval import sql

if TYPE_CHECKING:
    from regulus.planning.plan import QueryPlan

log = logging.getLogger("regulus.retrieval")

DEFAULT_METHODS = (METHOD_EXACT_CFR, METHOD_EXACT_DOCKET, METHOD_FULL_TEXT, METHOD_FULL_TEXT_OR, METHOD_TRIGRAM, METHOD_DEFINITION)
PRIMARY_METHODS = (METHOD_EXACT_CFR, METHOD_EXACT_DOCKET, METHOD_FULL_TEXT, METHOD_DEFINITION)
DEFINITION_LIMIT = 3  # the asked term's definitions kept as evidence; many parts define the same term
TRIGRAM_MAX_WORDS = 4
# Stage 7 controlled OR fallback defaults
DEFAULT_ENABLE_OR_FALLBACK = True
DEFAULT_PRIMARY_MIN_RESULTS = 3
DEFAULT_FALLBACK_MAX_TERMS = 8
GUIDANCE_CHUNKS_PER_DOCUMENT = 3
CANDIDATE_MULTIPLIER = 2  # fetch a little more than top_k per method before merging
GUIDANCE_CANDIDATE_MULTIPLIER = 10  # chunks ranked before the per-document cap is applied
# Stage 2: rows fetched per requirement by the exact leg. A paragraph lookup
# returns the paragraph and its descendants; a section lookup returns every
# row of the section. This is a resource guardrail, not a relevance cut.
DEFAULT_EXACT_ROW_LIMIT = 100
# Stage 2, part-level depth. A part-level request retrieves the first row of
# each section of the part (ECFR_EXACT_PART, `ordinal = 0`), which for many
# sections is a lead-in - "The definitions and interpretations of terms in
# section 201 of the act apply ..." - whose substance lives in the rows below
# it. The sections the question actually matches are expanded to their own
# paragraph rows, through ECFR_EXACT_SECTION, so a part-level answer can quote
# the provision instead of its lead-in. Bounded on both axes: only the N
# best-ranked MATCHING sections are expanded, and at most M rows of each, in the
# spirit of chunks_per_document - one section must not fill the whole context.
#
# 3 sections x 2 rows is what the existing ceilings afford, measured over the 113
# part-level acceptance questions (retrieval + selection only, no generation):
# the expected section reaches the prompt with substantive rows, not just its
# lead-in, for 73 of 152 expected sections against 1 before, while 130 of the 132
# that C1 already delivered stay. Going wider (4x2) or deeper (3x3, 2x6) buys no
# further depth and costs 6 more of those - the 9,000-character ceiling is full
# either way, so depth is paid for out of breadth. Raising the ceiling is a
# separate question and is deliberately not touched here.
DEFAULT_PART_EXPAND_SECTIONS = 3
DEFAULT_PART_EXPAND_ROWS = 2
DISCOVERY_METHODS = (METHOD_FULL_TEXT_OR, METHOD_TRIGRAM, METHOD_CROSS_REFERENCE)
# RC1, section coverage (sql.ECFR_SECTION_COVERAGE), for a question that names no provision and
# no docket. Run when the question's AND full-text search found fewer than primary_min_results
# eCFR paragraphs: AND needs every word of the question in one paragraph, which long guidance
# chunks satisfy far more often than short eCFR paragraphs, so the existing all-corpus trigger
# (primary_count) can be met by guidance alone while no binding text was found. Its rows are
# OR-method (discovery) evidence and a secondary source: rows only this leg found are ordered after
# all other evidence (the existing ranking is unchanged), and up to half of the top_k candidate
# slots are kept for them, so a long list of weak matches cannot push them out of the candidate
# list; at most two rows per section, so one section cannot take every slot.
DEFAULT_SECTION_COVERAGE = True
SECTION_COVERAGE_ROWS_PER_SECTION = 2
SECTION_COVERAGE_LEG = f"{METHOD_FULL_TEXT_OR}:section_coverage"

# Defined terms of a definitional general question (query.definitional_terms): the paragraphs of the one
# section that best defines the question's terms, as definition evidence. Runs after every other general
# leg, so their decisions (OR fallback, section coverage) are computed exactly as before; it only adds.
DEFAULT_DEFINED_TERMS = True
DEFINED_TERMS_LEG = f"{METHOD_DEFINITION}:defined_terms"
DEFINED_TERM_ROW_LIMIT = 40     # defining paragraphs per term, across the corpus, before the section is chosen
DEFINED_TERMS_MAX_ROWS = 4      # defining paragraphs kept from the chosen section
DEFINED_TERM_CHILD_LIMIT = 8    # sub-paragraphs kept under a definition that is a list lead-in ("includes:")

# Heading corroboration (general questions only): an eCFR candidate the retriever ALREADY found whose specific section
# heading occurs verbatim in the question (query.heading_in_question) is kept for the prompt: it is moved to the
# front of the optional evidence and is not removed by the trigram cut-off. Nothing new is retrieved.
DEFAULT_HEADING_CORROBORATION = True
HEADING_PROMOTED_MAX_ROWS = 3

# P3 cross-reference expansion (general questions only, OFF by default until measured): the provisions that the first
# XREF_SEEDS eCFR candidates explicitly cite (sql.ECFR_CROSS_REFERENCED, one hop, never recursive) are added after
# every other candidate as DISCOVERY evidence, at most XREF_MAX_ROWS of them, each recording the provision that cites
# it and the reference text (`xref_from`, `xref_text`). Measured offline 2026-10-20: the provisions the prompt's own
# sources cite held 11 missing draft-key provisions and added a median of 0 sections per question (p90 2, max 6);
# following references the other way (provisions that cite a source) reached 8 and added up to 26, so it is not used.
DEFAULT_CROSS_REFERENCES = False

XREF_LEG = f"{METHOD_CROSS_REFERENCE}:cites"
XREF_SEEDS = 4
XREF_MAX_ROWS = 3
XREF_ROW_LIMIT = 40


@dataclass
class SearchResponse:
    query: str
    query_type: QueryType
    results: list[RetrievalResult]
    timings_ms: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    total_ms: float = 0.0
    notes: list[str] = field(default_factory=list)
    # Stage 7 diagnostics: primary_result_count, fallback_used, fallback_terms,
    # fallback_candidate_count, final_result_count, retrieval_mode
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "query_type": self.query_type.value,
            "results": [r.to_dict() for r in self.results],
            "timings_ms": self.timings_ms,
            "counts": self.counts,
            "total_ms": self.total_ms,
            "notes": list(self.notes),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass
class PlanRetrieval:
    """Result of run_plan(): the registry (all evidence, per requirement) and a
    SearchResponse whose `results` are the ordered evidence with exact and
    structural rows protected from the top_k cut."""

    plan: "QueryPlan"
    registry: EvidenceRegistry
    response: SearchResponse

    @property
    def results(self) -> list[RetrievalResult]:
        return self.response.results

    def to_dict(self) -> dict[str, Any]:
        return {"plan": self.plan.to_dict(), "registry": self.registry.to_dict(), "response": self.response.to_dict()}


def _parent_path(paragraph_path: str) -> str | None:
    """"(b)(1)" -> "(b)"; "(b)" -> "" (the section row); "" -> None (no parent row)."""
    if not paragraph_path:
        return None
    tokens = _PARA_TOKEN_RE.findall(paragraph_path)
    return "".join(f"({t})" for t in tokens[:-1])


class LexicalRetriever:
    """Implements the Retriever protocol using only lexical PostgreSQL features."""

    def __init__(
        self,
        db: Database,
        *,
        chunks_per_document: int = GUIDANCE_CHUNKS_PER_DOCUMENT,
        enable_or_fallback: bool = DEFAULT_ENABLE_OR_FALLBACK,
        primary_min_results: int = DEFAULT_PRIMARY_MIN_RESULTS,
        fallback_max_terms: int = DEFAULT_FALLBACK_MAX_TERMS,
        exact_row_limit: int = DEFAULT_EXACT_ROW_LIMIT,
        part_expand_sections: int = DEFAULT_PART_EXPAND_SECTIONS,
        part_expand_rows: int = DEFAULT_PART_EXPAND_ROWS,
        section_coverage: bool = DEFAULT_SECTION_COVERAGE,
        defined_terms: bool = DEFAULT_DEFINED_TERMS,
        heading_corroboration: bool = DEFAULT_HEADING_CORROBORATION,
        cross_references: bool = DEFAULT_CROSS_REFERENCES,
    ) -> None:
        """enable_or_fallback=False reproduces the Stage 5 retriever exactly.

        Fallback trigger (Stage 7): after the exact, AND full-text and trigram
        legs have run, count the distinct results found by a primary method
        (exact_cfr, exact_docket, full_text). If that count is below
        primary_min_results, run one OR full-text query per selected corpus
        built from fallback_terms(query) and merge its candidates at the lower
        full_text_or score/priority.
        """
        if primary_min_results < 0 or fallback_max_terms < 0:
            raise ValueError("primary_min_results and fallback_max_terms must be >= 0")
        if exact_row_limit <= 0:
            raise ValueError("exact_row_limit must be positive")
        if part_expand_sections < 0 or part_expand_rows < 0:
            raise ValueError("part_expand_sections and part_expand_rows must be >= 0")
        self.db = db
        self.chunks_per_document = chunks_per_document
        self.enable_or_fallback = enable_or_fallback
        self.primary_min_results = primary_min_results
        self.fallback_max_terms = fallback_max_terms
        self.exact_row_limit = exact_row_limit
        self.part_expand_sections = part_expand_sections
        self.part_expand_rows = part_expand_rows
        self.section_coverage = section_coverage
        self.defined_terms = defined_terms
        self.heading_corroboration = heading_corroboration
        self.cross_references = cross_references
        self._heading_counts: dict[str, int] = {}

    def describe(self) -> dict[str, Any]:
        return {
            "retriever": "LexicalRetriever",
            "enable_or_fallback": self.enable_or_fallback,
            "primary_min_results": self.primary_min_results,
            "fallback_max_terms": self.fallback_max_terms,
            "chunks_per_document": self.chunks_per_document,
            "part_expand_sections": self.part_expand_sections,
            "part_expand_rows": self.part_expand_rows,
            "section_coverage": self.section_coverage,
            "defined_terms": self.defined_terms,
            "heading_corroboration": self.heading_corroboration,
            "cross_references": self.cross_references,
        }

    # -- public API --------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        corpus: str | None = None,
        top_k: int = 10,
        filters: Filters | None = None,
        methods: Iterable[str] | None = None,
    ) -> list[RetrievalResult]:
        return self.run(query, corpus=corpus, top_k=top_k, filters=filters, methods=methods).results

    def run(
        self,
        query: str,
        *,
        corpus: str | None = None,
        top_k: int = 10,
        filters: Filters | None = None,
        methods: Iterable[str] | None = None,
    ) -> SearchResponse:
        """Like search() but also reports per-method timings and counts."""
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        corpora = normalise_corpus(corpus)
        filters = filters or Filters()
        enabled = tuple(methods) if methods is not None else DEFAULT_METHODS
        unknown = set(enabled) - set(DEFAULT_METHODS)
        if unknown:
            raise ValueError(f"unknown method(s): {sorted(unknown)}")

        start = time.perf_counter()
        classification = classify(query)
        if classification.query_type is QueryType.EMPTY:
            raise ValueError("query must not be empty")
        limit = max(top_k * CANDIDATE_MULTIPLIER, top_k)

        candidates: list[RetrievalResult] = []
        timings: dict[str, float] = {}
        counts: dict[str, int] = {}

        def timed(name: str, fn, *args):
            t0 = time.perf_counter()
            rows = fn(*args)
            timings[name] = round((time.perf_counter() - t0) * 1000, 2)
            counts[name] = len(rows)
            candidates.extend(rows)
            return rows

        notes: list[str] = []
        if "ecfr" in corpora and METHOD_EXACT_CFR in enabled and classification.cfr is not None:
            if not timed(METHOD_EXACT_CFR, self.exact_cfr, classification.cfr, filters, limit):
                notes.append(
                    f"No live record for {classification.cfr.label} in this eCFR snapshot "
                    "(section may be reserved, removed, outside Title 21, or excluded by filters); "
                    "remaining results are text matches only."
                )
        if "fda_guidance" in corpora and METHOD_EXACT_DOCKET in enabled and classification.docket is not None:
            timed(METHOD_EXACT_DOCKET, self.exact_docket, classification.docket, filters, limit)

        if METHOD_FULL_TEXT in enabled:
            if "ecfr" in corpora:
                timed(f"{METHOD_FULL_TEXT}:ecfr", self.full_text_ecfr, query, filters, limit)
            if "fda_guidance" in corpora:
                timed(f"{METHOD_FULL_TEXT}:fda_guidance", self.full_text_guidance, query, filters, limit)

        if "ecfr" in corpora and METHOD_TRIGRAM in enabled and self._should_run_trigram(query, counts, top_k):
            timed(METHOD_TRIGRAM, self.trigram_ecfr, query, filters, limit)

        # -- Stage 7: controlled OR fallback ---------------------------------
        primary_count = len({c.key for c in candidates if c.retrieval_method in PRIMARY_METHODS})
        fallback_used = False
        terms: list[str] = []
        fallback_candidates = 0
        if (
            self.enable_or_fallback
            and METHOD_FULL_TEXT_OR in enabled
            and METHOD_FULL_TEXT in enabled
            and primary_count < self.primary_min_results
        ):
            terms = fallback_terms(query, self.fallback_max_terms)
            if terms:
                fallback_used = True
                or_query = " or ".join(terms)
                if "ecfr" in corpora:
                    fallback_candidates += len(timed(f"{METHOD_FULL_TEXT_OR}:ecfr", self.full_text_or_ecfr, or_query, filters, top_k))
                if "fda_guidance" in corpora:
                    fallback_candidates += len(timed(f"{METHOD_FULL_TEXT_OR}:fda_guidance", self.full_text_or_guidance, or_query, filters, top_k))

        results = merge(candidates, top_k=top_k)
        if not results:
            mode = "none"
        elif any(r.retrieval_method in (METHOD_EXACT_CFR, METHOD_EXACT_DOCKET) for r in results):
            mode = "exact"
        elif fallback_used and any(r.retrieval_method == METHOD_FULL_TEXT_OR for r in results):
            mode = "fallback"
        else:
            mode = "primary"
        diagnostics = {
            "primary_result_count": primary_count,
            "fallback_used": fallback_used,
            "fallback_terms": terms,
            "fallback_candidate_count": fallback_candidates,
            "final_result_count": len(results),
            "retrieval_mode": mode,
        }
        total_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info(
            "query=%r type=%s corpus=%s methods=%s results=%d mode=%s fallback=%s total_ms=%.1f timings=%s",
            query[:200], classification.query_type.value, ",".join(corpora),
            ",".join(k for k in counts), len(results), mode, fallback_used, total_ms, timings,
        )
        return SearchResponse(query, classification.query_type, results, timings, counts, total_ms, notes, diagnostics)

    # -- Stage 2: plan-driven, requirement-level retrieval -------------------

    def run_plan(
        self,
        plan: "QueryPlan",
        *,
        corpus: str | None = None,
        top_k: int = 10,
        filters: Filters | None = None,
        methods: Iterable[str] | None = None,
    ) -> PlanRetrieval:
        """Retrieve evidence for every requirement of `plan` (see module docstring).

        `top_k` bounds only the supporting/discovery remainder of the returned
        results; exact and structural evidence is always kept. The registry
        holds everything that was found, classified by identity.
        """
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if plan.query_type is QueryType.EMPTY:
            raise ValueError("query must not be empty")
        corpora = normalise_corpus(corpus)
        filters = filters or Filters()
        enabled = tuple(methods) if methods is not None else DEFAULT_METHODS
        unknown = set(enabled) - set(DEFAULT_METHODS)
        if unknown:
            raise ValueError(f"unknown method(s): {sorted(unknown)}")

        start = time.perf_counter()
        question = plan.normalized_question or plan.question
        text_limit = max(top_k * CANDIDATE_MULTIPLIER, top_k)
        candidates: list[RetrievalResult] = []
        timings: dict[str, float] = {}
        counts: dict[str, int] = {}
        notes: list[str] = []
        discovered: dict[str, set[str]] = {}  # result key -> requirement ids whose fallback found it

        def timed(name: str, fn, *args) -> list[RetrievalResult]:
            t0 = time.perf_counter()
            rows = fn(*args)
            timings[name] = round(timings.get(name, 0.0) + (time.perf_counter() - t0) * 1000, 2)
            counts[name] = counts.get(name, 0) + len(rows)
            candidates.extend(rows)
            return rows

        ecfr_on = "ecfr" in corpora
        guidance_on = "fda_guidance" in corpora
        exact_on = ecfr_on and METHOD_EXACT_CFR in enabled
        or_on = self.enable_or_fallback and METHOD_FULL_TEXT_OR in enabled and METHOD_FULL_TEXT in enabled
        trigram_on = ecfr_on and METHOD_TRIGRAM in enabled

        # 1. every requirement independently: exact rows, then the parent paragraph
        attempted: dict[str, bool] = {}
        req_notes: dict[str, str | None] = {}
        exact_found: dict[str, bool] = {}
        exact_cache: dict[tuple, list[RetrievalResult]] = {}
        parent_cache: dict[tuple, list[RetrievalResult]] = {}
        for req in plan.requirements:
            ref = req.reference
            rows: list[RetrievalResult] = []
            note = None
            if not exact_on:
                note = "eCFR corpus or exact lookup not selected for this search"
            elif ref.title != "21":
                note = f"{ref.canonical} is outside Title 21; this corpus cannot resolve it"
            else:
                attempted[req.id] = True
                if ref.key in exact_cache:
                    rows = exact_cache[ref.key]  # duplicate reference: reuse, no second query
                else:
                    rows = timed(f"{METHOD_EXACT_CFR}:{req.id}", self.exact_cfr, ref, filters, self.exact_row_limit, question)
                    exact_cache[ref.key] = rows
                if not rows:
                    note = (
                        f"No live record for {ref.canonical} in this eCFR snapshot "
                        "(section may be reserved, removed, outside Title 21, or excluded by filters); "
                        "remaining results are text matches only."
                    )
                    notes.append(note)
                parent = _parent_path(ref.paragraph_path) if ref.section is not None else None
                if parent is not None and (ref.section, parent) not in parent_cache:
                    parent_cache[(ref.section, parent)] = timed(f"structural:{req.id}", self.exact_row, ref.section, parent, filters)
            attempted.setdefault(req.id, False)
            exact_found[req.id] = bool(rows)
            req_notes[req.id] = note

        # 2. docket (guidance) lookup
        docket_hits = 0
        if guidance_on and METHOD_EXACT_DOCKET in enabled and plan.docket is not None:
            docket_hits = len(timed(METHOD_EXACT_DOCKET, self.exact_docket, plan.docket, filters, text_limit))
            if docket_hits == 0:
                notes.append(
                    f"No guidance document with docket {plan.docket} was found in this snapshot; "
                    "any retrieved passages are related material only and do not show that the docket exists."
                )

        # 3a. a definitional question about one term ("What does FDA stand for?")
        # names no provision, and its words ("stand for") are not the words the
        # CFR defines with ("FDA means ..."): look the term's definition up. When
        # the CFR defines it, that IS the evidence, and the question's own
        # keyword search is skipped - its frame words only match noise ("stand"
        # in "good standing"). When it does not, retrieval is unchanged.
        term = definition_term(question) if not plan.requirements else None
        definitions: list[RetrievalResult] = []
        if term is not None and ecfr_on and METHOD_DEFINITION in enabled:
            definitions = timed(METHOD_DEFINITION, self.definition_ecfr, term, filters, DEFINITION_LIMIT)
            if definitions:
                notes.append(f"The CFR's own definition of \"{term}\" was retrieved; the keyword search was not run.")

        # 3. supporting: the question's own full-text search on each corpus
        if METHOD_FULL_TEXT in enabled and not definitions:
            if ecfr_on:
                timed(f"{METHOD_FULL_TEXT}:ecfr", self.full_text_ecfr, question, filters, text_limit)
            if guidance_on:
                timed(f"{METHOD_FULL_TEXT}:fda_guidance", self.full_text_guidance, question, filters, text_limit)

        # 4. broad methods: per unresolved requirement only, on that identifier.
        # Skipped when the requirement's parent paragraph was found: the section
        # exists and only the paragraph is missing, so searching the section
        # number again would only return similarly numbered sections.
        fallback_terms_used: dict[str, tuple[str, ...]] = {}
        for req in plan.requirements:
            if not attempted[req.id] or exact_found[req.id]:
                continue
            ref = req.reference
            parent = _parent_path(ref.paragraph_path) if ref.section is not None else None
            if parent is not None and parent_cache.get((ref.section, parent)):
                req_notes[req.id] = (
                    f"No live record for {ref.canonical} in this eCFR snapshot, but its parent "
                    f"{ref.title} CFR {ref.section}{parent} exists; no broad search was run for it."
                )
                continue
            term = ref.section if ref.section is not None else ref.part
            found: list[RetrievalResult] = []
            if or_on:
                if ecfr_on:
                    found += timed(f"{METHOD_FULL_TEXT_OR}:{req.id}:ecfr", self.full_text_or_ecfr, term, filters, top_k)
                if guidance_on:
                    found += timed(f"{METHOD_FULL_TEXT_OR}:{req.id}:fda_guidance", self.full_text_or_guidance, term, filters, top_k)
            if trigram_on and ref.section is not None:
                found += timed(f"{METHOD_TRIGRAM}:{req.id}", self.trigram_ecfr, ref.section, filters, top_k)
            if or_on or trigram_on:
                fallback_terms_used[req.id] = (term,)
            for r in found:
                discovered.setdefault(r.key, set()).add(req.id)

        # 5. general search (no requirements): the legacy trigram and question-level fallback
        question_fallback_terms: list[str] = []
        question_fallback_used = False
        coverage_keys: list[str] = []
        if not plan.requirements and not definitions:
            if trigram_on and self._should_run_trigram(question, counts, top_k):
                timed(METHOD_TRIGRAM, self.trigram_ecfr, question, filters, text_limit)
            # 5b. RC1: section coverage, when the question found (almost) no binding text by AND
            coverage_slots = top_k // 2
            if (self.section_coverage and plan.docket is None and ecfr_on and or_on and coverage_slots > 0
                    and counts.get(f"{METHOD_FULL_TEXT}:ecfr", 0) < self.primary_min_results):
                terms = content_terms(question)
                if terms:
                    earlier = {c.key for c in candidates}
                    found = timed(SECTION_COVERAGE_LEG, self.section_coverage_ecfr, " ".join(terms), filters, coverage_slots)
                    coverage_keys = [r.key for r in found if r.key not in earlier]
            primary_count = len({c.key for c in candidates if c.retrieval_method in PRIMARY_METHODS})
            if or_on and primary_count < self.primary_min_results:
                question_fallback_terms = fallback_terms(question, self.fallback_max_terms)
                if question_fallback_terms:
                    # set whether or not section coverage stood in for the eCFR OR query: the scope
                    # policy reads fallback_used as "no passage matched every term", which it does not change
                    question_fallback_used = True
                    or_query = " or ".join(question_fallback_terms)
                    # RC1: when section coverage found eCFR candidates it replaces the eCFR OR query,
                    # whose terms are the longest words of the question, not the informative ones
                    if ecfr_on and not coverage_keys:
                        timed(f"{METHOD_FULL_TEXT_OR}:ecfr", self.full_text_or_ecfr, or_query, filters, top_k)
                    if guidance_on:
                        timed(f"{METHOD_FULL_TEXT_OR}:fda_guidance", self.full_text_or_guidance, or_query, filters, top_k)

        # 5c. a general question that asks how the regulations define the things it names: the CFR paragraphs
        # that define its terms. After every other leg, so nothing above changes; it only adds evidence.
        if (self.defined_terms and not plan.requirements and not definitions and plan.docket is None and ecfr_on
                and METHOD_DEFINITION in enabled):
            weights = definitional_terms(question)
            if weights and timed(DEFINED_TERMS_LEG, self.defined_terms_ecfr, weights, question, filters):
                notes.append("The CFR paragraphs that define terms of the question were retrieved.")

        # 6. classify by identity and build the registry
        merged = merge(candidates)
        evidence: list[Evidence] = []
        for r in merged:
            tier, satisfies, structural_for, relations = classify_result(
                r, plan.requirements, discovered_for=tuple(sorted(discovered.get(r.key, ()))), discovery_methods=DISCOVERY_METHODS,
            )
            evidence.append(Evidence("", r, tier, satisfies, structural_for, tuple(sorted(discovered.get(r.key, ()))), relations))
        ordered = order_evidence(evidence, plan.requirements)
        if coverage_keys:
            # RC1: rows only the section-coverage leg found are a secondary source. They follow every
            # other piece of evidence instead of competing on score with the OR/trigram hits (their
            # 0-5 coverage scores are not on the same scale), so the existing ranking is unchanged and
            # they add to it; their candidate slots are kept below.
            secondary = set(coverage_keys)
            ordered = [e for e in ordered if e.key not in secondary] + [e for e in ordered if e.key in secondary]
        if self.heading_corroboration and not plan.requirements and ecfr_on:
            ordered = self._promote_heading_matches(ordered, question)
        if self.cross_references and not plan.requirements and plan.docket is None and ecfr_on:
            t_xref = time.perf_counter()
            linked = self._cross_referenced(ordered, plan, filters)
            timings[XREF_LEG] = round((time.perf_counter() - t_xref) * 1000, 2)
            counts[XREF_LEG] = len(linked)
            ordered = ordered + linked
        ordered = [
            Evidence(f"e{i}", e.result, e.tier, e.satisfies, e.structural_for, e.discovered_for, e.relations)
            for i, e in enumerate(ordered, start=1)
        ]
        states: dict[str, RequirementRetrieval] = {}
        for req in plan.requirements:
            states[req.id] = RequirementRetrieval(
                requirement_id=req.id,
                canonical=req.canonical,
                exact_attempted=attempted[req.id],
                exact_hits=sum(1 for e in ordered if req.id in e.satisfies),
                structural_hits=sum(1 for e in ordered if req.id in e.structural_for),
                discovery_hits=sum(1 for e in ordered if req.id in e.discovered_for),
                fallback_run=req.id in fallback_terms_used,
                fallback_terms=fallback_terms_used.get(req.id, ()),
                note=req_notes[req.id],
            )

        protected = [e for e in ordered if e.tier in (TIER_EXACT, TIER_STRUCTURAL)]
        remainder = [e for e in ordered if e.tier not in (TIER_EXACT, TIER_STRUCTURAL)]
        room = max(0, top_k - len(protected))
        if coverage_keys:
            # RC1: the section-coverage rows keep their slots (at most top_k // 2 of them); the other
            # candidates fill the rest; the registry's order is kept
            reserved = {e.key for e in [e for e in remainder if e.key in set(coverage_keys)][:room]}
            others = [e for e in remainder if e.key not in reserved][: room - len(reserved)]
            keep_keys = reserved | {e.key for e in others}
            kept = protected + [e for e in remainder if e.key in keep_keys]
        else:
            kept = protected + remainder[:room]
        results = [e.result for e in kept]

        primary_count = len({c.key for c in candidates if c.retrieval_method in PRIMARY_METHODS})
        fallback_used = question_fallback_used or bool(fallback_terms_used)
        all_terms = list(question_fallback_terms) + [t for terms in fallback_terms_used.values() for t in terms]
        if not results:
            mode = "none"
        elif any(e.tier == TIER_EXACT for e in kept):
            mode = "exact"
        elif fallback_used and any(e.tier == TIER_DISCOVERY for e in kept):
            mode = "fallback"
        else:
            mode = "primary"
        tier_counts = {t: sum(1 for e in ordered if e.tier == t) for t in (TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING, TIER_DISCOVERY)}
        method_counts: dict[str, int] = {}
        for e in ordered:
            method_counts[e.retrieval_method] = method_counts.get(e.retrieval_method, 0) + 1
        unresolved = [r.id for r in plan.requirements if not states[r.id].resolved]
        plan_diag = {
            "kind": plan.kind,
            "requirement_count": len(plan.requirements),
            "requirement_ids": [r.id for r in plan.requirements],
            "exact_attempts": sum(1 for r in plan.requirements if attempted[r.id]),
            "resolved": [r.id for r in plan.requirements if states[r.id].resolved],
            "unresolved": unresolved,
            "tier_counts": tier_counts,
            "method_counts": method_counts,
            "candidate_count": len(candidates),
            "evidence_count": len(ordered),
            "protected_count": len(protected),
            "docket_requested": plan.docket,
            "docket_hits": docket_hits,
            "question_fallback_used": question_fallback_used,
            "requirements": {rid: st.to_dict() for rid, st in states.items()},
        }
        diagnostics = {
            "primary_result_count": primary_count,
            "fallback_used": fallback_used,
            "fallback_terms": all_terms,
            "fallback_candidate_count": sum(n for name, n in counts.items() if name.startswith(METHOD_FULL_TEXT_OR)),
            "section_coverage": {"run": SECTION_COVERAGE_LEG in counts, "candidates": len(coverage_keys),
                                 "kept": sum(1 for e in kept if e.key in coverage_keys)},
            "final_result_count": len(results),
            "retrieval_mode": mode,
            "plan": plan_diag,
        }
        registry = EvidenceRegistry(plan=plan, evidence=tuple(ordered), requirement_state=states, diagnostics=plan_diag)
        total_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info(
            "plan kind=%s requirements=%d resolved=%d unresolved=%s corpus=%s evidence=%d results=%d mode=%s total_ms=%.1f",
            plan.kind, len(plan.requirements), len(plan.requirements) - len(unresolved), unresolved,
            ",".join(corpora), len(ordered), len(results), mode, total_ms,
        )
        response = SearchResponse(question, plan.query_type, results, timings, counts, total_ms, notes, diagnostics)
        return PlanRetrieval(plan=plan, registry=registry, response=response)

    # -- method implementations -------------------------------------------

    def exact_cfr(self, ref: CfrReference, filters: Filters, limit: int, question: str | None = None) -> list[RetrievalResult]:
        """The requested section/paragraph rows. A paragraph returns itself plus
        its descendants (match_kind exact / descendant); a section returns all
        its rows; a part returns the first row of each section.

        `question` is used for part-level references only. It orders the part's
        section stems by relevance (it never filters them - see ECFR_EXACT_PART)
        and decides which of them are deepened to their own paragraph rows (see
        part_section_rows). It never touches a section- or paragraph-level
        lookup. Omitting it scores and orders a part by ASCII section number and
        deepens nothing, which is the behaviour this method had before either.
        """
        if ref.title != "21":
            return []  # the corpus holds Title 21 only; other titles cannot match
        params = self._ecfr_filter_params(filters)
        part_level = ref.section is None
        if part_level:
            rank_query = self.part_rank_query(question)
            rows = self.db.query(
                sql.ECFR_EXACT_PART,
                {**params, "part_number": ref.part, "query": rank_query, "limit": limit},
            )
        else:
            rank_query = ""
            rows = self.db.query(
                sql.ECFR_EXACT_SECTION,
                {
                    **params,
                    "section_number": ref.section,
                    "paragraph": ref.paragraph_path,
                    "paragraph_prefix": ref.paragraph_path + "(%",
                    "limit": limit,
                },
            )
        out = []
        expand: list[tuple[str, float]] = []  # (section_number, score) of the sections to deepen
        for position, row in enumerate(rows):
            meta = {"match_kind": row["match_kind"], "requested": ref.label}
            if part_level and rank_query:
                # the rows arrive in relevance order, so the position IS the rank
                score = part_stem_score(position)
                meta.update(part_relevance_rank=position, part_rank_query=rank_query,
                            ts_rank_cd=float(row["rank"]))
                if float(row["rank"]) > 0.0 and len(expand) < self.part_expand_sections:
                    expand.append((row["section_number"], score))
            else:
                # no relevance signal to spend (no question, or no term survived
                # selection): score and order the part exactly as before C1
                score = exact_score(row["match_kind"], row["ordinal"])
            out.append(self._ecfr_result(row, METHOD_EXACT_CFR, score, meta))
        for section, score in expand:
            out += self.part_section_rows(section, score, ref, filters)
        return out

    def part_section_rows(self, section: str, score: float, ref: CfrReference, filters: Filters) -> list[RetrievalResult]:
        """The substantive paragraph rows of one section of a requested part.

        A part-level request only ever saw each section's FIRST row, so a section
        whose first row is a lead-in reached the prompt without the provision it
        introduces. These are the rest of that section's rows, fetched with the
        same ECFR_EXACT_SECTION statement a section-level request uses, so the
        rows, their citations, their metadata and their match_kind are the ones
        the registry already knows how to classify - a part-level requirement
        makes every row of the part exact evidence either way.

        They carry their section's own relevance score, not one of their own:
        `order_evidence` breaks a score tie inside the exact tier by `ordinal`,
        which is document order, so each expanded section's rows follow its stem
        in the order the CFR prints them and the sections stay in C1's order.
        Nothing here re-ranks, and no row is added for a section C1 did not rank.
        """
        if self.part_expand_rows <= 0:
            return []
        rows = self.db.query(
            sql.ECFR_EXACT_SECTION,
            {
                **self._ecfr_filter_params(filters),
                "section_number": section,
                "paragraph": "",
                "paragraph_prefix": "(%",
                # +1: the stem (ordinal 0) is already in the result and is skipped below
                "limit": self.part_expand_rows + 1,
            },
        )
        return [
            self._ecfr_result(row, METHOD_EXACT_CFR, score,
                              {"match_kind": row["match_kind"], "requested": ref.label,
                               "part_expanded_from": section})
            for row in rows if row["ordinal"] != 0
        ]

    def part_rank_query(self, question: str | None) -> str:
        """The tsquery text that orders a requested part's section stems.

        The Stage 7 term selection (`fallback_terms`) is reused unchanged: it
        already drops question words and the regulatory words so common in this
        corpus that they carry no signal ("requirements", "section", "part",
        "applicable", ...), which is exactly what must not drive this ranking.
        The terms are OR-ed, as in the OR fallback, because a part-level
        question rarely has every term in one section stem and
        websearch_to_tsquery's default AND would score every stem 0.

        Returns "" when there is no question or no term survives selection; the
        statement then falls back to plain ASCII section order.
        """
        terms = fallback_terms(question or "", self.fallback_max_terms)
        return " or ".join(terms)

    def sections_in_part(self, part: str) -> list[tuple[str, int]]:
        """(section number, sort_order) for every section of `part`, in document order.

        Stage 1 uses this to fill in a cross-section range; see
        regulus.planning.ranges. It is a listing, not a retrieval leg: it returns
        no passages, scores nothing and feeds no evidence of its own. The rows it
        names are retrieved afterwards by the ordinary exact-section path.
        """
        rows = self.db.query(sql.ECFR_PART_SECTIONS, {"part_number": part})
        return [(row["number"], row["sort_order"]) for row in rows]

    def exact_row(self, section: str, paragraph_path: str, filters: Filters) -> list[RetrievalResult]:
        """Stage 2: exactly one eCFR row (a parent paragraph fetched as structural context)."""
        rows = self.db.query(
            sql.ECFR_EXACT_ROW,
            {**self._ecfr_filter_params(filters), "section_number": section, "paragraph": paragraph_path, "limit": 1},
        )
        return [self._ecfr_result(row, METHOD_EXACT_CFR, structural_score(row["ordinal"]), {"match_kind": "parent", "requested": f"parent of {section}{paragraph_path}"}) for row in rows]

    def exact_docket(self, docket: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        rows = self.db.query(
            sql.GUIDANCE_EXACT_DOCKET,
            {**self._guidance_filter_params(filters), "docket": docket, "per_document": self.chunks_per_document, "limit": limit},
        )
        return [self._guidance_result(row, METHOD_EXACT_DOCKET, exact_score("exact", row["ordinal"]), {"requested": docket}) for row in rows]

    def definition_ecfr(self, term: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        pattern = r"^\s*(\([0-9A-Za-z]{1,6}\)\s*)*" + re.escape(term).replace("\\ ", r"\s+") + r"\s+means\M"
        rows = self.db.query(sql.ECFR_DEFINITION, {**self._ecfr_filter_params(filters), "query": term, "pattern": pattern,
                                                   "limit": limit})
        return [self._ecfr_result(row, METHOD_DEFINITION, definition_score(i), {"defines": term}) for i, row in enumerate(rows)]

    def _heading_count(self, pattern: str) -> int:
        if pattern not in self._heading_counts:
            rows = self.db.query(sql.ECFR_HEADING_COUNT, {"query": pattern})
            self._heading_counts[pattern] = int(rows[0]["n"]) if rows else 0
        return self._heading_counts[pattern]

    def heading_is_specific(self, heading: str) -> bool:
        """Few sections carry this heading, and at least one of its words is rare among all section headings."""
        words = heading_words(heading)
        whole = r"^\s*" + r"[^a-z0-9]+".join(re.escape(w) for w in words) + r"[^a-z0-9]*$"
        if self._heading_count(whole) > HEADING_MAX_SECTIONS:
            return False
        return min(self._heading_count(r"\m" + re.escape(w) + r"\M") for w in words) <= HEADING_MAX_WORD_DF

    def _cross_referenced(self, ordered: list[Evidence], plan: "QueryPlan", filters: Filters) -> list[Evidence]:
        """The provisions the first XREF_SEEDS eCFR candidates cite, not already candidates, as DISCOVERY evidence
        (see DEFAULT_CROSS_REFERENCES). Each keeps the citing provision and the reference text in its metadata."""
        seeds = [e.result for e in ordered if e.result.corpus == "ecfr" and e.result.citation and e.result.citation.section][:XREF_SEEDS]
        if not seeds:
            return []
        rows = self.db.query(sql.ECFR_CROSS_REFERENCED, {
            **self._ecfr_filter_params(filters), "limit": XREF_ROW_LIMIT,
            "section_number": [r.metadata.get("section") or r.citation.section for r in seeds],
            "paragraph": [r.metadata.get("paragraph_path") or "" for r in seeds]})
        have = {e.key for e in ordered}
        out: list[Evidence] = []
        for row in rows:
            seed = seeds[int(row["seed_rank"]) - 1]
            result = self._ecfr_result(row, METHOD_CROSS_REFERENCE, 0.5, {
                "leg": "cross_references", "xref_from": seed.citation.label, "xref_text": row.get("xref_text")})
            if result.key in have:
                continue
            have.add(result.key)
            tier, satisfies, structural_for, relations = classify_result(
                result, plan.requirements, discovered_for=(), discovery_methods=DISCOVERY_METHODS)
            out.append(Evidence("", result, tier, satisfies, structural_for, (), relations))
            if len(out) >= XREF_MAX_ROWS:
                break
        return out

    def _promote_heading_matches(self, ordered: list[Evidence], question: str) -> list[Evidence]:
        """General questions: eCFR candidates whose specific section heading is in the question go to the front of
        the optional evidence as SUPPORTING evidence, marked `heading_match` (exempt from the trigram cut-off).

        Part corroboration: the section's CFR part must also be the part of some OTHER candidate that is not itself a
        heading match. Measured on the 300 benchmark questions (2026-10-20): every wrong-domain promotion (a food
        "statement of identity" question promoting the drug and device sections of that name; "recordkeeping
        requirements" promoting a tobacco part) came from a part nothing else retrieved - or only another section of
        the same heading - while the right ones had neighbours from their own part."""
        def part(r: RetrievalResult) -> str | None:
            section = r.citation.section if r.citation else None
            return section.split(".")[0] if section else None

        promoted: list[Evidence] = []
        for e in ordered:
            r = e.result
            own = r.citation.section if r.citation else None
            if (len(promoted) < HEADING_PROMOTED_MAX_ROWS and r.corpus == "ecfr" and e.tier in (TIER_SUPPORTING, TIER_DISCOVERY)
                    and r.heading and heading_in_question(r.heading, question)
                    and any(o.result.corpus == "ecfr" and part(o.result) == part(r) and o.result.citation.section != own
                            and not (o.result.heading and heading_in_question(o.result.heading, question))
                            for o in ordered)
                    and self.heading_is_specific(r.heading)):
                marked = dataclasses.replace(r, metadata={**(r.metadata or {}), "heading_match": True})
                promoted.append(Evidence(e.evidence_id, marked, TIER_SUPPORTING, e.satisfies, e.structural_for,
                                         e.discovered_for, e.relations))
        if not promoted:
            return ordered
        keys = {p.result.key for p in promoted}
        head = [e for e in ordered if e.tier in (TIER_EXACT, TIER_STRUCTURAL) and e.result.key not in keys]
        rest = [e for e in ordered if e.tier not in (TIER_EXACT, TIER_STRUCTURAL) and e.result.key not in keys]
        return head + promoted + rest

    def defined_terms_ecfr(self, weights: dict[str, int], question: str, filters: Filters) -> list[RetrievalResult]:
        """The defining paragraphs of the one section that best defines the question's terms (see
        query.choose_defining_section), in document order; [] when no section qualifies."""
        params = self._ecfr_filter_params(filters)
        hits: dict[str, dict[str, dict[str, Any]]] = {}
        headings: dict[str, str] = {}
        part_titles: dict[str, str] = {}
        for term in sorted(weights):
            rows = self.db.query(sql.ECFR_DEFINED_TERM, {**params, "query": term, "pattern": defined_term_pattern(term),
                                                         "limit": DEFINED_TERM_ROW_LIMIT})
            for row in rows:
                hits.setdefault(row["section_number"], {}).setdefault(term, row)
                headings[row["section_number"]] = row.get("section_heading") or ""
                part_titles[row["section_number"]] = row.get("part_title") or ""
        words = content_terms(question)

        def overlap(section: str) -> int:
            rows = self.db.query(sql.ECFR_SECTION_TEXT, {"section_number": section})
            text = ((rows[0].get("body_text") if rows else "") or "").lower()
            return sum(1 for w in words if re.search(r"\b" + re.escape(w) + r"\b", text))

        chosen = choose_defining_section(hits, weights, headings, overlap, part_titles=part_titles,
                                         question_words=question_words(question))
        if chosen is None:
            return []
        section, terms = chosen
        rows = {(r["paragraph_path"], r.get("path_ordinal", 0)): (r, t) for t in terms for r in [hits[section][t]]}
        ordered = sorted(rows.values(), key=lambda rt: rt[0]["ordinal"])[:DEFINED_TERMS_MAX_ROWS]
        # A definition that is a list lead-in ("(e) Combination product includes:") is defined by its
        # sub-paragraphs; the lead-in alone says nothing. Its descendants follow it, in document order.
        out: list[tuple[dict[str, Any], str]] = []
        for r, t in ordered:
            out.append((r, t))
            path = r.get("paragraph_path") or ""
            if path and (r.get("body_text") or "").rstrip().endswith(":"):
                children = self.db.query(sql.ECFR_EXACT_SECTION, {**params, "section_number": section, "paragraph": path,
                                                                  "paragraph_prefix": path + "(%",
                                                                  "limit": DEFINED_TERM_CHILD_LIMIT + 1})
                out += [(c, t) for c in children if c.get("match_kind") == "descendant"][:DEFINED_TERM_CHILD_LIMIT]
        return [self._ecfr_result(r, METHOD_DEFINITION, definition_score(i), {"defines": t, "leg": "defined_terms"})
                for i, (r, t) in enumerate(out)]

    def full_text_ecfr(self, query: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        rows = self.db.query(sql.ECFR_FULL_TEXT, {**self._ecfr_filter_params(filters), "query": query, "limit": limit})
        return [self._ecfr_result(row, METHOD_FULL_TEXT, full_text_score(row["rank"]), {"ts_rank_cd": float(row["rank"])}) for row in rows]

    def full_text_guidance(self, query: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        rows = self.db.query(
            sql.GUIDANCE_FULL_TEXT,
            {
                **self._guidance_filter_params(filters),
                "query": query,
                "per_document": self.chunks_per_document,
                "candidate_limit": limit * GUIDANCE_CANDIDATE_MULTIPLIER,
                "limit": limit,
            },
        )
        return [self._guidance_result(row, METHOD_FULL_TEXT, full_text_score(row["rank"]), {"ts_rank_cd": float(row["rank"])}) for row in rows]

    def full_text_or_ecfr(self, or_query: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        """Same parameterised statement and index as full_text_ecfr; the query
        string is 'term1 or term2 ...' which websearch_to_tsquery turns into an
        OR tsquery. Bounded by `limit` (= top_k) and scored at half scale."""
        rows = self.db.query(sql.ECFR_FULL_TEXT, {**self._ecfr_filter_params(filters), "query": or_query, "limit": limit})
        n_terms = or_query.count(" or ") + 1
        return [self._ecfr_result(row, METHOD_FULL_TEXT_OR, full_text_or_score(row["rank"], n_terms), {"ts_rank_cd": float(row["rank"]), "or_query": or_query}) for row in rows]

    def full_text_or_guidance(self, or_query: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        rows = self.db.query(
            sql.GUIDANCE_FULL_TEXT,
            {
                **self._guidance_filter_params(filters),
                "query": or_query,
                "per_document": self.chunks_per_document,
                "candidate_limit": limit * GUIDANCE_CANDIDATE_MULTIPLIER,
                "limit": limit,
            },
        )
        n_terms = or_query.count(" or ") + 1
        return [self._guidance_result(row, METHOD_FULL_TEXT_OR, full_text_or_score(row["rank"], n_terms), {"ts_rank_cd": float(row["rank"]), "or_query": or_query}) for row in rows]

    def section_coverage_ecfr(self, terms: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        """RC1: the paragraphs of the eCFR sections that cover most of the question's weight
        (sql.ECFR_SECTION_COVERAGE). OR-method evidence: scored in the fallback band, discovery tier."""
        rows = self.db.query(
            sql.ECFR_SECTION_COVERAGE,
            {**self._ecfr_filter_params(filters), "query": terms, "sections": limit,
             "rows_per_section": SECTION_COVERAGE_ROWS_PER_SECTION, "limit": limit},
        )
        return [
            self._ecfr_result(row, METHOD_FULL_TEXT_OR, section_coverage_score(row["section_score"], row["row_score"]),
                              {"section_coverage": round(float(row["section_score"]), 4),
                               "paragraph_coverage": round(float(row["row_score"]), 4), "coverage_terms": terms})
            for row in rows
        ]

    def trigram_ecfr(self, query: str, filters: Filters, limit: int) -> list[RetrievalResult]:
        rows = self.db.query(sql.ECFR_TRIGRAM, {**self._ecfr_filter_params(filters), "query": query, "limit": limit})
        return [self._ecfr_result(row, METHOD_TRIGRAM, trigram_score(row["sim"]), {"similarity": float(row["sim"])}) for row in rows]

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _should_run_trigram(query: str, counts: dict[str, int], top_k: int) -> bool:
        """Trigram is a complement for short or identifier-like queries and a
        fallback when full-text on eCFR returned fewer than top_k rows."""
        words = len(query.split())
        ecfr_hits = counts.get(f"{METHOD_FULL_TEXT}:ecfr")
        return words <= TRIGRAM_MAX_WORDS or looks_like_identifier(query) or (ecfr_hits is not None and ecfr_hits < top_k)

    @staticmethod
    def _ecfr_filter_params(filters: Filters) -> dict[str, Any]:
        return {"part": filters.part, "section": filters.section, "subchapter": filters.subchapter}

    @staticmethod
    def _guidance_filter_params(filters: Filters) -> dict[str, Any]:
        return {
            "retrievable": filters.retrievable,
            "sector": filters.sector,
            "center": filters.center,
            "status": filters.status,
            "anchor_part": filters.anchor_part,
            "anchor_section": filters.anchor_section,
        }

    @staticmethod
    def _ecfr_result(row: dict[str, Any], method: str, score: float, extra: dict[str, Any]) -> RetrievalResult:
        citation = build_ecfr_citation(row)
        key = f"ecfr:{row['section_number']}:{row.get('paragraph_path') or ''}:{row.get('path_ordinal', 0)}"
        metadata = {
            "subchapter": row.get("subchapter_code"),
            "part": row.get("part_number"),
            "part_title": row.get("part_title"),
            "section": row.get("section_number"),
            "paragraph_path": row.get("paragraph_path") or None,
            "ordinal": row.get("ordinal"),
            "parent_headings": list(row.get("parent_headings") or []),
            "govinfo_pdf_url": row.get("govinfo_pdf_url"),
            "snapshot_date": (row["snapshot_date"].isoformat() if hasattr(row["snapshot_date"], "isoformat") else row["snapshot_date"]) if row.get("snapshot_date") else None,
            "scores": {method: round(score, 4)},
            **extra,
        }
        return RetrievalResult(
            corpus="ecfr",
            text=row["body_text"],
            heading=row.get("section_heading"),
            relevance_score=score,
            retrieval_method=method,
            source_url=row.get("ecfr_permalink"),
            citation=citation,
            metadata=metadata,
            key=key,
        )

    @staticmethod
    def _guidance_result(row: dict[str, Any], method: str, score: float, extra: dict[str, Any]) -> RetrievalResult:
        citation = build_guidance_citation(row)
        key = f"fda_guidance:{row['source_url']}#{row['ordinal']}"
        metadata = {
            "chunk_ordinal": row.get("ordinal"),
            "start_offset": row.get("start_offset"),
            "sector": row.get("sector"),
            "center": row.get("center"),
            "status": row.get("status"),
            "doc_class": row.get("doc_class"),
            "anchor_part": row.get("anchor_part"),
            "anchor_section": row.get("anchor_section"),
            "retrievable": row.get("retrievable"),
            "scores": {method: round(score, 4)},
            **extra,
        }
        return RetrievalResult(
            corpus="fda_guidance",
            text=row["body_text"],
            heading=row.get("title_text") or row.get("title"),
            relevance_score=score,
            retrieval_method=method,
            source_url=row.get("source_url"),
            citation=citation,
            metadata=metadata,
            key=key,
        )
