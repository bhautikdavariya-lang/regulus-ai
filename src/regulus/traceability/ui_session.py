"""Measurement records for questions answered through the UI (scripts/serve_ui.py).

One server process is one SESSION, laid out like an acceptance run so that the existing offline evaluator
reads it unchanged (regulus.evaluation.ui_sessions):

    <root>/<session_id>/session.json       regulus_ui_session_v1: identity of the session and its state
    <root>/<session_id>/measurement.jsonl  one regulus_measurement_record_v1 per answer attempt
    <root>/<session_id>/answers.jsonl      one row per record, same question_id: what the user was given

The default root is data/ui_measurements/ (git-ignored: it holds user questions, answers and evidence).
Nothing here is ever uploaded or sent anywhere; the files stay on this host until deleted.

Turns
-----
One request is one TURN with its own id (`ui-<uuid>`, so a retried conversation turn is a separate attempt)
and a per-session ordinal assigned when it is written. A turn is written exactly once, when its outcome is
known: delivered -> the full record (captured, or capture_error); failed -> pipeline_error; client gone, or
a complete answer not delivered -> cancelled. A turn the server replays from chat history is never opened.

Durability and recovery
-----------------------
Each line is written with one os.write loop and then fsync'ed, so a record the log reports as recorded has
reached the disk (subject to the disk honouring fsync). What cannot be guaranteed: a record whose write is
cut short (disk full, SIGKILL, host failure, power loss mid-write) leaves an unterminated fragment. Before
every append the file's last byte is checked; an unterminated tail is TERMINATED IN PLACE with a newline -
never truncated or rewritten - so the fragment stays in the file as its own malformed line (readers report
it with its line number) and the next record starts on a clean line. Each such recovery is logged and
counted.

The two files are written in a fixed order - the measurement record first, then its answers row - and only
both together count as recorded. A failure of the first leaves neither; a failure of the second leaves a
record without a row, which the offline evaluator reports and never scores. JSONL across two files cannot be
one transaction; this order makes every partial outcome detectable rather than silent. A failed write still
consumes its ordinal, so a gap in the ordinals marks it.

session.json is replaced atomically (temporary file in the same directory, fsync, os.replace, directory
fsync), so an interrupted update leaves the previous version, never a truncated one. state is "open" until
close() writes "closed" with the final counters; a session left "open" by a process that no longer exists
ended uncleanly (SIGKILL, crash, power loss) - its records are still valid.

Permissions
-----------
Directories this module creates are 0700 and files 0600, set at creation (os.open/mkdir mode, so there is
no window in which they are wider; the umask can only narrow them). An existing root directory is left as
it is: permissions of existing data are never changed.

Logging
-------
One structured line per event - `measurement event=<...> session=<id> question_id=<id> ...` - with ids,
statuses and a failure CATEGORY (an errno name such as ENOSPC, or an exception type). Never a question, an
answer, evidence or a raw exception message.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import socket
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from regulus.traceability import measurement as M

SESSION_SCHEMA = "regulus_ui_session_v1"
SESSION_FILE = "session.json"
ANSWERS_FILE = "answers.jsonl"
ENV_ROOT = "REGULUS_UI_MEASUREMENTS"
NOT_RUN_BY_UI = "the accuracy evaluator was switched off for this session (--no-accuracy)"

DELIVERED = "delivered"
NOT_DELIVERED = "not_delivered"
OPEN, CLOSED = "open", "closed"
DIR_MODE, FILE_MODE = 0o700, 0o600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_root(project_root: Path) -> Path:
    override = os.environ.get(ENV_ROOT)
    return Path(override) if override else project_root / "data" / "ui_measurements"


def host_fingerprint() -> str:
    """Identifies the host without naming it: a session's process can only be checked on its own host."""
    return hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()[:16]


def failure_category(exc: BaseException) -> str:
    """An errno name (ENOSPC, EROFS, EACCES ...) or the exception type: never the message."""
    code = getattr(exc, "errno", None)
    return errno.errorcode.get(code, type(exc).__name__) if isinstance(code, int) else type(exc).__name__


def code_revision(root: Path) -> dict[str, Any]:
    """The code this session runs: HEAD, whether the tree is dirty, and a hash of the tracked diff."""
    def git(*args: str) -> bytes | None:
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=30, check=True).stdout
        except Exception:  # noqa: BLE001
            return None

    commit, status, diff = git("rev-parse", "HEAD"), git("status", "--porcelain"), git("diff", "HEAD")
    return {"git_commit": commit.decode().strip() if commit else None,
            "git_dirty": bool(status.strip()) if status is not None else None,
            "tracked_diff_sha256": hashlib.sha256(diff).hexdigest() if diff is not None else None}


# ------------------------------------------------------------------ file primitives


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def fsync_dir(path: Path) -> None:
    """Make a directory entry durable where the platform supports it (not on Windows)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def append_line(path: Path, line: str) -> bool:
    """Append one JSON line durably. Returns True when an unterminated tail had to be terminated first.

    The file is created 0600. An unterminated tail (a write cut short earlier) is terminated in place, never
    truncated, so the next record cannot be joined to it."""
    created = not path.exists()
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, FILE_MODE)
    try:
        recovered = False
        size = os.fstat(fd).st_size
        if size:
            os.lseek(fd, size - 1, os.SEEK_SET)
            if os.read(fd, 1) != b"\n":
                _write_all(fd, b"\n")
                recovered = True
        _write_all(fd, line.encode("utf-8") + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    if created:
        fsync_dir(path.parent)
    return recovered


def write_json_atomic(path: Path, obj: Any) -> None:
    """Replace `path` with `obj` as JSON so that an interruption leaves the old file or the new one, whole."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        try:
            _write_all(fd, json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    fsync_dir(path.parent)


# ------------------------------------------------------------------ the session


class UISession:
    """The measurement files of one server process. Thread-safe; every public method is failure-isolated."""

    def __init__(self, root: Path, run: dict[str, Any], *, log: Callable[[str], None] = print) -> None:
        root = Path(root)
        root.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)     # an existing root is left as it is
        self.session_id = f"ui_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        self.dir = root / self.session_id
        self.dir.mkdir(mode=DIR_MODE, exist_ok=False)
        self.run = {**run, "run_id": self.session_id}
        self.started_utc = _now()
        self.log = log
        self._lock = threading.Lock()
        self._ordinal = 0
        self.written = 0
        self.failures: dict[str, int] = {}
        self.recovered_partial_lines = 0
        self.records_without_row = 0
        self.last_failure: dict[str, str] | None = None
        self.closed = False
        write_json_atomic(self.dir / SESSION_FILE, self._session_body())
        self._event("session_opened")

    # -- state ------------------------------------------------------------------

    @property
    def write_failures(self) -> int:
        return sum(self.failures.values())

    def counters(self) -> dict[str, Any]:
        return {"written": self.written, "write_failures": dict(self.failures),
                "recovered_partial_lines": self.recovered_partial_lines,
                "records_without_row": self.records_without_row, "ordinals_assigned": self._ordinal}

    def status(self) -> dict[str, Any]:
        """For /api/config: ids and counters only."""
        with self._lock:
            return {"enabled": True, "session_id": self.session_id, "state": CLOSED if self.closed else OPEN,
                    **self.counters(), "last_failure": dict(self.last_failure) if self.last_failure else None}

    def _session_body(self) -> dict[str, Any]:
        return {"schema": SESSION_SCHEMA, "session_id": self.session_id, "source": "ui",
                "state": CLOSED if self.closed else OPEN, "started_utc": self.started_utc,
                "finished_utc": _now() if self.closed else None, "pid": os.getpid(), "host": host_fingerprint(),
                # counters are final only once the session is closed; while open they are not maintained here
                "counters": self.counters() if self.closed else None, "run": self.run}

    def close(self) -> None:
        """Record the final counters and mark the session closed. Idempotent; never raises."""
        try:
            with self._lock:
                if self.closed:
                    return
                self.closed = True
                write_json_atomic(self.dir / SESSION_FILE, self._session_body())
            self._event("session_closed", **{k: v for k, v in self.counters().items() if k != "write_failures"},
                        write_failures=self.write_failures)
        except Exception as exc:  # noqa: BLE001
            self._event("session_close_failed", category=failure_category(exc))

    # -- logging and accounting -------------------------------------------------

    def _event(self, event: str, **fields: Any) -> None:
        parts = " ".join(f"{k}={v}" for k, v in fields.items())
        try:
            self.log(f"  measurement event={event} session={self.session_id}" + (f" {parts}" if parts else ""))
        except Exception:  # noqa: BLE001 - a broken log never breaks answering
            pass

    def _fail(self, stage: str, exc: BaseException, question_id: str | None) -> None:
        """Count one failure (caller holds no lock)."""
        category = failure_category(exc)
        with self._lock:
            key = f"{stage}:{category}"
            self.failures[key] = self.failures.get(key, 0) + 1
            self.last_failure = {"stage": stage, "category": category, "utc": _now()}
        self._event("write_failed", question_id=question_id, stage=stage, category=category)

    # -- turns ------------------------------------------------------------------

    def turn(self, question: str, *, endpoint: str, conversation_id: str | None = None,
             turn_id: str | None = None, request: dict[str, Any] | None = None) -> "Turn":
        return Turn(self, question, origin={"source": "ui", "endpoint": endpoint, "conversation_id": conversation_id,
                                            "turn_id": turn_id, "request": dict(request or {})})

    def _append(self, row: dict[str, Any], record: dict[str, Any]) -> None:
        """The record, then its row, each durably, under one lock. Never raises."""
        stage = "measurement"
        with self._lock:
            self._ordinal += 1
            ordinal = self._ordinal
            try:
                record = self._with_ordinal(record, ordinal)
                row["ordinal"] = ordinal
                recovered = append_line(self.dir / M.MEASUREMENT_FILE, json.dumps(record, ensure_ascii=False, sort_keys=True))
                stage = "answers"
                recovered += append_line(self.dir / ANSWERS_FILE, json.dumps(row, ensure_ascii=False, default=str))
                self.recovered_partial_lines += recovered
                self.written += 1
                ok = True
            except Exception as exc:  # noqa: BLE001 - measurement never touches the answer
                ok, failure = False, exc
                if stage == "answers":
                    self.records_without_row += 1
        if ok:
            if recovered:
                self._event("partial_line_terminated", question_id=row["question_id"], ordinal=ordinal,
                            count=recovered)
            self._event("recorded", question_id=row["question_id"], ordinal=ordinal, status=record["status"])
        else:
            self._fail(stage, failure, row.get("question_id"))

    @staticmethod
    def _with_ordinal(record: dict[str, Any], ordinal: int) -> dict[str, Any]:
        record = {k: v for k, v in record.items() if k != "record_sha256"}
        record["ordinal"] = ordinal
        record["record_sha256"] = M.record_hash(record)      # sealed again: the ordinal is covered
        return record


class Turn:
    """One UI request. `answered` stages the finished RagAnswer; `finish` writes the outcome exactly once."""

    def __init__(self, session: UISession, question: str, *, origin: dict[str, Any]) -> None:
        self.session, self.question, self.origin = session, question, origin
        self.question_id = f"ui-{uuid.uuid4().hex}"
        self._out = None
        self._evaluation = self._review = None
        self._live: dict[str, Any] | None = None
        self._model: dict[str, Any] | None = None
        self._done = False

    def use_model(self, model: dict[str, Any] | None) -> None:
        """This turn was answered by another model than the one the session started with (the page's model
        selector): its record's run.model names that model. None keeps the session's own."""
        self._model = model

    def answered(self, out: Any, *, evaluation: dict[str, Any] | None, review: dict[str, Any] | None,
                 live: dict[str, Any] | None = None) -> None:
        """Stage the delivered-to-be answer. `live` is what the live answer path knew and the record should
        keep (actual aligner, embedder, identifier lookups, grounding outcome, adapter identity)."""
        self._out, self._evaluation, self._review, self._live = out, evaluation, review, live

    def failed(self, exc: BaseException, *, cancelled: bool = False, error: str | None = None) -> None:
        status = M.STATUS_CANCELLED if cancelled else M.STATUS_PIPELINE_ERROR
        self._write_failure(status, error or type(exc).__name__)

    def finish(self, delivery: str) -> None:
        """The request is over. Delivered with a staged answer: the full record. Otherwise: no answer."""
        if self._done:
            return
        if self._out is None:
            self._write_failure(M.STATUS_PIPELINE_ERROR, "the request ended without an answer")
        elif delivery != DELIVERED:
            self._write_failure(M.STATUS_CANCELLED, "the answer was complete but was not delivered to the client")
        else:
            self._write_answer()

    # -- writing ----------------------------------------------------------------

    def _ident(self) -> dict[str, Any]:
        run = self.session.run if self._model is None else {**self.session.run, "model": self._model}
        return dict(question_id=self.question_id, ordinal=0, question=self.question, run=run,
                    captured_utc=_now())

    def _write_answer(self) -> None:
        self._done = True
        try:
            origin = {**self.origin, "delivery": DELIVERED, **({"live": self._live} if self._live is not None else {})}
            record = M.capture_safely(**self._ident(), out=self._out, evaluation=self._evaluation,
                                      review=self._review, origin=origin,
                                      not_run_reason=NOT_RUN_BY_UI if self._evaluation is None else None)
            row = {"question_id": self.question_id, "question": self.question,
                   "execution_status": "OK" if record["status"] == M.STATUS_CAPTURED else "CAPTURE_ERROR",
                   "answer": self._out.answer, "model_called": self._out.model_called,
                   "conversation_id": origin["conversation_id"], "turn_id": origin["turn_id"],
                   "endpoint": origin["endpoint"], "captured_utc": record["captured_utc"],
                   "error": record.get("error")}
        except Exception as exc:  # noqa: BLE001
            self.session._fail("build", exc, self.question_id)
            return
        self.session._append(row, record)

    def _write_failure(self, status: str, error: str) -> None:
        if self._done:
            return
        self._done = True
        try:
            origin = {**self.origin, "delivery": NOT_DELIVERED}
            record = M.failure_record(**self._ident(), status=status, error=error, origin=origin)
            row = {"question_id": self.question_id, "question": self.question,
                   "execution_status": "CANCELLED" if status == M.STATUS_CANCELLED else "ERROR", "answer": None,
                   "conversation_id": origin["conversation_id"], "turn_id": origin["turn_id"],
                   "endpoint": origin["endpoint"], "captured_utc": record["captured_utc"], "error": error}
        except Exception as exc:  # noqa: BLE001
            self.session._fail("build", exc, self.question_id)
            return
        self.session._append(row, record)
