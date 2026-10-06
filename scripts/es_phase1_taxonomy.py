"""Evidence-supply Phase 1: the taxonomy of the 126 evidence-supply failures, and the subset freeze.

Combines the stage trace (`phase1_trace.jsonl`) with the depth probe (`phase1_depth.jsonl`) into one
taxonomy, ranks the mechanisms by the number of rows each explains, and writes the deterministic
diagnostic subset for Phase 4.

The subset is frozen here, before any treatment is run: a fixed stratification across the
mechanisms, each stratum filled in benchmark id order, with the per-stratum quota recorded.

    .venv/bin/python scripts/es_phase1_taxonomy.py [--subset-size 36]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# stratum -> (quota in the diagnostic subset, one-line mechanism)
STRATA = {
    "A1a_part_listing_ascii_truncated": (12, "whole-part request: the part listing is ASCII-ordered and cut at the budget, so which sections are supplied is independent of the question"),
    "A1b_guidance_took_the_budget": (6, "the governing CFR section was retrieved in the top 8 and guidance chunks filled the prompt budget instead"),
    "A2_reachable_at_greater_depth": (12, "not returned at top_k=8; the retriever does return it at top_k 24-96"),
    "B_unreachable_at_any_tested_depth": (4, "never returned at top_k up to 96: a recall problem this retriever cannot solve by depth"),
    "C_corpus_gap_or_reserved": (2, "no live rows in the snapshot, or reserved under the QMSR"),
}


def stratum_of(t: dict, depth: dict | None) -> str:
    if t["mode"] == "corpus_gap" or t["mode"] == "corpus_reserved_only":
        return "C_corpus_gap_or_reserved"
    if t["mode"] == "dropped_in_selection":
        return "A1a_part_listing_ascii_truncated" if t["trace"]["is_part_level"] else "A1b_guidance_took_the_budget"
    if t["mode"] == "not_retrieved":
        if depth and depth["first_depth_found"]:
            return "A2_reachable_at_greater_depth"
        return "B_unreachable_at_any_tested_depth"
    return f"other_{t['mode']}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trace", type=Path, default=ROOT / "artifacts/stage_b/phase1_trace.jsonl")
    ap.add_argument("--depth", type=Path, default=ROOT / "artifacts/stage_b/phase1_depth.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_b")
    args = ap.parse_args()

    traced = [json.loads(l) for l in args.trace.read_text().splitlines() if l.strip()]
    depths = {json.loads(l)["id"]: json.loads(l) for l in args.depth.read_text().splitlines() if l.strip()}

    rows = []
    for t in traced:
        s = stratum_of(t, depths.get(t["id"]))
        d = depths.get(t["id"], {})
        best = min((v["retrieved_rank"] for v in t["trace"]["per_key"].values() if v["retrieved_rank"]), default=None)
        rows.append({
            "id": t["id"], "type": t["type"], "domain": t["domain"],
            "key_sections": t["key_sections"], "stratum": s, "stage_mode": t["mode"],
            "is_part_level": t["trace"]["is_part_level"],
            "n_retrieved": t["trace"]["n_retrieved"], "n_selected": t["trace"]["n_selected"],
            "key_retrieved_rank": best,
            "first_depth_found": d.get("first_depth_found"),
            "selected_corpora": t["trace"]["selected_corpora"],
            "coverage_state": t["trace"]["coverage_state"],
        })

    counts = Counter(r["stratum"] for r in rows)
    reachable = sum(n for s, n in counts.items() if s.startswith("A"))
    taxonomy = {
        "stage": "B / evidence supply", "deliverable": "1 and 2 - taxonomy and ranked mechanisms",
        "population": "the 126 Stage A EVIDENCE_SUPPLY rows", "rows": len(rows),
        "mechanisms_ranked_by_rows": [
            {"stratum": s, "rows": n, "pct_of_126": round(100 * n / len(rows), 1),
             "mechanism": STRATA.get(s, ("", "unclassified"))[1]}
            for s, n in counts.most_common()
        ],
        "headline": {
            "governing_provision_is_reachable_but_does_not_reach_the_prompt": reachable,
            "pct": round(100 * reachable / len(rows), 1),
            "unreachable_by_this_retriever": counts["B_unreachable_at_any_tested_depth"],
            "corpus_gap": counts["C_corpus_gap_or_reserved"],
        },
    }
    (args.out / "phase1_taxonomy.json").write_text(json.dumps(taxonomy, indent=2) + "\n")
    (args.out / "phase1_rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    # ---- the frozen diagnostic subset ---------------------------------------------------------
    subset, quotas = [], {}
    for s, (quota, _) in STRATA.items():
        pool = sorted([r for r in rows if r["stratum"] == s], key=lambda r: r["id"])
        take = pool[:quota]
        quotas[s] = {"available": len(pool), "quota": quota, "taken": len(take), "ids": [r["id"] for r in take]}
        subset += take
    freeze = {
        "frozen_before_any_treatment_run": True,
        "selection_rule": "fixed per-stratum quota, filled in ascending benchmark id order; no treatment output consulted",
        "size": len(subset),
        "strata": quotas,
        "ids": sorted(r["id"] for r in subset),
    }
    (args.out / "subset_frozen.json").write_text(json.dumps(freeze, indent=2) + "\n")

    print(json.dumps(taxonomy, indent=2))
    print(f"\nfrozen diagnostic subset: {len(subset)} rows")
    for s, q in quotas.items():
        print(f"  {q['taken']:3}/{q['available']:3}  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
