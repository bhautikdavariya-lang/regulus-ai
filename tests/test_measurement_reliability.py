"""Reliability of UI measurement storage (regulus.traceability.ui_session, regulus.evaluation.ui_sessions).

Regressions for the audit's findings: a write cut short no longer corrupts the next record (the tail is
terminated in place, never discarded); the record is written before its row and only both count as
recorded; session.json is replaced atomically; SIGTERM closes the session; files are private; counters stay
exact under concurrency; logs carry ids and categories, never user content; and the offline evaluator
reports - never scores - what a failure left behind. Temporary directories and scripted answers only.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from regulus.config import PROJECT_ROOT
from regulus.evaluation import offline_evaluation as O
from regulus.evaluation.ui_sessions import evaluate_ui_session, session_state
from regulus.traceability import measurement as M
from regulus.traceability import ui_session as U
from tests.test_accuracy_observer import CASES, answer_one

RUN = {"source": "ui", "model": {"model_id": "scripted"}}
SECRET_QUESTION = "What does 21 CFR 820.10(b)(2) require for PRIVATE-MARKER-7f3a?"
POSIX = os.name == "posix"


def session(tmp_path, log=None):
    return U.UISession(tmp_path / "ui_measurements", RUN, log=log if log is not None else (lambda m: None))


def deliver(s, case=0, question=None):
    out = answer_one(*CASES[case])
    t = s.turn(question or out.question, endpoint="/api/ask")
    t.answered(out, evaluation=None, review=None)
    t.finish(U.DELIVERED)
    return t


def read_lines(path):
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def parse(path):
    good, bad = [], []
    for n, line in enumerate(read_lines(path), start=1):
        try:
            good.append(json.loads(line))
        except ValueError:
            bad.append(n)
    return good, bad


def results(summary):
    return [json.loads(l)["result"] for l in Path(summary["output"]).read_text().splitlines()]


class FailOnce:
    """_write_all that, for the first write to `name`, writes half and then fails as a full disk does."""

    def __init__(self, monkeypatch, name, *, err=errno.ENOSPC, half=True):
        self.real, self.name, self.err, self.half, self.armed = U._write_all, name, err, half, True
        monkeypatch.setattr(U, "_write_all", self)

    def __call__(self, fd, data):
        target = os.readlink(f"/proc/self/fd/{fd}") if Path("/proc/self/fd").exists() else None
        is_target = (target or "").endswith(self.name) if target else self._by_content(data)
        if self.armed and is_target and data != b"\n":
            self.armed = False
            if self.half:
                self.real(fd, data[: len(data) // 2])
            raise OSError(self.err, os.strerror(self.err))
        return self.real(fd, data)

    def _by_content(self, data):
        # no /proc (macOS): a measurement record is the sorted-key JSON object that starts with "canonicalization"
        starts = data.lstrip()[:20]
        return (b'"canonicalization"' in starts) == (self.name == M.MEASUREMENT_FILE) and starts.startswith(b"{")


# ------------------------------------------------------------------ partial lines


def test_an_unterminated_tail_is_terminated_in_place_and_the_next_record_is_clean(tmp_path):
    logs = []
    s = session(tmp_path, logs.append)
    deliver(s)
    path = s.dir / M.MEASUREMENT_FILE
    with path.open("a", encoding="utf-8") as f:                 # what a write cut short by SIGKILL leaves
        f.write('{"schema": "regulus_measurement_record_v1", "question_id": "ui-trunc')
    fragment_before = path.read_bytes()
    t = deliver(s, case=3)
    good, bad = parse(path)
    assert path.read_bytes().startswith(fragment_before)        # nothing truncated, nothing rewritten
    assert bad == [2] and [r["question_id"] for r in good][-1] == t.question_id
    assert all(M.verify_record(r) == [] for r in good)
    assert s.recovered_partial_lines == 1 and s.written == 2
    assert any("event=partial_line_terminated" in l for l in logs)
    loaded = M.load_run(s.dir)
    assert any("measurement.jsonl:2: not JSON" in p for p in loaded["problems"])


def test_a_write_cut_short_by_a_full_disk_costs_only_its_own_record(tmp_path, monkeypatch):
    s = session(tmp_path)
    FailOnce(monkeypatch, M.MEASUREMENT_FILE)
    first = deliver(s)                                           # half the record reaches the disk, then ENOSPC
    second = deliver(s, case=3)
    records, bad = parse(s.dir / M.MEASUREMENT_FILE)
    rows, _ = parse(s.dir / U.ANSWERS_FILE)
    assert [r["question_id"] for r in records] == [second.question_id] and bad == [1]
    assert [r["question_id"] for r in rows] == [second.question_id]     # no row for the record that failed
    assert s.failures == {"measurement:ENOSPC": 1} and s.written == 1 and s.recovered_partial_lines == 1
    assert [r["ordinal"] for r in records] == [2]                       # the failed write's ordinal is a gap
    summary = evaluate_ui_session(s.dir, root=PROJECT_ROOT)
    assert [r["outcome"] for r in results(summary)] == [O.EVALUATED]
    assert summary["integrity"]["unreadable_lines"] == 1
    assert first.question_id not in json.dumps(results(summary))


def test_a_full_disk_on_the_row_leaves_a_reported_record_without_a_row(tmp_path, monkeypatch):
    s = session(tmp_path)
    FailOnce(monkeypatch, U.ANSWERS_FILE, half=False)
    lonely = deliver(s)
    deliver(s, case=3)
    assert s.failures == {"answers:ENOSPC": 1} and s.records_without_row == 1 and s.written == 1
    summary = evaluate_ui_session(s.dir, root=PROJECT_ROOT)
    assert summary["integrity"]["records_without_row"] == 1
    assert lonely.question_id not in {r["question_id"] for r in results(summary)}    # reported, never scored


@pytest.mark.skipif(not POSIX or os.geteuid() == 0, reason="needs POSIX permissions and a non-root user")
def test_a_read_only_session_directory_is_counted_not_raised(tmp_path):
    s = session(tmp_path)
    deliver(s)
    os.chmod(s.dir, 0o500)
    (s.dir / M.MEASUREMENT_FILE).chmod(0o400)
    try:
        deliver(s, case=3)                                           # must not raise
    finally:
        os.chmod(s.dir, 0o700)
        (s.dir / M.MEASUREMENT_FILE).chmod(0o600)
    assert s.written == 1 and list(s.failures) == ["measurement:EACCES"]
    assert s.status()["last_failure"]["category"] == "EACCES"


# ------------------------------------------------------------------ pairs, hashes


def test_missing_and_mismatched_pairs_are_refused(tmp_path):
    s = session(tmp_path)
    a, b, c = deliver(s), deliver(s, case=3), deliver(s, case=6)
    rows_path, recs_path = s.dir / U.ANSWERS_FILE, s.dir / M.MEASUREMENT_FILE
    rows = [json.loads(l) for l in read_lines(rows_path)]
    rows[0]["answer"] += " (edited)"                                 # a row that disagrees with its record
    rows_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    recs = [json.loads(l) for l in read_lines(recs_path)]
    recs_path.write_text("".join(json.dumps(r) + "\n" for r in recs if r["question_id"] != b.question_id))
    recs = [json.loads(l) for l in read_lines(recs_path)]
    recs[-1]["text"]["delivered_answer"]["text"] = "tampered"         # a record whose hash no longer holds
    recs_path.write_text("".join(json.dumps(r) + "\n" for r in recs))
    by_id = {r["question_id"]: r for r in results(evaluate_ui_session(s.dir, root=PROJECT_ROOT))}
    assert by_id[a.question_id]["outcome"] == O.NOT_EVALUABLE and "answer differs" in by_id[a.question_id]["reason"]
    assert by_id[b.question_id]["outcome"] == O.NOT_EVALUABLE and "no measurement record" in by_id[b.question_id]["reason"]
    assert by_id[c.question_id]["outcome"] == O.NOT_EVALUABLE and "integrity" in by_id[c.question_id]["reason"]
    assert all(r["review_status"] is None for r in by_id.values())


def test_duplicate_records_are_refused(tmp_path):
    s = session(tmp_path)
    t = deliver(s)
    line = read_lines(s.dir / M.MEASUREMENT_FILE)[0]
    U.append_line(s.dir / M.MEASUREMENT_FILE, line)
    summary = evaluate_ui_session(s.dir, root=PROJECT_ROOT)
    [r] = results(summary)
    assert r["outcome"] == O.NOT_EVALUABLE and summary["integrity"]["rows_with_duplicate_records"] == 1


# ------------------------------------------------------------------ session.json


def test_session_json_is_replaced_atomically(tmp_path, monkeypatch):
    s = session(tmp_path)
    before = (s.dir / U.SESSION_FILE).read_bytes()

    def broken_replace(src, dst):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(U.os, "replace", broken_replace)
    s.close()                                                        # never raises
    monkeypatch.undo()
    assert (s.dir / U.SESSION_FILE).read_bytes() == before           # the previous version, whole
    assert not list(s.dir.glob(".session.json.*.tmp"))               # no temporary file left behind
    assert json.loads(before)["state"] == U.OPEN


def test_a_closed_session_records_its_final_counters(tmp_path):
    s = session(tmp_path)
    deliver(s)
    deliver(s, case=3)
    s.close()
    s.close()                                                        # idempotent
    meta = json.loads((s.dir / U.SESSION_FILE).read_text())
    assert meta["state"] == U.CLOSED and meta["finished_utc"] and meta["counters"]["written"] == 2
    assert session_state(meta) == "closed"
    assert evaluate_ui_session(s.dir, root=PROJECT_ROOT)["session_state"] == "closed"


CHILD = r'''
import sys, os, time, json
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, sys.argv[3])
from regulus.traceability import ui_session as U
from tests.test_accuracy_observer import CASES, answer_one
s = U.UISession(sys.argv[1], {"source": "ui"}, log=lambda m: None)
out = answer_one(*CASES[0])
t = s.turn(out.question, endpoint="/api/ask"); t.answered(out, evaluation=None, review=None); t.finish(U.DELIVERED)
print(s.dir, flush=True)
time.sleep(60)
'''


@pytest.mark.skipif(not POSIX, reason="SIGKILL")
def test_a_session_killed_without_cleanup_is_reported_as_unclean_and_still_evaluated(tmp_path):
    p = subprocess.Popen([sys.executable, "-c", CHILD, str(tmp_path), str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)],
                         stdout=subprocess.PIPE, text=True)
    d = Path(p.stdout.readline().strip())
    assert evaluate_ui_session(d, tmp_path / "live.jsonl", root=PROJECT_ROOT)["session_state"] == "running"
    p.kill()
    p.wait(timeout=20)
    summary = evaluate_ui_session(d, root=PROJECT_ROOT)
    assert summary["session_state"] == "ended_uncleanly" and summary["session_counters"] is None
    assert [r["outcome"] for r in results(summary)] == [O.EVALUATED]   # a missing finish time is no reason to refuse


def test_an_unreadable_session_file_does_not_strand_valid_records(tmp_path):
    s = session(tmp_path)
    deliver(s)
    (s.dir / U.SESSION_FILE).write_text('{"schema": "regulus_ui_se')   # what the pre-atomic version could leave
    summary = evaluate_ui_session(s.dir, root=PROJECT_ROOT)
    assert summary["session_state"] == "session_file_unreadable"
    assert [r["outcome"] for r in results(summary)] == [O.EVALUATED]


# ------------------------------------------------------------------ permissions


@pytest.mark.skipif(not POSIX, reason="POSIX permissions")
def test_session_files_and_evaluation_results_are_private(tmp_path):
    s = session(tmp_path)
    deliver(s)
    mode = lambda p: stat.S_IMODE(p.stat().st_mode)                  # noqa: E731
    assert mode(s.dir.parent) == 0o700 and mode(s.dir) == 0o700
    for name in (U.SESSION_FILE, M.MEASUREMENT_FILE, U.ANSWERS_FILE):
        assert mode(s.dir / name) == 0o600, name
    summary = evaluate_ui_session(s.dir, root=PROJECT_ROOT)
    assert mode(s.dir / "evaluations") == 0o700 and mode(Path(summary["output"])) == 0o600
    s.close()
    assert mode(s.dir / U.SESSION_FILE) == 0o600


@pytest.mark.skipif(not POSIX, reason="POSIX permissions")
def test_an_existing_root_keeps_its_permissions(tmp_path):
    root = tmp_path / "shared"
    root.mkdir(mode=0o755)
    os.chmod(root, 0o755)
    s = U.UISession(root, RUN, log=lambda m: None)
    assert stat.S_IMODE(root.stat().st_mode) == 0o755 and stat.S_IMODE(s.dir.stat().st_mode) == 0o700


# ------------------------------------------------------------------ shutdown


SERVER = r'''
import sys, json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, sys.argv[3])
import importlib.util
spec = importlib.util.spec_from_file_location("serve_ui_shutdown", sys.argv[3] + "/scripts/serve_ui.py")
UI = importlib.util.module_from_spec(spec); spec.loader.exec_module(UI)
from regulus.traceability.ui_session import UISession
s = UISession(sys.argv[1], {"source": "ui"}, log=lambda m: None)
server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
print(s.dir, flush=True)
UI.serve_until_stopped(server, s.close)
print("cleaned", flush=True)
'''


@pytest.mark.skipif(not POSIX, reason="signals")
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_termination_closes_the_session(tmp_path, sig):
    p = subprocess.Popen([sys.executable, "-c", SERVER, str(tmp_path), str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)],
                         stdout=subprocess.PIPE, text=True)
    d = Path(p.stdout.readline().strip())
    time.sleep(0.5)
    p.send_signal(sig)
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 0 and "cleaned" in out
    meta = json.loads((d / U.SESSION_FILE).read_text())
    assert meta["state"] == U.CLOSED and meta["counters"] is not None


# ------------------------------------------------------------------ concurrency, logs


def test_concurrent_writes_keep_counters_and_ordinals_exact(tmp_path):
    s = session(tmp_path)
    outs = [answer_one(*CASES[i % 3]) for i in range(3)]
    turns = []
    for i in range(90):
        t = s.turn(outs[i % 3].question, endpoint="/api/ask")
        t.answered(outs[i % 3], evaluation=None, review=None)
        turns.append(t)
    barrier = threading.Barrier(15)

    def worker(chunk):
        barrier.wait()
        for t in chunk:
            t.finish(U.DELIVERED)

    threads = [threading.Thread(target=worker, args=(turns[i::15],)) for i in range(15)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    records, bad = parse(s.dir / M.MEASUREMENT_FILE)
    rows, bad_rows = parse(s.dir / U.ANSWERS_FILE)
    assert not bad and not bad_rows and len(records) == len(rows) == 90 == s.written
    assert sorted(r["ordinal"] for r in records) == list(range(1, 91))
    assert [r["question_id"] for r in records] == [r["question_id"] for r in rows]
    assert all(M.verify_record(r) == [] for r in records) and s.write_failures == 0
    assert s.status()["written"] == 90


def test_logs_carry_ids_and_categories_never_user_content(tmp_path, monkeypatch):
    logs = []
    s = session(tmp_path, logs.append)
    deliver(s, question=SECRET_QUESTION)
    FailOnce(monkeypatch, M.MEASUREMENT_FILE)
    deliver(s, question=SECRET_QUESTION)
    s.close()
    text = "\n".join(logs)
    assert "PRIVATE-MARKER-7f3a" not in text and "No space left" not in text
    assert "event=recorded" in text and "event=write_failed" in text and "category=ENOSPC" in text
    assert all(l.lstrip().startswith("measurement event=") for l in logs)
