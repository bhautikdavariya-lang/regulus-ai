import sys, json, collections
from dataclasses import replace
sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
from regulus.config import load_settings
from regulus.system_identity import configured_rag_config
from regulus.retrieval.factory import build_retriever
from regulus.retrieval import Database
from regulus.planning import plan_query
from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
from regulus.rag.selection import select_evidence
from d1_experiment import install_k1, PART_HARD_MAX_RESULTS, PART_HARD_MAX_CHARS

print(install_k1())
s=load_settings(); c=configured_rag_config(s)
db=Database.from_env(); db.connect()
retr,scope=build_retriever(db,c)
bench={q.question_id:q for q in load_acceptance_benchmark()}
a0={r['id']:r for r in json.load(open('artifacts/diagnostics/d1_experiment/arm0.json'))['rows']}
a1={r['id']:r for r in json.load(open('artifacts/diagnostics/d1_experiment/arm1.json'))['rows']}
prod=c.context
probe=replace(prod,hard_max_results=PART_HARD_MAX_RESULTS,hard_max_total_chars=PART_HARD_MAX_CHARS)
out=[]
print(f"\n{'id':8} {'keyed':26} {'rk0':>4} {'rk1':>4} {'rk2_pred':>8} {'n2':>4} {'chars2':>7}")
for qid,r in a0.items():
    if not r['part_level_plan']: continue
    reg=retr.run_plan(plan_query(bench[qid].question)).registry   # K1 installed -> K1 order
    sx=select_evidence(reg,probe)
    secs=[x.evidence.result.metadata.get('section') for x in sx.selected]
    keyed=set(r['keyed_sections'] or [])
    rk=min([i+1 for i,x in enumerate(secs) if x in keyed] or [0]) or None
    out.append(dict(id=qid,keyed=sorted(keyed),rk0=r['keyed_rank'],rk1=a1[qid]['keyed_rank'],
                    rk2_pred=rk,n2=len(sx.selected),chars2=sum(x.chars for x in sx.selected)))
    print(f"{qid:8} {','.join(sorted(keyed)) or '-':26} {str(r['keyed_rank']):>4} {str(a1[qid]['keyed_rank']):>4} "
          f"{str(rk):>8} {len(sx.selected):4} {sum(x.chars for x in sx.selected):7}")
json.dump(out,open('/private/tmp/claude-501/-Users-sensussoftsoftware-Desktop-Prachi-Patel-Regulus-AI-nosync/6d44959d-46d1-41db-9908-b8dfa9e9f573/scratchpad/predict_arm2.json','w'),indent=1)
has=[o for o in out if o['keyed']]
print(f"\npredicted keyed presence, part-level rows with a key: arm0 {sum(1 for o in has if o['rk0'])}  arm1 {sum(1 for o in has if o['rk1'])}  arm2 {sum(1 for o in has if o['rk2_pred'])}  of {len(has)}")
db.close()
