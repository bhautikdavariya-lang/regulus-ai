"""Tests for discovery, freshness, comparison and the read-only API.

The registry is where a dashboard decides what counts as "how good is the
model right now", so most of these tests are about what it refuses to claim:
that a historical run is current, that an unfinished run replaces a finished
one, or that two runs on different benchmarks can be differenced.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from regulus.dashboard import registry as R
from regulus.dashboard.compare import compare
from regulus.dashboard.registry import Registry, Root, discover, read_current_model, resolve_freshness
from regulus.dashboard.schemas import (
    COMPLETE,
    CURRENT,
    FAILED,
    HISTORICAL,
    INCOMPLETE,
    KIND_EVALUATION,
    STALE,
    BenchmarkIdentity,
    CurrentSystem,
    Experiment,
    ModelIdentity,
)

from .test_dashboard_adapters import _answer_file, _retrieval_file, _training_run
from .test_dashboard_stage5_adapter import _make_run as _stage5_run

PROJECT = Path.cwd()


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A miniature project root holding one of each artifact family."""
    root = tmp_path / "proj"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "model.yaml").write_text(
        'model:\n  id: "Qwen/Qwen3-0.6B"\n  device: "auto"\n  dtype: "auto"\n', encoding="utf-8")

    # _stage5_run writes <parent>/run/stage5, which lands at the artifacts/*/*/*
    # depth the scanner looks at
    (root / "artifacts" / "group").mkdir(parents=True)
    _stage5_run(root / "artifacts" / "group")

    results = root / "data" / "evaluation" / "results"
    results.mkdir(parents=True)
    _answer_file(results)
    _retrieval_file(results)
    (results / "not-an-evaluation.json").write_text(json.dumps({"counters": {}}), encoding="utf-8")

    models = root / "models" / "qwen3-0.6b-lora"
    models.mkdir(parents=True)
    _training_run(models)
    return root


ROOTS = (
    Root("artifacts", "*/*/*", False, "stage 5 runs"),
    Root("models/qwen3-0.6b-lora", "*", False, "training runs"),
    Root("data/evaluation/results", "**/*.json", True, "legacy results"),
)


def _registry(root: Path) -> Registry:
    return Registry(root, roots=ROOTS)


REV = "c1899de289a04d12100db370d81485cdf75e47ca"
FP = {"version": 1, "algorithm": "sha256", "value": "f" * 64}
CURRENT_SYSTEM = CurrentSystem(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REV),
                               pipeline_fingerprint=FP)


def _experiment(**kwargs) -> Experiment:
    """By default a run that meets every CURRENT condition, so each test can
    take exactly one of them away."""
    defaults = dict(
        experiment_id="x", name="run", kind=KIND_EVALUATION, status=COMPLETE, path="p",
        model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REV),
        benchmark=BenchmarkIdentity(benchmark_id="b", sha256="a" * 64),
        completed_at="2026-01-01T00:00:00+00:00",
        question_set={"count": 3, "benchmark_questions": 3, "full_benchmark": True},
        pipeline_fingerprint={**FP, "verified": True},
    )
    defaults.update(kwargs)
    return Experiment(**defaults)


# ----------------------------------------------------------------- discovery


def test_discovery_finds_each_artifact_family(project):
    found, loaded = discover(project, ROOTS)
    kinds = sorted(e.kind for e in found.experiments)
    names = sorted(e.name for e in found.experiments)
    assert kinds.count("evaluation") == 3      # stage 5, legacy answer, legacy retrieval
    assert kinds.count("training") == 1
    assert "unit_v1" in names
    assert not found.errors
    assert len(loaded) == len(found.experiments)


def test_an_unclaimed_artifact_is_listed_not_skipped(project):
    found, _ = discover(project, ROOTS)
    assert [u["path"] for u in found.unsupported] == ["data/evaluation/results/not-an-evaluation.json"]
    assert "no adapter recognised" in found.unsupported[0]["reason"]


def test_discovery_is_generic_so_a_new_run_appears(project):
    before, _ = discover(project, ROOTS)
    _training_run(project / "models" / "qwen3-0.6b-lora", name="second")
    after, _ = discover(project, ROOTS)
    assert len(after.experiments) == len(before.experiments) + 1
    assert any(e.path.endswith("qwen3-0.6b-lora/second") for e in after.experiments)


def test_a_broken_artifact_is_reported_without_breaking_the_scan(project, monkeypatch):
    from regulus.dashboard.adapters import training as training_adapter

    def explode(path, root=None):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(training_adapter, "load", explode)
    found, _ = discover(project, ROOTS)
    assert found.errors and found.errors[0]["error"].startswith("RuntimeError")
    assert [e.kind for e in found.experiments].count("evaluation") == 3, "the other families still loaded"


def test_experiment_ids_are_stable_and_path_derived(project):
    first, _ = discover(project, ROOTS)
    second, _ = discover(project, ROOTS)
    assert {e.experiment_id for e in first.experiments} == {e.experiment_id for e in second.experiments}
    assert len({e.experiment_id for e in first.experiments}) == len(first.experiments)


# ------------------------------------------------------------- current model


def test_current_model_is_read_from_the_pipeline_config(project):
    identity, source = read_current_model(project)
    assert identity.base_model_id == "Qwen/Qwen3-0.6B"
    assert identity.adapter_id is None
    assert "configs/model.yaml" in source


def test_a_missing_config_is_reported_not_guessed(tmp_path):
    identity, source = read_current_model(tmp_path)
    assert identity.base_model_id == "unknown"
    assert "could not be read" in source


# ------------------------------------------------------------------ freshness


def _resolve(experiments, current=None):
    return resolve_freshness(list(experiments), current or CURRENT_SYSTEM)


def test_the_latest_eligible_run_is_current_and_earlier_ones_are_superseded():
    old = _experiment(experiment_id="old", path="p/old", completed_at="2026-01-01T00:00:00+00:00")
    new = _experiment(experiment_id="new", path="p/new", completed_at="2026-02-01T00:00:00+00:00")
    out = {e.experiment_id: e for e in _resolve([old, new])}
    assert (out["new"].status, out["new"].freshness_code) == (CURRENT, "current")
    assert (out["old"].status, out["old"].freshness_code) == (STALE, "superseded")
    assert "superseded by" in out["old"].status_reason


def test_a_different_model_is_historical_never_current():
    other = _experiment(model=ModelIdentity(base_model_id="some/other-model", revision=REV))
    out = _resolve([other])[0]
    assert (out.status, out.freshness_code) == (HISTORICAL, "model_mismatch")
    assert "not the configured model" in out.status_reason


def test_an_adapter_run_is_not_the_current_base_model():
    lora = _experiment(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision=REV, adapter_id="stage13_v1",
                                           checkpoint="checkpoint-90"))
    out = _resolve([lora])[0]
    assert (out.status, out.freshness_code) == (HISTORICAL, "model_mismatch")


def test_an_unrecorded_model_can_never_be_current():
    unknown = _experiment(model=ModelIdentity(base_model_id="unrecorded"),
                          completed_at="2099-01-01T00:00:00+00:00")
    out = _resolve([unknown])[0]
    assert out.status == HISTORICAL
    assert "do not record which weights" in out.status_reason


def test_a_retrieval_only_run_is_never_current():
    retrieval = _experiment(model=ModelIdentity(base_model_id="not_applicable"))
    out = _resolve([retrieval])[0]
    assert out.status == HISTORICAL
    assert "measures no model" in out.status_reason


def test_an_incomplete_newer_run_does_not_displace_a_complete_one():
    done = _experiment(experiment_id="done", completed_at="2026-01-01T00:00:00+00:00")
    partial = _experiment(experiment_id="partial", status=INCOMPLETE,
                          completed_at="2026-06-01T00:00:00+00:00")
    out = {e.experiment_id: e for e in _resolve([done, partial])}
    assert out["done"].status == CURRENT
    assert (out["partial"].status, out["partial"].freshness_code) == (INCOMPLETE, "run_incomplete")
    assert "did not finish" in out["partial"].status_reason


def test_runs_on_different_benchmarks_do_not_supersede_each_other():
    a = _experiment(experiment_id="a", benchmark=BenchmarkIdentity(benchmark_id="one", sha256="1" * 64))
    b = _experiment(experiment_id="b", benchmark=BenchmarkIdentity(benchmark_id="two", sha256="2" * 64),
                    completed_at="2026-09-01T00:00:00+00:00")
    out = {e.experiment_id: e for e in _resolve([a, b])}
    assert out["a"].status == CURRENT and out["b"].status == CURRENT


def test_a_training_run_is_never_current_or_stale():
    run = _experiment(kind="training", benchmark=None)
    out = _resolve([run])[0]
    assert out.status == COMPLETE
    assert "not the current model's answers" in out.status_reason


def test_a_failed_run_keeps_its_status_and_says_why():
    run = _experiment(kind="training", status=FAILED, benchmark=None)
    out = _resolve([run])[0]
    assert out.status == FAILED
    assert "failure stays visible" in out.status_reason


def test_a_different_base_revision_is_not_the_configured_model():
    """Replaces the old rule that an unpinned revision 'matches but is unproven':
    a revision is now resolved from the cache and must be equal."""
    run = _experiment(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision="abc123def456" + "0" * 28))
    out = _resolve([run])[0]
    assert (out.status, out.freshness_code) == (HISTORICAL, "model_mismatch")


def test_a_run_without_a_recorded_revision_is_not_current():
    run = _experiment(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B"))
    assert _resolve([run])[0].freshness_code == "model_revision_unrecorded"


def test_an_unresolved_current_system_makes_nothing_current():
    unresolved = CurrentSystem(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B"), pipeline_fingerprint=FP,
                               unresolved=("refs/main does not exist",))
    out = _resolve([_experiment()], unresolved)[0]
    assert (out.status, out.freshness_code) == (HISTORICAL, "current_system_unresolved")
    assert "refs/main" in out.status_reason


def test_a_pinned_model_key_no_longer_overrides_the_configuration(project):
    """Replaces the old pinned-model rule: the current system has one source,
    the configuration. A stored pin is reported and ignored."""
    registry = _registry(project)
    registry.set_pinned_model("some/other-model@default+base")
    payload = registry.current_model()
    assert payload["effective_model_key"] == registry.current_system.model.key
    assert "ignored" in payload["pinned_model_note"]


# ------------------------------------------------------------------ registry


def test_registry_writes_only_its_own_file(project):
    before = {p for p in project.rglob("*") if p.is_file()}
    registry = _registry(project)
    after = {p for p in project.rglob("*") if p.is_file()}
    created = after - before
    assert created == {project / "artifacts" / "dashboard" / "registry.json"}
    assert registry.store_path.is_file()
    payload = json.loads(registry.store_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1 and payload["experiments"]


def test_registry_never_modifies_an_artifact(project):
    stamps = {p: (p.stat().st_mtime_ns, p.stat().st_size)
              for p in project.rglob("*") if p.is_file() and "dashboard" not in p.parts}
    _registry(project).refresh()
    for path, stamp in stamps.items():
        assert (path.stat().st_mtime_ns, path.stat().st_size) == stamp, f"{path} was touched"


def test_names_and_pins_survive_a_rescan(project):
    registry = _registry(project)
    target = registry.experiments[0].experiment_id
    registry.rename(target, "my favourite run")
    registry.pin(target)
    assert registry.experiment(target).name == "my favourite run"
    reopened = _registry(project)
    assert reopened.experiment(target).name == "my favourite run"
    assert target in reopened.pinned


def test_current_model_payload_says_when_nothing_measures_it(project):
    registry = _registry(project)
    payload = registry.current_model()
    assert payload["effective_model_key"].startswith("Qwen/Qwen3-0.6B")
    if not payload["has_current_evaluation"]:
        assert "No evaluation of the current model exists" in payload["note"]
    else:
        assert payload["note"] is None and payload["current_evaluations"]


def test_diagnostics_reports_what_was_scanned(project):
    d = _registry(project).diagnostics()
    assert d["experiments"] == 4
    assert d["scanned_candidates"] >= 4
    assert len(d["unsupported"]) == 1
    assert d["by_kind"]["evaluation"] == 3 and d["by_kind"]["training"] == 1
    assert d["problems"], "every run reports at least one thing its artifacts do not record"


# ---------------------------------------------------------------- comparison


def _two_runs(project):
    registry = _registry(project)
    runs = [registry.evaluation(e.experiment_id) for e in registry.experiments if e.kind == KIND_EVALUATION]
    return registry, [r for r in runs if r is not None]


def test_comparing_a_run_with_itself_shows_no_change(project):
    _, runs = _two_runs(project)
    stage5 = next(r for r in runs if r.schema == "stage5/v1")
    result = compare(stage5, stage5)
    assert result["comparable"] is False, "an unrecorded model blocks attribution even against itself"
    assert any(b["code"] == "model_unrecorded" for b in result["blocking"])


def test_different_benchmarks_block_the_comparison(project):
    _, runs = _two_runs(project)
    answer = next(r for r in runs if r.schema == "legacy-answer/v1")
    retrieval = next(r for r in runs if r.schema == "legacy-retrieval/v1")
    result = compare(answer, retrieval)
    assert result["comparable"] is False
    codes = {b["code"] for b in result["blocking"]}
    assert {"benchmark_mismatch", "schema_mismatch", "no_model"} <= codes


def test_ratio_differences_are_percentage_points_not_percent_change(tmp_path):
    from regulus.dashboard.adapters import legacy

    a = legacy.load(_answer_file(tmp_path / "a", results=4, failed=2))
    b = legacy.load(_answer_file(tmp_path / "b", results=4, failed=1))
    result = compare(a, b)
    row = next(r for r in result["metrics"] if r["key"] == "completion_rate")
    assert row["delta"] == pytest.approx(0.25)
    assert row["delta_percentage_points"] == pytest.approx(25.0)
    assert row["change"] == "improved"


def test_direction_decides_improvement_not_the_sign(tmp_path):
    from regulus.dashboard.adapters import legacy

    a = legacy.load(_answer_file(tmp_path / "a", results=4, failed=0))
    b = legacy.load(_answer_file(tmp_path / "b", results=4, failed=2))
    result = compare(a, b)
    failed = next(r for r in result["metrics"] if r["key"] == "failed_count")
    assert failed["delta"] > 0
    assert failed["change"] == "regressed", "failed_count is lower_is_better, so a rise is a regression"


def test_a_metric_present_on_one_side_only_is_never_zero(tmp_path):
    from regulus.dashboard.adapters import legacy

    a = legacy.load(_answer_file(tmp_path / "a", manual=True))
    b = legacy.load(_answer_file(tmp_path / "b", manual=False))
    result = compare(a, b)
    row = next(r for r in result["metrics"] if r["key"] == "manual_score_mean")
    assert row["change"] == "incomparable"
    assert row["delta"] is None
    assert "only by the left run" in row["note"]


def test_comparison_names_no_winner(tmp_path):
    from regulus.dashboard.adapters import legacy

    a = legacy.load(_answer_file(tmp_path / "a"))
    b = legacy.load(_answer_file(tmp_path / "b"))
    result = compare(a, b)
    assert "No overall winner" in result["note"]
    assert "winner" not in {k.lower() for k in result}
    assert "score" not in {k.lower() for k in result}


def test_an_adapter_difference_is_a_warning_not_a_block(tmp_path):
    from regulus.dashboard.adapters import legacy

    a = legacy.load(_answer_file(tmp_path / "a"))
    b = legacy.load(_answer_file(tmp_path / "b", adapter={
        "adapter_name": "unit_v1", "best_checkpoint": "checkpoint-80",
        "base_model_name_or_path": "Qwen/Qwen3-0.6B"}))
    result = compare(a, b)
    assert result["comparable"] is True
    assert any(w["code"] == "adapter_differs" for w in result["warnings"])


# ------------------------------------------------------------------- the API


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """The real handler, on a real socket, against the real repository."""
    path = PROJECT / "scripts" / "serve_dashboard.py"
    spec = importlib.util.spec_from_file_location("serve_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STATE = module.State(PROJECT, store=tmp_path_factory.mktemp("dashboard_store") / "registry.json")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", module
    httpd.shutdown()
    httpd.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _status(base: str, path: str) -> int:
    try:
        with urllib.request.urlopen(base + path, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as err:
        return err.code


def test_api_serves_the_page_and_the_core_endpoints(server):
    base, _ = server
    with urllib.request.urlopen(base + "/", timeout=30) as response:
        assert response.status == 200
        assert "<title>Regulus AI — Model Analysis</title>".encode() in response.read()
    for path in ("/api/system/health", "/api/system/current-model", "/api/system/diagnostics",
                 "/api/metrics/definitions", "/api/experiments", "/api/evaluation/experiments",
                 "/api/training/runs", "/api/models"):
        status, payload = _get(base, path)
        assert status == 200 and payload, path


def test_api_declares_that_it_loads_no_model(server):
    base, module = server
    _, health = _get(base, "/api/system/health")
    assert health["loads_model"] is False
    assert health["connects_to_database"] is False
    # exactly one file, and in these tests it is a temporary one: the suite
    # must never rewrite the user's artifacts/dashboard/registry.json
    assert health["writes"] == [str(module.STATE.registry.store_path)]
    assert "artifacts" not in Path(health["writes"][0]).parts[-3:]


def test_api_returns_canonical_shapes_so_the_browser_parses_no_artifact(server):
    base, _ = server
    _, payload = _get(base, "/api/evaluation/experiments")
    experiment = payload["experiments"][0]
    assert {"experiment_id", "name", "kind", "status", "model", "benchmark", "metric_summary"} <= set(experiment)
    assert {"key", "label", "recorded"} <= set(experiment["model"])
    _, metrics = _get(base, f"/api/evaluation/experiments/{experiment['experiment_id']}/metrics")
    for metric in metrics["metrics"]:
        assert {"key", "display_name", "value", "unit", "direction", "status", "source"} <= set(metric)


def test_api_question_endpoints_keep_raw_and_final_apart(server):
    base, _ = server
    _, payload = _get(base, "/api/evaluation/experiments")
    stage5 = next(e for e in payload["experiments"] if e["path"].endswith("stage5_baseline_20260923/stage5"))
    _, questions = _get(base, f"/api/evaluation/experiments/{stage5['experiment_id']}/questions")
    repaired = next(q for q in questions["questions"] if q["repair"])
    _, one = _get(base, f"/api/evaluation/experiments/{stage5['experiment_id']}/questions/{repaired['id']}")
    question = one["question"]
    assert question["answer_raw"] and question["answer_final"]
    assert question["validation_raw"]["status"] != question["validation_final"]["status"]


def test_api_reports_missing_things_as_404_and_bad_input_as_400(server):
    base, _ = server
    assert _status(base, "/api/nope") == 404
    assert _status(base, "/api/evaluation/experiments/deadbeefdeadbeef") == 404
    assert _status(base, "/api/training/runs/deadbeefdeadbeef") == 404
    assert _status(base, "/api/evaluation/compare?ids=only-one") == 400


def test_api_metric_definitions_cover_every_metric_served(server):
    base, _ = server
    _, definitions = _get(base, "/api/metrics/definitions")
    known = set(definitions["by_key"])
    _, experiments = _get(base, "/api/experiments")
    for experiment in experiments["experiments"]:
        for key in experiment["metric_summary"]:
            assert key in known, key
    assert definitions["count"] == len(known)
    assert all(d["direction"] in ("higher_is_better", "lower_is_better", "informational")
               for d in definitions["by_key"].values())


def test_api_refresh_rescans(server):
    base, module = server
    request = urllib.request.Request(base + "/api/refresh", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["refreshed"] is True
    assert payload["diagnostics"]["experiments"] > 0
