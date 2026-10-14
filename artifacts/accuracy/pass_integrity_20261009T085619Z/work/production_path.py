"""Production configuration end to end, minus the model: configured_rag_config (as serve_ui), the real RagPipeline
with validation and repair, a scripted generation, then the evaluator exactly as serve_ui.Engine.assess calls it."""
import json, sys
sys.path.insert(0, "."); sys.path.insert(0, "artifacts/accuracy/pass_integrity_20261009T085619Z/work")
from regulus.accuracy import evaluate_safely
from regulus.accuracy.alignment import LexicalAligner
from regulus.accuracy.review import question_review
from regulus.config import load_settings
from regulus.rag import RagPipeline
from regulus.retrieval import LexicalRetriever
from regulus.system_identity import configured_rag_config
from tests.test_accuracy_observer import Scripted
from tests.test_retrieval_plan import TableDatabase
from realistic import TABLE211, TABLE180, TABLE1379, T

def run(question, response, table):
    out = RagPipeline(LexicalRetriever(TableDatabase(table)), Scripted(response), configured_rag_config(load_settings())).answer(question)
    a = evaluate_safely(out.question, out.answer, package=out.package, evidence=out.evidence_snapshot, citations=out.citations,
                        validation=out.validation, coverage=out.coverage, model_called=out.model_called,
                        fallback_type=out.metadata.get("fallback_type"),
                        scope_status=(out.metadata.get("question_analysis") or {}).get("scope_status"),
                        answerability=out.metadata.get("answerability"), aligner=LexicalAligner()).to_dict()
    return out, a, question_review(a, question=out.question)

if __name__ == "__main__":
    body = lambda c: T[c].split(") ", 1)[1]
    A, B, C = body("21 CFR 211.25(a)"), body("21 CFR 211.25(b)"), body("21 CFR 211.25(c)")
    for name, q, resp in [("full, unrestricted", "What does 21 CFR 211.25 require?", f"{A} [1] {B} [2] {C} [3]"),
                          ("(c) only, unrestricted", "What does 21 CFR 211.25 require?", f"{C} [3]"),
                          ("full, focused", "What are the personnel qualification requirements in 21 CFR 211.25?", f"{A} [1] {B} [2] {C} [3]"),
                          ("(c) only, focused", "What are the personnel qualification requirements in 21 CFR 211.25?", f"{C} [3]"),
                          ("(a) only, focused", "What are the personnel qualification requirements in 21 CFR 211.25?", f"{A} [1]")]:
        out, a, v = run(q, resp, TABLE211)
        g = out.metadata.get("generation") or {}; val = out.validation.to_dict() if out.validation else {}
        print(f"{v['label']:14} {str(v['live_check_score']):4} | {name:24} | shape={ (out.metadata.get('answer_shape') or {}).get('mode') } | repair={val.get('repair_type') or (out.metadata.get('validation') or {}).get('repair')} | codes={val.get('codes')} | answer_len={len(out.answer)}")
        print("      completeness:", next(x for x in a["dimensions"] if x["dimension"] == "completeness")["state"], "|", v["explanation"][:120])
