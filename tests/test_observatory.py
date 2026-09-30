"""Phase 3 backend: question forensics, history, comparison and their APIs.

Every behaviour here is decided on the server from canonical records: which
questions a filter selects, which runs share a history line, whether two
runs are comparable. These tests pin those decisions, and the rules that run
through all of them: unrecorded is never zero, distinct concepts stay
distinct, and nothing ranks or scores runs.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from regulus.config import PROJECT_ROOT
from regulus.dashboard.adapters import legacy, stage5
from regulus.dashboard.observatory import (
    compare_runs,
    evaluation_history,
    question_detail,
    question_list,
)
from regulus.dashboard.registry import Registry, read_current_system

from .current_system_fixtures import ROOTS, model_block_for, stage5_run, write_project
from .test_dashboard_adapters import _answer_file
from .test_dashboard_stage5_adapter import _evidence, _generation

PRODUCTION_RUN = PROJECT_ROOT / "artifacts" / "stage5_stage6" / "run_20260924T051025Z" / "stage5"


@pytest.fixture(autouse=True)
def _no_regulus_env(monkeypatch):
    for name in ("REGULUS_MODEL_ID", "REGULUS_ADAPTER", "REGULUS_MODEL_CACHE_DIR", "REGULUS_ANSWER_LENGTH_POLICY"):
        monkeypatch.delenv(name, raising=False)


def _registry(root: Path) -> Registry:
    return Registry(root, roots=ROOTS, store=root / "store.json")


def _rich_run(root: Path, name: str = "rich", **kwargs) -> Path:
    """A Stage 5 run whose questions exercise every filter."""
    d = stage5_run(root, name, ids=("Q-1", "Q-2", "Q-3", "Q-4"), **kwargs)
    full = [
        {**_generation("Q-1"), "selected_ids": ["e1", "e2"], "timings_ms": {"generation_ms": 1000.0, "total_ms": 1500.0},
         "citations": {"citation_ok": True, "listed": [{"index": 1, "label": "21 CFR 820.10(b)(1)", "cited_in_answer": True}], "markers": [1]}},
        {**_generation("Q-2", valid_raw=False, valid_final=True, repair="extractive_replacement"),
         "selected_ids": ["e3"], "timings_ms": {"generation_ms": 9000.0, "total_ms": 9600.0},
         "citations": {"citation_ok": False, "listed": [], "markers": [4]}},
        {**_generation("Q-3", generated=False), "selected_ids": None, "timings_ms": {"total_ms": 20.0},
         "refusal": {"raw_class": "refusal", "deterministic_refusal": True, "false_refusal": False}},
        {**_generation("Q-4"), "selected_ids": ["e1"], "timings_ms": {"generation_ms": 2000.0, "total_ms": 2400.0}},
    ]
    full[2]["generated"] = False
    full[2]["skipped_reason"] = "refuse_unsupported"
    (d / "generation_full.jsonl").write_text("".join(json.dumps(r) + "\n" for r in full), encoding="utf-8")
    ev = [_evidence(q, retrieval_ok=(q != "Q-4")) for q in ("Q-1", "Q-2", "Q-3", "Q-4")]
    (d / "evidence_records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ev), encoding="utf-8")
    correctness = {"per_question": [
        {"id": "Q-1", "raw_correct": True, "final_correct": True},
        {"id": "Q-2", "raw_correct": False, "final_correct": True, "raw_reasons": ["validator: unsupported"]},
        {"id": "Q-3", "raw_correct": False, "final_correct": False},
        {"id": "Q-4", "raw_correct": False, "final_correct": False}]}
    (d / "correctness_results.json").write_text(json.dumps(correctness), encoding="utf-8")
    (d / "failure_analysis.json").write_text(json.dumps({"per_question": [
        {"id": "Q-1", "layer": "none"}, {"id": "Q-2", "layer": "none"},
        {"id": "Q-3", "layer": "domain_boundary"}, {"id": "Q-4", "layer": "retrieval"}]}), encoding="utf-8")
    return d


# ------------------------------------------------------------------ questions


def test_every_question_is_listed_with_its_id(tmp_path):
    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    listing = question_list(run)
    assert listing["total"] == listing["matched"] == 4
    assert [r["id"] for r in listing["questions"]] == ["Q-1", "Q-2", "Q-3", "Q-4"]


@pytest.mark.parametrize("key,expected", [
    ("correct", {"Q-1", "Q-2"}),
    ("incorrect", {"Q-3", "Q-4"}),
    ("raw_incorrect", {"Q-2", "Q-3", "Q-4"}),
    ("only_after_repair", {"Q-2"}),
    ("validation_failure", {"Q-2"}),
    ("repaired", {"Q-2"}),
    ("unrepaired", {"Q-1", "Q-4"}),
    ("retrieval_issue", {"Q-4"}),
    ("citation_issue", {"Q-2"}),
    ("refused", {"Q-3"}),
    ("slow", {"Q-2"}),
    ("no_model_answer", {"Q-3"}),
    ("not_measured", set()),          # offered, and a measured zero: every question has a verdict
])
def test_filters_select_exactly_the_matching_questions(tmp_path, key, expected):
    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    listing = question_list(run, filter_key=key)
    assert {r["id"] for r in listing["questions"]} == expected
    offered = {f["key"]: f for f in listing["filters"]}
    assert offered[key]["available"] and offered[key]["count"] == len(expected)


def test_layer_category_and_search_filter_on_the_server(tmp_path):
    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    assert [r["id"] for r in question_list(run, layer="retrieval")["questions"]] == ["Q-4"]
    assert question_list(run, search="q-2")["matched"] == 1
    assert question_list(run, category="single")["matched"] == 4
    with pytest.raises(ValueError, match="no failure layer"):
        question_list(run, layer="nonsense")


def test_an_unknown_or_unanswerable_filter_is_an_error_not_an_empty_list(tmp_path):
    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    with pytest.raises(ValueError, match="unknown filter"):
        question_list(run, filter_key="bogus")
    # a legacy run records no validation, so "validation failure" cannot be answered
    old = legacy.load(_answer_file(root / "data" / "evaluation" / "results"))
    listing = question_list(old)
    offered = {f["key"]: f for f in listing["filters"]}
    assert offered["validation_failure"]["available"] is False and offered["validation_failure"]["count"] is None
    assert offered["repaired"]["available"] is False
    with pytest.raises(ValueError, match="not available"):
        question_list(old, filter_key="validation_failure")


def test_failure_layer_none_is_not_final_correctness(tmp_path):
    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    rows = {r["id"]: r for r in question_list(run)["questions"]}
    # Q-2 is correct only after repair with layer none; Q-1 correct with layer none:
    # the two outputs are reported as they are, never derived from each other
    assert rows["Q-2"]["failure_layer"] == "none" and rows["Q-2"]["correct_raw"] is False
    assert "does not mean the final answer is correct" in question_list(run)["notes"]["failure_layer"]


def test_question_detail_preserves_the_exact_question_and_selected_evidence(tmp_path):
    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    q = question_detail(run, "Q-1")
    assert q["question"] == "question Q-1"
    ev = q["forensics"]["evidence"]
    assert [s["evidence_id"] for s in ev["selected"]] == ["e1", "e2"]
    assert [s["prompt_index"] for s in ev["selected"]] == [1, 2]
    assert ev["selected"][0]["source_label"] == "21 CFR 820.10(b)(1)" and ev["selected"][0]["cited_in_answer"] is True
    assert ev["selected"][1]["source_label"] is None            # not cited: no label is invented
    assert "question-local" in ev["scope"] and "not global document ids" in ev["scope"]


def test_question_detail_invents_nothing(tmp_path):
    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    skipped = question_detail(run, "Q-3")["forensics"]
    assert skipped["evidence"]["selected"] == []              # no model call, no evidence given to one
    assert skipped["expected"]["reference_answer"] is None
    assert skipped["expected"]["reference_answer_display"] == "Not provided by the benchmark"
    semantic = question_detail(run, "Q-1")["forensics"]["citations"]["semantic_correctness"]
    assert (semantic["value"], semantic["status"], semantic["display"]) == (None, "missing", "Not measured")
    assert question_detail(run, "NOPE") is None


def test_an_unrecorded_legacy_time_is_not_zero(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    path = _answer_file(results)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for r in payload["results"]:
        r.pop("generation_seconds", None)
    path.write_text(json.dumps(payload), encoding="utf-8")
    run = legacy.load(path)
    assert all(q.latency_ms == {} for q in run.questions)
    assert all(r["total_ms"] is None for r in question_list(run)["questions"])


# -------------------------------------------------------------------- history


def test_one_compatible_run_has_no_trend(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "only")
    h = evaluation_history(_registry(root))
    assert len(h["groups"]) == 1
    g = h["groups"][0]
    assert g["contains_current"] and g["trend_available"] is False
    assert g["trend_note"] == "History unavailable: only one compatible evaluation."


def test_compatible_runs_form_one_line_and_incompatible_ones_do_not(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "early", completed_at="2026-01-01T00:00:00+00:00")
    stage5_run(root, "late", completed_at="2026-02-01T00:00:00+00:00")
    config = json.loads(json.dumps(read_current_system(root).evaluation_config))
    config["retrieval"]["top_k"] = 4
    stage5_run(root, "other_pipeline", completed_at="2026-03-01T00:00:00+00:00", evaluation_config=config)
    stage5_run(root, "other_model", model={**model_block_for(root), "id": "Other/model"})
    bench = tuple(f"S5-{i:03d}" for i in range(1, 52))
    stage5_run(root, "subset", ids=bench[:2], bench_ids=bench, bench_name="b51")
    stage5_run(root, "no_identity", model=None, evaluation_config=None, fingerprint=None, bench_name="b2")
    h = evaluation_history(_registry(root))
    cls = {r["name"]: r["compatibility"] for r in h["runs"]}
    assert cls == {"late": "reference", "early": "comparable", "other_pipeline": "different_pipeline",
                   "other_model": "different_model", "subset": "incomplete", "no_identity": "insufficient_identity"}
    current = next(g for g in h["groups"] if g["contains_current"])
    names = {r["experiment_id"]: r["name"] for r in h["runs"]}
    assert [names[i] for i in current["runs"]] == ["early", "late"]
    assert current["trend_available"] and current["series"]
    # every line holds one model, one benchmark, one pipeline
    for g in h["groups"]:
        members = [r for r in h["runs"] if r["experiment_id"] in g["runs"]]
        assert len({(m["identity"]["model_key"], m["identity"]["benchmark_key"],
                     m["identity"]["pipeline_fingerprint"]) for m in members}) == 1
        assert all(m["identity"]["full_benchmark"] is True for m in members)
    assert not any(names[i] in ("subset", "no_identity") for g in h["groups"] for i in g["runs"])


def test_a_legacy_run_stays_historical_with_limited_comparison(tmp_path):
    root = write_project(tmp_path / "p")
    _answer_file(root / "data" / "evaluation" / "results")
    h = evaluation_history(_registry(root))
    assert [r["compatibility"] for r in h["runs"]] == ["insufficient_identity"]
    assert h["groups"] == []


def test_an_empty_repository_has_empty_history(tmp_path):
    h = evaluation_history(_registry(write_project(tmp_path / "p")))
    assert h["runs"] == [] and h["groups"] == [] and h["counts"] == {}


def test_missing_history_metrics_are_not_zero(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "only")
    run = next(r for r in evaluation_history(_registry(root))["runs"])
    missing = [m for m in run["metrics"].values() if m["value"] is None]
    assert missing and all(m["display"] == "Not measured" for m in missing)


# ----------------------------------------------------------------- comparison


def _pairs(registry, *names):
    by_name = {e.name: e for e in registry.experiments}
    return [(by_name[n], registry.evaluation(by_name[n].experiment_id)) for n in names]


def test_compatible_runs_compare_with_deltas_and_no_winner(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "a", completed_at="2026-01-01T00:00:00+00:00")
    stage5_run(root, "b", completed_at="2026-02-01T00:00:00+00:00")
    t = compare_runs(_pairs(_registry(root), "a", "b"))
    assert [r["comparable"] for r in t["runs"]] == [True, True]
    row = next(r for r in t["rows"] if r["key"] == "valid_raw")
    assert row["cells"][1]["delta"] == 0 and row["cells"][1]["delta_percentage_points"] == 0
    blob = json.dumps(t).lower()
    # question-level "improved/regressed" lists name questions that changed; they are not a verdict
    for forbidden in ('"winner"', '"score"', '"rank"', '"overall'):
        assert forbidden not in blob


def test_different_benchmarks_are_explicitly_not_comparable(tmp_path):
    root = write_project(tmp_path / "p")
    stage5_run(root, "a")
    stage5_run(root, "b", bench_name="other", ids=("T-1", "T-2"))
    t = compare_runs(_pairs(_registry(root), "a", "b"))
    other = t["runs"][1]
    assert other["comparable"] is False and "benchmark_mismatch" in {b["code"] for b in other["blocking"]}
    assert all(r["cells"][1]["delta"] is None and r["cells"][1]["delta_note"] == "Not directly comparable"
               for r in t["rows"])
    assert t["questions"]["available"] is False


def test_a_subset_run_is_blocked_and_a_pipeline_change_is_flagged(tmp_path):
    root = write_project(tmp_path / "p")
    bench = tuple(f"S5-{i:03d}" for i in range(1, 52))
    stage5_run(root, "full", ids=bench, bench_ids=bench, bench_name="b51")
    stage5_run(root, "subset", ids=bench[:2], bench_ids=bench, bench_name="b51")
    config = json.loads(json.dumps(read_current_system(root).evaluation_config))
    config["generation_budget"]["min_tokens"] = 448
    stage5_run(root, "pipeline", ids=bench, bench_ids=bench, bench_name="b51", evaluation_config=config)
    t = compare_runs(_pairs(_registry(root), "full", "subset", "pipeline"))
    assert "partial_benchmark" in {b["code"] for b in t["runs"][1]["blocking"]}
    assert t["runs"][2]["comparable"] is True
    assert "pipeline_differs" in {w["code"] for w in t["runs"][2]["warnings"]}


def test_a_metric_one_run_lacks_is_not_measured_not_zero(tmp_path):
    root = write_project(tmp_path / "p")
    _rich_run(root, "with_correctness")
    stage5_run(root, "without_correctness", ids=("Q-1", "Q-2", "Q-3", "Q-4"))
    t = compare_runs(_pairs(_registry(root), "with_correctness", "without_correctness"))
    row = next(r for r in t["rows"] if r["key"] == "correctness_final")
    missing = row["cells"][1]
    assert missing["value"] is None and missing["display"] == "Not measured" and missing["delta"] is None


def test_comparison_needs_two_runs():
    with pytest.raises(ValueError):
        compare_runs([])


# ------------------------------------------------------------------ the API


@pytest.fixture
def api(tmp_path):
    servers = []

    def serve(root: Path):
        spec = importlib.util.spec_from_file_location(f"sd_{len(servers)}", PROJECT_ROOT / "scripts" / "serve_dashboard.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.STATE = module.State(root, store=tmp_path / f"store_{len(servers)}.json")
        module.STATE.registry.roots = ROOTS
        module.STATE.registry.refresh()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def get(path):
            try:
                with urllib.request.urlopen(base + path, timeout=30) as r:
                    return r.status, json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode("utf-8"))
        return get, module

    yield serve
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def test_api_questions_filtering_and_errors(tmp_path, api):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    get, _ = api(root)
    _, h = get("/api/model-health/current")
    eid = h["evaluation"]["experiment_id"]
    status, listing = get(f"/api/evaluation/experiments/{eid}/questions?filter=incorrect")
    assert status == 200 and {r["id"] for r in listing["questions"]} == {"Q-3", "Q-4"}
    assert listing["experiment"]["experiment_id"] == eid
    assert get(f"/api/evaluation/experiments/{eid}/questions?filter=bogus")[0] == 400
    assert get(f"/api/evaluation/experiments/{eid}/questions?filter=a&filter=b")[0] == 400
    assert get(f"/api/evaluation/experiments/{eid}/questions?layer=nonsense")[0] == 400
    assert get("/api/evaluation/experiments/0000000000000000/questions")[0] == 404
    status, detail = get(f"/api/evaluation/experiments/{eid}/questions/Q-1")
    assert status == 200 and detail["question"]["forensics"]["evidence"]["selected"][0]["evidence_id"] == "e1"
    assert get(f"/api/evaluation/experiments/{eid}/questions/NOPE")[0] == 404


def test_api_history_and_comparison(tmp_path, api):
    root = write_project(tmp_path / "p")
    stage5_run(root, "a", completed_at="2026-01-01T00:00:00+00:00")
    stage5_run(root, "b", completed_at="2026-02-01T00:00:00+00:00")
    stage5_run(root, "c", completed_at="2026-03-01T00:00:00+00:00")
    get, module = api(root)
    status, h = get("/api/evaluation/history")
    assert status == 200 and h["groups"][0]["trend_available"] and len(h["groups"][0]["runs"]) == 3
    ids = [e.experiment_id for e in module.STATE.registry.experiments]
    status, two = get(f"/api/evaluation/compare?ids={ids[0]},{ids[1]}")
    assert status == 200 and {"left", "right", "table"} <= set(two)
    status, three = get(f"/api/evaluation/compare?ids={','.join(ids)}")
    assert status == 200 and len(three["table"]["runs"]) == 3
    assert get(f"/api/evaluation/compare?ids={ids[0]}")[0] == 400
    assert get(f"/api/evaluation/compare?ids={ids[0]},{ids[0]}")[0] == 400
    assert get("/api/evaluation/compare?ids=" + ",".join([ids[0]] * 7))[0] == 400
    assert get(f"/api/evaluation/compare?ids={ids[0]},0000000000000000")[0] == 404
    assert get("/api/evaluation/compare")[0] == 400


def test_api_health_carries_evaluation_identity_and_coverage(tmp_path, api):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    get, _ = api(root)
    _, h = get("/api/model-health/current")
    ev = h["evaluation"]
    assert ev["started_at"] and ev["duration_seconds"] is not None
    assert ev["freshness_checks"] == {"question_set": "full", "model": "match", "pipeline": "match"}
    cov = h["coverage"]
    assert cov["measured"] + cov["not_measured"] == cov["health_defined"]
    assert cov["question_evidence"] == {**cov["question_evidence"], "questions": 4, "generated": 3,
                                        "with_generation_selected_ids": 3}


def test_api_writes_nothing_but_its_store(tmp_path, api):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    get, _ = api(root)
    for path in ("/api/model-health/current", "/api/evaluation/history", "/api/evaluation/experiments"):
        assert get(path)[0] == 200
    after = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    assert before == after


# ---------------------------------------------------------- import boundary


def test_the_dashboard_server_and_observatory_load_no_model_stack():
    code = (
        "import sys, importlib.util; from pathlib import Path; "
        "spec = importlib.util.spec_from_file_location('sd', 'scripts/serve_dashboard.py'); "
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
        "import regulus.dashboard.observatory, regulus.dashboard.health; "
        "print(sorted(x for x in ('torch', 'transformers', 'peft') if x in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT,
                         env={**__import__("os").environ, "PYTHONPATH": str(PROJECT_ROOT / "src")})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ---------------------------------------------------------- the real run


@pytest.mark.skipif(not PRODUCTION_RUN.is_dir(), reason="the production evaluation is not on this machine")
def test_the_production_run_exposes_all_51_questions_with_their_evidence():
    run = stage5.load(PRODUCTION_RUN, root=PROJECT_ROOT)
    listing = question_list(run)
    assert listing["total"] == 51 and len({r["id"] for r in listing["questions"]}) == 51
    generated = [r for r in listing["questions"] if r["generated"]]
    raw = {json.loads(line)["id"]: json.loads(line) for line in
           (PRODUCTION_RUN / "generation_full.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    for r in generated:
        detail = question_detail(run, r["id"])
        assert [s["evidence_id"] for s in detail["forensics"]["evidence"]["selected"]] == raw[r["id"]]["selected_ids"]
        assert detail["question"] and detail["forensics"]["citations"]["semantic_correctness"]["display"] == "Not measured"


# ------------------------------------------------------ model analysis view


def test_the_raw_to_final_trajectory_is_read_from_recorded_fields(tmp_path):
    from regulus.dashboard.observatory import TRAJECTORIES

    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    rows = {r["id"]: r["trajectory"] for r in question_list(run)["questions"]}
    assert rows == {"Q-1": "correct_throughout", "Q-2": "recovered_by_repair",
                    "Q-3": "no_model_call", "Q-4": "incorrect_unrepaired"}
    for qid, code in rows.items():
        t = question_detail(run, qid)["forensics"]["trajectory"]
        assert t["code"] == code and t["label"] == TRAJECTORIES[code]
    # Q-2 is the repair story: wrong raw, rewritten, right final
    t = question_detail(run, "Q-2")["forensics"]["trajectory"]
    assert (t["correct_raw"], t["repair_applied"], t["correct_final"]) == (False, True, True)
    assert question_list(run)["trajectories"] == TRAJECTORIES


def test_every_attention_item_opens_exactly_the_questions_it_counts(tmp_path):
    from regulus.dashboard.health import SECTIONS, build_attention

    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    items = [i for i in build_attention(run)["items"] if i["filter"]]
    assert {i["code"] for i in items} >= {"failed_final", "failed_raw", "retrieval_failed", "validation_failed",
                                          "citation_failed", "not_generated", "repaired", "only_repair"}
    offered = {f["key"] for f in question_list(run)["filters"] if f["available"]}
    for item in items:
        assert item["filter"] in offered, item                   # the link is a real filter
        assert item["section"] in {s.key for s in SECTIONS}
        opened = [q["id"] for q in question_list(run, filter_key=item["filter"])["questions"]]
        assert opened == item["question_ids"] and len(opened) == item["count"], item


def _three_runs(root: Path) -> dict[str, str]:
    stage5_run(root, "older_run", completed_at="2026-01-01T00:00:00+00:00", ids=("Q-1", "Q-2", "Q-3", "Q-4"))
    _rich_run(root, "newer_run", completed_at="2026-02-01T00:00:00+00:00")
    # later than both, but it records no model: it can never be the current model's evaluation
    stage5_run(root, "unrecorded_run", completed_at="2026-03-01T00:00:00+00:00",
               ids=("Q-1", "Q-2", "Q-3", "Q-4"), model=None)
    return {e.name: e.experiment_id for e in _registry(root).experiments}


def test_experiment_analysis_reports_the_freshness_engines_verdict(tmp_path):
    from regulus.dashboard.health import current_health, experiment_analysis

    root = write_project(tmp_path / "p")
    ids = _three_runs(root)
    reg = _registry(root)

    current = experiment_analysis(reg, ids["newer_run"])
    assert current["is_current"] is True and current["note"] is None
    assert current["current_evaluation"]["experiment_id"] == ids["newer_run"]
    # the same blocks, built by the same functions, as the current-model page
    home = current_health(reg)
    for block in ("sections", "attention", "failure_breakdown", "coverage", "evaluation", "benchmark", "model"):
        assert current[block] == home[block], block
    assert home["is_current"] is True and home["current_evaluation"]["experiment_id"] == ids["newer_run"]

    for name in ("older_run", "unrecorded_run"):
        other = experiment_analysis(reg, ids[name])
        assert other["is_current"] is False and other["note"], name
        assert other["current_evaluation"]["experiment_id"] == ids["newer_run"]
        assert other["evaluation"]["name"] == name                 # its own numbers, labelled as its own
    assert experiment_analysis(reg, "0" * 16) is None


def test_no_legacy_or_unrecorded_artifact_becomes_current(tmp_path):
    from regulus.dashboard.health import experiment_analysis

    root = write_project(tmp_path / "p")
    ids = _three_runs(root)
    (root / "data" / "evaluation" / "results" / "baseline_x.json").write_text(
        (Path(_answer_file(_results_dir(tmp_path)))).read_text(encoding="utf-8"), encoding="utf-8")
    reg = _registry(root)
    evaluations = [e for e in reg.experiments if e.kind == "evaluation"]
    # the population really contains a legacy file, an unrecorded run and a superseded run
    assert any(e.path.endswith("baseline_x.json") for e in evaluations)
    assert {"older_run", "unrecorded_run", "newer_run"} <= {e.name for e in evaluations}
    flagged = [e.name for e in evaluations if experiment_analysis(reg, e.experiment_id)["is_current"]]
    assert flagged == ["newer_run"]


def _results_dir(tmp_path: Path) -> Path:
    d = tmp_path / "legacy_results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_sections_split_retrieval_from_evidence_use(tmp_path):
    from regulus.dashboard.health import current_health

    root = write_project(tmp_path / "p")
    _rich_run(root)
    sections = {s["key"]: s for s in current_health(_registry(root))["sections"]}
    assert list(sections)[:4] == ["answer_quality", "retrieval", "validation_repair", "performance"]
    retrieval = sections["retrieval"]
    assert retrieval["subgroups"] == ["Found by retrieval", "Used in the answer"]
    group = {m["key"]: m["subgroup"] for m in retrieval["metrics"] + retrieval["not_measured"]}
    assert group["retrieval_ok"] == "Found by retrieval" and group["citation_ok"] == "Used in the answer"
    assert all(m["subgroup"] is None for m in sections["answer_quality"]["metrics"])


def test_the_analysis_endpoint_serves_any_evaluation_and_404s_otherwise(tmp_path):
    root = write_project(tmp_path / "p")
    ids = _three_runs(root)
    spec = importlib.util.spec_from_file_location("sd_analysis", PROJECT_ROOT / "scripts" / "serve_dashboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STATE = module.State(root, store=tmp_path / "store.json")
    module.STATE.registry.roots = ROOTS
    module.STATE.registry.refresh()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        for name, expected in (("newer_run", True), ("older_run", False)):
            with urllib.request.urlopen(f"{base}/api/evaluation/experiments/{ids[name]}/analysis", timeout=30) as r:
                assert json.loads(r.read())["is_current"] is expected
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"{base}/api/evaluation/experiments/{'0' * 16}/analysis", timeout=30)
        assert err.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


# ------------------------------------------------------------ home summary


def test_summary_cards_are_the_canonical_metrics_unchanged(tmp_path):
    from regulus.dashboard.health import SUMMARY_METRICS, build_attention, build_summary

    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    summary = build_summary(run, build_attention(run))
    assert [c["key"] for c in summary["metrics"]] == [s.key for s in SUMMARY_METRICS]
    assert 4 <= len(summary["metrics"]) <= 6
    for card in summary["metrics"]:
        metric = run.metric(card["key"])
        # value, numerator and denominator are the metric's own: nothing is recomputed
        assert (card["value"], card["numerator"], card["denominator"]) == (
            metric.value, metric.numerator, metric.denominator), card["key"]
        assert card["sample"] == f"{metric.numerator} of {metric.denominator} {card['population']}"
        assert f"{metric.numerator} of {metric.denominator}" in card["sentence"]
        # the shortfall link selects exactly the questions it counts
        if card["filter"]:
            listing = question_list(run, filter_key=card["filter"])
            assert listing["matched"] == card["filter_count"] > 0, card["key"]
    by_key = {c["key"]: c for c in summary["metrics"]}
    # validation is over generated answers, not over every question
    assert by_key["valid_final"]["denominator"] == 3 and by_key["retrieval_ok"]["denominator"] == 4


def test_summary_keeps_missing_distinct_from_zero(tmp_path):
    from regulus.dashboard.health import build_attention, build_summary

    root = write_project(tmp_path / "p")
    run = stage5.load(stage5_run(root, "basic_run"), root=root)      # no correctness verdicts recorded
    by_key = {c["key"]: c for c in build_summary(run, build_attention(run))["metrics"]}
    missing = by_key["correctness_final"]
    assert missing["measured"] is False and missing["value"] is None and missing["numerator"] is None
    assert missing["display"] == "Not measured" and missing["sample"] is None
    assert missing["sentence"] == "No measurement was recorded for this experiment."
    assert missing["filter"] is None


def test_summary_pipeline_facts_quote_the_canonical_counts(tmp_path):
    from regulus.dashboard.health import build_attention, build_summary

    root = write_project(tmp_path / "p")
    run = stage5.load(_rich_run(root), root=root)
    summary = build_summary(run, build_attention(run))
    facts = {tuple(f["keys"]): f for f in summary["pipeline"]}
    rate = run.metric("repair_rate")
    assert facts[("repair_rate",)]["text"].startswith(f"{rate.numerator} of {rate.denominator} generated answers")
    generated = run.metric("generated_count")
    assert f"{generated.numerator} of {generated.denominator} questions" in facts[("generated_count",)]["text"]
    for fact in summary["pipeline"]:
        if fact["filter"]:
            assert question_list(run, filter_key=fact["filter"])["matched"] > 0
    # timing is reported, separately, as recorded
    timing = {t["key"]: t for t in summary["timing"]}
    assert timing["e2e_latency_p50"]["value"] == run.metric("e2e_latency_p50").value
    assert "not a measure of answer quality" in summary["timing_note"]


# ------------------------------------------------------------ Stage 12 answer shape

SHAPE_RECORD = {
    "answer_shape": {"mode": "synthesis", "scope": "section", "exhaustive": False, "requested_units": ["21 CFR 820.10"],
                     "focus_terms": [], "signals": [], "rationale": "an overview of 21 CFR 820.10"},
    "evidence_plan": {"mode": "synthesis", "lead_in": [1], "context": [], "related": [],
                      "groups": [{"key": "820.10(b)", "label": "21 CFR 820.10(b)", "heading": "Applicable regulatory requirements",
                                  "kind": "requirement", "head": 2, "members": [2, 3], "items": [3], "requirement_ids": ["r1"]}]},
}


def _with_shape(d: Path, qid: str) -> None:
    path = d / "generation_full.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        if r["id"] == qid:
            r.update(SHAPE_RECORD)
            r["validation_initial"] = {**(r.get("validation_initial") or {}),
                                       "shape": {"groups": 1, "groups_covered": 1, "material_items": 2,
                                                 "material_items_covered": 2, "repeated_pairs": 0,
                                                 "codes": ["qualifier_dropped"]}}
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_question_detail_carries_the_answer_shape_only_when_recorded(tmp_path):
    root = write_project(tmp_path / "p")
    d = _rich_run(root)
    _with_shape(d, "Q-4")
    run = stage5.load(d, root=root)
    shaped = question_detail(run, "Q-4")["forensics"]["answer_shape"]
    assert shaped["shape"]["mode"] == "synthesis" and shaped["plan"]["groups"][0]["members"] == [2, 3]
    assert shaped["checks_raw"]["codes"] == ["qualifier_dropped"]
    assert question_detail(run, "Q-1")["forensics"]["answer_shape"] is None  # older records: nothing invented
