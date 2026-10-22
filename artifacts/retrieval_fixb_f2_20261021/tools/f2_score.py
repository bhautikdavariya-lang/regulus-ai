"""Score the F2 experiment against PREREGISTRATION.md C1–C7 (no database, no model) and build the blind pool of removed
regulation rows (C4). Writes evaluation.json, pool_blind.json, pool_key.json.

    python f2_score.py <dir> <352_run_id>
"""
import json
import random
import sys
from pathlib import Path

D = Path(sys.argv[1]).resolve()
ROOT = D.parents[1]
RUN = sys.argv[2]
E = json.loads((D / "eval" / "eval100.json").read_text())["questions"]
load = lambda p: {json.loads(l)["id"]: json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()}
B352 = load(ROOT / "data/evaluation/results/retrieval_baseline_20261021T102326Z_16fa796d/per_question.jsonl")
W352 = load(ROOT / f"data/evaluation/results/{RUN}/per_question.jsonl")
PROD = json.loads((ROOT / "artifacts/retrieval_selection_d_20261021/candidates.json").read_text())["questions"]
sig = lambda srcs: [(s["citation"], s["corpus"], s["chars"]) for s in srcs]

gen = {q: r for q, r in E.items() if r["general"]}
gained, lost, cand_gained, g_removed, e_removed, added_rows, kept_rows = [], [], [], [], [], [], []
for q, r in E.items():
    for lab, v in r["wide"]["required"].items():
        b = r["base"]["required"][lab]
        if v["in_context"] and not b["in_context"]: gained.append(f"{q} {lab}")
        if b["in_context"] and not v["in_context"]: lost.append(f"{q} {lab}")
        if v["candidate"] and not b["candidate"]: cand_gained.append(f"{q} {lab}")
    bk = {s["key"]: s for s in r["base"]["sources"]}; wk = {s["key"]: s for s in r["wide"]["sources"]}
    for k, s in bk.items():
        if k not in wk:
            (g_removed if s["corpus"] != "ecfr" else e_removed).append({"qid": q, **s})
        elif s["corpus"] == "ecfr":
            kept_rows.append({"qid": q, **s})
    added_rows += [{"qid": q, **s} for k, s in wk.items() if k not in bk and s["corpus"] == "ecfr"]
cnt = lambda c, f: sum(v[f] for r in gen.values() for v in r[c]["required"].values())
named = {q: r for q, r in E.items() if not r["general"]}
c5 = [q for q, r in named.items() if sig(r["base"]["sources"]) != sig(r["wide"]["sources"])]
over = [q for q, r in E.items() if not any(s["tier"] == "exact" for s in r["wide"]["sources"])
        and (len(r["wide"]["sources"]) > 8 or (r["wide"]["total_chars"] or 0) > 3600)]
c7_diff = [q for q, r in E.items() if sig(r["base"]["sources"]) != sig(PROD[q]["base"]["sources"])]
t_lost, t_gained = [], []
for k, a in B352.items():
    ta = {x["target"]: x for x in a.get("targets") or []}; tb = {x["target"]: x for x in W352[k].get("targets") or []}
    t_lost += [(k, n) for n, x in ta.items() if x.get("in_context") and not tb.get(n, {}).get("in_context")]
    t_gained += [(k, n) for n, x in ta.items() if not x.get("in_context") and tb.get(n, {}).get("in_context")]
def by_class(recs):
    out = {}
    for r in recs.values():
        for x in r.get("targets") or []:
            if x["target"].startswith("21 CFR"):
                c = r.get("question_class"); out.setdefault(c, 0); out[c] += bool(x.get("in_context"))
    return out
ev = {"C1": {"base": cnt("base", "in_context"), "wide": cnt("wide", "in_context"), "candidates_base": cnt("base", "candidate"),
             "candidates_wide": cnt("wide", "candidate"), "gained": gained, "lost": lost, "candidate_gained": cand_gained,
             "pass": len(gained) >= 3 and not lost},
      "C2": {"gained": t_gained, "lost": t_lost, "by_class_base": by_class(B352), "by_class_wide": by_class(W352)},
      "C3": {"guidance_removed": [f"{x['qid']} {x['citation'][:80]}" for x in g_removed], "pass": not g_removed},
      "C4_rows_removed": [{"qid": x["qid"], "citation": x["citation"], "chars": x["chars"]} for x in e_removed],
      "C5": {"changed": c5, "pass": not c5},
      "C6": {"over": over, "max_total_general": max((r["wide"]["total_chars"] or 0) for r in gen.values()), "pass": not over},
      "C7_contexts": {"switch_off_differs_from_production": c7_diff, "pass": not c7_diff},
      "chars": {c: {"ecfr": sum(s["chars"] for r in gen.values() for s in r[c]["sources"] if s["corpus"] == "ecfr"),
                    "guidance": sum(s["chars"] for r in gen.values() for s in r[c]["sources"] if s["corpus"] != "ecfr")} for c in ("base", "wide")}}
bc, wc = ev["C2"]["by_class_base"], ev["C2"]["by_class_wide"]
ev["C2"]["pass"] = not t_lost and all(wc.get(k, 0) >= v for k, v in bc.items())
# C4 blind pool: removed rows + equal numbers of added and kept rows as fillers
rng = random.Random(20261021)
n = len(e_removed)
fill = rng.sample(added_rows, min(n, len(added_rows))) + rng.sample(kept_rows, min(n, len(kept_rows)))
items = [("removed", x) for x in e_removed] + [("filler", x) for x in fill]
rng.shuffle(items)
blind, key = [], {}
for i, (role, x) in enumerate(items, 1):
    iid = f"R{i:03d}"
    blind.append({"item": iid, "question": E[x["qid"]]["question"], "citation": x["citation"], "passage": x["text"]})
    key[iid] = {"role": role, "qid": x["qid"], "citation": x["citation"]}
(D / "pool_blind.json").write_text(json.dumps(blind, indent=1, ensure_ascii=False))
(D / "pool_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False))
(D / "evaluation.json").write_text(json.dumps(ev, indent=1, ensure_ascii=False))
print(json.dumps({k: (v if k in ("chars",) else {kk: vv for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in ev.items()}, indent=1, ensure_ascii=False)[:5000])
print("pool items", len(blind), "removed", n)
