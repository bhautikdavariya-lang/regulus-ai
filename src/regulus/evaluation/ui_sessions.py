"""Offline evaluation of a UI measurement session (regulus.traceability.ui_session).

    python scripts/evaluate_ui_session.py data/ui_measurements/<session> [--evaluation-out FILE]
                                                                         [--offline-aligner lexical|semantic]

A session is laid out like an acceptance run, so the evaluation itself is the existing one,
`regulus.evaluation.offline_evaluation.evaluate_run`: the same integrity checks, the same lossless rebuilding
of the evaluator's inputs, the same refusal of anything missing or malformed (not_evaluable), the same parity
record. This module only adds what a session needs around it:

  - a session is still written to while its server runs, so the two files are copied first and the copy is
    evaluated: rows appended meanwhile are left for a later evaluation, and a half-written last line is
    reported, not evaluated. The copy is deleted afterwards; the session's own files are only read, and are
    checked afterwards to have been only appended to.
  - results go INSIDE the session directory (<session>/evaluations/<utc>_<execution id>.jsonl), because they
    quote the user's questions and answers: like the session, git-ignored and local. A new file every time,
    never overwritten.
  - each UI record already holds the LIVE assessment the user saw; the summary compares it with the offline
    one, per question, next to that row's parity record.
  - the session's state is reported: "closed" (clean stop, final counters recorded), "running" (its process
    is alive on this host), "ended_uncleanly" (its process is gone and it never closed: SIGKILL, crash, power
    loss) or "not_closed" (opened on another host). Records of an unclosed session are evaluated like any
    other: a missing finished_utc is not a reason to refuse them.
  - a session.json that cannot be read (written by an older version, or damaged) does not make the records
    unusable: when the records themselves identify the directory as a UI session (origin.source "ui", run_id
    = the directory name) the session is evaluated and reported as "session_file_unreadable".
  - everything written here is private: the evaluations directory 0700, result files and the temporary copy
    0600 (a restrictive umask for the duration of the evaluation).

Nothing is answered, retrieved or looked up in a database.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from regulus.evaluation.offline_evaluation import EVALUATED, evaluate_run
from regulus.traceability import measurement as M
from regulus.traceability.ui_session import ANSWERS_FILE, CLOSED, SESSION_FILE, SESSION_SCHEMA, host_fingerprint


class NotASession(ValueError):
    """The directory is not a UI measurement session."""


def _records_say_ui(session_dir: Path) -> bool:
    """True when the first readable record is a UI record of this directory's session."""
    path = session_dir / M.MEASUREMENT_FILE
    if not path.is_file():
        return False
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            return ((rec.get("origin") or {}).get("source") == "ui"
                    and (rec.get("run") or {}).get("run_id") == session_dir.name)
    return False


def _session(session_dir: Path) -> dict[str, Any]:
    try:
        meta = json.loads((session_dir / SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if _records_say_ui(session_dir):
            return {"session_id": session_dir.name, "state": None, "session_file_error": type(exc).__name__}
        raise NotASession(f"{session_dir} has no readable {SESSION_FILE} ({type(exc).__name__})") from None
    if meta.get("schema") != SESSION_SCHEMA or meta.get("session_id") != session_dir.name:
        raise NotASession(f"{session_dir} is not a {SESSION_SCHEMA} session")
    return meta


def session_state(meta: dict[str, Any]) -> str:
    if meta.get("session_file_error"):
        return "session_file_unreadable"
    if meta.get("state") == CLOSED or meta.get("finished_utc"):
        return "closed"
    pid, host = meta.get("pid"), meta.get("host")
    if not isinstance(pid, int) or host != host_fingerprint():
        return "not_closed"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "ended_uncleanly"
    except PermissionError:          # alive, owned by someone else
        return "running"
    except OSError:
        return "not_closed"
    return "running"


def evaluate_ui_session(session_dir: Path | str, out_path: Path | str | None = None, *, root: Path,
                        aligner=None, execution_id: str | None = None) -> dict[str, Any]:
    session_dir = Path(session_dir).resolve()
    meta = _session(session_dir)
    execution_id = execution_id or uuid.uuid4().hex
    out_path = Path(out_path) if out_path else (session_dir / "evaluations" /
                                                f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{execution_id[:12]}.jsonl")
    sources = [session_dir / ANSWERS_FILE, session_dir / M.MEASUREMENT_FILE]
    frozen = {p.name: p.read_bytes() if p.is_file() else b"" for p in sources}
    work = session_dir / "evaluations" / f".snapshot_{execution_id}"
    previous_umask = os.umask(0o077)                   # results quote user content: private files and dirs
    try:
        (session_dir / "evaluations").mkdir(mode=0o700, exist_ok=True)
        copy = work / session_dir.name                 # evaluate_run keys records by the directory's name
        copy.mkdir(mode=0o700, parents=True)
        for name, data in frozen.items():
            (copy / name).write_bytes(data)
        summary = evaluate_run(copy, out_path, root=root, aligner=aligner, execution_id=execution_id)
    finally:
        os.umask(previous_umask)
        shutil.rmtree(work, ignore_errors=True)        # the temporary copy only; never the session's files
    appended_only = all((p.read_bytes() if p.is_file() else b"").startswith(frozen[p.name]) for p in sources)

    live = {}
    for line in frozen[M.MEASUREMENT_FILE].decode("utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        review = ((rec.get("evaluation") or {}).get("review") or {}) if isinstance(rec, dict) else {}
        live[rec.get("question_id")] = review.get("status")
    rows, agree, differ, duplicates = [], 0, [], 0
    for line in out_path.read_text(encoding="utf-8").splitlines():
        result = json.loads(line)["result"]
        duplicates += "more than one record" in (result.get("reason") or "")
        if result["outcome"] != EVALUATED or live.get(result["question_id"]) is None:
            continue
        rows.append(result["question_id"])
        if result["review_status"] == live[result["question_id"]]:
            agree += 1
        else:
            differ.append({"question_id": result["question_id"], "live": live[result["question_id"]],
                           "offline": result["review_status"],
                           "live_equivalent": (result.get("parity") or {}).get("live_equivalent")})
    problems = summary["problems"]
    return {**summary, "run_dir": str(session_dir), "session_id": meta["session_id"],
            "session_state": session_state(meta), "session_counters": meta.get("counters"),
            "session_finished": meta.get("finished_utc") is not None, "rows_in_snapshot": summary["rows"],
            "integrity": {"unreadable_lines": sum("unreadable" in p for p in problems),
                          "records_without_row": sum("records without an answers.jsonl row" in p for p in problems),
                          "rows_with_duplicate_records": duplicates},
            "session_files_only_appended": appended_only,
            "live_vs_offline": {"compared": len(rows), "same_review_status": agree, "different": differ}}
