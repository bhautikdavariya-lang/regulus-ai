"""Is the C1+C2+C3 pipeline deterministic? Two passes over the same 30 questions.

    .venv/bin/python scripts/c123_determinism_check.py

The subset is the one the base determinism check used (artifacts/sft2/determinism_check.json),
so the two checks are comparable. Greedy decoding and lexical retrieval make the pipeline
deterministic by construction; this tests that empirically, with C1 (relevance-ranked part
stems), C2 (part section expansion) and C3 (cross-section range expansion) all enabled and no
adapter. S-025 is a known transient (database timeout) in the base check.

Read-only with respect to the benchmark and to every existing artifact: writes one new file.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

SUBSET = ROOT / "artifacts/sft2/determinism_check.json"
OUT = ROOT / "artifacts/acceptance_test/c123_determinism.json"


def main() -> int:
    os.environ.pop("REGULUS_ADAPTER", None)  # no adapter, as the frozen configuration requires

    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.rag import RagPipeline
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config

    ids = [r["question_id"] for r in json.loads(SUBSET.read_text(encoding="utf-8"))["rows"]]
    bench = load_acceptance_benchmark(ROOT / DEFAULT_WORKBOOK)
    questions = {q.question_id: q for q in bench}
    todo = [questions[i] for i in ids]
    print(f"{len(todo)} questions, two passes", flush=True)

    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    generator = load_generator(settings, local_files_only=True)
    db = Database.from_env()
    db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config)
    pipeline = RagPipeline(retriever, generator, config, scope_policy=scope)
    assert settings.model.adapter is None, "an adapter is configured; this run must have none"

    def one_pass(tag: str) -> dict:
        out = {}
        t0 = time.perf_counter()
        for n, q in enumerate(todo, start=1):
            try:
                a = pipeline.answer(q.question)
                sel = (a.metadata.get("selection") or {})
                out[q.question_id] = {
                    "answer": a.answer,
                    "evidence": [s.result.citation.label for s in a.context.sources],
                    "citations": [c.label for c in a.citations],
                    "model_called": a.model_called,
                    "generated_tokens": ((a.metadata.get("generation") or {}).get("generated_tokens")),
                    "coverage": (a.metadata.get("coverage") or {}).get("state"),
                    "selected_sources": len(sel.get("selected", [])) or None,
                    "total_chars": sel.get("total_chars"),
                    "error": None,
                }
            except Exception as exc:
                out[q.question_id] = {"error": f"{type(exc).__name__}: {exc}", "answer": None}
            print(f"  {tag} {n:2}/{len(todo)} {q.question_id:8} "
                  f"{'ERR' if out[q.question_id]['error'] else 'ok'} "
                  f"({(time.perf_counter() - t0) / 60:.1f} min)", flush=True)
        return out

    first = one_pass("pass1")
    second = one_pass("pass2")
    db.close()

    rows, identical, differing = [], 0, []
    for qid in ids:
        a, b = first[qid], second[qid]
        same_answer = a.get("answer") == b.get("answer")
        same_ev = a.get("evidence") == b.get("evidence")
        same = same_answer and same_ev and a.get("error") == b.get("error") and a.get("citations") == b.get("citations")
        identical += bool(same)
        if not same:
            differing.append(qid)
        rows.append({"question_id": qid, "identical": same, "answer_identical": same_answer,
                     "evidence_identical": same_ev, "error_pass1": a.get("error"), "error_pass2": b.get("error"),
                     "coverage": a.get("coverage"), "selected_sources": a.get("selected_sources"),
                     "total_chars": a.get("total_chars"),
                     "answer_head_pass1": (a.get("answer") or "")[:140],
                     "answer_head_pass2": (b.get("answer") or "")[:140]})

    result = {"checked": len(ids), "identical": identical, "differing": differing,
              "known_transient": ["S-025"], "arms": "C1+C2+C3, no adapter", "rows": rows}
    OUT.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(f"\n{identical}/{len(ids)} identical; differing: {differing or 'none'} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
