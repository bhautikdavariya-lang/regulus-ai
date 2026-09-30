"""Convenience loaders for the experimental semantic and hybrid retrievers.
Used by the CLI and evaluation scripts so the setup is not duplicated."""

from __future__ import annotations

from regulus.config import load_settings
from regulus.retrieval.semantic.embedder import TransformersEmbedder
from regulus.retrieval.semantic.index import SemanticIndex
from regulus.retrieval.semantic.models import load_manifest, resolve_paths
from regulus.retrieval.semantic.retriever import SemanticRetriever


def load_semantic_retriever(*, offline: bool = False, semantic_corpus: str | None = None) -> SemanticRetriever:
    """semantic_corpus: None/'stage8' = the Stage 8 corpus; a name selects
    data/evaluation/semantic/<name>/ (e.g. 'semantic_expanded_v1')."""
    paths = resolve_paths(semantic_corpus)
    cfg = load_manifest(paths.manifest).embedding
    index = SemanticIndex.load_paths(cfg, paths)
    embedder = TransformersEmbedder(cfg, cache_dir=str(load_settings().model.cache_dir), local_files_only=offline)
    return SemanticRetriever(index, embedder, corpus_name=paths.name)


def load_hybrid_retriever(lexical, *, strategy: str = "authority", semantic_floor: float | None = None, rrf_k: int = 60, lexical_top_n: int = 10, semantic_top_n: int = 10, offline: bool = False, semantic_corpus: str | None = None):
    from regulus.retrieval.hybrid import HybridConfig, HybridRetriever

    config = HybridConfig(strategy=strategy, semantic_floor=semantic_floor, rrf_k=rrf_k, lexical_top_n=lexical_top_n, semantic_top_n=semantic_top_n)
    return HybridRetriever(lexical, load_semantic_retriever(offline=offline, semantic_corpus=semantic_corpus), config)
