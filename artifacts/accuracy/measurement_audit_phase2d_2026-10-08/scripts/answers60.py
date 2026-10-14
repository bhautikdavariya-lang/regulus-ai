"""READ-ONLY: answer-level evaluator results on the frozen 60, both aligners."""
import json, sys, importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("av","scripts/accuracy_validate.py"); av=importlib.util.module_from_spec(spec); sys.modules["av"]=av; spec.loader.exec_module(av)
from regulus.accuracy import evaluate
from regulus.accuracy.alignment import SemanticAligner, LexicalAligner
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings
FROZEN, OUT = sys.argv[1], sys.argv[2]
H={json.loads(l)["id"]:json.loads(l) for l in open("artifacts/stage_a/dataset.jsonl")}
sem=SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True))
db=Database.from_env(); db.connect(); index=DatabaseIdentifierIndex(db)
out={}
for r in json.loads(Path(FROZEN).read_text()):
    srcs=tuple(av.Src(index=s["index"],citation=s["citation"],text=s["text"],heading=s["heading"],citation_fields=s["citation_fields"]) for s in r["sources"])
    reqs=tuple(tuple(x) for x in r["requirements"])
    for name,al in (("semantic",sem),("lexical",LexicalAligner())):
        a=evaluate(r["question"],r["answer"],package=av.Pkg(r["question"],reqs,tuple(r["satisfied_ids"]),srcs),
                   coverage=av.Cov(reqs,tuple(r["satisfied_ids"]),tuple(r["missing_labels"]),r["explicit"]),validation=None,
                   model_called=r["model_called"],fallback_type=r["fallback_type"],scope_status=r["scope"],
                   answerability={"state":r["answerability"]} if r["answerability"] else None,
                   identifier_index=index,aligner=al,evidence_provenance="legacy_reconstructed")
        av_=a.checked.get("answer_verdict") or {}
        out.setdefault(r["id"],{"N":H[r["id"]]["N"],"L":H[r["id"]].get("L")})[name]={
            "verdict":av_.get("verdict"),"score":a.accuracy,"states":{str(k):str(v) for k,v in (a.states or {}).items()},
            "claim_status":a.checked.get("claim_status"),"counts":av_.get("counts"),
            "claims":[(c["claim"],c["support_basis"],c["final"],c["relevance"]["verdict"],((c.get("evidence") or [{}])[0]).get("citation"),
                       (c.get("citation_trace") or {}).get("markers")) for c in a.checked.get("claims",[])]}
db.close()
Path(OUT).write_text(json.dumps(out,indent=1,ensure_ascii=False,default=str)); print("rows",len(out))
