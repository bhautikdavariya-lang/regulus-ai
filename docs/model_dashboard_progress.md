# Model Dashboard Progress

## Status

COMPLETE

Phases A through I are implemented, validated against the repository's real
artifacts, and covered by tests. The dashboard is a permanent part of the
project, not a Stage 5 viewer: it discovers whatever evaluation and training
artifacts exist, and a new run appears without a code change.

It is read-only. No model was loaded, no database connection was opened, no
training was run, and no existing artifact was modified.

## How to run it

```bash
python scripts/serve_dashboard.py            # then open http://127.0.0.1:8050
python scripts/serve_dashboard.py --port 9000 --host 127.0.0.1
python scripts/generate_metric_docs.py       # regenerate docs/model_dashboard_metrics.md
python scripts/generate_metric_docs.py --check
python -m pytest tests/test_dashboard_stage5_adapter.py tests/test_dashboard_adapters.py tests/test_dashboard_registry.py
```

The server is a separate application from `scripts/serve_ui.py`: a different
port, a different page, no shared state, and no model in the process, so it
can run beside the answering UI or beside a training job.

## Final report

### 1. Every number carries its identity

No figure is rendered without its provenance. A metric card shows the value,
the numerator and denominator behind it, the direction, the source file it
came from, and its status; the card sits inside a run whose header names the
model, the benchmark and its content hash, the run id, the completion
timestamp, the configuration and the exact list of source files read. The
`/api/.../metrics` payload carries the same fields, so the page cannot
display a number it does not have provenance for.

### 2. Freshness is resolved, and a historical number is never shown as current

Each run is resolved to `CURRENT`, `HISTORICAL`, `STALE`, `INCOMPLETE`,
`FAILED` or `UNSUPPORTED_SCHEMA`, with a written reason attached to every
one. The rules that are tested: the newest complete run of the current model
on a benchmark is CURRENT and older ones are STALE; a run of a different
model or adapter is HISTORICAL; an incomplete newer run never displaces a
complete one; a training run is never CURRENT; and a run whose model
identity was never recorded can never be CURRENT however recent it is. When
no CURRENT evaluation exists, the Overview says so in a banner instead of
quietly showing the newest thing it has.

### 3. It is a separate application from the answering UI

New page (`web/dashboard.html`), new server (`scripts/serve_dashboard.py`),
default port 8050. `scripts/serve_ui.py`, the pipeline, the retriever, the
generator and the validator were not touched.

### 4. No composite score, no ranking, no automatic winner

There is no "AI score" anywhere. Comparison lays two runs side by side,
counts how many metrics improved, regressed, stayed put or could not be
compared, and states in the payload and on the page that no overall winner
is computed. A test asserts the word does not appear in the comparison
result.

### 5. Training metrics are a separate family and never read as accuracy

Training runs have their own page, their own `TrainingRun` schema and their
own metric family, whose caveats say that a lower loss can equally mean
memorisation or a narrower answer style. The training page opens with a
banner saying so. Loss and accuracy are never differenced against each
other, and a training run cannot be selected for an evaluation comparison.

### 6. Direction is declared, and ratio deltas are percentage points

Every metric declares `higher_is_better`, `lower_is_better` or
`informational` in the registry, and the comparison layer consults that
declaration before calling anything an improvement. A rise in
`failed_count` is a regression, and a test asserts it. Ratios are
differenced in percentage points, never as percent change.

### 7. Per-question table and a forensic detail page

The Questions view is searchable and filters by category, failure layer and
ten outcome filters (raw incorrect, final incorrect, repaired, correct only
after repair, unsupported content, truncated, not generated, false refusal,
citation problem). Each row opens a detail page showing the plan, the
detected and expected requirements, coverage, evidence by tier, the selected
evidence, the raw answer with its validator report, the repair kind, the
final answer with its validator report, the controlled exact-evidence answer,
the sentence-faithfulness classification for both stages, the citations, the
timings and tokens, and everything else the artifact recorded.

### 8. Raw and final are never merged

They are separate fields in `QuestionResult`, separate metrics
(`valid_raw`/`valid_final`, `correctness_raw`/`correctness_final`,
`faithfulness_raw`/`faithfulness_final`), separate columns in the question
table, separate panels in the detail view, and separate sections in the
comparison's per-question movement list. `correct_only_after_repair` is
shown beside them as the honest size of the gap, with a line saying that gap
is the pipeline and not the model. The legacy runs had no repair layer, so
their `answer_final` is left null rather than duplicated from the raw answer.

### 9. Failure analysis by layer and category

The Stage 5 adapter carries `failure_analysis.json` into `failure_summary`:
counts by layer, counts by layer and category, the individual failures with
their reasons, and the soft failures. Both the run page and the Questions
page draw the layer breakdown, and each question shows its own layer and the
reasons it was marked a failure.

### 10. One metric registry drives the tooltips and the document

`src/regulus/dashboard/metrics.py` holds 73 `MetricDefinition` records
across 12 families. Each has a definition, a calculation, a direction, a
unit, a caveat naming what it does not prove, a heuristic flag and its source
artifact. The API serves them at `/api/metrics/definitions`, the ⓘ buttons
render from that payload alone, and `docs/model_dashboard_metrics.md` is
generated from the same records, so the three cannot drift. An adapter that
emits an undefined metric key raises rather than reaching the UI.

### 11. The registry is a JSON file, and it is the only thing written

`artifacts/dashboard/registry.json` holds the names and pins a person sets,
the optional current-model pin, and a cache of the last scan. The regulatory
PostgreSQL database is never contacted. A test snapshots every file in a
project tree, builds a registry, and asserts the registry file is the only
one created and that no artifact's size or modification time changed.

### 12. Discovery is generic

Three configured roots (`artifacts/*/*/*`, `models/qwen3-0.6b-lora/*`,
`data/evaluation/results/**/*.json`) are walked and every candidate is
offered to each adapter's `detect`. No run identifier appears anywhere in the
code: adding a directory makes it appear, and a test adds one mid-run to
prove it. Anything no adapter claims is listed as UNSUPPORTED_SCHEMA with its
path rather than silently skipped, and an adapter that throws is recorded as
an error without stopping the scan.

### 13. Numerators and denominators are visible

Every proportion is recomputed from the per-question records and shown as
`36 / 51` beside `70.6%`. The recomputed value is cross-checked against the
aggregate the evaluator stored; a disagreement beyond half a percentage
point marks the metric `inconsistent`, attaches a note naming both numbers,
and raises a run-level problem. The stored value is still what is displayed —
a bug in the evaluator is reported, never silently corrected.

### 14. Benchmark and model identity are content-addressed

`benchmark_key` is `benchmark_id@sha256[:12]`, so two files with the same
name and different content are different benchmarks and comparison between
them is blocked. `model_key` is
`base_model_id@revision+adapter_id@checkpoint`. Two sentinels exist for runs
that name no weights: `unrecorded` (the artifact should have said and did
not) and `not_applicable` (a retrieval-only run, which has no answer model).
Neither is ever rendered as `+base`, because omitting an adapter is not the
same as saying there was none.

### 15. Model registry and training-to-evaluation traceability

The Models page lists every distinct set of weights, the evaluations that
measured it and the training runs that used it, and joins an adapter back to
the training run that produced it — with a line stating that the training
numbers and the evaluation numbers are different kinds of measurement and are
never differenced. The four legacy runs that used a LoRA adapter record its
name, checkpoint and dataset hash, and that is what makes the join possible.

### 16. A clean API layer; the browser parses no artifact

Fifteen endpoints serve the canonical schemas only. The page never opens an
artifact file. Missing things are 404 with a message, bad input is 400, and a
malformed artifact is reported as a diagnostic rather than as an empty
result. `/api/system/health` states in its payload that the process loads no
model, opens no database connection, and writes one file.

### 17. Validated against the real artifacts, with nothing hard-coded

The Stage 5 baseline reproduces every target from the brief — retrieval_ok
0.9608 (49/51), valid_raw 0.7609 (35/46), correctness 0.5686 raw and 0.7059
final, faithfulness 0.5000 (49/98) raw and 0.5413 final, hallucination
0.2609 → 0.1522, citation_ok 0.9130, exact-tier citation 0.9365 (59/63),
refusal correctness 0.8889 (8/9), domain leak 0.2500 (1/4), repair 0.2391
(11/46) with 8 of 11 succeeding, latency p50/p95 40.788/138.345 s generation
and 41.628/139.012 s end to end, failure layers
`{none 35, generation 9, generation_context 4, retrieval 2, domain_boundary 1}` —
with no expected number written into the adapter or the tests, and zero
`inconsistent` metrics. The full table is below.

## What was discovered in this repository

| | |
|---|---|
| Experiments | 44 |
| Evaluations | 40 — 3 Stage 5, 13 legacy answer runs, 24 legacy retrieval runs |
| Training runs | 4 |
| Statuses | 1 CURRENT, 8 STALE, 30 HISTORICAL, 3 COMPLETE (training), 1 INCOMPLETE, 1 FAILED |
| Unsupported artifacts | 1 — `data/evaluation/results/stage14_v1/safety_baseline.json`, a safety counter file, not an evaluation |
| Load errors | 0 |
| Scan time | about 0.4 s warm, 1.4 s cold |
| Metric definitions | 73 across 12 families |

Two findings worth stating plainly:

* **The Stage 5 baseline cannot be called a measurement of the current
  model**, because Stage 5 does not record which weights it evaluated. It is
  shown as HISTORICAL with that reason, and comparison involving it is
  blocked.
* **`stage14_v1` is reported as FAILED.** It wrote no summary, no metrics and
  no checkpoint, and its logs were renamed `train.stalled.log` and
  `chain.stalled.log`. The dashboard keeps it visible rather than hiding an
  unfinished run.

## Files

| File | Lines | What |
|---|---|---|
| `src/regulus/dashboard/schemas.py` | 383 | canonical schemas and identity |
| `src/regulus/dashboard/metrics.py` | 792 | the 73-entry metric registry |
| `src/regulus/dashboard/registry.py` | 564 | discovery, freshness, the JSON store |
| `src/regulus/dashboard/compare.py` | 279 | comparison rules and refusals |
| `src/regulus/dashboard/adapters/stage5.py` | 921 | Stage 5 run directories |
| `src/regulus/dashboard/adapters/legacy.py` | 384 | legacy answer and retrieval runs |
| `src/regulus/dashboard/adapters/training.py` | 356 | LoRA training runs |
| `scripts/serve_dashboard.py` | 376 | the read-only API and page server |
| `scripts/generate_metric_docs.py` | 135 | generates the metric reference |
| `web/dashboard.html` | 1171 | the seven-view page |
| `tests/test_dashboard_stage5_adapter.py` | 411 | 24 tests |
| `tests/test_dashboard_adapters.py` | 378 | 19 tests |
| `tests/test_dashboard_registry.py` | 486 | 37 tests |
| `docs/model_dashboard_architecture.md` | 293 | the design |
| `docs/model_dashboard_metrics.md` | 1194 | generated metric reference |
| `README.md` | — | entry 20 |

## Tests run

| Command | Result | Duration |
|---|---|---|
| `pytest tests/test_dashboard_stage5_adapter.py tests/test_dashboard_adapters.py tests/test_dashboard_registry.py -q` | **80 passed** | 3.6 s |
| `pytest -q` (the whole fast suite) | **600 passed, 26 deselected** | 22.1 s |
| `python -m compileall -q src/regulus/dashboard scripts/serve_dashboard.py` | pass | under 2 s |
| `node --check` on the page's script | pass | instant |
| Browser-renderer harness (scratchpad): every view rendered against the live API through a DOM shim | **17 views, 13 content assertions, 5 chart assertions — all pass** | about 3 s |
| Live API check: 15 endpoints, the page, four 404 cases, one 400 case, `POST /api/refresh` | all as expected | about 5 s |
| `python scripts/generate_metric_docs.py --check` | up to date | instant |

The suite was 520 passed before this work; 520 + 80 = 600. Nothing regressed.

### Stage 5 validation table

Every value produced by the adapter from the artifacts, with zero
`inconsistent` metrics:

| Metric | Value | Counts |
|---|---|---|
| retrieval_ok | 0.9608 | 49 / 51 |
| requirement_recall | 1.0000 | 62 / 62 |
| question_recall | 1.0000 | 35 / 35 |
| coverage_ok | 0.9804 | 50 / 51 |
| coverage_missing_ok | 1.0000 | 6 / 6 |
| selection_ok | 0.9804 | 50 / 51 |
| protected_preserved | 1.0000 | 35 / 35 |
| evidence_deterministic | 1.0000 | 51 / 51 |
| valid_raw | 0.7609 | 35 / 46 |
| valid_final | 0.9348 | 43 / 46 |
| valid_raw_controlled | 0.8333 | 30 / 36 |
| correctness_raw | 0.5686 | 29 / 51 |
| correctness_final | 0.7059 | 36 / 51 |
| correct_only_after_repair | 7 | 7 / 51 |
| faithfulness_raw | 0.5000 | 49 / 98 |
| unsupported_sentences_raw | 27 | 27 / 98 |
| faithfulness_final | 0.5413 | 59 / 109 |
| unsupported_sentences_final | 13 | 13 / 109 |
| hallucination_raw | 0.2609 | 12 / 46 |
| hallucination_final | 0.1522 | 7 / 46 |
| citation_ok | 0.9130 | 42 / 46 |
| exact_source_citation | 0.9365 | 59 / 63 |
| refusal_correct | 0.8889 | 8 / 9 |
| false_refusal_count / false_answer_count | 1 / 1 | of 42 and 9 |
| domain_leak_rate | 0.2500 | 1 / 4 |
| multi_provision_accuracy | 1.0000 | 5 / 5 |
| range_accuracy | 1.0000 | 6 / 6 |
| partial_behaviour_ok | 1.0000 | 6 / 6 |
| repair_rate / repair_success | 0.2391 / 0.7273 | 11 / 46 and 8 / 11 |
| truncated_count / degenerate_count | 2 / 1 | of 46 |
| generation latency p50 / p95 | 40.788 s / 138.345 s | converted from ms |
| end-to-end latency p50 / p95 | 41.628 s / 139.012 s | converted from ms |
| run_duration | not recorded | status `missing` |

## Tests NOT run

* the `slow` (6) and `integration` (21) marks: they load the full model or
  need the live PostgreSQL database, and neither is needed to verify a
  read-only artifact reader;
* any Stage 5 evaluation, Stage 6 or other training, or model inference;
* a real browser. No browser automation is available on this machine and
  none was installed. Instead every view was rendered against the live API
  through a minimal DOM shim, which catches a renderer crashing on real data
  but not a visual layout problem. The page has not been looked at in a
  browser.

## Known issues and things the artifacts do not record

These are gaps in the existing artifacts, **documented rather than patched
over**. Changing the evaluators was out of scope and would alter runs that
have already happened.

1. **Stage 5 does not record its model.** `run_manifest.json` stores the
   retrieval and generation configuration only, and `scripts/run_stage5.py
   --adapter` leaves no trace. The "Base Qwen3-0.6B" line in
   `STAGE5_FINAL_REPORT.md` is a hard-coded string in the report template,
   not a measurement, so it is not parsed. **Recommended fix, not done:**
   write the model id, revision, adapter path, dtype and device into
   `run_manifest.json`. Until then no Stage 5 run can be CURRENT or compared.
2. **Stage 5 records no start time**, so `run_duration` is reported missing
   rather than estimated from file modification times, and no run records a
   git revision, so pipeline-revision warnings cannot be raised.
3. **Stage 5 persists no evidence text**, only identifiers and per-tier
   counts, so the question detail view can show which evidence was retrieved,
   selected or dropped but not what it said.
4. **A Stage 5 manifest reflects the last invocation, not the run.** The
   baseline's says `skip_generation: true` because the report was rebuilt
   into the same directory. Completeness is therefore decided from the phase
   markers and the record counts, and the contradiction is raised as a
   problem.
5. **Legacy runs predate the repair layer**, so they have one answer per
   question. `answer_final` is left null rather than duplicated, and the run
   carries a problem saying its numbers are throughput and human judgment,
   not machine-checked quality.
6. **Manual reviewer scores are on an unlabelled scale.** They were briefly
   modelled as a ratio, which would have rendered a mean of 1.074 as
   "107.4%"; a test caught it. They now use a `score` unit that is never
   rendered as a percentage, and they carry a heuristic badge and a caveat
   that they must not be compared across reviewers.
7. **`configs/model.yaml` pins no revision**, while the legacy runs recorded
   one. Rather than declaring every historical run incomparable, the
   current-model match is made on base model and adapter, and the CURRENT
   run's status reason states that the revision is assumed identical but not
   proven.
8. **Two Stage 5 retrieval failures (S5-090, S5-091)** remain a genuine
   Stage 1 parser limitation, deliberately unfixed and surfaced rather than
   hidden.
9. `STAGE5_FINAL_REPORT.md` and `stage5_training_plan.json` are present but
   intentionally not consumed: one is prose rendered from the same data, the
   other is a Stage 6 planning artifact rather than an evaluation result.

## Constraints honoured

* The PostgreSQL regulatory database is read-only and was never contacted by
  any dashboard code.
* No regulatory data, model weight, adapter or existing evaluation artifact
  was modified. A test asserts the artifacts are byte-identical after a scan.
* No training was run. Stage 6 training remains unauthorised and its finetune
  config is still deliberately unwritten.
* No model is loaded in the dashboard process.
* The answering system is untouched and still works; the dashboard is a
  separate application on its own port.
* No composite score, no ranking, no automatic winner, no automatic accept or
  reject. The dashboard measures; a person decides.

## Model health redesign

The dashboard's default experience was rebuilt around the current model
rather than the artifact list. `src/regulus/dashboard/health.py` derives the
page from the registry; `web/dashboard.html` renders it; the navigation now
leads with Model health, Questions and History.

What this repository's data makes the page say, which is the point of the
redesign: **the configured model has a current evaluation, and that
evaluation measures 7 of the 73 things the system can measure.** Correctness,
faithfulness, citations, retrieval, evidence, behaviour, repair and human
review are all absent from it. Those sections read "not measured" and name
what would be there. The Stage 5 run that holds those 43 metrics is
HISTORICAL, because Stage 5 never recorded which weights it evaluated, so not
one of its numbers is allowed onto the health page.

That is an uncomfortable headline and it is the correct one. The fix is to
run Stage 5 against the configured model and have the runner record its model
identity; the dashboard's job was only to stop the gap being invisible.

## Acceptance benchmark integration — Phase A complete

`Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx` is now readable as a
first-class object: `src/regulus/evaluation/acceptance_benchmark.py`. Phase A
is ingestion and schema only. Nothing has been run against it, nothing has
been trained, and the workbook is opened read-only and never written to.

### What it is

A contractual acceptance gate, not a question set. The workbook's own words:
"The platform is not accepted, and final payment is not released, until it
passes every gate in Section 4 on a live run of all 300 questions."

| | |
|---|---|
| Identity | `regulus_acceptance_rev02@c009d5f9c649` (sha256 of the workbook) |
| Questions | 300, unique ids, 23 domains, 8 question types |
| Sheets | Question Bank, Instructions & Gates, Scoring Rubric, Results Summary |
| Gates | G1 ≥ 99% citation accuracy · **G2 = 0 fabricated** · **G3 = 100% negative controls** · G4 ≥ 95% substantive · G5 ≥ 90% completeness · G6 ≥ 98% scope · G7 ≥ 95% ISO concordance |
| Absolute gates | G2 and G3. "A single failure on either is a failed acceptance test regardless of every other score." |

Composition, cross-checked against the workbook's own Results Summary and
matching it exactly: Direct Lookup 188, Distinction 23, Negative Control 22,
Cross-Reference 20, Application 20, Scope/Boundary 15, Temporal/Version 11,
Abstention 1. Part 820 domain 42 rows; G7 scope 51 rows.

### The finding that gates everything else

**The answer key is unverified.** Column K reads empty on all 300 rows, and
the workbook requires it to be marked Y by an SME — against current eCFR
text, the FDA source documents and a controlled copy of ISO 13485:2016 —
*before* the vendor is given the test. Its own Results Summary says
"WARNING — key not fully verified", and Section 2 says: "An unverified key
invalidates the entire result."

The loader enforces this rather than noting it. `key_verified` is preserved
per row, and `accepted_expectation` returns `None` until the row is marked Y,
so a draft key cannot be mistaken for ground truth by anything downstream.
The draft remains readable as `expected_citation_draft`.

### Behavioural classes preserved

The eight question types drive behaviour and are constants, not free text.
Negative controls (22) must be answered by establishing that something does
not exist; temporal/version rows (11) ask about sections reserved on
2 February 2026 and must be answered from the current snapshot, not from
remembered Quality System Regulation text.

Column H turned out to have **three** states, not two, and the distinction is
scored: `—` means the row is outside G7 and column Q stays blank (249 rows);
`None` means the correct answer names *no* ISO clause, and naming one scores
Q=0 *and* triggers the fabricated-citation column (8 rows); anything else is
the clause key itself (43 rows). G7 scope follows column H, not the domain —
42 Part 820 rows plus 9 cross-domain rows.

Column H is also an expression rather than a single number: it can list
several clauses, name a range ("1 through 8 (entire standard)", 5 rows) and
reference ISO 9000 as well as ISO 13485 (2 rows). The raw string stays
authoritative; the parsed clause list is a convenience, and the standard's
own number is not read as a clause number.

### Training leakage: none

All 300 questions were checked against every training dataset on disk —
20 files, 70,194 text fields. **Zero benchmark questions appear in training
data.** The benchmark is held out, as an acceptance test must be. Registering
the workbook as a protected benchmark in `regulus.training.config` so it
stays that way is a later step: the exclusion machinery expects JSONL paths
and would need to understand this format.

### A dependency decision

The loader reads .xlsx with the standard library — `zipfile` plus
`xml.etree` — rather than adding openpyxl. This keeps the benchmark readable
from the dashboard process, whose guarantee is that it loads no model. That
guarantee turned out to be at risk for a different reason: importing
`regulus.evaluation` pulled in the inference stack and therefore torch
(about 18 seconds and several hundred megabytes). `regulus/evaluation/__init__.py`
is now lazy (PEP 562), so `from regulus.evaluation import run_evaluation`
behaves exactly as before and pays that cost only when used, while the
benchmark loader imports in 0.26 s with torch absent. A test asserts it.

### Not done, deliberately

No runner, no scoring, no dashboard integration, no training. The dashboard
work described in the brief's section 19 is explicitly deferred until the
evaluator is correct.

## Acceptance benchmark — phase status

```text
Phase A — COMPLETE
Phase B — COMPLETE (automated pass); SME sign-off outstanding
SME review infrastructure — COMPLETE, awaiting a reviewer
300-question scoring — BLOCKED (enforced in the execution path)
Stage 6 training — BLOCKED (enforced in the execution path)
```

Nothing has been scored against the workbook. There is no acceptance result,
no PASS/FAIL, and no gate figure, because the answer key is unverified and the
workbook says an unverified key invalidates the entire result. Reporting a
number now would be reporting a number that does not mean anything.

## Resource state

The answering UI was stopped to recover memory (PID 11400,
`scripts/serve_ui.py --port 8000 --offline`, holding 2.86 GB of the machine's
7.9 GB). Available memory went from **0.56 GB to 3.62 GB**, and no
model-sized process is resident. Port 8000 is free.

Stopping it was the only change: no model weights, adapters, benchmark files,
database rows, dashboard code or model configuration were touched, and no
unrelated process was stopped. The read-only dashboard is still serving on
port 8050 (two small processes, a launcher and the server it re-execs into,
13 MB combined).

To bring the answering UI back when it is wanted:

```bash
python scripts/serve_ui.py --port 8000 --offline
```

Loading the model takes about 15 seconds and roughly 2.4 GB; the earlier
2.86 GB reflects memory that generation had accumulated over a session.

## Phase B — Benchmark Key Verification (planned, not implemented)

The objective is narrow: turn a **draft expectation** into an **accepted
expectation**, and only where it has actually been verified. Until then, a row
cannot take part in automated acceptance scoring.

```text
expected_citation_draft  ──verification──▶  accepted_expectation
        (column G)            (evidence)         (only if verified)
```

### What verification is not

It is **not** "the current eCFR database contains the cited provision". That
check would pass a row whose citation exists but whose substance, paragraph,
completeness, temporal status or ISO clause is wrong, and it would pass the
negative controls for exactly the wrong reason. Existence of the citation is
one input to verification, never the whole of it.

A row is verifiable only when each of the following that applies to it has
been checked against the authoritative source:

| | What must be checked |
|---|---|
| Citation | the section is correct, and the paragraph where the answer asserts a paragraph-level requirement |
| Provision / subparagraph | the cited subdivision is the one that carries the requirement |
| Substantive elements | the key answer elements in column J are actually what the provision requires |
| Completeness | every governing section the question reaches, not only the first |
| Current / temporal status | in force, reserved as of 2 February 2026, or historical — the 11 temporal rows exist to catch a wrong answer here |
| ISO clause mapping | the clause number and title in columns H and I, including the 8 rows where the correct answer names **no** clause |
| Negative-control expectation | that the object genuinely does not exist, so the expected refusal is the right expectation |

### Fields every row keeps

The workbook's own fields and terminology are preserved; verification adds to
them and replaces nothing:

```text
expected_citation_draft     column G, never overwritten
expected_ISO_clause         column H, never overwritten
key_verified                the workbook's column K semantics
accepted_expectation        None unless key_verified
verification_source         what was checked against
verification_notes          why, especially when it failed
```

### The verification artifact

A separate, auditable artifact — not an edit to the workbook. The original
`.xlsx` stays byte-identical, as it is today. Each record carries:

```text
benchmark_id            question_id            verification_status
verification_source     verified_citation      verified_answer_elements
verified_ISO_clause     verification_notes     verifier
verification_timestamp
```

### Rules the implementation must hold

* **No silent repair.** If a draft expectation is wrong, ambiguous, incomplete
  or needs clarification, the outcome is `key_verified = false`,
  `accepted_expectation = None`, and a recorded reason. The workbook's answer
  is never quietly replaced with a better one.
* **No automatic verification.** A row is marked verified by a person, or by a
  check that covers every applicable dimension above — not by a database
  lookup that happens to succeed.
* **Only verified rows score.** Automated acceptance scoring reads
  `accepted_expectation`, which is `None` until the row is verified, so an
  unverified row cannot silently contribute to a gate.
* **The workbook is read-only.** It is opened, never written.

## Phase B — key verification, automated pass

`src/regulus/evaluation/key_verification.py`, run by
`python scripts/verify_benchmark_key.py`. It reads the workbook and the
read-only snapshot, checks every row on seven dimensions, and writes a
timestamped artifact under `artifacts/benchmark_verification/`. The workbook
is never written to; previous runs are never overwritten.

### Result over all 300 rows

| | |
|---|---|
| Rows verified | **0** |
| Rows contradicted | **1** (X-004) |
| Rows awaiting SME | 299 |
| Scoring | **BLOCKED** — the key is not locked |

| Dimension | Confirmed | Contradicted | Unverifiable | Requires SME | N/A |
|---|---|---|---|---|---|
| citation | 246 | 1 | 24 | — | 29 |
| provision paragraph | 59 | — | — | — | 241 |
| temporal status | 13 | — | 1 | — | 286 |
| negative control | 5 | — | 2 | 15 | 278 |
| ISO clause | 12 | — | 16 | 23 | 249 |
| substantive elements | — | — | — | 300 | — |
| completeness | — | — | — | 300 | — |

No row reaches VERIFIED, and none can from an unattended run: substantive
correctness and completeness are judgments about what a provision requires,
so they always return REQUIRES_SME. `accepted_expectation` is None on every
row, which is what stops an unverified expectation reaching a gate.

### The one contradiction

**X-004** — the draft key reads "21 CFR 4.100 through 4.110". Part 4 of the
snapshot ends at 4.105; there is no 4.106 through 4.110. The key cites
sections that do not exist. This is a defect in the acceptance test's own
answer key, recorded with its evidence and **not corrected** — the workbook
is untouched and the SME decides.

### Sources, and what they could not settle

* **eCFR snapshot 2026-09-03**, 65,341 live records — citation and paragraph
  existence, and reserved status.
* **The approved ISO crosswalk** in the database: 189 rows, 88 clause
  identifiers with titles and **no clause text**, so clause identity is
  checked without reproducing a copyrighted standard.

Three things it cannot settle, reported rather than guessed:

1. **Substance and completeness (600 findings).** Whether a provision
   actually requires what column J says, and whether the key names every
   governing section, are judgments about text.
2. **ISO clause disagreements (23 rows).** The draft key and the approved
   crosswalk disagree — for example the key maps 820.35(a) to clause 8.2.2
   (Complaint handling) while the crosswalk maps the section to 4.2.5
   (Control of records). Both clauses exist. The crosswalk is an internal
   approved mapping at section granularity; the contract's authority is the
   controlled copy of ISO 13485:2016, which is not held here. Only that copy
   can settle these.
3. **Absences that are not sections (15 rows).** "NO SUCH REQUIREMENT",
   "NO SUCH LIMIT", "NO SUCH GUIDANCE" and "NO SUCH SUBPART" assert that
   something inside or beyond a provision is missing, which a section lookup
   cannot establish.

### The verifier was wrong twice before it was right

Worth recording, because both errors would have produced false accusations
against the contract's answer key:

* Its first pass reported **27 contradictions**. Four were reserved
  provisions being called nonexistent — a reserved section *exists*, and the
  snapshot stores a reserved span as one record with a range section number
  ("820.20-820.30"), so a naive lookup for 820.30 finds nothing. A false
  premise about a reserved section is not a claim that the section is absent.
* Eight more were rows where column H reads "None" (the correct answer names
  no ISO clause) being contradicted by a section-level crosswalk entry. A
  mapping from a *section* to clauses cannot settle a claim about a
  *question's answer*.
* Fifteen more were crosswalk disagreements, reclassified from CONTRADICTED
  to REQUIRES_SME once it was clear the crosswalk is evidence, not authority.

Each correction is pinned by a regression test, and the module now
distinguishes reserved from nonexistent, a false premise from an absence
claim, and a conflict of sources from a defect.

### What an SME has to do before scoring

1. Resolve X-004 — the draft key cites sections that do not exist.
2. Settle the 23 ISO clause disagreements against the controlled copy of
   ISO 13485:2016.
3. Establish the 15 non-section absences.
4. Judge substance and completeness on all 300 rows.
5. Mark column K, and record the verifier, title, date and eCFR revision date
   in the workbook's Section 2.

Only then does `accepted_expectation` populate and scoring become possible.

## SME key-review workflow and the hard gate

The controlled path from a draft key to a locked one is implemented and
tested. It has not been walked: no reviewer has decided a single row, so the
benchmark is **not verified** and both gates are shut.

```
benchmark (immutable, sha256)
  -> verification run (immutable)
    -> SME decisions, append-only, one per question
      -> sign-off (refuses while any row is open)
        -> locked key version  -> the gates open
```

### States, and the one that cannot be asserted

`UNREVIEWED · REQUIRES_SME · ACCEPTED · CORRECTED · REJECTED ·
NEEDS_RESEARCH · VERIFIED`

A reviewer may record ACCEPTED, CORRECTED, REJECTED or NEEDS_RESEARCH.
**VERIFIED is not in that list**: it is derived at sign-off, and only for a
row that was accepted or corrected *and* carries both the substantive and
completeness judgments. Attempting to record it directly raises. That is what
keeps REQUIRES_SME from collapsing into VERIFIED.

### The gate is in the execution path, not the dashboard

`require_locked_key()` raises `AcceptanceGateError`, and the entry points call
it before doing any work:

| Path | Behaviour today |
|---|---|
| `scripts/train_model.py` | **exit 3**, before any config or model load |
| `scripts/prepare_stage6_dataset.py` | **exit 3**, before generating anything |
| future 300-question scoring | calls the same function |

Both accept `--allow-unverified-key` for smoke tests, and both say in their
help text that it is never for a real run. A key locked against a *different*
workbook hash does not open the gate, and a hand-written locked key with an
unverified row does not either.

### Immutability and versioning

* The workbook is never written. It is still byte-identical:
  `c009d5f9c649…`, 76,773 bytes.
* `artifacts/benchmark_keys/<benchmark_key>/baseline.json` freezes the 300
  rows. Re-freezing identical content is a no-op; freezing *different* content
  under the same identity is refused — a different benchmark is a new version,
  not an overwrite.
* Decisions are append-only JSONL. Superseding a decision keeps the old one,
  so how a row reached its state is always recoverable.
* A locked key is written once and carries its own `key_version_sha256`. A
  later correction becomes review v2 and a new locked key; v1 on disk is
  untouched, so historical results stay reproducible.
* A correction records `original_citation` beside `corrected_citation`. The
  draft is never replaced.

### Evidence is labelled with what it can prove

Each review packet tags every piece of evidence with its weight, so a lookup
is never mistaken for a legal conclusion. The ISO crosswalk carries:

> An internal mapping approved inside this project. It is **NOT** the ISO
> standard and is not authority for what a clause requires; where it disagrees
> with the benchmark's key, the controlled copy of ISO 13485:2016 decides.

### What a reviewer faces

| | Rows |
|---|---|
| Contradicted by automation | 1 — X-004 |
| ISO conflicts (crosswalk vs draft key) | 23 |
| Absence claims that are not section lookups | 15 |
| Substantive judgment outstanding | 300 |
| Completeness judgment outstanding | 300 |
| **Open rows** | **300** |

X-004 is exposed as a decision, not corrected: the draft key reads "21 CFR
4.100 through 4.110" and Part 4 of the snapshot ends at 4.105. The evidence is
attached; the disposition is the reviewer's.

### Commands

```bash
python scripts/review_benchmark_key.py status
python scripts/review_benchmark_key.py queue --state REQUIRES_SME
python scripts/review_benchmark_key.py packet X-004
python scripts/review_benchmark_key.py decide X-004 --state CORRECTED \
    --reviewer "Name, Title" --rationale "Part 4 ends at 4.105" \
    --corrected-citation "21 CFR 4.100 through 4.105" \
    --substantive correct --substantive-rationale "..." \
    --completeness correct --completeness-rationale "..."
python scripts/review_benchmark_key.py sign-off --reviewer "Name" --title "..." \
    --ecfr-revision-date 2026-09-03
```

The dashboard's **Key review** page reports the same state and calls the same
gate function, so it cannot show "unlocked" while the scripts refuse.

## SME review operation

The 300-row review is prepared: see `docs/sme_key_review_operation.md` for
the categorisation, batching, reviewer protocol, special-case guidance,
consistency and QC design, and the workload estimate.

One defect was found in the workflow and fixed: packets carried no provision
text, so an SME judging substance and completeness would have had to navigate
eCFR by hand for all 300 rows. Packets now carry the eCFR text of every cited
provision, and negative controls carry a targeted search of the named part
with the caveat that it cannot prove an absence. ISO text is never included,
and a test asserts it cannot be.

Work profile: 221 rows need only the substantive and completeness judgments;
23 are ISO conflicts needing the controlled standard; 15 are absence claims;
1 is the X-004 contradiction. Estimated 35-69 hours of SME time including
calibration and second reviews.

## Exact Next Action

```
NEXT ACTION:
A subject-matter expert has to work the queue. The infrastructure is finished
and tested; nothing in it has been exercised on a real row, and no row is
verified. The reviewer resolves X-004, settles the 23 ISO conflicts against the
controlled copy of ISO 13485:2016, establishes the 15 non-section absence
claims, records a substantive and a completeness judgment on all 300 rows, then
signs off. Sign-off writes the locked key, and only then do the scoring and
training gates open. Until that happens both refuse with exit code 3.
```
