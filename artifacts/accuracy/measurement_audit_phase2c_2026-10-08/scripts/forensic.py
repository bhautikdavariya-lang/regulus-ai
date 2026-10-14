"""READ-ONLY Phase 2C diagnostic: every decided support verdict on the frozen 60, both aligners."""
import json, sys, importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("av","scripts/accuracy_validate.py"); av=importlib.util.module_from_spec(spec); sys.modules["av"]=av; spec.loader.exec_module(av)
from regulus.accuracy import evaluate, operators as OP
from regulus.accuracy.alignment import SemanticAligner, LexicalAligner, passages, content_terms
from regulus.accuracy.attribution import longest_run, normalise, strip_lead
from regulus.accuracy.intent import stem
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings
FROZEN, OUT = sys.argv[1], sys.argv[2]
H={json.loads(l)["id"]:json.loads(l) for l in open("artifacts/stage_a/dataset.jsonl")}
sem=SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True))
db=Database.from_env(); db.connect(); index=DatabaseIdentifierIndex(db)
stems=lambda t:{stem(w) for w in content_terms(t)}
out=[]
for r in json.loads(Path(FROZEN).read_text()):
    srcs=tuple(av.Src(index=s["index"],citation=s["citation"],text=s["text"],heading=s["heading"],citation_fields=s["citation_fields"]) for s in r["sources"])
    reqs=tuple(tuple(x) for x in r["requirements"])
    pkg=av.Pkg(question=r["question"],requirements=reqs,satisfied_ids=tuple(r["satisfied_ids"]),sources=srcs)
    cov=av.Cov(requirements=reqs,satisfied_ids=tuple(r["satisfied_ids"]),missing_labels=tuple(r["missing_labels"]),explicit=r["explicit"])
    ps=passages(srcs)
    for name,al in (("semantic",sem),("lexical",LexicalAligner())):
        a=evaluate(r["question"],r["answer"],package=pkg,coverage=cov,validation=None,model_called=r["model_called"],
                   fallback_type=r["fallback_type"],scope_status=r["scope"],
                   answerability={"state":r["answerability"]} if r["answerability"] else None,
                   identifier_index=index,aligner=al,evidence_provenance="legacy_reconstructed")
        for c in a.checked.get("claims",[]):
            if c["support"] not in ("supported","partially_supported"): continue
            ev=(c.get("evidence") or [{}])[0]
            p=next((p for p in ps if p.citation==ev.get("citation") and p.text.startswith((ev.get("text") or "")[:120])), None)
            ptext=p.text if p else (ev.get("text") or "")
            core=strip_lead(c["claim"]); words=normalise(core).split(); run,_=longest_run(words, normalise(ptext))
            ot=c.get("operator_trace") or {}
            out.append({"row":r["id"],"N":H[r["id"]]["N"],"aligner":name,"claim_id":c["claim_id"],"claim":c["claim"],
                        "path":c["match_path"],"basis":c["support_basis"],"final":c["final"],"rel":c["relevance"]["verdict"],
                        "source":ev.get("citation"),"passage":ptext,"coverage":round(run/len(words),2) if words else 0,"run":run,
                        "missing_stems":sorted(stems(core)-stems(ptext)),"claim_ops":ot.get("claim_operators"),
                        "evidence_ops":ot.get("evidence_operators"),"relations":ot.get("relations"),"reason":c["support_reason"][:220]})
db.close()
Path(OUT).write_text(json.dumps(out,indent=1,ensure_ascii=False)); print("support decisions recorded:",len(out))
