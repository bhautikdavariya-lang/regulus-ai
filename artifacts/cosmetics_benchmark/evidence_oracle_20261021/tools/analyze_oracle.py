"""Merge blind scores, apply recorded adjudications, un-blind, and apply the pre-registered interpretation.

    python analyze_oracle.py <experiment_dir> <workflow_result.json> [--disputes-only]

--disputes-only prints the items a verifier disputed (before un-blinding), for adjudication into
scoring/adjudication.json ({item_id: {"final": {...fields...}, "reason": "..."}}). Without it: un-blinds through
scoring/blind_map.json, maps scores to categories with the Step 6 category() (verbatim), compares Condition A with
its Step 6 blind verdict, classifies each question and applies the decision rules fixed in PREREGISTRATION.md.
Writes scoring/results.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

E = Path(sys.argv[1]).resolve()
WF = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
ROOT = E.parents[2]
PASS, PPASS, PFAIL, FAIL, NEV = "PASS", "PARTIALLY PASS", "PARTIALLY FAIL", "FAIL", "NOT EVALUABLE"
ORDER = {FAIL: 0, PFAIL: 1, PPASS: 2, PASS: 3}
CONTROLS = {"COS-710.5-Q1", "COS-70.50-Q2", "COS-70.3-Q3"}
FIELDS = ("ce", "fab", "sub", "comp", "scope", "not_evaluable", "decline_appropriate", "citation_support", "conditions_exceptions")


def category(v):   # verbatim from the 20 Oct / Step 6 build_workbook.py, plus NOT EVALUABLE
    if v.get("not_evaluable"):
        return NEV
    if v["sub"] == 0:
        return FAIL
    if v["sub"] == 1:
        return PFAIL
    if v["fab"] == 1 or v["scope"] == 0 or v["comp"] == 0:
        return PFAIL
    if v["comp"] == 2 and v["ce"] == 1:
        return PASS
    return PPASS


items = {i["item_id"]: i for i in WF["items"]}
disputes = {}
for v in WF["verdicts"]:
    for x in v["verdicts"]:
        if not x["agree"]:
            disputes.setdefault(x["item_id"], []).append({"lens": v["lens"][:40], "corrected": x["corrected"], "reason": x["reason"]})

if "--disputes-only" in sys.argv:
    print(f"{len(items)} items scored; {len(disputes)} disputed")
    for iid, ds in sorted(disputes.items()):
        s = items[iid]
        print(f"\n== {iid}  scored: " + json.dumps({k: s[k] for k in FIELDS}))
        print(f"   why: {s['why']}")
        for d in ds:
            print(f"   DISPUTE [{d['lens']}] corrected={d['corrected']} :: {d['reason']}")
    sys.exit(0)

adj_path = E / "scoring/adjudication.json"
adj = json.loads(adj_path.read_text(encoding="utf-8")) if adj_path.exists() else {}
missing = sorted(set(disputes) - set(adj))
assert not missing, f"disputed items not adjudicated: {missing}"
final = {}
for iid, s in items.items():
    f = {k: s[k] for k in FIELDS}
    override = dict(adj.get(iid, {}).get("final", {}))
    checklist = override.pop("checklist", s["checklist"])
    f.update(override)
    final[iid] = {**f, "category": category(f), "checklist": checklist, "critical_errors": s["critical_errors"],
                  "declined": s["declined"], "why": s["why"], "adjudicated": iid in adj}

blind = json.loads((E / "scoring/blind_map.json").read_text(encoding="utf-8"))
step6 = json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/scoring/analysis.json").read_text(encoding="utf-8"))
packets = json.loads((E / "packets/packets.json").read_text(encoding="utf-8"))["questions"]
b_rec = {r["qid"]: r for r in (json.loads(l) for l in (E / "condition_b.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
coverage = {i: c["cov"] for i, c in json.loads((ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/evidence/classification.json").read_text()).items()}
per = {}
for iid, cond in blind.items():
    per.setdefault(iid.split("#")[0], {})[cond] = {**final[iid], "item": iid}
rows = {}
for q, d in per.items():
    a, b = d["A"], d["B"]
    a6 = step6["verdicts"][q]["A"]["category"]
    if b["category"] == NEV or a["category"] == NEV:
        cls = "inconclusive"
    elif ORDER[b["category"]] > ORDER[a["category"]] and coverage[q] in ("none", "part"):
        cls = "evidence-sensitive improvement"
    elif b["sub"] == 2 and (b["ce"] == 0 or (b_rec[q].get("repair") and b["category"] in (PFAIL, FAIL))):
        cls = "citation or validation problem"
    elif b["category"] in (FAIL, PFAIL):
        cls = "generation failure persists"
    elif ORDER[b["category"]] > ORDER[a["category"]]:
        cls = "improvement (A already had the evidence)"
    else:
        cls = "acceptable in both"
    rows[q] = {"A": a["category"], "A_step6": a6, "A_consistent_with_step6": a["category"] == a6, "B": b["category"],
               "A_coverage": coverage[q], "control": q in CONTROLS, "class": cls,
               "A_scores": {k: a[k] for k in FIELDS}, "B_scores": {k: b[k] for k in FIELDS},
               "A_declined": a["declined"], "B_declined": b["declined"], "A_why": a["why"], "B_why": b["why"],
               "B_checklist": b["checklist"], "B_critical": b["critical_errors"], "A_critical": a["critical_errors"]}
non_controls = [q for q in rows if not rows[q]["control"]]
improved = [q for q in non_controls if rows[q]["A"] in (FAIL, PFAIL) and rows[q]["B"] in (PASS, PPASS)]
persist = [q for q in non_controls if rows[q]["B"] in (FAIL, PFAIL)]
control_drops = [q for q in CONTROLS if ORDER.get(rows[q]["B"], -1) < ORDER.get(rows[q]["A"], -1)]
if len(improved) >= 3 and not control_drops:
    result = "A (evidence materially improves answers: prioritise retrieval/context selection)"
elif len(improved) <= 1 and len(persist) >= 5:
    result = "B (generation errors persist: prioritise answer generation)"
else:
    result = "C (mixed)"
dims = {}
for cond in ("A", "B"):
    s = [per[q][cond] for q in per]
    dims[cond] = {"categories": dict(Counter(x["category"] for x in s)), "sub": dict(Counter(x["sub"] for x in s)),
                  "comp": dict(Counter(x["comp"] for x in s)), "ce": sum(x["ce"] for x in s), "fab": sum(x["fab"] for x in s),
                  "citation_support": dict(Counter(x["citation_support"] for x in s)),
                  "conditions_exceptions": dict(Counter(x["conditions_exceptions"] for x in s)),
                  "declined": sum(x["declined"] for x in s),
                  "decline_appropriate": dict(Counter(x["decline_appropriate"] for x in s if x["declined"]))}
out = {"result": result, "improved": improved, "persist_with_sufficient_packet": persist, "control_drops": sorted(control_drops),
       "classes": dict(Counter(r["class"] for r in rows.values())), "dimensions": dims,
       "A_agreement_with_step6": sum(r["A_consistent_with_step6"] for r in rows.values()), "questions": rows,
       "disputed_items": sorted(disputes), "adjudications": adj}
(E / "scoring/results.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("result", "improved", "persist_with_sufficient_packet", "control_drops", "classes", "A_agreement_with_step6")}, indent=1))
for q, r in rows.items():
    print(f"{q:16} A={r['A']:15} (step6 {r['A_step6']:15}) B={r['B']:15} cov={r['A_coverage']:5} {r['class']}")
print(json.dumps(dims, indent=1))
