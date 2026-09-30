"""Stage 8 controlled semantic retrieval experiment.

This retriever operates only on the controlled evaluation corpus extracted
by scripts/build_semantic_corpus.py and embedded locally by
scripts/build_semantic_index.py. It is an experimental retrieval leg, not the
production retrieval layer, and it never touches the database's existing
1024-dimensional vectors.
"""

from regulus.retrieval.semantic.embedder import TransformersEmbedder, cosine_similarity, l2_normalize
from regulus.retrieval.semantic.index import IndexMismatchError, SemanticIndex, corpus_sha256
from regulus.retrieval.semantic.models import (
    CorpusItem,
    EmbeddingConfig,
    IndexMeta,
    SemanticManifest,
    SemanticPaths,
    load_corpus,
    load_manifest,
    resolve_paths,
    validate_items,
)
from regulus.retrieval.semantic.retriever import SemanticRetriever

__all__ = [
    "CorpusItem",
    "EmbeddingConfig",
    "IndexMeta",
    "IndexMismatchError",
    "SemanticIndex",
    "SemanticManifest",
    "SemanticPaths",
    "SemanticRetriever",
    "TransformersEmbedder",
    "corpus_sha256",
    "cosine_similarity",
    "l2_normalize",
    "load_corpus",
    "load_manifest",
    "resolve_paths",
    "validate_items",
]
