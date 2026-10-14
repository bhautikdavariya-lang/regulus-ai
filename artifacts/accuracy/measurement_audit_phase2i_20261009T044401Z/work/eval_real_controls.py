"""Evaluate the real-text controls with whatever regulus.accuracy is loaded (run via use_variant_ro.py).
Operator level (compare) and claim level (single-source judge, as the existing tests do)."""
import json, sys
sys.path.insert(0, ".")
from regulus.accuracy import operators as OP
from regulus.accuracy import answer as AN
from tests.test_accuracy_claim_extraction import judge
W, NAME = sys.argv[1] + "/work/", sys.argv[2]
C = json.load(open(W + "controls_real.json"))
CREDB = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
out = []
for c in C:
    cmp = OP.compare(c["claim"], c["evidence"])
    ops = sorted({x["operator"] for x in cmp.conflicts})
    a = judge(f"What does {c['evidence_citation']} require?", c["claim"] + " [1]", [(c["evidence_citation"], c["evidence"])])
    cl = a.checked["claims"][0] if a.checked["claims"] else {}
    final, basis = cl.get("final"), cl.get("support_basis")
    if c["expect"] == "conflict":
        credited = basis in CREDB
        ok = bool(ops) and not credited
        danger = ("FALSE " + ("PARTIAL" if basis == "drops_a_condition" else "SUPPORT") + f" ({basis})") if credited else ("missed contradiction" if not ops else "")
    else:
        ok = "polarity" not in ops
        danger = "" if ok else "false polarity conflict"
    out.append({"id": c["id"], "expect": c["expect"], "conflicts": ops, "claim_final": final, "basis": basis,
                "claim_pol": cmp.claim_operators["polarity"], "evid_pol": cmp.evidence_operators["polarity"], "ok": ok, "issue": danger})
json.dump(out, open(W + f"real_controls_{NAME}.json", "w"), indent=1)
print(f"{NAME:14} passed {sum(o['ok'] for o in out)}/{len(out)} | " + " ".join(f"{o['id']}:{'ok' if o['ok'] else o['issue'] or 'FAIL'}" for o in out))
