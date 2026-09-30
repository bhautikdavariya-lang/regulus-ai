"""Stage 5 runner: evidence phase, generation phase, report phase, resumable.

Layout under <run_dir>/stage5/:
    evidence_records.jsonl          one record per question (model-free)
    generation_full.jsonl           full pipeline, raw + repaired, per question
    generation_controlled.jsonl     exact-evidence-only generation, per question
    phase_<name>.json               completion marker with counts
    *.json, STAGE5_FINAL_REPORT.md, stage5_training_plan.json

A phase whose marker exists is skipped on resume; the generation phase also
skips questions already present in its jsonl, so an interrupted run
continues from the next question. The database is read-only throughout.

run_manifest.json records what the run evaluated (see regulus.stage5.identity).
Resuming is refused when it would mix two pipeline configurations or two sets
of weights in one run's answers. Answers written before identity was recorded
keep the run unrecorded: identity is never attached to answers retroactively.
"""

from __future__ import annotations

import gc
import time
from pathlib import Path
from typing import Any, Callable

from regulus.automation.log import PipelineLog, append_jsonl, ensure_resources, read_json, read_jsonl, write_json
from regulus.config import load_settings
from regulus.dashboard.fingerprint import pipeline_fingerprint, question_set_identity
from regulus.system_identity import evaluation_rag_config
from regulus.rag.pipeline import RagConfig, RagPipeline
from regulus.retrieval import Database, LexicalRetriever
from regulus.stage5 import report as rep
from regulus.stage5.dataset import Stage5Dataset, Stage5Example, load_stage5_dataset
from regulus.stage5.evidence_eval import EvidenceOutcome, EvidenceRecord, evaluate_evidence, summarise_evidence
from regulus.stage5.generation_eval import run_controlled, run_full
from regulus.stage5.identity import MANIFEST_SCHEMA_VERSION, evaluation_config, model_block, utc_now

PHASES = ("evidence", "generation", "report")
GeneratorFactory = Callable[[], Any]  # returns a Generator (model loaded lazily so the evidence phase needs no model)


class Stage5Error(RuntimeError):
    pass


def _marker(stage_dir: Path, phase: str) -> Path:
    return stage_dir / f"phase_{phase}.json"


def phase_done(stage_dir: Path, phase: str) -> bool:
    p = _marker(stage_dir, phase)
    return p.is_file() and read_json(p).get("status") == "done"


def _mark(stage_dir: Path, phase: str, **info: Any) -> None:
    write_json(_marker(stage_dir, phase), {"status": "done", "phase": phase, "finished_at": utc_now(), **info})


# ------------------------------------------------------------------ manifest


def _manifest_path(stage_dir: Path) -> Path:
    return stage_dir / "run_manifest.json"


def _has_answers(stage_dir: Path) -> bool:
    return bool(read_jsonl(stage_dir / "generation_full.jsonl") or read_jsonl(stage_dir / "generation_controlled.jsonl"))


def start_manifest(
    stage_dir: Path, *, run_id: str, dataset: Stage5Dataset, examples: list[Stage5Example],
    config: RagConfig, skip_generation: bool, controlled: bool,
) -> dict[str, Any]:
    """Write the manifest for this invocation, keeping what earlier ones recorded.

    The version 1 keys are rewritten as before (they describe the latest
    invocation, which existing readers expect). The identity of the answers
    already on disk is kept, and a configuration that differs from the one
    those answers were produced with is refused.
    """
    path = _manifest_path(stage_dir)
    prior = read_json(path) if path.is_file() else {}
    now = utc_now()
    answers_exist = _has_answers(stage_dir)
    current = evaluation_config(config, None)  # decoding is unknown until the model loads
    recorded = prior.get("evaluation_config") if isinstance(prior.get("evaluation_config"), dict) else None
    if answers_exist and recorded is not None:
        before = {k: v for k, v in recorded.items() if k != "decoding"}
        after = {k: v for k, v in current.items() if k != "decoding"}
        if before != after:
            changed = sorted(k for k in after if before.get(k) != after.get(k))
            raise Stage5Error(
                f"refusing to continue {stage_dir}: its answers were produced with a different evaluation "
                f"configuration (differs in: {', '.join(changed)}). Start a new run directory."
            )

    requested = question_set_identity(e.id for e in examples)
    manifest: dict[str, Any] = {
        "run_id": run_id, "dataset": dataset.path.as_posix(), "dataset_sha256": dataset.sha256,
        "questions": [e.id for e in examples], "config": config.to_dict(),
        "skip_generation": skip_generation, "controlled": controlled,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        # A version 1 manifest never recorded its start, and "now" would be false.
        "started_at": prior.get("started_at") if prior else now,
        "invocations": list(prior.get("invocations") or []) + [
            {"started_at": now, "skip_generation": skip_generation, "controlled": controlled, "questions": len(examples)}
        ],
        "question_set": {
            **requested.to_dict(),
            "benchmark_questions": len(dataset),
            "full_benchmark": requested.sha256 == question_set_identity(e.id for e in dataset.examples).sha256,
        },
    }
    # completed_at is not carried over: this invocation has not completed yet.
    for key in ("model", "pipeline_fingerprint", "identity_unrecorded_reason"):
        if key in prior:
            manifest[key] = prior[key]
    if recorded is not None:
        manifest["evaluation_config"] = recorded
    elif answers_exist:
        manifest["identity_unrecorded_reason"] = (
            "answers in this run directory were written before Stage 5 recorded model identity "
            "and configuration; they cannot be identified after the fact"
        )
    else:
        # Model-independent sections now; decoding is added when the model loads.
        manifest["evaluation_config"] = current
    write_json(path, manifest)
    return manifest


def record_generation_identity(stage_dir: Path, generator: Any, config: RagConfig, log: PipelineLog) -> dict[str, Any]:
    """Write the resolved weights and fingerprint once the model has loaded.

    Refuses to resume with different weights or configuration: answers from
    two models in one run could not be attributed to either.
    """
    path = _manifest_path(stage_dir)
    manifest = read_json(path)
    model = model_block(generator)
    econfig = evaluation_config(config, generator)
    fingerprint = pipeline_fingerprint(econfig).to_dict()
    if manifest.get("identity_unrecorded_reason"):
        log.info(f"identity not recorded: {manifest['identity_unrecorded_reason']}")
        return manifest
    if _has_answers(stage_dir):
        if manifest.get("model") is None or manifest.get("pipeline_fingerprint") is None:
            manifest["identity_unrecorded_reason"] = "answers exist from an invocation that did not record model identity"
            write_json(path, manifest)
            return manifest
        if manifest["model"] != model or manifest["pipeline_fingerprint"] != fingerprint:
            raise Stage5Error(
                f"refusing to resume {stage_dir}: the existing answers were produced by "
                f"{manifest['model'].get('id')} + {manifest['model'].get('adapter_name') or 'no adapter'} "
                f"(fingerprint {manifest['pipeline_fingerprint'].get('value', '')[:12]}), not by the model now "
                f"loaded ({model.get('id')} + {model.get('adapter_name') or 'no adapter'}, fingerprint "
                f"{fingerprint['value'][:12]}). Start a new run directory."
            )
        return manifest
    manifest.update({"model": model, "evaluation_config": econfig, "pipeline_fingerprint": fingerprint})
    write_json(path, manifest)
    log.info(f"model identity: {model.get('id')}@{(model.get('revision') or 'unknown')[:12]} "
             f"adapter={model.get('adapter_name') or 'none'} checkpoint={model.get('checkpoint') or '-'} "
             f"fingerprint={fingerprint['value'][:12]}")
    return manifest


def _mark_manifest_completed(stage_dir: Path) -> None:
    path = _manifest_path(stage_dir)
    manifest = read_json(path)
    manifest["completed_at"] = utc_now()
    write_json(path, manifest)


def _select(dataset: Stage5Dataset, ids: list[str] | None, limit: int | None) -> list[Stage5Example]:
    rows = list(dataset.examples)
    if ids:
        wanted = set(ids)
        rows = [e for e in rows if e.id in wanted]
    if limit is not None:
        rows = rows[: max(0, limit)]
    if not rows:
        raise Stage5Error("no questions selected")
    return rows


def _load_evidence(stage_dir: Path) -> dict[str, EvidenceRecord]:
    out: dict[str, EvidenceRecord] = {}
    for d in read_jsonl(stage_dir / "evidence_records.jsonl"):
        out[d["id"]] = EvidenceRecord(
            id=d["id"], category=d["category"], question=d["question"], plan_kind=d["plan_kind"], requirements=d["requirements"],
            retrieval=d["retrieval"], coverage=d["coverage"], selection=d["selection"], retrieval_ok=d["retrieval_ok"],
            coverage_ok=d["coverage_ok"], selection_ok=d["selection_ok"], deterministic=d["deterministic"], timings_ms=d.get("timings_ms", {}),
        )
    return out


def run_evidence_phase(examples: list[Stage5Example], retriever: LexicalRetriever, config: RagConfig, stage_dir: Path, log: PipelineLog) -> dict[str, EvidenceOutcome]:
    path = stage_dir / "evidence_records.jsonl"
    if path.exists():
        path.unlink()  # cheap phase: always recomputed as a whole
    outcomes: dict[str, EvidenceOutcome] = {}
    for i, ex in enumerate(examples, start=1):
        try:
            outcome = evaluate_evidence(ex, retriever, config)
        except Exception as exc:  # one broken question must not abort the phase
            log.info(f"  [{ex.id}] evidence phase error: {type(exc).__name__}: {exc}")
            continue
        outcomes[ex.id] = outcome
        append_jsonl(path, outcome.record.to_dict())
        r = outcome.record
        log.info(f"  [{ex.id:<7}] {i:>2}/{len(examples)} {ex.category:<15} retrieval={'ok ' if r.retrieval_ok else 'FAIL'} coverage={'ok ' if r.coverage_ok else 'FAIL'} selection={'ok ' if r.selection_ok else 'FAIL'} state={r.coverage['state']}")
    return outcomes


def run_generation_phase(examples: list[Stage5Example], outcomes: dict[str, EvidenceOutcome], pipeline: RagPipeline, stage_dir: Path, log: PipelineLog, *, controlled: bool = True) -> None:
    full_path = stage_dir / "generation_full.jsonl"
    ctrl_path = stage_dir / "generation_controlled.jsonl"
    done_full = {r["id"] for r in read_jsonl(full_path)}
    done_ctrl = {r["id"] for r in read_jsonl(ctrl_path)}
    for i, ex in enumerate(examples, start=1):
        if ex.id not in done_full:
            t0 = time.perf_counter()
            try:
                rec = run_full(ex, pipeline)
            except Exception as exc:
                log.info(f"  [{ex.id}] full-pipeline generation error: {type(exc).__name__}: {exc}")
                rec = {"id": ex.id, "category": ex.category, "expected_behavior": ex.expected_behavior, "domain": ex.domain, "mode": "full", "generated": False, "skipped_reason": f"error: {type(exc).__name__}", "refusal": {"raw_class": "error", "final_class": "error", "expected": ex.expected_behavior, "correct_refusal": False, "false_refusal": False, "false_answer": False}, "timings_ms": {}}
            append_jsonl(full_path, rec)
            v = rec.get("validation_initial") or {}
            log.info(f"  [{ex.id:<7}] {i:>2}/{len(examples)} full      gen={'yes' if rec.get('generated') else 'no '} tokens={rec.get('tokens', {}).get('generated')} raw={v.get('status', rec.get('skipped_reason'))} repair={rec.get('repair')} {time.perf_counter() - t0:.0f}s")
        if controlled and ex.id not in done_ctrl:
            outcome = outcomes.get(ex.id)
            if outcome is None:
                append_jsonl(ctrl_path, {"id": ex.id, "category": ex.category, "mode": "controlled", "generated": False, "skipped_reason": "no evidence outcome"})
                continue
            t0 = time.perf_counter()
            try:
                rec = run_controlled(ex, pipeline, outcome)
            except Exception as exc:
                log.info(f"  [{ex.id}] controlled generation error: {type(exc).__name__}: {exc}")
                rec = {"id": ex.id, "category": ex.category, "mode": "controlled", "generated": False, "skipped_reason": f"error: {type(exc).__name__}"}
            append_jsonl(ctrl_path, rec)
            v = rec.get("validation_initial") or {}
            log.info(f"  [{ex.id:<7}]       controlled gen={'yes' if rec.get('generated') else 'no '} raw={v.get('status', rec.get('skipped_reason'))} {time.perf_counter() - t0:.0f}s")


def build_reports(run_id: str, dataset: Stage5Dataset, examples: list[Stage5Example], stage_dir: Path) -> dict[str, Any]:
    ex_map = {e.id: e for e in examples}
    evidence = _load_evidence(stage_dir)
    full = read_jsonl(stage_dir / "generation_full.jsonl")
    controlled = read_jsonl(stage_dir / "generation_controlled.jsonl")
    ev_records = [evidence[e.id] for e in examples if e.id in evidence]
    metrics: dict[str, Any] = summarise_evidence(ev_records, ex_map)
    metrics["generation_results"] = rep.generation_results(full, controlled, ex_map)
    metrics["semantic_faithfulness_results"] = rep.faithfulness_results(full)
    metrics["citation_results"] = rep.citation_results(full)
    metrics["hallucination_results"] = rep.hallucination_results(full)
    metrics["refusal_results"] = rep.refusal_results(full, ex_map)
    metrics["domain_boundary_results"] = rep.domain_boundary_results(full, evidence, ex_map)
    metrics["latency_results"] = rep.latency_results(full, evidence)
    metrics["repair_results"] = rep.repair_results(full)
    metrics["correctness_results"] = rep.correctness_results(full, ex_map)
    metrics["behaviour_results"] = rep.behaviour_results(full, ex_map)
    metrics["failure_analysis"] = rep.failure_analysis(ex_map, evidence, full, controlled)
    dataset_meta = {"name": dataset.name, "path": dataset.path.as_posix(), "sha256": dataset.sha256, "questions_total": len(dataset), "questions_run": len(examples)}
    summary = rep.stage5_summary(run_id, dataset_meta, metrics)
    plan = rep.training_plan(run_id, summary, metrics["failure_analysis"], ex_map, full)
    for name, data in metrics.items():
        write_json(stage_dir / f"{name}.json", data)
    write_json(stage_dir / "stage5_summary.json", summary)
    write_json(stage_dir / "stage5_training_plan.json", plan)
    (stage_dir / "STAGE5_FINAL_REPORT.md").write_text(rep.render_report(run_id, summary, metrics, plan, ex_map), encoding="utf-8")
    return {"summary": summary, "plan": plan, "metrics": metrics}


def run_stage5(
    run_dir: Path,
    *,
    run_id: str,
    log: PipelineLog,
    generator_factory: GeneratorFactory | None,
    dataset_path: Path | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
    skip_generation: bool = False,
    controlled: bool = True,
    config: RagConfig | None = None,
) -> dict[str, Any]:
    """Run (or resume) Stage 5 into <run_dir>/stage5. Returns summary + plan."""
    stage_dir = run_dir / "stage5"
    stage_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_stage5_dataset(dataset_path)
    examples = _select(dataset, ids, limit)
    # The configured pipeline under the evaluation protocol: the same
    # definition the dashboard uses for "the system configured today".
    config = config or evaluation_rag_config(load_settings())
    if config.validation_behavior != "annotate":
        raise Stage5Error("Stage 5 needs validation_behavior='annotate' so raw and repaired answers are both recorded")
    start_manifest(stage_dir, run_id=run_id, dataset=dataset, examples=examples, config=config,
                   skip_generation=skip_generation, controlled=controlled)
    log.tag("STAGE 5", f"dataset {dataset.name} ({len(examples)} of {len(dataset)} questions), run {run_id}")

    db = Database.from_env()
    db.connect()
    status = db.status()
    if str(status.get("default_transaction_read_only", "")).lower() not in ("on", "true", "1"):
        raise Stage5Error("database connection is not read-only")
    log.info(f"Database {status.get('database')} read-only={status.get('default_transaction_read_only')}")
    retriever = LexicalRetriever(db)
    try:
        # ---- evidence (always fresh: seconds)
        log.tag("STAGE 5", "phase evidence: retrieval, coverage, selection (no model)")
        outcomes = run_evidence_phase(examples, retriever, config, stage_dir, log)
        _mark(stage_dir, "evidence", questions=len(outcomes))

        # ---- generation (resumable per question)
        if skip_generation:
            log.tag("STAGE 5", "generation phase skipped by request")
        elif phase_done(stage_dir, "generation"):
            log.tag("STAGE 5", "generation phase already complete (resume)")
        else:
            if generator_factory is None:
                raise Stage5Error("a generator factory is required for the generation phase")
            ensure_resources(log)
            log.tag("STAGE 5", "phase generation: loading the base model")
            generator = generator_factory()
            record_generation_identity(stage_dir, generator, config, log)
            pipeline = RagPipeline(retriever, generator, config)
            log.tag("STAGE 5", f"phase generation: {len(examples)} questions, full pipeline (raw + repaired){' and controlled evidence' if controlled else ''}")
            run_generation_phase(examples, outcomes, pipeline, stage_dir, log, controlled=controlled)
            _mark(stage_dir, "generation", questions=len(examples))
            del pipeline, generator
            gc.collect()

        # ---- reports
        log.tag("STAGE 5", "phase report")
        result = build_reports(run_id, dataset, examples, stage_dir)
        _mark(stage_dir, "report", proceed=result["plan"]["proceed"])
        _mark_manifest_completed(stage_dir)
        s = result["summary"]
        log.tag("STAGE 5 COMPLETE", f"retrieval_ok={s['retrieval_ok']} coverage_ok={s['coverage_ok']} selection_ok={s['selection_ok']} valid_raw={s['generation_valid_raw_full']} valid_final={s['generation_valid_final_full']} hallucination_raw={s['hallucination_any_raw']} proceed={result['plan']['proceed']}")
        return result
    finally:
        db.close()


def stage5_completed(run_dir: Path) -> bool:
    stage_dir = run_dir / "stage5"
    return phase_done(stage_dir, "report") and (stage_dir / "stage5_training_plan.json").is_file()
