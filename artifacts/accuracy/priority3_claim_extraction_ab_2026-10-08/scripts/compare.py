import json, sys, statistics as st, importlib.util
from collections import Counter
spec=importlib.util.spec_from_file_location("av","scripts/accuracy_validate.py"); av=importlib.util.module_from_spec(spec); sys.modules["av"]=av; spec.loader.exec_module(av)
P=sys.argv[1]
old={r["id"]:r for r in json.load(open(P+"old.json"))}; new={r["id"]:r for r in json.load(open(P+sys.argv[2]))}
WT={"D-001","D-003","D-004","D-006","D-007","D-008","D-009","D-010","E-005","E-010","F-003","K-003"}; TEMP={"M-031","M-032","M-033","M-035","M-036","M-037","M-038"}
def stats(D):
    sc=[k for k in D if D[k]["accuracy"] is not None]
    means={n:round(st.mean([D[k]["accuracy"] for k in sc if D[k]["N"]==n]),1) for n in (2,1,0)}
    rho=av.spearman([float(D[k]["N"]) for k in sc],[float(D[k]["accuracy"]) for k in sc])
    return dict(scored=len(sc), means=means, rho=round(rho,3),
                N0high=[k for k in sc if (D[k]["N"]==0 or D[k]["M"]==1) and D[k]["accuracy"]>50],
                WThigh=[k for k in sc if k in WT and D[k]["accuracy"]>50], TEMPhigh=[k for k in sc if k in TEMP and D[k]["accuracy"]>50],
                verdicts=dict(Counter(D[k]["verdict"] for k in D)))
def claimsN(r): return len(r["claims"])
def disc(r): return sum(1 for s in r["sentences"] if s["origin"]!="model_claim")
def status(r): return Counter((s.get("status") or ("claim" if s["origin"]=="model_claim" else "non_claim")) for s in r["sentences"])
print("OLD", stats(old)); print("NEW", stats(new))
print(f"\n{'id':7}{'N':>2} {'oc':>3}{'nc':>4} {'od':>3}{'nd':>4}  {'old':>18} -> {'new':<18}")
for k in old:
    o,n=old[k],new[k]
    if (o["verdict"],o["accuracy"],claimsN(o),disc(o))!=(n["verdict"],n["accuracy"],claimsN(n),disc(n)):
        print(f"{k:7}{o['N']:>2} {claimsN(o):>3}{claimsN(n):>4} {disc(o):>3}{disc(n):>4}  {str(o['verdict'])+':'+str(o['accuracy']):>18} -> {str(n['verdict'])+':'+str(n['accuracy']):<18}")
so=sum(len(r["sentences"]) for r in old.values()); 
print("\nsentences", so, "| OLD claims-sentences", sum(1 for r in old.values() for s in r["sentences"] if s["origin"]=="model_claim"),
      "| NEW status", dict(sum((status(r) for r in new.values()), Counter())),
      "| OLD assessed claims", sum(claimsN(r) for r in old.values()), "NEW assessed claims", sum(claimsN(r) for r in new.values()))
paths=Counter(c.get("match_path") for r in new.values() for c in r["claims"]); print("match paths", dict(paths))
print("new support of recovered/list claims:", Counter((c.get("match_path"), c["final"]) for r in new.values() for c in r["claims"] if c.get("match_path")!="sentence"))
