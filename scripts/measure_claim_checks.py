"""Measure the Stage 7 claim-level checks on recorded answers before enforcing them (no model).

    python scripts/measure_claim_checks.py <run dir>

Rebuilds each generated question's package exactly as the run built it (lexical retriever, the run's
configuration; the prompt hash must match the trace), validates the recorded RAW model output and the
FINAL answer, and lists every claim-level finding next to the question's reviewed verdict.
"""
import json, sys, dataclasses
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from regulus.config import load_settings
from regulus.inference.types import GenerationResult
from regulus.observability.trace import sha256
from regulus.planning import plan_query
from regulus.rag import RagPipeline
from regulus.rag.claim_validation import CLAIM_CODES
from regulus.rag.generation import build_grounded_messages, build_package
from regulus.rag.validation import validate_answer
from regulus.retrieval import Database, LexicalRetriever
from run_diagnostics import configured_rag_config


def first(p):
    o = {}
    for l in open(p, encoding="utf-8"):
        if l.strip():
            r = json.loads(l); o.setdefault(r["question_id"], r)
    return o


run = Path(sys.argv[1])
traces, diags = first(run / "traces.jsonl"), first(run / "diagnoses.jsonl")
reviews = first(run / "manual_review.jsonl") if (run / "manual_review.jsonl").exists() else {}
db = Database.from_env(); db.connect()
cfg = dataclasses.replace(configured_rag_config(load_settings()), semantic_fallback="off")
pipe = RagPipeline(LexicalRetriever(db), None, cfg)   # the Stage 6 retrieval path, no scope policy
rows, mismatched = [], []
for q, t in traces.items():
    if not t["model_called"]:
        continue
    plan = plan_query(t["question"]); sh, an = pipe.question_view(plan)
    r, reg = pipe.retrieve(t["question"], plan); b, cov, sel = pipe.build_bundle(r, reg, sh)
    pkg = build_package(plan, cov, sel, notes=b.notes, budget=cfg.generation_budget, answer_shape=sh, question_analysis=an)
    if sha256(build_grounded_messages(pkg)) != t["prompt_hash"]:
        mismatched.append(q); continue
    gen = GenerationResult("", t["raw_model_output"] or "", t["prompt_token_count"] or 0, t["output_token_count"] or 0, 0.0, finished=t["finished"])
    status = (reviews.get(q) or {}).get("reviewed_status", diags[q]["final_status"]).split(" ")[0]
    for which, text in (("raw", t["raw_model_output"] or ""), ("final", t["final_answer"])):
        rep = validate_answer(text, pkg, gen)
        for p in rep.problems:
            if p.code in CLAIM_CODES:
                rows.append({"id": q, "status": status, "text": which, "code": p.code, "detail": p.detail, "sentence": (p.sentence or "")[:160]})
out = ROOT / "artifacts/validation_eval" / f"claim_checks_{run.name}.jsonl"
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("prompt-hash mismatches (skipped):", mismatched)
for r in rows:
    print(f"{r['id']:9} {r['status']:24} {r['text']:5} {r['code']:25} {r['detail'][:90]} | {r['sentence'][:80]}")
print("wrote", out)
