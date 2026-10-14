"""READ-ONLY: assemble the 78 remaining false-conflict cases with traceable context from the recorded run."""
import json, re, sys
sys.path.insert(0, "src")
from regulus.accuracy import operators as OP
W = sys.argv[1] + "/work/"
CF = {c["control_id"]: c for c in json.load(open(W + "controls_frozen.json"))}
RES = json.load(open(W + "controls_result_current.json"))["frozen"]
remaining = [x for x in RES if x["kind"] == "false_conflict" and not x["ok"]]
H = json.load(open(W + "h_current.json"))
calls = {}
for c in H["calls"]:
    calls.setdefault((c["claim"], c["evidence"], c["authority"]), []).append(c)
def trigger(text):
    mc = OP.main_clause(text); m = OP._NEGATE_RE.search(mc)
    if not m: return None
    return {"token": m.group(0), "context": mc[max(0, m.start() - 110): m.end() + 50].replace("\n", " "),
            "sentences_in_main_clause": len(re.findall(r"[.;:]\s", mc)) + 1}
cases = []
for x in remaining:
    c = CF[x["id"]]; k = (c["claim"], c["evidence"], c["authority"])
    occ = []
    for call in calls.get(k, []):
        r = next(r for r in H["results"] if (r["dataset"], r["row"], r["aligner"]) == (call["dataset"], call["row"], call["aligner"]))
        cl = [cc for cc in r["claims"] if cc["claim"] == c["claim"] or c["claim"] in cc["claim"] or cc["claim"] in c["claim"]]
        for cc in cl:
            occ.append({"dataset": call["dataset"], "row": call["row"], "aligner": call["aligner"], "N": r["N"],
                        "claim_id": cc["claim_id"], "path": cc["path"], "final": cc["final"], "basis": cc["basis"], "support": cc["support"],
                        "chosen_source": cc["source"], "gate_candidate": ((cc.get("gate") or {}).get("candidate_selection") or {}).get("passage"),
                        "answer_verdict": r["answer_verdict"], "score": r["score"]})
    co, eo = OP.extract(c["claim"]), OP.extract(c["evidence"])
    cases.append({"case": x["id"], "label_2F": c["label"], "authority": c["authority"], "provenance": c["provenance"],
                  "claim": c["claim"], "evidence": c["evidence"], "conflicts_now": x["now"],
                  "claim_ops": {"strength": co.strength, "polarity": co.polarity, "main_clause": OP.main_clause(c["claim"])},
                  "evidence_ops": {"strength": eo.strength, "polarity": eo.polarity, "main_clause": OP.main_clause(c["evidence"])},
                  "claim_trigger": trigger(c["claim"]), "evidence_trigger": trigger(c["evidence"]),
                  "occurrences": occ})
json.dump(cases, open(W + "cases_78.json", "w"), indent=1, ensure_ascii=False)
from collections import Counter
print(len(cases), "cases;", sum(len(c["occurrences"]) for c in cases), "occurrences (row x aligner x claim)")
print("cases with no mapped occurrence:", [c["case"] for c in cases if not c["occurrences"]])
print("distinct rows:", sorted({o["row"] for c in cases for o in c["occurrences"]}))
print("distinct claims (dataset,row,claim_id):", len({(o["dataset"], o["row"], o["claim_id"]) for c in cases for o in c["occurrences"]}))
