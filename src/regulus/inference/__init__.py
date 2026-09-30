"""Text generation. The data types load eagerly; everything that needs torch
loads on first use, so importing a type does not import the model stack."""

from regulus.inference.types import GenerationResult, Message

_LAZY = {
    "ChatSession": "regulus.inference.chat",
    "split_thinking": "regulus.inference.chat",
    "generate": "regulus.inference.generate",
    "generate_chat": "regulus.inference.generate",
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        value = getattr(importlib.import_module(_LAZY[name]), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ChatSession",
    "GenerationResult",
    "Message",
    "generate",
    "generate_chat",
    "split_thinking",
]
