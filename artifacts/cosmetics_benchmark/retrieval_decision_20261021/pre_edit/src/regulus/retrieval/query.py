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
from typing import Any

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


def content_terms(query: str) -> list[str]:
    """Every content word of the query, in query order: the input of the section-coverage search.

    Same stop lists as fallback_terms, but no length ranking and no cap: which words matter is
    decided by the corpus (each word's weight is its section-level inverse document frequency,
    see sql.ECFR_SECTION_COVERAGE), so a short, common head noun such as "records" is down-weighted
    instead of dropped. Identifiers are left out: a question that names one takes the exact path.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in _TOKEN_RE.findall(query or ""):
        tok = raw.strip(".-()").lower()
        if len(tok) < 3 or tok in _STOP_TERMS or tok in seen or any(c.isdigit() for c in tok):
            continue
        seen.add(tok)
        out.append(tok)
    return out


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


# A general question that asks how the regulations DEFINE or classify the things it names ("Are these 'color
# additives' in FDA's sense?", "How do FDA's definitions classify the lake?", "How do the color additive
# definitions treat 'area of the eye'?"). Measured on a client question (2026-10-19): the keyword legs found
# orthopedic-coating guidance and colour listings, never 21 CFR 70.3, the Definitions section that answers it;
# 70.3(f) opens "A color additive is ...", which the "<term> means" lookup above cannot see. The lookup below
# finds the CFR paragraphs that define terms OF THE QUESTION and keeps the best defining section. It only adds
# evidence: no other leg, term list or fallback decision changes.
_INVOKES_DEFINITION_RE = re.compile(
    r"\b(?:defin(?:e|ed|es|ition|itions)|in\s+(?:the\s+)?FDA['’]?s?\s+sense|what\s+counts\s+as)\b", re.IGNORECASE)
# a quote mark attached to a letter is an apostrophe, never a quote: "FDA's definitions treat a 'medical food'"
# quotes "medical food" only, not "s definitions treat a "
_QUOTED_TERM_RE = re.compile(r"(?<![A-Za-z])[\"'‘“]([^\"'’”]{3,60})[\"'’”](?![A-Za-z])")
_TERM_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]*")
# term boundaries: function and question words only. Generic regulatory words stay usable inside a term
# ("combination product", "food additive"), unlike in the OR fallback.
_TERM_BOUNDARY_WORDS = _QUESTION_WORDS | _FUNCTION_WORDS
QUOTED_TERM_WEIGHT = 3         # a multi-word term inside a quoted phrase: the term the question asks about
DEFINED_TERM_WEIGHT = 2        # a multi-word term of the question
QUOTED_WORD_WEIGHT = 1         # a single word, counted only inside a quoted phrase ('D&C Red lake blend')


def definitional_terms(question: str) -> dict[str, int]:
    """{term: weight} for a general question that invokes definitions; {} for any other question.

    Multi-word n-grams (2-4 words, not starting or ending on a function/question word) weigh 2, or 3 inside a
    quoted phrase (the term the question asks about: 'food contact surface' over the unquoted "human food");
    single words count (weight 1) only inside a quoted phrase, because single words are defined all over the
    CFR ("color", "process", "red"). Hyphens separate words ("food-contact" = "food contact"); the singular and
    plural of the last word are both tried ("color additives", "food-contact surfaces")."""
    if not question or not _INVOKES_DEFINITION_RE.search(question):
        return {}
    out: dict[str, int] = {}

    def add(term: str, weight: int) -> None:
        stem = term[:-1] if term.endswith("s") and not term.endswith("ss") else term
        for t in (term, stem, stem + "s" if " " in stem else None):
            if t:
                out[t] = max(out.get(t, 0), weight)

    def grams(text: str, weight: int) -> None:
        words = [w for w in (x.lower() for x in _TERM_WORD_RE.findall(text.replace("-", " ")))]
        for n in (2, 3, 4):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                if gram[0] in _TERM_BOUNDARY_WORDS or gram[-1] in _TERM_BOUNDARY_WORDS or len(gram[0]) < 3 or len(gram[-1]) < 3:
                    continue
                add(" ".join(gram), weight)

    for phrase in _QUOTED_TERM_RE.findall(question):
        for w in _TERM_WORD_RE.findall(phrase.replace("-", " ")):
            w = w.lower()
            if len(w) >= 3 and w not in _STOP_TERMS:
                add(w, QUOTED_WORD_WEIGHT)
        grams(phrase, QUOTED_TERM_WEIGHT)
    grams(question, DEFINED_TERM_WEIGHT)
    return out


def defined_term_pattern(term: str) -> str:
    """PostgreSQL regex for a paragraph that DEFINES `term` (case-insensitive, matched from the start):
    "(l) The term lake means", "(f) A color additive is", "(s) The term area of the eye means"; and, after a
    leading "The" only, a scoping sentence with a few intervening words: "(v) The terms externally applied drugs
    and externally applied cosmetics mean", "(u) The hair dye exemption in section 601(a) of the act applies to".
    After "A"/"An" or no article the verb must follow the term directly, so "A medical device data system ... is"
    does not define "medical device"."""
    t = r"[\s\-]+".join(re.escape(w) for w in term.split())
    verb = r"\s+(means|mean|is|are|includes|refers\s+to|applies\s+to)\M"
    label = r"^\s*(\([0-9A-Za-z]{1,6}\)\s*)*"
    return label + r"((the\s+terms?\s+|an?\s+)?" + t + verb + r"|the\s+(terms?\s+)?" + t + r"(\s+\S+){1,6}?" + verb + ")"


# words that say nothing about a regulated domain: kept out of the domain check below
_NOT_DOMAIN_WORDS = frozenset({"fda", "cfr", "definition", "definitions", "define", "defined", "defines", "term", "terms",
                               "sense", "counts", "count", "treat", "treats", "classify", "classifies", "regulation",
                               "regulations", "section", "part", "rule"})
SINGLE_WORD_MIN_OVERLAP = 2    # a single quoted word is accepted only with this much other question context


def question_words(question: str) -> set[str]:
    """The question's content words (singular forms, hyphens split), for the domain check of
    choose_defining_section: function/question words and words that name no domain are left out."""
    out = set()
    for w in _TERM_WORD_RE.findall((question or "").replace("-", " ")):
        w = w.lower()
        s = w[:-1] if w.endswith("s") and not w.endswith("ss") else w
        if len(w) >= 3 and w not in _TERM_BOUNDARY_WORDS and w not in _NOT_DOMAIN_WORDS:
            out.add(s)
    return out


def _title_words(title: str) -> set[str]:
    return {w[:-1] if w.endswith("s") and not w.endswith("ss") else w for w in _TERM_WORD_RE.findall((title or "").lower())}


def choose_defining_section(hits: dict[str, dict[str, Any]], weights: dict[str, int], headings: dict[str, str],
                            overlap, *, part_titles: dict[str, str] | None = None,
                            question_words: set[str] | None = None) -> tuple[str, list[str]] | None:
    """The section whose paragraphs define the question's terms best, and the terms it defines; None when none
    qualifies.

    hits: section -> {term: row}. Order: a section headed "Definitions" first (a definitional question is
    answered from the regulation's Definitions section); then the summed weight of the terms it defines (a
    defined term subsumes the shorter terms inside it: "color additive" over "color"); then how many words of
    the question, its terms included, the section's PART title shares ("Color Additives" for a color additive
    question, not "Patent Term Restoration"); then `overlap(section)`, the question's words found in the
    section; then section number.

    Accepted when the weight is >= 2 (a multi-word term), or when a single quoted word is defined in a
    Definitions section that shares at least SINGLE_WORD_MIN_OVERLAP other words with the question. Domain gate:
    the question's words that are not the chosen section's own terms say what the question is about; when some
    candidate's part title carries one of them ("dietary supplements" -> part 111) but the chosen section's part
    title carries none, nothing is chosen: a medical-gas definition does not answer a dietary-supplement
    question (measured 2026-10-20)."""
    titles = part_titles or {}
    qwords = set(question_words or ())
    all_words = qwords | {w for t in weights for w in t.split()} | {w[:-1] for t in weights for w in t.split() if w.endswith("s")}
    ranked = []
    for section, by_term in hits.items():
        kept = sorted(t for t in by_term if not any(t != u and f" {t} " in f" {u} " for u in by_term))
        is_definitions = headings.get(section, "").strip().rstrip(".").lower() in ("definitions", "definition")
        title_match = len(_title_words(titles.get(section, "")) & all_words)
        ranked.append((is_definitions, sum(weights.get(t, 0) for t in kept), title_match, section, kept))
    if not ranked:
        return None
    ranked.sort(key=lambda x: (not x[0], -x[1], -x[2], x[3]))
    best = ranked[0][:3]
    tied = [r for r in ranked if r[:3] == best]
    scores: dict[str, int] = {}
    if len(tied) > 1:
        scores = {r[3]: overlap(r[3]) for r in tied}
        tied.sort(key=lambda r: (-scores[r[3]], r[3]))
    is_definitions, weight, _, section, kept = tied[0]
    if weight < 2:
        if not is_definitions:
            return None
        if (scores[section] if section in scores else overlap(section)) < SINGLE_WORD_MIN_OVERLAP:
            return None
    own = {w for t in kept for w in t.split()} | {w[:-1] for t in kept for w in t.split() if w.endswith("s")}
    domain = qwords - own
    if domain:
        named = {s for s in hits if _title_words(titles.get(s, "")) & domain}
        if named and section not in named:
            return None
    return section, kept


# A section heading that occurs verbatim in a general question ("What must the production record review include?"
# -> 211.192 "Production record review.") names the provision the question is about. Measured 2026-10-20 on the 300
# benchmark questions: such sections were often already among the retriever's candidates but lost before the prompt
# (trigram cut-off, guidance ahead in the soft budget). Only SPECIFIC headings count: at least two words, shared by
# few sections, with at least one word that is rare among all headings ("Tobacco products.", "Performance
# standard.", "Requirements." say nothing on their own).
HEADING_MIN_WORDS = 2
HEADING_MAX_SECTIONS = 4       # a heading carried by more sections than this names no one provision
HEADING_MAX_WORD_DF = 20       # its rarest word appears in at most this many section headings


def heading_words(heading: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", (heading or "").lower()).split()


def _singular_words(words: list[str]) -> list[str]:
    return [w[:-1] if w.endswith("s") and not w.endswith("ss") else w for w in words]


def heading_in_question(heading: str, question: str) -> bool:
    """The heading, as a whole phrase of at least HEADING_MIN_WORDS words, occurs in the question (case, punctuation
    and a plural "s" ignored)."""
    h = heading_words(heading)
    if len(h) < HEADING_MIN_WORDS:
        return False
    q = heading_words(question)
    return f" {' '.join(h)} " in f" {' '.join(q)} " or \
        f" {' '.join(_singular_words(h))} " in f" {' '.join(_singular_words(q))} "


def looks_like_identifier(query: str) -> bool:
    """Short queries with a dotted number ("820.3", "801.109 labeling") benefit
    from trigram matching on section numbers."""
    return bool(re.search(r"\b\d{1,4}\.\d{1,4}\b", query or ""))
