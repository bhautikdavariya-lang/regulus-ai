"""READ-ONLY Phase 2F collector. Records EVERY OP.compare call the evaluator makes, plus each
claim's final verdict and each row's answer verdict, over three frozen datasets and both aligners:
  F60    artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json (LEGACY_RECONSTRUCTED)
  GUIDE8 tests/fixtures/accuracy_guidance_rows.json (guidance text present; test fixture)
  REAL17 tests/fixtures/accuracy_real_rows.json (test fixture)
Run under use_variant.py to measure an offline variant; nothing is written outside OUT."""
import json, sys, importlib.util
sys.path.insert(0, ".")
from pathlib import Path
OUT = sys.argv[1]
from regulus.accuracy import evaluate, operators as OP
from regulus.accuracy.alignment import SemanticAligner, LexicalAligner
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings
spec = importlib.util.spec_from_file_location("av", "scripts/accuracy_validate.py"); av = importlib.util.module_from_spec(spec)
sys.modules["av"] = av; spec.loader.exec_module(av)
import tests.test_accuracy_guidance_logic as TG
import tests.test_accuracy_relevance as TR

calls, ctx = [], {}
_orig = OP.compare
def recording(claim, evidence, *, authority=OP.BINDING):
    r = _orig(claim, evidence, authority=authority)
    calls.append({**ctx, "claim": claim, "evidence": evidence, "authority": authority,
                  "conflicts": [dict(x) for x in r.conflicts], "agreed": list(r.agreed),
                  "relations": [dict(x) for x in r.relations], "support_blocked": r.support_blocked,
                  "claim_ops": r.claim_operators, "evidence_ops": r.evidence_operators})
    return r
OP.compare = recording

H = {json.loads(l)["id"]: json.loads(l) for l in open("artifacts/stage_a/dataset.jsonl")}
sem = SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True))
db = Database.from_env(); db.connect(); index = DatabaseIdentifierIndex(db)
ALIGNERS = (("semantic", sem), ("lexical", LexicalAligner()))
results = []

def record(dataset, rid, arm, a):
    results.append({"dataset": dataset, "row": rid, "aligner": arm, "N": (H.get(rid) or {}).get("N"),
                    "answer_verdict": (a.checked.get("answer_verdict") or {}).get("verdict"), "score": a.accuracy,
                    "states": {str(k): str(v) for k, v in (a.states or {}).items()},
                    "claims": [{"claim": c["claim"], "basis": c["support_basis"], "support": c["support"], "final": c["final"],
                                "source": ((c.get("evidence") or [{}])[0]).get("citation"), "reason": c["support_reason"]}
                               for c in a.checked.get("claims", [])]})

for r in json.load(open("artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json")):
    srcs = tuple(av.Src(index=s["index"], citation=s["citation"], text=s["text"], heading=s["heading"], citation_fields=s["citation_fields"]) for s in r["sources"])
    reqs = tuple(tuple(x) for x in r["requirements"])
    for arm, al in ALIGNERS:
        ctx.clear(); ctx.update(dataset="F60", row=r["id"], aligner=arm)
        a = evaluate(r["question"], r["answer"], package=av.Pkg(r["question"], reqs, tuple(r["satisfied_ids"]), srcs),
                     coverage=av.Cov(reqs, tuple(r["satisfied_ids"]), tuple(r["missing_labels"]), r["explicit"]), validation=None,
                     model_called=r["model_called"], fallback_type=r["fallback_type"], scope_status=r["scope"],
                     answerability={"state": r["answerability"]} if r["answerability"] else None,
                     identifier_index=index, aligner=al, evidence_provenance="legacy_reconstructed")
        record("F60", r["id"], arm, a)
for rid, row in TG.REAL.items():
    srcs = tuple(TG.Src(i + 1, s["citation"], s["text"], s["corpus"], is_docket=s["corpus"] == "fda_guidance") for i, s in enumerate(row["sources"]))
    for arm, al in ALIGNERS:
        ctx.clear(); ctx.update(dataset="GUIDE8", row=rid, aligner=arm)
        a = evaluate(row["question"], row["answer"] or "", package=TG.Pkg(row["question"], srcs), coverage=TG.Cov(),
                     model_called=row["model_called"], fallback_type=row["fallback_type"], aligner=al)
        record("GUIDE8", rid, arm, a)
for rid, row in TR.REAL.items():
    srcs = [(s["citation"], s["text"], s.get("heading")) for s in row["sources"]]
    for arm, al in ALIGNERS:
        ctx.clear(); ctx.update(dataset="REAL17", row=rid, aligner=arm)
        a = TR.run(row["question"], row["answer"] or "", srcs, model_called=row["model_called"], fallback_type=row["fallback_type"],
                   answerability={"state": row["answerability"]} if row.get("answerability") else None, aligner=al)
        record("REAL17", rid, arm, a)
db.close()
Path(OUT).write_text(json.dumps({"calls": calls, "results": results}, ensure_ascii=False))
print("compare calls", len(calls), "with conflicts", sum(1 for c in calls if c["conflicts"]), "row-runs", len(results))
