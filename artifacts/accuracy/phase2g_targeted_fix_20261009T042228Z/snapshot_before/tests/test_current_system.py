"""Phase 2: the configured system, and the one rule that decides CURRENT.

These tests answer one question: does the backend call an evaluation CURRENT
exactly when it measured the system configured today (same weights, same
pipeline, the whole benchmark), and never otherwise?
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import threading
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from regulus.config import PROJECT_ROOT
from regulus.dashboard import freshness
from regulus.dashboard import registry as R
from regulus.dashboard.adapters import stage5 as stage5_adapter
from regulus.dashboard.fingerprint import pipeline_fingerprint
from regulus.dashboard.health import current_health
from regulus.dashboard.registry import Registry, read_current_system
from regulus.dashboard.schemas import CURRENT, HISTORICAL, INCOMPLETE, STALE

from .current_system_fixtures import (
    OTHER_REVISION,
    REVISION,
    ROOTS,
    model_block_for,
    stage5_run,
    write_adapter,
    write_project,
)
from .test_dashboard_adapters import _answer_file
from .test_stage5_identity import _dataset, _manifest, _run, fake_stage5  # noqa: F401  (fixture)


def _statuses(root: Path) -> dict[str, tuple[str, str]]:
    registry = Registry(root, roots=ROOTS, store=root / "store.json")
    return {e.name: (e.status, e.freshness_code) for e in registry.experiments if e.kind == "evaluation"}


@pytest.fixture(autouse=True)
def _no_regulus_env(monkeypatch):
    """Tests control the configuration; a developer's REGULUS_* must not leak in."""
    for name in ("REGULUS_MODEL_ID", "REGULUS_ADAPTER", "REGULUS_MODEL_CACHE_DIR", "REGULUS_DEVICE",
                 "REGULUS_DTYPE", "REGULUS_ANSWER_LENGTH_POLICY", "REGULUS_MAX_NEW_TOKENS"):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------ A-C: current system resolution


def test_a_the_configured_model_is_the_current_identity(tmp_path):
    root = write_project(tmp_path / "a")
    current = read_current_system(root)
    assert current.resolved
    assert current.model.base_model_id == "Qwen/Qwen3-0.6B"
    assert current.model.revision == REVISION          # from the cache the loader resolves against
    assert current.model.adapter_id is None
    assert current.model.key == f"Qwen/Qwen3-0.6B@{REVISION}+base"

    other = read_current_system(write_project(tmp_path / "b", model_id="Other/model", revision=OTHER_REVISION))
    assert other.model.base_model_id == "Other/model" and other.model.revision == OTHER_REVISION
    assert other.model.key != current.model.key


def test_a_an_uncached_revision_leaves_the_system_unresolved(tmp_path):
    root = write_project(tmp_path / "p")
    (root / "hf_cache" / "models--Qwen--Qwen3-0.6B" / "refs" / "main").unlink()
    current = read_current_system(root)
    assert not current.resolved and current.model.revision is None
    assert any("refs" in why for why in current.unresolved)


def test_b_a_configured_adapter_is_part_of_the_current_identity(tmp_path):
    root = tmp_path / "p"
    adapter = write_adapter(root, "lora_x", best="checkpoint-80")
    current = read_current_system(write_project(root, adapter=adapter))
    assert current.resolved
    assert (current.model.adapter_id, current.model.checkpoint) == ("lora_x", "checkpoint-80")
    assert current.model.key == f"Qwen/Qwen3-0.6B@{REVISION}+lora_x@checkpoint-80"
    assert current.source["checkpoint_source"] == "metadata.json best_checkpoint of the training run"


def test_b_an_adapter_whose_checkpoint_is_unknown_is_not_guessed(tmp_path):
    root = tmp_path / "p"
    adapter = write_adapter(root, "lora_x", best=None)
    current = read_current_system(write_project(root, adapter=adapter))
    assert not current.resolved and current.model.checkpoint_unresolved
    assert any("does not say which checkpoint" in why for why in current.unresolved)


def test_b_an_adapter_for_another_base_model_is_not_accepted(tmp_path):
    root = tmp_path / "p"
    adapter = write_adapter(root, "lora_x", base="Some/other-base")
    current = read_current_system(write_project(root, adapter=adapter))
    assert not current.resolved
    assert any("was trained on Some/other-base" in why for why in current.unresolved)


def test_b_a_missing_adapter_directory_is_reported(tmp_path):
    current = read_current_system(write_project(tmp_path / "p", adapter=tmp_path / "nowhere" / "adapter"))
    assert not current.resolved
    assert any("cannot be read" in why for why in current.unresolved)


def test_c_environment_overrides_change_the_current_identity(tmp_path, monkeypatch):
    root = write_project(tmp_path / "p")
    write_project(root, model_id="Other/model", revision=OTHER_REVISION)  # cache stub for the override
    write_project(root)                                                   # config back to Qwen
    monkeypatch.setenv("REGULUS_MODEL_ID", "Other/model")
    assert read_current_system(root).model.base_model_id == "Other/model"

    adapter = write_adapter(root, "lora_env", best="checkpoint-40")
    monkeypatch.setenv("REGULUS_ADAPTER", adapter.as_posix())
    assert read_current_system(root).model.adapter_id == "lora_env"
    monkeypatch.setenv("REGULUS_ADAPTER", "none")                        # clears a configured adapter
    assert read_current_system(root).model.adapter_id is None


# ------------------------------------------------ D: one fingerprint implementation


def test_d_the_runner_and_the_dashboard_compute_the_same_fingerprint(tmp_path, fake_stage5):  # noqa: F811
    """Stage 5 (real runner, real factory, real load_qwen_generator) and the
    dashboard's view of the configured system agree exactly."""
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 3))
    manifest = _manifest(stage_dir)
    current = read_current_system(PROJECT_ROOT)
    assert manifest["pipeline_fingerprint"] == current.pipeline_fingerprint
    assert manifest["evaluation_config"] == current.evaluation_config


def test_e_a_run_made_by_the_real_runner_is_current(tmp_path, fake_stage5):  # noqa: F811
    """End to end: what the runner records is what the engine accepts."""
    stage_dir = _run(tmp_path, dataset=_dataset(tmp_path, 3))
    run = stage5_adapter.load(stage_dir)
    experiment = R._experiment("evaluation", "stage5", stage_dir, tmp_path, run)
    out = freshness.resolve([experiment], read_current_system(PROJECT_ROOT))[0]
    assert (out.status, out.freshness_code) == (CURRENT, "current"), out.status_reason


# ------------------------------------------------ E-L: the CURRENT rule


def test_e_matching_model_pipeline_and_whole_benchmark_is_current(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "good")
    assert _statuses(root)["good"] == (CURRENT, "current")


@pytest.mark.parametrize("section,field,value", [
    ("generation_budget", "min_tokens", 448),        # answer length
    ("generation_budget", "hard_max_tokens", 448),
    ("retrieval", "top_k", 4),                        # retrieval
    ("context", "max_total_chars", 9000),
    ("repair", "mode", "none"),                       # repair
    ("validation", "validation_behavior", "repair"),
    ("decoding", "do_sample", True),
])
def test_f_same_weights_different_pipeline_is_not_current(tmp_path, section, field, value):
    root = write_project(tmp_path / "p")
    config = json.loads(json.dumps(read_current_system(root).evaluation_config))
    config[section][field] = value
    stage5_run(root, "other_pipeline", evaluation_config=config)
    assert _statuses(root)["other_pipeline"] == (STALE, "pipeline_fingerprint_mismatch")


def test_g_a_run_without_a_fingerprint_is_not_current(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "no_fingerprint", evaluation_config=None, fingerprint=None)
    assert _statuses(root)["no_fingerprint"] == (HISTORICAL, "pipeline_fingerprint_missing")


def test_g_a_fingerprint_that_does_not_verify_is_not_current(tmp_path):
    root = write_project(tmp_path / "p")
    current = read_current_system(root)
    # the recorded fingerprint equals the current one, but the stored config
    # it claims to summarise says something else: it is not evidence
    tampered = json.loads(json.dumps(current.evaluation_config))
    tampered["retrieval"]["top_k"] = 4
    stage5_run(root, "tampered", evaluation_config=tampered, fingerprint=current.pipeline_fingerprint)
    assert _statuses(root)["tampered"] == (HISTORICAL, "pipeline_fingerprint_unverified")


def test_h_the_real_stage5_baseline_stays_unrecorded_and_historical():
    registry_path = PROJECT_ROOT / "artifacts" / "stage5_stage6" / "stage5_baseline_20260923" / "stage5"
    if not registry_path.is_dir():
        pytest.skip("the Stage 5 baseline is not on this machine")
    found, _ = R.discover(PROJECT_ROOT)
    resolved = {e.path: e for e in R.resolve_freshness(found.experiments, read_current_system(PROJECT_ROOT))}
    baseline = resolved["artifacts/stage5_stage6/stage5_baseline_20260923/stage5"]
    assert baseline.model.base_model_id == "unrecorded"
    assert baseline.pipeline_fingerprint is None                         # today's is never attached
    assert (baseline.status, baseline.freshness_code) == (HISTORICAL, "model_identity_unrecorded")


def test_i_a_partial_benchmark_is_not_current(tmp_path):
    root = write_project(tmp_path / "p")
    bench = tuple(f"S5-{i:03d}" for i in range(1, 52))
    stage5_run(root, "smoke", ids=bench[:2], bench_ids=bench)
    assert _statuses(root)["smoke"] == (INCOMPLETE, "question_set_is_subset")


def test_j_another_model_is_not_current(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "other_model", model={**model_block_for(root), "id": "Other/model"})
    stage5_run(root, "other_revision", model={**model_block_for(root), "revision": OTHER_REVISION})
    stage5_run(root, "no_revision", model={**model_block_for(root), "revision": None})
    s = _statuses(root)
    assert s["other_model"] == (HISTORICAL, "model_mismatch")
    assert s["other_revision"] == (HISTORICAL, "model_mismatch")
    assert s["no_revision"] == (HISTORICAL, "model_revision_unrecorded")


def test_k_another_checkpoint_of_the_configured_adapter_is_not_current(tmp_path):
    root = tmp_path / "p"
    adapter = write_adapter(root, "lora_x", best="checkpoint-80")
    write_project(root, adapter=adapter)
    block = model_block_for(root)
    stage5_run(root, "ckpt80", model=block)
    stage5_run(root, "ckpt40", model={**block, "checkpoint": "checkpoint-40"})
    stage5_run(root, "base", model={**block, "adapter_name": None, "checkpoint": None, "adapter_dir": None})
    s = _statuses(root)
    assert s["ckpt80"] == (CURRENT, "current")
    assert s["ckpt40"] == (HISTORICAL, "model_mismatch")
    assert s["base"] == (HISTORICAL, "model_mismatch")


def test_l_a_legacy_run_is_not_promoted_because_its_model_name_matches(tmp_path):
    root = write_project(tmp_path / "p")
    path = _answer_file(root / "data" / "evaluation" / "results")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run"]["model_revision"] = REVISION         # same name, same revision
    path.write_text(json.dumps(payload), encoding="utf-8")
    status = [v for k, v in _statuses(root).items()]
    assert status == [(HISTORICAL, "pipeline_fingerprint_missing")]


def test_l_the_real_27_question_legacy_run_is_not_current():
    found, _ = R.discover(PROJECT_ROOT)
    resolved = R.resolve_freshness(found.experiments, read_current_system(PROJECT_ROOT))
    gated = [e for e in resolved if "rag-stage13-base-gated" in e.path]
    if not gated:
        pytest.skip("the legacy stage13 gated run is not on this machine")
    assert (gated[0].status, gated[0].freshness_code) == (HISTORICAL, "pipeline_fingerprint_missing")
    # and no legacy pipeline is CURRENT, so stage7/9/10/gatecheck/13 cannot be pooled into one
    assert not [e for e in resolved if e.path.startswith("data/evaluation/results") and e.status == CURRENT]


# ------------------------------------------------ M, N: the health API


@pytest.fixture
def served(tmp_path):
    def serve(root: Path):
        path = PROJECT_ROOT / "scripts" / "serve_dashboard.py"
        import importlib.util

        spec = importlib.util.spec_from_file_location(f"serve_dashboard_{id(root)}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.STATE = module.State(root, store=tmp_path / "store.json")
        module.STATE.registry.roots = ROOTS
        module.STATE.registry.refresh()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        return lambda p: json.loads(urllib.request.urlopen(base + p, timeout=30).read().decode("utf-8"))

    servers: list = []
    yield serve
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def test_m_with_no_compatible_evaluation_the_api_says_not_evaluated(tmp_path, served):
    root = write_project(tmp_path / "p")
    bench = tuple(f"S5-{i:03d}" for i in range(1, 52))
    # everything that must NOT stand in for the current system
    stage5_run(root, "partial", ids=bench[:2], bench_ids=bench, completed_at="2026-12-01T00:00:00+00:00")
    config = json.loads(json.dumps(read_current_system(root).evaluation_config))
    config["generation_budget"]["min_tokens"] = 448
    stage5_run(root, "other_pipeline", evaluation_config=config, bench_name="b2")
    stage5_run(root, "unrecorded", model=None, bench_name="b3")
    get = served(root)
    h = get("/api/model-health/current")
    assert (h["state"], h["status"], h["reason"]) == ("not_evaluated", "not_evaluated", "no_current_evaluation")
    assert h["evaluation"] is None and h["benchmarks"] == [] and h["sections"] == []
    assert h["evaluations_by_freshness"] == {"model_identity_unrecorded": 1, "pipeline_fingerprint_mismatch": 1,
                                             "question_set_is_subset": 1}
    assert "metrics" not in (h["latest_available"] or {})

    system = get("/api/system/current-model")
    assert system["resolved"] is True and system["has_current_evaluation"] is False
    assert system["model"]["base_model_id"] == "Qwen/Qwen3-0.6B" and system["model"]["revision"] == REVISION
    assert system["pipeline_fingerprint"]["value"] == read_current_system(root).pipeline_fingerprint["value"]
    assert system["system"]["source"]["config_file"].endswith("configs/model.yaml")


def test_m_with_a_compatible_evaluation_the_api_serves_only_its_numbers(tmp_path, served):
    root = write_project(tmp_path / "p")
    stage5_run(root, "good")
    get = served(root)
    h = get("/api/model-health/current")
    assert (h["status"], h["reason"]) == ("evaluated", "current_evaluation")
    assert h["evaluation"]["name"] == "good" and len(h["benchmarks"]) == 1
    run_metrics = {m["key"] for m in get(f"/api/evaluation/experiments/{h['evaluation']['experiment_id']}/metrics")["metrics"]}
    assert {m["key"] for s in h["sections"] for m in s["metrics"]} == run_metrics


def test_n_a_count_over_no_applicable_questions_is_not_zero(tmp_path):
    """The fixture has no question expecting a refusal: false answers were not
    measured, which must not be reported as 0 false answers."""
    root = write_project(tmp_path / "p")
    run = stage5_adapter.load(stage5_run(root, "good"), root=root)
    for key in ("false_answer_count", "refusal_correct", "coverage_missing_ok"):
        m = run.metric(key)
        assert m.value is None and m.status == "missing", key
        assert m.numerator is None and m.denominator is None, key


# ------------------------------------------------ O: deterministic selection


def test_o_among_compatible_runs_the_choice_is_deterministic(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "early", completed_at="2026-01-01T00:00:00+00:00")
    stage5_run(root, "late", completed_at="2026-02-01T00:00:00+00:00")
    stage5_run(root, "tie_a", completed_at="2026-02-01T00:00:00+00:00")
    registry = Registry(root, roots=ROOTS, store=root / "store.json")
    experiments = [e for e in registry.experiments if e.kind == "evaluation"]
    current = registry.current_system
    winners = set()
    for seed in range(5):
        shuffled = experiments[:]
        random.Random(seed).shuffle(shuffled)
        reset = [replace(e, status="COMPLETE") for e in shuffled]
        winners.add(next(e.name for e in freshness.resolve(reset, current) if e.status == CURRENT))
    # latest time wins; the tie at that time is broken by artifact path
    assert winners == {"tie_a"}
    s = _statuses(root)
    assert s["early"] == (STALE, "superseded") and s["late"] == (STALE, "superseded")


def test_o_a_timestamp_with_an_offset_is_ordered_by_its_instant(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "utc_later", completed_at="2026-02-01T05:00:00+00:00")
    stage5_run(root, "ist_earlier", completed_at="2026-02-01T10:00:00+05:30")   # 04:30 UTC
    s = _statuses(root)
    assert s["utc_later"] == (CURRENT, "current") and s["ist_earlier"] == (STALE, "superseded")


# ------------------------------------------------ P, Q: configuration changes


def test_p_changing_an_evaluation_relevant_setting_invalidates_current(tmp_path, monkeypatch):
    root = write_project(tmp_path / "p")
    stage5_run(root, "good")
    assert _statuses(root)["good"] == (CURRENT, "current")
    write_project(root, answer_length={"min_tokens": 448})                  # configs/model.yaml
    assert _statuses(root)["good"] == (STALE, "pipeline_fingerprint_mismatch")
    write_project(root)
    monkeypatch.setenv("REGULUS_ANSWER_LENGTH_POLICY", "fixed")             # environment
    assert _statuses(root)["good"] == (STALE, "pipeline_fingerprint_mismatch")


def test_q_changing_an_irrelevant_setting_keeps_current(tmp_path, monkeypatch):
    root = write_project(tmp_path / "p")
    stage5_run(root, "good")
    config = root / "configs" / "model.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('device: "auto"', 'device: "cpu"').replace('dtype: "auto"', 'dtype: "float32"')
        + "generation:\n  max_new_tokens: 999\n  temperature: 1.3\n  top_p: 0.5\n  top_k: 3\n  do_sample: true\n",
        encoding="utf-8")
    # device and dtype are runtime, not identity; sampling settings and the
    # global max_new_tokens are overridden by the pipeline (greedy, per-question
    # allowance), so none of them changes what is measured
    assert _statuses(root)["good"] == (CURRENT, "current")


# ------------------------------------------------ the process boundary


def test_resolving_the_current_system_loads_no_model_stack():
    """The dashboard resolves the configured system without torch, transformers or peft."""
    code = ("import sys; from regulus.dashboard.registry import read_current_system; "
            "from regulus.config import PROJECT_ROOT; c = read_current_system(PROJECT_ROOT); "
            "print(sorted(m for m in ('torch', 'transformers', 'peft') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=PROJECT_ROOT, env={**__import__("os").environ, "PYTHONPATH": str(PROJECT_ROOT / "src")})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ------------------------------------------------ latency integrity


def test_latency_percentiles_are_recomputed_from_the_question_timings(tmp_path):
    root = write_project(tmp_path / "p")
    d = stage5_run(root, "good")
    rows = [json.loads(line) for line in (d / "generation_full.jsonl").read_text(encoding="utf-8").splitlines()]
    for row, (gen_ms, total_ms) in zip(rows, ((1000.0, 1500.0), (2000.0, 2600.0), (9000.0, 9800.0))):
        row["timings_ms"] = {"generation_ms": gen_ms, "total_ms": total_ms}
    (d / "generation_full.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    consistent = {"phases_ms": {"generation": {"p50": 2000.0, "p95": 9000.0}, "end_to_end": {"p50": 2600.0, "p95": 9800.0}}}
    (d / "latency_results.json").write_text(json.dumps(consistent), encoding="utf-8")
    run = stage5_adapter.load(d, root=root)
    p50 = run.metric("generation_latency_p50")
    assert (p50.value, p50.status) == (2.0, "ok") and "timings_ms" in p50.recomputed_from

    wrong = {"phases_ms": {"generation": {"p50": 7000.0, "p95": 9000.0}, "end_to_end": {"p50": 2600.0, "p95": 9800.0}}}
    (d / "latency_results.json").write_text(json.dumps(wrong), encoding="utf-8")
    p50 = stage5_adapter.load(d, root=root).metric("generation_latency_p50")
    assert p50.value == 7.0, "the stored aggregate is still what is shown"
    assert p50.status == "inconsistent" and "2.0" in p50.note


def test_the_real_baseline_latency_agrees_with_its_question_timings():
    baseline = PROJECT_ROOT / "artifacts" / "stage5_stage6" / "stage5_baseline_20260923" / "stage5"
    if not baseline.is_dir():
        pytest.skip("the Stage 5 baseline is not on this machine")
    run = stage5_adapter.load(baseline, root=PROJECT_ROOT)
    for key in ("generation_latency_p50", "generation_latency_p95", "e2e_latency_p50", "e2e_latency_p95"):
        m = run.metric(key)
        assert m.status == "ok" and m.recomputed_from, (key, m.note)
