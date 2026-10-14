"""Step-5 focused matrix on 21 CFR 211.192. Each answer is DELIVERED by the production pipeline exactly as
serve_ui.Engine.ask builds it (configured RAG config, build_retriever, scope policy, validation/repair, evidence
snapshot), with the model replaced by a scripted response (no generation). It is then assessed exactly as
serve_ui.Engine.assess does (evidence=snapshot, semantic aligner, identifier index) and labelled by
question_review. Verbatim sentences are read from cfr_records at run time."""
from __future__ import annotations
import json, re, sys
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tests"))


class Scripted:
    def __init__(self, text): self.text = text
    def generate(self, messages, max_new_tokens=None):
        from regulus.inference.generate import GenerationResult
        return GenerationResult("p", self.text, 500, 60, 1.0, finished=True)
    def describe(self): return {"model_id": "scripted"}


def main():
    from regulus.accuracy import evaluate_safely
    from regulus.accuracy.alignment import SemanticAligner
    from regulus.accuracy.review import question_review
    from regulus.config import load_settings
    from regulus.grounding import DatabaseIdentifierIndex
    from regulus.rag import RagPipeline
    from regulus.retrieval import Database, LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
    from regulus.system_identity import configured_rag_config
    s = load_settings(); db = Database.from_env(); db.connect()
    cfg = configured_rag_config(s)
    retriever, scope = build_retriever(db, cfg, lexical=LexicalRetriever(db))
    aligner = SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=s.model.cache_dir, local_files_only=True))
    idx = DatabaseIdentifierIndex(db)
    row = db.query("SELECT body_text FROM cfr_records WHERE section_number='211.192' AND removed_on IS NULL")[0]["body_text"]
    S = [x.strip() for x in re.split(r"(?<=\.)\s+(?=[A-Z])", " ".join(row.split()))]
    assert len(S) == 4, S
    S1, S2, S3, S4 = S
    orig = json.load(open(Path(__file__).with_name("reproduce.json")))
    QF = "Under 21 CFR 211.192, what must a manufacturer do when a batch fails to meet specifications?"
    QS = {"broad": "What does 21 CFR 211.192 require?",
          "investigation": "What are the investigation requirements under 21 CFR 211.192?",
          "focused": QF}
    AS = {
        "1 verbatim S1-S4": f"{S1} {S2} {S3} {S4} [1]",
        "1b verbatim S2-S4 (omits S1)": f"{S2} {S3} {S4} [1]",
        "2 paraphrase S1-S4": ("Under 21 CFR 211.192, the quality control unit must review and approve all drug product production "
                               "and control records, including packaging and labeling records, before a batch is released or "
                               "distributed. Any unexplained discrepancy or any failure of a batch or its components to meet "
                               "specifications must be thoroughly investigated, even if the batch was already distributed. The "
                               "investigation must be extended to other batches of the same drug product and to other drug "
                               "products that may be associated with the failure. The firm must keep a written record of the "
                               "investigation, including its conclusions and follow-up. [1]"),
        "3 one unsupported material claim": (f"{S1} {S2} {S3} {S4} The manufacturer must also notify FDA of the failure "
                                             f"within 3 working days. [1]"),
        "4 omits investigation duty (S2)": f"{S1} {S3} {S4} [1]",
        "5 adjacent S2+S3 in one sentence": ("Any unexplained discrepancy or batch failure to meet specifications must be thoroughly "
                                             "investigated, and that investigation must extend to other batches of the same drug "
                                             "product and other associated drug products. A written record of the investigation, "
                                             "including conclusions and followup, must be made. [1]"),
        "6 closest-match generated answer": orig[QF]["answer"],
        "7 no inline citation": orig[QF]["answer"].replace(" [1]", ""),
        "8 pronoun-led claims": ("Under 21 CFR 211.192, a failure of a batch to meet its specifications must be thoroughly "
                                 "investigated. It must also cover other batches and other drug products that may be "
                                 "associated. This must be documented in writing with conclusions and followup. [1]"),
    }
    import os
    only = os.environ.get("ONLY")
    out = []
    for qk, q in QS.items():
        for ak, a in AS.items():
            if only and f"{qk}|{ak}" != only: continue
            pipe = RagPipeline(retriever, Scripted(a), replace(cfg, top_k=8), scope_policy=scope)
            r = pipe.answer(q)
            d = evaluate_safely(r.question, r.answer, package=r.package, evidence=r.evidence_snapshot, citations=r.citations,
                                validation=r.validation, coverage=r.coverage, model_called=r.model_called,
                                fallback_type=r.metadata.get("fallback_type"),
                                scope_status=(r.metadata.get("question_analysis") or {}).get("scope_status"),
                                answerability=r.metadata.get("answerability"), identifier_index=idx, aligner=aligner).to_dict()
            v = question_review(d, question=r.question)
            ck = d.get("checked") or {}
            rec = {"question": qk, "answer_case": ak, "label": v["label"], "score": v["live_check_score"],
                   "status": d.get("status"), "verdict": (d.get("answer_verdict") or ck.get("answer_verdict") or {}).get("verdict"),
                   "explanation": v["explanation"], "reason": d.get("reason"), "dim_detail": {x["dimension"]: x.get("detail") for x in d.get("dimensions") or []}, "answer": r.answer, "intent": ck.get("intent"), "delivered_as_given": r.answer.strip() == a.strip(),
                   "fallback_type": r.metadata.get("fallback_type"), "shape": (r.metadata.get("answer_shape") or {}).get("mode"),
                   "sources": [getattr(x, "citation", None) for x in (r.package.sources if r.package else ())],
                   "dims": {x["dimension"]: x["state"] for x in d.get("dimensions") or []},
                   "claims": [{"claim": c["claim"][:110], "support": c["support"], "basis": c.get("support_basis"),
                               "relevance": c["relevance"]["verdict"], "rel_reason": c["relevance"]["reason"][:120],
                               "final": c.get("final"), "support_reason": c.get("support_reason"), "evidence": c.get("evidence"), "citation": c.get("citation"), "citation_detail": c.get("citation_detail"), "operators": c.get("operators"), "rel_checks": c["relevance"].get("checks")} for c in ck.get("claims") or []]}
            out.append(rec)
            nonpass = {k: v_ for k, v_ in rec["dims"].items() if v_ != "pass"}
            print(f"{qk:<13} {ak:<34} {rec['label']:<20} {rec['score']!s:<4} verdict={rec['verdict']} given={rec['delivered_as_given']} "
                  f"{nonpass} {[(c['support'][:5], c['relevance'][:7]) for c in rec['claims']]}", flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    db.close()


main()
