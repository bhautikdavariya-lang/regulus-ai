"""READ-ONLY probe: F-003 citation traces, current vs COMPL-suppressed (in-process counterfactual)."""
import json, sys, importlib.util, dataclasses
sys.path.insert(0, ".")
W = sys.argv[1] + "/work/"
spec = importlib.util.spec_from_file_location("av", "scripts/accuracy_validate.py"); av = importlib.util.module_from_spec(spec); sys.modules["av"] = av; spec.loader.exec_module(av)
from regulus.accuracy import evaluate, operators as OP
from regulus.accuracy.alignment import LexicalAligner
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
r = next(x for x in json.load(open("artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json")) if x["id"] == "F-003")
db = Database.from_env(); db.connect(); index = DatabaseIdentifierIndex(db)
_orig = OP.compare
SUP = {(a, b, c): set(d) for a, b, c, d in json.load(open(W + "suppress_COMPL.json"))}
hits = []
def patched(claim, evidence, *, authority=OP.BINDING):
    res = _orig(claim, evidence, authority=authority); drop = SUP.get((claim, evidence, authority))
    if drop and MODE == "cf":
        hits.append(claim[:80])
        res = dataclasses.replace(res, conflicts=tuple(x for x in res.conflicts if x["operator"] not in drop))
    return res
OP.compare = patched
out = {}
for MODE in ("base", "cf"):
    srcs = tuple(av.Src(index=s["index"], citation=s["citation"], text=s["text"], heading=s["heading"], citation_fields=s["citation_fields"]) for s in r["sources"])
    reqs = tuple(tuple(x) for x in r["requirements"])
    a = evaluate(r["question"], r["answer"], package=av.Pkg(r["question"], reqs, tuple(r["satisfied_ids"]), srcs),
                 coverage=av.Cov(reqs, tuple(r["satisfied_ids"]), tuple(r["missing_labels"]), r["explicit"]), validation=None,
                 model_called=r["model_called"], fallback_type=r["fallback_type"], scope_status=r["scope"],
                 answerability={"state": r["answerability"]} if r["answerability"] else None, identifier_index=index,
                 aligner=LexicalAligner(), evidence_provenance="legacy_reconstructed")
    out[MODE] = {c["claim_id"]: (c["claim"], json.dumps(c.get("citation_trace"), sort_keys=True)) for c in a.checked["claims"]}
    out[MODE + "_state"] = str(a.states.get("citation_correctness")) if a.states else None
    out[MODE + "_detail"] = [str(v) for k, v in (a.checked.get("dimension_details") or {}).items()] if a.checked.get("dimension_details") else None
db.close()
print("citation state:", out["base_state"], "->", out["cf_state"], "| suppressed comparisons hit:", len(hits))
for cid in out["base"]:
    if out["base"][cid] != out["cf"].get(cid):
        print("CHANGED", cid, out["base"][cid][0][:90]); print("   before:", out["base"][cid][1][:400]); print("   after: ", out["cf"][cid][1][:400])
