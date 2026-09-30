"""Single-turn text generation using the Qwen3 chat template."""

from __future__ import annotations

import time

import torch
from transformers import PreTrainedModel, PreTrainedTokenizerBase

from regulus.config import GenerationConfig
# Defined in a torch-free module so the pipeline's configuration and types can
# be imported without the model stack; re-exported here for existing callers.
from regulus.inference.types import GenerationResult, Message


def generate(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizerBase,
    prompt: str,
    gen: GenerationConfig,
    system_prompt: str | None = None,
) -> GenerationResult:
    """Single-turn convenience wrapper around generate_chat()."""
    messages: list[Message] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return generate_chat(model, tokenizer, messages, gen)


class _FirstTokenTimer:
    """A transformers streamer that only records when the first new token
    arrives, forwarding everything to an optional caller streamer. generate()
    first calls put() with the prompt ids, then once per generated token; it
    does not change what is generated. Exact on CPU/CUDA; on MPS transformers
    streams one step behind (DeferredStopCheck), so it would read one decode
    step late there."""

    def __init__(self, inner=None) -> None:
        self.inner = inner
        self.calls = 0
        self.first_token_at: float | None = None

    def put(self, value) -> None:
        self.calls += 1
        if self.calls == 2 and self.first_token_at is None:
            self.first_token_at = time.perf_counter()
        if self.inner is not None:
            self.inner.put(value)

    def end(self) -> None:
        if self.inner is not None:
            self.inner.end()


@torch.inference_mode()
def generate_chat(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizerBase,
    messages: list[Message],
    gen: GenerationConfig,
    streamer=None,
) -> GenerationResult:
    """Generate the next assistant turn for a list of chat messages.

    `messages` follows the standard {"role": ..., "content": ...} format and
    is rendered with the model's own chat template. Pass a transformers
    streamer (e.g. TextStreamer) to print tokens as they are produced.
    """
    if not messages or messages[-1]["role"] != "user":
        raise ValueError("messages must end with a user turn")

    t_prepare = time.perf_counter()
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=gen.enable_thinking,
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    sampling = {}
    if gen.do_sample:
        sampling = {"temperature": gen.temperature, "top_p": gen.top_p, "top_k": gen.top_k}
    # Stage 4: optional repetition controls, off unless configured
    if getattr(gen, "repetition_penalty", 1.0) and gen.repetition_penalty != 1.0:
        sampling["repetition_penalty"] = gen.repetition_penalty
    if getattr(gen, "no_repeat_ngram_size", 0):
        sampling["no_repeat_ngram_size"] = gen.no_repeat_ngram_size

    timer = _FirstTokenTimer(streamer)
    start = time.perf_counter()
    prepare_seconds = start - t_prepare
    output_ids = model.generate(
        **inputs,
        max_new_tokens=gen.max_new_tokens,
        do_sample=gen.do_sample,
        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        streamer=timer,
        **sampling,
    )
    elapsed = time.perf_counter() - start

    t_detok = time.perf_counter()
    prompt_len = inputs["input_ids"].shape[1]
    new_ids = output_ids[0][prompt_len:]
    response = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    detokenize_seconds = time.perf_counter() - t_detok

    return GenerationResult(
        prompt=messages[-1]["content"],
        response=response,
        prompt_tokens=prompt_len,
        generated_tokens=int(new_ids.shape[0]),
        seconds=elapsed,
        finished=_finished(model, tokenizer, new_ids),
        prepare_seconds=prepare_seconds,
        first_token_seconds=(timer.first_token_at - start) if timer.first_token_at is not None else None,
        detokenize_seconds=detokenize_seconds,
    )


def _finished(model, tokenizer, new_ids) -> bool | None:
    """Did generation end with an end-of-turn token (True) or at the cap (False)?"""
    if new_ids.shape[0] == 0:
        return None
    eos: set[int] = set()
    cfg = getattr(getattr(model, "generation_config", None), "eos_token_id", None)
    if isinstance(cfg, int):
        eos.add(cfg)
    elif isinstance(cfg, (list, tuple)):
        eos.update(int(i) for i in cfg)
    if tokenizer.eos_token_id is not None:
        eos.add(int(tokenizer.eos_token_id))
    if not eos:
        return None
    return int(new_ids[-1]) in eos
