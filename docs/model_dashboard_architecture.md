# Regulus AI: Model Evaluation Dashboard Architecture

A permanent, read-only observability layer over the evaluation and training
artifacts this project already produces. It changes no model, no adapter, no
database row and no existing artifact. Its purpose is to make it hard to
fool ourselves about whether the system is improving.

## 1. Where the data already lives

Nothing is invented. Four artifact families exist today.

| Family | Location | Shape | Produced by |
|---|---|---|---|
| Stage 5 evaluation | `artifacts/stage5_stage6/<run>/stage5/` | 12 aggregate `*.json`, 3 `*.jsonl` per-question files, `stage5_summary.json`, `run_manifest.json`, `phase_*.json` markers | `scripts/run_stage5.py` |
| Legacy answer evaluation | `data/evaluation/results/**.json` with `run.model_id` | `{schema_version, run, summary, results}` | `scripts/evaluate_baseline.py` |
| Legacy retrieval evaluation | `data/evaluation/results/retrieval-*.json` | the same shape, but recall at k and per-query ranks, and no answer model | `scripts/evaluate_retrieval.py` |
| Training run | `models/qwen3-0.6b-lora/<run>/` | `training_summary.json`, `training_metrics.json`, `metadata.json`, `training_config.yaml`, `dataset_manifest.json`, `checkpoints/checkpoint-*/trainer_state.json`, `adapter/adapter_config.json` | `scripts/train_model.py` |
| Benchmarks | `data/evaluation/datasets/*.jsonl` | question sets with sha256 | hand-authored, protected |

The dashboard reads these. It never writes to them.

The only file the dashboard writes is its own registry,
`artifacts/dashboard/registry.json`, which holds names, pins and cached
identity. Artifacts stay immutable; the registry points at them.

## 2. Identity

Every number on screen is reachable from an identity. Four identities exist.

```
ModelIdentity        base_model_id, revision, adapter_id, adapter_path,
                     checkpoint, dtype, device        -> model_key
BenchmarkIdentity    benchmark_id, version, path, sha256, questions,
                     categories, protected            -> benchmark_key
EvaluationRun        evaluation_run_id, model, benchmark, config, started,
                     completed, status, artifact paths, metrics, questions
TrainingRun          training_run_id, base model, dataset identity, LoRA
                     settings, hyper-parameters, curves, checkpoints
```

`Experiment` binds them:

```
experiment_id   stable, derived from the artifact location
name            human label (registry, else derived)
model           ModelIdentity
benchmark       BenchmarkIdentity | None
evaluation_run_id / training_run_id
created_at, completed_at, status, git_revision
configuration, source_artifacts[], metric_summary
```

`experiment_id` is `sha1(kind + ":" + artifact path relative to the project
root)[:16]`, so the same directory always resolves to the same experiment
and two runs never collide.

`model_key` is `base_model_id@revision+adapter_id@checkpoint`. A base-model
evaluation and a LoRA evaluation therefore never share an identity, and two
checkpoints of one adapter never do either.

`benchmark_key` is `benchmark_id@sha256[:12]`. Two files both called
"Stage 5" with different content are different benchmarks, which is what
makes cross-experiment comparison safe.

## 3. Freshness

The dashboard resolves the **current model** from `configs/model.yaml` plus
an optional registry pin (`current_model`). With no pin the current model is
the configured base model with no adapter, which is what the production
pipeline uses today.

Each experiment then gets a status:

| Status | Meaning |
|---|---|
| `CURRENT` | complete, and its `model_key` equals the current model's |
| `HISTORICAL` | complete, but for a different model, adapter or checkpoint |
| `STALE` | complete and for the current model, but superseded by a newer complete run on the same benchmark |
| `INCOMPLETE` | artifacts present but the run did not finish, or required files are missing |
| `FAILED` | the run recorded an error |
| `UNSUPPORTED_SCHEMA` | discovered but no adapter understands it |

Rules that must hold, and are tested:

* a `HISTORICAL` result is never presented as the current model's performance;
* when no `CURRENT` evaluation exists, the Overview says so explicitly and
  offers the latest available run, labelled with its real status;
* an `INCOMPLETE` newer run never replaces the latest complete run; both are
  listed, with the incomplete one marked and its missing pieces named;
* nothing is silently substituted.

## 4. Canonical metric schema

Every metric, from any artifact family, is normalised to one record.

```json
{
  "key": "correctness_final",
  "display_name": "Final Correctness",
  "value": 0.7059,
  "numerator": 36,
  "denominator": 51,
  "unit": "ratio",
  "direction": "higher_is_better",
  "definition_key": "correctness_final",
  "source": "correctness_results.json",
  "status": "ok",
  "sample_note": "51 evaluated questions"
}
```

* `unit` is `ratio`, `count`, `seconds` or `tokens`.
* `direction` is `higher_is_better`, `lower_is_better` or `informational`.
  Comparison uses it; nothing is called an improvement because a number rose.
* `numerator` / `denominator` are populated whenever the metric is a
  proportion, so the UI can always print `36 / 51` beside `70.6%`.
* `status` is `ok`, `missing`, or `inconsistent`. The Stage 5 adapter
  recomputes each proportion from the per-question records and compares it
  with the value stored in the aggregate file; a disagreement beyond 0.5
  percentage points marks the metric `inconsistent` and the UI shows it.
  The stored value is displayed, never overwritten: a metric bug in the
  evaluator is reported, not silently corrected.

There is deliberately **no composite score**. No "AI score", no ranking, no
automatic winner.

## 5. Metric definitions

`src/regulus/dashboard/metrics.py` holds one `MetricDefinition` per key and
is the single source of truth for every tooltip:

```python
MetricDefinition(key, name, definition, calculation, direction, unit,
                 caveats, heuristic: bool, family)
```

The API serves them at `/api/metrics/definitions`; the UI renders the ⓘ
buttons from that payload only. A metric whose `heuristic` flag is set (for
example faithfulness) renders with a visible "heuristic" badge and its
caveat text. Definitions are written in `docs/model_dashboard_metrics.md`
too, generated from the same registry so the two cannot drift.

## 6. Adapters

```
adapters/stage5.py    Stage 5 run directory   -> EvaluationRun (43 metrics, 51 QuestionResults)
adapters/legacy.py    data/evaluation/results -> EvaluationRun, in two flavours:
                        answer runs    throughput, completion, human review, one answer per question
                        retrieval runs recall@k, MRR, negative controls, no answer model
adapters/training.py  model run directory     -> TrainingRun (config, curves, checkpoints, losses)
```

Each adapter declares `detect(path) -> bool` and `load(path)`. Discovery
tries them in order; an artifact no adapter claims becomes
`UNSUPPORTED_SCHEMA` rather than being skipped.

The Stage 5 adapter builds metrics from the per-question files
(`generation_full.jsonl`, `evidence_records.jsonl`,
`correctness_results.json:per_question`) so numerators and denominators are
real counts, and cross-checks them against the aggregates. Nothing is
hard-coded: removing `stage5_summary.json` changes the output.

The legacy adapter exposes only what maps cleanly (question counts,
latency percentiles computed from `results[].seconds`, token averages, and
the manual reviewer mean, which is labelled a human judgment, not a
measurement). Its benchmark key differs from Stage 5's, so the compatibility
rule blocks comparison with Stage 5 runs automatically.

## 6a. Model identity when the artifact does not record it

Two sentinels sit in `ModelIdentity.base_model_id`, and both make `recorded`
false so nothing can quietly treat them as weights:

* `unrecorded` — the artifact should have named the weights and did not.
  Stage 5 is in this position: its manifest stores the retrieval and
  generation configuration only, and `--adapter` leaves no trace. `model_key`
  is then `unrecorded`, deliberately not `...+base`, because omitting the
  adapter is not the same as saying there was none. Such a run can never be
  resolved to CURRENT and can never be compared.
* `not_applicable` — a retrieval evaluation, which legitimately has no answer
  model. Nothing is missing; there is simply nothing to name.

## 7. API

A separate read-only HTTP service, `scripts/serve_dashboard.py`, default
port 8050. It never loads the model, so it can run while the answering UI or
a training job is using the machine's memory.

```
GET /api/system/current-model
GET /api/system/health
GET /api/metrics/definitions
GET /api/evaluation/experiments
GET /api/evaluation/experiments/{id}
GET /api/evaluation/experiments/{id}/metrics
GET /api/evaluation/experiments/{id}/questions
GET /api/evaluation/experiments/{id}/questions/{question_id}
GET /api/evaluation/compare?ids=a,b
GET /api/training/runs
GET /api/training/runs/{id}
GET /api/training/runs/{id}/metrics
GET /api/training/runs/{id}/checkpoints
GET /api/models
GET /api/system/diagnostics
GET /api/experiments
GET /api/model-health/current
GET /api/model-health/current/metrics
GET /api/model-health/current/failures
GET /api/model-health/current/history
POST /api/refresh
POST /api/registry/threshold
POST /api/registry/name
POST /api/registry/pin
POST /api/registry/current-model
```

The browser never parses an artifact. Every response is the canonical
schema. Errors return `{"error": ...}` with a real status code; a missing
experiment is 404, a malformed artifact is reported as such rather than as
an empty result.

## 8. Dashboard pages

One page application, `web/dashboard.html`, vanilla JavaScript and inline
SVG, matching the project's existing stdlib-only, no-framework UI.

| Page | Answers |
|---|---|
| Model health | how good is the model we are running right now, across every dimension this evaluation measured, and what it did not measure |
| History | how has *this* model moved on *this* benchmark over time |
| Experiments | what runs exist, for which model and benchmark, with what status |
| Comparison | what changed between two runs, in percentage points, with compatibility warnings |
| Training | what happened during a training run: config, loss curves, learning rate, checkpoints, resources |
| Questions | which questions failed, filterable by 20 failure and category filters |
| Question detail | the forensic view for one question |
| Models | every distinct set of weights, what evaluated it, and the training run that produced the adapter |
| Diagnostics | artifact roots, discovery results, unsupported or incomplete artifacts, registry state, last refresh, the metric catalogue |

Raw and final are never merged. The Overview shows raw correctness and final
correctness side by side with the repair rate between them, and a line
stating how many answers are correct only because of deterministic repair.

## 9. Comparison

Two experiments compare only when their `benchmark_key` matches. Otherwise
the comparison renders with a blocking warning naming the difference.
Non-blocking warnings are raised for a different model family, different
evaluation configuration (decoding, token budget, validation behaviour,
top-k), and a different pipeline revision.

Differences are shown in percentage points for ratios and absolute units for
latency, with the direction applied to decide whether a change is an
improvement, a regression or neutral. There is no overall winner.

## 10. Question-level debugging

`QuestionResult` carries, per question, exactly the fields the Stage 5
artifacts hold: plan and detected requirements, requirement status, evidence
by tier, selected evidence with tier and protection, the raw model answer,
the validation report, the repaired answer, the expected behaviour and
terms, per-question metrics, citations, timings and the failure layer with
its reasons. Nothing is fabricated; a field absent from the artifact is
absent from the view.

## 9a. Model health

`src/regulus/dashboard/health.py` builds the page the dashboard opens on. It
answers one question - how good is the model configured right now - and is
built so it cannot answer a different one without saying so.

* **Only the current model's own evaluation is read.** With no current
  evaluation the page says the model has not been evaluated, names the
  configured model, and offers the latest run there is, labelled with its real
  status and deliberately *without* its metrics.
* **A metric the current evaluation did not measure is listed by name as not
  measured.** It is never filled in from another run. The page states its own
  coverage - "this evaluation reports 7 of the 73 metrics the system can
  measure" - and names the families that are absent.
* **Sections come from the registry**, not from a list in the frontend. A
  section declares the metric families it contains plus any explicit keys, so
  a metric added to an adapter appears without anyone editing the page.
  Retrieval and answer quality are separate sections by construction, and a
  test asserts the two never intersect.
* **No threshold is invented.** The project defines none, so a metric's state
  is descriptive - available, missing, inconsistent, informational. A
  threshold map can be set per metric in the registry store, and only then does
  a metric become good / attention / poor, with the rule quoted in the badge.
* **Attention counts come from the question records**, never from an
  aggregate, so a count and the questions behind it cannot disagree. Each item
  links into the Questions view pre-filtered.
* **Freshness is per benchmark**, so a model can hold more than one current
  evaluation. The newest leads the page and the others are named, because a
  reader who saw only one would think it was the only measurement.

`current_history()` plots one model on one benchmark. A run with a different
adapter, checkpoint or question set is not a later point on that line; those
are returned separately as "model changed" markers.

## 10a. Charts

Charts are inline SVG in the page, with no chart library. Three rules hold:

* **One axis.** Training loss and validation loss share a scale and share a
  chart; the learning rate does not, so it gets its own. There is no
  dual-axis chart anywhere.
* **Identity is never colour alone.** Every series carries a direct label at
  its last point and appears in a legend, and every chart has a table view
  beneath it.
* **The series colours are validated, not chosen by eye.** Blue, orange and
  aqua, stepped separately for the light and dark surfaces, clear the
  colour-vision-deficiency and contrast gates for all pairs in both modes.

## 11. Testing

`tests/test_dashboard.py` covers ingestion (valid, missing, incomplete,
corrupted JSON, unsupported schema, duplicate experiment), freshness
(current versus historical, incomplete not replacing complete, checkpoint
distinction), metrics (Stage 5 values, numerator and denominator,
percentages, direction metadata), comparison (compatible, incompatible,
missing metric), question detail (raw and final preserved, repair status,
evidence, failure classification), training parsing (config, curves,
checkpoints, missing metrics) and the API layer (routing, 404s, payload
shape). Fixtures are synthetic artifact trees written to `tmp_path`, plus a
read-only check against the real Stage 5 baseline when it is present.

## 12. Non-goals

* No write path to the regulatory database, which stays read-only.
* No model loading in the dashboard process.
* No modification of Stage 5 artifacts, benchmarks, adapters or weights.
* No composite quality score.
* No automatic accept or reject decision. The dashboard measures; a person
  decides.
