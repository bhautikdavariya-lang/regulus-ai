"""READ-ONLY: how much numeric-bound content the 170 frozen row-runs expose to the NUM2 check (Phase 2L)."""
import json, sys
from collections import Counter
from regulus.accuracy import operators as OP
W = sys.argv[1]
calls = json.load(open(W + "/h_cf_JRN2.json"))["calls"]
pairs = {(c["claim"], c["evidence"]) for c in calls}
st = Counter(); ex = []
for cl, ev in pairs:
    bc, be = OP._p2l_bounds(cl), OP._p2l_bounds(ev)
    if not bc: st["claim has no bound"] += 1; continue
    if all(b[0] == "ambiguous" for b in bc): st["claim bound ambiguous"] += 1; continue
    if not be: st["claim bound, evidence none"] += 1; continue
    vals = {(b[1], b[2]) for b in bc if b[0] != "ambiguous"} & {(b[1], b[2]) for b in be if b[0] != "ambiguous"}
    if not vals: st["both bounded, no shared value+unit"] += 1; ex.append((cl, ev, bc, be)); continue
    r = OP._p2l_compare(cl, ev)
    st["shared value+unit -> " + (r[0] if r else "abstain/agree")] += 1
    ex.append((cl, ev, bc, be))
print(dict(st), "pairs", len(pairs))
for cl, ev, bc, be in ex[:12]:
    print("  C:", cl[:110]); print("    cb", [b[:3] for b in bc], "eb", [b[:3] for b in be][:4])
json.dump({"pairs": len(pairs), "counts": dict(st)}, open(W + "/exposure_frozen.json", "w"), indent=1)
