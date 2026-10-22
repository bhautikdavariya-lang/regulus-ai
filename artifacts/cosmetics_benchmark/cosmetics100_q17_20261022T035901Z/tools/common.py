"""Shared loaders for the cosmetics benchmark run directory (read-only)."""

from __future__ import annotations

import json
import re
from pathlib import Path

SECTION_RE = re.compile(r"\b(\d{2,3}\.\d+[a-z]?)\b")
MARKER_RE = re.compile(r"\[(\d+)\]")


def load_run(run_dir: Path) -> list[dict]:
    """One dict per selected question, in run order: the bank row, the result row, the full response."""
    sel = json.loads((run_dir / "selection.json").read_text(encoding="utf-8"))
    results = {}
    if (run_dir / "results.jsonl").exists():
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                results.setdefault(r["question_id"], []).append(r)
    out = []
    for q in sel["questions"]:
        rows = results.get(q["ID"], [])
        resp_path = run_dir / "responses" / f"{q['ID']}.json"
        resp = json.loads(resp_path.read_text(encoding="utf-8")) if resp_path.exists() else None
        out.append({"q": q, "attempts": rows, "r": rows[-1] if rows else None, "resp": resp})
    return out


def expected_sections(q: dict) -> list[str]:
    return sorted(set(SECTION_RE.findall(str(q.get("Expected Citation — VERIFIED KEY") or ""))))


def label_has_section(label: str, section: str) -> bool:
    return re.search(r"21 CFR " + re.escape(section) + r"(?![\d.a-z])", label or "") is not None


def evidence_check(q: dict, resp: dict | None) -> dict:
    exp = expected_sections(q)
    srcs = [s.get("citation") or "" for s in (resp or {}).get("sources") or []]
    cites = [c.get("label") or "" for c in (resp or {}).get("citations") or [] if c.get("cited_in_answer")]
    return {
        "expected": exp,
        "in_evidence": [s for s in exp if any(label_has_section(l, s) for l in srcs)],
        "cited": [s for s in exp if any(label_has_section(l, s) for l in cites)],
        "statute_key": "FD&C" in str(q.get("Expected Citation — VERIFIED KEY") or "") or "U.S.C" in str(q.get("Expected Citation — VERIFIED KEY") or ""),
    }


def resolve_markers(answer: str, resp: dict | None) -> list[str]:
    """[n] markers used in the answer -> the citation label the response gives for n."""
    labels = {c.get("index"): c.get("label") for c in (resp or {}).get("citations") or []}
    src = {s.get("index"): s.get("citation") for s in (resp or {}).get("sources") or []}
    seen = []
    for n in MARKER_RE.findall(answer or ""):
        n = int(n)
        lab = labels.get(n) or src.get(n) or "UNRESOLVED"
        item = f"[{n}] = {lab}"
        if item not in seen:
            seen.append(item)
    return seen
