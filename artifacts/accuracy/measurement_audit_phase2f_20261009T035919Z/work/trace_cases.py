"""READ-ONLY trace: operator extraction and every candidate comparison for named claims."""
import json, sys
sys.path.insert(0, ".")
from tests.test_accuracy_claim_extraction import Src, Pkg, Cov
from regulus.accuracy import evaluate, operators as OP
from regulus.accuracy.alignment import LexicalAligner, passages
FROZEN = "artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json"
F = {r["id"]: r for r in json.load(open(FROZEN))}
CASES = [("H-003", "If you are an authorized user of CBP"), ("H-003", "If you are not an authorized user"),
         ("D-009", "Written procedures shall include control of microbiological contamination")]
def ops(t):
    e = OP.extract(t)
    return {"main_clause": OP.main_clause(t), "strength": e.strength, "polarity": e.polarity,
            "duty_holder": e.duty_holder, "conditions": sorted(e.conditions)}
out = []
for row, prefix in CASES:
    r = F[row]
    srcs = tuple(Src(s["index"], s["citation"], s["text"], s.get("heading"), citation_fields=s.get("citation_fields") or {}) for s in r["sources"])
    reqs = tuple(tuple(x) for x in r.get("requirements") or ())
    a = evaluate(r["question"], r["answer"], package=Pkg(r["question"], srcs, reqs, tuple(r.get("satisfied_ids") or ())),
                 coverage=Cov(reqs, tuple(r.get("satisfied_ids") or ()), tuple(r.get("missing_labels") or ()), bool(r.get("explicit"))),
                 model_called=r["model_called"], fallback_type=r["fallback_type"], aligner=LexicalAligner())
    c = next(c for c in a.checked["claims"] if c["claim"].startswith(prefix))
    ps = {p.citation: p for p in passages(srcs)}
    allp = passages(srcs)
    cands = []
    for cit in c.get("candidate_evidence") or []:
        for p in [p for p in allp if p.citation == cit]:
            cmp = OP.compare(c["claim"], p.text, authority=p.authority)
            cands.append({"citation": cit, "authority": p.authority, "seq": p.seq, "text": p.text,
                          "evidence_ops": ops(p.text), "conflicts": list(cmp.conflicts), "agreed": list(cmp.agreed),
                          "relations": list(cmp.relations)})
    out.append({"row": row, "N": None, "claim": c["claim"], "claim_ops": ops(c["claim"]), "support_basis": c["support_basis"],
                "final": c["final"], "support_reason": c["support_reason"], "answer_verdict": a.checked["answer_verdict"]["verdict"],
                "score": a.accuracy, "candidates": cands})
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
for o in out:
    print("==", o["row"], "|", o["claim"]); print("   claim ops:", o["claim_ops"]); print("   verdict:", o["support_basis"], o["final"], "|", o["support_reason"][:200]); print("   answer:", o["answer_verdict"], o["score"])
    for k in o["candidates"]:
        if k["conflicts"] or "211.113" in k["citation"]:
            print("   cand", k["citation"], "seq", k["seq"], "|", k["text"][:150]); print("      ev ops:", k["evidence_ops"]); print("      conflicts:", [x["detail"] for x in k["conflicts"]], "agreed:", k["agreed"])
