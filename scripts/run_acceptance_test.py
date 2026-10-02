"""Run the 300-question acceptance benchmark through the current answering pipeline (answers only).

    python scripts/run_acceptance_test.py [--label acceptance_rev02]
    python scripts/run_acceptance_test.py --resume artifacts/acceptance_test/<run dir>

Each question in column F is submitted verbatim, once, to a fresh `RagPipeline.answer` call (the
pipeline is stateless per question: no conversation history, no follow-up prompt). This is the same
configured pipeline the UI serves (`configured_rag_config`, `build_retriever`, `load_generator`).

Nothing is scored here. The workbook requires an SME-verified key before scoring and says the vendor
must not score the test; the key is unverified (0/300), so `scripts/build_acceptance_results.py` only
adds machine-checkable indicators and marks rows for SME review.

Errors are recorded once, with the traceback, and are NOT retried (on --resume, rows already
recorded - including errors - are skipped). The benchmark workbook is opened read-only; its sha256
is recorded before and after the run.

Output: artifacts/acceptance_test/<label>_<utc>/ (answers.jsonl, run_metadata.json)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from regulus.config import load_settings  # noqa: E402
from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark  # noqa: E402
from regulus.rag import RagPipeline  # noqa: E402
from regulus.rag.remote_generator import load_generator  # noqa: E402
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.system_identity import configured_generation_config, configured_rag_config  # noqa: E402
from run_diagnostics import reproducibility  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record(q, out, seconds: float) -> dict:
    m = out.metadata
    gen = m.get("generation") or {}
    val = m.get("validation") or {}
    return {
        "question_id": q.question_id,
        "question": q.question,
        "execution_status": "OK",
        "seconds": seconds,
        "answer": out.answer,
        "raw_model_output": m.get("raw_model_output"),
        "model_called": out.model_called,
        "no_context": out.no_context,
        "citations": [{"index": c.index, "label": c.label} for c in out.citations],
        "evidence": [s.result.citation.label for s in out.context.sources],
        "answerability": (m.get("answerability") or {}).get("state"),
        "scope": m.get("scope"),
        "fallback_type": m.get("fallback_type"),
        "validation_initial": (val.get("initial") or {}).get("status"),
        "validation_initial_codes": (val.get("initial") or {}).get("codes"),
        "validation_final": (val.get("final") or {}).get("status"),
        "repair": val.get("repair"),
        "stop_reason": gen.get("stop_reason"),
        "generated_tokens": gen.get("generated_tokens"),
        "error": None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="acceptance_rev02")
    ap.add_argument("--resume", default=None)
    args = ap.parse_args()

    workbook = ROOT / DEFAULT_WORKBOOK
    sha_before = sha256(workbook)
    bench = load_acceptance_benchmark(workbook)
    questions = list(bench)
    if len(questions) != 300 or len({q.question_id for q in questions}) != 300:
        print(f"STOP: expected 300 unique questions, found {len(questions)}")
        return 2

    if args.resume:
        out_dir = Path(args.resume).resolve()
    else:
        out_dir = ROOT / "artifacts/acceptance_test" / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        out_dir.mkdir(parents=True, exist_ok=False)
    answers = out_dir / "answers.jsonl"
    done = set()
    if answers.exists():
        done = {json.loads(l)["question_id"] for l in answers.read_text(encoding="utf-8").splitlines() if l.strip()}

    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    generator = load_generator(settings, local_files_only=True)
    db = Database.from_env()
    db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config)
    pipeline = RagPipeline(retriever, generator, config, scope_policy=scope)

    meta_path = out_dir / "run_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.setdefault("started_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    meta.update({
        "benchmark": {"file": str(DEFAULT_WORKBOOK), "benchmark_key": bench.benchmark_key, "version": bench.to_dict()["version"],
                      "questions": len(questions), "sha256_before": meta.get("benchmark", {}).get("sha256_before", sha_before),
                      "key_verification": {k: v for k, v in bench.verification().items() if k != "unverified_ids"}},
        "active_model": {"model_id": settings.model.id, "adapter": str(settings.model.adapter) if settings.model.adapter else None,
                         "backend": settings.model.backend},
        "reproducibility": reproducibility(settings, config, retriever, generator.describe()),
        "hardware": {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()},
        "command": "python " + " ".join(sys.argv),
        "protocol": "column F verbatim; one stateless pipeline call per question; no follow-up; no retries",
    })
    meta_path.write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")

    todo = [q for q in questions if q.question_id not in done]
    print(f"{len(done)} already recorded, {len(todo)} to run -> {out_dir}", flush=True)
    t_start = time.perf_counter()
    with answers.open("a", encoding="utf-8") as f:
        for n, q in enumerate(todo, start=1):
            t0 = time.perf_counter()
            try:
                out = pipeline.answer(q.question)
                row = record(q, out, round(time.perf_counter() - t0, 2))
            except Exception as exc:   # recorded once, never retried
                row = {"question_id": q.question_id, "question": q.question, "execution_status": "ERROR",
                       "seconds": round(time.perf_counter() - t0, 2), "answer": None,
                       "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-4000:]}
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            el = time.perf_counter() - t_start
            print(f"{len(done) + n:3}/300 {q.question_id:8} {row['execution_status']:5} {row['seconds']:6.1f}s "
                  f"| elapsed {el / 60:5.1f} min, ~{el / n * (len(todo) - n) / 60:5.1f} min left", flush=True)
    db.close()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["benchmark"]["sha256_after"] = sha256(workbook)
    meta["benchmark"]["unchanged"] = meta["benchmark"]["sha256_after"] == meta["benchmark"]["sha256_before"]
    meta_path.write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    print("benchmark unchanged:", meta["benchmark"]["unchanged"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
