"""READ-ONLY: comparison-level differences between a switch variant and its base over the recorded frozen compare calls."""
import json, sys
W = sys.argv[1]; out = {}
key = lambda c: (c["claim"], c["evidence"], c["authority"])
def load(v): return {key(c): c for c in json.load(open(f"{W}/h_cf_{v}.json"))["calls"]}
for base, v in [p.split(":") for p in sys.argv[2:]]:
    A, B = load(base), load(v); ch = []
    for k in B:
        a, b = A.get(k), B[k]
        if a is None: ch.append({"claim": k[0], "evidence": k[1][:300], "change": "pair not in base"}); continue
        ca, cb = sorted(x["operator"] for x in a["conflicts"]), sorted(x["operator"] for x in b["conflicts"])
        if ca != cb or a["support_blocked"] != b["support_blocked"]:
            ch.append({"claim": k[0], "evidence": k[1][:300], "conflicts": [ca, cb], "blocked": [a["support_blocked"], b["support_blocked"]],
                       "details": [x["detail"] for x in b["conflicts"] if x["operator"] not in ca]})
    out[v] = ch
    print(f"{v} vs {base}: {len(ch)} changed comparisons")
    for c in ch: print("   ", c.get("conflicts"), c.get("blocked"), "|", c["claim"][:90], "||", c["evidence"][:90])
json.dump(out, open(W + "/compare_diffs.json", "w"), indent=1, ensure_ascii=False)
