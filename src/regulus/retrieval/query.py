"""Deterministic query classification and CFR reference parsing. No LLM.

Reference extraction lives in regulus.retrieval.references (Stage 1): every
form it recognises, ranges, lists and continuations. This module keeps the
classification API used by the retrievers and re-exports CfrReference so
existing imports keep working. parse_cfr_reference() returns the FIRST
reference in text order; classify() exposes all of them.

Docket numbers such as FDA-2016-D-2565 are also recognised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from regulus.retrieval.references import (  # noqa: F401  (re-exported)
    DEFAULT_TITLE,
    CfrReference,
    parse_cfr_references,
    scan_references,
)

_DOCKET_RE = re.compile(r"\bFDA-\d{4}-[A-Z]-\d{4,5}\b", re.IGNORECASE)
_GUIDANCE_RE = re.compile(r"\bguidance\b|\bguidances\b|\bdraft guidance\b", re.IGNORECASE)


class QueryType(str, Enum):
    EMPTY = "EMPTY"
    EXACT_CFR = "EXACT_CFR"
    GUIDANCE_SEARCH = "GUIDANCE_SEARCH"
    GENERAL_REGULATORY_SEARCH = "GENERAL_REGULATORY_SEARCH"


@dataclass(frozen=True)
class QueryClassification:
    query_type: QueryType
    cfr: CfrReference | None = None      # the first reference in text order (compatibility)
    docket: str | None = None
    references: tuple[CfrReference, ...] = ()  # every reference, ranges expanded, in order


def parse_cfr_reference(text: str) -> CfrReference | None:
    """Return the first CFR reference found in the text (in text order), or None.

    Kept for callers that need a single identifier; use parse_cfr_references()
    or classify().references to see every reference the text names.
    """
    refs = parse_cfr_references(text)
    return refs[0] if refs else None


def parse_docket(text: str) -> str | None:
    m = _DOCKET_RE.search(text or "")
    return m.group(0).upper() if m else None


def classify(query: str) -> QueryClassification:
    if query is None or not query.strip():
        return QueryClassification(QueryType.EMPTY)
    refs = parse_cfr_references(query)
    docket = parse_docket(query)
    if refs:
        return QueryClassification(QueryType.EXACT_CFR, cfr=refs[0], docket=docket, references=refs)
    if docket is not None or _GUIDANCE_RE.search(query):
        return QueryClassification(QueryType.GUIDANCE_SEARCH, docket=docket)
    return QueryClassification(QueryType.GENERAL_REGULATORY_SEARCH)


# ---------------------------------------------------------------- Stage 7
# Term selection for the controlled OR fallback. Deterministic, dependency-free.
# Dropped: question/instruction words, common English function words (PostgreSQL's
# english config would drop most of these anyway, but OR-ing them is pointless),
# and a short list of regulatory words so common in this corpus that OR-ing them
# returns thousands of unrelated paragraphs. Kept: identifiers (820.10, 510(k)),
# quoted phrases, and up to `max_terms` remaining words, longest first (length is
# a cheap, stable proxy for rarity), ties broken by position in the query.
_QUESTION_WORDS = {
    "what", "which", "who", "whom", "whose", "how", "why", "when", "where", "does", "do", "did", "is", "are",
    "was", "were", "be", "been", "being", "can", "could", "should", "would", "will", "may", "might", "shall",
    "explain", "describe", "compare", "define", "summarize", "summarise", "summary", "tell", "give", "list",
    "difference", "differences", "between", "simple", "simply", "plain", "language", "terms", "term", "someone",
    "background", "general", "generally", "example", "examples", "mean", "means", "meaning", "matter", "matters",
    "please", "need", "needs", "needed", "want", "wants", "apply", "applies", "applicable", "consider",
    "considerations", "context", "role", "purpose", "main", "key", "specific", "specifically", "exact", "exactly",
    "cover", "covers", "say", "says", "about", "regarding", "according",
}
_FUNCTION_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "of", "to", "in", "on", "at", "by", "for", "with",
    "from", "into", "onto", "as", "it", "its", "this", "that", "these", "those", "there", "their", "they", "them",
    "he", "she", "his", "her", "we", "our", "you", "your", "i", "me", "my", "not", "no", "yes", "all", "any", "some",
    "each", "every", "both", "such", "so", "too", "very", "also", "just", "only", "own", "same", "other", "another",
    "more", "most", "less", "least", "many", "much", "few", "several", "before", "after", "during", "while",
    "under", "over", "above", "below", "up", "down", "out", "off", "again", "further", "once", "here", "new",
    "one", "two", "three", "first", "second", "us", "u.s.", "united", "states", "s",
}
_GENERIC_REGULATORY_WORDS = {
    "cfr", "fda", "regulation", "regulations", "regulatory", "regulated", "requirement", "requirements", "required",
    "require", "requires", "rule", "rules", "law", "laws", "legal", "section", "sections", "part", "parts", "title",
    "chapter", "subpart", "federal", "code", "agency", "administration", "food", "drug", "drugs", "product",
    "products", "provision", "provisions", "must", "shall",
    # near-universal in the guidance corpus: OR-ing them returns arbitrary chunks
    "guidance", "guidances", "document", "documents", "recommendation", "recommendations", "recommend",
    "recommends", "recommended", "industry", "staff",
}
_STOP_TERMS = _QUESTION_WORDS | _FUNCTION_WORDS | _GENERIC_REGULATORY_WORDS
_PHRASE_RE = re.compile(r'"([^"]{3,80})"')
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-()]*")


def fallback_terms(query: str, max_terms: int = 8) -> list[str]:
    """Select the query terms used by the controlled OR fallback."""
    if not query or max_terms <= 0:
        return []
    phrases = [f'"{p.strip()}"' for p in _PHRASE_RE.findall(query) if p.strip()]
    stripped = _PHRASE_RE.sub(" ", query)
    seen: set[str] = set()
    words: list[tuple[int, int, str]] = []
    for pos, raw in enumerate(_TOKEN_RE.findall(stripped)):
        tok = raw.strip(".-()").lower()
        has_digit = any(c.isdigit() for c in tok)
        if has_digit and "(" in tok:
            tok = tok.split("(", 1)[0].rstrip(".-")  # "820.30(b)(1)" -> "820.30", "510(k)" -> "510"
        if not tok or tok in seen:
            continue
        if has_digit:
            if not ("." in tok or len(tok) >= 3):
                continue  # bare "21" would match everything with a 21 in it
        elif len(tok) < 3 or tok in _STOP_TERMS:
            continue
        seen.add(tok)
        words.append((-len(tok), pos, tok))
    words.sort()
    chosen = [w for _, _, w in words]
    budget = max(max_terms - len(phrases), 0)
    return phrases + chosen[:budget]


# A definitional question about ONE short term. Narrow on purpose: "What does
# FDA stand for?", "What does adulterated mean?", "What is the meaning/definition
# of X?", "Define X", "What is meant by X?". A question that names a provision,
# carries a number, or asks about more than a short term is not one of these;
# its own retrieval is unchanged.
_DEFINITION_QUESTION_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"^\s*what\s+(?:does|do)\s+(?:the\s+)?(?:term\s+|acronym\s+|abbreviation\s+)?[\"'“]?(?P<term>[^?\"'”]+?)[\"'”]?\s+(?:stand\s+for|mean)\s*\??\s*$",
    r"^\s*what\s+is\s+(?:the\s+)?(?:meaning|definition)\s+of\s+(?:the\s+)?(?:term\s+|acronym\s+|abbreviation\s+)?[\"'“]?(?P<term>[^?\"'”]+?)[\"'”]?\s*\??\s*$",
    r"^\s*define\s+(?:the\s+)?(?:term\s+)?[\"'“]?(?P<term>[^?\"'”]+?)[\"'”]?\s*[.?]?\s*$",
    r"^\s*what\s+is\s+meant\s+by\s+(?:the\s+)?(?:term\s+)?[\"'“]?(?P<term>[^?\"'”]+?)[\"'”]?\s*\??\s*$",
))
_DEFINITION_TERM_RE = re.compile(r"^[A-Za-z][A-Za-z&/\-]*(?:\s+[A-Za-z][A-Za-z&/\-]*){0,4}$")
_DEFINITION_TERM_STOP = frozenset({"it", "this", "that", "these", "those", "they", "he", "she", "you", "we", "i"})


def definition_term(question: str) -> str | None:
    """The term a definitional question asks about, or None."""
    for pattern in _DEFINITION_QUESTION_RES:
        m = pattern.match(question or "")
        if m:
            term = re.sub(r"^(?:a|an|the)\s+", "", " ".join(m.group("term").split()), flags=re.IGNORECASE)
            if _DEFINITION_TERM_RE.match(term) and term.lower() not in _DEFINITION_TERM_STOP:
                return term
    return None


def looks_like_identifier(query: str) -> bool:
    """Short queries with a dotted number ("820.3", "801.109 labeling") benefit
    from trigram matching on section numbers."""
    return bool(re.search(r"\b\d{1,4}\.\d{1,4}\b", query or ""))
