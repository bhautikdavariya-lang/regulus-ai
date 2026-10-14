"""Shared fixtures: a miniature project whose configured system resolves, and
Stage 5 runs that record exactly what a real schema-2 run records.

`write_project` gives the project a local Hugging Face cache stub (refs/main
and a snapshot directory), so the configured base model resolves to a known
revision without any weights. `stage5_run` writes a Stage 5 run directory;
by default its manifest records the current system's own model identity and
pipeline fingerprint, i.e. a run that genuinely measured today's
configuration. Every piece can be overridden to build the ineligible cases.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from regulus.dashboard.fingerprint import pipeline_fingerprint
from regulus.dashboard.registry import Root, read_current_system

from .test_dashboard_stage5_adapter import _evidence, _generation

REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"
OTHER_REVISION = "0" * 40

ROOTS = (
    Root("artifacts", "*/*/*", False, "stage 5 runs"),
    Root("models/qwen3-0.6b-lora", "*", False, "training runs"),
    Root("data/evaluation/results", "**/*.json", True, "legacy results"),
)


def write_project(root: Path, *, model_id: str = "Qwen/Qwen3-0.6B", adapter: Path | None = None,
                  answer_length: dict[str, Any] | None = None, revision: str = REVISION) -> Path:
    """configs/model.yaml plus a cache stub the configured model resolves against."""
    cache = root / "hf_cache"
    repo = cache / f"models--{model_id.replace('/', '--')}"
    (repo / "refs").mkdir(parents=True, exist_ok=True)
    (repo / "refs" / "main").write_text(revision, encoding="utf-8")
    (repo / "snapshots" / revision).mkdir(parents=True, exist_ok=True)
    lines = ["model:", f'  id: "{model_id}"', f'  cache_dir: "{cache.as_posix()}"', '  device: "auto"', '  dtype: "auto"']
    if adapter is not None:
        lines.append(f'  adapter: "{Path(adapter).as_posix()}"')
    if answer_length:
        lines.append("answer_length:")
        lines += [f"  {k}: {v}" for k, v in answer_length.items()]
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / "configs" / "model.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "data" / "evaluation" / "results").mkdir(parents=True, exist_ok=True)
    return root


def write_adapter(root: Path, name: str = "lora_x", best: str | None = "checkpoint-80",
                  base: str = "Qwen/Qwen3-0.6B") -> Path:
    run = root / "models" / "qwen3-0.6b-lora" / name
    adapter = run / "adapter"
    adapter.mkdir(parents=True, exist_ok=True)
    (adapter / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": base, "r": 16}), encoding="utf-8")
    meta = {"stage": 12, "dataset": {"hash": "d" * 64}}
    if best:
        meta["best_checkpoint"] = best
    (run / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return adapter


def model_block_for(root: Path) -> dict[str, Any]:
    m = read_current_system(root).model
    return {"id": m.base_model_id, "revision": m.revision, "adapter_dir": m.adapter_path,
            "adapter_name": m.adapter_id, "checkpoint": m.checkpoint, "dtype": "float32", "device": "cpu"}


def stage5_run(root: Path, name: str, *, completed_at: str = "2026-09-24T10:00:00+00:00",
               ids: tuple[str, ...] = ("S-1", "S-2", "S-3"), bench_ids: tuple[str, ...] | None = None,
               bench_name: str = "unit_bench", model: dict[str, Any] | None | str = "current",
               evaluation_config: dict[str, Any] | None | str = "current",
               fingerprint: dict[str, Any] | None | str = "derived",
               aggregates: dict[str, Any] | None = None) -> Path:
    """A Stage 5 run at artifacts/<group>/<name>/stage5, as a schema-2 run writes it."""
    d = root / "artifacts" / "stage5_stage6" / name / "stage5"
    d.mkdir(parents=True)
    bench = root / "data" / "evaluation" / "datasets" / f"{bench_name}.jsonl"
    bench.parent.mkdir(parents=True, exist_ok=True)
    if not bench.exists():
        rows = [{"id": q, "category": "single", "question": f"question {q}", "domain": "regulatory",
                 "expected_behavior": "answer", "expected_missing": []} for q in (bench_ids or ids)]
        bench.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    current = read_current_system(root)
    econfig = current.evaluation_config if evaluation_config == "current" else evaluation_config
    manifest: dict[str, Any] = {
        "run_id": name, "dataset": bench.as_posix(), "dataset_sha256": hashlib.sha256(bench.read_bytes()).hexdigest(),
        "questions": list(ids), "config": {"retriever": "LexicalRetriever", "top_k": 8},
        "skip_generation": False, "controlled": True, "schema_version": 2,
        "started_at": "2026-09-24T00:00:00+00:00", "completed_at": completed_at,
    }
    block = model_block_for(root) if model == "current" else model
    if block is not None:
        manifest["model"] = block
    if econfig is not None:
        manifest["evaluation_config"] = econfig
    fp = pipeline_fingerprint(econfig).to_dict() if fingerprint == "derived" and econfig is not None else (
        None if fingerprint == "derived" else fingerprint)
    if fp is not None:
        manifest["pipeline_fingerprint"] = fp
    (d / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    full = [_generation(q, valid_raw=(q != ids[-1]), valid_final=True,
                        repair=None if q != ids[-1] else "extractive_replacement") for q in ids]
    for filename, rows in (("evidence_records.jsonl", [_evidence(q) for q in ids]),
                           ("generation_full.jsonl", full),
                           ("generation_controlled.jsonl", [_generation(q) for q in ids])):
        (d / filename).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for phase in ("evidence", "generation", "report"):
        (d / f"phase_{phase}.json").write_text(
            json.dumps({"status": "done", "phase": phase, "finished_at": completed_at}), encoding="utf-8")
    for filename, payload in (aggregates or {}).items():
        (d / filename).write_text(json.dumps(payload), encoding="utf-8")
    return d
