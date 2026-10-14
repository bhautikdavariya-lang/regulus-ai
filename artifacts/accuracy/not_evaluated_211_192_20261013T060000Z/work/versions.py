"""Score the SAME answer, against the same production evidence, under whichever evaluator `regulus` resolves to
(selected by PYTHONPATH). The package is built by the production pipeline; the evaluator is called as
serve_ui.Engine.assess calls it (semantic aligner). Prints one JSON line."""
import json, sys
from dataclasses import replace
Q, A = sys.argv[1], sys.argv[2]


class Stub:
    def describe(self): return {}
    def generate(self, *a, **k): raise AssertionError


def main():
    import regulus.accuracy.evaluator as E
    from regulus.accuracy import evaluate_safely
    from regulus.accuracy.alignment import SemanticAligner
    from regulus.accuracy.review import question_review
    from regulus.config import load_settings
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.generation import build_package
    from regulus.retrieval import Database, Filters, LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
    from regulus.system_identity import configured_rag_config
    s = load_settings(); db = Database.from_env(); db.connect()
    cfg = replace(configured_rag_config(s), top_k=8)
    r, sc = build_retriever(db, cfg, lexical=LexicalRetriever(db)); pipe = RagPipeline(r, Stub(), cfg, scope_policy=sc)
    plan = pipe.complete_plan(plan_query(Q)); shape, an = pipe.question_view(plan)
    out = r.run_plan(plan, corpus=cfg.corpus, top_k=cfg.top_k, filters=Filters())
    b, cov, sel = pipe.build_bundle(out.response, out.registry, shape, Q)
    pkg = build_package(plan, cov, sel, notes=b.notes, budget=pipe.config.generation_budget, answer_shape=shape,
                        question_analysis=an)
    aligner = SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=s.model.cache_dir, local_files_only=True))
    a = evaluate_safely(Q, A, package=pkg, coverage=cov, aligner=aligner)       # as serve_ui.Engine.assess
    d = a.to_dict(); rv = question_review(d, question=Q)
    print(json.dumps({"evaluator": E.__file__, "label": rv["label"], "score": rv["live_check_score"], "status": d.get("status"),
                      "why": rv["explanation"], "dims": {x["dimension"]: x["state"] for x in d.get("dimensions") or []},
                      "claims": [{"claim": c["claim"], "support": c["support"], "basis": c.get("support_basis"),
                                  "support_reason": c.get("support_reason"), "relevance": c["relevance"]["verdict"],
                                  "relevance_reason": c["relevance"]["reason"],
                                  "aligned": [e.get("text") for e in c.get("evidence") or []][:2]}
                                 for c in (d.get("checked") or {}).get("claims") or []]}))
    db.close()


main()
