"""Tests for the legacy and training dashboard adapters.

Synthetic artifact trees exercise the behaviour. The real repository's
artifacts are checked for internal consistency only, never for a specific
number: the adapters exist so the numbers come out of the files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.dashboard import metrics as M
from regulus.dashboard.adapters import legacy, training
from regulus.dashboard.schemas import COMPLETE, FAILED, INCOMPLETE, NOT_APPLICABLE

LEGACY_DIR = Path("data/evaluation/results")
TRAINING_DIR = Path("models/qwen3-0.6b-lora")


# ------------------------------------------------------------------ fixtures


def _answer_file(tmp_path: Path, *, failed=0, manual=True, adapter=None, results=3) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(results):
        ok = i >= failed
        rows.append({
            "question_id": f"q-{i:03d}", "category": "fda_ecfr",
            "question": f"question {i}", "reference_answer": "reference",
            "evaluation_notes": "notes", "expected_behavior": "answer",
            "status": "completed" if ok else "error",
            "model_answer": f"answer {i}" if ok else None,
            "error": None if ok else "boom",
            "generation_seconds": 10.0 if ok else None,
            "input_tokens": 800 if ok else None, "output_tokens": 100 if ok else None,
            "tokens_per_second": 10.0 if ok else None,
            "quality_score": 1 if ok else None,
            "manual_evaluation": {"reviewer": "a reviewer", "score": 1} if manual and ok else {},
            "citations": [{"index": 1, "label": "21 CFR 820.10"}],
        })
    completed = results - failed
    run = {
        "evaluation_run_id": "abcd1234", "pipeline": "unit-answer",
        "timestamp_utc": "2026-01-02T03:04:05+00:00",
        "model_id": "Qwen/Qwen3-0.6B", "model_revision": "rev1234567890",
        "device": "cpu", "dtype": "float32", "decoding_mode": "greedy", "seed": 42,
        "dataset": {"name": "unit_v1", "path": "data/evaluation/datasets/unit_v1.jsonl",
                    "sha256": "a" * 64, "num_examples": results},
        "num_questions": results, "duration_seconds": 40.0,
    }
    if adapter:
        run["adapter"] = adapter
    payload = {
        "schema_version": 3, "run": run,
        "summary": {
            "total": results, "completed": completed, "failed": failed,
            "failed_ids": [f"q-{i:03d}" for i in range(failed)],
            "avg_generation_seconds": 10.0, "total_generation_seconds": 10.0 * completed,
            "avg_input_tokens": 800.0, "avg_output_tokens": 100.0, "avg_tokens_per_second": 10.0,
            "by_category": {"fda_ecfr": {"total": results, "completed": completed, "failed": failed}},
            "manual_evaluation": {"scored": completed if manual else 0, "unscored": 0,
                                  "mean_score": 1.0 if manual else None, "by_category": {}},
        },
        "results": rows,
    }
    path = tmp_path / "unit-answer_20260102.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _retrieval_file(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    results = [
        {"id": "r-1", "category": "exact_cfr", "query": "21 CFR 820.10", "expected": ["21 CFR 820.10"],
         "first_hit_rank": 1, "negative_control": False, "negative_control_passed": None,
         "top_results": [], "total_ms": 100.0, "timings_ms": {}, "error": None, "retrieval": {}},
        {"id": "r-2", "category": "exact_cfr", "query": "21 CFR 820.20", "expected": ["21 CFR 820.20"],
         "first_hit_rank": 4, "negative_control": False, "negative_control_passed": None,
         "top_results": [], "total_ms": 200.0, "timings_ms": {}, "error": None, "retrieval": {}},
        {"id": "r-3", "category": "negative", "query": "nonsense", "expected": [],
         "first_hit_rank": None, "negative_control": True, "negative_control_passed": True,
         "top_results": [], "total_ms": 50.0, "timings_ms": {}, "error": None, "retrieval": {}},
    ]
    payload = {
        "schema_version": 2,
        "run": {"evaluation_run_id": "ret12345", "pipeline": "retrieval-unit",
                "timestamp_utc": "2026-01-03T00:00:00+00:00",
                "retriever": {"retriever": "LexicalRetriever"}, "top_k": 8,
                "dataset": {"name": "retrieval_unit", "path": "d.jsonl", "sha256": "b" * 64, "num_queries": 3}},
        "summary": {"queries": 3, "scored": 2, "negative_controls": 1, "negative_controls_passed": 1,
                    "failed": 0, "recall@1": 0.5, "recall@3": 0.5, "recall@5": 1.0, "recall@10": 1.0,
                    "mrr": 0.625, "misses": [], "avg_total_ms": 116.67, "max_total_ms": 200.0,
                    "by_category": {}},
        "results": results,
    }
    path = tmp_path / "retrieval-unit_20260103.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _training_run(tmp_path: Path, *, name="unit_v1", finished=True, metrics=True,
                  checkpoints=(40, 80), stalled=False) -> Path:
    d = tmp_path / name
    (d / "checkpoints").mkdir(parents=True)
    (d / "adapter").mkdir()
    (d / "adapter" / "adapter_config.json").write_text(json.dumps({
        "base_model_name_or_path": "Qwen/Qwen3-0.6B", "r": 16, "lora_alpha": 32, "lora_dropout": 0.05,
    }), encoding="utf-8")

    history = [
        {"loss": 0.9, "learning_rate": 1e-4, "grad_norm": 3.0, "epoch": 0.1, "step": 10},
        {"loss": 0.5, "learning_rate": 8e-5, "grad_norm": 2.0, "epoch": 0.4, "step": 40},
        {"eval_loss": 0.30, "epoch": 0.4, "step": 40},
        {"loss": 0.3, "learning_rate": 1e-5, "grad_norm": 1.0, "epoch": 0.8, "step": 80},
        {"eval_loss": 0.22, "epoch": 0.8, "step": 80},
        {"train_runtime": 1000.0, "train_loss": 0.35, "epoch": 0.8, "step": 80},
    ]
    if metrics:
        (d / "training_metrics.json").write_text(json.dumps({
            "log_history": history,
            "base_eval": {"eval_loss": 1.1, "epoch": 0},
            "final_eval": {"eval_loss": 0.22, "note": "last evaluated checkpoint"},
        }), encoding="utf-8")
        (d / "metadata.json").write_text(json.dumps({
            "stage": 99, "model": "Qwen/Qwen3-0.6B", "base_model_id": "Qwen/Qwen3-0.6B", "method": "lora",
            "dataset": {"train_examples": 1000, "train_examples_used": 950, "validation_examples": 100,
                        "test_examples": 50, "seed": 7, "hash": "c" * 64, "version": "v9"},
            "lora": {"r": 16, "alpha": 32, "dropout": 0.05, "target_modules": ["q_proj"],
                     "trainable_parameters": 10_092_544, "total_parameters": 606_142_464},
            "training": {"learning_rate": 1e-4, "epochs": 0.8, "max_steps": 100, "steps_completed": 80,
                         "batch_size": 1, "gradient_accumulation": 8, "max_seq_length": 1280,
                         "scheduler": "cosine", "warmup_steps": 5, "duration_seconds": 1000.0},
            "best_checkpoint": "checkpoint-80", "best_validation_loss": 0.22,
            "base_validation_loss": 1.1, "final_training_loss": 0.35,
            "device": "cpu", "dtype": "float32", "timestamp": "2026-01-04T00:00:00+00:00",
        }), encoding="utf-8")
    if finished:
        (d / "training_summary.json").write_text(json.dumps({
            "stage": 99, "mode": "full", "started_utc": "2026-01-03T20:00:00+00:00",
            "finished_utc": "2026-01-04T00:00:00+00:00", "training_duration_seconds": 1000.0,
            "hardware": {"device": "cpu", "dtype": "float32", "ram_total_gb": 8.5},
            "dependencies": {"torch": "2.14.0"},
            "dataset_identity": {"dataset_sha256": "c" * 64, "database_snapshot": "2026-01-01"},
            "protected_files_sha256": {}, "tokenization": {},
            "lora": {"trainable_parameters": 10_092_544, "total_parameters": 606_142_464},
        }), encoding="utf-8")
    for step in checkpoints:
        ck = d / "checkpoints" / f"checkpoint-{step}"
        ck.mkdir()
        (ck / "trainer_state.json").write_text(json.dumps({
            "best_global_step": 80, "best_metric": 0.22,
            "best_model_checkpoint": str(d / "checkpoints" / "checkpoint-80"),
            "global_step": step, "max_steps": 100, "epoch": step / 100,
            "eval_steps": 40, "save_steps": 40, "total_flos": 1.0, "num_input_tokens_seen": 0,
            "log_history": history,
        }), encoding="utf-8")
        (ck / "adapter_model.safetensors").write_bytes(b"x" * 64)
    if stalled:
        (d / "train.stalled.log").write_text("stalled", encoding="utf-8")
        (d / "chain.stalled.log").write_text("stalled", encoding="utf-8")
    return d


# ------------------------------------------------------------ legacy adapter


def test_legacy_detects_only_result_files(tmp_path):
    answer = _answer_file(tmp_path)
    assert legacy.detect(answer) is True
    assert legacy.detect(tmp_path) is False
    junk = tmp_path / "junk.json"
    junk.write_text("{}", encoding="utf-8")
    assert legacy.detect(junk) is False
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert legacy.detect(broken) is False


def test_legacy_answer_run_metrics_come_from_the_records(tmp_path):
    run = legacy.load(_answer_file(tmp_path, results=4, failed=1))
    assert run.schema == "legacy-answer/v1"
    assert run.metric("completion_rate").numerator == 3
    assert run.metric("completion_rate").denominator == 4
    assert run.metric("failed_count").value == 1
    assert run.metric("avg_generated_tokens").value == 100
    assert run.model.base_model_id == "Qwen/Qwen3-0.6B"
    assert run.model.revision == "rev1234567890"
    assert len(run.questions) == 4


def test_legacy_answer_run_has_no_final_answer_because_it_had_no_repair_layer(tmp_path):
    run = legacy.load(_answer_file(tmp_path))
    q = run.questions[0]
    assert q.answer_raw
    assert q.answer_final is None, "inventing a final answer would fake a distinction the run never made"
    assert q.extra["no_repair_layer"] is True
    assert any("no raw-versus-final distinction" in p for p in run.problems)


def test_legacy_manual_scores_are_labelled_as_human_judgment(tmp_path):
    run = legacy.load(_answer_file(tmp_path))
    manual = run.metric("manual_score_mean")
    assert manual is not None and manual.value == 1.0
    assert M.definition("manual_score_mean").heuristic is True
    assert any("reviewer" in p for p in run.problems)


def test_legacy_adapter_records_the_training_run_that_produced_it(tmp_path):
    run = legacy.load(_answer_file(tmp_path, adapter={
        "adapter_dir": "models/qwen3-0.6b-lora/unit_v1/adapter", "adapter_name": "unit_v1",
        "base_model_name_or_path": "Qwen/Qwen3-0.6B", "best_checkpoint": "checkpoint-80",
        "dataset_hash": "c" * 64, "stage": 99, "timestamp": "2026-01-04T00:00:00+00:00",
    }))
    assert run.model.adapter_id == "unit_v1"
    assert run.model.checkpoint == "checkpoint-80"
    assert run.model.key.endswith("unit_v1@checkpoint-80")
    assert run.breakdowns["trained_from"]["training_run"] == "unit_v1"
    assert run.breakdowns["trained_from"]["dataset_hash"] == "c" * 64


def test_retrieval_run_has_no_answer_model_and_says_so(tmp_path):
    run = legacy.load(_retrieval_file(tmp_path))
    assert run.schema == "legacy-retrieval/v1"
    assert run.model.base_model_id == NOT_APPLICABLE
    assert run.model.applicable is False
    assert run.model.recorded is False
    assert "retrieval-only" in " ".join(run.problems)


def test_retrieval_recall_is_recomputed_from_the_ranks(tmp_path):
    run = legacy.load(_retrieval_file(tmp_path))
    # two scored queries, ranks 1 and 4: recall@1 = 1/2, recall@5 = 2/2
    assert run.metric("recall_at_1").numerator == 1
    assert run.metric("recall_at_1").denominator == 2
    assert run.metric("recall_at_5").value == pytest.approx(1.0)
    assert run.metric("mrr").value == pytest.approx(0.625)
    assert run.metric("negative_control_pass").value == pytest.approx(1.0)
    assert run.metric("retrieval_latency_avg").unit == "seconds"


def test_retrieval_questions_are_marked_not_generated(tmp_path):
    run = legacy.load(_retrieval_file(tmp_path))
    assert all(q.generated is False for q in run.questions)
    assert all("retrieval-only" in (q.skipped_reason or "") for q in run.questions)
    assert run.questions[0].extra["first_hit_rank"] == 1


def test_legacy_flags_a_stored_aggregate_that_disagrees(tmp_path):
    path = _answer_file(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"]["avg_output_tokens"] = 999.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    run = legacy.load(path)
    metric = run.metric("avg_generated_tokens")
    assert metric.status == "inconsistent"
    assert metric.value == 999.0, "the stored value is still what is displayed"


def test_legacy_partial_file_is_incomplete(tmp_path):
    path = _answer_file(tmp_path, results=3)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["results"] = payload["results"][:1]
    path.write_text(json.dumps(payload), encoding="utf-8")
    run = legacy.load(path)
    assert run.status == INCOMPLETE
    assert any("1 of the 3" in p for p in run.problems)


# ---------------------------------------------------------- training adapter


def test_training_detects_finished_and_unfinished_runs(tmp_path):
    assert training.detect(_training_run(tmp_path)) is True
    bare = tmp_path / "bare"
    (bare / "checkpoints").mkdir(parents=True)
    assert training.detect(bare) is False, "an empty checkpoints directory is not a run"
    (bare / "train.log").write_text("x", encoding="utf-8")
    assert training.detect(bare) is True
    assert training.detect(tmp_path / "missing") is False


def test_training_run_parses_config_curves_and_checkpoints(tmp_path):
    run = training.load(_training_run(tmp_path))
    assert run.status == COMPLETE
    assert run.model.base_model_id == "Qwen/Qwen3-0.6B"
    assert run.model.adapter_id == "unit_v1"
    assert run.model.checkpoint == "checkpoint-80"
    assert [p["step"] for p in run.curves["training_loss"]] == [10, 40, 80]
    assert [p["step"] for p in run.curves["validation_loss"]] == [40, 80]
    assert [p["step"] for p in run.curves["learning_rate"]] == [10, 40, 80]
    assert [c.name for c in run.checkpoints] == ["checkpoint-40", "checkpoint-80"]
    selected = [c for c in run.checkpoints if c.is_selected]
    assert [c.name for c in selected] == ["checkpoint-80"]
    assert selected[0].validation_loss == pytest.approx(0.22)
    assert selected[0].size_bytes and selected[0].size_bytes > 0
    assert run.hyperparameters["learning_rate"] == pytest.approx(1e-4)
    assert run.dataset["train_examples_used"] == 950


def test_training_metrics_are_labelled_as_process_not_quality(tmp_path):
    run = training.load(_training_run(tmp_path))
    assert run.metric("final_eval_loss").value == pytest.approx(0.22)
    assert run.metric("base_eval_loss").value == pytest.approx(1.1)
    assert run.metric("eval_loss_delta").value == pytest.approx(-0.88)
    assert run.metric("total_steps").value == 80
    assert run.metric("planned_steps").value == 100
    assert run.metric("trainable_percent").value == pytest.approx(10_092_544 / 606_142_464)
    for m in run.metrics:
        assert M.definition(m.key).family == "training", m.key
    assert "lower training or validation loss is not" in " ".join(run.problems)


def test_training_notes_a_run_that_stopped_short(tmp_path):
    run = training.load(_training_run(tmp_path))
    assert any("stopped at step 80 of the 100" in p for p in run.problems)


def test_a_training_run_with_no_output_is_failed_when_it_stalled(tmp_path):
    run = training.load(_training_run(tmp_path, finished=False, metrics=False, checkpoints=(), stalled=True))
    assert run.status == FAILED
    assert any("stalled" in p for p in run.problems)
    assert any("No checkpoint was written" in p for p in run.problems)
    assert run.metric("final_eval_loss").status == "missing"


def test_a_training_run_without_a_summary_is_incomplete(tmp_path):
    run = training.load(_training_run(tmp_path, finished=False))
    assert run.status == INCOMPLETE
    assert any("did not complete cleanly" in p for p in run.problems)


def test_curves_fall_back_to_the_trainer_state(tmp_path):
    d = _training_run(tmp_path)
    (d / "training_metrics.json").unlink()
    run = training.load(d)
    assert run.curves["training_loss"], "the trainer state carries the same log history"
    assert any("were read from" in p for p in run.problems)


# -------------------------------------------------- the real repository data


@pytest.mark.skipif(not LEGACY_DIR.is_dir(), reason="no legacy evaluation results present")
def test_every_real_legacy_file_loads_consistently():
    files = sorted(LEGACY_DIR.rglob("*.json"))
    claimed = [f for f in files if legacy.detect(f)]
    assert claimed, "the repository has legacy result files"
    for path in claimed:
        run = legacy.load(path, root=Path.cwd())
        assert run.name and run.schema in ("legacy-answer/v1", "legacy-retrieval/v1")
        assert run.benchmark and run.benchmark.sha256
        for m in run.metrics:
            assert M.has_definition(m.key), f"{path.name}: {m.key}"
            if m.unit == "ratio" and m.value is not None:
                assert -0.001 <= m.value <= 1.001, f"{path.name}: {m.key} = {m.value}"
                if m.numerator is not None and m.denominator:
                    assert m.value == pytest.approx(m.numerator / m.denominator, abs=0.01), f"{path.name}: {m.key}"


@pytest.mark.skipif(not TRAINING_DIR.is_dir(), reason="no training runs present")
def test_every_real_training_run_loads_consistently():
    runs = [d for d in sorted(TRAINING_DIR.iterdir()) if d.is_dir() and training.detect(d)]
    assert runs, "the repository has training runs"
    for directory in runs:
        run = training.load(directory, root=Path.cwd())
        assert run.name == directory.name
        assert run.status in (COMPLETE, INCOMPLETE, FAILED)
        for m in run.metrics:
            assert M.definition(m.key).family == "training", m.key
        # a selected checkpoint, if any, must be one that exists
        selected = [c for c in run.checkpoints if c.is_selected]
        assert len(selected) <= 1
        if run.status == COMPLETE:
            assert run.curves["training_loss"], f"{directory.name} finished but recorded no loss curve"
