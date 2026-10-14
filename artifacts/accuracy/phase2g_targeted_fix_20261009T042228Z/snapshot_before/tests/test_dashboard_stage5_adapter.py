"""Tests for the Stage 5 dashboard adapter.

Synthetic run directories exercise the behaviour; the real Stage 5 baseline,
when it is present, is checked for internal consistency only. No expected
metric value is written into this file: the point of the adapter is that the
numbers come out of the artifacts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from regulus.dashboard import metrics as M
from regulus.dashboard.adapters import stage5
from regulus.dashboard.schemas import COMPLETE, INCOMPLETE, INCONSISTENT, OK, UNRECORDED

REAL_RUN = Path("artifacts/stage5_stage6/stage5_baseline_20260923/stage5")


# ------------------------------------------------------------------ fixtures


def _evidence(qid: str, *, retrieval_ok=True, coverage_ok=True, selection_ok=True, expected_exact=("21 CFR 820.10(b)(1)",)):
    return {
        "id": qid, "category": "single", "question": f"question {qid}", "plan_kind": "single_provision",
        "requirements": list(expected_exact),
        "retrieval": {
            "parsed_requirements": list(expected_exact), "parse_ok": True,
            "expected_exact": list(expected_exact),
            "retrieved_exact": list(expected_exact) if retrieval_ok else [],
            "exact_recall": 1.0 if retrieval_ok else 0.0,
            "expected_missing_without_exact": [], "false_exact_for_missing": [],
            "tier_counts": {"exact": 1, "structural": 1, "supporting": 0, "discovery": 0},
            "fallback_used": False, "retrieval_mode": "exact", "candidates": 4,
            "per_requirement": {"r1": {"requirement_id": "r1", "canonical": expected_exact[0], "resolved": True}},
            "notes": [],
        },
        "coverage": {
            "state": "COMPLETE", "expected_state": "COMPLETE", "missing": [], "expected_missing": [],
            "satisfied": ["r1"],
            "counts": {"total_requirements": 1, "exact_requirements": 1},
            "requirements": [{
                "requirement_id": "r1", "canonical": expected_exact[0], "status": "exact", "satisfied": True,
                "exact_evidence_ids": ["e1"], "structural_evidence_ids": ["e2"],
                "supporting_evidence_ids": [], "discovery_evidence_ids": [], "note": None,
            }],
        },
        "selection": {
            "selected": 2, "protected": 1, "dropped": 0,
            "context_tiers": {"exact": 1, "structural": 1, "supporting": 0, "discovery": 0},
            "total_chars": 900, "overflow": False, "required_dropped": [], "required_truncated": [],
            "optional_truncated": 0, "required_present_in_context": {expected_exact[0]: True},
            "structural_in_context": 1, "discovery_in_context": 0,
            "dropped_reasons": [], "selected_ids": ["e1", "e2"],
        },
        "retrieval_ok": retrieval_ok, "coverage_ok": coverage_ok, "selection_ok": selection_ok,
        "deterministic": True, "evidence_ok": retrieval_ok and coverage_ok and selection_ok,
        "timings_ms": {"planning_ms": 1.0, "retrieval_ms": 20.0, "coverage_selection_ms": 3.0},
    }


def _generation(qid: str, *, generated=True, valid_raw=True, valid_final=True, repair=None, expected_behavior="answer"):
    validation_raw = {"status": "valid" if valid_raw else "evidence_mismatched", "ok": valid_raw,
                      "codes": [] if valid_raw else ["citation_mismatch"], "problems": []}
    validation_final = {"status": "valid" if valid_final else "evidence_mismatched", "ok": valid_final,
                        "codes": [] if valid_final else ["citation_mismatch"], "problems": []}
    return {
        "id": qid, "category": "single", "expected_behavior": expected_behavior,
        "domain": {"leak_raw": False, "leak_final": False},
        "mode": "full", "generated": generated, "skipped_reason": None if generated else "refuse_unsupported",
        "coverage_action": "complete",
        "answer_raw": f"raw answer for {qid}", "answer_final": f"final answer for {qid}",
        "repair": repair,
        "validation_initial": validation_raw, "validation_final": validation_final,
        "valid_raw": valid_raw, "valid_final": valid_final,
        "valid_only_after_repair": bool(valid_final and not valid_raw),
        "tokens": {"cap": 128, "generated": 40, "finished": True, "prompt_tokens": 800, "truncated": False},
        "timings_ms": {"retrieval_ms": 20.0, "context_ms": 1.0, "generation_ms": 3000.0, "validation_ms": 2.0, "total_ms": 3023.0},
        "wall_s": 3.1,
        "refusal": {"raw_class": "answer", "final_class": "answer", "expected": expected_behavior,
                    "deterministic_refusal": False, "correct_refusal": expected_behavior != "refuse",
                    "false_refusal": False, "false_answer": False, "final_false_refusal": False},
        "completeness": {"expected_exact_ids": ["r1"], "expected_exact_labels": ["21 CFR 820.10(b)(1)"],
                         "addressed_raw": ["r1"], "addressed_final": ["r1"],
                         "all_addressed_raw": True, "all_addressed_final": True,
                         "terms_expected": [], "terms_found_raw": [], "terms_found_final": [],
                         "term_recall_raw": 1.0, "term_recall_final": 1.0},
        "hallucination": {"fabricated_identifiers_raw": [], "fabricated_identifiers_final": [],
                          "codes_raw": [], "codes_final": [], "flags_raw": {},
                          "any_raw": not valid_raw, "any_final": False},
        "citations": {"listed": [{"index": 1, "label": "21 CFR 820.10(b)(1)", "tier": "exact", "role": "cited"}],
                      "markers": [1], "invalid": [],
                      "by_tier": {"exact": 1, "structural": 0, "supporting": 0, "discovery": 0, "invalid": 0},
                      "exact_source_cited_for": {"r1": True}, "requirements_with_exact_cited": 1,
                      "requirements_satisfied": 1, "irrelevant_markers": 0, "citation_ok": True},
        "faithfulness": {"claims": [{"claim": "raw claim", "supported": "YES" if valid_raw else "NO", "overlap": 0.8}],
                         "counts": {"YES": int(valid_raw), "NO": int(not valid_raw), "UNCERTAIN": 0, "N/A": 0},
                         "supported_ratio": 1.0 if valid_raw else 0.0},
        "faithfulness_final": {"claims": [{"claim": "final claim", "supported": "YES", "overlap": 0.9}],
                               "counts": {"YES": 1, "NO": 0, "UNCERTAIN": 0, "N/A": 0}, "supported_ratio": 1.0},
        "shape": "single", "prompt_chars": 2400,
    }


def _make_run(tmp_path: Path, *, ids=("S-1", "S-2", "S-3"), aggregates=None, phases=("evidence", "generation", "report"),
              benchmark_rows=None, benchmark_sha=None, extra_files=None) -> Path:
    """Write a minimal but realistic Stage 5 run directory."""
    d = tmp_path / "run" / "stage5"
    d.mkdir(parents=True)

    bench = d.parent / "bench.jsonl"
    rows = benchmark_rows if benchmark_rows is not None else [
        {"id": qid, "category": "single", "question": f"question {qid}", "domain": "regulatory",
         "expected_behavior": "answer", "expected_missing": []} for qid in ids
    ]
    bench.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    sha = benchmark_sha or hashlib.sha256(bench.read_bytes()).hexdigest()

    (d / "run_manifest.json").write_text(json.dumps({
        "run_id": "unit_run", "dataset": bench.as_posix(), "dataset_sha256": sha,
        "questions": list(ids), "config": {"retriever": "LexicalRetriever", "top_k": 8},
        "skip_generation": False, "controlled": True,
    }), encoding="utf-8")

    evidence = [_evidence(q) for q in ids]
    full = [_generation(q, valid_raw=(q != ids[-1]), valid_final=True,
                        repair=None if q != ids[-1] else "extractive_replacement") for q in ids]
    controlled = [_generation(q) for q in ids]
    for name, rows_ in (("evidence_records.jsonl", evidence), ("generation_full.jsonl", full),
                        ("generation_controlled.jsonl", controlled)):
        (d / name).write_text("".join(json.dumps(r) + "\n" for r in rows_), encoding="utf-8")

    for phase in phases:
        (d / f"phase_{phase}.json").write_text(
            json.dumps({"status": "done", "phase": phase, "finished_at": "2026-01-01 00:00:00"}), encoding="utf-8")

    for name, payload in (aggregates or {}).items():
        (d / name).write_text(json.dumps(payload), encoding="utf-8")
    for name, text in (extra_files or {}).items():
        (d / name).write_text(text, encoding="utf-8")
    return d


# -------------------------------------------------------------------- detect


def test_detect_accepts_a_run_directory(tmp_path):
    assert stage5.detect(_make_run(tmp_path)) is True


def test_detect_rejects_non_runs(tmp_path):
    assert stage5.detect(tmp_path / "missing") is False
    empty = tmp_path / "empty"
    empty.mkdir()
    assert stage5.detect(empty) is False
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "run_manifest.json").write_text("{not json", encoding="utf-8")
    assert stage5.detect(junk) is False
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "run_manifest.json").write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
    assert stage5.detect(partial) is False


def test_detect_rejects_a_file(tmp_path):
    f = tmp_path / "run_manifest.json"
    f.write_text("{}", encoding="utf-8")
    assert stage5.detect(f) is False


# ---------------------------------------------------------------- basic load


def test_load_builds_an_evaluation_run_from_the_records(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    assert run.schema == "stage5/v1"
    assert run.status == COMPLETE
    assert run.name == "unit_run"
    assert len(run.questions) == 3
    # two of three raw answers are valid in the fixture, and all three are final-valid
    assert run.metric("valid_raw").numerator == 2
    assert run.metric("valid_raw").denominator == 3
    assert run.metric("valid_raw").value == pytest.approx(2 / 3)
    assert run.metric("valid_final").value == pytest.approx(1.0)


def test_numerators_and_denominators_are_preserved(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    proportions = [m for m in run.metrics if m.unit == "ratio" and m.value is not None]
    assert proportions
    for m in proportions:
        if m.numerator is not None and m.denominator:
            assert m.sample_note == f"{m.numerator} / {m.denominator}"


def test_every_metric_has_a_registry_definition(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    for m in run.metrics:
        assert M.has_definition(m.key), m.key
        assert m.direction == M.definition(m.key).direction
        assert m.unit == M.definition(m.key).unit


def test_metrics_carry_their_source_artifact(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    assert all(m.source for m in run.metrics)
    assert "generation_full.jsonl" in run.source_artifacts
    assert "run_manifest.json" in run.source_artifacts


# --------------------------------------------------------- identity handling


def test_model_identity_is_reported_as_unrecorded_not_guessed(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    assert run.model.base_model_id == UNRECORDED
    assert run.model.recorded is False
    # it must not claim "base", which would assert that no adapter was used
    assert run.model.key == UNRECORDED
    assert "base" not in run.model.key
    assert any("model identity is not recorded" in p for p in run.problems)


def test_benchmark_identity_comes_from_the_manifest_hash(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    assert run.benchmark.benchmark_id == "bench"
    assert run.benchmark.questions == 3
    assert run.benchmark.sha256
    assert run.benchmark.key.endswith(run.benchmark.sha256[:12])


def test_benchmark_content_is_ignored_when_its_hash_does_not_match(tmp_path):
    run = stage5.load(_make_run(tmp_path, benchmark_sha="0" * 64))
    assert run.benchmark.sha256 == "0" * 64
    assert any("has sha256" in p for p in run.problems)


# ----------------------------------------------------------- cross-checking


def test_a_stored_aggregate_that_disagrees_is_flagged_not_corrected(tmp_path):
    # the records give 3/3; the aggregate file claims half that
    run = stage5.load(_make_run(tmp_path, aggregates={"retrieval_results.json": {"retrieval_ok": 0.5}}))
    m = run.metric("retrieval_ok")
    assert m.status == INCONSISTENT
    assert m.value == 0.5, "the stored value is what is displayed"
    assert m.numerator == 3 and m.denominator == 3
    assert "recomputed from the per-question records" in (m.note or "")
    assert any("disagree" in p for p in run.problems)


def test_a_matching_stored_aggregate_is_accepted(tmp_path):
    run = stage5.load(_make_run(tmp_path, aggregates={"retrieval_results.json": {"retrieval_ok": 1.0}}))
    assert run.metric("retrieval_ok").status == OK


def test_metrics_survive_a_missing_aggregate_file(tmp_path):
    run = stage5.load(_make_run(tmp_path))  # no aggregate files at all
    assert run.metric("retrieval_ok").value == pytest.approx(1.0)
    assert run.metric("correctness_raw") is None, "correctness has no per-question fallback"


def test_run_duration_is_reported_missing_rather_than_invented(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    duration = run.metric("run_duration")
    assert duration.value is None
    assert duration.status == "missing"
    assert run.started_at is None and run.duration_seconds is None


# ------------------------------------------------------------ raw vs final


def test_raw_and_final_are_never_merged(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    q = run.questions[-1]  # the fixture's repaired question
    assert q.answer_raw != q.answer_final
    assert q.validation_raw["status"] != q.validation_final["status"]
    assert q.repair == "extractive_replacement"
    assert q.claims_raw[0]["claim"] == "raw claim"
    assert q.claims_final[0]["claim"] == "final claim"
    assert run.metric("valid_raw").value < run.metric("valid_final").value


def test_faithfulness_raw_and_final_come_from_their_own_blocks(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    assert run.metric("faithfulness_raw").value == pytest.approx(2 / 3)
    assert run.metric("faithfulness_final").value == pytest.approx(1.0)
    assert run.metric("unsupported_sentences_raw").value == 1.0
    assert run.metric("unsupported_sentences_final").value == 0.0


# ------------------------------------------------------- per-question detail


def test_question_records_preserve_the_pipeline_layers(tmp_path):
    run = stage5.load(_make_run(tmp_path))
    q = run.questions[0]
    assert q.question == "question S-1"
    assert q.plan_kind == "single_provision"
    assert q.detected_requirements == ("21 CFR 820.10(b)(1)",)
    assert q.coverage_state == "COMPLETE"
    assert [e["evidence_id"] for e in q.evidence_by_tier["exact"]] == ["e1"]
    assert [e["evidence_id"] for e in q.selected_evidence] == ["e1", "e2"]
    assert q.latency_ms["evidence_planning_ms"] == 1.0
    assert q.total_ms == 3023.0
    assert q.tokens["generated"] == 40
    assert q.citations and q.citations[0]["tier"] == "exact"
    assert q.extra["completeness"]["all_addressed_raw"] is True
    assert q.domain == "regulatory"


def test_controlled_condition_is_kept_separate(tmp_path):
    """The exact-evidence condition is what localises a failure to context."""
    run = stage5.load(_make_run(tmp_path))
    q = run.questions[-1]
    assert q.controlled_generated is True
    # the fixture's last question fails the full pipeline and passes with
    # exact evidence only, which is the signal the whole condition exists for
    assert q.validation_raw["ok"] is False
    assert q.controlled_valid_raw is True
    assert q.controlled_answer_raw is not None
    assert run.metric("valid_raw_controlled").value > run.metric("valid_raw").value


# ---------------------------------------------------- incomplete and broken


def test_a_run_without_a_generation_phase_is_incomplete(tmp_path):
    run = stage5.load(_make_run(tmp_path, phases=("evidence",)))
    assert run.status == INCOMPLETE
    assert any("generation phase did not finish" in p for p in run.problems)


def test_fewer_records_than_questions_is_incomplete(tmp_path):
    d = _make_run(tmp_path)
    rows = (d / "generation_full.jsonl").read_text(encoding="utf-8").splitlines()
    (d / "generation_full.jsonl").write_text(rows[0] + "\n", encoding="utf-8")
    run = stage5.load(d)
    assert run.status == INCOMPLETE
    assert any("1 of the 3 questions" in p for p in run.problems)


def test_a_truncated_jsonl_line_is_skipped_not_fatal(tmp_path):
    d = _make_run(tmp_path)
    with (d / "generation_full.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"id": "S-4", "categ')
    run = stage5.load(d)
    assert len(run.questions) == 3


def test_an_unparseable_aggregate_is_reported_not_swallowed(tmp_path):
    d = _make_run(tmp_path)
    (d / "citation_results.json").write_text("{broken", encoding="utf-8")
    run = stage5.load(d)
    assert any("citation_results.json" in p and "JSON" in p for p in run.problems)


def test_load_rejects_a_directory_that_is_not_a_run(tmp_path):
    with pytest.raises(ValueError):
        stage5.load(tmp_path)


# ------------------------------------------------- the real Stage 5 baseline


@pytest.mark.skipif(not REAL_RUN.is_dir(), reason="the Stage 5 baseline run is not present")
def test_real_stage5_run_loads_and_is_internally_consistent():
    root = Path.cwd()
    run = stage5.load(REAL_RUN, root=root)

    assert run.schema == "stage5/v1"
    assert run.status == COMPLETE
    assert run.benchmark.questions == len(run.questions)
    assert run.completed_at

    # every stored proportion agrees with the count recomputed from the
    # per-question records; a disagreement would be an evaluator bug
    assert [m.key for m in run.metrics if m.status == INCONSISTENT] == []

    for m in run.metrics:
        if m.unit == "ratio" and m.value is not None and m.numerator is not None and m.denominator:
            assert m.value == pytest.approx(m.numerator / m.denominator, abs=0.005), m.key
            assert 0.0 <= m.value <= 1.0, m.key

    # the layers stay distinguishable
    for key in ("retrieval_ok", "coverage_ok", "selection_ok", "valid_raw", "valid_final",
                "correctness_raw", "correctness_final", "faithfulness_raw", "faithfulness_final",
                "citation_ok", "hallucination_raw", "repair_rate", "e2e_latency_p50"):
        assert run.metric(key) is not None, key

    # raw and final are separate numbers, not one number shown twice
    assert run.metric("valid_raw").value != run.metric("valid_final").value
    assert run.metric("correctness_raw").value != run.metric("correctness_final").value

    # the run knows what it does not know
    assert run.model.recorded is False
    assert run.metric("run_duration").status == "missing"

    # per-question forensics survived
    repaired = [q for q in run.questions if q.repair]
    assert repaired, "the baseline has repaired answers"
    assert all(q.answer_raw is not None and q.answer_final is not None for q in repaired)
    assert any(q.answer_raw != q.answer_final for q in repaired)
    assert any(q.failure_layer and q.failure_layer != "none" for q in run.questions)
    assert sum(run.failure_summary["by_layer"].values()) == len(run.questions)
