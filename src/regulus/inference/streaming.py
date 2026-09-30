"""Streaming the text of the single generation call, as it is produced.

`TextCallbackStreamer` is transformers' own `TextStreamer` (word-boundary
decoding, prompt skipped, special tokens skipped) with the print replaced by a
callback. It observes `model.generate()`; it does not change what is
generated, and it adds no generation call. The streamed text is a draft: the
RAG pipeline still validates (and, if needed, repairs) the complete answer
after generation, and that validated answer is what the caller must treat as
final.

If the callback raises (for example because the HTTP client has gone away),
the exception propagates out of `model.generate()` and generation stops: that
is how a disconnect cancels the work instead of finishing an answer nobody
will read.
"""

from __future__ import annotations

from typing import Callable

from transformers import TextStreamer


class TextCallbackStreamer(TextStreamer):
    def __init__(self, tokenizer, on_text: Callable[[str], None]) -> None:
        super().__init__(tokenizer, skip_prompt=True, skip_special_tokens=True)
        self.on_text = on_text
        self.chunks = 0

    def on_finalized_text(self, text: str, stream_end: bool = False) -> None:
        if text:
            self.chunks += 1
            self.on_text(text)
