"""Compare two trace_retrieval.py runs question by question (no database). Writes <out_json>.

    python compare_traces.py <before_dir> <after_dir> <out_json>

Per question: final context (citation, method, tier, chars) identical or not; required-paragraph stage changes; legs
whose returned rows changed. Summarises unchanged / changed questions and lists every change."""
import json, sys
from pathlib import Path
B, A, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
res, changed = {}, []
for f in sorted(p for p in B.glob("*.json") if p.name != "summary.json"):
    b, a = json.loads(f.read_text()), json.loads((A / f.name).read_text())
    fb = [(x["citation"], x["method"], x["tier"], x["chars"]) for x in b["final_context"]]
    fa = [(x["citation"], x["method"], x["tier"], x["chars"]) for x in a["final_context"]]
    st = {k: (b["required_status"][k]["stage"], a["required_status"].get(k, {}).get("stage")) for k in b["required_status"]}
    legs = []
    for lb, la in zip(b["legs"], a["legs"]):
        rb = [(r["citation"], r["chars"]) for r in lb["rows"]]
        ra = [(r["citation"], r["chars"]) for r in la["rows"]]
        if lb["leg"] != la["leg"] or rb != ra:
            legs.append({"leg": lb["leg"], "before": rb, "after": ra})
    if len(b["legs"]) != len(a["legs"]):
        legs.append({"leg": "leg count", "before": [l["leg"] for l in b["legs"]], "after": [l["leg"] for l in a["legs"]]})
    rec = {"final_identical": fb == fa, "stage_changes": {k: v for k, v in st.items() if v[0] != v[1]}, "legs_changed": legs}
    if fb != fa:
        rec["final_before"], rec["final_after"] = fb, fa
    res[f.stem] = rec
    if fb != fa or rec["stage_changes"] or legs:
        changed.append(f.stem)
summary = {"questions": len(res), "final_context_identical": sum(r["final_identical"] for r in res.values()),
           "questions_with_any_change": changed,
           "required_stage_changes": {q: r["stage_changes"] for q, r in res.items() if r["stage_changes"]}}
OUT.write_text(json.dumps({"summary": summary, "per_question": res}, indent=1, ensure_ascii=False))
print(json.dumps(summary, indent=1, ensure_ascii=False))
