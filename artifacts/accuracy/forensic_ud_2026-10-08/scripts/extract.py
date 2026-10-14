"""Read-only: re-run the evaluator over the official 60 exactly as accuracy_validate does,
and dump full per-claim detail. Writes only to this scratch directory."""
import json, sys, importlib.util
from pathlib import Path
ROOT = Path.cwd()
spec = importlib.util.spec_from_file_location("av", ROOT / "scripts/accuracy_validate.py")
av = importlib.util.module_from_spec(spec); sys.modules["av"] = av; spec.loader.exec_module(av)
from regulus.accuracy.evaluator import evaluate
from regulus.accuracy.alignment import SemanticAligner
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings

OUT = Path(sys.argv[1])
official = {r["id"]: r for r in json.load(open(ROOT / "artifacts/accuracy/validation_semantic_2026-10-08T055521Z.json"))["rows"]}
rows = [json.loads(l) for l in av.DATASET.read_text().splitlines() if l.strip()]
subset = av.select(rows, 60)
assert [r["id"] for r in subset] == list(official), "subset differs from official artifact"
emb = TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True)
aligner = SemanticAligner(emb)
db = Database.from_env(); db.connect(); index = DatabaseIdentifierIndex(db); cache = {}
out = []
for row in subset:
    pkg, cov, dockets = av.build(row, db, cache)
    a = evaluate(row["question"], row["answer"] or "", package=pkg, coverage=cov, validation=None,
                 model_called=bool(row.get("model_called")), fallback_type=row.get("fallback_type"),
                 scope_status=row.get("scope"),
                 answerability={"state": row.get("answerability")} if row.get("answerability") else None,
                 identifier_index=index, aligner=aligner)
    v = a.checked.get("answer_verdict") or {}
    o = official[row["id"]]
    assert (v.get("verdict"), a.accuracy) == (o["answer_verdict"], o["accuracy"]), row["id"]
    out.append({
        "id": row["id"], "N": row["N"], "M": row.get("M"), "L": row.get("L"), "O": row.get("O"), "P": row.get("P"),
        "result": row["result"], "type": row["type"], "question": row["question"], "answer": row["answer"],
        "key_elements": row.get("key_elements"), "key_citation": row.get("key_citation_draft"),
        "rev": {k: row.get(k) for k in row if k.startswith("rev_")}, "notes": row.get("notes"), "eval": row.get("eval"),
        "model_called": row.get("model_called"), "fallback_type": row.get("fallback_type"),
        "answerability": row.get("answerability"), "validation_final": row.get("validation_final"),
        "evidence_labels": row["evidence"], "docket_labels_without_text": dockets,
        "sources": [{"citation": s.citation, "heading": s.heading, "text": s.text} for s in pkg.sources],
        "requirements": pkg.requirements, "satisfied": pkg.satisfied_ids,
        "verdict": v.get("verdict"), "accuracy": a.accuracy, "reason": a.reason, "states": a.states,
        "answer_verdict": v, "intent": a.checked.get("intent"), "abstention": a.checked.get("abstention"),
        "claims": a.checked.get("claims"), "sentences": a.checked.get("material_claims"),
        "checked_keys": sorted(a.checked),
    })
db.close()
OUT.write_text(json.dumps(out, indent=1, default=str))
print("rows", len(out), "all match official artifact")
