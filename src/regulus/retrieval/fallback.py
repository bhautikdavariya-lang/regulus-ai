"""Semantic retrieval as a FALLBACK for insufficient lexical evidence (Stage 7).

    lexical run_plan ─► sufficient? ── yes ─► the lexical result, unchanged
                             │
                             no
                             ▼
                   semantic search (floor, top-n) ─► merged into the SAME registry ─► pipeline

Lexical retrieval stays the primary layer. Semantic search runs only when a
general rule says the lexical evidence cannot answer the question:

  * no_passage_matched   (opt-in, `FallbackConfig.general_questions`) a question with no requested provision or docket, where no
                         passage matched every term of the question (lexical had to
                         use its OR-fallback);
  * reference_target_only a citation lookup whose only named provisions are the ones
                         being referred to ("... meeting part 803 criteria"): lexical
                         fetches that provision by identity, which cannot show which
                         provision refers to it;
  * no_results           lexical returned nothing for a question that names no provision or docket.

It never runs for a question the scope policy marks as general knowledge.

Resolution policy when both layers return candidates (never a score sum, never a
silent choice; recorded in `diagnostics["semantic_fallback"]`):

  1. evidence identified by citation (exact / structural) keeps its place, always first;
  2. lexical passages that matched every question term (full-text) come next;
  3. semantic candidates above the similarity floor come next;
  4. lexical broad-search candidates (OR-fallback, trigram) come last: they are what
     triggered the fallback.
  A passage found by both layers keeps its lexical entry; the semantic rank is recorded.
  For a reference_target_only question, a semantic candidate counts only if its text
  mentions the referenced provision (otherwise it cannot be the referring provision).

The semantic index covers part of the database (see its manifest); an unavailable or
mismatched index is reported and the result is the lexical one.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from regulus.retrieval.evidence import (
    TIER_EXACT,
    TIER_STRUCTURAL,
    Evidence,
    EvidenceRegistry,
    classify_result,
)
from regulus.retrieval.lexical import DISCOVERY_METHODS, LexicalRetriever, PlanRetrieval, SearchResponse
from regulus.retrieval.models import METHOD_FULL_TEXT, RetrievalResult

REASON_NO_PASSAGE = "no_passage_matched"
REASON_REFERENCE_ONLY = "reference_target_only"
REASON_NO_RESULTS = "no_results"


@dataclass(frozen=True)
class FallbackConfig:
    semantic_top_n: int = 8
    # Stage 10 measurement (docs/expanded_hybrid_retrieval_experiment.md): a 0.75 floor removed
    # 277 of 520 semantic candidates with no recall loss on the expanded corpus. Not re-tuned here.
    similarity_floor: float = 0.75
    # how semantic candidates meet the lexical broad-search (OR-fallback/trigram) candidates:
    # "interleave" alternates them rank by rank (neither weak signal outranks the other);
    # "semantic_first" puts all semantic candidates ahead of them. Measured in Stage 7.
    merge_policy: str = "interleave"
    # the no_passage_matched trigger (general questions whose terms no passage matched). OFF by default:
    # measured in Stage 7 on the 266 benchmark questions with draft citations, it moved the drafted
    # provision INTO the prompt for 6 questions and OUT of it for 4 (net +2), and changed nothing on
    # retrieval_v2 - not a reliable improvement. The reference-lookup and no-results triggers are on.
    general_questions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"semantic_top_n": self.semantic_top_n, "similarity_floor": self.similarity_floor, "merge_policy": self.merge_policy,
                "general_questions": self.general_questions}


def mention_pattern(label: str) -> re.Pattern[str] | None:
    """How a provision is written inside regulatory text: '21 CFR part 803' -> 'part 803';
    '21 CFR 803.50(a)' -> '803.50'. None when the label is not a CFR provision."""
    m = re.search(r"CFR\s+part\s+(\d{1,4})\b", label, re.I)
    if m:
        return re.compile(rf"\bpart\s+{m.group(1)}\b", re.I)
    m = re.search(r"CFR\s+(\d{1,4}\.\d{1,4}[a-z]?)", label, re.I)
    if m:
        return re.compile(rf"(?<![\d.]){re.escape(m.group(1))}(?![\d])", re.I)
    return None


def lexical_insufficiency(plan, response: SearchResponse, reference_targets: tuple[str, ...] = (), *,
                          general_questions: bool = False) -> str | None:
    """The reason the lexical evidence cannot answer, or None when it is sufficient. A question that names a
    provision or docket is never sent to semantic search for lack of results: a missing identifier must stay
    'not found', not be answered from similar text."""
    if reference_targets:
        return REASON_REFERENCE_ONLY  # a content search for the provision that refers to the targets
    names_identifier = bool(plan.requirements) or plan.docket is not None
    if names_identifier:
        return None
    if not response.results:
        return REASON_NO_RESULTS
    if general_questions and response.diagnostics.get("fallback_used"):
        return REASON_NO_PASSAGE
    return None


class SemanticFallbackRetriever:
    """`run_plan`-compatible wrapper: lexical first, semantic only when lexical is insufficient.

    `semantic_loader` builds the semantic retriever on first use (the embedding model is loaded
    only if a fallback is ever needed). `skip_semantic(question, plan, lexical_response)` returns a
    reason to skip (the scope policy), or None."""

    def __init__(self, lexical: LexicalRetriever, semantic_loader: Callable[[], Any], config: FallbackConfig | None = None,
                 skip_semantic: Callable[..., str | None] | None = None) -> None:
        self.lexical = lexical
        self._loader = semantic_loader
        self._semantic = None
        self._unavailable: str | None = None
        self.config = config or FallbackConfig()
        self.skip_semantic = skip_semantic

    # the pipeline and the gates use these through the lexical retriever
    def __getattr__(self, name):
        return getattr(self.lexical, name)

    def semantic(self):
        if self._semantic is None and self._unavailable is None:
            try:
                self._semantic = self._loader()
            except Exception as exc:  # a missing or mismatched index must not break answering
                self._unavailable = f"{type(exc).__name__}: {exc}"
        return self._semantic

    def describe(self) -> dict[str, Any]:
        sem = self._semantic
        return {"retriever": "LexicalRetriever+SemanticFallback", "fallback": self.config.to_dict(),
                "semantic_corpus": getattr(sem, "corpus_name", None), "semantic_unavailable": self._unavailable}

    def run(self, *args, **kwargs):
        """Query-level search is the lexical layer's (kept for existing callers)."""
        return self.lexical.run(*args, **kwargs)

    def run_plan(self, plan, *, corpus=None, top_k: int = 10, filters=None, methods=None,
                 reference_targets: tuple[str, ...] = ()) -> PlanRetrieval:
        lex = self.lexical.run_plan(plan, corpus=corpus, top_k=top_k, filters=filters, methods=methods)
        reason = lexical_insufficiency(plan, lex.response, tuple(reference_targets), general_questions=self.config.general_questions)
        record: dict[str, Any] = {"invoked": False, "lexical_insufficient": reason, "config": self.config.to_dict(),
                                  "lexical_mode": lex.response.diagnostics.get("retrieval_mode")}
        # a reference lookup named a provision: it is never general knowledge
        skipped = (self.skip_semantic(plan.question, plan, lex.response)
                   if (reason and self.skip_semantic and reason != REASON_REFERENCE_ONLY) else None)
        sem = self.semantic() if reason and not skipped else None
        if reason is None or skipped or sem is None:
            record["skipped"] = skipped or (None if reason is None else f"semantic index unavailable: {self._unavailable}")
            return _annotate(lex, record)

        t0 = time.perf_counter()
        sem_resp = sem.run(plan.question, corpus=corpus, top_k=self.config.semantic_top_n)
        patterns = [p for p in (mention_pattern(t) for t in reference_targets) if p is not None]
        candidates, rejected = [], []
        for rank, r in enumerate(sem_resp.results, start=1):
            if r.relevance_score < self.config.similarity_floor:
                rejected.append({"key": r.key, "rank": rank, "similarity": round(r.relevance_score, 4), "why": "below floor"})
            elif reason == REASON_REFERENCE_ONLY and not any(p.search(r.text or "") for p in patterns):
                rejected.append({"key": r.key, "rank": rank, "similarity": round(r.relevance_score, 4), "why": "does not mention the referenced provision"})
            else:
                candidates.append((rank, r))
        merged, overlap = _merge(lex.registry, candidates, plan, self.config.merge_policy)
        if reason == REASON_REFERENCE_ONLY:
            # a passage that does not mention the referenced provision cannot be the one that refers to it
            dropped = [e.key for e in merged if e.tier not in (TIER_EXACT, TIER_STRUCTURAL) and not any(p.search(e.text or "") for p in patterns)]
            merged = [replace(e, evidence_id=f"e{i}") for i, e in enumerate(
                [e for e in merged if e.key not in set(dropped)], start=1)]
            record["lexical_dropped_not_mentioning_target"] = dropped
        protected = [e for e in merged if e.tier in (TIER_EXACT, TIER_STRUCTURAL)]
        remainder = [e for e in merged if e.tier not in (TIER_EXACT, TIER_STRUCTURAL)]
        kept = protected + remainder[: max(0, top_k - len(protected))]
        record.update({
            "invoked": True, "semantic_ms": round((time.perf_counter() - t0) * 1000, 2),
            "semantic_corpus": getattr(sem, "corpus_name", None),
            "lexical_candidates": [{"key": e.key, "tier": e.tier, "method": e.retrieval_method} for e in lex.registry.evidence],
            "semantic_candidates": [{"key": r.key, "rank": rank, "similarity": round(r.relevance_score, 4)} for rank, r in candidates],
            "semantic_rejected": rejected, "found_by_both": overlap,
            "final_evidence": [{"key": e.key, "tier": e.tier, "method": e.retrieval_method} for e in kept],
        })
        diag = {**lex.response.diagnostics, "retrieval_mode": "semantic_fallback" if candidates else lex.response.diagnostics.get("retrieval_mode"),
                "final_result_count": len(kept), "semantic_fallback": record}
        response = replace(lex.response, results=[e.result for e in kept], diagnostics=diag,
                           counts={**lex.response.counts, "semantic": len(candidates)},
                           timings_ms={**lex.response.timings_ms, "semantic_fallback": record["semantic_ms"]})
        registry = EvidenceRegistry(plan=lex.registry.plan, evidence=tuple(merged), requirement_state=lex.registry.requirement_state,
                                    diagnostics={**lex.registry.diagnostics, "semantic_fallback": {k: record[k] for k in ("invoked", "lexical_insufficient")}})
        return PlanRetrieval(plan=lex.plan, registry=registry, response=response)


def _annotate(lex: PlanRetrieval, record: dict[str, Any]) -> PlanRetrieval:
    """The lexical result as it is, with the fallback decision recorded (evidence and order untouched)."""
    lex.response.diagnostics["semantic_fallback"] = record
    lex.registry.diagnostics["semantic_fallback"] = {"invoked": False, "lexical_insufficient": record["lexical_insufficient"]}
    return lex


def _merge(registry: EvidenceRegistry, candidates: list[tuple[int, RetrievalResult]], plan, policy: str = "interleave") -> tuple[list[Evidence], list[dict]]:
    """Authority order (module docstring). Semantic rows are classified by identity like any row, so a
    semantic hit that IS a requested provision is exact; otherwise it is supporting material."""
    lexical_keys = {e.key: e for e in registry.evidence}
    overlap, sem_evidence = [], []
    for rank, r in candidates:
        if r.key in lexical_keys:
            overlap.append({"key": r.key, "semantic_rank": rank, "lexical_tier": lexical_keys[r.key].tier})
            continue
        tier, satisfies, structural, relations = classify_result(r, plan.requirements, discovered_for=(), discovery_methods=DISCOVERY_METHODS)
        sem_evidence.append(Evidence("", r, tier, satisfies, structural, (), relations))
    identity = [e for e in registry.evidence if e.tier in (TIER_EXACT, TIER_STRUCTURAL)] + [e for e in sem_evidence if e.tier in (TIER_EXACT, TIER_STRUCTURAL)]
    lexical_primary = [e for e in registry.evidence if e.tier not in (TIER_EXACT, TIER_STRUCTURAL) and e.retrieval_method == METHOD_FULL_TEXT]
    semantic = [e for e in sem_evidence if e.tier not in (TIER_EXACT, TIER_STRUCTURAL)]
    broad = [e for e in registry.evidence if e.tier not in (TIER_EXACT, TIER_STRUCTURAL) and e.retrieval_method != METHOD_FULL_TEXT]
    if policy == "semantic_first":
        rest = semantic + broad
    else:  # interleave: lexical broad, semantic, lexical broad, ... (lexical first: it is the primary layer)
        rest = [e for pair in zip(broad, semantic) for e in pair] + broad[len(semantic):] + semantic[len(broad):]
    ordered = identity + lexical_primary + rest
    return [replace(e, evidence_id=f"e{i}") for i, e in enumerate(ordered, start=1)], overlap
