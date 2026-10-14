"""READ-ONLY detail traces for Phase 2M (run under the JRN2_PROP variant, which carries all helper functions)."""
import json, sys
from regulus.accuracy import operators as OP
W = sys.argv[1]
M = {c["id"]: c for c in json.load(open(W + "/m_cases.json"))}
T = {c["id"]: c for c in json.load(open(W + "/trace_L0_identity.json"))}
def show(i, c):
    au = OP._p2m_anchor(c["evidence"], c["claim"])
    print(f"{i}: units={len(OP._p2m_units(c['evidence']))} anchor={'NONE' if au is None else repr(au[:110])}"
          f" -> anchored polarity {OP.polarity(au) if au else '-'} | whole-passage polarity {OP.polarity(c['evidence'])}")
for i in ("T3c", "DX4"): show(i, T[i])
for i in ("PR1", "PR2", "PR3", "PR4", "PR5", "PR6", "PR7"): show(i, M[i])
c = M["NN2"]["claim"]
print("NN2 claim main clause:", OP.main_clause(c)); print("  negators:", [m.group(0) for m in OP._NEGATE_RE.finditer(OP.main_clause(c))], "polarity", OP.polarity(c))
for i in ("N15",):
    for side in ("claim", "evidence"):
        mc = OP.main_clause(T[i][side]); print(f"N15 {side} main clause == full text: {mc == T[i][side]} | negators {[m.group(0) for m in OP._NEGATE_RE.finditer(mc)]} | polarity {OP.polarity(T[i][side])}")
    print("N15 bounds claim", [b[:3] for b in OP._p2l_bounds(T[i]["claim"])], "evidence", [b[:3] for b in OP._p2l_bounds(T[i]["evidence"])])
