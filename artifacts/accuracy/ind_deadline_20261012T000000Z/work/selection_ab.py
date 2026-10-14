"""Blast radius of the relevance-ordered required-evidence fix, over all 300 benchmark questions.

Retrieval -> coverage -> selection only; no model is loaded and no answer is generated, so this is
not a benchmark run and it writes nothing but its own output file. For each question the bundle is
built TWICE from the same retrieval: once without the question (document order, the behaviour
before this change) and once with it (relevance-ordered competition for the hard ceiling).

    .venv/bin/python artifacts/.../work/selection_ab.py out.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))


class Stub:
    def describe(self): return {"generator": "none (selection A/B)"}
    def generate(self, *a, **k): raise AssertionError("the A/B pass must not generate")


def main() -> int:
    out_path = Path(sys.argv[1])
    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.retrieval import Database, Filters
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config

    settings = load_settings()
    db = Database.from_env(); db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config)
    pipeline = RagPipeline(retriever, Stub(), config, scope_policy=scope)
    bench = load_acceptance_benchmark(ROOT / DEFAULT_WORKBOOK)

    res = {}
    for n, q in enumerate(bench, start=1):
        plan = pipeline.complete_plan(plan_query(q.question))
        shape, _ = pipeline.question_view(plan)
        out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
        b_off, _, s_off = pipeline.build_bundle(out.response, out.registry, shape)           # before
        b_on, _, s_on = pipeline.build_bundle(out.response, out.registry, shape, q.question)  # after
        off = [s.evidence.citation for s in s_off.selected] if s_off else []
        on = [s.evidence.citation for s in s_on.selected] if s_on else []
        res[q.question_id] = {
            "question": q.question,
            "identical_context": b_off.text == b_on.text,
            "identical_set": sorted(off) == sorted(on),
            "identical_order": off == on,
            "n_off": len(off), "n_on": len(on),
            "chars_off": s_off.total_chars if s_off else 0, "chars_on": s_on.total_chars if s_on else 0,
            "overflow": bool(s_off.overflow) if s_off else False,
            "relevance_used": bool(s_on and s_on.diagnostics.get("required_order") == "relevance"),
            "gained": sorted(set(on) - set(off)), "lost": sorted(set(off) - set(on)),
        }
        if n % 50 == 0:
            print(f"  {n}/300", flush=True)
    db.close()
    out_path.write_text(json.dumps(res, indent=0, default=str), encoding="utf-8")

    rows = list(res.values())
    changed = [r for r in rows if not r["identical_context"]]
    print(f"\n300 questions. identical context: {len(rows)-len(changed)}  changed: {len(changed)}")
    print(f"  overflow (required evidence did not fit): {sum(1 for r in rows if r['overflow'])}")
    print(f"  relevance decided the competition:        {sum(1 for r in rows if r['relevance_used'])}")
    print(f"  same set, different order:                {sum(1 for r in changed if r['identical_set'])}")
    print(f"  different set:                            {sum(1 for r in changed if not r['identical_set'])}")
    print(f"  source count changed:                     {sum(1 for r in changed if r['n_off'] != r['n_on'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
