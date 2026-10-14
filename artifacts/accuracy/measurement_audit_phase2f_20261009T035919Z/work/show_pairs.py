import json,sys
P=json.load(open(sys.argv[1]+"/work/conflict_pairs.json")); lo,hi=int(sys.argv[2]),int(sys.argv[3])
for p in P[lo:hi]:
    cs,es=p["claim_side"],p["evidence_side"]
    print(f"{p['pid']} {','.join(r[1] for r in p['rows'])} {p['aligners']} {p['authority'][:4]} {p['operators']} | finals={[f[1]+':'+str(f[2]) for f in p['claim_finals']][:2]}")
    print(f"   C[{cs['strength']},{cs['polarity']},{cs['neg_token']}{',FB' if cs['fallback_whole_sentence'] else ''}]: {p['claim'][:200]}")
    print(f"   E[{es['strength']},{es['polarity']},{es['neg_token']}{',FB' if es['fallback_whole_sentence'] else ''}]: {p['evidence'][:260]}")
