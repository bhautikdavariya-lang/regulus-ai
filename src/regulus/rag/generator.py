"""Generator protocol and the Qwen implementation built on the existing
inference code. The model is loaded once per process by the caller."""

from __future__ import annotations

from dataclasses import replace

from typing import Any, Protocol

from regulus.config import GenerationConfig, Settings
from regulus.inference.generate import GenerationResult, Message, generate_chat
from regulus.model import load_model, load_tokenizer


class Generator(Protocol):
    def generate(self, messages: list[Message]) -> GenerationResult: ...

    def describe(self) -> dict[str, Any]: ...


class QwenGenerator:
    """Wraps an already-loaded model/tokenizer; reuses regulus.inference.generate_chat."""

    def __init__(self, model, tokenizer, gen: GenerationConfig, model_id: str) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.gen = gen
        self.model_id = model_id

    def generate(self, messages: list[Message], max_new_tokens: int | None = None, on_text=None) -> GenerationResult:
        """Stage 4: the pipeline passes the per-question token budget; the
        configured max_new_tokens applies when none is given.

        `on_text`, when given, receives the text of this same generation as it
        is produced (a draft; see regulus.inference.streaming). Decoding is
        identical with or without it."""
        gen = self.gen if max_new_tokens is None else replace(self.gen, max_new_tokens=max_new_tokens)
        streamer = None
        if on_text is not None:
            from regulus.inference.streaming import TextCallbackStreamer

            streamer = TextCallbackStreamer(self.tokenizer, on_text)
        return generate_chat(self.model, self.tokenizer, messages, gen, streamer=streamer)

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_revision": getattr(self.model.config, "_commit_hash", None),
            "device": str(self.model.device),
            "dtype": str(self.model.dtype).replace("torch.", ""),
            "generation": {
                "max_new_tokens": self.gen.max_new_tokens,
                "do_sample": self.gen.do_sample,
                "temperature": self.gen.temperature if self.gen.do_sample else None,
                "top_p": self.gen.top_p if self.gen.do_sample else None,
                "top_k": self.gen.top_k if self.gen.do_sample else None,
                "enable_thinking": self.gen.enable_thinking,
            },
        }


def load_qwen_generator(settings: Settings, *, local_files_only: bool = False) -> QwenGenerator:
    """Load tokenizer + model once through the existing loaders.

    A configured adapter (`settings.model.adapter`) is merged into the base
    model here, so every caller runs the configured weights. What was loaded is
    attached as `system_identity` for whoever must record it (Stage 5).
    """
    tokenizer = load_tokenizer(settings.model, local_files_only=local_files_only)
    model = load_model(settings.model, local_files_only=local_files_only)
    adapter_info = None
    model_id = settings.model.id
    if settings.model.adapter is not None:
        from regulus.finetune import attach_saved_adapter

        model, adapter_info = attach_saved_adapter(model, settings.model.adapter, merge=True)
        model_id = f"{settings.model.id}+{adapter_info.get('adapter_name')}"
    generator = QwenGenerator(model, tokenizer, settings.generation, model_id)
    generator.system_identity = {"base_model_id": settings.model.id, "adapter": adapter_info}
    return generator
