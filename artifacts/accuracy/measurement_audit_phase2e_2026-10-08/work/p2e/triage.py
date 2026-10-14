import json, sys, re
from collections import Counter, defaultdict
P=sys.argv[1]
A=json.load(open(P+"p2e/all.json"))
import os
pre={(x["row"],x["aligner"],x["claim"]):x for x in json.load(open(P+"pre2d/before_all.json"))} if os.path.exists(P+"pre2d/before_all.json") else {}
L={(c["row"],c["claim"]):c for c in json.load(open(P+"p2c/labelled.json"))}
CRED={"verbatim","paraphrase","list_item","descriptive","adjacent_window"}
by=defaultdict(dict)
for a in A: by[(a["row"],a["claim"])][a["aligner"]]=a
sys.path.insert(0,"src")
from regulus.accuracy.verdicts import _stems
def morph(terms, text):
    st=_stems(text); hits=[]
    for t in terms:
        for s in st:
            if t!=s and min(len(t),len(s))>=4 and (t.startswith(s[:max(4,min(len(t),len(s))-1)]) or s.startswith(t[:max(4,min(len(t),len(s))-1)])): hits.append(f"{t}~{s}")
    return hits
cands=[]
for (row,claim),arms in by.items():
    sig=[]; 
    bases={k:v["basis"] for k,v in arms.items()}
    if not any(b in ("not_decisive","drops_a_condition") for b in bases.values()): continue
    if any(b in CRED for b in bases.values()) and any(b=="not_decisive" for b in bases.values()): sig.append("aligner_disagreement")
    for arm,a in arms.items():
        g=a.get("gate") or {}; v=g.get("content_gate_verdict")
        if a["basis"]=="not_decisive":
            if v=="blocked":
                m=morph(g.get("distinguishing_terms",[]), (a.get("gate_text") or "")+" ")
                if m: sig.append(f"{arm}:blocked_morph({','.join(m)})")
                if len(g.get("distinguishing_terms",[]))==1: sig.append(f"{arm}:blocked_single_term({g['distinguishing_terms'][0]})")
            elif v=="not_established":
                if g.get("core_overlap",0)>=0.6 or g.get("term_overlap",0)>=0.6: sig.append(f"{arm}:near({g.get('term_overlap')},{g.get('core_overlap')},ops={len(g.get('operators_agreed',[]))})")
            elif v in ("established_terms_only","established"): sig.append(f"{arm}:gate_{v}_no_credit")
        if a["basis"]=="drops_a_condition": sig.append(f"{arm}:partial")
        p=pre.get((row,arm,claim))
        if p and p["basis"] in CRED|{"drops_a_condition"} and a["basis"]!=p["basis"]: sig.append(f"{arm}:changed_by_2D({p['basis']}->{a['basis']})")
    lab=L.get((row,claim))
    if sig: cands.append({"row":row,"claim":claim,"N":next(iter(arms.values()))["N"],"signals":sorted(set(sig)),"label2C":lab["label"] if lab else None,"bases":bases})
json.dump(cands,open(P+"p2e/candidates.json","w"),indent=1,ensure_ascii=False)
print("unique claims with conservative verdict:",sum(1 for (r,c),arms in by.items() if any(v["basis"] in ("not_decisive","drops_a_condition") for v in arms.values())))
print("triaged candidates:",len(cands)); print(Counter(s.split("(")[0].split(":")[-1] for c in cands for s in c["signals"]))
print("2C-labelled among candidates:",Counter(c["label2C"] for c in cands))
