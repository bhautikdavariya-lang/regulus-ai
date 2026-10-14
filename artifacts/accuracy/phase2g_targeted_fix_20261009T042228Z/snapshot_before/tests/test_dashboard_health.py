"""Tests for the model health view.

This page answers "how good is the model we are running right now?", and the
way it can fail is by answering a different question without saying so. So
most of these tests are isolation tests: a historical run's numbers must
never reach a current-model card, a metric this evaluation did not measure
must say so rather than borrow, and a history line must contain exactly one
set of weights on exactly one benchmark.
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

from regulus.dashboard import metrics as M
from regulus.dashboard.adapters import legacy, stage5
from regulus.dashboard.health import (
    SECTION_OF,
    SECTIONS,
    STATE_AVAILABLE,
    STATE_GOOD,
    STATE_INFORMATIONAL,
    STATE_MISSING,
    STATE_POOR,
    build_attention,
    build_failure_breakdown,
    build_sections,
    current_health,
    current_history,
    metric_state,
)
from regulus.dashboard.registry import Registry, Root
from regulus.dashboard.schemas import CURRENT, HISTORICAL, INCONSISTENT, MISSING, MetricResult

from regulus.dashboard.registry import read_current_system

from .current_system_fixtures import REVISION, model_block_for, stage5_run, write_project
from .test_dashboard_adapters import _answer_file, _retrieval_file, _training_run
from .test_dashboard_stage5_adapter import _make_run as _stage5_run

PROJECT = Path.cwd()
REAL_STAGE5 = Path("artifacts/stage5_stage6/stage5_baseline_20260923/stage5")

ROOTS = (
    Root("artifacts", "*/*/*", False, "stage 5 runs"),
    Root("models/qwen3-0.6b-lora", "*", False, "training runs"),
    Root("data/evaluation/results", "**/*.json", True, "legacy results"),
)


# ------------------------------------------------------------------ fixtures


def _project(tmp_path: Path, name: str = "proj") -> Path:
    root = tmp_path / name
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "model.yaml").write_text(
        'model:\n  id: "Qwen/Qwen3-0.6B"\n  device: "auto"\n  dtype: "auto"\n', encoding="utf-8")
    (root / "data" / "evaluation" / "results").mkdir(parents=True)
    return root


def _results(root: Path) -> Path:
    return root / "data" / "evaluation" / "results"


def _rename(path: Path, new_stem: str) -> Path:
    target = path.with_name(f"{new_stem}.json")
    path.rename(target)
    return target


def _set(path: Path, **run_fields) -> Path:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run"].update(run_fields)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def evaluated(tmp_path: Path) -> Registry:
    """A project whose configured system has a current evaluation: a Stage 5
    run that recorded the configured weights and pipeline, on its whole
    benchmark. (A legacy run can no longer be current: it records no
    pipeline fingerprint.)"""
    root = write_project(tmp_path / "proj")
    stage5_run(root, "current_run")
    return Registry(root, roots=ROOTS)


@pytest.fixture
def unevaluated(tmp_path: Path) -> Registry:
    """A project where nothing measured the configured model."""
    root = _project(tmp_path)
    # a run of a different model, and a Stage 5 run whose model is unrecorded
    _set(_rename(_answer_file(_results(root)), "other_model"),
         pipeline="other-model", model_id="some/other-model",
         timestamp_utc="2026-04-01T00:00:00+00:00")
    (root / "artifacts" / "group").mkdir(parents=True)
    _stage5_run(root / "artifacts" / "group")
    return Registry(root, roots=ROOTS)


def _health(registry: Registry) -> dict:
    return current_health(registry, registry.thresholds)


# --------------------------------------------------- the evaluated headline


def test_the_page_is_about_the_configured_model(evaluated):
    h = _health(evaluated)
    assert (h["state"], h["status"], h["reason"]) == ("evaluated", "evaluated", "current_evaluation")
    assert h["evaluation"]["status"] == CURRENT and h["evaluation"]["freshness_code"] == "current"
    assert h["model"]["base_model"] == "Qwen/Qwen3-0.6B"
    assert h["model"]["adapter"] is None
    assert h["benchmark"]["name"] == "unit_bench"
    assert h["evaluation"]["questions_evaluated"] == 3
    assert h["evaluation"]["pipeline_fingerprint"]["value"] == h["current_system"]["pipeline_fingerprint"]["value"]


def test_identity_is_plain_and_paths_are_secondary(evaluated):
    h = _health(evaluated)
    # what a manager reads
    assert set(h["model"]) >= {"label", "base_model", "adapter", "checkpoint", "revision"}
    # what an engineer reads, kept apart
    technical = h["model"]["technical"]
    assert set(technical) >= {"model_key", "artifact_path", "experiment_id", "source_artifacts"}
    assert "artifact_path" not in h["model"]
    assert "sha256" not in h["benchmark"] and "sha256" in h["benchmark"]["technical"]


def test_no_composite_score_is_produced(evaluated):
    payload = json.dumps(_health(evaluated)).lower()
    for forbidden in ("ai score", "overall score", "composite score", "model_quality", "grade"):
        assert forbidden not in payload


# --------------------------------------------------- current-model isolation


def test_a_historical_run_never_supplies_a_current_metric(tmp_path):
    """A historical run with metrics the current one lacks must not fill them in."""
    root = write_project(tmp_path / "proj")
    stage5_run(root, "current_run")
    # a legacy run of the same base model: completion rate, prompt tokens and a
    # human score, none of which the Stage 5 run measures. No fingerprint, so
    # it is HISTORICAL however its model name reads.
    _set(_rename(_answer_file(_results(root)), "legacy_run"), pipeline="legacy-run",
         timestamp_utc="2026-12-01T00:00:00+00:00", model_revision=REVISION)
    registry = Registry(root, roots=ROOTS)

    statuses = {e.status for e in registry.experiments if e.kind == "evaluation"}
    assert CURRENT in statuses and HISTORICAL in statuses

    h = _health(registry)
    shown = {m["key"] for s in h["sections"] for m in s["metrics"]}
    current_run = registry.evaluation(h["evaluation"]["experiment_id"])
    assert shown == {m.key for m in current_run.metrics}
    for legacy_only in ("completion_rate", "avg_prompt_tokens", "manual_score_mean"):
        assert legacy_only not in shown
        assert any(n["key"] == legacy_only for s in h["sections"] for n in s["not_measured"])


def test_an_unmeasured_metric_says_so_and_carries_no_value(evaluated):
    h = _health(evaluated)
    stubs = [n for s in h["sections"] for n in s["not_measured"]]
    assert stubs
    for stub in stubs:
        assert stub["value"] is None and stub["numerator"] is None
        assert stub["status"] == "missing" and stub["measured"] is False
        assert stub["display"] == "Not measured"
        assert stub["reason"] == "not measured by this evaluation"


def test_a_metric_the_run_could_not_derive_is_null_not_zero(evaluated):
    """Test N: a metric present in the run but not measurable (run duration of
    a run with no start time here) is value None, status missing, never 0."""
    h = _health(evaluated)
    metrics = {m["key"]: m for s in h["sections"] for m in s["metrics"]}
    missing = [m for m in metrics.values() if m["status"] == "missing"]
    for m in missing:
        assert m["value"] is None and m["measured"] is False and m["display"] == "Not measured"
    for m in metrics.values():
        if m["value"] == 0:
            assert m["status"] != "missing" and m["measured"] is True


def test_the_page_states_how_much_it_could_not_measure(evaluated):
    h = _health(evaluated)
    coverage = h["coverage"]
    assert coverage["defined"] == len(M.all_definitions())
    assert 0 < coverage["available"] < coverage["defined"]
    absent = {f["key"] for f in coverage["families_absent"]}
    # the fixture's Stage 5 run has no correctness file and no retrieval ranking
    assert {"correctness", "retrieval", "human"} <= absent
    assert "training" not in absent, "training is excluded from health, not reported as missing"


# ------------------------------------------------------- the unevaluated state


def test_with_no_current_evaluation_the_page_says_so(unevaluated):
    h = _health(unevaluated)
    assert h["state"] == "not_evaluated"
    assert (h["status"], h["evaluation"], h["benchmarks"]) == ("not_evaluated", None, [])
    assert h["reason"] in ("no_current_evaluation", "current_system_unresolved")
    assert h["headline"] == "This model has not been evaluated"
    assert h["sections"] == [] and h["attention"] is None
    assert "different weights" in h["explanation"]


def test_the_unevaluated_state_offers_the_latest_run_without_its_numbers(unevaluated):
    h = _health(unevaluated)
    latest = h["latest_available"]
    assert latest is not None
    assert latest["status"] in (HISTORICAL, "STALE", "INCOMPLETE", "FAILED")
    assert "metric_summary" not in latest and "metrics" not in latest
    assert "not the current model's results" in latest["warning"]


def test_the_unevaluated_state_still_names_the_configured_model(unevaluated):
    h = _health(unevaluated)
    assert h["configured_model"]["base_model_id"] == "Qwen/Qwen3-0.6B"
    assert h["effective_model_key"].startswith("Qwen/Qwen3-0.6B")


# --------------------------------------------------------------- grouping


def test_every_defined_metric_has_exactly_one_section():
    for d in M.all_definitions():
        if d.family == M.TRAINING:
            assert d.key not in SECTION_OF, f"{d.key}: training is not a health metric"
            continue
        assert d.key in SECTION_OF, f"{d.key} belongs to no section"
    assigned = list(SECTION_OF.values())
    assert set(assigned) <= {s.key for s in SECTIONS}


def test_metrics_land_in_the_section_a_reader_would_expect():
    expected = {
        "correctness_raw": "answer_quality", "correctness_final": "answer_quality",
        "refusal_correct": "answer_quality", "faithfulness_raw": "answer_quality",
        "hallucination_raw": "answer_quality", "hallucination_final": "answer_quality",
        "retrieval_ok": "retrieval", "recall_at_1": "retrieval", "mrr": "retrieval",
        "citation_ok": "retrieval", "exact_source_citation": "retrieval",
        "valid_raw": "validation_repair", "valid_final": "validation_repair",
        "repair_rate": "validation_repair", "repair_success": "validation_repair",
        "correct_only_after_repair": "validation_repair",
        "e2e_latency_p50": "performance", "generation_latency_p95": "performance",
        "avg_generated_tokens": "performance", "completion_rate": "performance",
        "failed_count": "performance", "questions_evaluated": "composition",
        "manual_score_mean": "human",
    }
    for key, section in expected.items():
        assert SECTION_OF[key] == section, f"{key} is in {SECTION_OF[key]}, expected {section}"


def test_retrieval_is_never_mixed_into_answer_quality():
    retrieval = {k for k, s in SECTION_OF.items() if s == "retrieval"}
    quality = {k for k, s in SECTION_OF.items() if s == "answer_quality"}
    assert not retrieval & quality
    assert {"recall_at_1", "mrr", "retrieval_ok"} <= retrieval
    assert not any(M.definition(k).family in (M.EVIDENCE, M.RETRIEVAL) for k in quality)


def test_no_metric_the_run_reports_is_dropped(evaluated):
    h = _health(evaluated)
    run = evaluated.evaluation(h["evaluation"]["experiment_id"])
    shown = {m["key"] for s in h["sections"] for m in s["metrics"]}
    expected = {m.key for m in run.metrics if M.definition(m.key).family != M.TRAINING}
    assert shown == expected


def test_sections_carry_plain_english_for_a_non_specialist():
    for section in SECTIONS:
        assert section.question.endswith("?")
        assert len(section.explanation) > 60
        for jargon in ("LoRA", "checkpoint", "adapter", "sha256", "artifact"):
            assert jargon not in section.explanation, f"{section.key} leaks jargon: {jargon}"


# ------------------------------------------------- numerators and denominators


def test_proportions_keep_their_counts(evaluated):
    h = _health(evaluated)
    for section in h["sections"]:
        for m in section["metrics"]:
            if m["unit"] == "ratio" and m["numerator"] is not None:
                assert m["denominator"]
                assert m["sample_note"] == f"{m['numerator']} / {m['denominator']}"


def test_a_ratio_without_counts_is_still_shown_but_without_a_fake_sample(evaluated):
    h = _health(evaluated)
    for section in h["sections"]:
        for m in section["metrics"]:
            if m["numerator"] is None:
                assert m["sample_note"] is None


# ---------------------------------------------------------------- states


def test_without_a_configured_threshold_no_metric_is_called_good():
    metric = MetricResult(key="correctness_final", display_name="x", value=0.706,
                          direction=M.HIGHER_IS_BETTER)
    state = metric_state(metric, {})
    assert state["state"] == STATE_AVAILABLE
    assert "no quality threshold is configured" in state["reason"]


def test_informational_metrics_are_not_judged():
    metric = MetricResult(key="questions_evaluated", display_name="x", value=51.0,
                          unit=M.COUNT, direction=M.INFORMATIONAL)
    assert metric_state(metric, {})["state"] == STATE_INFORMATIONAL


def test_a_configured_threshold_is_applied_and_explained():
    metric = MetricResult(key="correctness_final", display_name="x", value=0.95,
                          direction=M.HIGHER_IS_BETTER)
    thresholds = {"correctness_final": {"good": 0.9, "attention": 0.75}}
    assert metric_state(metric, thresholds)["state"] == STATE_GOOD
    poor = MetricResult(key="correctness_final", display_name="x", value=0.5,
                        direction=M.HIGHER_IS_BETTER)
    assert metric_state(poor, thresholds)["state"] == STATE_POOR


def test_a_lower_is_better_threshold_is_not_inverted():
    thresholds = {"hallucination_raw": {"good": 0.05, "attention": 0.2}}
    good = MetricResult(key="hallucination_raw", display_name="x", value=0.01,
                        direction=M.LOWER_IS_BETTER)
    bad = MetricResult(key="hallucination_raw", display_name="x", value=0.5,
                       direction=M.LOWER_IS_BETTER)
    assert metric_state(good, thresholds)["state"] == STATE_GOOD
    assert metric_state(bad, thresholds)["state"] == STATE_POOR


def test_missing_and_inconsistent_states_are_distinct():
    absent = MetricResult(key="correctness_final", display_name="x", value=None, status=MISSING)
    assert metric_state(absent, {})["state"] == STATE_MISSING
    odd = MetricResult(key="correctness_final", display_name="x", value=0.7,
                       status=INCONSISTENT, note="stored disagrees")
    assert metric_state(odd, {})["state"] == "inconsistent"


def test_thresholds_are_off_by_default_and_configurable(evaluated):
    assert evaluated.thresholds == {}
    assert _health(evaluated)["thresholds_configured"] is False
    evaluated.set_threshold("valid_final", good=0.99, attention=0.9)
    assert evaluated.thresholds["valid_final"] == {"good": 0.99, "attention": 0.9}
    h = current_health(evaluated, evaluated.thresholds)
    assert h["thresholds_configured"] is True
    rate = next(m for s in h["sections"] for m in s["metrics"] if m["key"] == "valid_final")
    assert rate["state"]["state"] == STATE_GOOD


# --------------------------------------------------------------- attention


@pytest.mark.skipif(not REAL_STAGE5.is_dir(), reason="the Stage 5 baseline is not present")
def test_attention_counts_match_the_question_records():
    run = stage5.load(REAL_STAGE5, root=PROJECT)
    attention = build_attention(run)
    by_code = {i["code"]: i for i in attention["items"]}

    expected = {
        "failed_final": sum(1 for q in run.questions if q.correct_final is False),
        "failed_raw": sum(1 for q in run.questions if q.correct_raw is False),
        "repaired": sum(1 for q in run.questions if q.repair),
        "only_repair": sum(1 for q in run.questions if q.correct_raw is False and q.correct_final is True),
        "truncated": sum(1 for q in run.questions if q.truncated is True),
        "hallucination": sum(1 for q in run.questions if q.hallucination_raw is True),
    }
    for code, count in expected.items():
        if count:
            assert by_code[code]["count"] == count, code
            assert len(by_code[code]["question_ids"]) == min(count, 50)
        else:
            assert code not in by_code

    # and they agree with the aggregates the evaluator itself wrote
    assert by_code["only_repair"]["count"] == len(run.failure_summary["correct_only_after_repair"])
    assert by_code["repaired"]["count"] == run.metric("repair_rate").numerator


@pytest.mark.skipif(not REAL_STAGE5.is_dir(), reason="the Stage 5 baseline is not present")
def test_every_attention_item_can_be_opened_in_the_questions_view():
    from regulus.dashboard.observatory import question_list

    run = stage5.load(REAL_STAGE5, root=PROJECT)
    sections = {s.key for s in SECTIONS}
    for item in build_attention(run)["items"]:
        if item["code"] == "inconsistent_metric":
            continue
        assert item["filter"], item["code"]
        assert item["severity"] in ("serious", "warning", "info")
        assert item["section"] in sections, item["code"]
        assert item["denominator"] == len(run.questions)
        # the link opens exactly the questions the count was made of
        opened = [q["id"] for q in question_list(run, filter_key=item["filter"])["questions"]]
        assert len(opened) == item["count"], item["code"]
        assert opened[:50] == item["question_ids"], item["code"]


def test_a_run_that_measures_no_quality_says_there_is_nothing_to_flag(tmp_path):
    # A legacy answer run records completion only. It can no longer be current,
    # so the attention builder is exercised on the run directly.
    run = legacy.load(_answer_file(_results(_project(tmp_path))))
    attention = build_attention(run)
    assert attention["measurable"] is False
    assert attention["items"] == []
    assert "not whether the answer was correct" in attention["note"]


def test_an_inconsistent_metric_is_raised_for_attention(tmp_path):
    root = write_project(tmp_path / "proj")
    # the stored aggregate disagrees with the per-question records
    stage5_run(root, "current_run", aggregates={"retrieval_results.json": {"retrieval_ok": 0.1}})
    h = _health(Registry(root, roots=ROOTS))
    assert h["state"] == "evaluated"
    assert any(i["code"] == "inconsistent_metric" for i in h["attention"]["items"])


@pytest.mark.skipif(not REAL_STAGE5.is_dir(), reason="the Stage 5 baseline is not present")
def test_the_failure_breakdown_uses_the_evaluator_s_own_attribution():
    run = stage5.load(REAL_STAGE5, root=PROJECT)
    breakdown = build_failure_breakdown(run)
    assert breakdown["available"]
    assert breakdown["total"] == len(run.questions)
    assert sum(l["count"] for l in breakdown["layers"]) == breakdown["total"]
    assert breakdown["layers"] == sorted(breakdown["layers"], key=lambda l: -l["count"])
    assert {l["layer"] for l in breakdown["layers"]} == set(run.failure_summary["by_layer"])


def test_a_run_without_layer_attribution_says_so(evaluated):
    breakdown = _health(evaluated)["failure_breakdown"]
    assert breakdown["available"] is False
    assert "does not attribute failures" in breakdown["reason"]
    assert breakdown["layers"] == []


# ----------------------------------------------------------------- history


def _lora_block(root: Path, checkpoint: str) -> dict:
    return {**model_block_for(root), "adapter_name": "unit_v1", "checkpoint": checkpoint,
            "adapter_dir": "models/qwen3-0.6b-lora/unit_v1/adapter"}


def test_history_contains_only_the_current_model_on_one_benchmark(tmp_path):
    root = write_project(tmp_path / "proj")
    stage5_run(root, "run_a", completed_at="2026-01-01T00:00:00+00:00")
    stage5_run(root, "run_b", completed_at="2026-02-01T00:00:00+00:00")
    # same benchmark, different weights: a change, not a later point
    stage5_run(root, "run_lora", completed_at="2026-02-15T00:00:00+00:00", model=_lora_block(root, "checkpoint-80"))
    # same weights and benchmark, different pipeline: not on the line either
    other_pipeline = json.loads(json.dumps(read_current_system(root).evaluation_config))
    other_pipeline["generation_budget"]["min_tokens"] = 448
    stage5_run(root, "run_other_pipeline", completed_at="2026-02-20T00:00:00+00:00", evaluation_config=other_pipeline)
    # different benchmark content: neither anchors this line nor joins it
    stage5_run(root, "run_other_bench", completed_at="2026-01-15T00:00:00+00:00", bench_name="other_bench",
               ids=("T-1", "T-2"))

    history = current_history(Registry(root, roots=ROOTS))
    assert history["available"]
    names = [p["name"] for p in history["points"]]
    assert names == ["run_a", "run_b"], names
    assert history["points"][-1]["is_current"] is True
    assert "run_lora" in [c["name"] for c in history["model_changes"]]


def test_history_series_are_ordered_and_carry_their_definitions(tmp_path):
    root = write_project(tmp_path / "proj")
    for i, stamp in enumerate(("2026-01-01", "2026-02-01", "2026-03-01")):
        stage5_run(root, f"run_{i}", completed_at=f"{stamp}T00:00:00+00:00")
    history = current_history(Registry(root, roots=ROOTS))
    stamps = [p["completed_at"] for p in history["points"]]
    assert stamps == sorted(stamps)
    assert history["series"], "at least one metric is comparable across the runs"
    for series in history["series"]:
        definition = M.definition(series["key"])
        assert series["display_name"] == definition.name
        assert series["unit"] == definition.unit and series["direction"] == definition.direction
        assert len(series["points"]) == len(history["points"])


def test_history_is_empty_when_the_model_has_no_evaluation(unevaluated):
    history = current_history(unevaluated)
    assert history["available"] is False
    assert history["points"] == [] and history["series"] == []
    assert "no evaluation" in history["reason"]


def test_a_different_checkpoint_is_not_a_later_point(tmp_path):
    """Two checkpoints of the same adapter are two models, not one history."""
    root = write_project(tmp_path / "proj")
    stage5_run(root, "base_run", completed_at="2026-01-01T00:00:00+00:00")
    for checkpoint in ("checkpoint-40", "checkpoint-80"):
        stage5_run(root, f"run_{checkpoint}", completed_at="2026-02-01T00:00:00+00:00",
                   model=_lora_block(root, checkpoint))
    history = current_history(Registry(root, roots=ROOTS))
    assert [p["name"] for p in history["points"]] == ["base_run"]
    assert len(history["model_changes"]) == 2
    assert len({c["model_key"] for c in history["model_changes"]}) == 2


# --------------------------------------------------------------------- API


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    path = PROJECT / "scripts" / "serve_dashboard.py"
    spec = importlib.util.spec_from_file_location("serve_dashboard_health", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STATE = module.State(PROJECT, store=tmp_path_factory.mktemp("dashboard_store") / "registry.json")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def test_the_health_endpoints_serve_canonical_data(server):
    payload = _get(server, "/api/model-health/current")
    assert payload["state"] in ("evaluated", "not_evaluated")
    if payload["state"] == "evaluated":
        assert {"model", "evaluation", "benchmark", "sections", "attention", "coverage"} <= set(payload)
        for section in payload["sections"]:
            assert {"key", "title", "question", "explanation", "metrics", "not_measured"} <= set(section)
            for metric in section["metrics"]:
                assert {"key", "display_name", "value", "unit", "direction", "state", "source"} <= set(metric)
                assert M.has_definition(metric["key"])


def test_the_history_endpoint_serves_canonical_data(server):
    payload = _get(server, "/api/model-health/current/history")
    assert "available" in payload
    if payload["available"]:
        for series in payload["series"]:
            assert M.has_definition(series["key"])
            assert series["points"]


def test_the_health_slices_agree_with_the_composite(server):
    whole = _get(server, "/api/model-health/current")
    metrics = _get(server, "/api/model-health/current/metrics")
    failures = _get(server, "/api/model-health/current/failures")
    assert metrics["sections"] == whole["sections"]
    assert failures["attention"] == whole["attention"]
    assert failures["failure_breakdown"] == whole["failure_breakdown"]


def test_the_real_dashboard_reports_the_current_model_honestly(server):
    """Against this repository: the current model's evaluation is thin, and the
    page must say so instead of borrowing the Stage 5 numbers."""
    payload = _get(server, "/api/model-health/current")
    if payload["state"] != "evaluated":
        pytest.skip("no current evaluation in this repository")
    shown = {m["key"] for s in payload["sections"] for m in s["metrics"]}
    registry_metrics = {m["key"] for m in _get(
        server, f"/api/evaluation/experiments/{payload['evaluation']['experiment_id']}/metrics")["metrics"]}
    assert shown == registry_metrics
    assert payload["coverage"]["available"] == len(shown)


def test_a_second_current_evaluation_on_another_benchmark_is_disclosed(tmp_path):
    """Freshness is resolved per benchmark, so a model can hold more than one
    current evaluation. The page leads with the newest and must say the other
    exists rather than let it look like the only measurement."""
    root = write_project(tmp_path / "proj")
    stage5_run(root, "on_unit", completed_at="2026-01-01T00:00:00+00:00")
    stage5_run(root, "on_other", completed_at="2026-02-01T00:00:00+00:00", bench_name="other_v1", ids=("T-1", "T-2"))

    h = _health(Registry(root, roots=ROOTS))
    assert h["evaluation"]["name"] == "on_other", "the newest leads"
    assert [o["name"] for o in h["other_current_evaluations"]] == ["on_unit"]
    assert "different measurement" in h["other_current_note"]
    # and its metrics are not merged in
    assert h["benchmark"]["name"] == "other_v1"
    # every benchmark gets its own block, with only its own numbers
    blocks = {b["benchmark"]["name"]: b for b in h["benchmarks"]}
    assert set(blocks) == {"other_v1", "unit_bench"}
    assert blocks["other_v1"]["evaluation"]["questions_evaluated"] == 2
    assert blocks["unit_bench"]["evaluation"]["questions_evaluated"] == 3


def test_a_single_benchmark_run_discloses_nothing_extra(evaluated):
    h = _health(evaluated)
    assert h["other_current_evaluations"] == []
    assert h["other_current_note"] is None
