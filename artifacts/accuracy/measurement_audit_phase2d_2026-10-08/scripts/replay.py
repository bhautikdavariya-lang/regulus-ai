import json, sys
from collections import Counter
P=sys.argv[1]
L=json.load(open(P+"p2c/labelled.json")); A=json.load(open(P+"p2d/after_all.json"))
SUP={"verbatim":"supported","paraphrase":"supported","list_item":"supported","descriptive":"supported","adjacent_window":"supported",
     "drops_a_condition":"partially_supported","operator_conflict":"contradicted","no_evidence":"unverifiable","not_decisive":"unverifiable"}
idx={}
for a in A: idx.setdefault((a["row"],a["aligner"],a["claim"]),[]).append(a)
PARTIAL_OK={("list_item",1),("paraphrase",11)}          # Phase 2C 'correct verdict' = partial (E-005 item, C-002 conjunction)
out=[]
for c in L:
    i=int(c["idx"][4:])
    for arm in c["aligners"]:
        new=(idx.get((c["row"],arm,c["claim"])) or [None])[0]
        ns=None if new is None else SUP.get(new["basis"],new["basis"])
        if c["label"].startswith("FALSE"):
            if ns is None: o="fixed: no longer a claim"
            elif ns=="partially_supported" and (c["basis"],i) in PARTIAL_OK: o="fixed: partial (correct verdict)"
            elif ns in ("supported","partially_supported") and new["source"]==c["source"]: o="NOT FIXED"
            elif ns in ("supported","partially_supported"): o="fixed: supported by the stating source "+new["source"]
            else: o="fixed: "+ns
        else:
            old="supported" if c["basis"]!="drops_a_condition" else "partially_supported"
            o="preserved" if ns==old else f"CHANGED {old} -> {ns}"
        out.append({**{k:c[k] for k in ("idx","row","N","label","basis","claim","source")},"aligner":arm,"outcome":o,
                    "new_basis":None if new is None else new["basis"],"new_source":None if new is None else new["source"],
                    "new_reason":None if new is None else new["reason"]})
json.dump(out,open(P+"p2d/replay.json","w"),indent=1,ensure_ascii=False)
print("PER ALIGNER INSTANCE:")
for k,v in sorted(Counter((r["label"],r["outcome"].split(" 21 CFR")[0]) for r in out).items()): print(f"   {k[0]:14} {k[1]:48} {v}")
uniq={}
for r in out: uniq.setdefault(r["idx"],[]).append(r)
def worst(rs): 
    o=[r["outcome"] for r in rs]
    return next((x for x in o if x.startswith(("NOT","CHANGED"))), o[0])
print("PER UNIQUE DECISION:")
for k,v in sorted(Counter((rs[0]["label"],worst(rs).split(" 21 CFR")[0].split(" ->")[0]) for rs in uniq.values()).items()): print(f"   {k[0]:14} {k[1]:48} {v}")
for idx,rs in uniq.items():
    w=worst(rs)
    if w.startswith(("NOT","CHANGED")): print("   >>", idx, rs[0]["row"], rs[0]["label"], w, "|", rs[0]["claim"][:70], "|", (rs[0]["new_reason"] or "")[:150])
