"""The acceptance evaluation on the dashboard: provenance, and what it refuses to claim.

The 300-question acceptance test is the only controlled, hand-scored measure of
this system's answers. Before this adapter existed it was invisible to the
dashboard: the registry's `artifacts/*/*/*` root is three levels deep and a run
directory sits two levels down, so only its `scoring/` subdirectory was ever
offered to an adapter and none claimed it. The Overview said "this model has not
been evaluated" while a 300-row hand-scored result sat on disk.

These tests pin the things that would make the dashboard lie:

* that the run it shows is chosen by SUBSTANCE and not by being the newest file;
* that a run which is not the configured system's cannot be presented as current;
* that every displayed number names the artifact, run, model, rubric and
  configuration it came from;
* that absence of a result is reported as absence rather than as a number;
* that the live per-answer indicator and this benchmark never mix.

The synthetic runs below are written to a temporary project root, so none of
these tests reads or depends on the real artifacts; the two that do assert
against the repository's own runs say so in their names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.config import PROJECT_ROOT
from regulus.dashboard import acceptance_view as AV
from regulus.dashboard.adapters import acceptance
from regulus.dashboard.fingerprint import config_differences
from regulus.dashboard.health import current_health
from regulus.dashboard.metrics import REGISTRY, definition
from regulus.dashboard.registry import Registry
from regulus.dashboard.schemas import COMPLETE, CURRENT, INCOMPLETE, STALE

BENCHMARK_SHA = "c" * 64
QUESTIONS = 6

# A pipeline_config of the shape run_acceptance_test.py records, complete enough
# that a fingerprint derives from it.
PIPELINE = {
    "retrieval": {"retriever": "LexicalRetriever", "top_k": 8, "corpus": "all", "min_trigram_similarity": 0.4,
                  "exclude_contextual_only": True, "semantic_fallback": "on"},
    "coverage": {"no_context_behavior": "refuse", "incomplete_behavior": "partial", "answerability": "gate",
                 "optional_context": "incomplete_only", "scope_policy": "general_knowledge",
                 "evidence_consolidation": "on"},
    "context": {"max_results": 8, "max_chars_per_result": 1200, "max_total_chars": 3600, "hard_max_results": 24,
                "hard_max_total_chars": 9000, "required_max_chars_per_result": 4000},
    "generation_budget": {"policy": "adaptive", "base_tokens": 96, "per_unit_tokens": 160, "range_bonus_tokens": 64,
                          "general_tokens": 384, "max_units": 10, "min_tokens": 256, "evidence_multiple": 1.4,
                          "evidence_cap_fraction": 0.75, "hard_max_tokens": 2048},
    "validation": {"validation_behavior": "repair"},
    "repair": {"mode": "post_hoc_deterministic"},
    "prompt": {"system_prompt_sha256": "p" * 64, "answer_shape": "adaptive"},
}
DECODING = {"max_new_tokens": 2048, "do_sample": False, "temperature": None, "top_p": None, "top_k": None,
            "enable_thinking": False, "repetition_penalty": 1, "no_repeat_ngram_size": 0}


def write_run(parent: Path, label: str, *, finished: str, scored: int, answers: int = QUESTIONS,
              passes: int = 1, adapter: str | None = None, key_locked: bool = False,
              validation: str = "repair", basis: str = "manual_rubric_read") -> Path:
    """One synthetic acceptance run directory."""
    run = parent / label
    (run / "scoring").mkdir(parents=True)
    pipeline = {**PIPELINE, "validation": {"validation_behavior": validation}}
    (run / "run_metadata.json").write_text(json.dumps({
        "started_utc": finished, "finished_utc": finished,
        "benchmark": {"file": "bench.xlsx", "benchmark_key": f"synthetic_bench@{BENCHMARK_SHA[:12]}",
                      "version": "Rev 02", "questions": QUESTIONS, "sha256_before": BENCHMARK_SHA,
                      "sha256_after": BENCHMARK_SHA, "unchanged": True,
                      "key_verification": {"verified_rows": QUESTIONS if key_locked else 0,
                                           "total_rows": QUESTIONS, "key_is_locked": key_locked,
                                           "status": "locked" if key_locked else "WARNING - key not fully verified"}},
        "active_model": {"model_id": "Qwen/Qwen3-0.6B", "adapter": adapter, "backend": "transformers"},
        "reproducibility": {"model_id": "Qwen/Qwen3-0.6B", "model_revision": "r" * 40, "weights_sha256": "w" * 64,
                            "device": "cpu", "dtype": "float32", "decoding": DECODING,
                            "system_prompt_sha256": "p" * 64, "pipeline_config": pipeline,
                            "git_commit": "g" * 40, "git_dirty": False},
        "protocol": "column F verbatim", "command": "python scripts/run_acceptance_test.py",
    }), encoding="utf-8")
    with (run / "answers.jsonl").open("w", encoding="utf-8") as handle:
        for i in range(answers):
            handle.write(json.dumps({"question_id": f"Q-{i:03d}", "question": f"q{i}", "answer": f"a{i}",
                                     "model_called": True, "seconds": 1.0, "generated_tokens": 10,
                                     "execution_status": "OK"}) + "\n")
    with (run / "scoring" / "verdicts_01.jsonl").open("w", encoding="utf-8") as handle:
        for i in range(scored):
            good = i < passes
            handle.write(json.dumps({
                "id": f"Q-{i:03d}", "result": "PASS" if good else "FAIL", "scoring_basis": basis,
                "L": 1 if good else 0, "M": 0, "N": 2 if good else 0, "O": 1 if good else 0, "P": 1,
                "Q": None, "notes": "n",
            }) + "\n")
    return run


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "model.yaml").write_text(
        'model:\n  id: "Qwen/Qwen3-0.6B"\n  device: "auto"\n  dtype: "auto"\n', encoding="utf-8")
    (root / "artifacts" / "acceptance_test").mkdir(parents=True)
    return root


def registry_for(root: Path) -> Registry:
    registry = Registry(root, store=root / "artifacts" / "dashboard" / "registry.json")
    registry.refresh()
    return registry


# ------------------------------------------------------- 1. the correct source


def test_the_acceptance_run_is_discovered_at_all(project: Path):
    """The regression this adapter exists for: a run two levels under artifacts/."""
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS)
    registry = registry_for(project)
    names = [e.name for e in registry.experiments]
    assert "acc_20260101T000000Z" in names
    run = registry.evaluation(next(e.experiment_id for e in registry.experiments if e.name in names))
    assert run.schema == acceptance.SCHEMA


def test_the_selected_run_is_the_fully_scored_one_not_the_newest(project: Path):
    """§3: do NOT assume the latest file is the correct file.

    The newer run is scored on 2 of 6 rows. It must lose to the older run that
    covers the benchmark, and the reason must be its coverage, not its age.
    """
    parent = project / "artifacts" / "acceptance_test"
    write_run(parent, "acc_old_20260101T000000Z", finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, passes=2)
    write_run(parent, "acc_new_20260601T000000Z", finished="2026-06-01T00:00:00+00:00", scored=2, passes=2)
    registry = registry_for(project)
    payload = AV.payload(registry)
    assert payload["available"] is True
    assert payload["provenance"]["run_id"] == "acc_old_20260101T000000Z"
    rejected = {r["run"]: r for r in payload["rejected"]}
    assert rejected["acc_new_20260601T000000Z"]["rejected_because"] == AV.WHOLE_BENCHMARK
    assert "2 of 6" in rejected["acc_new_20260601T000000Z"]["detail"]


def test_recency_decides_only_among_runs_that_cover_the_benchmark(project: Path):
    parent = project / "artifacts" / "acceptance_test"
    write_run(parent, "acc_old_20260101T000000Z", finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS)
    write_run(parent, "acc_new_20260601T000000Z", finished="2026-06-01T00:00:00+00:00", scored=QUESTIONS, passes=3)
    payload = AV.payload(registry_for(project))
    assert payload["provenance"]["run_id"] == "acc_new_20260601T000000Z"
    assert payload["headline"]["numerator"] == 3
    assert next(r for r in payload["rejected"] if r["run"] == "acc_old_20260101T000000Z")["rejected_because"] \
        == "superseded_by_a_later_fully_scored_run"


def test_an_adapter_run_with_no_checkpoint_cannot_be_the_result(project: Path):
    """An adapter names a family of weights, not a set of them: every checkpoint is
    different weights, so a run that does not say which one it loaded has not
    recorded what it evaluated and can never be the benchmark result -- not even
    by being the newest."""
    parent = project / "artifacts" / "acceptance_test"
    write_run(parent, "acc_base_20260101T000000Z", finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS)
    write_run(parent, "acc_lora_20260601T000000Z", finished="2026-06-01T00:00:00+00:00", scored=QUESTIONS,
              adapter="models/qwen3-0.6b-lora/someadapter/adapter")
    payload = AV.payload(registry_for(project))
    assert payload["provenance"]["run_id"] == "acc_base_20260101T000000Z"
    assert next(r for r in payload["rejected"] if r["run"] == "acc_lora_20260601T000000Z")["rejected_because"] \
        == AV.MODEL_UNRECORDED


def test_the_configured_model_is_preferred_over_a_newer_run_of_other_weights(project: Path):
    """select() directly, with a constructed current system, so the model filter is
    exercised rather than depending on what the local model cache resolves to."""
    from regulus.dashboard.schemas import CurrentSystem, ModelIdentity

    parent = project / "artifacts" / "acceptance_test"
    write_run(parent, "acc_base_20260101T000000Z", finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS)
    write_run(parent, "acc_lora_20260601T000000Z", finished="2026-06-01T00:00:00+00:00", scored=QUESTIONS,
              adapter="models/qwen3-0.6b-lora/someadapter/adapter")
    registry = registry_for(project)
    # the configured system is the BASE model, as the synthetic runs record it
    current = CurrentSystem(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision="r" * 40),
                            pipeline_fingerprint={"version": 6, "algorithm": "sha256", "value": "0" * 64})
    schema_of = lambda e: getattr(registry.evaluation(e.experiment_id), "schema", None)
    chosen, rejected, matches = AV.select(registry.experiments, current, schema_of)
    assert chosen.name == "acc_base_20260101T000000Z" and matches is True

    # and with the adapter configured instead, the base run is the one set aside
    other = CurrentSystem(model=ModelIdentity(base_model_id="Qwen/Qwen3-0.6B", revision="r" * 40,
                                              adapter_id="someadapter", checkpoint="checkpoint-1"),
                          pipeline_fingerprint={"version": 6, "algorithm": "sha256", "value": "0" * 64})
    chosen, rejected, matches = AV.select(registry.experiments, other, schema_of)
    assert matches is False, "no eligible run has those weights, and the payload must say so"
    assert chosen.name == "acc_base_20260101T000000Z"


def test_the_metrics_are_recomputed_from_the_verdict_records(project: Path):
    run = write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
                    finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, passes=2)
    loaded = acceptance.load(run, project)
    pass_rate = loaded.metric("acceptance_full_pass")
    assert (pass_rate.numerator, pass_rate.denominator) == (2, QUESTIONS)
    assert pass_rate.value == pytest.approx(2 / QUESTIONS)
    assert pass_rate.recomputed_from == "per-question verdict records"
    # and every key it emits has a definition, or the dashboard would raise
    for metric in loaded.metrics:
        assert definition(metric.definition_key or metric.key) is not None


# -------------------------------------------------- 2. stale source detection


def test_a_run_of_a_different_pipeline_is_never_current(project: Path):
    """§9: an old benchmark cannot silently appear as the current metric."""
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, validation="annotate_but_different")
    registry = registry_for(project)
    payload = AV.payload(registry)
    assert payload["is_current"] is False
    assert payload["freshness"]["status"] in (STALE, "HISTORICAL")
    assert AV.REVALIDATION_WARNING in payload["warnings"]
    assert "require revalidation" in AV.REVALIDATION_WARNING


def test_the_staleness_reason_names_the_settings_not_just_the_hashes(project: Path):
    """Two digests differing is not actionable; a named field is."""
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, validation="off")
    experiment = next(e for e in registry_for(project).experiments if e.name.startswith("acc_"))
    if experiment.freshness_code == "pipeline_fingerprint_mismatch":
        differences = experiment.freshness_checks["pipeline_differences"]
        assert any(d["field"] == "validation.validation_behavior" for d in differences)
        assert "validation.validation_behavior" in experiment.status_reason


def test_config_differences_distinguishes_unrecorded_from_different():
    a = {**PIPELINE, "decoding": {k: v for k, v in DECODING.items() if k != "repetition_penalty"}}
    b = {**PIPELINE, "decoding": DECODING}
    diffs = {d["field"]: d for d in config_differences(a, b)}
    assert diffs["decoding.repetition_penalty"]["note"] == "not recorded by the run"
    c = {**PIPELINE, "validation": {"validation_behavior": "annotate"}, "decoding": DECODING}
    assert config_differences(b, c)[0]["note"] == "configured differently"


def test_an_unverified_answer_key_is_always_disclosed(project: Path):
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, key_locked=False)
    payload = AV.payload(registry_for(project))
    assert AV.KEY_WARNING in payload["warnings"]
    assert payload["provenance"]["key_verification"]["key_is_locked"] is False
    assert any("unverified key invalidates" in c for c in payload["caveats"])


def test_inherited_verdicts_are_counted_and_not_presented_as_hand_scoring(project: Path):
    run = write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
                    finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, basis="inherited")
    loaded = acceptance.load(run, project)
    hand = loaded.metric("acceptance_rows_hand_scored")
    assert hand.value == 0.0 and "inherited" in (hand.note or "")
    assert any("inherited from an earlier run" in p for p in loaded.problems)


def test_a_run_that_records_no_scoring_basis_reports_it_as_unrecorded_not_zero(project: Path):
    """Absence must not read as zero: the first hand-scoring pass predates the field."""
    run = write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
                    finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, basis=None)
    loaded = acceptance.load(run, project)
    hand = loaded.metric("acceptance_rows_hand_scored")
    assert hand.value is None and hand.status == "missing"
    assert "it is not zero, it is unrecorded" in hand.note


# ------------------------------------------------------------- 3. provenance


REQUIRED_PROVENANCE = ("evaluation", "run_id", "evaluated_at", "model", "adapter", "retrieval",
                       "rubric", "questions", "evaluation_status", "artifact", "benchmark_sha256")


def test_every_provenance_field_the_spec_requires_is_present(project: Path):
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS)
    provenance = AV.payload(registry_for(project))["provenance"]
    for field in REQUIRED_PROVENANCE:
        assert provenance.get(field) not in (None, ""), field
    assert provenance["rubric"] == "regulus_substantive_rubric_v1"
    assert provenance["questions"] == provenance["benchmark_questions"] == QUESTIONS
    assert provenance["pipeline_fingerprint"]["derived"] is True


def test_the_payload_states_that_this_is_not_the_live_indicator(project: Path):
    """§7 / §8: the two accuracy numbers must never read as the same measure."""
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS)
    payload = AV.payload(registry_for(project))
    assert "per-answer accuracy indicator" in payload["not_the_live_indicator"]
    assert "must never be combined" in payload["not_the_live_indicator"]


# ---------------------------------------------- 4. live accuracy isolation


def test_the_dashboard_does_not_import_the_live_accuracy_evaluator():
    """§8: the per-question indicator must never feed the overall metric."""
    import subprocess
    import sys

    code = ("import regulus.dashboard.registry, regulus.dashboard.health, regulus.dashboard.acceptance_view, sys;"
            "print([m for m in sys.modules if m.startswith('regulus.accuracy')])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_no_dashboard_metric_comes_from_live_questions(project: Path):
    """Every metric the dashboard can show is defined against a controlled artifact."""
    for key, meta in REGISTRY.items():
        assert "live" not in meta.source_hint.lower(), key
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS)
    registry = registry_for(project)
    before = json.dumps(AV.payload(registry), sort_keys=True, default=str)
    # running the live evaluator cannot move a dashboard number
    from regulus.accuracy import evaluate_safely

    evaluate_safely("a live question", "a live answer", package=None)
    assert json.dumps(AV.payload(registry), sort_keys=True, default=str) == before


# --------------------------------------------------------- 6. missing metrics


def test_with_no_acceptance_run_the_dashboard_says_so(project: Path):
    payload = AV.payload(registry_for(project))
    assert payload["available"] is False
    assert "never been run here" in payload["reason"]
    assert "headline" not in payload and "metrics" not in payload


def test_with_only_a_partially_scored_run_no_number_is_offered(project: Path):
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=2)
    payload = AV.payload(registry_for(project))
    assert payload["available"] is False
    assert "partially scored run is not a benchmark result" in payload["reason"]
    assert payload["rejected"][0]["rejected_because"] == AV.WHOLE_BENCHMARK


def test_the_overview_headline_still_refuses_when_nothing_is_current(project: Path):
    """Adding the acceptance section must not make the headline claim a number."""
    write_run(project / "artifacts" / "acceptance_test", "acc_20260101T000000Z",
              finished="2026-01-01T00:00:00+00:00", scored=QUESTIONS, validation="off")
    registry = registry_for(project)
    health = current_health(registry, registry.thresholds)
    assert health["state"] == "not_evaluated" and health["sections"] == []
    assert AV.payload(registry)["is_current"] is False


def test_a_run_whose_answers_are_short_is_an_incomplete_run(project: Path):
    """A short ANSWER set means the run did not finish; short SCORING does not."""
    short = write_run(project / "artifacts" / "acceptance_test", "acc_short_20260101T000000Z",
                      finished="2026-01-01T00:00:00+00:00", scored=2, answers=2)
    assert acceptance.load(short, project).status == INCOMPLETE
    scored_short = write_run(project / "artifacts" / "acceptance_test", "acc_part_20260201T000000Z",
                             finished="2026-02-01T00:00:00+00:00", scored=2, answers=QUESTIONS)
    loaded = acceptance.load(scored_short, project)
    assert loaded.status == COMPLETE and loaded.question_set["full_benchmark"] is False
    assert any("partial scoring" in p for p in loaded.problems)


# ------------------------------------- the repository's own runs (not synthetic)


REAL = PROJECT_ROOT / "artifacts" / "acceptance_test"
real_runs = pytest.mark.skipif(not REAL.is_dir(), reason="no acceptance runs in this checkout")


@real_runs
def test_this_repository_s_acceptance_runs_load_and_are_not_current():
    """The real artifacts: they must be visible, and none may claim to be current."""
    registry = Registry(PROJECT_ROOT)
    registry.refresh()
    runs = [e for e in registry.experiments if e.name.startswith("acceptance_")]
    assert runs, "the acceptance runs are not being discovered"
    assert all(e.status != CURRENT for e in runs)
    payload = AV.payload(registry)
    assert payload["available"] is True and payload["is_current"] is False
    assert payload["provenance"]["rubric"] == "regulus_substantive_rubric_v1"
    assert payload["provenance"]["questions"] == payload["provenance"]["benchmark_questions"]


@real_runs
def test_the_real_pass_rate_matches_the_projects_own_score_report():
    """The dashboard number must equal what scripts/c123_score_report.py tabulates
    from the same verdict files, on the same denominator (ERROR rows excluded)."""
    import glob

    registry = Registry(PROJECT_ROOT)
    registry.refresh()
    payload = AV.payload(registry)
    run_dir = PROJECT_ROOT / payload["provenance"]["artifact"]
    rows = {}
    for path in sorted(glob.glob(str(run_dir / "scoring" / "verdicts_*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                record = json.loads(line)
                rows[record["id"]] = record
    scored = [r for r in rows.values() if r.get("result") != "ERROR"]
    expected = sum(1 for r in scored if acceptance._full_pass(r))
    assert payload["headline"]["numerator"] == expected
    assert payload["headline"]["denominator"] == len(scored)
