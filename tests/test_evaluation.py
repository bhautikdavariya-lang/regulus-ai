"""Evaluation infrastructure tests. No model is loaded; generation is faked."""

import json
from datetime import datetime, timezone

import pytest

from regulus.config import GenerationConfig, Settings
from regulus.evaluation import (
    CATEGORIES,
    DatasetError,
    EvalExample,
    EvaluationRun,
    QuestionResult,
    aggregate,
    build_run_metadata,
    load_dataset,
    load_run,
    result_filename,
    run_evaluation,
    save_run,
)
from regulus.evaluation.dataset import DEFAULT_DATASET_PATH, parse_jsonl
from regulus.evaluation.report import render_answers, render_summary
from regulus.evaluation.results import ResultsError
from regulus.evaluation.runner import sanitize_error
from regulus.inference import GenerationResult

VALID = {
    "id": "t-1",
    "category": "general_knowledge",
    "question": "Q?",
    "reference_answer": "A.",
    "evaluation_notes": "n",
    "expected_behavior": "answer",
}


def _line(**overrides):
    return json.dumps({**VALID, **overrides})


def _example(i: int, category: str = "general_knowledge") -> EvalExample:
    return EvalExample(f"t-{i}", category, f"Q{i}?", "ref", "notes", "answer")


def fake_generate(question: str) -> GenerationResult:
    return GenerationResult(prompt=question, response=f"answer to {question}", prompt_tokens=10, generated_tokens=5, seconds=0.5)


# ---------------------------------------------------------------- dataset


def test_real_dataset_loads_and_is_well_formed():
    ds = load_dataset()
    assert ds.name == "baseline_v1"
    assert 20 <= len(ds) <= 30
    assert len(ds.sha256) == 64
    assert {e.category for e in ds} == set(CATEGORIES)
    for e in ds:
        if e.category == "hallucination":
            assert e.expected_behavior == "acknowledge_uncertainty"
        else:
            assert e.expected_behavior == "answer"
    assert ds.relative_path() == "data/evaluation/datasets/baseline_v1.jsonl"


def test_default_dataset_path_exists():
    assert DEFAULT_DATASET_PATH.is_file()


def test_parse_valid_and_skips_blank_lines():
    text = "\n" + _line() + "\n\n" + _line(id="t-2") + "\n"
    examples = parse_jsonl(text)
    assert [e.id for e in examples] == ["t-1", "t-2"]


@pytest.mark.parametrize("field", ["id", "category", "question", "reference_answer", "evaluation_notes", "expected_behavior"])
def test_missing_required_field(field):
    record = {k: v for k, v in VALID.items() if k != field}
    with pytest.raises(DatasetError, match=f"missing required field.*{field}"):
        parse_jsonl(json.dumps(record))


def test_empty_string_field_rejected():
    with pytest.raises(DatasetError, match="non-empty string"):
        parse_jsonl(_line(question="   "))


def test_unknown_category_rejected():
    with pytest.raises(DatasetError, match="unknown category"):
        parse_jsonl(_line(category="trivia"))


def test_unknown_expected_behavior_rejected():
    with pytest.raises(DatasetError, match="unknown expected_behavior"):
        parse_jsonl(_line(expected_behavior="refuse"))


def test_extra_field_rejected():
    with pytest.raises(DatasetError, match="unexpected field"):
        parse_jsonl(_line(extra="x"))


def test_duplicate_id_rejected():
    with pytest.raises(DatasetError, match="duplicate id"):
        parse_jsonl(_line() + "\n" + _line())


def test_malformed_json_line_reports_line_number():
    with pytest.raises(DatasetError, match="line 2: invalid JSON"):
        parse_jsonl(_line() + "\n{not json")


def test_non_object_record_rejected():
    with pytest.raises(DatasetError, match="expected a JSON object"):
        parse_jsonl("[1, 2]")


def test_empty_dataset_rejected():
    with pytest.raises(DatasetError, match="no examples"):
        parse_jsonl("\n\n")


def test_missing_file(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load_dataset(tmp_path / "missing.jsonl")


# ----------------------------------------------------------------- runner


def test_run_evaluation_records_completed_results():
    examples = [_example(1), _example(2, "hallucination")]
    seen = []
    run = run_evaluation(examples, fake_generate, {"pipeline": "test"}, on_progress=lambda i, n, r: seen.append((i, n)))
    assert seen == [(1, 2), (2, 2)]
    assert run.summary["completed"] == 2 and run.summary["failed"] == 0
    r = run.results[0]
    assert r.status == "completed"
    assert r.model_answer == "answer to Q1?"
    assert (r.input_tokens, r.output_tokens, r.generation_seconds, r.tokens_per_second) == (10, 5, 0.5, 10.0)
    assert r.quality_score is None and r.manual_evaluation is None
    assert run.run["pipeline"] == "test" and run.run["duration_seconds"] >= 0


def test_failure_is_recorded_and_run_continues():
    def flaky(question):
        if question == "Q2?":
            raise RuntimeError("boom")
        return fake_generate(question)

    run = run_evaluation([_example(1), _example(2), _example(3)], flaky, {})
    statuses = [r.status for r in run.results]
    assert statuses == ["completed", "failed", "completed"]
    assert run.results[1].error == "RuntimeError: boom"
    assert run.results[1].model_answer is None
    assert run.summary == {**run.summary, "total": 3, "completed": 2, "failed": 1, "failed_ids": ["t-2"]}


def test_sanitize_error_strips_paths_and_truncates():
    msg = sanitize_error(OSError("cannot open C:\\Users\\someone\\secret\\file.txt or /home/someone/x/y.txt"))
    assert "someone" not in msg
    assert msg.startswith("OSError: cannot open <path> or <path>")
    long = sanitize_error(ValueError("x" * 2000))
    assert len(long) <= 520 and long.endswith("...")


def test_build_run_metadata_contents():
    ds = load_dataset()
    settings = Settings()
    gen = GenerationConfig(do_sample=False, max_new_tokens=64)
    meta = build_run_metadata(
        run_id="abc12345",
        pipeline="baseline",
        started_at=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
        settings=settings,
        gen=gen,
        dataset=ds,
        device="cpu",
        dtype="float32",
        model_revision="deadbeef",
        environment={"python": "3.11", "torch": "2.x", "HF_TOKEN": "leak", "cuda_available": False},
        seed=42,
        num_questions=3,
    )
    assert meta["evaluation_run_id"] == "abc12345"
    assert meta["timestamp_utc"] == "2026-09-15T12:00:00+00:00"
    assert meta["model_id"] == "Qwen/Qwen3-0.6B"
    assert meta["decoding_mode"] == "greedy"
    assert meta["generation"]["max_new_tokens"] == 64
    assert meta["generation"]["temperature"] is None  # not meaningful when greedy
    assert meta["dataset"] == {"name": "baseline_v1", "path": ds.relative_path(), "sha256": ds.sha256, "num_examples": len(ds)}
    assert "HF_TOKEN" not in meta["environment"]
    assert "cache_dir" not in json.dumps(meta)


def test_sampling_metadata_keeps_sampling_params():
    ds = load_dataset()
    gen = GenerationConfig(do_sample=True, temperature=0.3, top_p=0.9, top_k=5)
    meta = build_run_metadata(
        run_id="x", pipeline="p", started_at=datetime.now(timezone.utc), settings=Settings(), gen=gen, dataset=ds,
        device="cpu", dtype="float32", model_revision=None, environment={}, seed=1, num_questions=1,
    )
    assert meta["decoding_mode"] == "sampling"
    assert meta["generation"]["temperature"] == 0.3 and meta["generation"]["top_k"] == 5


# ------------------------------------------------------------ aggregation


def _result(i, status="completed", category="general_knowledge", score=None, secs=1.0, tin=10, tout=20):
    kwargs = dict(status=status, quality_score=score)
    if status == "completed":
        kwargs.update(model_answer="a", generation_seconds=secs, input_tokens=tin, output_tokens=tout, tokens_per_second=tout / secs)
    else:
        kwargs["error"] = "E: x"
    return QuestionResult.from_example(_example(i, category), **kwargs)


def test_aggregate_metrics():
    rows = [
        _result(1, secs=1.0, tin=10, tout=20),
        _result(2, secs=3.0, tin=30, tout=40, category="reasoning"),
        _result(3, status="failed", category="reasoning"),
    ]
    s = aggregate(rows)
    assert (s["total"], s["completed"], s["failed"]) == (3, 2, 1)
    assert s["failed_ids"] == ["t-3"]
    assert s["avg_generation_seconds"] == 2.0
    assert s["avg_input_tokens"] == 20.0 and s["avg_output_tokens"] == 30.0
    assert s["by_category"] == {
        "general_knowledge": {"total": 1, "completed": 1, "failed": 0},
        "reasoning": {"total": 2, "completed": 1, "failed": 1},
    }
    assert s["manual_evaluation"] == {"scored": 0, "unscored": 3}


def test_aggregate_empty():
    s = aggregate([])
    assert s["total"] == 0 and s["avg_generation_seconds"] is None and s["by_category"] == {}


def test_aggregate_manual_scores():
    rows = [_result(1, score=2), _result(2, score=1, category="hallucination"), _result(3)]
    m = aggregate(rows)["manual_evaluation"]
    assert m["scored"] == 2 and m["unscored"] == 1 and m["mean_score"] == 1.5
    assert m["by_category"] == {"general_knowledge": 2.0, "hallucination": 1.0}


# ------------------------------------------------------------ persistence


def test_result_filename_convention():
    when = datetime(2026, 9, 15, 15, 30, 12)
    assert result_filename("baseline", "a1b2c3d4", when) == "baseline_20260915_153012_a1b2c3d4.json"
    assert result_filename("qwen + rag/v2", "x", when).startswith("qwen___rag_v2_")


def test_save_and_load_roundtrip(tmp_path):
    run = run_evaluation([_example(1), _example(2)], fake_generate, {"pipeline": "test", "evaluation_run_id": "r1"})
    path = save_run(run, tmp_path / "sub" / "r.json")
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert set(data) == {"schema_version", "run", "summary", "results"}
    assert data["results"][0]["quality_score"] is None
    loaded = load_run(path)
    assert loaded.run == run.run
    assert loaded.results == run.results
    assert loaded.summary == run.summary


def test_load_run_errors(tmp_path):
    with pytest.raises(ResultsError, match="not found"):
        load_run(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(ResultsError, match="not valid JSON"):
        load_run(bad)
    bad.write_text('{"run": {}}', encoding="utf-8")
    with pytest.raises(ResultsError, match="malformed"):
        load_run(bad)


def test_manual_scores_survive_reload_and_aggregate(tmp_path):
    run = run_evaluation([_example(1)], fake_generate, {})
    path = save_run(run, tmp_path / "r.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["results"][0]["quality_score"] = 2
    data["results"][0]["manual_evaluation"] = {"reviewer": "me", "comment": "good"}
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_run(path)
    assert aggregate(loaded.results)["manual_evaluation"]["mean_score"] == 2.0


# ----------------------------------------------------------------- report


def test_render_summary_and_answers():
    ds = load_dataset()
    meta = build_run_metadata(
        run_id="r1", pipeline="baseline", started_at=datetime.now(timezone.utc), settings=Settings(),
        gen=GenerationConfig(do_sample=False), dataset=ds, device="cpu", dtype="float32",
        model_revision=None, environment={}, seed=42, num_questions=2,
    )

    def flaky(q):
        if q.startswith("What does CFR"):
            raise ValueError("nope")
        return fake_generate(q)

    run = run_evaluation(ds.examples[5:8], flaky, meta)
    text = render_summary(run)
    for needle in ("Model:       Qwen/Qwen3-0.6B", "Completed: 2", "Failed:    1", "Total:     3", "Regulatory concepts:", "No questions scored yet"):
        assert needle in text
    answers = render_answers(run)
    assert "ERROR: ValueError: nope" in answers and "Score: not evaluated" in answers
    assert render_answers(run, category="reasoning") == "(no matching questions)"
    assert "[baseline-006]" in render_answers(run, ids={"baseline-006"})
    assert "[baseline-007]" not in render_answers(run, ids={"baseline-006"})


def test_evaluation_run_from_dict_rejects_missing_results():
    with pytest.raises(ResultsError):
        EvaluationRun.from_dict({"run": {}})
