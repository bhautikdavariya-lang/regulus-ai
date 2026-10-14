"""SCRATCH SIMULATION (no source edits): the manually identified false supports/partials become
UNVERIFIABLE, then the answer verdict and score are re-aggregated, semantic aligner of record."""
import json, sys, importlib.util, dataclasses
from pathlib import Path
spec=importlib.util.spec_from_file_location("av","scripts/accuracy_validate.py"); av=importlib.util.module_from_spec(spec); sys.modules["av"]=av; spec.loader.exec_module(av)
from regulus.accuracy import evaluate, answer as AN
from regulus.accuracy.alignment import SemanticAligner
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings
P=sys.argv[1]
L=json.load(open(P+"labelled.json"))
FALSE={(c["row"],c["claim"]) for c in L if c["label"].startswith("FALSE") and "semantic" in c["aligners"]}
H={json.loads(l)["id"]:json.loads(l) for l in open("artifacts/stage_a/dataset.jsonl")}
sem=SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True))
db=Database.from_env(); db.connect(); index=DatabaseIdentifierIndex(db)
orig=AN.assess_claims; current={"row":None}
def patched(*a,**k):
    out=orig(*a,**k)
    return [dataclasses.replace(c, support=AN.UNVERIFIABLE, support_basis="simulated_false", final=(AN.IRRELEVANT if c.final==AN.IRRELEVANT else AN.UNVERIFIABLE))
            if (current["row"],c.claim) in FALSE else c for c in out]
rows=json.load(open("artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json"))
res={}
for arm in ("before","after"):
    AN.assess_claims = patched if arm=="after" else orig
    import regulus.accuracy.evaluator as EV; EV.AN.assess_claims = AN.assess_claims
    for r in rows:
        current["row"]=r["id"]
        srcs=tuple(av.Src(index=s["index"],citation=s["citation"],text=s["text"],heading=s["heading"],citation_fields=s["citation_fields"]) for s in r["sources"])
        reqs=tuple(tuple(x) for x in r["requirements"])
        a=evaluate(r["question"],r["answer"],package=av.Pkg(r["question"],reqs,tuple(r["satisfied_ids"]),srcs),
                   coverage=av.Cov(reqs,tuple(r["satisfied_ids"]),tuple(r["missing_labels"]),r["explicit"]),validation=None,
                   model_called=r["model_called"],fallback_type=r["fallback_type"],scope_status=r["scope"],
                   answerability={"state":r["answerability"]} if r["answerability"] else None,identifier_index=index,aligner=sem,
                   evidence_provenance="legacy_reconstructed")
        res.setdefault(r["id"],{})[arm]=((a.checked.get("answer_verdict") or {}).get("verdict"),a.accuracy)
AN.assess_claims=orig
db.close()
ch=[(k,H[k]["N"],v["before"],v["after"]) for k,v in res.items() if v["before"]!=v["after"]]
print("false decisions simulated (semantic arm):", len(FALSE)); print("rows whose verdict/score would change:"); [print("  ",x) for x in ch]
sc=lambda arm:[k for k,v in res.items() if v[arm][1] is not None]
print("scored rows before/after:", len(sc("before")), len(sc("after")))
print("rows scored >50 before/after with N<2:", [k for k in sc("before") if res[k]["before"][1]>50 and H[k]["N"]<2], [k for k in sc("after") if res[k]["after"][1]>50 and H[k]["N"]<2])
