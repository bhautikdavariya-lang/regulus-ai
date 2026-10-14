import json, sys
from collections import Counter
W = sys.argv[1] + "/work/"
B = json.load(open(W + "base_compares.json"))["results"]
CRED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
def idx(R): return {(r["dataset"], r["row"], r["aligner"]): r for r in R}
b = idx(B); out = {}
for v in sys.argv[2:]:
    X = idx(json.load(open(W + f"compares_{v}.json"))["results"])
    claim_changes, ans_changes, gate = [], [], Counter()
    for k, r in b.items():
        x = X[k]
        if (r["answer_verdict"], r["score"]) != (x["answer_verdict"], x["score"]):
            ans_changes.append({"run": k, "N": r["N"], "before": [r["answer_verdict"], r["score"]], "after": [x["answer_verdict"], x["score"]],
                                "dims": {d: [r["states"].get(d), x["states"].get(d)] for d in r["states"] if r["states"].get(d) != x["states"].get(d)}})
        bc = {c["claim"]: c for c in r["claims"]}; xc = {c["claim"]: c for c in x["claims"]}
        for cl in bc:
            p, q = bc[cl], xc.get(cl)
            if q is None or (p["final"], p["basis"], p["source"]) != (q["final"], q["basis"], q["source"]):
                claim_changes.append({"run": k, "claim": cl[:160], "before": [p["final"], p["basis"], p["source"]],
                                      "after": None if q is None else [q["final"], q["basis"], q["source"]]})
                if q is not None:
                    gate[("credited" if p["basis"] in CRED else "uncredited") + "->" + ("credited" if q["basis"] in CRED else "uncredited")] += 1
    contra_b = sum(1 for r in b.values() for c in r["claims"] if c["final"] == "contradicted")
    contra_x = sum(1 for r in X.values() for c in r["claims"] if c["final"] == "contradicted")
    out[v] = {"claim_changes": claim_changes, "answer_changes": ans_changes, "gate_credit_transitions": dict(gate),
              "contradicted_before": contra_b, "contradicted_after": contra_x}
    print(f"== {v}: claim-level changes {len(claim_changes)} | answer changes {len(ans_changes)} | contradicted {contra_b}->{contra_x} | credit transitions {dict(gate)}")
    for c in claim_changes: print(f"   C {c['run'][0]}:{c['run'][1]}:{c['run'][2][:3]} {c['before']} -> {c['after']} | {c['claim'][:90]}")
    for a in ans_changes: print(f"   A {a['run'][0]}:{a['run'][1]}:{a['run'][2][:3]} N={a['N']} {a['before']} -> {a['after']} {a['dims']}")
json.dump(out, open(W + "verdict_diffs.json", "w"), indent=1, ensure_ascii=False, default=list)
