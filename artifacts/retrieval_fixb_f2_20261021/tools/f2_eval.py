"""F2 code experiment: 100 cosmetics questions with REGULUS_SECTION_COVERAGE_WIDE off (base) and on (wide), using the
code under test (lexical.SECTION_COVERAGE_WIDE_ENABLED toggled in this process only). Production pipeline, stub
generator, read-only database behind the guarded.py guards. Writes <out>/eval100.json only.

    python f2_eval.py <out_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/retrieval_rootcause_20261021/tools"))
import trace_retrieval as T  # noqa: E402  (-> guarded)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.planning import plan_query  # noqa: E402
from regulus.retrieval import lexical as L  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
assert L.SECTION_COVERAGE_WIDE_ENABLED is False, "run with the switch unset; this tool toggles it in process"


def hit(cits, sec, p):
    return any(T.split_cit(c)[0] == sec and (not p or (T.split_cit(c)[1] or "").startswith(f"({p})")) for c in cits)


def record(out, req):
    reg = [e.citation for e in out.evidence.evidence] if out.evidence is not None else []
    srcs = out.context.sources
    final = [s.result.citation.label for s in srcs]
    st = {}
    for sec, paras in req.items():
        for p in sorted(paras) or [""]:
            lab = f"21 CFR {sec}{'(' + p + ')' if p else ''}"
            if lab != "21 CFR 740.11(i)":
                st[lab] = {"candidate": hit(reg, sec, p), "in_context": hit(final, sec, p)}
    return {"required": st, "total_chars": out.selection.total_chars if out.selection else None,
            "sources": [{"citation": s.result.citation.label, "corpus": s.result.corpus, "key": s.result.key, "chars": len(s.text),
                         "tier": s.tier, "text": s.text} for s in srcs]}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db = Database.from_env()
    db.connect()
    res = {}
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        fp0 = RB.database_fingerprint(db)
        pipe, gen = RB.production_pipeline(db)
        for qid, q in T.SEL.items():
            question = q["Question (ask verbatim)"]
            plan = plan_query(question)
            req = T.required(q)
            res[qid] = {"question": question, "general": not plan.requirements and plan.docket is None}
            for cond, flag in (("base", False), ("wide", True)):
                L.SECTION_COVERAGE_WIDE_ENABLED = flag
                try:
                    res[qid][cond] = record(pipe.answer(question), req)
                finally:
                    L.SECTION_COVERAGE_WIDE_ENABLED = False
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    run = {"semantic_load_attempts": len(T.SEMANTIC_ATTEMPTS), "generator_calls": gen.calls,
           "database_unchanged": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
           "corpus_identity": fp0["corpus_identity"]["ecfr"]}
    (OUT / "eval100.json").write_text(json.dumps({"run": run, "questions": res}, indent=1, ensure_ascii=False, default=str))
    print(json.dumps(run, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
