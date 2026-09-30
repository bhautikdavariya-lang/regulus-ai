"""Classify the failures in a saved evaluation run, and name the layer that
should fix each one.

The Stage 13 brief asks for failures to be sorted into classes and attributed
to a layer, so that a deterministic problem is not "fixed" by training and a
behavioural problem is not "fixed" by a rule. This does the sorting from the
saved result file plus the benchmark's own expectations; it never re-runs the
model.

Usage:
    python scripts/analyze_failures.py data/evaluation/results/stage13_v1/rag-stage13-lora_*.json
    python scripts/analyze_failures.py A.json B.json --answers
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from regulus.evaluation.grounding_eval import ANSWER, HEDGED, REFUSAL, classify_answer
from regulus.grounding.identifiers import extract_identifier

# failure classes from the Stage 13 brief
CLASSES = {
    "A": ("nonexistent identifier answered", "grounding gate"),
    "C": ("existing identifier, irrelevant context, answered anyway", "training data"),
    "D": ("partially supported context, unsupported remainder asserted", "training data"),
    "E": ("CFR / FDA guidance confusion", "training data"),
    "F": ("citation does not match the supporting passage", "training data + citation validation"),
    "G": ("refused although the answer was supported", "training data balance"),
    "H": ("unsupported answer despite a valid identifier", "training data"),
    "I": ("repetition or degeneration", "decoding / training duration"),
    "J": ("formatting failure", "prompt / training data"),
    "K": ("other", "review"),
}


def _sources(r: dict) -> list[dict]:
    return ((r.get("diagnostics") or {}).get("context") or {}).get("sources", []) or []


def _degenerate(a: str) -> bool:
    import re

    quoted = re.findall(r'"[^"]{6,}"', a or "")
    return len(re.findall(r"(?<![A-Za-z0-9])\[\d{1,2}\]", a or "")) > 12 or (len(quoted) - len(set(quoted))) >= 2


def classify_failure(r: dict) -> tuple[str, str] | None:
    """Return (class, why) for a failed question, or None when it looks fine."""
    answer = r.get("model_answer") or ""
    kind = classify_answer(answer)
    expected = r.get("expected_behavior")
    score = r.get("quality_score")
    ident = extract_identifier(r.get("question", ""))
    retrieved = " ".join(s.get("citation", "") for s in _sources(r))
    gate = (r.get("diagnostics") or {}).get("grounding") or {}

    if _degenerate(answer):
        return "I", "repeated markers or repeated quoted phrases"
    if expected == "acknowledge_uncertainty" and kind in (ANSWER, HEDGED):
        if ident is not None:
            key = ident.section or ident.part or ident.docket or ""
            if key and key not in retrieved:
                return "A", f"{ident.label} is not in the retrieved context yet content was produced"
            return "H", f"{ident.label} exists but the answer is not supported by the retrieved passage"
        return "H", "content produced where the benchmark expects uncertainty"
    if expected == "answer" and kind == REFUSAL:
        return "G", "refused a question the benchmark marks answerable"
    if score is not None and score <= 1:
        if ident is not None:
            key = ident.section or ident.part or ident.docket or ""
            if key and key not in retrieved:
                return "C", f"answered about {ident.label} from context that does not carry it"
        low = answer.lower()
        if ("guidance" in low and "binding regulation" in low) or ("non-binding" in low and "21 cfr" in low and "guidance" not in low.split("21 cfr")[0][-60:]):
            return "E", "mixes binding regulation with non-binding guidance"
        if score == 0:
            return "K", "scored 0 for reasons not captured by the structural classes"
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    p.add_argument("--answers", action="store_true", help="print the offending answer text")
    p.add_argument("--width", type=int, default=240)
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for raw in args.runs:
        path = Path(raw)
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("run", {}).get("pipeline", path.stem)
        rows = []
        for r in data.get("results", []):
            hit = classify_failure(r)
            if hit:
                rows.append((hit[0], r["question_id"], r.get("category"), hit[1], r.get("model_answer") or ""))
        rows.sort()
        counts = Counter(c for c, *_ in rows)
        print(f"\n===== {name}: {len(rows)} failures of {len(data.get('results', []))}")
        for cls in sorted(CLASSES):
            if counts.get(cls):
                desc, layer = CLASSES[cls]
                print(f"  {cls}  {counts[cls]:>2}  {desc:<58} -> fix in: {layer}")
        for cls, qid, cat, why, ans in rows:
            print(f"    [{cls}] {qid} ({cat}): {why}")
            if args.answers:
                print(f"         {ans[:args.width]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
