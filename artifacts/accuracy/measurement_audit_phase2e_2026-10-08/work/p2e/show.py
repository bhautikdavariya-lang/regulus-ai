import json,sys
P=sys.argv[1]; lo,hi=int(sys.argv[2]),int(sys.argv[3]); which=sys.argv[4] if len(sys.argv)>4 else "unlabelled"
A=json.load(open(P+"p2e/all.json")); C=json.load(open(P+"p2e/candidates.json"))
by={}
for a in A: by.setdefault((a["row"],a["claim"]),{})[a["aligner"]]=a
sel=[c for c in C if (c["label2C"] is None)==(which=="unlabelled")]
for i,c in enumerate(sel[lo:hi],lo):
    arms=by[(c["row"],c["claim"])]
    print(f"### {i} {c['row']} N={c['N']} bases={c['bases']} 2C={c['label2C']}")
    print("CLAIM:",c["claim"][:300])
    seen=set()
    for arm,a in arms.items():
        g=a.get("gate") or {}
        key=(g.get("candidate_selection") or {}).get("passage")
        print(f"  [{arm}] gate={g.get('content_gate_verdict')} cand={key} dt={g.get('distinguishing_term_sources')} t={g.get('term_overlap')} core={g.get('core_overlap')} raw={g.get('raw_term_overlap')} ops={g.get('operators_agreed')} omis={g.get('material_omissions')}")
        if key and key not in seen: seen.add(key); print("    PASSAGE:",(a.get("gate_text") or "")[:420].replace("\n"," "))
    print("  SIGNALS:",c["signals"])
