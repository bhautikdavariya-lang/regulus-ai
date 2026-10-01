"""Plain data types shared by generation and the RAG pipeline.

Kept free of torch and transformers so that code which only needs these
names (configuration, validation, the read-only dashboard) can import them
without loading the model stack. `regulus.inference.generate` re-exports both.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GenerationResult:
    prompt: str
    response: str
    prompt_tokens: int
    generated_tokens: int
    seconds: float
    # Stage 4: True when the model emitted an end-of-turn token, False when it
    # stopped at max_new_tokens, None when unknown (older callers, fakes).
    finished: bool | None = None
    # Latency baseline instrumentation (all None when not measured, e.g. fakes):
    # chat template + tokenisation before generate(); generate() start to the
    # first new token (prefill + first step); token ids back to text afterwards.
    prepare_seconds: float | None = None
    first_token_seconds: float | None = None
    detokenize_seconds: float | None = None
    # Stage 7: why generation stopped early, when it did ("repetition": a sentence-repetition loop)
    stop_reason: str | None = None

    @property
    def tokens_per_second(self) -> float:
        return self.generated_tokens / self.seconds if self.seconds else 0.0

    @property
    def decode_tokens_per_second(self) -> float | None:
        """Steady-state rate after the first token (excludes prefill)."""
        if self.first_token_seconds is None or self.generated_tokens < 2:
            return None
        rest = self.seconds - self.first_token_seconds
        return (self.generated_tokens - 1) / rest if rest > 0 else None


Message = dict[str, str]
