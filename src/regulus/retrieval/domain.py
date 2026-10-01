"""General-knowledge scope policy (Stage 7): is a question outside the regulatory domain?

A question is classified GENERAL KNOWLEDGE (out of scope) only when three independent
signals agree:

  1. it names no CFR provision and no guidance docket;
  2. it contains no word of the regulatory domain vocabulary. The vocabulary is taken from
     the verified database itself (part titles, section headings, guidance titles), so it is
     neither hand-picked nor question-specific;
  3. no regulatory passage matched every term of the question (lexical retrieval had to use
     its broad OR-fallback, or found nothing).

Otherwise it is IN SCOPE (a provision or docket is named, or a passage matched), or
POTENTIALLY RELATED (domain words present but no passage matched: it proceeds to retrieval
fallback and the answerability gate as usual).

Measured before adoption over 431 questions (79 diagnostic, 300 benchmark, 52 retrieval): only
"What is the capital of France?" and "Who wrote Hamlet?" have zero domain words; every other
question without a named provision has at least one (a misspelled "informd consent requirments"
has one). Known limitation: a general-knowledge question built from words that also occur in
regulations ("the boiling point of water in Celsius": water, boiling and Celsius all appear in
food-processing provisions) is NOT caught; separating it needs topic judgment, not a rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

IN_SCOPE = "in_scope"
POTENTIALLY_RELATED = "potentially_related"
GENERAL_KNOWLEDGE = "general_knowledge"

_WORD = re.compile(r"[a-z][a-z\-]{2,}")
_STOP = frozenset(
    "a an the of and or for to in on at by with from as is are be this that these those what which who whom how when where "
    "why does do did must may can shall should will would under into about than then there their its it any all each other "
    "such not no yes if was were been being has have had our your my his her they them you we i me".split()
)

VOCABULARY_SQL = (
    "SELECT title AS t FROM cfr_parts "
    "UNION SELECT DISTINCT section_heading AS t FROM cfr_records WHERE section_heading IS NOT NULL "
    "UNION SELECT title AS t FROM fda_guidance"
)


def words(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower())) - _STOP


@dataclass(frozen=True)
class ScopeDecision:
    status: str
    reason: str
    domain_terms: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason, "domain_terms": list(self.domain_terms)}


class DomainVocabulary:
    def __init__(self, terms: Iterable[str]) -> None:
        self.terms = frozenset(terms)

    @classmethod
    def from_texts(cls, texts: Iterable[str]) -> "DomainVocabulary":
        vocab: set[str] = set()
        for t in texts:
            vocab |= words(t)
        return cls(vocab)

    @classmethod
    def from_database(cls, db) -> "DomainVocabulary":
        """Read-only: titles and headings of the verified database."""
        return cls.from_texts(r["t"] for r in db.query(VOCABULARY_SQL))

    def domain_terms(self, question: str) -> tuple[str, ...]:
        return tuple(sorted(words(question) & self.terms))


class ScopePolicy:
    def __init__(self, vocabulary: DomainVocabulary) -> None:
        self.vocabulary = vocabulary

    def decide(self, question: str, plan, lexical_diagnostics: dict | None, *, results: bool) -> ScopeDecision:
        terms = self.vocabulary.domain_terms(question)
        if plan.requirements or plan.docket is not None:
            return ScopeDecision(IN_SCOPE, "names a CFR provision or guidance docket", terms)
        matched = results and not (lexical_diagnostics or {}).get("fallback_used")
        if matched:
            return ScopeDecision(IN_SCOPE, "a regulatory passage matched every term of the question", terms)
        if terms:
            return ScopeDecision(POTENTIALLY_RELATED, "regulatory terms present, but no passage matched every term", terms)
        return ScopeDecision(GENERAL_KNOWLEDGE, "asks a general-knowledge question: it names no regulation, uses no term of the "
                             "regulatory vocabulary, and no regulatory text matches it", terms)

    def skip_semantic(self, question: str, plan, lexical_response) -> str | None:
        """For the semantic fallback: never search semantically for a general-knowledge question."""
        d = self.decide(question, plan, lexical_response.diagnostics, results=bool(lexical_response.results))
        return f"scope policy: {d.status}" if d.status == GENERAL_KNOWLEDGE else None
