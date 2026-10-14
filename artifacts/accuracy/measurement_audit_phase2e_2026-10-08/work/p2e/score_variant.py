import json,sys
from collections import Counter
W=sys.argv[1]; V=sys.argv[2]
CRED={"verbatim","paraphrase","list_item","descriptive","adjacent_window","drops_a_condition"}
base={(a["row"],a["aligner"],a["claim"]):a for a in json.load(open(W+"p2e/all.json"))}
var={(a["row"],a["aligner"],a["claim"]):a for a in json.load(open(W+f"p2e/all_{V}.json"))}
cls={(o["row"],o["claim"]):o for o in json.load(open(W+"p2e/classified.json"))}
lab={(c["row"],c["claim"]):c for c in json.load(open(W+"p2c/labelled.json"))}
out=Counter(); lines=[]
for k,b in base.items():
    v=var[k]
    if (b["basis"],b["source"])==(v["basis"],v["source"]): continue
    o=cls.get((k[0],k[2])); l=lab.get((k[0],k[2]))
    tag=o["cls"] if o else ("LABELLED_"+l["label"] if l else "UNLABELLED_CREDITED")
    if b["basis"] in CRED and v["basis"] not in CRED: kind="LOST_CREDIT"
    elif b["basis"] in CRED and v["basis"] in CRED: kind="CREDIT_CHANGED"
    elif v["basis"] in CRED: kind="NEW_CREDIT"
    else: kind="other"
    if l and l["label"].startswith("FALSE") and v["basis"] in CRED and v["source"]==l["source"] and l["idx"] not in ("list01",): kind+="!!FALSE_REOPENED"
    out[(kind,tag)]+=1
    lines.append(f"  {kind:16} {tag:22} {k[0]} {k[1][:3]} {b['basis']}->{v['basis']} {v['source']} | {k[2][:80]}")
print("==",V); [print(f"  {a:30} {b:22} {n}") for (a,b),n in sorted(out.items())]; print("\n".join(lines))
