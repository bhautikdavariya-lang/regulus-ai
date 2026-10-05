import sys, json, collections
from dataclasses import replace
sys.path.insert(0,'src')
from regulus.config import load_settings
from regulus.system_identity import configured_rag_config
from regulus.retrieval.factory import build_retriever
from regulus.retrieval import Database
from regulus.planning import plan_query
from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
from regulus.rag.selection import select_evidence

s=load_settings(); c=configured_rag_config(s)
db=Database.from_env(); db.connect()
retr,scope=build_retriever(db,c)
bench={q.question_id:q for q in load_acceptance_benchmark()}
a0={r['id']:r for r in json.load(open('artifacts/diagnostics/d1_experiment/arm0.json'))['rows']}
prod=c.context
probe_policy=replace(prod,hard_max_results=84,hard_max_total_chars=24000)

rows=[]
for qid,r in a0.items():
    if not r['part_level_plan']: continue
    reg=retr.run_plan(plan_query(bench[qid].question)).registry
    ev=list(reg.evidence)
    keyed=set(r['keyed_sections'] or [])
    out={}
    for name,pol in (("prod",prod),("probe",probe_policy)):
        sx=select_evidence(reg,pol)
        secs=[x.evidence.result.metadata.get('section') for x in sx.selected]
        out[name]=dict(n=len(sx.selected), chars=sum(x.chars for x in sx.selected),
                       dropped=len(sx.dropped),
                       reasons=dict(collections.Counter(d.reason for d in sx.dropped)),
                       keyed_in=sorted(keyed & set(secs)),
                       keyed_rank=min([i+1 for i,x in enumerate(secs) if x in keyed] or [0]) or None)
    rows.append(dict(id=qid, retrieved=len(ev), keyed=sorted(keyed), **{f"{k}_{kk}":vv for k,v in out.items() for kk,vv in v.items()}))
    print(f"{qid:8} retrieved={len(ev):3}  prod n={out['prod']['n']:3} chars={out['prod']['chars']:6} keyed_rank={str(out['prod']['keyed_rank']):5}"
          f"  | probe n={out['probe']['n']:3} chars={out['probe']['chars']:6} keyed_rank={str(out['probe']['keyed_rank']):5}"
          f"  drops_probe={out['probe']['reasons'] or '{}'}", flush=True)
json.dump(rows,open('/private/tmp/claude-501/-Users-sensussoftsoftware-Desktop-Prachi-Patel-Regulus-AI-nosync/6d44959d-46d1-41db-9908-b8dfa9e9f573/scratchpad/sel_accounting.json','w'),indent=1)
db.close()
