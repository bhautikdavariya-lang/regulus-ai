"""Stop a generation that has entered a sentence-repetition loop, and keep what came before it.

Validation already rejects degenerate output (`rag.validation._degenerate`): a sentence repeated
three or more times, or mostly repeated 4-grams. The repeated-sentence test is MONOTONIC: once a
sentence has occurred three times, no continuation can make the text pass it, so stopping there
never changes the validation outcome of the full text.

Sentences are compared NORMALISED (citation markers such as "[7]" or "SOURCE 7", case, whitespace
and trailing punctuation removed): a model that repeats one sentence with an incrementing citation
number ("... technology. [5] ... technology. [6] ...") is repeating the same sentence. Stage 7
compared sentences verbatim and missed exactly that loop (21 CFR 830.20: 1,216 tokens, 173 s).

`trim_repetition(text)` keeps the answer up to and including the FIRST occurrence of the repeated
sentence and discards the loop, so a valid prefix can still be validated and shown.
"""

from __future__ import annotations

import torch
from transformers import StoppingCriteria

from regulus.inference.repetition_text import (  # noqa: F401  (re-exported for callers)
    MIN_SENTENCE_CHARS,
    SENTENCE_REPEATS,
    normalise_sentence,
    repeated_sentence,
    trim_repetition,
)

CHECK_EVERY = 16            # decode and check every N new tokens


class RepetitionStop(StoppingCriteria):
    def __init__(self, tokenizer, prompt_length: int) -> None:
        self.tokenizer = tokenizer
        self.prompt_length = prompt_length
        self.triggered: tuple[str, int] | None = None

    def __call__(self, input_ids, scores, **kwargs):
        new = input_ids.shape[1] - self.prompt_length
        done = False
        if new > 0 and new % CHECK_EVERY == 0:
            text = self.tokenizer.decode(input_ids[0][self.prompt_length:], skip_special_tokens=True)
            hit = repeated_sentence(text)
            if hit:
                self.triggered = hit
                done = True
        return torch.full((input_ids.shape[0],), done, dtype=torch.bool, device=input_ids.device)
