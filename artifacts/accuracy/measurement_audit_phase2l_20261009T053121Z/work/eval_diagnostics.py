"""Phase 2K diagnostic set, evaluated with whatever regulus.accuracy is loaded (run via use_variant_ro.py)."""
import json, sys, re
sys.path.insert(0, ".")
from regulus.accuracy import operators as OP
from regulus.accuracy import answer as AN
from tests.test_accuracy_claim_extraction import judge
W, NAME = sys.argv[1] + "/work/", sys.argv[2]
X = json.load(open(W + "diagnostics.json"))
CREDB = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
flags = getattr(OP, "_P2I_FLAGS", frozenset())
def keys(text):
    if "JRQ" in flags: return [k for k, _ in OP._p2k_rel_qualifiers(text)]
    if "QPART" in flags: return [k for k, _ in OP._p2j_qualifiers(text)]
    if "QUAL" in flags: return sorted(OP._p2i_qualifiers(text))
    if "RELC" in flags:
        body = OP.main_clause(text); return [OP._p2k_key_after(body, m) for m in OP._NEGATE_RE.finditer(body) if OP._p2i_relative_negation(body, m)]
    return []
FORBID = {"EX1": {"test", "testing", "stability"}, "EX2": {"manufactur", "manufacturing", "good"}, "EX3": {"packag", "packaging", "tamper-evident"},
          "EX4": None, "EX5": {"the"}}
out = []
for x in X:
    if x["kind"] == "decision":
        cmp = OP.compare(x["claim"], x["evidence"]); ops = sorted({c["operator"] for c in cmp.conflicts})
        a = judge(f"What does {x['citation']} require?", x["claim"] + " [1]", [(x["citation"], x["evidence"])])
        cl = a.checked["claims"][0] if a.checked["claims"] else {}
        basis, final = cl.get("support_basis"), cl.get("final")
        if x["expect"] == "conflict":
            ok = bool(ops) and basis not in CREDB
            issue = "" if ok else ("FALSE " + ("PARTIAL" if basis == "drops_a_condition" else "SUPPORT") + f" ({basis})" if basis in CREDB else "missed contradiction")
        else:
            ok = not ({"polarity", "qualifier_polarity"} & set(ops)) and final != AN.CONTRADICTED
            issue = "" if ok else f"false contradiction ({','.join(ops)}; final {final})"
        out.append({"id": x["id"], "kind": "decision", "expect": x["expect"], "conflicts": ops, "basis": basis, "final": final, "ok": ok, "issue": issue})
    else:
        ks = [k for k in keys(x["text"]) if k]
        bad = ks if FORBID[x["id"]] is None else [k for k in ks if k in FORBID[x["id"]]]
        out.append({"id": x["id"], "kind": "extraction", "keys": ks, "ok": not bad, "issue": f"misread keys {bad}" if bad else ""})
json.dump(out, open(W + f"diagnostics_{NAME}.json", "w"), indent=1)
print(f"{NAME:12} decisions {sum(o['ok'] for o in out if o['kind']=='decision')}/11 | extraction {sum(o['ok'] for o in out if o['kind']=='extraction')}/5 | " +
      " ".join(f"{o['id']}:{'ok' if o['ok'] else o['issue']}" for o in out if not o["ok"]))
