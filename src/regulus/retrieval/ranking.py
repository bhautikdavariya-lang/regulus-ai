"""Deterministic scoring, merging and ordering of lexical results.

Score components (documented in docs/lexical_retrieval.md):
    exact_cfr     100.0 for the requested section/paragraph rows,
                   95.0 for descendant paragraphs of a requested paragraph,
                   minus 0.001 * ordinal so document order is preserved on ties
    exact_docket  100.0 minus 0.001 * chunk ordinal
    structural     90.0 for the parent paragraph fetched as context (Stage 2)
    full_text     50.0 * ts_rank_cd(search_vector, websearch_to_tsquery(query), 1)
                  (normalisation 1 = divided by 1 + log(document length))
    full_text_or   5.0 * rank / number_of_OR_terms for the Stage 7 fallback. An
                  OR query over n terms inflates ts_rank_cd roughly with the number
                  of matching terms (values above 3 were measured), so the rank is
                  averaged per term and placed in the trigram band (0-5): fallback
                  evidence ranks with trigram evidence, below any primary hit
    trigram        5.0 * greatest(similarity(section_number), similarity(heading))

No component is learned and none uses vectors. Exact identifier matches
always outrank text matches (normalised full-text scores stay well below 100;
the largest observed on this corpus is about 30).

Merging: the same passage found by several methods is kept once. Its
relevance_score is the maximum, its retrieval_method is the strongest
method by priority (exact > full_text > full_text_or = trigram), and `methods` lists all.
Final order: score desc, then key asc, so output is stable across runs.
"""

from __future__ import annotations

from regulus.retrieval.models import (
    METHOD_EXACT_CFR,
    METHOD_EXACT_DOCKET,
    METHOD_FULL_TEXT,
    METHOD_FULL_TEXT_OR,
    METHOD_SEMANTIC,
    METHOD_TRIGRAM,
    RetrievalResult,
)

EXACT_SCORE = 100.0
EXACT_DESCENDANT_SCORE = 95.0
STRUCTURAL_SCORE = 90.0  # Stage 2: a parent paragraph fetched as context for a requested provision
ORDER_TIEBREAK = 0.001
FULL_TEXT_SCALE = 50.0
FULL_TEXT_OR_SCALE = 5.0
TRIGRAM_SCALE = 5.0

METHOD_PRIORITY = {
    METHOD_EXACT_CFR: 3,
    METHOD_EXACT_DOCKET: 3,
    METHOD_FULL_TEXT: 2,
    METHOD_FULL_TEXT_OR: 1,
    METHOD_TRIGRAM: 1,
    METHOD_SEMANTIC: 0,  # experimental; scores are cosine similarities, not merged with lexical scores
}


def exact_score(match_kind: str, ordinal: int) -> float:
    base = EXACT_SCORE if match_kind == "exact" else EXACT_DESCENDANT_SCORE
    return base - ORDER_TIEBREAK * int(ordinal)


def structural_score(ordinal: int) -> float:
    """Parent paragraph of a requested provision: below any exact row, above every text match."""
    return STRUCTURAL_SCORE - ORDER_TIEBREAK * ordinal


def full_text_score(rank: float) -> float:
    return FULL_TEXT_SCALE * float(rank)


def full_text_or_score(rank: float, n_terms: int = 1) -> float:
    return FULL_TEXT_OR_SCALE * float(rank) / max(1, int(n_terms))


def trigram_score(similarity: float) -> float:
    return TRIGRAM_SCALE * float(similarity)


def merge(results: list[RetrievalResult], top_k: int | None = None) -> list[RetrievalResult]:
    """De-duplicate by key, keep the strongest reason, order deterministically."""
    merged: dict[str, RetrievalResult] = {}
    for r in results:
        existing = merged.get(r.key)
        if existing is None:
            merged[r.key] = r
            continue
        methods = tuple(sorted(set(existing.methods) | set(r.methods), key=lambda m: (-METHOD_PRIORITY[m], m)))
        stronger = r if METHOD_PRIORITY[r.retrieval_method] > METHOD_PRIORITY[existing.retrieval_method] else existing
        weaker = existing if stronger is r else r
        scores = dict(existing.metadata.get("scores", {}))
        scores.update(r.metadata.get("scores", {}))
        merged[r.key] = RetrievalResult(
            corpus=stronger.corpus,
            text=stronger.text,
            heading=stronger.heading,
            relevance_score=max(existing.relevance_score, r.relevance_score),
            retrieval_method=stronger.retrieval_method,
            source_url=stronger.source_url,
            citation=stronger.citation,
            metadata={**weaker.metadata, **stronger.metadata, "scores": scores},
            methods=methods,
            key=stronger.key,
        )
    ordered = sorted(merged.values(), key=lambda r: (-r.relevance_score, r.key))
    return ordered[:top_k] if top_k is not None else ordered
