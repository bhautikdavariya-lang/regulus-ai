import sys
P=sys.argv[1]
s=open(P+"/p2d/forensic_all.py").read()
s=s.replace('"""READ-ONLY Phase 2C diagnostic','"""READ-ONLY Phase 2E diagnostic (all claims, full gate trace)')
old='''"evidence_ops":ot.get("evidence_operators"),"relations":ot.get("relations"),"reason":c["support_reason"][:220]})'''
new='''"evidence_ops":ot.get("evidence_operators"),"relations":ot.get("relations"),"reason":c["support_reason"],
                        "gate":ot.get("content_gate"),"agreed":ot.get("agreed"),"omissions":ot.get("omissions"),
                        "candidates":list(c.get("candidate_evidence") or []),
                        "cand_text":{p.citation:p.text for p in ps if p.citation in (c.get("candidate_evidence") or [])},
                        "gate_text":next((p.text for p in ps if p.citation==((ot.get("content_gate") or {}).get("candidate_selection") or {}).get("passage")),None),
                        "row_answer_N":H[r["id"]]["N"],"question":r["question"]})'''
assert old in s; s=s.replace(old,new); open(P+"/p2e/collect.py","w").write(s)
