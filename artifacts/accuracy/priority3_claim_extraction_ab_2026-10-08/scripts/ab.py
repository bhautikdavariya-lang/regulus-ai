"""Priority 3 A/B runner. `freeze` writes the 60 official validation inputs (question,
answer, labels, evidence text, coverage) once; `run` evaluates those frozen inputs with
whatever evaluator is on disk and records per-row claim traces."""
import json, sys, importlib.util, time
from pathlib import Path
ROOT = Path.cwd()
spec = importlib.util.spec_from_file_location("av", ROOT / "scripts/accuracy_validate.py")
av = importlib.util.module_from_spec(spec); sys.modules["av"] = av; spec.loader.exec_module(av)

def freeze(out):
    from regulus.retrieval import Database
    rows = [json.loads(l) for l in av.DATASET.read_text().splitlines() if l.strip()]
    db = Database.from_env(); db.connect(); cache = {}
    frozen = []
    for row in av.select(rows, 60):
        pkg, cov, dockets = av.build(row, db, cache)
        frozen.append({"id": row["id"], "N": row["N"], "M": row.get("M"), "type": row["type"], "question": row["question"],
                       "answer": row["answer"] or "", "model_called": bool(row.get("model_called")),
                       "fallback_type": row.get("fallback_type"), "scope": row.get("scope"), "answerability": row.get("answerability"),
                       "sources": [{"index": s.index, "citation": s.citation, "text": s.text, "heading": s.heading,
                                    "citation_fields": s.citation_fields} for s in pkg.sources],
                       "requirements": pkg.requirements, "satisfied_ids": pkg.satisfied_ids,
                       "missing_labels": cov.missing_labels, "explicit": cov.explicit, "dockets_lost": dockets})
    db.close()
    Path(out).write_text(json.dumps(frozen, ensure_ascii=False, default=list))
    print("frozen", len(frozen))

def run(frozen_path, out):
    from regulus.accuracy import evaluate, claims as CL
    from regulus.accuracy.alignment import SemanticAligner
    from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
    from regulus.retrieval import Database
    from regulus.grounding import DatabaseIdentifierIndex
    from regulus.config import load_settings
    emb = TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True)
    aligner = SemanticAligner(emb)
    db = Database.from_env(); db.connect(); index = DatabaseIdentifierIndex(db)
    res = []
    for r in json.loads(Path(frozen_path).read_text()):
        srcs = tuple(av.Src(index=s["index"], citation=s["citation"], text=s["text"], heading=s["heading"],
                            citation_fields=s["citation_fields"]) for s in r["sources"])
        reqs = tuple(tuple(x) for x in r["requirements"])
        pkg = av.Pkg(question=r["question"], requirements=reqs, satisfied_ids=tuple(r["satisfied_ids"]), sources=srcs)
        cov = av.Cov(requirements=reqs, satisfied_ids=tuple(r["satisfied_ids"]), missing_labels=tuple(r["missing_labels"]),
                     explicit=r["explicit"])
        t0 = time.perf_counter()
        a = evaluate(r["question"], r["answer"], package=pkg, coverage=cov, validation=None, model_called=r["model_called"],
                     fallback_type=r["fallback_type"], scope_status=r["scope"],
                     answerability={"state": r["answerability"]} if r["answerability"] else None,
                     identifier_index=index, aligner=aligner, evidence_provenance="legacy_reconstructed")
        ms = (time.perf_counter() - t0) * 1000
        segs = CL.segment(r["answer"], question=r["question"])
        res.append({"id": r["id"], "N": r["N"], "M": r["M"], "type": r["type"],
                    "verdict": (a.checked.get("answer_verdict") or {}).get("verdict"), "accuracy": a.accuracy,
                    "reason": a.reason, "ms": round(ms, 1),
                    "sentences": [{"text": s.text, "origin": s.origin, "reason": s.reason,
                                   "status": getattr(s, "claim_status", None)} for s in segs],
                    "claims": a.checked.get("claims", []), "candidates": a.checked.get("claim_candidates")})
    db.close()
    Path(out).write_text(json.dumps(res, ensure_ascii=False, default=str))
    print("ran", len(res))

if __name__ == "__main__":
    {"freeze": lambda: freeze(sys.argv[2]), "run": lambda: run(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
