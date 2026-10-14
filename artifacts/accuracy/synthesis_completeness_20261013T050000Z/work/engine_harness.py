"""The PRODUCTION path with only the model's output scripted.

`serve_ui.Engine` is used as the answering UI uses it - its own retriever, configured pipeline
(validation, repair, shape checks), and evaluator call (`Engine.assess`, semantic aligner, identifier
index). The single substitution is `QwenGenerator.generate`, which returns a scripted text instead of
calling the model, so the same answer can be pushed through every post-processing step and evaluated
exactly as a live one. Nothing else is replaced.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))

_ENGINE = {}
_SCRIPT = {"text": None, "prompt": None}


def engine():
    if "e" not in _ENGINE:
        from regulus.config import load_settings
        from regulus.inference.generate import GenerationResult
        from regulus.rag import generator as G
        from serve_ui import Engine

        def scripted(self, messages, max_new_tokens=None, on_text=None):
            _SCRIPT["prompt"] = messages[-1]["content"]
            return GenerationResult(_SCRIPT["prompt"], _SCRIPT["text"], 500, 60, 1.0, finished=True)

        G.QwenGenerator.generate = scripted
        _ENGINE["e"] = Engine(load_settings(), offline=True)
    return _ENGINE["e"]


def ask(question: str, scripted_answer: str) -> dict:
    """Engine.ask with evaluation ON, the model's output replaced by `scripted_answer`."""
    _SCRIPT["text"] = scripted_answer
    return engine().ask(question, accuracy=True)


def run_pipeline(question: str, scripted_answer: str):
    """The same configured pipeline Engine.ask builds, returning the RagAnswer itself (for tracing)."""
    from dataclasses import replace
    from regulus.rag import QwenGenerator, RagPipeline
    from regulus.retrieval import LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config
    e = engine()
    _SCRIPT["text"] = scripted_answer
    config = configured_rag_config(e.settings)
    budget = config.generation_budget
    gen = replace(configured_generation_config(e.settings), max_new_tokens=budget.hard_max_tokens)
    if getattr(e, "_retrieval", None) is None:
        e._retrieval = build_retriever(e.db, config, lexical=LexicalRetriever(e.db))
    retriever, scope = e._retrieval
    model, _ = e.model_for("")
    pipe = RagPipeline(retriever, QwenGenerator(model, e.tokenizer, gen, e.settings.model.id),
                       replace(config, top_k=8, generation_budget=budget), scope_policy=scope)
    out = pipe.answer(question)
    return out, e.assess(out)
