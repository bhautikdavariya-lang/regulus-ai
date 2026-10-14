"""Phase 2M labelled diagnostics + the seven reproduced cases, judged with whatever regulus.accuracy is loaded."""
import json, sys
sys.path.insert(0, ".")
from regulus.accuracy import operators as OP
from regulus.accuracy import answer as AN
from tests.test_accuracy_claim_extraction import judge
W, NAME = sys.argv[1] + "/work/", sys.argv[2]
CRED = {"verbatim", "paraphrase", "list_item", "descriptive", "adjacent_window", "drops_a_condition"}
cases = json.load(open(W + "m_cases.json"))
tr = {c["id"]: c for c in json.load(open(W + "trace_L0_identity.json"))}
for i, exp in (("T3c", "no_polarity_conflict"), ("DX4", "no_polarity_conflict"), ("DX2", "conflict"), ("N9", "not_credited"),
               ("N10", "not_credited"), ("N12", "equivalent"), ("N15", "conflict")):
    cases.append({"id": i, "family": "TARGET", "citation": tr[i]["citation"], "evidence": tr[i]["evidence"], "claim": tr[i]["claim"], "expect": exp})
out = []
for c in cases:
    cmp = OP.compare(c["claim"], c["evidence"]); ops = sorted({x["operator"] for x in cmp.conflicts})
    a = judge(f"What does {c['citation']} require?", c["claim"] + " [1]", [(c["citation"], c["evidence"])])
    cl = a.checked["claims"][0] if a.checked["claims"] else {}
    basis, final = cl.get("support_basis"), cl.get("final"); cred = basis in CRED; e = c["expect"]
    if e == "conflict": ok = bool(ops) and not cred
    elif e == "equivalent": ok = final != AN.CONTRADICTED and not ops
    elif e == "not_credited": ok = not cred
    elif e == "not_contradicted": ok = final != AN.CONTRADICTED
    else: ok = "polarity" not in ops
    out.append({"id": c["id"], "family": c["family"], "expect": e, "conflicts": ops, "blocked": cmp.support_blocked, "basis": basis,
                "final": final, "credited": cred, "ok": ok, "c_str": cmp.claim_operators["strength"], "e_str": cmp.evidence_operators["strength"],
                "c_pol": cmp.claim_operators["polarity"], "e_pol": cmp.evidence_operators["polarity"]})
json.dump(out, open(W + f"m_cases_{NAME}.json", "w"), indent=1)
print(f"{NAME:13} m-cases {sum(o['ok'] for o in out)}/{len(out)} | FAIL: " + " ".join(f"{o['id']}({o['basis'][:6] if o['basis'] else '-'}/{','.join(o['conflicts']) or '-'})" for o in out if not o["ok"]))
