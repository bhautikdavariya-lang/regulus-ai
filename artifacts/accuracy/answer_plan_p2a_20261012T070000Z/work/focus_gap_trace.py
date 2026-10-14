"""Which requirement groups does _focus_gap treat as on-topic, with the section heading counted and
without it? Production packages, no model."""
from __future__ import annotations
import sys
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(Path(__file__).parent))
from prompts import PROBES, Stub  # noqa: E402


def main():
    from regulus.accuracy import operators as OP, relevance as RV
    from regulus.accuracy.alignment import Passage
    from regulus.accuracy.intent import analyze as analyze_intent
    from regulus.config import load_settings
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.generation import build_package
    from regulus.retrieval import Database, Filters, LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config
    settings = load_settings(); db = Database.from_env(); db.connect()
    config = replace(configured_rag_config(settings), top_k=8)
    retriever, scope = build_retriever(db, config, lexical=LexicalRetriever(db))
    pipe = RagPipeline(retriever, Stub(), config, scope_policy=scope)
    for qid, q in PROBES:
        if not qid.startswith(("P1", "P2", "P4")):
            continue
        plan = pipe.complete_plan(plan_query(q)); shape, analysis = pipe.question_view(plan)
        out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
        bundle, coverage, sel = pipe.build_bundle(out.response, out.registry, shape, q)
        pkg = build_package(plan, coverage, sel, notes=bundle.notes, budget=pipe.config.generation_budget,
                            answer_shape=shape, question_analysis=analysis)
        intent = analyze_intent(q)
        by_index = {s.index: s for s in pkg.sources}
        print(f"### {qid}  topic={intent.topic}")
        for g in pkg.answer_plan.groups:
            if g.kind != "requirement":
                continue
            mem = [by_index[i] for i in g.members if i in by_index]
            if not any(OP.strength(s.text) == OP.MANDATORY for s in mem):
                continue
            with_h = [Passage(s.index, s.citation, s.tier, s.text, s.heading) for s in mem]
            no_h = [Passage(s.index, s.citation, s.tier, s.text, None) for s in mem]
            on_with, on_without = bool(RV.on_topic(intent, with_h)), bool(RV.on_topic(intent, no_h))
            print(f"   {g.label:<24} members={list(g.members)!s:<22} on_topic(heading+text)={on_with!s:<5} on_topic(text only)={on_without}")
    db.close()


if __name__ == "__main__":
    main()
