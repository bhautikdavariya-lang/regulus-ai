"""The hard gate: no scoring and no training on an unverified key.

The workbook's own instruction is that "An unverified key invalidates the
entire result." A dashboard that displays BLOCKED does not enforce that; a
person can still run the script. So the refusal lives here, on the execution
path, and the entry points call it before they do any work.

    require_locked_key(...)   -> returns the locked key, or raises

Two gates use it, and they are deliberately separate calls with separate
messages, because the reasons differ:

* **Scoring** must not run because a score computed against an unverified key
  is not a measurement of anything.
* **Training** must not run because the benchmark is an acceptance test. Using
  an unresolved answer key to build training data would both leak the test and
  teach the model an expectation nobody has checked.

Nothing here weakens an existing gate: the leakage exclusion in
`regulus.training.config` and the Stage 5 planning gate keep working exactly
as before. This is an additional refusal in front of them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_KEY_ROOT = Path("artifacts") / "benchmark_keys"
LOCKED_FILE = "locked_key.json"


class AcceptanceGateError(RuntimeError):
    """Raised when an execution path is blocked by the key-verification gate."""


def _explain(reason: str, action: str) -> str:
    return (
        f"{action} is blocked by the acceptance benchmark key gate.\n"
        f"  reason: {reason}\n"
        "  The Regulus AI Vendor Acceptance Benchmark's own instructions state that the draft "
        "answer key must be verified by an SME before the test is administered, and that an "
        "unverified key invalidates the entire result.\n"
        "  Resolve the outstanding rows with `python scripts/review_benchmark_key.py`, have the "
        "reviewer sign the review off, and the locked key will be written automatically."
    )


def find_locked_keys(root: Path | str = DEFAULT_KEY_ROOT) -> list[Path]:
    """Every locked key version on disk, newest last."""
    base = Path(root)
    if not base.is_dir():
        return []
    return sorted(base.glob(f"*/locked/*/{LOCKED_FILE}"))


def load_locked_key(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def locked_key_for(benchmark_key: str, root: Path | str = DEFAULT_KEY_ROOT) -> dict[str, Any] | None:
    """The newest locked key for this exact benchmark content, if any.

    Matching on the content hash is what stops a key locked against one
    version of the workbook unlocking a different one.
    """
    best: dict[str, Any] | None = None
    for path in find_locked_keys(root):
        payload = load_locked_key(path)
        if payload.get("benchmark_key") != benchmark_key:
            continue
        if best is None or int(payload.get("review_version", 0)) >= int(best.get("review_version", 0)):
            best = payload
            best["_path"] = path.as_posix()
    return best


def gate_status(benchmark_key: str, root: Path | str = DEFAULT_KEY_ROOT) -> dict[str, Any]:
    """What the gate would do, without raising. For dashboards and reports."""
    locked = locked_key_for(benchmark_key, root)
    if locked is None:
        return {
            "open": False,
            "benchmark_key": benchmark_key,
            "reason": "no locked key exists for this benchmark version",
            "locked_key": None,
        }
    signoff = locked.get("signoff") or {}
    if not signoff.get("reviewer"):
        return {"open": False, "benchmark_key": benchmark_key,
                "reason": "the locked key carries no reviewer sign-off", "locked_key": locked}
    unresolved = [r for r in locked.get("rows", [])
                  if not r.get("in_scope_for_scoring") and r.get("state") != "REJECTED"]
    if unresolved:
        return {
            "open": False, "benchmark_key": benchmark_key,
            "reason": f"{len(unresolved)} row(s) in the locked key are not verified",
            "unresolved_ids": [r["question_id"] for r in unresolved[:20]],
            "locked_key": locked,
        }
    return {
        "open": True, "benchmark_key": benchmark_key, "reason": None, "locked_key": locked,
        "key_version_sha256": locked.get("key_version_sha256"),
        "scoring_rows": locked.get("scoring_rows"),
        "withdrawn_rows": locked.get("withdrawn_rows", []),
        "reviewer": signoff.get("reviewer"),
        "signed_at": signoff.get("signed_at"),
    }


def require_locked_key(
    benchmark_key: str,
    action: str,
    root: Path | str = DEFAULT_KEY_ROOT,
) -> dict[str, Any]:
    """Return the locked key for this benchmark, or refuse.

    This is the function an execution path calls. It raises rather than
    returning a flag, so a caller cannot proceed by ignoring a return value.
    """
    status = gate_status(benchmark_key, root)
    if not status["open"]:
        raise AcceptanceGateError(_explain(status["reason"], action))
    return status["locked_key"]


def require_benchmark_not_in_training(
    texts, benchmark, action: str = "Training data preparation",
) -> None:
    """Refuse if any acceptance-benchmark question appears in training text.

    The benchmark is an acceptance test. It is held out by construction, and
    this is the check that it stayed held out - it complements, and does not
    replace, the group-level benchmark exclusion in `regulus.training.config`.
    """
    from regulus.evaluation.acceptance_benchmark import leaked_questions

    hits = leaked_questions(benchmark, texts)
    if hits:
        ids = ", ".join(h["question_id"] for h in hits[:10])
        raise AcceptanceGateError(
            f"{action} is blocked: {len(hits)} acceptance-benchmark question(s) appear verbatim in "
            f"the training text ({ids}). The 300-question workbook is an acceptance test and must "
            "stay completely held out of anything the model is trained on."
        )
