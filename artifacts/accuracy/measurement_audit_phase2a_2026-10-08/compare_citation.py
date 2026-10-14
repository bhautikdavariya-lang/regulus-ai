import json, sys
B={r["id"]:r for r in json.load(open(sys.argv[1]))}; A={r["id"]:r for r in json.load(open(sys.argv[2]))}
MAP={"pass":1,"fail":0}
for arm in ("semantic","lexical"):
    print(f"\n===== {arm}")
    for name,D in (("before",B),("after",A)):
        dec=[r for r in D.values() if r[arm]["states"]["citation_correctness"] in MAP]
        agree=sum(1 for r in dec if MAP[r[arm]["states"]["citation_correctness"]]==r["human"]["L"])
        fp=[r["id"] for r in dec if r[arm]["states"]["citation_correctness"]=="pass" and r["human"]["L"]==0]
        fn=[r["id"] for r in dec if r[arm]["states"]["citation_correctness"]=="fail" and r["human"]["L"]==1]
        ne=[r["id"] for r in D.values() if r[arm]["states"]["citation_correctness"]=="not_established"]
        print(f"  {name:6} decided {len(dec):2}  agree {agree}/{len(dec)} = {agree/len(dec):.0%}  false-pass {len(fp)} {fp}\n         false-fail {len(fn)} {fn}  not_established {len(ne)}")
    ch=[]
    for k in B:
        b,a=B[k][arm],A[k][arm]
        if b["states"]["citation_correctness"]!=a["states"]["citation_correctness"] or (b["verdict"],b["score"])!=(a["verdict"],a["score"]):
            other={d:(b["states"][d],a["states"][d]) for d in b["states"] if d!="citation_correctness" and b["states"][d]!=a["states"][d]}
            ch.append(k); print(f"   {k} L={B[k]['human']['L']} N={B[k]['human']['N']}: citation {b['states']['citation_correctness']} -> {a['states']['citation_correctness']} | verdict {b['verdict']}:{b['score']} -> {a['verdict']}:{a['score']} | other dims changed: {other or 'none'}")
    sub=[k for k in B if B[k][arm]["verdict"]!=A[k][arm]["verdict"]]
    clm=[k for k in B if [ (c["id"],c["support"],c["rel"]) for c in B[k][arm]["claims"]]!=[(c["id"],c["support"],c["rel"]) for c in A[k][arm]["claims"]]]
    print(f"  answer-verdict changes: {sub}  | claim support/relevance changes: {clm}")
