"""Run the 300-question acceptance benchmark through the current answering pipeline (answers only).

    python scripts/run_acceptance_test.py [--label acceptance_rev02]
    python scripts/run_acceptance_test.py --resume artifacts/acceptance_test/<run dir>
    python scripts/run_acceptance_test.py --evaluate-offline artifacts/acceptance_test/<run dir> [--evaluation-out F]
                                          [--offline-aligner lexical|semantic]

Each question in column F is submitted verbatim, once, to a fresh `RagPipeline.answer` call (the
pipeline is stateless per question: no conversation history, no follow-up prompt). This is the same
configured pipeline the UI serves (`configured_rag_config`, `build_retriever`, `load_generator`).

Nothing is scored here. The workbook requires an SME-verified key before scoring and says the vendor
must not score the test; the key is unverified (0/300), so `scripts/build_acceptance_results.py` only
adds machine-checkable indicators and marks rows for SME review.

Errors are recorded once, with the traceback, and are NOT retried (on --resume, rows already
recorded - including errors - are skipped). The benchmark workbook is opened read-only; its sha256
is recorded before and after the run.

Beside each answers.jsonl row a measurement record is written to measurement.jsonl
(regulus.traceability.measurement): the raw model output, the validated draft where the pipeline
exposes it, the delivered answer, the exact evidence, both validation reports and the repair, each
hashed, so the answer can be rescored later from what this run actually had. It is captured after
the answer is final and never alters the answers.jsonl row; a capture failure is written as a
capture_error record for that question only. No evaluator is called when answering.

--evaluate-offline is a separate operation on a finished run: it loads no model, database or workbook,
answers nothing, and assesses each saved answer against its saved evidence
(regulus.evaluation.offline_evaluation). Results go to a NEW file, by default
artifacts/offline_evaluation/<run>/<utc>_<execution id>.jsonl; the run's own files are only read.

Output: artifacts/acceptance_test/<label>_<utc>/ (answers.jsonl, measurement.jsonl, run_metadata.json)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from regulus.accuracy.rubric import RUBRIC_ID, RUBRIC_VERSION  # noqa: E402
from regulus.config import load_settings  # noqa: E402
from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark  # noqa: E402
from regulus.rag import RagPipeline  # noqa: E402
from regulus.rag.remote_generator import load_generator  # noqa: E402
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.system_identity import configured_generation_config, configured_rag_config  # noqa: E402
from regulus.traceability import measurement as M  # noqa: E402
from regulus.traceability.corpus import corpus_identity  # noqa: E402
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
        # the exact evidence placed in the prompt, fingerprinted (regulus.traceability); replayable as-is
        "evidence_snapshot": out.evidence_snapshot.to_dict() if out.evidence_snapshot is not None else None,
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


def run_identity(out_dir: Path, meta: dict) -> dict:
    """What every measurement record of this run carries about the run, from run_metadata.json."""
    rep, model, bench = meta.get("reproducibility") or {}, meta.get("active_model") or {}, meta.get("benchmark") or {}
    try:   # tracked changes only: an untracked file is not covered
        diff = subprocess.run(["git", "diff", "HEAD"], cwd=ROOT, capture_output=True, timeout=30, check=True).stdout
        diff_sha = hashlib.sha256(diff).hexdigest()
    except Exception:
        diff_sha = None
    return {
        "run_id": out_dir.name, "run_started_utc": meta.get("started_utc"),
        "model": {**{k: rep.get(k) for k in ("model_id", "model_revision", "weights_sha256", "device", "dtype")},
                  "adapter": model.get("adapter"), "backend": model.get("backend")},
        "generation_config": rep.get("decoding"),
        "system_prompt_sha256": rep.get("system_prompt_sha256"),
        "pipeline_config_sha256": M.sha256_json(rep.get("pipeline_config")),
        "code_revision": {"git_commit": rep.get("git_commit"), "git_dirty": rep.get("git_dirty"),
                          "tracked_diff_sha256": diff_sha},
        # no evaluator version identifier exists; the code revision is what identifies the evaluator
        "evaluator": {"rubric_id": RUBRIC_ID, "rubric_version": RUBRIC_VERSION, "evaluator_version": None},
        "benchmark": {k: bench.get(k) for k in ("benchmark_key", "version", "sha256_before")},
        # the text the evidence came from (database snapshot and semantic index), as it was when the run started
        "corpus": meta.get("corpus"),
    }


def run_questions(pipeline, todo, ordinals: dict, run: dict, out_dir: Path, progress=None) -> None:
    """Answer each question once and append its row, then its measurement record. The answers.jsonl
    row is written first and is exactly what it was before measurement existed."""
    with (out_dir / "answers.jsonl").open("a", encoding="utf-8") as f, \
            (out_dir / M.MEASUREMENT_FILE).open("a", encoding="utf-8") as mf:
        for n, q in enumerate(todo, start=1):
            t0 = time.perf_counter()
            ident = dict(question_id=q.question_id, ordinal=ordinals[q.question_id], question=q.question, run=run)
            try:
                out = pipeline.answer(q.question)
                row = record(q, out, round(time.perf_counter() - t0, 2))
            except Exception as exc:   # recorded once, never retried
                row = {"question_id": q.question_id, "question": q.question, "execution_status": "ERROR",
                       "seconds": round(time.perf_counter() - t0, 2), "answer": None,
                       "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-4000:]}
                measured = M.failure_record(**ident, captured_utc=_now(), status=M.STATUS_PIPELINE_ERROR,
                                            error=row["error"])
            else:
                measured = M.capture_safely(**ident, out=out, captured_utc=_now())
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            mf.write(json.dumps(measured, ensure_ascii=False, sort_keys=True) + "\n")
            mf.flush()
            if progress is not None:
                progress(n, q, row)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evaluate_offline(run_dir: Path, out: str | None, aligner: str = "lexical") -> int:
    from regulus.evaluation.offline_evaluation import evaluate_run, semantic_aligner

    execution_id = uuid.uuid4().hex
    out_path = (Path(out).resolve() if out else ROOT / "artifacts/offline_evaluation" / run_dir.name
                / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{execution_id[:12]}.jsonl")
    summary = evaluate_run(run_dir, out_path, root=ROOT, execution_id=execution_id,
                           aligner=semantic_aligner() if aligner == "semantic" else None)
    print(json.dumps(summary, indent=1))
    return 0 if summary["inputs_unchanged"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="acceptance_rev02")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--resume", default=None)
    mode.add_argument("--evaluate-offline", default=None, metavar="RUN_DIR",
                      help="evaluate a finished run's saved answers from its measurement records; answers nothing")
    ap.add_argument("--evaluation-out", default=None, metavar="FILE",
                    help="with --evaluate-offline: the new results file (refused if it exists)")
    ap.add_argument("--offline-aligner", choices=("lexical", "semantic"), default=None,
                    help="with --evaluate-offline: claim-to-passage aligner (default lexical, no model; semantic "
                         "loads the UI's pinned local embedder and fails rather than fall back)")
    args = ap.parse_args()
    if args.evaluate_offline:
        return evaluate_offline(Path(args.evaluate_offline).resolve(), args.evaluation_out,
                                args.offline_aligner or "lexical")
    if args.evaluation_out or args.offline_aligner:
        ap.error("--evaluation-out and --offline-aligner need --evaluate-offline")

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
    corpus_now = corpus_identity(db)
    meta.setdefault("corpus", corpus_now)
    if meta["corpus"] != corpus_now:   # a resumed run whose source text changed since it started: say so, keep both
        meta.setdefault("corpus_changed_on_resume", []).append(corpus_now)
        print("WARNING: the corpus or semantic index changed since this run started (run_metadata.json "
              "corpus_changed_on_resume)", flush=True)
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

    def progress(n, q, row):
        el = time.perf_counter() - t_start
        print(f"{len(done) + n:3}/300 {q.question_id:8} {row['execution_status']:5} {row['seconds']:6.1f}s "
              f"| elapsed {el / 60:5.1f} min, ~{el / n * (len(todo) - n) / 60:5.1f} min left", flush=True)

    if todo:   # a finished run directory gains no new file on --resume
        ordinals = {q.question_id: i for i, q in enumerate(questions, start=1)}
        run_questions(pipeline, todo, ordinals, run_identity(out_dir, meta), out_dir, progress)
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
