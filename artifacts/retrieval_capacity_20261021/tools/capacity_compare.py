"""Bounded capacity comparison (PREREGISTRATION.md): production vs T4800, T6000, H3600, read-only and in process.

    python capacity_compare.py <out_dir>

Every candidate is the production pipeline (configured RagConfig, SemanticFallbackRetriever + ScopePolicy, stub
generator) with one ContextPolicy value overridden in this process (T4800, T6000), or with the budget charged for a
compact header instead of the full rendered block (H3600: selection._block_chars is patched only while that
candidate answers). Runs the 100 cosmetics questions for every condition, and the 352-row set for each candidate. The
352 production records are the reused baseline run retrieval_baseline_20261021T102326Z_16fa796d (same code, same
database identity). Writes <out_dir>/compare.json and <out_dir>/runs_352/<cand>.jsonl only. No code, prompt,
configuration or database change.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/retrieval_rootcause_20261021/tools"))
import trace_retrieval as T  # noqa: E402  (-> guarded: SELECT-only, semantic loader refused; literal-OR switch unset)

from regulus.config import load_settings  # noqa: E402
from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.rag import selection as SELM  # noqa: E402
from regulus.rag.context import ContextSource  # noqa: E402
from regulus.rag.pipeline import RagPipeline  # noqa: E402
from regulus.retrieval import lexical as L  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.system_identity import configured_rag_config  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
BASE352 = ROOT / "data/evaluation/results/retrieval_baseline_20261021T102326Z_16fa796d/per_question.jsonl"
FULL_BLOCK = SELM._block_chars


def compact_block(evidence, text, index, truncated):
    """Charge = 'SOURCE n' + Citation line + 'Text:' + the text; the rendered prompt itself is not changed."""
    return len(f"SOURCE {index}\nCitation: {evidence.result.citation.label}\nText:\n{text}")


def pipeline(db, **context):
    config = configured_rag_config(load_settings())
    if context:
        config = replace(config, context=replace(config.context, **context))
    retriever, scope = build_retriever(db, config, lexical=L.LexicalRetriever(db))
    gen = RB.NoGenerator()
    return RagPipeline(retriever, gen, replace(config, top_k=8), grounding=None, scope_policy=scope), gen


def ctx(out, req):
    srcs = [{"citation": s.result.citation.label, "corpus": s.result.corpus, "key": s.result.key, "chars": len(s.text),
             "tier": s.tier} for s in out.context.sources]
    final = [s["citation"] for s in srcs]
    status = {}
    for sec, paras in req.items():
        for p in sorted(paras) or [""]:
            lab = f"21 CFR {sec}{'(' + p + ')' if p else ''}"
            if lab == "21 CFR 740.11(i)":
                continue
            status[lab] = any(T.split_cit(c)[0] == sec and (not p or (T.split_cit(c)[1] or "").startswith(f"({p})")) for c in final)
    rendered = len(out.context.text) if getattr(out.context, "text", None) is not None else None
    return {"sources": srcs, "required": status, "total_chars": out.selection.total_chars if out.selection else None,
            "rendered_chars": rendered}


def answer(pipe, question, compact):
    if compact:
        SELM._block_chars = compact_block
    try:
        return pipe.answer(question)
    finally:
        SELM._block_chars = FULL_BLOCK


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs_352").mkdir(exist_ok=True)
    db = Database.from_env()
    db.connect()
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        fp0 = RB.database_fingerprint(db)
        conds = {"base": (pipeline(db), False), "T4800": (pipeline(db, max_total_chars=4800), False),
                 "T6000": (pipeline(db, max_total_chars=6000), False), "H3600": (pipeline(db), True)}
        q100 = {}
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            req = T.required(q)
            q100[qid] = {"general": not plan_query(question).requirements and plan_query(question).docket is None,
                         **{c: ctx(answer(p, question, compact), req) for c, ((p, g), compact) in conds.items()}}
        rows = RB.load_dataset()
        lookup = RB.CorpusLookup(db)
        summ352 = {}
        for c, ((p, g), compact) in conds.items():
            if c == "base":
                continue
            recs = []
            with (OUT / "runs_352" / f"{c}.jsonl").open("w", encoding="utf-8") as f:
                for row in rows:
                    if compact:
                        SELM._block_chars = compact_block
                    try:
                        rec = RB.run_question(p, g, lookup, row)
                    finally:
                        SELM._block_chars = FULL_BLOCK
                    recs.append(rec)
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            summ352[c] = RB.summarise(recs)
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    run = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS),
           "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
           "corpus_identity": fp0["corpus_identity"]["ecfr"]}
    (OUT / "compare_raw.json").write_text(json.dumps({"run": run, "q100": q100, "summary_352": summ352}, indent=1, default=str))
    print(json.dumps(run, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
