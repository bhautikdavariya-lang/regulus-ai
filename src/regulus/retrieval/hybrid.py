"""Stage 9 controlled hybrid retrieval experiment.

    query ─► LexicalRetriever (Stage 7) ─► lexical candidates (top-N)
          ─► SemanticRetriever (Stage 8) ─► semantic candidates (top-N, similarity floor)
          ─► authority rules ─► de-duplicate by key ─► fusion ─► top-K

Strategies (HybridConfig.strategy):
  "fallback"  A: lexical results as they are; semantic candidates are appended
                 only when lexical primary coverage is weak
                 (primary_result_count < primary_min_results).
  "rrf"       B: reciprocal-rank fusion of both candidate lists,
                 score = sum(1 / (rrf_k + rank)) over the legs that returned the
                 item. No authority rule: this is the control that shows what
                 naive fusion does to identifiers.
  "authority" C: exact lexical hits (exact_cfr / exact_docket) are pinned first
                 in lexical order; the remaining lexical and semantic candidates
                 are fused with RRF behind them.

Rules that hold for every strategy:
  * Lexical scores and cosine similarities are never added together.
  * De-duplication is by the stable natural key; the lexical entry keeps its
    method, citation and text, and the semantic evidence is recorded in
    metadata["hybrid"].
  * If the query names an identifier that lexical resolution could not find
    (the retriever's "No live record" note), semantic candidates are kept only
    as contextual material: metadata["contextual_only"] = True and the note is
    propagated. Semantic similarity never creates a citation for the requested
    identifier and never counts as evidence that it exists.
This layer is experimental and depends on the Stage 8 controlled corpus.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Iterable

from regulus.retrieval.base import Filters
from regulus.retrieval.lexical import LexicalRetriever, SearchResponse
from regulus.retrieval.models import METHOD_EXACT_CFR, METHOD_EXACT_DOCKET, METHOD_SEMANTIC, RetrievalResult
from regulus.retrieval.query import QueryType, classify
from regulus.retrieval.semantic.retriever import SemanticRetriever

log = logging.getLogger("regulus.retrieval.hybrid")

STRATEGIES = ("fallback", "rrf", "authority")
EXACT_METHODS = (METHOD_EXACT_CFR, METHOD_EXACT_DOCKET)


@dataclass(frozen=True)
class HybridConfig:
    strategy: str = "authority"
    lexical_top_n: int = 10
    semantic_top_n: int = 10
    semantic_floor: float | None = None  # cosine similarity below which semantic candidates are dropped
    rrf_k: int = 60
    primary_min_results: int = 3  # strategy "fallback": semantic added only below this lexical primary count

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {STRATEGIES}")
        if self.lexical_top_n <= 0 or self.semantic_top_n <= 0:
            raise ValueError("lexical_top_n and semantic_top_n must be positive")
        if self.semantic_floor is not None and not (0.0 <= self.semantic_floor <= 1.0):
            raise ValueError("semantic_floor must be between 0 and 1, or None")
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        if self.primary_min_results < 0:
            raise ValueError("primary_min_results must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "lexical_top_n": self.lexical_top_n,
            "semantic_top_n": self.semantic_top_n,
            "semantic_floor": self.semantic_floor,
            "fusion_method": "rrf" if self.strategy in ("rrf", "authority") else "append",
            "rrf_k": self.rrf_k,
            "primary_min_results": self.primary_min_results,
        }


def rrf_score(ranks: Iterable[int | None], k: int) -> float:
    return float(sum(1.0 / (k + r) for r in ranks if r is not None))


class HybridRetriever:
    def __init__(self, lexical: LexicalRetriever, semantic: SemanticRetriever, config: HybridConfig | None = None) -> None:
        self.lexical = lexical
        self.semantic = semantic
        self.config = config or HybridConfig()

    # -- public API ----------------------------------------------------------

    def search(self, query: str, *, corpus: str | None = None, top_k: int = 10, filters: Filters | None = None, methods: Iterable[str] | None = None) -> list[RetrievalResult]:
        return self.run(query, corpus=corpus, top_k=top_k, filters=filters, methods=methods).results

    def run(self, query: str, *, corpus: str | None = None, top_k: int = 10, filters: Filters | None = None, methods: Iterable[str] | None = None) -> SearchResponse:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        cfg = self.config
        classification = classify(query)
        if classification.query_type is QueryType.EMPTY:
            raise ValueError("query must not be empty")
        start = time.perf_counter()

        lex = self.lexical.run(query, corpus=corpus, top_k=cfg.lexical_top_n, filters=filters, methods=methods)
        lexical_ms = round((time.perf_counter() - start) * 1000, 2)
        t1 = time.perf_counter()
        sem = self.semantic.run(query, corpus=corpus, top_k=cfg.semantic_top_n)
        semantic_ms = round((time.perf_counter() - t1) * 1000, 2)

        t2 = time.perf_counter()
        accepted = [r for r in sem.results if cfg.semantic_floor is None or r.relevance_score >= cfg.semantic_floor]
        exact_detected = classification.cfr is not None or classification.docket is not None
        exact_present = any(r.retrieval_method in EXACT_METHODS for r in lex.results)
        identifier_not_found = exact_detected and not exact_present
        notes = list(lex.notes)
        if identifier_not_found:
            accepted = [self._contextual(r) for r in accepted]
            # The lexical layer notes a missing CFR reference itself; a missing
            # docket has no lexical note, so state it here. General rule, no
            # special-casing of particular questions.
            if classification.docket is not None and not any(classification.docket in n for n in notes):
                notes.append(
                    f"No guidance document with docket {classification.docket} was found in this snapshot; "
                    "any retrieved passages are related material only and do not show that the docket exists."
                )

        lex_keys = {r.key for r in lex.results}
        semantic_used = False
        if cfg.strategy == "fallback":
            weak = int(lex.diagnostics.get("primary_result_count", 0)) < cfg.primary_min_results
            if weak:
                fused = list(lex.results) + [self._tag(r, semantic_rank=i, lexical_rank=None) for i, r in enumerate(accepted, start=1) if r.key not in lex_keys]
                semantic_used = True
            else:
                fused = list(lex.results)
            final = fused[:top_k]
        elif cfg.strategy == "rrf":
            final = self._fuse(lex.results, accepted, cfg.rrf_k)[:top_k]
        else:  # authority
            pinned = [r for r in lex.results if r.retrieval_method in EXACT_METHODS]
            pinned_keys = {r.key for r in pinned}
            rest = self._fuse([r for r in lex.results if r.key not in pinned_keys], [r for r in accepted if r.key not in pinned_keys], cfg.rrf_k)
            final = (pinned + rest)[:top_k]
        fusion_ms = round((time.perf_counter() - t2) * 1000, 2)

        semantic_in_final = sum(1 for r in final if METHOD_SEMANTIC in r.methods)
        semantic_only_in_final = sum(1 for r in final if r.retrieval_method == METHOD_SEMANTIC)
        lexical_in_final = sum(1 for r in final if r.retrieval_method != METHOD_SEMANTIC)
        if not final:
            mode = "none"
        elif exact_present:
            mode = "exact"
        elif lexical_in_final and semantic_only_in_final:
            mode = "hybrid"
        elif semantic_only_in_final:
            mode = "semantic"
        else:
            mode = "lexical"
        dedup_count = len(lex_keys | {r.key for r in accepted})
        diagnostics = {
            "retrieval_strategy": cfg.strategy,
            "fusion_method": cfg.to_dict()["fusion_method"],
            "rrf_k": cfg.rrf_k,
            "lexical_candidate_count": len(lex.results),
            "semantic_candidate_count": len(sem.results),
            "semantic_floor": cfg.semantic_floor,
            "semantic_candidates_accepted": len(accepted),
            "semantic_candidates_removed": len(sem.results) - len(accepted),
            "deduplicated_candidate_count": dedup_count,
            "final_result_count": len(final),
            "semantic_in_final": semantic_in_final,
            "semantic_only_in_final": semantic_only_in_final,
            "semantic_used": bool(semantic_in_final) or (cfg.strategy == "fallback" and semantic_used and semantic_only_in_final > 0),
            "exact_identifier_detected": exact_detected,
            "exact_match_present": exact_present,
            "identifier_not_found": identifier_not_found,
            "retrieval_mode": mode,
            # kept for the retrieval-evaluation summary and compare script
            "primary_result_count": lex.diagnostics.get("primary_result_count"),
            "fallback_used": lex.diagnostics.get("fallback_used"),
            "fallback_terms": lex.diagnostics.get("fallback_terms"),
            "lexical": dict(lex.diagnostics),
            "semantic_top_similarity": sem.diagnostics.get("top_similarity"),
        }
        timings = {
            "lexical": lexical_ms,
            "semantic:embed": sem.timings_ms.get("semantic:embed", 0.0),
            "semantic:search": sem.timings_ms.get("semantic:search", 0.0),
            "semantic": semantic_ms,
            "fusion": fusion_ms,
            **{f"lexical:{k}": v for k, v in lex.timings_ms.items()},
        }
        counts = {**{f"lexical:{k}": v for k, v in lex.counts.items()}, "semantic": len(sem.results), "semantic_accepted": len(accepted)}
        total_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info("hybrid strategy=%s query=%r mode=%s final=%d semantic_in_final=%d total_ms=%.1f", cfg.strategy, query[:120], mode, len(final), semantic_in_final, total_ms)
        return SearchResponse(query, classification.query_type, final, timings, counts, total_ms, notes, diagnostics)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _contextual(r: RetrievalResult) -> RetrievalResult:
        return replace(r, metadata={**r.metadata, "contextual_only": True, "existence_evidence": False})

    @staticmethod
    def _tag(r: RetrievalResult, *, lexical_rank: int | None, semantic_rank: int | None, fusion: float | None = None) -> RetrievalResult:
        hybrid = {"lexical_rank": lexical_rank, "semantic_rank": semantic_rank}
        if fusion is not None:
            hybrid["fusion_score"] = round(fusion, 6)
        return replace(r, metadata={**r.metadata, "hybrid": hybrid})

    def _fuse(self, lexical: list[RetrievalResult], semantic: list[RetrievalResult], k: int) -> list[RetrievalResult]:
        """RRF over two ranked lists; the lexical entry is the base for duplicates."""
        entries: dict[str, dict[str, Any]] = {}
        for rank, r in enumerate(lexical, start=1):
            entries[r.key] = {"base": r, "lex": rank, "sem": None, "sem_result": None}
        for rank, r in enumerate(semantic, start=1):
            e = entries.get(r.key)
            if e is None:
                entries[r.key] = {"base": r, "lex": None, "sem": rank, "sem_result": r}
            elif e["sem"] is None:
                e["sem"] = rank
                e["sem_result"] = r
        fused: list[RetrievalResult] = []
        for key, e in entries.items():
            base: RetrievalResult = e["base"]
            score = rrf_score((e["lex"], e["sem"]), k)
            methods = tuple(base.methods)
            scores = dict(base.metadata.get("scores", {}))
            meta = dict(base.metadata)
            if e["sem_result"] is not None and e["sem_result"] is not base:
                sem_r = e["sem_result"]
                methods = tuple(dict.fromkeys(list(base.methods) + [METHOD_SEMANTIC]))
                scores.update(sem_r.metadata.get("scores", {}))
                meta["cosine_similarity"] = sem_r.metadata.get("cosine_similarity")
            meta["scores"] = scores
            fused.append(replace(self._tag(replace(base, metadata=meta, methods=methods), lexical_rank=e["lex"], semantic_rank=e["sem"], fusion=score), relevance_score=score))
        fused.sort(key=lambda r: (-r.relevance_score, r.key))
        return fused

    def describe(self) -> dict[str, Any]:
        return {"retriever": "HybridRetriever", "experimental": True, "config": self.config.to_dict(), "lexical": self.lexical.describe(), "semantic": self.semantic.describe()}
