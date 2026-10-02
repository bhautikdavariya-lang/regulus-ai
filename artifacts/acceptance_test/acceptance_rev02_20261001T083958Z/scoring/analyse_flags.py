import json,sys,re
from collections import Counter
sys.path.insert(0,"src"); sys.path.insert(0,"scripts")
from build_acceptance_results import indicators, CfrIndex
from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
from regulus.retrieval import Database
run=sys.argv[1]
bench=load_acceptance_benchmark()
rows={json.loads(l)["question_id"]:json.loads(l) for l in open(f"{run}/answers.jsonl")}
db=Database.from_env(); db.connect(); cfr=CfrIndex(db); db.close()
kinds=Counter(); per_dom=Counter(); dom_tot=Counter(); per_type=Counter(); type_tot=Counter()
nc_ok=nc_bad=[]; nc_ok=[]; nc_bad=[]; withheld=[]; nocit=[]; fab=[]
for q in bench:
    r=rows.get(q.question_id); dom_tot[q.domain]+=1; type_tot[q.question_type]+=1
    if not r or r["execution_status"]!="OK": continue
    ind=indicators(q,r,cfr)
    if ind["flags"]: per_dom[q.domain]+=1; per_type[q.question_type]+=1
    for f in ind["flags"]:
        k=f.split(":")[0]; kinds[k]+=1
        if k=="cited provision not in local CFR DB": fab.append((q.question_id,f[:160]))
    if q.is_negative_control: (nc_ok if ind["declined"] else nc_bad).append(q.question_id)
    if any(f.startswith("answer withheld") for f in ind["flags"]): withheld.append(q.question_id)
    if ind["draft_match"]=="no CFR citation": nocit.append(q.question_id)
print("FLAG KINDS"); [print(f"  {v:4}  {k}") for k,v in kinds.most_common()]
print("neg controls declined",len(nc_ok),"not declined",len(nc_bad),nc_bad)
print("withheld",len(withheld)); print("no citation",len(nocit))
print("possible fabrication",len(fab)); [print("   ",x) for x in fab[:15]]
print("\nBY DOMAIN (flagged/total)")
for d,t in dom_tot.items(): print(f"  {per_dom[d]:3}/{t:3}  {100*per_dom[d]/t:5.1f}%  {d}")
print("\nBY TYPE (flagged/total)")
for d,t in type_tot.items(): print(f"  {per_type[d]:3}/{t:3}  {100*per_type[d]/t:5.1f}%  {d}")
m=Counter(indicators(q,rows[q.question_id],cfr)["draft_match"] for q in bench if rows.get(q.question_id,{}).get("execution_status")=="OK")
print("\nCITATION vs DRAFT KEY"); [print(f"  {v:4}  {k}") for k,v in m.most_common()]
