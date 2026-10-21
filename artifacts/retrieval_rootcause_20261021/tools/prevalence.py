"""Prevalence of each traced loss mechanism over the 100 cosmetics questions, from trace_retrieval.py output only.

    python prevalence.py <traces_dir> <out_json>

No database, no model: reads <traces_dir>/<ID>.json and writes <out_json>. Each required eCFR paragraph (from the
verified key) that is not in the final context is assigned the first point on its path where it was lost:
  D  selection: returned and in the registry, then dropped or not selected;
  B  paragraph: never returned, but another paragraph of its section was returned by some leg;
  A  operator: never returned, its section reached by no leg, the question's AND query contains an OR branch, and
     that query returned at least primary_min_results eCFR rows, so section coverage did not run;
  C  section: never returned and its section reached by no leg (section coverage ran, or the gate was closed for a
     reason other than A);
  S  absent from the source store.
Questions that name a provision (exact path) are counted separately.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

TR, OUT = Path(sys.argv[1]), Path(sys.argv[2])


def sec_of(label):
    import re
    m = re.match(r"21 CFR (\d+\.\d+[a-z]?)", label or "")
    return m.group(1) if m else None


rows, per_q = [], {}
ctx = Counter()
ecfr_dropped_while_guidance_selected = 0
for f in sorted([p for p in TR.glob("*.json") if p.name != "summary.json"]):
    d = json.loads(f.read_text(encoding="utf-8"))
    g = d["gates"]
    general = not g["requirements"] and g["docket"] is None
    fte = next((c for c in d["legs"] if c["leg"] == "full_text_ecfr"), None)
    and_or = bool(fte and fte["tsquery"] and "|" in fte["tsquery"])
    reached_any = {sec_of(r["citation"]) for c in d["legs"] for r in c["rows"]}
    reached_rc1 = {sec_of(r["citation"]) for c in d["legs"] if c["leg"] == "section_coverage_ecfr" for r in c["rows"]}
    if general:
        for s in d["final_context"]:
            ctx["guidance" if not s["citation"].startswith("21 CFR") else "ecfr:" + s["method"]] += s["chars"]
        sel_guid = any(not s["citation"].startswith("21 CFR") for s in d["final_context"])
        dropped_ecfr = [c for c, why in d["selection"]["dropped"] if c.startswith("21 CFR")]
        if sel_guid and dropped_ecfr:
            ecfr_dropped_while_guidance_selected += 1
    q = {"general": general, "and_has_or_branch": and_or, "ecfr_and_rows": g["ecfr_all_words_rows"],
         "section_coverage_ran": "section_coverage_ecfr" in g["legs_called"], "labels": {}}
    for lab, st in d["required_status"].items():
        stage = st["stage"]
        sec = sec_of(lab)
        if stage == "in final context":
            mech = "OK"
        elif stage in ("dropped at selection", "in registry, not selected"):
            mech = "D"
        elif stage == "absent from the source store":
            mech = "S"
        elif sec in reached_any:
            mech = "B"
        elif general and and_or and g["ecfr_all_words_rows"] >= g["primary_min_results"]:
            mech = "A"
        else:
            mech = "C"
        q["labels"][lab] = {"stage": stage, "mechanism": mech, "section_reached_by_any_leg": sec in reached_any,
                            "section_reached_by_section_coverage": sec in reached_rc1, "drop_reason": st.get("drop_reason")}
        rows.append((d["id"], general, lab, mech))
    per_q[d["id"]] = q

summary = {}
for kind in (True, False):
    sub = [r for r in rows if r[1] is kind]
    qs = {k: v for k, v in per_q.items() if v["general"] is kind}
    with_key = {k: v for k, v in qs.items() if v["labels"]}
    full = sum(1 for v in with_key.values() if all(x["mechanism"] == "OK" for x in v["labels"].values()))
    none = sum(1 for v in with_key.values() if all(x["mechanism"] != "OK" for x in v["labels"].values()))
    first_loss = Counter()
    for v in with_key.values():
        mechs = {x["mechanism"] for x in v["labels"].values()} - {"OK"}
        for m in mechs:
            first_loss[m] += 1
    summary["general" if kind else "names_a_provision"] = {
        "questions": len(qs), "questions_with_ecfr_key": len(with_key),
        "all_required_in_context": full, "none_required_in_context": none,
        "required_paragraphs": len(sub), "paragraph_mechanism_counts": dict(Counter(r[3] for r in sub)),
        "questions_affected_by_mechanism": dict(first_loss),
        "and_query_has_or_branch": sum(1 for v in qs.values() if v["and_has_or_branch"]),
        "and_or_branch_and_rows_ge_3": sum(1 for v in qs.values() if v["and_has_or_branch"] and v["ecfr_and_rows"] >= 3),
        "section_coverage_ran": sum(1 for v in qs.values() if v["section_coverage_ran"]),
    }
summary["general"]["final_context_chars_by_source"] = dict(ctx)
summary["general"]["questions_with_ecfr_rows_dropped_while_guidance_selected"] = ecfr_dropped_while_guidance_selected
OUT.write_text(json.dumps({"summary": summary, "per_question": per_q}, indent=1), encoding="utf-8")
print(json.dumps(summary, indent=1))
