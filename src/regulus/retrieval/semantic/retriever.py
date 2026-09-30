"""SemanticRetriever: query -> local embedding -> cosine search over the
experiment corpus -> RetrievalResult objects with the same citations as the
lexical retriever.

EXPERIMENTAL. Operates only on the controlled evaluation corpus; it is not
the production retrieval layer and does not read the database at query time.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from regulus.retrieval.base import Filters, normalise_corpus
from regulus.retrieval.lexical import LexicalRetriever, SearchResponse
from regulus.retrieval.models import METHOD_SEMANTIC, RetrievalResult
from regulus.retrieval.query import QueryType, classify
from regulus.retrieval.semantic.embedder import Embedder
from regulus.retrieval.semantic.index import SemanticIndex
from regulus.retrieval.semantic.models import CorpusItem

log = logging.getLogger("regulus.retrieval.semantic")


class SemanticRetriever:
    def __init__(self, index: SemanticIndex, embedder: Embedder, corpus_name: str = "stage8") -> None:
        if embedder.config.fingerprint() != index.meta.embedding_fingerprint:
            raise ValueError("embedder configuration does not match the index it is used with")
        self.index = index
        self.embedder = embedder
        self.corpus_name = corpus_name

    def search(self, query: str, *, corpus: str | None = None, top_k: int = 10, filters: Filters | None = None, methods: Iterable[str] | None = None) -> list[RetrievalResult]:
        return self.run(query, corpus=corpus, top_k=top_k, filters=filters, methods=methods).results

    def run(self, query: str, *, corpus: str | None = None, top_k: int = 10, filters: Filters | None = None, methods: Iterable[str] | None = None) -> SearchResponse:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        corpora = normalise_corpus(corpus)
        classification = classify(query)
        if classification.query_type is QueryType.EMPTY:
            raise ValueError("query must not be empty")
        start = time.perf_counter()
        qvec = self.embedder.embed_query(query)
        embed_ms = round((time.perf_counter() - start) * 1000, 2)

        t1 = time.perf_counter()
        hits: list[tuple[CorpusItem, float]] = []
        if len(corpora) == 1:
            hits = self.index.search(qvec, top_k, corpus=corpora[0])
        else:
            hits = self.index.search(qvec, top_k)
        search_ms = round((time.perf_counter() - t1) * 1000, 2)

        results = [self._to_result(item, score) for item, score in hits]
        total_ms = round((time.perf_counter() - start) * 1000, 2)
        diagnostics = {
            "retrieval_mode": "semantic" if results else "none",
            "candidates_searched": int(sum(1 for i in self.index.items if i.corpus in corpora)),
            "top_similarity": round(results[0].relevance_score, 4) if results else None,
            "primary_result_count": len(results),
            "fallback_used": False,
            "final_result_count": len(results),
        }
        log.info("semantic query=%r results=%d embed_ms=%.1f search_ms=%.1f", query[:200], len(results), embed_ms, search_ms)
        return SearchResponse(
            query, classification.query_type, results,
            {"semantic:embed": embed_ms, "semantic:search": search_ms}, {"semantic": len(results)}, total_ms, [], diagnostics,
        )

    @staticmethod
    def _to_result(item: CorpusItem, score: float) -> RetrievalResult:
        row = dict(item.metadata)
        row["body_text"] = item.text
        extra = {"cosine_similarity": round(score, 6), "corpus_role": item.role, "experimental": True}
        if item.corpus == "ecfr":
            return LexicalRetriever._ecfr_result(row, METHOD_SEMANTIC, score, extra)
        return LexicalRetriever._guidance_result(row, METHOD_SEMANTIC, score, extra)

    def describe(self) -> dict[str, Any]:
        return {"retriever": "SemanticRetriever", "experimental": True, "scope": "controlled evaluation corpus only", "semantic_corpus": self.corpus_name, "embedder": self.embedder.describe(), "index": self.index.describe()}
