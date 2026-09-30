"""Minimal lexical RAG (Stage 6): LexicalRetriever -> context -> Qwen -> answer + citations.

No SQL, no embeddings, no vectors live here. Retrieval comes in as
RetrievalResult objects; generation goes through the existing inference code.
"""

from regulus.rag.context import ContextBundle, ContextPolicy, ContextSource, build_context, render_selection
from regulus.rag.coverage import CoverageReport, RequirementCoverage, check_coverage
from regulus.rag.citations import RagCitation, build_answer_citations, citation_support
from regulus.rag.generation import GenerationBudget, GenerationPackage, build_grounded_messages, build_package, extractive_answer
from regulus.rag.pipeline import RagAnswer, RagConfig, RagGenerationResult, RagPipeline
from regulus.rag.validation import ValidationReport, validate_answer
from regulus.rag.prompt import NO_CONTEXT_ANSWER, RAG_SYSTEM_PROMPT, build_messages
from regulus.rag.selection import SelectedEvidence, Selection, select_evidence

# The generator needs torch and the model loaders, so it is imported on first
# use: configuration, planning and validation stay importable without them.
_LAZY = {"Generator", "QwenGenerator", "load_qwen_generator"}


def __getattr__(name: str):
    if name in _LAZY:
        from regulus.rag import generator

        value = getattr(generator, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ContextBundle",
    "ContextPolicy",
    "ContextSource",
    "CoverageReport",
    "GenerationBudget",
    "GenerationPackage",
    "Generator",
    "NO_CONTEXT_ANSWER",
    "QwenGenerator",
    "RAG_SYSTEM_PROMPT",
    "RagAnswer",
    "RagCitation",
    "RagConfig",
    "RagGenerationResult",
    "RagPipeline",
    "RequirementCoverage",
    "SelectedEvidence",
    "ValidationReport",
    "Selection",
    "build_context",
    "build_answer_citations",
    "build_grounded_messages",
    "build_messages",
    "build_package",
    "citation_support",
    "check_coverage",
    "extractive_answer",
    "load_qwen_generator",
    "render_selection",
    "select_evidence",
    "validate_answer",
]
