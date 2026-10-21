"""Compare a cosmetics retrieval replay with the Step 6 arm A baseline (or with another replay).

    python compare_cosmetics.py <replay.jsonl> [<other_replay.jsonl>]

Without a second file, the reference is Step 6 arm A (Qwen3-1.7B, switch off): each response's prompt sources as
(citation, method, tier, text) and its selection drops as (citation, reason). Prints the differing question ids.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ARM_A = ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off"


def load_replay(p):
    return {r["id"]: r for r in (json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip())}


def load_arm_a(ids):
    out = {}
    for i in ids:
        r = json.loads((ARM_A / "responses" / f"{i}.json").read_text(encoding="utf-8"))
        out[i] = {"sources": [[s["citation"], s.get("method"), s.get("tier"), s.get("text")] for s in r.get("sources") or []],
                  "dropped": [[d.get("citation"), d.get("reason")] for d in (r.get("selection") or {}).get("dropped") or []]}
    return out


def main() -> int:
    a = load_replay(sys.argv[1])
    b = load_replay(sys.argv[2]) if len(sys.argv) > 2 else load_arm_a(a)
    src = [i for i in a if a[i]["sources"] != b[i]["sources"]]
    drp = [i for i in a if a[i]["dropped"] != b[i]["dropped"]]
    print(f"questions {len(a)}: identical prompt sources {len(a) - len(src)}, identical drops {len(a) - len(drp)}")
    print(f"differing sources: {src}")
    print(f"differing drops: {drp}")
    return 0 if not src and not drp else 1


if __name__ == "__main__":
    raise SystemExit(main())
