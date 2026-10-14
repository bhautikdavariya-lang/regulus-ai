"""Evaluate fixed answer texts against the PRODUCTION package for "How quickly ...?": the real
retrieval, selection and package (section headings included), then the evaluator in-process.
No model. Compares with the test harness (`judge`, which builds sources without headings)."""
from __future__ import annotations
import json, sys
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from prompts import Stub  # noqa: E402

Q = "How quickly must IND safety reports be submitted under 21 CFR 312.32?"
ANSWERS = {
    "paraphrased_correct_7": ("The sponsor must notify FDA of any unexpected fatal or life-threatening suspected adverse "
                              "reaction no later than 7 calendar days after the sponsor's initial receipt of the information. [9]"),
    "both_correct_paraphrased": ("The sponsor must submit an IND safety report no later than 15 calendar days after "
                                 "determining that the information qualifies for reporting. [2]\n\nThe sponsor must notify "
                                 "FDA of any unexpected fatal or life-threatening suspected adverse reaction no later than "
                                 "7 calendar days after the sponsor's initial receipt of the information. [9]"),
    "reversed_15_for_fatal": ("The sponsor must notify FDA of any unexpected fatal or life-threatening suspected adverse "
                              "reaction no later than 15 calendar days after initial receipt of the information. [9]"),
}


def main():
    from regulus.accuracy import evaluate_safely
    from regulus.config import load_settings
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.generation import build_package
    from regulus.retrieval import Database, Filters, LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config
    from tests.test_accuracy_claim_extraction import judge
    settings = load_settings(); db = Database.from_env(); db.connect()
    config = replace(configured_rag_config(settings), top_k=8)
    retriever, scope = build_retriever(db, config, lexical=LexicalRetriever(db))
    pipe = RagPipeline(retriever, Stub(), config, scope_policy=scope)
    plan = pipe.complete_plan(plan_query(Q)); shape, analysis = pipe.question_view(plan)
    out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
    bundle, coverage, sel = pipe.build_bundle(out.response, out.registry, shape, Q)
    pkg = build_package(plan, coverage, sel, notes=bundle.notes, budget=pipe.config.generation_budget,
                        answer_shape=shape, question_analysis=analysis)
    src9 = next(s for s in pkg.sources if s.index == 9)
    print(f"production SOURCE 9: {src9.citation} heading={src9.heading!r}\n")
    harness_sources = [(s.citation, s.text) for s in pkg.sources]
    res = {}
    for name, ans in ANSWERS.items():
        for where, a in (("PRODUCTION", evaluate_safely(Q, ans, package=pkg, coverage=coverage)),
                         ("HARNESS", judge(Q, ans, harness_sources))):
            d = a.to_dict()
            dims = {x["dimension"]: x["state"] for x in d["dimensions"]}
            rels = [(c["relevance"]["verdict"], c["support"]) for c in a.checked["claims"]]
            print(f"{name:<26} {where:<10} verdict={d['answer_verdict']['verdict']:<13} relevance={dims.get('question_relevance'):<8} "
                  f"substantive={dims.get('substantive_correctness'):<9} claims(rel,support)={rels}")
            if where == "PRODUCTION":
                res[name] = {"dims": dims, "claims": a.checked["claims"], "verdict": d["answer_verdict"]}
    db.close()
    Path(sys.argv[1]).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
