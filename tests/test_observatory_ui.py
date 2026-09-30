"""Phase 3 UI: the page renders canonical API data and computes no semantics.

Two kinds of test. Static checks read web/dashboard.html and pin what it must
never contain: a run id, a model name, a benchmark size, an artifact path, a
composite score. Render checks run the page's own script (unmodified) under
node with a minimal DOM (tests/dashboard_render_harness.js) against a live API
over a synthetic project, and read what each view actually shows.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from regulus.config import PROJECT_ROOT

from .current_system_fixtures import ROOTS, stage5_run, write_project
from .test_observatory import _rich_run

PAGE = (PROJECT_ROOT / "web" / "dashboard.html").read_text(encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>"):PAGE.rindex("</script>")]
HARNESS = PROJECT_ROOT / "tests" / "dashboard_render_harness.js"
NODE = shutil.which("node")


# ------------------------------------------------------------------ static


def test_the_page_hard_codes_no_run_model_or_benchmark():
    assert not re.search(r"run_\d{8}T\d{6}Z", PAGE), "a run id is hard-coded"
    assert not re.search(r"\b[0-9a-f]{16}\b", SCRIPT), "an experiment id is hard-coded"
    for literal in ("Qwen3-0.6B\"", "Qwen/Qwen3", "stage5_v1", "c1899de2", "4aad07f5", "stage5_baseline"):
        assert literal not in SCRIPT, f"{literal} is hard-coded"
    # no measured value or benchmark size baked into the page
    for literal in ("64.7", "33 / 51", "51 questions", "/ 51", "43 metrics"):
        assert literal not in SCRIPT, f"{literal} is hard-coded"


def test_the_page_reads_only_the_api_never_an_artifact():
    fetched = set(re.findall(r"api\(\s*[`\"](/[^`\"$?]*)", SCRIPT))
    assert fetched and all(p.startswith("/api/") for p in fetched), fetched
    for artifact in (".jsonl", "run_manifest", "_results.json", "stage5_summary", "latency_results"):
        assert artifact not in SCRIPT, f"the page references the artifact {artifact}"


def test_the_page_decides_no_freshness_and_computes_no_score():
    # freshness and comparability are backend decisions the page only displays
    for decision in ("pipeline_fingerprint_mismatch", "question_set_is_subset", "model_identity_unrecorded",
                     "=== \"CURRENT\" ?", "freshness.resolve"):
        assert decision not in SCRIPT
    for composite in ("overallScore", "overall_score", "healthScore", "qualityScore", "winner =", "rank("):
        assert composite not in SCRIPT


def test_missing_values_render_as_not_measured():
    assert 'const NOT_MEASURED = "Not measured";' in SCRIPT
    assert "if (!isMeasured(m)) return NOT_MEASURED;" in SCRIPT
    assert '"Not available"' not in SCRIPT


def test_the_page_script_is_valid_javascript(tmp_path):
    if not NODE:
        pytest.skip("node is not installed")
    js = tmp_path / "page.js"
    js.write_text(SCRIPT[len("<script>"):], encoding="utf-8")
    out = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ------------------------------------------------------------------ render


@pytest.fixture
def render(tmp_path):
    if not NODE:
        pytest.skip("node is not installed")
    servers = []

    def run(root: Path, *routes: str) -> dict:
        spec = importlib.util.spec_from_file_location(f"sd_ui_{len(servers)}", PROJECT_ROOT / "scripts" / "serve_dashboard.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.STATE = module.State(root, store=tmp_path / f"store_{len(servers)}.json")
        module.STATE.registry.roots = ROOTS
        module.STATE.registry.refresh()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        routes = [r.replace("{current}", _current_id(module)) for r in routes]
        out = subprocess.run([NODE, str(HARNESS), base, *routes], capture_output=True, encoding="utf-8", timeout=120)
        payload = json.loads(out.stdout or "{}")
        assert "__fatal__" not in payload, payload.get("__fatal__")
        for route, view in payload.items():
            assert not view["errors"], (route, view["errors"])
            assert "This view could not be built" not in view["text"], (route, view["text"][:300])
        key = lambda r: r.split("?")[0].split("/")[1] + ("?" + r.split("?")[1] if "?" in r else "")
        # the active primary-navigation item of each route, for navigation tests
        run.navs = {key(r): v.get("nav") for r, v in payload.items()}
        return {key(r): v["text"] for r, v in payload.items()}

    run.navs = {}
    yield run
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def _current_id(module) -> str:
    evals = module.STATE.registry.current_model()["current_evaluations"]
    return evals[0]["experiment_id"] if evals else "none"


def test_the_current_model_view_renders_from_the_api(tmp_path, render):
    root = write_project(tmp_path / "p")
    _rich_run(root, "alpha_run")
    text = render(root, "#/overview")["overview"]
    assert "alpha_run" in text and "CURRENT" in text
    assert "Qwen/Qwen3-0.6B" in text                              # from the API, not the page
    assert "Not measured" in text and "Measured" in text
    assert "Freshness engine: pipeline match" in text


def test_a_different_project_renders_its_own_run_without_code_changes(tmp_path, render):
    root = write_project(tmp_path / "p", model_id="Other/model")
    stage5_run(root, "beta_run")
    text = render(root, "#/overview")["overview"]
    assert "beta_run" in text and "Other/model" in text and "alpha_run" not in text


def test_an_unevaluated_system_says_so(tmp_path, render):
    root = write_project(tmp_path / "p")
    stage5_run(root, "unrecorded_run", model=None)
    text = render(root, "#/overview")["overview"]
    assert "has not been evaluated" in text
    assert "unrecorded_run" in text                               # named, with its real status, no metrics


def test_the_question_list_is_filtered_by_the_server(tmp_path, render):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    views = render(root, "#/questions/{current}?filter=incorrect", "#/questions/{current}")
    filtered, everything = (v for k, v in sorted(views.items(), key=lambda kv: "filter" not in kv[0]))
    assert "2 of 4 questions" in filtered and "Q-3" in filtered and "Q-4" in filtered and "Q-1 " not in filtered
    assert "4 of 4 questions" in everything
    assert "Incorrect (final) 2" in everything and "Retrieval issue 1" in everything


def test_question_detail_shows_question_local_evidence_and_not_measured(tmp_path, render):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    text = render(root, "#/question/{current}/Q-1")["question"]
    assert "question-local evidence registry ids" in text
    assert "[1]" in text and "e1" in text and "e2" in text and "21 CFR 820.10(b)(1)" in text
    assert "Semantic citation correctness Not measured" in text
    assert "Not provided by the benchmark" in text


def test_a_question_answered_without_the_model_shows_no_evidence(tmp_path, render):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    text = render(root, "#/question/{current}/Q-3")["question"]
    assert "no model call, so no evidence was given to a model" in text


def test_history_renders_one_run_honestly_and_a_line_with_several(tmp_path, render):
    root = write_project(tmp_path / "p")
    stage5_run(root, "first", completed_at="2026-01-01T00:00:00+00:00")
    assert "History unavailable: only one compatible evaluation." in render(root, "#/history")["history"]
    stage5_run(root, "second", completed_at="2026-02-01T00:00:00+00:00")
    text = render(root, "#/history")["history"]
    assert "History unavailable" not in text and "current line" in text and "comparable" in text


def test_comparison_renders_compatible_and_blocked_runs(tmp_path, render):
    root = write_project(tmp_path / "p")
    stage5_run(root, "a", completed_at="2026-01-01T00:00:00+00:00")
    stage5_run(root, "b", completed_at="2026-02-01T00:00:00+00:00")
    stage5_run(root, "other_bench", bench_name="other", ids=("T-1",))
    from regulus.dashboard.registry import Registry
    reg = Registry(root, roots=ROOTS, store=tmp_path / "probe.json")
    ids = {e.name: e.experiment_id for e in reg.experiments}
    views = render(root, f"#/compare?ids={ids['b']},{ids['a']},{ids['other_bench']}")
    text = next(iter(views.values()))
    assert "reference" in text and "comparable" in text and "not comparable" in text
    assert "not directly comparable (benchmark_mismatch)" in text
    assert "pp vs reference" in text
    # "winner" and "score" may only ever appear as denials ("no winner or overall score is computed")
    lowered = text.lower()
    assert lowered.count("winner") == len(re.findall(r"\bno (?:overall )?winner", lowered)) >= 1
    assert lowered.count("score") == len(re.findall(r"no (?:overall )?winner,? (?:or overall )?score", lowered))


def test_metric_definitions_render_with_availability(tmp_path, render):
    root = write_project(tmp_path / "p")
    stage5_run(root, "a")
    text = render(root, "#/metrics")["metrics"]
    assert "Recall@1" in text and "Composite Correctness (final)" in text
    assert "Not measured" in text and "training runs only" in text


# ------------------------------------------------------ model analysis view


def _ids(root: Path, tmp_path: Path) -> dict[str, str]:
    from regulus.dashboard.registry import Registry
    reg = Registry(root, roots=ROOTS, store=tmp_path / "probe_ids.json")
    return {e.name: e.experiment_id for e in reg.experiments}


def test_home_is_a_short_plain_english_summary_of_the_current_model(tmp_path, render):
    from .current_system_fixtures import REVISION
    from .test_observatory import _three_runs

    root = write_project(tmp_path / "p")
    ids = _three_runs(root)
    views = render(root, "#/analysis", "#/")
    text = views["analysis"]
    assert views[""] == text                                      # the dashboard opens on it
    assert render.navs["analysis"] == ["Model analysis"]
    # who, first: the model and the evaluation, in plain words
    assert text.startswith("Current model Qwen3-0.6B Qwen · base model, no fine-tuning adapter")
    assert "Current evaluation unit_bench 4 questions" in text
    # four independent measurements: percentage first, the canonical counts under it
    for card in ("Correct answers i 50.0% 2 of 4 questions",
                 "Validation i 100% 3 of 3 generated answers",
                 "Citations i 66.7% 2 of 3 generated answers",
                 "Retrieval i 75.0% 3 of 4 questions"):
        assert card in text, card
    assert "2 of 4 questions were marked correct in the final answer." in text
    for heading in ("How the model performed", "What needs attention", "Answer pipeline", "Response time",
                    "Question analysis"):
        assert heading in text, heading
    assert "Median response time" in text and "95th percentile" in text
    # the summary is not the database: no identifiers, hashes, enums or internals
    for technical in (REVISION, ids["newer_run"], "newer_run", "sha256", "fingerprint", "Freshness", "CURRENT",
                      "stage5/v1", "artifacts/", "HEURISTIC", "Qwen/Qwen3-0.6B@"):
        assert technical not in text, technical
    assert len(text) < 3000, len(text)


def test_experiment_details_hold_the_full_record(tmp_path, render):
    from .current_system_fixtures import REVISION
    from .test_observatory import _three_runs

    root = write_project(tmp_path / "p")
    ids = _three_runs(root)
    views = render(root, "#/experiment/{current}", "#/overview")
    text = views["experiment"]
    assert render.navs["experiment"] == ["Model analysis"]      # the current experiment belongs to home
    assert "Experiment details" in text and "Current model" in text and "Current experiment" in text
    assert "Qwen/Qwen3-0.6B" in text and f"Revision {REVISION}" in text
    assert "Adapter None" in text and "Checkpoint None" in text
    assert ids["newer_run"] in text and "newer_run" in text and "CURRENT" in text
    assert "Historical experiment" not in text
    # the measurement groups, in order, then attention and the questions
    order = ["Answer quality", "Retrieval and evidence", "Validation and repair", "Performance",
             "What needs attention", "Question analysis"]
    heads = [text.index(f"{title} ", text.index("Metric definitions →")) for title in order]
    assert heads == sorted(heads), heads
    assert "Found by retrieval" in text and "Used in the answer" in text and "runtime-dependent" in text
    assert "4 of 4 questions" in text                             # the embedded, server-filtered table
    assert "Experiment details" in views["overview"]              # the Phase 3 route shows the full record


def test_the_default_view_never_mixes_in_other_experiments(tmp_path, render):
    from .test_observatory import _three_runs

    root = write_project(tmp_path / "p")
    _three_runs(root)
    text = render(root, "#/analysis")["analysis"]
    # a superseded run and a later run with no recorded model are both absent;
    # the four cards are the current run's own numbers (older_run has no correctness at all)
    assert "older_run" not in text and "unrecorded_run" not in text
    assert "Correct answers i 50.0% 2 of 4 questions" in text


def test_home_says_not_measured_for_a_missing_measurement(tmp_path, render):
    root = write_project(tmp_path / "p")
    stage5_run(root, "basic_run")                                  # records no correctness verdicts
    text = render(root, "#/analysis")["analysis"]
    assert "Correct answers i Not measured No measurement was recorded for this experiment." in text
    assert "Correct answers i 0%" not in text and "0 of 0" not in text
    assert "Validation i 100% 3 of 3 generated answers" in text


def test_zero_stays_zero_and_missing_says_not_measured(tmp_path, render):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    text = render(root, "#/experiment/{current}")["experiment"]
    # measured zero: a value and its counts
    assert re.search(r"Hallucination Rate \(final\) i 0% 0 / 3", text), text[:400]
    assert re.search(r"False Refusals i 0 0 / 4", text)
    # present in the run but unmeasurable here, and defined but never produced
    assert re.search(r"Refusal Correctness i Not measured", text)
    assert re.search(r"Recall@1 i Not measured", text)
    assert "0% Not measured" not in text and "Not measured 0 /" not in text


def test_attention_links_to_exactly_the_counted_questions(tmp_path, render):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    views = render(root, "#/analysis", "#/experiment/{current}", "#/questions/{current}?filter=incorrect",
                   "#/questions/{current}?filter=no_model_answer")
    home, details = views["analysis"], views["experiment"]
    assert "What needs attention" in home
    assert "2 of 4 questions not marked correct in the final answer" in home
    assert "1 of 4 questions whose retrieval check failed" in home
    # the details page lists every observation, the home page the first few
    assert "1 of 4 questions answered without a model call" in details
    assert "questions answered without a model call" not in home
    assert "2 of 4 questions" in views["questions?filter=incorrect"]
    no_model = views["questions?filter=no_model_answer"]
    assert "1 of 4 questions" in no_model and "Q-3" in no_model and "Q-1 " not in no_model


def test_a_historical_experiment_is_available_but_labelled(tmp_path, render):
    from .test_observatory import _three_runs

    root = write_project(tmp_path / "p")
    ids = _three_runs(root)
    old = render(root, f"#/experiment/{ids['older_run']}")["experiment"]
    assert render.navs["experiment"] == ["Experiments"]
    assert "Historical experiment (STALE)" in old and "Go to the current model's analysis (newer_run)" in old
    assert "superseded" in old and "The full record of evaluation older_run" in old
    unrecorded = render(root, f"#/experiment/{ids['unrecorded_run']}")["experiment"]
    assert "Historical experiment" in unrecorded and "Current experiment" not in unrecorded
    current = render(root, f"#/experiment/{ids['newer_run']}")["experiment"]
    assert render.navs["experiment"] == ["Model analysis"]
    assert "Historical experiment" not in current and "Current experiment" in current


def test_question_drill_down_shows_the_raw_to_final_path(tmp_path, render):
    root = write_project(tmp_path / "p")
    _rich_run(root)
    q2 = render(root, "#/question/{current}/Q-2")["question"]
    assert render.navs["question"] == ["Questions"]
    assert "Not marked correct before repair; marked correct after repair" in q2
    assert "3 · Raw answer not marked correct" in q2
    assert "4 · Repair applied extractive_replacement" in q2
    assert "5 · Final answer marked correct" in q2
    q3 = render(root, "#/question/{current}/Q-3")["question"]
    assert "No model call: the pipeline answered without the model" in q3
    assert "2 · Evidence given none" in q3


def test_navigation_groups_history_compare_and_diagnostics(tmp_path, render):
    from .test_observatory import _three_runs

    root = write_project(tmp_path / "p")
    ids = _three_runs(root)
    expected = {
        "#/experiments": "Experiments", "#/history": "Experiments", "#/models": "Experiments",
        f"#/compare?ids={ids['newer_run']},{ids['older_run']}": "Experiments",
        "#/training": "Training", "#/diagnostics": "Diagnostics", "#/review": "Diagnostics",
        "#/metrics": "Definitions", "#/questions/{current}": "Questions",
    }
    views = render(root, *expected)
    for route, tab in expected.items():
        key = route.replace("{current}", ids["newer_run"])
        key = key.split("?")[0].split("/")[1] + ("?" + key.split("?")[1] if "?" in key else "")
        assert render.navs[key] == [tab], (route, render.navs[key])
    listing = views["experiments"]
    assert "All experiments" in listing and "older_run" in listing and "unrecorded_run" in listing
    compared = views[f"compare?ids={ids['newer_run']},{ids['older_run']}"]
    assert "reference" in compared and "comparable" in compared


def test_question_detail_shows_the_answer_shape_when_recorded(tmp_path, render):
    from .test_observatory import _with_shape

    root = write_project(tmp_path / "p")
    d = _rich_run(root)
    _with_shape(d, "Q-4")
    shaped = render(root, "#/question/{current}/Q-4")["question"]
    assert "Answer shape" in shaped and "synthesis" in shaped and "an overview of 21 CFR 820.10" in shaped
    assert "1 of 1 represented" in shaped and "qualifier_dropped" in shaped and "[2] [3]" in shaped
    assert "Answer shape" not in render(root, "#/question/{current}/Q-1")["question"]
