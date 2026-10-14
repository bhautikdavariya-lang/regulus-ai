"""Persistent chat conversations for the answering UI.

Stored in a local SQLite file, never in the regulatory PostgreSQL corpus, which stays
read-only. A conversation is a record of what was asked and what was answered; it is
NOT evidence. Nothing here is passed to retrieval or to the model.

Access boundary: the store has no notion of users. The UI server binds to loopback and
has no authentication, so every conversation is visible to anyone who can reach that
server. Conversations are kept apart from each other, not from other people.
"""

from regulus.conversations.store import (
    ASSISTANT,
    CANCELLED,
    ERROR,
    MAX_QUESTION_CHARS,
    OK,
    USER,
    ConversationNotFound,
    ConversationStore,
    InvalidInput,
    default_store_path,
    title_from,
)

__all__ = [
    "ASSISTANT",
    "CANCELLED",
    "ERROR",
    "MAX_QUESTION_CHARS",
    "OK",
    "USER",
    "ConversationNotFound",
    "ConversationStore",
    "InvalidInput",
    "default_store_path",
    "title_from",
]
