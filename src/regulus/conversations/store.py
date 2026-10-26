"""SQLite persistence for chat conversations (see the package docstring for what it is not).

Design rules, each one a failure it prevents:

* The SERVER writes, never the browser: a stored answer is the result the server delivered,
  so it cannot be forged or half-written by a page.
* A user message is written when the question is received, its answer when generation ends
  (ok, error or cancelled). A process that dies in between leaves the question with no reply,
  which reads as "no answer recorded" - never as an answer.
* (conversation_id, turn_id, role) is unique. A retried send reuses its turn_id, so it can
  never store a second answer, and a delivered ("ok") answer is never overwritten.
* Messages are ordered by their own turn, not by wall-clock time: an answer always follows its
  own question, even if two questions in one conversation were in flight at once.
* One short-lived connection per operation, so the threaded HTTP server never shares one.
* A conversation can be deleted with all its messages in one transaction, with secure_delete on and the
  WAL truncated afterwards, so the deleted text does not linger in free pages or the WAL of this file.
  (Measurement records under data/ui_measurements are separate files and keep their own copy.)
* The evaluation summary reads only evaluation fields of stored answers, never the answer text
  or any draft field (regulus.conversations.evaluation_summary).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from regulus.config import PROJECT_ROOT

log = logging.getLogger("regulus.conversations")

USER = "user"
ASSISTANT = "assistant"
OK = "ok"
ERROR = "error"
CANCELLED = "cancelled"
STATUSES = (OK, ERROR, CANCELLED)

MAX_QUESTION_CHARS = 4000          # far above any real question; bounds what a request can store
MAX_TITLE_CHARS = 80
MAX_RESULT_BYTES = 8_000_000       # a stored answer with its sources and evidence is typically < 200 KB
SCHEMA_VERSION = 1
ENV_PATH = "REGULUS_CHAT_DB"
_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    id              TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id         TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error', 'cancelled')),
    content         TEXT NOT NULL,
    result_json     TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (conversation_id, turn_id, role)
);
CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages (conversation_id, seq);
CREATE INDEX IF NOT EXISTS conversations_by_activity ON conversations (updated_at);
"""


class ConversationNotFound(KeyError):
    """No conversation has this id."""


class InvalidInput(ValueError):
    """A value the store refuses to record; the message is safe to show to the user."""


def default_store_path() -> Path:
    """REGULUS_CHAT_DB if set, else data/chat/regulus_chat.sqlite3 under the project (gitignored)."""
    override = os.environ.get(ENV_PATH)
    return Path(override) if override else PROJECT_ROOT / "data" / "chat" / "regulus_chat.sqlite3"


def title_from(question: str) -> str:
    """A conversation's title: its first question, whitespace collapsed, cut at a word boundary."""
    text = " ".join((question or "").split())
    if len(text) <= MAX_TITLE_CHARS:
        return text or "New conversation"
    cut = text[: MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0] or text[: MAX_TITLE_CHARS - 1]
    return cut.rstrip(" ,;:.-") + "…"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _check_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise InvalidInput(f"{what} must be 8-64 letters, digits or hyphens")
    return value


def _check_question(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput("the question must not be empty")
    if len(value) > MAX_QUESTION_CHARS:
        raise InvalidInput(f"the question is longer than {MAX_QUESTION_CHARS} characters")
    return value.strip()


def _result_json(result: dict[str, Any] | None) -> str | None:
    """The delivered result as JSON, within MAX_RESULT_BYTES. An oversized result keeps what the
    page displays and records what was left out, rather than failing to store the answer."""
    if result is None:
        return None
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) <= MAX_RESULT_BYTES:
        return text
    slim = {k: v for k, v in result.items() if k != "evidence_snapshot"}
    slim["_stored_without"] = ["evidence_snapshot"]
    text = json.dumps(slim, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) <= MAX_RESULT_BYTES:
        return text
    keep = ("question", "answer", "citations", "accuracy", "model_called", "no_context", "notes", "grounding")
    slim = {k: result.get(k) for k in keep if k in result}
    slim["_stored_without"] = sorted(set(result) - set(keep))
    return json.dumps(slim, ensure_ascii=False, default=str)


def _message(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "conversation_id": row["conversation_id"], "turn_id": row["turn_id"],
            "role": row["role"], "status": row["status"], "content": row["content"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"]}


class ConversationStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"conversation store schema v{version} is newer than this code (v{SCHEMA_VERSION})")
            db.executescript(_SCHEMA)
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA busy_timeout = 10000")
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self, *, secure_delete: bool = False) -> Iterator[sqlite3.Connection]:
        """One write transaction, taken immediately so concurrent writers queue instead of racing.

        secure_delete: deleted content is overwritten with zeros (PRAGMA secure_delete, this connection only), and
        after the commit the WAL is checkpointed into the main file and truncated, so the old page images in it
        are gone too. A checkpoint that cannot complete (a long reader) is logged; the delete itself stands."""
        with self._connect() as db:
            if secure_delete:
                db.execute("PRAGMA secure_delete = ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
            if secure_delete:
                try:
                    busy = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if busy and busy[0]:
                        log.warning("conversation store: WAL checkpoint after a delete did not complete (busy)")
                except sqlite3.Error as exc:
                    log.warning("conversation store: WAL checkpoint after a delete failed (%s)", exc)

    # ---- conversations

    def create_conversation(self) -> dict[str, Any]:
        cid, now = uuid.uuid4().hex, _now()
        with self._transaction() as db:
            db.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, NULL, ?, ?)",
                       (cid, now, now))
        return {"id": cid, "title": None, "created_at": now, "updated_at": now, "message_count": 0}

    def list_conversations(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.seq) AS message_count "
                "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
                "GROUP BY c.id ORDER BY c.updated_at DESC, c.created_at DESC, c.id LIMIT ?",
                (max(1, min(int(limit), 1000)),)).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Delete a conversation and every message in it, in one transaction.

        Returns {"id": conversation_id, "messages_deleted": n}. Raises InvalidInput for a malformed id and
        ConversationNotFound when no conversation has it. The deleted rows are zeroed in this file
        (secure_delete, then a WAL truncate). History only: measurement records (data/ui_measurements) are
        not touched and keep their own copy of each answered turn. A turn still being answered in this
        conversation will fail to record its answer (record_answer raises InvalidInput: no question for this
        turn), which serve_ui._record_turn already reports as saved: false."""
        _check_id(conversation_id, "conversation id")
        with self._transaction(secure_delete=True) as db:
            if db.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is None:
                raise ConversationNotFound(conversation_id)
            # messages first and explicitly: correctness does not depend on ON DELETE CASCADE or the pragma
            n = db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)).rowcount
            db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        log.info("conversation %s deleted (%d messages)", conversation_id, n)
        return {"id": conversation_id, "messages_deleted": n}

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        _check_id(conversation_id, "conversation id")
        with self._connect() as db:
            conv = db.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                              (conversation_id,)).fetchone()
            if conv is None:
                raise ConversationNotFound(conversation_id)
            # each answer directly after its own question, turns in the order their questions arrived
            rows = db.execute(
                "SELECT m.* FROM messages m JOIN (SELECT turn_id, MIN(seq) AS turn_seq FROM messages "
                "WHERE conversation_id = ? GROUP BY turn_id) t ON t.turn_id = m.turn_id "
                "WHERE m.conversation_id = ? "
                "ORDER BY t.turn_seq, CASE m.role WHEN 'user' THEN 0 ELSE 1 END, m.seq",
                (conversation_id, conversation_id)).fetchall()
        return {**dict(conv), "messages": [_message(r) for r in rows]}

    # ---- messages

    def add_user_message(self, conversation_id: str, turn_id: str, question: str) -> tuple[dict[str, Any], bool]:
        """Record a question. Returns (message, created). Re-sending the same turn returns the
        stored message; reusing a turn_id for a DIFFERENT question is refused."""
        _check_id(conversation_id, "conversation id")
        _check_id(turn_id, "turn id")
        question = _check_question(question)
        now = _now()
        with self._transaction() as db:
            conv = db.execute("SELECT title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if conv is None:
                raise ConversationNotFound(conversation_id)
            existing = db.execute("SELECT * FROM messages WHERE conversation_id = ? AND turn_id = ? AND role = ?",
                                  (conversation_id, turn_id, USER)).fetchone()
            if existing is not None:
                if existing["content"] != question:
                    raise InvalidInput("this turn id was already used for a different question")
                return _message(existing), False
            db.execute("INSERT INTO messages (id, conversation_id, turn_id, role, status, content, result_json, "
                       "created_at) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                       (uuid.uuid4().hex, conversation_id, turn_id, USER, OK, question, now))
            db.execute("UPDATE conversations SET updated_at = ?, title = COALESCE(title, ?) WHERE id = ?",
                       (now, title_from(question), conversation_id))
            row = db.execute("SELECT * FROM messages WHERE conversation_id = ? AND turn_id = ? AND role = ?",
                             (conversation_id, turn_id, USER)).fetchone()
        return _message(row), True

    def answer_for(self, conversation_id: str, turn_id: str) -> dict[str, Any] | None:
        """The answer stored for a turn, whatever its status, or None."""
        _check_id(conversation_id, "conversation id")
        _check_id(turn_id, "turn id")
        with self._connect() as db:
            row = db.execute("SELECT * FROM messages WHERE conversation_id = ? AND turn_id = ? AND role = ?",
                             (conversation_id, turn_id, ASSISTANT)).fetchone()
        return _message(row) if row else None

    def record_answer(self, conversation_id: str, turn_id: str, status: str, content: str,
                      result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record how a turn ended. A failed or cancelled reply is replaced by a later attempt at the
        same turn; a delivered (ok) answer is never replaced - the stored one is returned instead."""
        _check_id(conversation_id, "conversation id")
        _check_id(turn_id, "turn id")
        if status not in STATUSES:
            raise InvalidInput(f"unknown status {status!r}")
        now, payload = _now(), _result_json(result)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM messages WHERE conversation_id = ? AND turn_id = ? AND role = ?",
                          (conversation_id, turn_id, USER)).fetchone() is None:
                raise InvalidInput("there is no question for this turn")
            existing = db.execute("SELECT * FROM messages WHERE conversation_id = ? AND turn_id = ? AND role = ?",
                                  (conversation_id, turn_id, ASSISTANT)).fetchone()
            if existing is not None and existing["status"] == OK:
                log.info("conversation %s turn %s already answered; keeping the stored answer", conversation_id, turn_id)
                return _message(existing)
            if existing is not None:
                db.execute("UPDATE messages SET status = ?, content = ?, result_json = ?, created_at = ? WHERE seq = ?",
                           (status, content or "", payload, now, existing["seq"]))
            else:
                db.execute("INSERT INTO messages (id, conversation_id, turn_id, role, status, content, result_json, "
                           "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (uuid.uuid4().hex, conversation_id, turn_id, ASSISTANT, status, content or "", payload, now))
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            row = db.execute("SELECT * FROM messages WHERE conversation_id = ? AND turn_id = ? AND role = ?",
                             (conversation_id, turn_id, ASSISTANT)).fetchone()
        return _message(row)

    # ---- evaluation summary (read-only)

    def evaluation_rows(self, limit: int = 5000) -> dict[str, Any]:
        """The evaluation fields of the most recent delivered answers, newest first, for the dashboard.

        Read-only, one connection. Only the scalars the summary reads are extracted, in SQLite (JSON1): the
        result's question; the assessment's status and rubric id; the question review's status, label,
        question, explanation, live_check_score and the two sub-states; and each dimension's dimension, state
        and label. The answer text, the draft fields, the dimensions' details, claims and evidence, and
        result_json itself never reach Python. json_valid guards every extraction, so one malformed stored
        result is counted as unreadable instead of failing the query."""
        limit = max(1, min(int(limit), 100_000))
        review = "'$.accuracy.question_review"
        # json_type() tells an object from a scalar (a JSON true would otherwise come back as the integer 1)
        dims = ("(SELECT json_group_array(json_object("
                "'dimension', CASE WHEN json_type(d.value, '$.dimension') = 'text' THEN json_extract(d.value, '$.dimension') END, "
                "'state', CASE WHEN json_type(d.value, '$.state') = 'text' THEN json_extract(d.value, '$.state') END, "
                "'label', CASE WHEN json_type(d.value, '$.label') = 'text' THEN json_extract(d.value, '$.label') END)) "
                "FROM json_each(a.j, '$.accuracy.dimensions') AS d WHERE d.type = 'object')")
        with self._connect() as db:
            rows = db.execute(
                "WITH a AS (SELECT m.seq, m.conversation_id, m.turn_id, m.created_at, "
                "m.result_json IS NOT NULL AS has_result, "
                "CASE WHEN json_valid(m.result_json) THEN m.result_json END AS j "
                "FROM messages m WHERE m.role = 'assistant' AND m.status = 'ok' "
                "ORDER BY m.created_at DESC, m.seq DESC LIMIT ?) "
                "SELECT a.conversation_id, a.turn_id, a.created_at, a.has_result, u.content AS asked, "
                "a.j IS NOT NULL AS valid, "
                "json_type(a.j, '$.accuracy') AS acc_type, "
                "json_extract(a.j, '$.question') AS result_question, "
                "json_extract(a.j, '$.accuracy.status') AS acc_status, "
                "json_extract(a.j, '$.accuracy.rubric_id') AS rubric_id, "
                f"json_type(a.j, {review}') AS rv_type, "
                f"json_extract(a.j, {review}.status') AS rv_status, "
                f"json_extract(a.j, {review}.label') AS rv_label, "
                f"json_extract(a.j, {review}.question') AS rv_question, "
                f"CASE WHEN json_type(a.j, {review}.explanation') = 'text' "
                f"THEN json_extract(a.j, {review}.explanation') END AS rv_explanation, "
                f"CASE WHEN json_type(a.j, {review}.live_check_score') IN ('integer', 'real') "
                f"THEN json_extract(a.j, {review}.live_check_score') END AS rv_score, "
                f"json_type(a.j, {review}.substantive_correctness') AS sub_type, "
                f"json_extract(a.j, {review}.substantive_correctness.state') AS sub_state, "
                f"json_type(a.j, {review}.citation_correctness') AS cite_type, "
                f"json_extract(a.j, {review}.citation_correctness.state') AS cite_state, "
                f"CASE WHEN json_type(a.j, '$.accuracy.dimensions') = 'array' THEN {dims} END AS dims_json "
                "FROM a LEFT JOIN messages u ON u.conversation_id = a.conversation_id AND u.turn_id = a.turn_id "
                "AND u.role = 'user' "
                "ORDER BY a.created_at DESC, a.seq DESC", (limit,)).fetchall()
            answered = db.execute("SELECT COUNT(*) FROM messages WHERE role = 'assistant' AND status = 'ok'").fetchone()[0]
            failed = db.execute("SELECT COUNT(*) FROM messages WHERE role = 'assistant' "
                                "AND status IN ('error', 'cancelled')").fetchone()[0]
        out = []
        for r in rows:
            acc_type = r["acc_type"]
            review_fields = None
            if r["rv_type"] == "object":
                # the fields evaluation_summary.displayed() reads, in the shape it reads them
                review_fields = {
                    "status": r["rv_status"], "label": r["rv_label"], "question": r["rv_question"],
                    "explanation": r["rv_explanation"], "live_check_score": r["rv_score"],
                    "substantive_correctness": {"state": r["sub_state"]} if r["sub_type"] == "object" else None,
                    "citation_correctness": {"state": r["cite_state"]} if r["cite_type"] == "object" else None,
                }
            out.append({
                "conversation_id": r["conversation_id"], "turn_id": r["turn_id"], "created_at": r["created_at"],
                "asked": r["asked"], "has_result": bool(r["has_result"]), "valid": bool(r["valid"]),
                "has_accuracy": acc_type is not None, "accuracy_is_object": acc_type == "object",
                "result_question": r["result_question"], "acc_status": r["acc_status"], "rubric_id": r["rubric_id"],
                "review": review_fields, "dims": _loads_or_none(r["dims_json"]),
            })
        return {"rows": out, "answered": answered, "failed": failed, "limit": limit}

    def evaluation_summary(self, recent: int = 25, limit: int = 5000) -> dict[str, Any]:
        """What the Evaluation dashboard shows about this store's answered turns (evaluation_summary.summarize)."""
        from regulus.conversations.evaluation_summary import summarize

        return summarize(self.evaluation_rows(limit=limit), recent=recent)


def _loads_or_none(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None
