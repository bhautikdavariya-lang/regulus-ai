import json, sys
from collections import Counter, defaultdict
sys.path.insert(0, "src")
from regulus.accuracy import operators as OP
D = sys.argv[1]
B = json.load(open(D + "/work/base_compares.json"))
pairs = defaultdict(list)
for c in B["calls"]:
    if c["conflicts"]: pairs[(c["claim"], c["evidence"], c["authority"])].append(c)
final = {}
for r in B["results"]:
    for cl in r["claims"]: final.setdefault((r["dataset"], r["row"], cl["claim"]), set()).add((r["aligner"], cl["final"], cl["basis"], cl["source"]))
def side(t):
    mc = OP.main_clause(t); fb = mc.strip() == (t or "").strip() and (OP._CONDITION_BOUNDARY_RE.search(t) or OP._PURPOSE_BOUNDARY_RE.search(t))
    m = OP._NEGATE_RE.search(mc)
    return {"main": mc, "fallback_whole_sentence": bool(fb), "neg_token": m.group(0) if m else None,
            "strength": OP.strength(t), "polarity": OP.polarity(t)}
out = []
for i, ((cl, ev, au), v) in enumerate(sorted(pairs.items(), key=lambda kv: (kv[1][0]["dataset"], kv[1][0]["row"]))):
    rows = sorted({(x["dataset"], x["row"]) for x in v}); arms = sorted({x["aligner"] for x in v})
    fins = set()
    for (ds, row) in rows:
        for k, s in final.items():
            if k[0] == ds and k[1] == row and (k[2] == cl or cl in k[2] or k[2] in cl): fins |= s
    out.append({"pid": f"P{i:03d}", "rows": rows, "aligners": arms, "authority": au, "claim": cl, "evidence": ev,
                "operators": sorted({x["operator"] for x in v[0]["conflicts"]}), "details": [x["detail"] for x in v[0]["conflicts"]],
                "claim_side": side(cl), "evidence_side": side(ev), "claim_finals": sorted(fins)})
json.dump(out, open(D + "/work/conflict_pairs.json", "w"), indent=1, ensure_ascii=False)
print(len(out))
print("polarity pairs: negation side/token/fallback")
c = Counter()
for p in out:
    if "polarity" in p["operators"]:
        cs, es = p["claim_side"], p["evidence_side"]
        neg = "evidence" if es["polarity"] == "negate" else "claim"
        s = es if neg == "evidence" else cs
        c[(neg, s["neg_token"], s["fallback_whole_sentence"])] += 1
for k, n in c.most_common(): print("  ", k, n)
