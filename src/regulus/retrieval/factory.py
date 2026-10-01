"""One place that builds the answering pipeline's retriever and scope policy from configuration (Stage 7).

    retriever, scope = build_retriever(db, rag_config)
    pipeline = RagPipeline(retriever, generator, rag_config, scope_policy=scope)

semantic_fallback="on" wraps the lexical retriever in SemanticFallbackRetriever; the semantic index
(data/evaluation/semantic/<corpus>/generated/, built by scripts/build_semantic_corpus.py and
scripts/build_semantic_index.py) is loaded on first use. If it is missing or does not match its
manifest, the fallback reports it as unavailable and answering continues with lexical evidence.
"""

from __future__ import annotations

from regulus.retrieval.domain import DomainVocabulary, ScopePolicy
from regulus.retrieval.fallback import FallbackConfig, SemanticFallbackRetriever
from regulus.retrieval.lexical import LexicalRetriever

SEMANTIC_CORPUS = "semantic_expanded_v1"


def build_retriever(db, config, *, offline: bool = True, semantic_corpus: str = SEMANTIC_CORPUS, lexical: LexicalRetriever | None = None):
    lexical = lexical or LexicalRetriever(db)
    scope = ScopePolicy(DomainVocabulary.from_database(db)) if config.scope_policy == "general_knowledge" else None
    if config.semantic_fallback != "on":
        return lexical, scope

    def load():
        from regulus.retrieval.semantic.loaders import load_semantic_retriever
        return load_semantic_retriever(offline=offline, semantic_corpus=semantic_corpus)

    return SemanticFallbackRetriever(lexical, load, FallbackConfig(), skip_semantic=scope.skip_semantic if scope else None), scope
