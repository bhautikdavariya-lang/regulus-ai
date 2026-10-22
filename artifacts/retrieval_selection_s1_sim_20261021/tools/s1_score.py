"""Score the S1 simulation against PREREGISTRATION.md E1–E6 (no database, no model); build the blind pools of removed
passages that have no reusable label (E3). Writes evaluation.json, pools/<arm>_<corpus>_{blind,key}.json, reused_labels.json.

    python s1_score.py <dir>
"""
import json
import random
import re
import sys
from pathlib import Path

D = Path(sys.argv[1]).resolve()
ROOT = D.parents[1]
EV = json.loads((D / "eval" / "eval100.json").read_text())
E = EV["questions"]
load = lambda p: {json.loads(l)["id"]: json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()}
B352 = load(ROOT / "data/evaluation/results/retrieval_baseline_20261021T102326Z_16fa796d/per_question.jsonl")
R352 = {c: load(D / "eval" / "runs_352" / f"{c}.jsonl") for c in ("base", "S1", "S1F2")}
F2E = json.loads((ROOT / "artifacts/retrieval_fixb_f2_20261021/eval/eval100.json").read_text())["questions"]
ARMS = ("S1", "S1F2")
sig = lambda srcs: [(s["key"], s["citation"], s["corpus"], s["chars"]) for s in srcs]
sigt = lambda srcs: [(s["key"], s["chars"], s["truncated"], s["text"]) for s in srcs]

# ---- reusable labels: identical question, key and text
LBL = {}
d_key = json.loads((ROOT / "artifacts/retrieval_selection_d_20261021/pool_key.json").read_text())
d_rel = json.loads((ROOT / "artifacts/retrieval_selection_d_20261021/relevance.json").read_text())
for b in json.loads((ROOT / "artifacts/retrieval_selection_d_20261021/pool_blind.json").read_text()):
    LBL[(b["question"], d_key[b["item"]]["key"], b["passage"])] = ("exp D " + b["item"], d_rel[b["item"]]["label"])
f_key = json.loads((ROOT / "artifacts/retrieval_fixb_f2_20261021/pool_key.json").read_text())
f_jud = json.loads((ROOT / "artifacts/retrieval_fixb_f2_20261021/judgements.json").read_text())["items"]
for b in json.loads((ROOT / "artifacts/retrieval_fixb_f2_20261021/pool_blind.json").read_text()):
    qid = f_key[b["item"]]["qid"]
    keys = {s["key"] for c in ("base", "wide") for s in F2E[qid][c]["sources"] if s["citation"] == b["citation"] and s["text"] == b["passage"]}
    for k in keys:
        LBL[(b["question"], k, b["passage"])] = ("F2 " + b["item"], f_jud[b["item"]]["final"])

# ---- contexts per question: (question, base sources, arm sources, is_general) for the 100 and the 352
def contexts(arm):
    out = {}
    for q, r in E.items():
        out[q] = (r["question"], r["base"]["sources"], r[arm]["sources"], r["base"]["general"], r["general_plan"])
    for k, a in R352["base"].items():
        b = R352[arm][k]
        if a.get("s1_context") and b.get("s1_context"):
            out[k] = (a["question"], a["s1_context"]["sources"], b["s1_context"]["sources"], a["s1_context"]["general"], None)
    return out


def has_cit(srcs, sec, para=None):
    for s in srcs:
        m = re.match(r"21 CFR (\S+?)(\(.*)?$", s["citation"])
        if m and m.group(1) == sec and (para is None or (m.group(2) or "").startswith(para)):
            return True
    return False


has_doc = lambda srcs, docket: any(docket in s["citation"] for s in srcs)
has_key = lambda srcs, key: any(s["key"] == key for s in srcs)
G129 = d_key["G129"]["key"]


def ctx100(q, c):
    return E[q][c]["sources"]


def ctx352(q, c):
    return (R352[c][q].get("s1_context") or {}).get("sources") or []


E4 = [  # (case, qid, check(sources)) - from the design report §6, unchanged
    ("COS-74.2602a-Q1 keeps 81.30(i)", "COS-74.2602a-Q1", ctx100, lambda s: has_cit(s, "81.30", "(i)")),
    ("COS-701.12-Q2 keeps the OTC-drug Q&A passage (FDA-2007-D-0429)", "COS-701.12-Q2", ctx100, lambda s: has_key(s, G129)),
    ("X-001 keeps 4.1", "X-001", ctx352, lambda s: has_cit(s, "4.1")),
    ("retrieval-031 keeps FDA-2007-D-0372", "retrieval-031", ctx352, lambda s: has_doc(s, "FDA-2007-D-0372")),
    ("retrieval-034 keeps FDA-2017-D-6821", "retrieval-034", ctx352, lambda s: has_doc(s, "FDA-2017-D-6821")),
    ("retrieval-039 keeps FDA-2013-D-0114", "retrieval-039", ctx352, lambda s: has_doc(s, "FDA-2013-D-0114")),
    ("COS-740.11-Q2 keeps 740.11(b)(1)", "COS-740.11-Q2", ctx100, lambda s: has_cit(s, "740.11", "(b)(1)")),
    ("COS-70.3-Q1 keeps 70.3(f)", "COS-70.3-Q1", ctx100, lambda s: has_cit(s, "70.3", "(f)")),
    ("COS-740.12-Q1 keeps 740.12(b)", "COS-740.12-Q1", ctx100, lambda s: has_cit(s, "740.12", "(b)")),
]


def by_class(recs):
    out = {}
    for r in recs.values():
        for x in r.get("targets") or []:
            if x["target"].startswith("21 CFR"):
                c = r.get("question_class")
                out[c] = out.get(c, 0) + bool(x.get("in_context"))
    return out


def targets_diff(a_recs, b_recs):
    lost, gained = [], []
    for k, a in a_recs.items():
        ta = {x["target"]: x for x in a.get("targets") or []}
        tb = {x["target"]: x for x in b_recs[k].get("targets") or []}
        lost += [f"{k} {n}" for n, x in ta.items() if x.get("in_context") and not tb.get(n, {}).get("in_context")]
        gained += [f"{k} {n}" for n, x in ta.items() if not x.get("in_context") and tb.get(n, {}).get("in_context")]
    return lost, gained


def usage(recs_ctx):
    n = len(recs_ctx)
    tot = lambda f: sum(f(s) for srcs in recs_ctx for s in srcs)
    return {"questions": n, "sources": tot(lambda s: 1), "ecfr_chars": tot(lambda s: s["chars"] if s["corpus"] == "ecfr" else 0),
            "guidance_chars": tot(lambda s: s["chars"] if s["corpus"] != "ecfr" else 0),
            "truncated": tot(lambda s: bool(s["truncated"])), "ecfr_sources": tot(lambda s: s["corpus"] == "ecfr")}


ev = {"run": EV["run"]}
# production identity of the in-process base
ev["base_identity"] = {
    "100_vs_F2_production_base": [q for q in E if sig(E[q]["base"]["sources"]) != sig(F2E[q]["base"]["sources"])],
    "352_base_vs_16fa796d_targets": targets_diff(B352, R352["base"]),
    "352_base_by_class": by_class(R352["base"]), "16fa796d_by_class": by_class(B352),
}
pools, reused = {}, {}
rng = random.Random(20261021)
for arm in ARMS:
    a = {}
    gen = {q: r for q, r in E.items() if r["general_plan"]}
    cnt = lambda c, f: sum(v[f] for r in gen.values() for v in r[c]["required"].values())
    gained, lost = [], []
    for q, r in E.items():
        for lab, v in r[arm]["required"].items():
            b = r["base"]["required"][lab]
            if v["in_context"] and not b["in_context"]:
                gained.append(f"{q} {lab}")
            if b["in_context"] and not v["in_context"]:
                lost.append(f"{q} {lab}")
    a["E1"] = {"base": cnt("base", "in_context"), "arm": cnt(arm, "in_context"), "candidates_base": cnt("base", "candidate"),
               "candidates_arm": cnt(arm, "candidate"), "gained": gained, "lost": lost, "pass": len(gained) >= 3 and not lost}
    t_lost, t_gained = targets_diff(B352, R352[arm])
    bc, wc = by_class(B352), by_class(R352[arm])
    a["E2"] = {"in_context_base": sum(bc.values()), "in_context_arm": sum(wc.values()), "lost": t_lost, "gained": t_gained,
               "by_class_base": bc, "by_class_arm": wc,
               "lost_vs_inprocess_base": targets_diff(R352["base"], R352[arm])[0],
               "pass": not t_lost and all(wc.get(k, 0) >= v for k, v in bc.items())}
    # E3: removed passages
    removed, kept = [], []
    for q, (question, bs, ws, general, _) in contexts(arm).items():
        wk = {s["key"] for s in ws}
        for s in bs:
            (kept if s["key"] in wk else removed).append({"qid": q, "question": question, **s})
    for x in removed:
        hit = LBL.get((x["question"], x["key"], x["text"]))
        x["label_source"], x["label"] = hit if hit else (None, None)
    new = [x for x in removed if x["label"] is None]
    a["E3"] = {"removed": len(removed), "removed_guidance": sum(x["corpus"] != "ecfr" for x in removed),
               "removed_ecfr": sum(x["corpus"] == "ecfr" for x in removed), "reused_labels": len(removed) - len(new),
               "to_judge": len(new),
               "items": [{k: x[k] for k in ("qid", "citation", "corpus", "key", "chars", "label_source", "label")} for x in removed]}
    reused[arm] = [x for x in a["E3"]["items"] if x["label"]]
    for corpus in ("guidance", "ecfr"):
        sub = [x for x in new if (x["corpus"] == "ecfr") == (corpus == "ecfr")]
        if not sub:
            continue
        kp = [x for x in kept if (x["corpus"] == "ecfr") == (corpus == "ecfr")]
        fill = rng.sample(kp, min(len(sub), len(kp)))
        items = [("removed", x) for x in sub] + [("filler", x) for x in fill]
        rng.shuffle(items)
        pools[f"{arm}_{corpus}"] = items
    # E4
    a["E4"] = []
    for name, q, get, ok in E4:
        a["E4"].append({"case": name, "base": ok(get(q, "base")), "arm": ok(get(q, arm)), "pass": ok(get(q, arm)) or not ok(get(q, "base"))})
    b12 = has_cit(E["COS-740.12-Q1"]["base"]["sources"], "740.12", "(a)")
    a12 = has_cit(E["COS-740.12-Q1"][arm]["sources"], "740.12", "(a)")
    a["E4"].append({"case": "COS-740.12-Q1 does not lose 740.12(a) if base had it", "base": b12, "arm": a12, "pass": a12 or not b12})
    for x in a["E4"]:
        if not x["base"] and x["case"] != "COS-740.12-Q1 does not lose 740.12(a) if base had it":
            x["note"] = "base does not have it either"
    a["E4_pass"] = all(x["pass"] for x in a["E4"])
    # E5: non-general contexts identical (100 by plan; 352 by the selector's own rule)
    ch100 = [q for q, r in E.items() if not r["base"]["general"] and sig(r["base"]["sources"]) != sig(r[arm]["sources"])]
    ch352 = [k for k, r in R352["base"].items() if r.get("s1_context") and not r["s1_context"]["general"]
             and sig(r["s1_context"]["sources"]) != sig(ctx352(k, arm))]
    nongen100 = sum(not r["base"]["general"] for r in E.values())  # named provision, docket or guidance question
    nongen352 = sum(bool(r.get("s1_context")) and not r["s1_context"]["general"] for r in R352["base"].values())
    a["E5"] = {"non_general_100": nongen100, "changed_100": ch100, "non_general_352": nongen352, "changed_352": ch352,
               "pass": not ch100 and not ch352}
    # E6
    over, order = [], []
    for q, r in E.items():
        c = r[arm]
        if c["general"] and (c["n"] > 8 or (c["total_chars"] or 0) > 3600):
            over.append(q)
        if c["general"] and not c["optional_in_registry_order"]:
            order.append(q)
    for k, r in R352[arm].items():
        c = r.get("s1_context")
        if c and c["general"] and (c["n"] > 8 or (c["total_chars"] or 0) > 3600):
            over.append(k)
        if c and c["general"] and not c["optional_in_registry_order"]:
            order.append(k)
    rep = f"{arm}_rep2"
    nondet = [q for q, r in E.items() if sigt(r[arm]["sources"]) != sigt(r[rep]["sources"])]
    a["E6"] = {"over_limits": sorted(set(over)), "not_registry_order": order, "nondeterministic_100": nondet,
               "max_total_general": max((r[arm]["total_chars"] or 0) for r in E.values() if r[arm]["general"]),
               "pass": not over and not order and not nondet}
    # context usage (general questions)
    a["usage"] = {
        "100_general_base": usage([r["base"]["sources"] for r in E.values() if r["base"]["general"]]),
        "100_general_arm": usage([r[arm]["sources"] for r in E.values() if r["base"]["general"]]),
        "352_general_base": usage([r["s1_context"]["sources"] for r in R352["base"].values() if r.get("s1_context") and r["s1_context"]["general"]]),
        "352_general_arm": usage([ctx352(k, arm) for k, r in R352["base"].items() if r.get("s1_context") and r["s1_context"]["general"]]),
        "100_contexts_changed": sum(sig(r["base"]["sources"]) != sig(r[arm]["sources"]) for r in E.values()),
        "352_contexts_changed": sum(sig(ctx352(k, "base")) != sig(ctx352(k, arm)) for k in R352["base"]),
    }
    # report targets
    tg = [("COS-70.55-Q1", "70.55", None), ("COS-71.15-Q2", "71.15", "(b)"), ("COS-701.3-Q1", "701.3", "(b)"),
          ("COS-70.19-Q2", "70.19", "(i)"), ("COS-74.2602a-Q1", "74.2602a", "(c)"), ("COS-74.2602a-Q1", "74.2602a", "(e)")]
    a["report_targets"] = [{"qid": q, "target": f"{s}{p or ''}", "base": has_cit(ctx100(q, "base"), s, p), "arm": has_cit(ctx100(q, arm), s, p)} for q, s, p in tg]
    for q, s in (("L-004", "101.5"), ("L-016", "101.11"), ("Y-004", "108.35")):
        a["report_targets"].append({"qid": q, "target": s, "base": has_cit(ctx352(q, "base"), s), "arm": has_cit(ctx352(q, arm), s)})
    ev[arm] = a

# blind pools: one pool per corpus across both arms (an item removed by both arms is judged once)
for corpus in ("guidance", "ecfr"):
    seen, items = set(), []
    for arm in ARMS:
        for role, x in pools.get(f"{arm}_{corpus}", []):
            k = (x["question"], x["key"], x["text"])
            if k in seen:
                for it in items:
                    if (it[1]["question"], it[1]["key"], it[1]["text"]) == k:
                        it[2].add(f"{role}:{arm}")
                continue
            seen.add(k)
            items.append([role, x, {f"{role}:{arm}"}])
    rng.shuffle(items)
    blind, key = [], {}
    pre = "G" if corpus == "guidance" else "R"
    for i, (role, x, roles) in enumerate(items, 1):
        iid = f"{pre}{i:03d}"
        b = {"item": iid, "question": x["question"], "passage": x["text"]}
        b["guidance_document" if corpus == "guidance" else "citation"] = x["citation"]
        blind.append(b)
        key[iid] = {"qid": x["qid"], "key": x["key"], "citation": x["citation"], "roles": sorted(roles)}
    (D / "pools").mkdir(exist_ok=True)
    (D / "pools" / f"{corpus}_blind.json").write_text(json.dumps(blind, indent=1, ensure_ascii=False))
    (D / "pools" / f"{corpus}_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False))
    print(corpus, "pool", len(blind), "items;", sum(any(r.startswith("removed") for r in v["roles"]) for v in key.values()), "removed")
(D / "reused_labels.json").write_text(json.dumps(reused, indent=1, ensure_ascii=False))
(D / "evaluation.json").write_text(json.dumps(ev, indent=1, ensure_ascii=False))
short = {arm: {k: ({kk: vv for kk, vv in v.items() if kk != "items"} if isinstance(v, dict) else v) for k, v in ev[arm].items()} for arm in ARMS}
print(json.dumps({"base_identity": ev["base_identity"], **short}, indent=1, ensure_ascii=False))
