"""READ-ONLY: which current supports count a polarity or strength AGREEMENT that rests on a false scope reading?
The scope-corrected reading is taken from the Phase 2F offline variant VA_all (loaded as a separate module;
production untouched). An agreement is 'at risk' when the corrected readings no longer agree."""
import json, sys, importlib.util
sys.path.insert(0, "src")
W = sys.argv[1] + "/work/"
VA = "artifacts/accuracy/measurement_audit_phase2f_20261009T035919Z/work/variants/VA_all/regulus/accuracy/operators.py"
spec = importlib.util.spec_from_file_location("ops_va_all", VA); va = importlib.util.module_from_spec(spec); sys.modules["ops_va_all"] = va; spec.loader.exec_module(va)
from regulus.accuracy import operators as OP
H = json.load(open(W + "h_current.json"))
calls = {}
for c in H["calls"]: calls.setdefault((c["dataset"], c["row"], c["aligner"]), []).append(c)
CRED = {"paraphrase"}   # the only basis that relies on operator agreement (verbatim, list, descriptive do not count agreements)
rows, risk = [], []
for r in H["results"]:
    for c in r["claims"]:
        if c["basis"] not in CRED: continue
        g = c.get("gate") or {}; agreed = g.get("operators_agreed") or []
        cand = (g.get("candidate_selection") or {}).get("passage")
        call = next((x for x in calls[(r["dataset"], r["row"], r["aligner"])] if (x["claim"] == c["claim"] or x["claim"] in c["claim"])
                     and x["agreed"] == agreed and x["claim_ops"] and x["evidence_ops"]), None)
        if call is None: continue
        lost = []
        if "polarity" in agreed and va.polarity(call["claim"]) != va.polarity(call["evidence"]): lost.append("polarity")
        if "strength" in agreed and va.strength(call["claim"]) != va.strength(call["evidence"]): lost.append("strength")
        rec = {"dataset": r["dataset"], "row": r["row"], "aligner": r["aligner"], "claim_id": c["claim_id"], "claim": c["claim"][:150],
               "source": c["source"], "agreed": agreed, "agreement_lost_under_scope_correction": lost,
               "would_fall_below_two": len(agreed) - len(lost) < 2,
               "claim_neg_token": (OP._NEGATE_RE.search(OP.main_clause(call["claim"])) or [None])[0],
               "evidence_neg_token": (OP._NEGATE_RE.search(OP.main_clause(call["evidence"])) or [None])[0]}
        rows.append(rec)
        if lost: risk.append(rec)
json.dump({"paraphrase_supports_checked": len(rows), "at_risk": risk}, open(W + "spurious_agreements.json", "w"), indent=1, ensure_ascii=False)
print("paraphrase supports checked:", len(rows), "| agreements resting on a false reading:", len(risk),
      "| would fall below the 2-operator rule:", sum(x["would_fall_below_two"] for x in risk))
for x in risk: print(" ", x["dataset"], x["row"], x["aligner"][:3], x["claim_id"], x["agreed"], "lost", x["agreement_lost_under_scope_correction"], "| neg tokens", x["claim_neg_token"], "/", x["evidence_neg_token"], "|", x["claim"][:70])
