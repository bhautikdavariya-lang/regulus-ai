import json, sys, time
sys.path.insert(0,".")
from tests.test_accuracy_claim_extraction import Src, Pkg, Cov
from regulus.accuracy import evaluate
from regulus.accuracy.alignment import LexicalAligner, passages
P=sys.argv[1]
F={r["id"]:r for r in json.load(open("artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json"))}
R=json.load(open(P+"p2d/replay.json"))
class Prefer(LexicalAligner):
    def __init__(self, citation): self.citation=citation
    def align(self, claim, candidates, *, top_k=3):
        found=super().align(claim, candidates, top_k=len(candidates))
        found.sort(key=lambda a: a.passage.citation!=self.citation)
        return found[:top_k]
cache={}
def run(row, mode):
    if (row,mode) in cache: return cache[(row,mode)]
    r=F[row]
    srcs=tuple(Src(s["index"],s["citation"],s["text"],s.get("heading"),citation_fields=s.get("citation_fields") or {}) for s in r["sources"])
    reqs=tuple(tuple(x) for x in r.get("requirements") or ())
    pkg=Pkg(r["question"],srcs,reqs,tuple(r.get("satisfied_ids") or ()))
    cov=Cov(reqs,tuple(r.get("satisfied_ids") or ()),tuple(r.get("missing_labels") or ()),bool(r.get("explicit")))
    al=LexicalAligner() if mode=="lexical" else Prefer(mode)
    a=evaluate(r["question"],r["answer"],package=pkg,coverage=cov,model_called=r["model_called"],fallback_type=r["fallback_type"],aligner=al)
    cache[(row,mode)]=a; return a
t=time.time(); bad=0
for x in R:
    mode="lexical" if x["aligner"]=="lexical" else x["source"]
    a=run(x["row"],mode)
    c=next((c for c in a.checked.get("claims",[]) if c["claim"]==x["claim"]),None)
    got=None if c is None else (c["support_basis"], ((c.get("evidence") or [{}])[0]).get("citation"))
    exp=(x["new_basis"],x["new_source"]) if x["new_basis"] else None
    ok = got==exp or (got and exp and got[0]==exp[0] and got[0] in ("not_decisive","no_evidence"))
    if not ok: bad+=1; print("MISMATCH",x["idx"],x["row"],x["aligner"],"exp",exp,"got",got,"|",x["claim"][:60])
print("checked",len(R),"mismatch",bad,"time",round(time.time()-t,1),"runs",len(cache))
