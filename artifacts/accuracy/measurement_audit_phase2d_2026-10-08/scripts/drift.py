import json,sys
P=sys.argv[1]
SUP={"verbatim","paraphrase","list_item","descriptive","adjacent_window","drops_a_condition"}
pre={(x["row"],x["aligner"],x["claim"]):x for x in json.load(open(P+"p2c/support.json"))}
L={(c["row"],c["claim"]) for c in json.load(open(P+"p2c/labelled.json"))}
post=json.load(open(P+"p2d/after_all.json"))
new=[y for y in post if y["basis"] in SUP and (y["row"],y["aligner"],y["claim"]) not in pre]
print("NEW DECIDED (not decided pre-2D):",len(new))
for y in new: print("  ",y["row"],y["aligner"],y["basis"],y["source"],"|",y["claim"][:80])
P2={(x["row"],x["aligner"],x["claim"]):x for x in post}
unl=[(k[0],k[1],x["basis"],x["source"],P2.get(k,{}).get("basis"),P2.get(k,{}).get("source"),k[2][:60]) for k,x in pre.items() if (k[0],k[2]) not in L and (P2.get(k,{}).get("basis"),P2.get(k,{}).get("source"))!=(x["basis"],x["source"])]
print("UNLABELLED PRE-2D DECISIONS CHANGED:",len(unl))
for u in unl: print("  ",u)
lab=[(k[0],k[1],x["basis"],x["source"],P2.get(k,{}).get("basis"),P2.get(k,{}).get("source")) for k,x in pre.items() if (k[0],k[2]) in L and P2.get(k,{}).get("basis") in SUP and P2[k]["source"]!=x["source"]]
print("LABELLED DECISIONS NOW CREDITED TO A DIFFERENT SOURCE:",len(lab))
for u in lab: print("  ",u)
