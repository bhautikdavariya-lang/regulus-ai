"""Is the BASE arm still byte-identical to the 2026-10-01 acceptance run?

    .venv/bin/python scripts/sft2_determinism_check.py [--n 30]

The Oct 1 run recorded git commit, prompt hash, weights, decoding and pipeline config, but NOT the
corpus state, so nothing in the artifact proves the database is unchanged. Greedy decoding makes
the pipeline deterministic, so re-answering a stratified sample with no adapter and comparing the
final answer byte-for-byte tests the corpus and the whole pipeline at once.

Identical answers => the Oct 1 BASE arm is reusable as Arm A, with its existing hand-scored
verdicts, and Arm B is the only run needed. Any difference => Arm A must be re-run in full, and
this script says which questions diverged.

Read-only: writes one file under artifacts/sft2/ and never touches artifacts/acceptance_test/.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

BASE_RUN = ROOT / "artifacts/acceptance_test/acceptance_rev02_20261001T083958Z"
OUT = ROOT / "artifacts/sft2/determinism_check.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()
    os.environ.pop("REGULUS_ADAPTER", None)          # Arm A: no adapter

    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.rag import RagPipeline
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config

    bench = {q.question_id: q for q in load_acceptance_benchmark(ROOT / DEFAULT_WORKBOOK).questions}
    old = {json.loads(l)["question_id"]: json.loads(l)
           for l in (BASE_RUN / "answers.jsonl").read_text().splitlines() if l.strip()}

    # Stratified: the 4 held-out PASS rows and the ERROR row first (they matter most for the
    # regression analysis), then a category-proportional spread in benchmark order.
    must = [q for q in ("C-004", "G-004", "L-010", "P-010", "S-025") if q in bench]
    by_cat: dict[str, list[str]] = collections.defaultdict(list)
    for qid, q in bench.items():
        if qid not in must:
            by_cat[q.question_type].append(qid)
    pick = list(must)
    i = 0
    while len(pick) < args.n:
        added = False
        for cat in sorted(by_cat):
            if i < len(by_cat[cat]) and len(pick) < args.n:
                pick.append(by_cat[cat][i]); added = True
        if not added:
            break
        i += 1

    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    generator = load_generator(settings, local_files_only=True)
    assert settings.model.adapter is None, "adapter must be absent for the BASE arm"
    db = Database.from_env(); db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config)
    pipeline = RagPipeline(retriever, generator, config, scope_policy=scope)

    rows, identical, differing = [], 0, []
    t0 = time.perf_counter()
    for n, qid in enumerate(pick, start=1):
        prev = old.get(qid, {})
        try:
            out = pipeline.answer(bench[qid].question)
            ans, ev, err = out.answer, [s.result.citation.label for s in out.context.sources], None
        except Exception as exc:
            ans, ev, err = None, [], f"{type(exc).__name__}: {exc}"
        same_ans = (ans == prev.get("answer"))
        same_ev = (ev == prev.get("evidence"))
        if err and prev.get("execution_status") == "ERROR":
            same_ans = same_ev = True            # both arms errored: same outcome
        identical += bool(same_ans and same_ev)
        if not (same_ans and same_ev):
            differing.append(qid)
        rows.append({"question_id": qid, "category": bench[qid].question_type,
                     "answer_identical": same_ans, "evidence_identical": same_ev,
                     "error_now": err, "status_oct1": prev.get("execution_status"),
                     "answer_now_head": (ans or "")[:160], "answer_oct1_head": (prev.get("answer") or "")[:160]})
        print(f"  [{n:2}/{len(pick)}] {qid:7} answer={'SAME' if same_ans else 'DIFF'} "
              f"evidence={'SAME' if same_ev else 'DIFF'}", flush=True)

    result = {"checked": len(pick), "identical": identical, "differing": differing,
              "minutes": round((time.perf_counter() - t0) / 60, 1),
              "base_run": BASE_RUN.name, "rows": rows}
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\n{identical}/{len(pick)} byte-identical to {BASE_RUN.name} in {result['minutes']} min")
    print("differing:", differing or "NONE")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
