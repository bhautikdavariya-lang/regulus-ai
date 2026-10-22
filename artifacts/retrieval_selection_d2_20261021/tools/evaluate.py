"""Evaluate the candidate against PREREGISTRATION.md (no database, no model). Reads candidates.json and, when present,
relevance.json (adjudicated labels joined to pool_key.json). Writes evaluation.json.

    python evaluate.py <dir>
"""
import json
import sys
from collections import Counter
from pathlib import Path

D = Path(sys.argv[1]).resolve()
C = json.loads((D / "candidates.json").read_text())["questions"]
rel = json.loads((D / "relevance.json").read_text()) if (D / "relevance.json").exists() else None


def req_count(r, cond):
    return sum(r[cond]["required_in_context"].values())


gen = {q: r for q, r in C.items() if r["general"]}
named = {q: r for q, r in C.items() if not r["general"]}
gained, lost = [], []
for q, r in gen.items():
    for lab, on in r["c2"]["required_in_context"].items():
        before = r["base"]["required_in_context"][lab]
        if on and not before:
            gained.append(f"{q} {lab}")
        if before and not on:
            lost.append(f"{q} {lab}")
a1 = {"base": sum(req_count(r, "base") for r in gen.values()), "c2": sum(req_count(r, "c2") for r in gen.values()),
      "of": sum(len(r["base"]["required_in_context"]) for r in gen.values()), "gained": gained, "lost": lost}
a1["pass"] = a1["c2"] - a1["base"] >= 3 and not lost
targets = {"COS-70.55-Q1": "21 CFR 70.55", "COS-71.15-Q2": "21 CFR 71.15(b)", "COS-701.3-Q1": "21 CFR 701.3(b)"}
a2 = {f"{q} {lab}": C[q]["c2"]["required_in_context"].get(lab) for q, lab in targets.items()}
sig = lambda r, c: [(s["citation"], s["corpus"], s["chars"]) for s in r[c]["sources"]]
a4 = {"named_questions": len(named), "identical": sum(1 for r in named.values() if sig(r, "base") == sig(r, "c2")),
      "changed": [q for q, r in named.items() if sig(r, "base") != sig(r, "c2")]}
a4["pass"] = not a4["changed"]
# the soft limits bound optional evidence; required (EXACT) evidence may exceed them up to the hard ceilings by design
no_required = lambda r, c: not any(s["tier"] == "exact" for s in r[c]["sources"])
over = [q for q, r in C.items() if no_required(r, "c2") and (r["c2"]["n_sources"] > 8 or (r["c2"]["total_chars"] or 0) > 3600)]
with_required_over = [q for q, r in C.items() if not no_required(r, "c2") and (r["c2"]["n_sources"] > 8 or (r["c2"]["total_chars"] or 0) > 3600)]
a7 = {"over_soft_limits_without_required": over, "general_flagged": sum(1 for r in gen.values() if r["c2"]["diag_order"] == "ecfr_discovery_first_guidance_floor"),
      "required_above_soft_limits_same_as_base": {q: sig(C[q], "base") == sig(C[q], "c2") for q in with_required_over},
      "max_total_chars_general": max((r["c2"]["total_chars"] or 0) for r in gen.values()),
      "max_sources_general": max(r["c2"]["n_sources"] for r in gen.values()),
      "pass": not over}
changed_q = [q for q, r in C.items() if sig(r, "base") != sig(r, "c2")]
ecfr_removed = Counter()
non_required_ecfr_removed = []
for q in changed_q:
    b = {s["key"] for s in C[q]["base"]["sources"] if s["corpus"] == "ecfr"}
    v = {s["key"] for s in C[q]["c2"]["sources"] if s["corpus"] == "ecfr"}
    for k in b - v:
        non_required_ecfr_removed.append(f"{q} {k}")
chars = {c: {"ecfr": sum(s["chars"] for r in gen.values() for s in r[c]["sources"] if s["corpus"] == "ecfr"),
             "guidance": sum(s["chars"] for r in gen.values() for s in r[c]["sources"] if s["corpus"] != "ecfr"),
             "guidance_passages": sum(1 for r in gen.values() for s in r[c]["sources"] if s["corpus"] != "ecfr")} for c in ("base", "c2")}
out = {"A1_required": a1, "A2_targets": {**a2, "pass": all(a2.values())}, "A4_named_identical": a4, "A7_budget": a7,
       "questions_with_changed_context": changed_q, "ecfr_rows_removed_by_c2": non_required_ecfr_removed, "chars": chars}
if rel is not None:
    removed = {i: v for i, v in rel.items() if "removed_by_c2" in v["roles"]}
    added = {i: v for i, v in rel.items() if "added_by_c2" in v["roles"]}
    fill = {i: v for i, v in rel.items() if v["roles"] == ["filler_kept_by_c2"]}
    out["A3_relevant_guidance"] = {
        "removed_by_label": dict(Counter(v["label"] for v in removed.values())),
        "added_by_label": dict(Counter(v["label"] for v in added.values())),
        "fillers_by_label": dict(Counter(v["label"] for v in fill.values())),
        "removed_R2": sorted(f"{v['qid']} | {v['title'][:90]}" for v in removed.values() if v["label"] == "R2"),
        "removed_R1": sorted(f"{v['qid']} | {v['title'][:90]}" for v in removed.values() if v["label"] == "R1"),
        "pass": not any(v["label"] == "R2" for v in removed.values())}
(D / "evaluation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(json.dumps(out, indent=1, ensure_ascii=False)[:6000])
