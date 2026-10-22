"""Refined first-loss classes from prevalence.json + rank_check.json (no database). Writes <out_json>.

    python refine_classes.py <dir>

A   gate closed by a standalone "or" (unchanged);
B1  section ranked 1-4 and reached by the coverage leg, paragraph beyond the 2-rows-per-section cap or matching no lexeme;
B2  section ranked 1-4 by the coverage weighting but cut out entirely by the 4-row total limit;
C   section ranked > 4 (or matching no question lexeme): a ranking loss;
D1  dropped at the soft budget; D2 rejected by the usefulness filter.
The spurious label 21 CFR 740.11(i) (a mis-parsed "(b)(2)(i)-(iv)") is excluded.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

D = Path(sys.argv[1])
P = json.loads((D / "prevalence.json").read_text())["per_question"]
K = json.loads((D / "rank_check.json").read_text())["per_question"]
labels, qs = {}, defaultdict(set)
for q, v in P.items():
    if not v["general"]:
        continue
    for lab, x in v["labels"].items():
        if lab == "21 CFR 740.11(i)":
            continue
        m = x["mechanism"]
        rk = K.get(q, {}).get("labels", {}).get(lab, {})
        rank = rk.get("section_rank")
        if m in ("B", "C"):
            if rank is not None and rank <= 4:
                m = "B1" if x["section_reached_by_section_coverage"] else "B2"
            else:
                m = "C"
        elif m == "D":
            m = "D2" if x["drop_reason"] == "filtered" else "D1"
        labels[f"{q} {lab}"] = {"class": m, "section_rank": rank, "lexeme": rk.get("paragraph_matches_a_lexeme")}
        if m != "OK":
            qs[m].add(q)
out = {"paragraph_counts": dict(Counter(v["class"] for v in labels.values())),
       "question_counts": {k: len(v) for k, v in qs.items()}, "total": len(labels),
       "B1_without_lexeme": sorted(k for k, v in labels.items() if v["class"] == "B1" and not v["lexeme"]),
       "B2": sorted(k for k, v in labels.items() if v["class"] == "B2"),
       "C_best_rank_per_question": dict(Counter(
           (lambda r: "none" if r is None else "5-8" if r <= 8 else "9-20" if r <= 20 else "21-100" if r <= 100 else ">100")(
               min((labels[f"{q} {l}"]["section_rank"] or 10**9 for l in P[q]["labels"] if f"{q} {l}" in labels and labels[f"{q} {l}"]["class"] == "C"))
               if any(labels.get(f"{q} {l}", {}).get("class") == "C" for l in P[q]["labels"]) else None) for q in qs["C"])),
       "labels": labels}
(D / "refined_classes.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: v for k, v in out.items() if k != "labels"}, indent=1))
