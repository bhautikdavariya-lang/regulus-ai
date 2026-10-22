"""Score the capacity comparison against PREREGISTRATION.md K1–K5 (no database, no model). Writes evaluation.json."""
import json, statistics as st
from pathlib import Path
D = Path(__file__).resolve().parents[1]
ROOT = D.parents[1]
raw = json.loads((D / "compare_raw.json").read_text())
Q = raw["q100"]
def load(p): return {json.loads(l)["id"]: json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()}
base352 = load(ROOT / "data/evaluation/results/retrieval_baseline_20261021T102326Z_16fa796d/per_question.jsonl")
out = {}
for c in ("T4800", "T6000", "H3600"):
    gained, lost, g_removed, order_bad, growth = [], [], [], [], []
    for q, r in Q.items():
        for lab, on in r[c]["required"].items():
            b = r["base"]["required"][lab]
            if on and not b: gained.append(f"{q} {lab}")
            if b and not on: lost.append(f"{q} {lab}")
        bk = [s["key"] for s in r["base"]["sources"]]; ck = [s["key"] for s in r[c]["sources"]]
        g_removed += [f"{q} {s['citation'][:70]}" for s in r["base"]["sources"] if s["corpus"] != "ecfr" and s["key"] not in ck]
        if [k for k in ck if k in bk] != [k for k in bk if k in ck] or not set(bk) <= set(ck):
            order_bad.append(q)
        growth.append((r[c]["total_chars"] or 0) - (r["base"]["total_chars"] or 0))
    rec = load(D / "runs_352" / f"{c}.jsonl")
    t_lost, t_gained = [], []
    for k, a in base352.items():
        ta = {t["target"]: t["in_context"] for t in a.get("targets") or []}
        tb = {t["target"]: t["in_context"] for t in rec[k].get("targets") or []}
        t_lost += [(k, t) for t in ta if ta[t] and not tb.get(t)]
        t_gained += [(k, t) for t in ta if not ta[t] and tb.get(t)]
    s352 = raw["summary_352"][c]
    max_growth = max(growth)
    added = {"ecfr": 0, "guidance": 0}
    for r in Q.values():
        bk = {s["key"] for s in r["base"]["sources"]}
        for s in r[c]["sources"]:
            if s["key"] not in bk: added["ecfr" if s["corpus"] == "ecfr" else "guidance"] += 1
    k5_s = max_growth / 4 * 2.155 / 1000
    out[c] = {"K1_required": {"gained": gained, "lost": lost, "pass": not lost},
              "K2_352": {"targets_gained": t_gained, "targets_lost": t_lost, "summary": s352.get("by_class") or {k: s352[k] for k in list(s352)[:6]},
                         "pass": not t_lost},
              "K3_guidance_removed": {"removed": g_removed, "pass": not g_removed},
              "K4_superset_same_order": {"violations": order_bad, "pass": not order_bad},
              "K5_cost": {"budget_chars_growth_median": st.median(growth), "max": max_growth, "est_added_prefill_s_max": round(k5_s, 2),
                          "pass": k5_s <= 1.5},
              "added_sources_100": added}
    out[c]["eligible"] = all(v["pass"] for k, v in out[c].items() if k.startswith("K"))
(D / "evaluation.json").write_text(json.dumps(out, indent=1))
for c, v in out.items():
    print(c, "eligible" if v["eligible"] else "NOT eligible", "| req +", len(v["K1_required"]["gained"]), "-", len(v["K1_required"]["lost"]),
          "| 352 targets +", len(v["K2_352"]["targets_gained"]), "-", len(v["K2_352"]["targets_lost"]), "| guidance removed", len(v["K3_guidance_removed"]["removed"]),
          "| order viol", len(v["K4_superset_same_order"]["violations"]), "| prefill max +", v["K5_cost"]["est_added_prefill_s_max"], "s | added", v["added_sources_100"])
