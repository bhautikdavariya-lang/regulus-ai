"""In-memory conversation state for an interactive chat session.

Holds the message list in the format expected by the Qwen3 chat template.
Nothing here touches the model, so it is cheap to unit test. History lives
only for the lifetime of the process.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from regulus.inference.types import Message

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def split_thinking(text: str) -> tuple[str | None, str]:
    """Separate a Qwen3 <think>...</think> block from the final answer.

    Returns (thinking, answer). thinking is None when no block is present or
    the block is empty. Both parts are stripped of surrounding whitespace.
    """
    match = _THINK_RE.search(text)
    if not match:
        return None, text.strip()
    thinking = match.group(1).strip() or None
    answer = (text[: match.start()] + text[match.end() :]).strip()
    return thinking, answer


@dataclass
class ChatSession:
    """Conversation history for one terminal session."""

    system_prompt: str | None = None
    messages: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.system_prompt and not self.messages:
            self.messages.append({"role": "system", "content": self.system_prompt})

    @property
    def turns(self) -> int:
        """Number of completed user/assistant exchanges."""
        return sum(1 for m in self.messages if m["role"] == "assistant")

    def add_user(self, content: str) -> list[Message]:
        content = content.strip()
        if not content:
            raise ValueError("user message must not be empty")
        self.messages.append({"role": "user", "content": content})
        return self.messages

    def add_assistant(self, content: str) -> None:
        # Store only the final answer; the chat template drops old <think>
        # blocks anyway, and this keeps the prompt shorter on CPU.
        _, answer = split_thinking(content)
        self.messages.append({"role": "assistant", "content": answer})

    def drop_last_user(self) -> None:
        """Remove a dangling user turn (e.g. after an interrupted generation)."""
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()

    def clear(self) -> None:
        self.messages.clear()
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})

    def transcript(self) -> list[Message]:
        """Messages excluding the system prompt, for display."""
        return [m for m in self.messages if m["role"] != "system"]
