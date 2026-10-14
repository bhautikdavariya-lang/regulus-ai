import json, sys
from collections import Counter
from regulus.accuracy import claims as CL
rows = json.load(open(sys.argv[1]))
tot = Counter(); allrows = {}
for r in rows:
    segs = CL.segment(r["answer"] or "", question=r["question"])
    c = Counter(s.origin for s in segs); allrows[r["id"]] = (r["verdict"], dict(c), len(CL.claims(segs)), len(segs))
    if r["verdict"] != "unverifiable" or r["id"] not in sys.argv[2].split(","): continue
    print("=====", r["id"])
    for s in segs: print(f"   {s.origin:22} {s.text[:150]!r}")
json.dump(allrows, open(sys.argv[1].replace("rows.json","segs.json"), "w"))
