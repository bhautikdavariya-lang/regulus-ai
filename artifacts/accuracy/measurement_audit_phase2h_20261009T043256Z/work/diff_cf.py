import json, sys
W = sys.argv[1] + "/work/"
CRED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
idx = lambda R: {(r["dataset"], r["row"], r["aligner"]): r for r in R["results"]}
B = idx(json.load(open(W + "h_current.json")))
out = {}
for g in sys.argv[2:]:
    X = idx(json.load(open(W + f"h_cf_{g}.json")))
    cl, an, dims = [], [], []
    for k, b in B.items():
        x = X[k]
        bc = {c["claim_id"]: c for c in b["claims"]}; xc = {c["claim_id"]: c for c in x["claims"]}
        for cid, p in bc.items():
            q = xc.get(cid)
            if q is None or (p["final"], p["basis"], p["source"]) != (q["final"], q["basis"], q["source"]):
                cl.append({"run": list(k), "N": b["N"], "claim_id": cid, "claim": p["claim"], "before": [p["final"], p["basis"], p["source"]],
                           "after": None if q is None else [q["final"], q["basis"], q["source"]],
                           "transition": ("cred" if p["basis"] in CRED else "uncred") + "->" + ("cred" if q and q["basis"] in CRED else "uncred")})
        if (b["answer_verdict"], b["score"]) != (x["answer_verdict"], x["score"]):
            an.append({"run": list(k), "N": b["N"], "before": [b["answer_verdict"], b["score"]], "after": [x["answer_verdict"], x["score"]]})
        dd = {d: [b["states"].get(d), x["states"].get(d)] for d in b["states"] if b["states"].get(d) != x["states"].get(d)}
        if dd: dims.append({"run": list(k), "N": b["N"], "dims": dd})
    out[g] = {"claims": cl, "answers": an, "dims": dims}
    print(f"== {g}: claim changes {len(cl)} | answer changes {len(an)} | dimension changes {len(dims)}")
    for c in cl: print(f"   C {c['run'][0]}:{c['run'][1]}:{c['run'][2][:3]} {c['claim_id']} N={c['N']} {c['before']} -> {c['after']} | {c['claim'][:85]}")
    for a in an: print(f"   A {a['run']} N={a['N']} {a['before']} -> {a['after']}")
    for d in dims: print(f"   D {d['run']} N={d['N']} {d['dims']}")
json.dump(out, open(W + "cf_diffs.json", "w"), indent=1, ensure_ascii=False)
