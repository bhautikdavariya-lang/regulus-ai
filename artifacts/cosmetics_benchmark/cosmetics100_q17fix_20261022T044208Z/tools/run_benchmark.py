"""Send the selected cosmetics questions to a running Regulus answering UI (scripts/serve_ui.py), one at a time.

    python run_benchmark.py <run_dir> [--url http://127.0.0.1:8765] [--timeout 1800] [--warmup "question"]

This is a CLIENT only: it changes nothing in the application. Each question is POSTed verbatim to
/api/ask as {"question": <text>} - the request the page makes with every control at its default (no
adapter, grounding gate off, top_k 8, configured token ceiling, accuracy evaluator as the server runs
it, default model). /api/ask is stateless: no conversation history reaches the model.

Timing: time.perf_counter() (monotonic) around the full HTTP request, from sending the request to
having the complete response body. The server's own stage timings (retrieval, generation, accuracy
evaluation, lock wait) are copied from the response, never estimated.

No retries. An HTTP error, a timeout or a connection failure is recorded once, with its details, and
the run moves on. On restart, questions already recorded in results.jsonl are skipped (and the restart
is logged in run_log.jsonl), so an interrupted run never re-asks a recorded question.

Writes in <run_dir>: results.jsonl (one row per question), responses/<ID>.json (the full response
body), run_log.jsonl (start/stop/warm-up events, tree fingerprints).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]   # project root (artifacts/cosmetics_benchmark/<run>/tools/)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout


def tree_fingerprint() -> dict:
    """The code the server runs: HEAD, the tracked diff, and every untracked/modified file's hash."""
    status = git("status", "--porcelain", "--untracked-files=all")
    files = {}
    for line in status.splitlines():
        path = line[3:]
        p = ROOT / path
        if p.is_file() and not path.startswith("artifacts/cosmetics_benchmark/"):
            files[path] = hashlib.sha256(p.read_bytes()).hexdigest()
    diff = subprocess.run(["git", "diff", "HEAD"], cwd=ROOT, capture_output=True, timeout=60).stdout
    return {"head": git("rev-parse", "HEAD").strip(), "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
            "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "changed_or_untracked_files": len(files),
            "files_sha256": files,
            "combined_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def log(run_dir: Path, event: dict) -> None:
    with (run_dir / "run_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"utc": now(), **event}, ensure_ascii=False, default=str) + "\n")


def post(url: str, question: str, timeout: float):
    body = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(url + "/api/ask", data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (TimeoutError, socket.timeout) as exc:
        return time.perf_counter() - t0, None, None, f"TIMEOUT after {timeout}s: {type(exc).__name__}: {exc}"
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return time.perf_counter() - t0, None, None, f"TIMEOUT after {timeout}s: {reason}"
        return time.perf_counter() - t0, None, None, f"CONNECTION: {type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return time.perf_counter() - t0, None, None, f"CLIENT: {type(exc).__name__}: {exc}"
    seconds = time.perf_counter() - t0
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return seconds, status, None, f"BAD_RESPONSE: {type(exc).__name__}: {raw[:300]!r}"
    return seconds, status, payload, None


def row_from(q: dict, seconds: float, status, payload, error) -> dict:
    base = {"question_id": q["ID"], "run_order": q["Run Order"], "question": q["Question (ask verbatim)"],
            "client_seconds": round(seconds, 3), "http_status": status, "started_utc": None}
    if error is not None:
        kind = "TIMEOUT" if error.startswith("TIMEOUT") else "ERROR"
        return {**base, "execution_status": kind, "error": error, "answer": None}
    if status != 200 or not isinstance(payload, dict) or "answer" not in payload:
        return {**base, "execution_status": "ERROR",
                "error": f"HTTP {status}: {(payload or {}).get('error') if isinstance(payload, dict) else payload}",
                "answer": None}
    acc = payload.get("accuracy") or {}
    rev = acc.get("question_review") or {}
    t = payload.get("timings_ms") or {}
    st = payload.get("server_timings_ms") or {}
    val = payload.get("validation") or {}
    gen = payload.get("generation") or {}
    return {
        **base, "execution_status": "SUCCESS", "error": None,
        "answer": payload.get("answer"),
        "input_tokens": payload.get("input_tokens"), "output_tokens": payload.get("output_tokens"),
        "model_called": payload.get("model_called"), "no_context": payload.get("no_context"),
        "model": payload.get("model"), "adapter": payload.get("adapter"),
        "timings_ms": t, "server_timings_ms": st, "wall_seconds_server": payload.get("wall_seconds"),
        "citations": [c.get("label") for c in payload.get("citations") or []],
        "cited_in_answer": [c.get("label") for c in payload.get("citations") or [] if c.get("cited_in_answer")],
        "sources": [{"citation": s.get("citation"), "method": s.get("method"), "score": s.get("score"),
                     "tier": s.get("tier")} for s in payload.get("sources") or []],
        "query_type": payload.get("query_type"),
        "answerability": (payload.get("answerability") or {}).get("state") if isinstance(payload.get("answerability"), dict) else payload.get("answerability"),
        "fallback_type": payload.get("fallback_type"), "fallback_reason": payload.get("fallback_reason"),
        "generation_blocked": payload.get("generation_blocked"), "block_reason": payload.get("block_reason"),
        "semantic_fallback": payload.get("semantic_fallback"),
        "evidence_gap": (payload.get("coverage") or {}).get("evidence_complete") if isinstance(payload.get("coverage"), dict) else None,
        "validation_initial": (val.get("initial") or {}).get("status"),
        "validation_initial_codes": (val.get("initial") or {}).get("codes"),
        "validation_final": (val.get("final") or {}).get("status"),
        "repair": val.get("repair") if not isinstance(val.get("repair"), dict) else {k: v for k, v in val["repair"].items() if k not in ("repair_input", "repair_output")},
        "stop_reason": gen.get("stop_reason"), "finished": gen.get("finished"),
        "live_eval": {"status": rev.get("status"), "label": rev.get("label"), "score": rev.get("live_check_score"),
                      "explanation": rev.get("explanation"), "evaluator_status": acc.get("status"),
                      "answer_verdict": (acc.get("answer_verdict") or {}).get("verdict") if isinstance(acc.get("answer_verdict"), dict) else None,
                      "rubric_id": rev.get("rubric_id")},
        "snapshot_date": payload.get("snapshot_date"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--warmup", default=None)
    a = ap.parse_args()
    run_dir = Path(a.run_dir).resolve()
    questions = json.loads((run_dir / "selection.json").read_text(encoding="utf-8"))["questions"]
    (run_dir / "responses").mkdir(exist_ok=True)
    results = run_dir / "results.jsonl"
    done = set()
    if results.exists():
        done = {json.loads(l)["question_id"] for l in results.read_text(encoding="utf-8").splitlines() if l.strip()}

    with urllib.request.urlopen(a.url + "/api/config", timeout=30) as resp:
        config = json.loads(resp.read().decode("utf-8"))
    (run_dir / f"server_config_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(
        json.dumps(config, indent=1, default=str), encoding="utf-8")
    log(run_dir, {"event": "start", "already_recorded": len(done), "to_run": len(questions) - len(done),
                  "url": a.url, "timeout_s": a.timeout, "argv": sys.argv, "tree": tree_fingerprint()})

    if a.warmup and not done:
        seconds, status, payload, error = post(a.url, a.warmup, a.timeout)
        log(run_dir, {"event": "warmup", "question": a.warmup, "client_seconds": round(seconds, 3), "http_status": status,
                      "error": error, "answer": (payload or {}).get("answer") if isinstance(payload, dict) else None,
                      "timings_ms": (payload or {}).get("timings_ms") if isinstance(payload, dict) else None,
                      "server_timings_ms": (payload or {}).get("server_timings_ms") if isinstance(payload, dict) else None,
                      "note": "excluded from every benchmark statistic"})

    t_run = time.perf_counter()
    todo = [q for q in questions if q["ID"] not in done]
    for n, q in enumerate(todo, start=1):
        started = now()
        seconds, status, payload, error = post(a.url, q["Question (ask verbatim)"], a.timeout)
        row = row_from(q, seconds, status, payload, error)
        row["started_utc"], row["finished_utc"] = started, now()
        if payload is not None:
            (run_dir / "responses" / f"{q['ID']}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        with results.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        el = time.perf_counter() - t_run
        print(f"{len(done) + n:3}/{len(questions)} {q['ID']:22} {row['execution_status']:7} {seconds:7.1f}s "
              f"in={row.get('input_tokens')} out={row.get('output_tokens')} live={((row.get('live_eval') or {}).get('label'))} "
              f"| elapsed {el / 60:5.1f} min, ~{el / n * (len(todo) - n) / 60:5.1f} min left", flush=True)
    log(run_dir, {"event": "finish", "run_seconds_this_invocation": round(time.perf_counter() - t_run, 3),
                  "tree": tree_fingerprint()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
