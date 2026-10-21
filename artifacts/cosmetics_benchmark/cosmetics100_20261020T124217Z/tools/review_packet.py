"""Print the scoring packet for a slice of the run: key vs generated answer, markers resolved.

    python review_packet.py <run_dir> [start] [end]      (1-based run order, inclusive)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import evidence_check, load_run, resolve_markers  # noqa: E402


def main() -> int:
    run_dir = Path(sys.argv[1]).resolve()
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 6
    for item in load_run(run_dir):
        q, r, resp = item["q"], item["r"], item["resp"]
        if not (start <= q["Run Order"] <= end):
            continue
        print("=" * 100)
        print(f"#{q['Run Order']} {q['ID']} | {q['Question Type']} | {q['Difficulty']} | section {q['Section']}")
        print("Q:", q["Question (ask verbatim)"])
        print("EXPECTED CITATION:", q["Expected Citation — VERIFIED KEY"])
        print("KEY:", q["Key Answer Elements"])
        if q.get("Audit Correction Note"):
            print("AUDIT NOTE:", q["Audit Correction Note"])
        if r is None:
            print("RESULT: none recorded")
            continue
        print(f"EXEC: {r['execution_status']} {r.get('error') or ''}")
        print("ANSWER:", r.get("answer"))
        print("MARKERS:", "; ".join(resolve_markers(r.get("answer") or "", resp)))
        ev = evidence_check(q, resp)
        print(f"EVIDENCE: expected {ev['expected']} in_evidence {ev['in_evidence']} cited {ev['cited']} statute_key={ev['statute_key']}")
        print("SOURCES:", " | ".join(f"{s.get('citation')[:70]} ({s.get('method')})" for s in (resp or {}).get("sources") or []))
        print(f"VALIDATION: initial={r.get('validation_initial')} {r.get('validation_initial_codes')} final={r.get('validation_final')} "
              f"repair={'yes' if r.get('repair') else 'no'} fallback={r.get('fallback_type')} blocked={r.get('generation_blocked')}")
        le = r.get("live_eval") or {}
        print(f"LIVE EVAL: {le.get('label')} score={le.get('score')} verdict={le.get('answer_verdict')} :: {le.get('explanation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
