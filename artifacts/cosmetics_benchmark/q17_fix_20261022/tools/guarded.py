"""Retrieval-only runs under two guards, for the literal-"or" experiment. No model is ever loaded.

    python guarded.py baseline352 -- <scripts/retrieval_baseline.py arguments>   run the existing 352-row harness
    python guarded.py cosmetics <out.jsonl>                                    replay the 100 cosmetics questions
    python guarded.py tsquery <text> [<text> ...]                              how PostgreSQL parses each text

Guards, installed before anything runs:
  * the semantic fallback's loader raises (its only path to an embedding model); every attempt is counted
    and printed, so a run that needed it is visible rather than silently different;
  * Database.query refuses any statement that is not SELECT/WITH (the session is read-only as well).
The generation step is the harness's NoGenerator stub. The REGULUS_ECFR_LITERAL_OR switch is read from the
environment by the code under test, exactly as in production.
"""
from __future__ import annotations

import json
import re
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True

import regulus.retrieval.semantic.loaders as SL  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

SEMANTIC_ATTEMPTS = []


def _refuse(*a, **k):
    SEMANTIC_ATTEMPTS.append(1)
    raise RuntimeError("semantic loader refused: retrieval-only run, no model may be loaded")


SL.load_semantic_retriever = _refuse
_query = Database.query


def _select_only(self, statement, params=None, *a, **k):
    body = re.sub(r"--[^\n]*", " ", statement)
    if not re.match(r"(?is)^\s*(select|with)\b", body):
        raise RuntimeError("non-SELECT statement refused")
    return _query(self, statement, params, *a, **k)


Database.query = _select_only


def cosmetics(out_path: str) -> None:
    from regulus.evaluation import retrieval_baseline as RB

    sel = json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json")
                     .read_text(encoding="utf-8"))["questions"]
    db = Database.from_env()
    db.connect()
    try:
        st = {k: v for k, v in db.status().items() if k != "url"}
        assert st["default_transaction_read_only"] == "on", st
        fp0 = RB.database_fingerprint(db)
        pipe, gen = RB.production_pipeline(db)
        with open(out_path, "w", encoding="utf-8") as f:
            for q in sel:
                out = pipe.answer(q["Question (ask verbatim)"])
                md = out.metadata
                f.write(json.dumps({
                    "id": q["ID"],
                    "sources": [[s.result.citation.label, s.result.retrieval_method, s.tier, s.text] for s in out.context.sources],
                    "dropped": [[d.get("citation"), d.get("reason")] for d in (md.get("selection") or {}).get("dropped") or []],
                    "retrieval": md.get("retrieval"),
                }, ensure_ascii=False, default=str) + "\n")
        fp1 = RB.database_fingerprint(db)
    finally:
        db.close()
    unchanged = all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))
    print(f"cosmetics: {len(sel)} questions -> {out_path}; generation stub calls {gen.calls}; "
          f"semantic load attempts {len(SEMANTIC_ATTEMPTS)}; database unchanged {unchanged}")


def tsquery(texts: list[str]) -> None:
    db = Database.from_env()
    db.connect()
    try:
        for t in texts:
            row = db.query("SELECT websearch_to_tsquery('english', %(q)s)::text AS q", {"q": t})[0]
            print(f"{t!r:60} -> {row['q']}")
    finally:
        db.close()


def main() -> int:
    mode = sys.argv[1]
    if mode == "baseline352":
        sys.argv = [str(ROOT / "scripts/retrieval_baseline.py")] + sys.argv[sys.argv.index("--") + 1:]
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as exc:
            print(f"harness exit {exc.code}; semantic load attempts {len(SEMANTIC_ATTEMPTS)}")
            return int(exc.code or 0)
        print(f"semantic load attempts {len(SEMANTIC_ATTEMPTS)}")
        return 0
    if mode == "cosmetics":
        cosmetics(sys.argv[2])
        return 0
    if mode == "tsquery":
        tsquery(sys.argv[2:])
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
