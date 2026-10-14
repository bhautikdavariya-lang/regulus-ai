import json,sys
from collections import Counter
W=sys.argv[1]
A=json.load(open(W+"p2e/all.json")); C=json.load(open(W+"p2e/candidates.json"))
L={}; LL={}
for c in json.load(open(W+"p2c/labelled.json")):
    LL.setdefault((c["row"],c["claim"]),[]).append(c)
for k,v in LL.items():   # a claim labelled on two arms: the label that explains a CONSERVATIVE arm decides
    v=sorted(v,key=lambda c:(c["idx"] not in ("para20","para28","drop15","desc00"),))
    L[k]=v[0]
by={}
for a in A: by.setdefault((a["row"],a["claim"]),{})[a["aligner"]]=a
cons=[k for k,v in by.items() if any(x["basis"] in ("not_decisive","drops_a_condition") for x in v.values())]
cset={(c["row"],c["claim"]) for c in C}
unl=[c for c in C if c["label2C"] is None]
sweep=[k for k in cons if k not in cset and k not in L]
cls={}
for f in ("cls_u1","cls_u2","cls_u3"): cls.update(json.load(open(W+f"p2e/{f}.json")))
out=[]
for i,c in enumerate(unl):
    v=cls[str(i)]; out.append({"id":f"C{i}","row":c["row"],"claim":c["claim"],"N":c["N"],"source":"unlabelled-triaged","cls":v[0],"correct":v[1],"root":v[2],"note":v[3],"bases":c["bases"],"caused_by_2D":False})
sw=json.load(open(W+"p2e/cls_sweep.json"))
for i,k in enumerate(sweep):
    v=sw[f"U{i}"]; a=next(iter(by[k].values()))
    out.append({"id":f"U{i}","row":k[0],"claim":k[1],"N":a["N"],"source":"unlabelled-untriaged","cls":v[0],"correct":v[1],"root":v[2],"note":v[3],"bases":{x:y["basis"] for x,y in by[k].items()},"caused_by_2D":False})
# labelled (Phase 2C) decisions with a conservative verdict now
PARTIAL_2C={"desc00":"B-005: 2C correct verdict partial (drops 'for a specific recipient' and the proviso)","para20":"D-008: 2C correct verdict partial (211.68(a) states calibration records are maintained; 'procedures' is not)"}
AMBIG_2C={"para11":"C-002: 2C correct verdict 'partial / unverifiable here' (identity is in 701.11)"}
for k in cons:
    if k not in L: continue
    l=L[k]; v=by[k]; idx=l["idx"]
    if l["label"].startswith("FALSE"):
        if idx in PARTIAL_2C: r=("FALSE_NEGATIVE","partial","content gate",PARTIAL_2C[idx]+"; Phase 2D returns unverifiable"+("; semantic arm only - the lexical arm credits 213.68(a) (Phase 2C para21 SAFE)" if idx=="para20" else ""))
        elif idx in AMBIG_2C: r=("AMBIGUOUS","-","content gate",AMBIG_2C[idx])
        elif any(x["basis"]=="drops_a_condition" for x in v.values()): r=("TRUE_PARTIAL","partial","-","Phase 2C correct verdict, now returned")
        else: r=("CORRECT_UNVERIFIABLE","unverifiable","-","Phase 2C label "+l["label"]+"; correct verdict unverifiable")
    elif idx=="para28":
        r=("FALSE_NEGATIVE","supported","alignment","semantic arm only: selects 211.100(a) (guard correctly blocks it); the lexical arm credits 211.101, heading 'Charge-in of components' (Phase 2C para28 SAFE)")
    else:
        if idx=="drop15": r=("FALSE_NEGATIVE","partial","terminology normalization","117.160(a) 'You must validate that the preventive controls ... are adequate ... as appropriate'; validation/validate stem differently (valid vs validat): 67% core < 70%. Documented in Phase 2C/2D")
        elif False: r=("FALSE_NEGATIVE","supported","alignment","semantic arm only: selects 211.100(a) (guard correctly blocks it); the lexical arm credits 211.101, heading 'Charge-in of components' (Phase 2C SAFE)")
        elif any(x["basis"]=="drops_a_condition" for x in v.values()): r=("TRUE_PARTIAL","partial","-","Phase 2C SAFE_PARTIAL, preserved")
        else: r=("TRUE_SUPPORT","supported","-","Phase 2C SAFE, preserved on its labelled arm")
    out.append({"id":idx,"row":k[0],"claim":k[1],"N":l["N"],"source":"phase2c-labelled:"+l["label"],"cls":r[0],"correct":r[1],"root":r[2],"note":r[3],
                "bases":{x:y["basis"] for x,y in v.items()},"caused_by_2D":idx in ("drop15","desc00","para20","para11"),"arm_specific":idx in ("para20","para28")})
A2={}
for a in A: A2.setdefault((a["row"],a["claim"]),a)
for e in json.load(open(W+"p2e/cls_extra.json")):
    k=next(k for k in A2 if k[0]==e[1] and k[1].startswith(e[2]))
    out.append({"id":e[0],"row":k[0],"claim":k[1],"N":A2[k]["N"],"source":e[3],"cls":e[4],"correct":e[5],"root":e[6],"note":e[7],
                "bases":{x:y["basis"] for x,y in by[k].items()},"caused_by_2D":False})
json.dump(out,open(W+"p2e/classified.json","w"),indent=1,ensure_ascii=False)
print("classified",len(out),"(",len(cons),"conservative + extra)"); print(Counter(o["cls"] for o in out))
for i in ("C2","C43","C62","C71","U24","U44"):
    o=next(x for x in out if x["id"]==i); print(i,o["row"],o["cls"],"|",o["claim"][:70],"|",o["note"][:60])
