"""READ-ONLY measurement audit: evaluates the frozen 60 (legacy-reconstructed evidence) with the
current evaluator under two aligners and records everything needed to compare with the human rubric."""
import json, sys, importlib.util, re
from pathlib import Path
spec=importlib.util.spec_from_file_location("av","scripts/accuracy_validate.py"); av=importlib.util.module_from_spec(spec); sys.modules["av"]=av; spec.loader.exec_module(av)
from regulus.accuracy import evaluate
from regulus.accuracy.alignment import SemanticAligner, LexicalAligner, passages
from regulus.accuracy.attribution import longest_run, normalise, strip_lead, MARK_RE
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings
FROZEN, OUT = sys.argv[1], sys.argv[2]
human={}
for l in open("artifacts/stage_a/dataset.jsonl"):
    d=json.loads(l); human[d["id"]]={k:d.get(k) for k in ("N","L","M","O","P","Q","result","type","notes","eval","rev_mechanical_root_cause","rev_key_retrieved","rev_substantively_correct","citations")}
sem=SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True))
db=Database.from_env(); db.connect(); index=DatabaseIdentifierIndex(db)
out=[]
for r in json.loads(Path(FROZEN).read_text()):
    srcs=tuple(av.Src(index=s["index"],citation=s["citation"],text=s["text"],heading=s["heading"],citation_fields=s["citation_fields"]) for s in r["sources"])
    reqs=tuple(tuple(x) for x in r["requirements"])
    pkg=av.Pkg(question=r["question"],requirements=reqs,satisfied_ids=tuple(r["satisfied_ids"]),sources=srcs)
    cov=av.Cov(requirements=reqs,satisfied_ids=tuple(r["satisfied_ids"]),missing_labels=tuple(r["missing_labels"]),explicit=r["explicit"])
    row={"id":r["id"],"human":human[r["id"]],"sources":len(srcs),"dockets_lost":r["dockets_lost"]}
    ps=passages(srcs); by_index={s.index:s for s in srcs}
    for name,al in (("semantic",sem),("lexical",LexicalAligner())):
        a=evaluate(r["question"],r["answer"],package=pkg,coverage=cov,validation=None,model_called=r["model_called"],
                   fallback_type=r["fallback_type"],scope_status=r["scope"],
                   answerability={"state":r["answerability"]} if r["answerability"] else None,
                   identifier_index=index,aligner=al,evidence_provenance="legacy_reconstructed")
        claims=[]
        for c in a.checked.get("claims",[]):
            alt=None
            if c["citation"]=="points_elsewhere":
                marks=[int(m) for m in MARK_RE.findall(c["claim"])] or [int(m) for m in MARK_RE.findall(c.get("split_from") or "")]
                words=normalise(strip_lead(c["claim"])).split()
                best=0
                for m in marks:
                    s=by_index.get(m)
                    if s is None: continue
                    for p in ps:
                        if p.source_index==m:
                            run,_=longest_run(words, normalise(p.text)); best=max(best, run/len(words) if words else 0)
                alt=round(best,2)
            claims.append({"id":c["claim_id"],"claim":c["claim"][:220],"final":c["final"],"support":c["support"],"basis":c["support_basis"],
                           "rel":c["relevance"]["verdict"],"citation":c["citation"],"citation_detail":c["citation_detail"],
                           "path":c["match_path"],"selected":c.get("selected_evidence"),"cited_source_cov":alt,
                           "reason":c["support_reason"][:200]})
        row[name]={"verdict":(a.checked.get("answer_verdict") or {}).get("verdict"),"score":a.accuracy,"status":a.status,
                   "states":a.states,"details":{d.dimension:d.detail[:200] for d in a.dimensions},"reason":a.reason[:300],
                   "claims":claims,"candidates":a.checked.get("claim_status_counts"),"abstention":(a.checked.get("abstention") or {}).get("outcome")}
    out.append(row)
db.close()
Path(OUT).write_text(json.dumps(out,indent=1,ensure_ascii=False,default=str)); print("audited",len(out))
