"""Real answers (production engine, greedy; NOT scripted) to named-section synthesis questions, each generated
ONCE and assessed under production and under TU3. Bounded: six questions. The candidate patch is active while
the answer is built (so the package carries `withheld`), which cannot change the prompt or the answer."""
from __future__ import annotations
import json, sys
from dataclasses import replace
from pathlib import Path
HERE = Path(__file__).parent; ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(HERE))
from proto import patched  # noqa: E402

QS = ["What does 21 CFR 211.25 require?", "What does 21 CFR 312.32 require?", "What does 21 CFR 211.67 require?",
      "What does 21 CFR 111.12 require?", "What does 21 CFR 117.40 require?", "What does 21 CFR 820.10 require?"]


def main():
    from regulus.config import load_settings
    from regulus.rag import QwenGenerator, RagPipeline
    from regulus.retrieval import LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config
    from serve_ui import Engine
    from regulus.accuracy.review import question_review
    e = Engine(load_settings(), offline=True)
    config = configured_rag_config(e.settings); budget = config.generation_budget
    gen = replace(configured_generation_config(e.settings), max_new_tokens=budget.hard_max_tokens)
    retriever, scope = build_retriever(e.db, config, lexical=LexicalRetriever(e.db))
    model, _ = e.model_for("")
    pipe = RagPipeline(retriever, QwenGenerator(model, e.tokenizer, gen, e.settings.model.id),
                       replace(config, top_k=8, generation_budget=budget), scope_policy=scope)
    out = {}
    for q in QS:
        with patched("TU3"):
            ans = pipe.answer(q)
            tu3 = e.assess(ans).to_dict()
        prod = e.assess(ans).to_dict()
        rec = {"answer": ans.answer, "mode": (ans.metadata.get("answer_shape") or {}).get("mode"),
               "withheld": len(getattr(ans.package, "withheld", ()))}
        for name, d in (("production", prod), ("TU3", tu3)):
            rv = question_review(d, question=q)
            comp = next((x for x in d.get("dimensions") or [] if x["dimension"] == "completeness"), {})
            rec[name] = {"label": rv["label"], "score": rv["live_check_score"], "completeness": comp.get("state"),
                         "detail": str(comp.get("detail"))[:170]}
        out[q] = rec
        print(f"{q:<36} mode={rec['mode']:<10} withheld={rec['withheld']:<3} production={rec['production']['label']} "
              f"{rec['production']['score']} [{rec['production']['completeness']}]  ->  TU3={rec['TU3']['label']} "
              f"{rec['TU3']['score']} [{rec['TU3']['completeness']}]", flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
