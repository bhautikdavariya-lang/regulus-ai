"""READ-ONLY answer-level simulation on the frozen 60 (semantic aligner of record).
mode 'base' = Phase 2D as is; 'fn_upper' = every confirmed FALSE_NEGATIVE credited at its correct verdict."""
import json, sys, importlib.util, dataclasses
from pathlib import Path
spec=importlib.util.spec_from_file_location("av","scripts/accuracy_validate.py"); av=importlib.util.module_from_spec(spec); sys.modules["av"]=av; spec.loader.exec_module(av)
from regulus.accuracy import evaluate, answer as AN
import regulus.accuracy.evaluator as EV
from regulus.accuracy.alignment import SemanticAligner
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings
W, MODE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
FN={}
for o in json.load(open(W+"p2e/classified.json")):
    if o["cls"]=="FALSE_NEGATIVE": FN[(o["row"],o["claim"])]=o["correct"]
H={json.loads(l)["id"]:json.loads(l) for l in open("artifacts/stage_a/dataset.jsonl")}
sem=SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True))
db=Database.from_env(); db.connect(); index=DatabaseIdentifierIndex(db)
orig=AN.assess_claims; cur={"row":None}
def patched(*a,**k):
    out=orig(*a,**k); res=[]
    for c in out:
        want=FN.get((cur["row"],c.claim))
        if want and c.support_basis in ("not_decisive","no_evidence"):
            sup=AN.SUPPORTED if want=="supported" else AN.PARTIALLY_SUPPORTED
            c=dataclasses.replace(c,support=sup,support_basis="simulated_fn_credit",final=(AN.IRRELEVANT if c.final==AN.IRRELEVANT else sup))
        res.append(c)
    return res
if MODE=="fn_upper": EV.AN.assess_claims=patched
res={}
for r in json.load(open("artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json")):
    cur["row"]=r["id"]
    srcs=tuple(av.Src(index=s["index"],citation=s["citation"],text=s["text"],heading=s["heading"],citation_fields=s["citation_fields"]) for s in r["sources"])
    reqs=tuple(tuple(x) for x in r["requirements"])
    a=evaluate(r["question"],r["answer"],package=av.Pkg(r["question"],reqs,tuple(r["satisfied_ids"]),srcs),
               coverage=av.Cov(reqs,tuple(r["satisfied_ids"]),tuple(r["missing_labels"]),r["explicit"]),validation=None,
               model_called=r["model_called"],fallback_type=r["fallback_type"],scope_status=r["scope"],
               answerability={"state":r["answerability"]} if r["answerability"] else None,identifier_index=index,aligner=sem,
               evidence_provenance="legacy_reconstructed")
    res[r["id"]]={"N":H[r["id"]]["N"],"verdict":(a.checked.get("answer_verdict") or {}).get("verdict"),"score":a.accuracy,
                 "states":{str(k):str(v) for k,v in (a.states or {}).items()},"claim_status":a.checked.get("claim_status")}
db.close(); Path(OUT).write_text(json.dumps(res,indent=1)); print(MODE,"rows",len(res))
