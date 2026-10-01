"""Stage 5 evaluation identity: what a run evaluated, recorded and read back.

The runner tests drive the real `run_stage5`, the real generator factory from
`scripts/run_stage5.py`, the real `QwenGenerator.describe()` and the real
`adapter_identity()`. Only what would touch the database, load weights or
compute the full report is replaced by fakes, so no model is loaded here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from regulus.automation.log import PipelineLog
from regulus.config import PROJECT_ROOT, GenerationConfig
from regulus.dashboard.adapters import stage5 as stage5_adapter
from regulus.dashboard.fingerprint import (
    FINGERPRINT_FIELDS,
    normalize_evaluation_config,
    pipeline_fingerprint,
    question_set_identity,
)
from regulus.dashboard.registry import resolve_freshness, same_weights
from regulus.dashboard.schemas import (
    COMPLETE,
    INCOMPLETE,
    CURRENT,
    HISTORICAL,
    KIND_EVALUATION,
    UNRECORDED,
    BenchmarkIdentity,
    CurrentSystem,
    Experiment,
    ModelIdentity,
)
from regulus.rag.context import ContextPolicy
from regulus.rag.generation import GenerationBudget, GenerationPackage, PackagedSource
from regulus.rag.pipeline import RagConfig
from regulus.stage5 import generation_eval, runner
from regulus.stage5.identity import resolve_adapter, utc_now

REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"
_FP = {"version": 1, "algorithm": "sha256", "value": "f" * 64}
_FULL = {"count": 3, "benchmark_questions": 3, "full_benchmark": True}


# ------------------------------------------------------------------ helpers


def _load_script():
    spec = importlib.util.spec_from_file_location("run_stage5_script", PROJECT_ROOT / "scripts" / "run_stage5.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dataset(tmp_path: Path, n: int) -> Path:
    path = tmp_path / "bench.jsonl"
    rows = [{"id": f"S5-{i:03d}", "category": "single", "question": f"What does question {i} require?",
             "expected_requirements": [], "expected_exact": [], "expected_missing": [],
             "expected_behavior": "answer", "expected_terms": [], "domain": "regulatory"} for i in range(1, n + 1)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _adapter_run(tmp_path: Path, name: str = "lora_x", best: str | None = "checkpoint-80") -> Path:
    run = tmp_path / "models" / name
    adapter = run / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text(json.dumps({
        "base_model_name_or_path": "Qwen/Qwen3-0.6B", "peft_type": "LORA", "r": 16, "lora_alpha": 32,
        "lora_dropout": 0.05, "target_modules": ["q_proj"]}), encoding="utf-8")
    meta = {"stage": 12, "dataset": {"hash": "d" * 64}, "timestamp": "2026-09-21T12:44:05+00:00"}
    if best:
        meta["best_checkpoint"] = best
    (run / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return adapter


class _FakeModel:
    """Just enough of a loaded transformers model for QwenGenerator.describe()."""

    def __init__(self, revision: str = REVISION) -> None:
        self.config = SimpleNamespace(_commit_hash=revision, _name_or_path="Qwen/Qwen3-0.6B")
        self.device = "cpu"
        self.dtype = "torch.float32"


class _FakeDatabase:
    @classmethod
    def from_env(cls):
        return cls()

    def connect(self):
        pass

    def status(self):
        return {"database": "fake", "default_transaction_read_only": "on"}

    def close(self):
        pass


def _fake_evidence(ex, retriever, config):
    record = SimpleNamespace(
        retrieval_ok=True, coverage_ok=True, selection_ok=True, coverage={"state": "COMPLETE"},
        to_dict=lambda: {"id": ex.id, "category": ex.category, "question": ex.question,
                         "selection": {"selected_ids": [f"phase-ev-{ex.id}"]}},
    )
    return SimpleNamespace(record=record)


def _fake_full(ex, pipeline):
    return {"id": ex.id, "category": ex.category, "expected_behavior": ex.expected_behavior, "mode": "full",
            "generated": True, "selected_ids": [f"gen-ev-{ex.id}-a", f"gen-ev-{ex.id}-b"],
            "validation_initial": {"status": "valid"}, "tokens": {"generated": 3}, "repair": None}


def _fake_controlled(ex, pipeline, outcome):
    return {"id": ex.id, "category": ex.category, "mode": "controlled", "generated": False,
            "skipped_reason": "no exact evidence to control for"}


@pytest.fixture
def fake_stage5(monkeypatch):
    """Everything outside the runner's own logic replaced, nothing loaded."""
    import regulus.finetune
    import regulus.rag.generator as generator_module
    from regulus.system_identity import adapter_identity

    monkeypatch.setattr(runner, "Database", _FakeDatabase)
    monkeypatch.setattr(runner, "LexicalRetriever", lambda db: object())
    monkeypatch.setattr(runner, "RagPipeline", lambda retriever, generator, config: object())
    monkeypatch.setattr(runner, "ensure_resources", lambda log: None)
    monkeypatch.setattr(runner, "evaluate_evidence", _fake_evidence)
    monkeypatch.setattr(runner, "run_full", _fake_full)
    monkeypatch.setattr(runner, "run_controlled", _fake_controlled)
    monkeypatch.setattr(runner, "build_reports", lambda run_id, dataset, examples, stage_dir: {
        "summary": defaultdict(int), "plan": {"proceed": False}})

    # The real load_qwen_generator runs (it merges any adapter and records
    # system_identity); only the weight loading and the peft merge are faked.
    loaded = {"revision": REVISION}
    monkeypatch.setattr(generator_module, "load_model", lambda cfg, local_files_only=False: _FakeModel(loaded["revision"]))
    monkeypatch.setattr(generator_module, "load_tokenizer", lambda cfg, local_files_only=False: None)
    monkeypatch.setattr(regulus.finetune, "attach_saved_adapter",
                        lambda model, path, merge=True: (model, adapter_identity(Path(path))))
    return loaded


def _run(tmp_path, *, dataset, adapter=None, limit=None, config=None, run_dir=None, skip_generation=False):
    script = _load_script()
    run_dir = run_dir or tmp_path / "run"
    runner.run_stage5(
        run_dir, run_id="unit", log=PipelineLog(tmp_path / "pipeline.log"),
        generator_factory=None if skip_generation else script.make_generator_factory(
            str(adapter) if adapter else None, True),
        dataset_path=dataset, limit=limit, config=config, skip_generation=skip_generation,
    )
    return run_dir / "stage5"


def _manifest(stage_dir: Path) -> dict:
    return json.loads((stage_dir / "run_manifest.json").read_text(encoding="utf-8"))


def _write_stage5_dir(tmp_path: Path, *, run_ids, bench_ids, manifest_extra=None) -> Path:
    """A minimal Stage 5 run directory written by hand, as an old run would be."""
    d = tmp_path / "old" / "stage5"
    d.mkdir(parents=True)
    bench = d.parent / "bench.jsonl"
    bench.write_text("".join(json.dumps({"id": q, "category": "single"}) + "\n" for q in bench_ids), encoding="utf-8")
    manifest = {"run_id": "old", "dataset": bench.as_posix(),
                "dataset_sha256": hashlib.sha256(bench.read_bytes()).hexdigest(),
                "questions": list(run_ids), "config": {"retriever": "LexicalRetriever", "top_k": 8},
                "skip_generation": False, "controlled": True, **(manifest_extra or {})}
    (d / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in ("evidence_records.jsonl", "generation_full.jsonl"):
        (d / name).write_text("".join(json.dumps({"id": q, "generated": True}) + "\n" for q in run_ids), encoding="utf-8")
    for phase in ("evidence", "generation", "report"):
        (d / f"phase_{phase}.json").write_text(json.dumps({"status": "done", "finished_at": "2026-01-01 00:00:00"}), encoding="utf-8")
    return d


_CURRENT = CurrentSystem(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REVISION), pipeline_fingerprint=_FP)


def _experiment(**kwargs) -> Experiment:
    defaults = dict(experiment_id="x", name="run", kind=KIND_EVALUATION, status=COMPLETE, path="p",
                    model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B"),
                    benchmark=BenchmarkIdentity(benchmark_id="b", sha256="a" * 64),
                    completed_at="2026-01-01T00:00:00+00:00")
    defaults.update(kwargs)
    return Experiment(**defaults)


# ------------------------------------------------ A: model identity persistence


def test_a_manifest_records_the_resolved_model_identity(tmp_path, fake_stage5):
    adapter = _adapter_run(tmp_path)
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 3), adapter=adapter)
    m = _manifest(stage_dir)

    assert m["schema_version"] == 2
    model = m["model"]
    assert model["id"] == "Qwen/Qwen3-0.6B"            # the base id, not the "+adapter" display name
    assert model["revision"] == REVISION                 # read from the loaded model's config
    assert model["adapter_name"] == "lora_x"
    assert model["adapter_dir"] == adapter.as_posix()
    assert model["checkpoint"] == "checkpoint-80"
    assert model["checkpoint_source"] == "metadata.json best_checkpoint of the training run"
    assert (model["dtype"], model["device"]) == ("float32", "cpu")   # resolved, not "auto"
    # the script forces greedy decoding; the manifest records what actually ran
    assert m["evaluation_config"]["decoding"]["do_sample"] is False
    assert m["pipeline_fingerprint"]["algorithm"] == "sha256"
    assert m["pipeline_fingerprint"]["value"] == pipeline_fingerprint(m["evaluation_config"]).value
    # version 1 keys that existing readers use are unchanged
    for key in ("run_id", "dataset", "dataset_sha256", "questions", "config", "skip_generation", "controlled"):
        assert key in m


def test_a_the_dashboard_reads_the_recorded_identity_back(tmp_path, fake_stage5):
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 3), adapter=_adapter_run(tmp_path))
    run = stage5_adapter.load(stage_dir)
    assert run.model.recorded
    assert run.model.key == f"Qwen/Qwen3-0.6B@{REVISION}+lora_x@checkpoint-80"
    assert run.pipeline_fingerprint["verified"] is True
    assert run.question_set["full_benchmark"] is True
    assert not any("model identity is not recorded" in p for p in run.problems)


def test_a_a_base_model_run_records_no_adapter(tmp_path, fake_stage5):
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 2))
    model = _manifest(stage_dir)["model"]
    assert model["adapter_name"] is None and model["checkpoint"] is None
    assert stage5_adapter.load(stage_dir).model.key == f"Qwen/Qwen3-0.6B@{REVISION}+base"


def test_an_evidence_only_run_records_no_model(tmp_path, fake_stage5):
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 2), skip_generation=True)
    m = _manifest(stage_dir)
    assert "model" not in m and "pipeline_fingerprint" not in m
    assert stage5_adapter.load(stage_dir).model.base_model_id == UNRECORDED


# ----------------------------------------------------- resume safety


def test_resuming_with_different_weights_is_refused(tmp_path, fake_stage5):
    dataset = _dataset(tmp_path, 3)
    stage_dir = _run(tmp_path, dataset=dataset, adapter=_adapter_run(tmp_path, "lora_x", "checkpoint-40"))
    (stage_dir / "phase_generation.json").unlink()   # as if interrupted mid-generation
    with pytest.raises(runner.Stage5Error, match="refusing to resume"):
        _run(tmp_path, dataset=dataset, adapter=_adapter_run(tmp_path, "lora_y", "checkpoint-80"))


def test_resuming_with_a_different_configuration_is_refused(tmp_path, fake_stage5):
    dataset = _dataset(tmp_path, 3)
    _run(tmp_path, dataset=dataset)
    with pytest.raises(runner.Stage5Error, match="different evaluation configuration"):
        _run(tmp_path, dataset=dataset, config=RagConfig(validation_behavior="annotate", top_k=4))


def test_a_report_rebuild_keeps_the_identity_of_the_answers(tmp_path, fake_stage5):
    dataset = _dataset(tmp_path, 3)
    stage_dir = _run(tmp_path, dataset=dataset, adapter=_adapter_run(tmp_path))
    before = _manifest(stage_dir)
    _run(tmp_path, dataset=dataset, skip_generation=True)
    after = _manifest(stage_dir)
    assert after["model"] == before["model"]
    assert after["pipeline_fingerprint"] == before["pipeline_fingerprint"]
    assert after["started_at"] == before["started_at"]
    assert [i["skip_generation"] for i in after["invocations"]] == [False, True]


def test_answers_from_before_identity_recording_stay_unrecorded(tmp_path, fake_stage5):
    """Resuming a version 1 run must not attach today's identity to old answers."""
    dataset = _dataset(tmp_path, 3)
    stage_dir = tmp_path / "run" / "stage5"
    stage_dir.mkdir(parents=True)
    (stage_dir / "run_manifest.json").write_text(json.dumps({
        "run_id": "unit", "dataset": dataset.as_posix(), "dataset_sha256": "x", "questions": ["S5-001"],
        "config": {}, "skip_generation": False, "controlled": True}), encoding="utf-8")
    (stage_dir / "generation_full.jsonl").write_text(json.dumps({"id": "S5-001", "generated": True}) + "\n", encoding="utf-8")
    _run(tmp_path, dataset=dataset)
    m = _manifest(stage_dir)
    assert "model" not in m and "pipeline_fingerprint" not in m
    assert m["started_at"] is None                    # unknown, not "now"
    assert "cannot be identified after the fact" in m["identity_unrecorded_reason"]
    assert stage5_adapter.load(stage_dir).model.base_model_id == UNRECORDED


# ------------------------------------------------ B: old artifacts stay unrecorded


def test_b_a_manifest_without_a_model_block_is_unrecorded(tmp_path):
    d = _write_stage5_dir(tmp_path, run_ids=["A", "B"], bench_ids=["A", "B"])
    run = stage5_adapter.load(d)
    assert run.model.base_model_id == UNRECORDED
    assert run.model.recorded is False
    assert run.pipeline_fingerprint is None
    assert any("model identity is not recorded" in p for p in run.problems)


def test_b_the_real_stage5_baseline_is_still_unrecorded():
    baseline = PROJECT_ROOT / "artifacts" / "stage5_stage6" / "stage5_baseline_20260923" / "stage5"
    if not baseline.is_dir():
        pytest.skip("the Stage 5 baseline artifact is not present on this machine")
    run = stage5_adapter.load(baseline, root=PROJECT_ROOT)
    assert run.model.base_model_id == UNRECORDED and not run.model.recorded
    assert run.question_set["count"] == 51 and run.question_set["full_benchmark"] is True
    assert run.started_at is None and run.metric("run_duration").value is None
    out = resolve_freshness([_experiment(model=run.model, question_set=run.question_set,
                                         pipeline_fingerprint=run.pipeline_fingerprint)], _CURRENT)
    assert (out[0].status, out[0].freshness_code) == (HISTORICAL, "model_identity_unrecorded")


# ------------------------------------------------ C / D: checkpoints


def test_c_different_checkpoints_are_different_models():
    a = ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REVISION, adapter_id="stage13_v1", checkpoint="checkpoint-40")
    b = ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REVISION, adapter_id="stage13_v1", checkpoint="checkpoint-80")
    assert a.key != b.key
    assert same_weights(a, b, None)[0] is False


def test_d_an_adapter_without_a_checkpoint_is_unresolved_not_collapsed():
    m = ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REVISION, adapter_id="stage13_v1")
    assert m.checkpoint_unresolved and m.recorded is False
    assert "@adapter" not in m.key and m.key.startswith(f"{UNRECORDED}:")
    resolved = ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REVISION, adapter_id="stage13_v1", checkpoint="checkpoint-90")
    assert m.key != resolved.key
    current = CurrentSystem(model=resolved, pipeline_fingerprint=_FP)
    out = resolve_freshness([_experiment(model=m, question_set=_FULL, pipeline_fingerprint={**_FP, "verified": True})], current)
    assert (out[0].status, out[0].freshness_code) == (HISTORICAL, "checkpoint_unresolved")
    assert "not which checkpoint" in out[0].status_reason


def test_d_the_checkpoint_comes_from_a_fact_or_not_at_all(tmp_path):
    from regulus.finetune.adapter import adapter_identity

    no_meta = _adapter_run(tmp_path, "no_best", best=None)
    assert resolve_adapter(adapter_identity(no_meta))["checkpoint"] is None
    ckpt = tmp_path / "models" / "run_z" / "checkpoints" / "checkpoint-40"
    ckpt.mkdir(parents=True)
    (ckpt / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": "Qwen/Qwen3-0.6B"}), encoding="utf-8")
    resolved = resolve_adapter(adapter_identity(ckpt))
    assert (resolved["adapter_name"], resolved["checkpoint"]) == ("run_z", "checkpoint-40")


def test_d_a_manifest_naming_an_adapter_but_no_checkpoint_is_unresolved(tmp_path):
    d = _write_stage5_dir(tmp_path, run_ids=["A"], bench_ids=["A"], manifest_extra={"model": {
        "id": "Qwen/Qwen3-0.6B", "revision": REVISION, "adapter_name": "stage13_v1", "checkpoint": None}})
    run = stage5_adapter.load(d)
    assert run.model.checkpoint_unresolved and not run.model.recorded
    assert any("no checkpoint" in p for p in run.problems)


# ------------------------------------------------ E / F: question sets


def test_e_question_set_identity_depends_on_the_ids_only():
    full = [f"S5-{i:03d}" for i in range(1, 52)]
    assert question_set_identity(full).sha256 != question_set_identity(full[:2]).sha256
    assert question_set_identity(full).count == 51
    assert question_set_identity(reversed(full)).sha256 == question_set_identity(full).sha256
    expected = hashlib.sha256(json.dumps(sorted(full), separators=(",", ":")).encode()).hexdigest()
    assert question_set_identity(full).sha256 == expected   # the documented algorithm


def test_f_a_completed_subset_is_not_a_full_benchmark_run(tmp_path):
    bench = [f"S5-{i:03d}" for i in range(1, 52)]
    d = _write_stage5_dir(tmp_path, run_ids=bench[:2], bench_ids=bench)
    run = stage5_adapter.load(d)
    assert run.status == COMPLETE                     # the process completed ...
    assert run.full_benchmark is False                # ... the benchmark did not
    assert run.question_set["count"] == 2 and run.question_set["benchmark_questions"] == 51


def test_f_a_subset_can_never_be_current_even_with_a_known_model():
    known = dict(model=_CURRENT.model, pipeline_fingerprint={**_FP, "verified": True})
    partial = _experiment(experiment_id="smoke", completed_at="2026-03-01T00:00:00+00:00",
                          question_set={"count": 2, "benchmark_questions": 51, "full_benchmark": False}, **known)
    full = _experiment(experiment_id="full", completed_at="2026-01-01T00:00:00+00:00",
                       question_set={"count": 51, "benchmark_questions": 51, "full_benchmark": True}, **known)
    out = {e.experiment_id: e for e in resolve_freshness([partial, full], _CURRENT)}
    assert (out["smoke"].status, out["smoke"].freshness_code) == (INCOMPLETE, "question_set_is_subset")
    assert "partial benchmark" in out["smoke"].status_reason
    assert out["full"].status == CURRENT


def test_f_the_runner_marks_a_limited_run_as_partial(tmp_path, fake_stage5):
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 5), limit=2)
    assert _manifest(stage_dir)["question_set"]["full_benchmark"] is False
    assert stage5_adapter.load(stage_dir).full_benchmark is False


# ------------------------------------------------ G / H / I: pipeline fingerprint


def _config(**budget):
    return {
        "retrieval": {"retriever": "LexicalRetriever", "top_k": 8, "corpus": "all",
                      "min_trigram_similarity": 0.4, "exclude_contextual_only": True},
        "coverage": {"no_context_behavior": "refuse", "incomplete_behavior": "partial"},
        "context": ContextPolicy().to_dict(),
        "generation_budget": {**GenerationBudget().to_dict(), **budget},
        "decoding": {"do_sample": False, "temperature": 0.7, "top_p": 0.8, "top_k": 20, "enable_thinking": False,
                     "repetition_penalty": 1.0, "no_repeat_ngram_size": 0},
        "validation": {"validation_behavior": "annotate"},
        "repair": {"mode": "post_hoc_deterministic"},
        "prompt": {"system_prompt_sha256": "p" * 64},
    }


def test_g_the_fingerprint_is_deterministic_and_order_independent():
    a = pipeline_fingerprint(_config())
    reordered = {k: dict(reversed(list(v.items()))) for k, v in reversed(list(_config().items()))}
    assert a == pipeline_fingerprint(_config()) == pipeline_fingerprint(reordered)
    # version 2 since Stage 12 added prompt.answer_shape (docs/adaptive_answer_shape.md);
    # version 3 since the Stage 5 answerability gate added coverage.answerability;
    # version 4 since Stage 6 added coverage.optional_context; version 5 since Stage 7 added
    # retrieval.semantic_fallback and coverage.scope_policy
    # version 6 since Stage 8 added coverage.evidence_consolidation
    assert a.version == 6 and a.algorithm == "sha256" and len(a.value) == 64


@pytest.mark.parametrize("section,field,value", [
    ("generation_budget", "min_tokens", 448),
    ("generation_budget", "hard_max_tokens", 448),
    ("generation_budget", "policy", "fixed"),
    ("retrieval", "top_k", 4),
    ("context", "max_total_chars", 9000),
    ("decoding", "do_sample", True),
    ("validation", "validation_behavior", "repair"),
    ("prompt", "system_prompt_sha256", "q" * 64),
])
def test_h_an_evaluation_relevant_change_changes_the_fingerprint(section, field, value):
    changed = _config()
    changed[section][field] = value
    assert pipeline_fingerprint(changed) != pipeline_fingerprint(_config())


def test_h_the_answer_length_floor_256_to_448_changes_the_fingerprint():
    assert pipeline_fingerprint(_config(min_tokens=256)) != pipeline_fingerprint(_config(min_tokens=448))


def test_i_irrelevant_changes_do_not_change_the_fingerprint():
    base = pipeline_fingerprint(_config())
    noisy = _config()
    noisy["decoding"]["temperature"] = 1.3            # ignored under greedy decoding
    noisy["decoding"]["top_k"] = 50
    noisy["retrieval"]["cache_dir"] = "D:/elsewhere"  # not an evaluation field
    noisy["run_id"] = "another-run"
    noisy["started_at"] = utc_now()
    assert pipeline_fingerprint(noisy) == base
    floats = _config()
    floats["generation_budget"]["hard_max_tokens"] = 2048.0
    assert pipeline_fingerprint(floats) == base


def test_i_the_global_max_new_tokens_does_not_enter_the_fingerprint(tmp_path, fake_stage5, monkeypatch):
    """The pipeline always passes its own per-question budget, so this value is never used."""
    from regulus.config import settings as settings_module

    dataset = _dataset(tmp_path, 2)
    first = _manifest(_run(tmp_path, dataset=dataset, run_dir=tmp_path / "r1"))["pipeline_fingerprint"]
    real_load = settings_module.load_settings

    def load_with_other_cap(*args, **kwargs):
        s = real_load(*args, **kwargs)
        s.generation.max_new_tokens = 999
        return s

    import regulus.config
    monkeypatch.setattr(regulus.config, "load_settings", load_with_other_cap)
    second = _manifest(_run(tmp_path, dataset=dataset, run_dir=tmp_path / "r2"))["pipeline_fingerprint"]
    assert first == second


def test_every_configuration_field_is_classified():
    """A new RagConfig, budget, context or decoding field must be added to the
    fingerprint or explicitly excluded; it can never slip in unnoticed."""
    excluded_generation = {"max_new_tokens"}
    rag = RagConfig().to_dict()
    listed = {f for fields in FINGERPRINT_FIELDS.values() for f in fields}
    assert set(rag) - {"generation_budget", "context"} <= listed
    assert set(GenerationBudget().to_dict()) == set(FINGERPRINT_FIELDS["generation_budget"])
    assert set(ContextPolicy().to_dict()) == set(FINGERPRINT_FIELDS["context"])
    assert set(vars(GenerationConfig())) - excluded_generation == set(FINGERPRINT_FIELDS["decoding"])


def test_a_missing_section_is_explicit_not_silently_equal():
    partial = _config()
    del partial["decoding"]
    assert normalize_evaluation_config(partial)["decoding"] is None
    assert pipeline_fingerprint(partial) != pipeline_fingerprint(_config())


def test_a_tampered_fingerprint_is_reported_unverified(tmp_path):
    config = normalize_evaluation_config(_config())
    fp = pipeline_fingerprint(config).to_dict()
    fp["value"] = "0" * 64
    d = _write_stage5_dir(tmp_path, run_ids=["A"], bench_ids=["A"],
                          manifest_extra={"evaluation_config": config, "pipeline_fingerprint": fp})
    run = stage5_adapter.load(d)
    assert run.pipeline_fingerprint["verified"] is False
    assert any("does not match the evaluation_config" in p for p in run.problems)


# ------------------------------------------------ J: timestamps


def test_j_new_timestamps_are_timezone_aware_utc(tmp_path, fake_stage5):
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 2))
    m = _manifest(stage_dir)
    stamps = [m["started_at"], m["completed_at"], *(i["started_at"] for i in m["invocations"])]
    stamps += [json.loads((stage_dir / f"phase_{p}.json").read_text())["finished_at"]
               for p in ("evidence", "generation", "report")]
    parsed = [datetime.fromisoformat(s) for s in stamps]
    assert all(p.tzinfo is not None and p.utcoffset().total_seconds() == 0 for p in parsed)
    assert parsed[0] <= parsed[1]
    # one format everywhere, so string order equals time order
    assert sorted(stamps) == [s for _, s in sorted(zip(parsed, stamps))]
    run = stage5_adapter.load(stage_dir)
    assert run.started_at == m["started_at"] and run.duration_seconds is not None
    assert run.metric("run_duration").value == run.duration_seconds


# ------------------------------------------------ K: selected evidence ids


def _source(index: int, evidence_id: str) -> PackagedSource:
    return PackagedSource(index=index, tier="exact", requirement_ids=("r1",), protected=True, corpus="ecfr",
                          citation="21 CFR 820.10", heading=None, url=None, text="text", truncated=False,
                          evidence_id=evidence_id, key=evidence_id)


def _package(sources) -> GenerationPackage:
    return GenerationPackage(question="q", requirements=(("r1", "21 CFR 820.10"),), satisfied_ids=("r1",),
                             missing_labels=(), sources=tuple(sources), notes=(), shape="single",
                             max_new_tokens=256, coverage_state="COMPLETE", budget=GenerationBudget())


def test_k_selected_ids_are_the_sources_in_the_prompt_in_prompt_order():
    package = _package([_source(2, "ev-second"), _source(1, "ev-first"), _source(3, "ev-third")])
    assert generation_eval.selected_evidence_ids(package) == ["ev-first", "ev-second", "ev-third"]


def test_k_a_generation_record_carries_its_selected_ids(monkeypatch):
    for name in ("claims", "_completeness", "_hallucination", "_citations", "_refusal_block"):
        monkeypatch.setattr(generation_eval, name, lambda *a, _n=name, **k: [] if _n == "claims" else {})
    monkeypatch.setattr(generation_eval, "build_grounded_messages", lambda p: [{}, {"content": "prompt"}])
    report = SimpleNamespace(ok=True, to_dict=lambda: {"status": "valid"}, truncated=False)
    ex = SimpleNamespace(id="S5-001", category="single", expected_behavior="answer", domain="regulatory")
    package = _package([_source(1, "ev-a"), _source(2, "ev-b")])
    record = generation_eval._record(ex, "full", package, "raw", "raw", None, report, report,
                                     {"max_new_tokens": 256}, "answer", {}, 1.0, [], None)
    assert record["selected_ids"] == ["ev-a", "ev-b"]


def test_k_a_question_answered_without_the_model_records_no_selection():
    ex = SimpleNamespace(id="S5-002", category="refusal", question="q", expected_behavior="refuse", domain="regulatory")
    out = SimpleNamespace(package=None, model_called=False, no_context=True, answer="cannot answer",
                          metadata={"coverage_action": "refuse_unsupported"}, citations=[], timings_ms={})
    record = generation_eval.run_full(ex, SimpleNamespace(answer=lambda q: out))
    assert record["selected_ids"] is None


def test_k_the_forensic_view_prefers_the_generations_own_evidence(tmp_path, fake_stage5):
    run = stage5_adapter.load(_run(tmp_path, dataset=_dataset(tmp_path, 2)))
    q = run.questions[0]
    assert [e["evidence_id"] for e in q.selected_evidence] == [f"gen-ev-{q.id}-a", f"gen-ev-{q.id}-b"]
    assert q.selected_evidence[0]["prompt_index"] == 1
    assert "generation_full.jsonl" in q.extra["selected_evidence_source"]


def test_k_an_old_record_falls_back_to_the_evidence_phase_and_says_so(tmp_path):
    d = _write_stage5_dir(tmp_path, run_ids=["A"], bench_ids=["A"])
    (d / "evidence_records.jsonl").write_text(json.dumps({"id": "A", "selection": {"selected_ids": ["ev-1"]}}) + "\n",
                                              encoding="utf-8")
    q = stage5_adapter.load(d).questions[0]
    assert [e["evidence_id"] for e in q.selected_evidence] == ["ev-1"]
    assert "does not say which evidence the model was given" in q.extra["selected_evidence_source"]
