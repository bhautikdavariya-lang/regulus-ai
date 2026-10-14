"""Phase 2L numeric cases, evaluated with whatever regulus.accuracy is loaded (run via use_variant_ro.py)."""
import json, sys
sys.path.insert(0, ".")
from regulus.accuracy import operators as OP
from regulus.accuracy import answer as AN
from tests.test_accuracy_claim_extraction import judge
W, NAME = sys.argv[1] + "/work/", sys.argv[2]
CS = json.load(open(W + "numeric_cases.json"))["cases"]
CREDB = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
out = []
for n in CS:
    cmp = OP.compare(n["claim"], n["evidence"]); ops = sorted({c["operator"] for c in cmp.conflicts})
    numblock = bool(cmp.support_blocked and "boundary" in (cmp.support_blocked or ""))
    a = judge(f"What does {n['citation']} require?", n["claim"] + " [1]", [(n["citation"], n["evidence"])])
    cl = a.checked["claims"][0] if a.checked["claims"] else {}
    basis, final = cl.get("support_basis"), cl.get("final")
    e = n["expect"]
    if e == "conflict":
        ok = bool(ops) and basis not in CREDB; issue = "" if ok else ("FALSE SUPPORT" if basis in CREDB else "missed contradiction")
    elif e == "equivalent":
        ok = not ({"limit_direction", "polarity", "quantity"} & set(ops)) and not numblock and final != AN.CONTRADICTED
        issue = "" if ok else f"false contradiction/block ({ops}, block={numblock}, final {final})"
    elif e == "boundary":
        ok = final != AN.CONTRADICTED and basis not in CREDB
        issue = "" if ok else ("FALSE SUPPORT (boundary)" if basis in CREDB else f"over-strong: contradicted {ops}")
    else:  # no_numeric
        ok = "limit_direction" not in ops and not numblock; issue = "" if ok else f"numeric finding on an incomparable pair ({ops}, block={numblock})"
    out.append({"id": n["id"], "expect": e, "conflicts": ops, "numeric_block": numblock, "basis": basis, "final": final, "ok": ok, "issue": issue})
json.dump(out, open(W + f"numeric_{NAME}.json", "w"), indent=1)
print(f"{NAME:12} numeric cases {sum(o['ok'] for o in out)}/{len(out)} | " + " ".join(f"{o['id']}:{o['issue']}" for o in out if not o["ok"]))
