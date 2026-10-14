# Acceptance-run measurement record (`regulus_measurement_record_v1`)

`scripts/run_acceptance_test.py` writes one measurement record per question to
`artifacts/acceptance_test/<run>/measurement.jsonl`, next to `answers.jsonl`. The record holds what the
run actually had for that answer: the raw model output, the validated draft (when the pipeline exposes it),
the delivered answer, the exact evidence placed in the prompt, both validation reports and the repair. With
it, an answer can be rescored without rebuilding evidence from today's database.

`answers.jsonl` is unchanged: same keys, same meanings, and each answer row is written before its
measurement record. Implementation and loader: `src/regulus/traceability/measurement.py`. Tests:
`tests/test_measurement_record.py`.

## Data flow and where each item comes from

| Stage | Source in the pipeline | In `answers.jsonl` (unchanged) | In the measurement record |
|---|---|---|---|
| Question | benchmark column F | `question` | `question.text`, `.sha256` |
| Retrieval ranking | `RagAnswer.retrieved_results` | - | `evidence.retrieval_ranking` (rank, score, method, key) |
| Selection / coverage | `metadata.selection`, `metadata.coverage` | - | `evidence.selection`, `evidence.coverage` |
| Evidence in the prompt | `RagAnswer.evidence_snapshot` | `evidence_snapshot` (since 27860c6), `evidence` (labels) | `evidence.snapshot`, `.fingerprint`, `.item_text_sha256` |
| Raw model output | `metadata.raw_model_output` | `raw_model_output` | `text.raw_model_output` |
| Pre-validation edits | `metadata.generation`, `metadata.normalization` | - | `transformations` |
| Draft into validation | `metadata.repair_input` (set only when repair runs) | - | `text.validation_input` |
| Validation | `metadata.validation.initial` / `.final` | status and codes only | `validation.initial`, `validation.final` (full reports, problems included) |
| Repair | `metadata.validation.repair`, `metadata.repair_output` | `repair` | `validation.repair`, `text.repair_output` |
| Fallback / withholding | `metadata.fallback_type`, `fallback_reason`, `answerability`, `generation_blocked`, `block_reason` | `fallback_type`, `answerability` (state) | `validation.*` |
| Delivered answer | `RagAnswer.answer` | `answer` | `text.delivered_answer` |
| Citations | `RagAnswer.citations` | index and label | `citations` (full) |
| Evaluator-only inputs | `RagAnswer.package.answer_plan`, `.withheld`; `metadata.question_analysis.scope_status` | - | `evaluator_inputs` |
| Evaluation | **none while answering** (only `serve_ui` evaluates live) | - | `evaluation.state = "not_run"`; results of `--evaluate-offline` go to a separate file (below) |

## Fields

| Field | Type | Meaning |
|---|---|---|
| `schema` | str | `regulus_measurement_record_v1` |
| `hash_algorithm`, `canonicalization` | str | how `record_sha256` is computed (below) |
| `status` | str | `captured`, `pipeline_error` (the pipeline raised; the answers row is the ERROR row) or `capture_error` (the answer is fine but capture failed; `error` says why) |
| `complete` | bool | true only when every required rescoring input is captured: `text.delivered_answer`, `text.raw_model_output` (when the model was called), `evidence` (exact snapshot), and `validation` (when it ran) |
| `gaps` | list | `{field, state, reason}` for every field that is neither captured nor not applicable, required or not |
| `question_id`, `ordinal` | str, int | benchmark ID and 1-based benchmark position |
| `captured_utc` | str | when the record was built (stored once; covered by the hash) |
| `run` | object | `run_id`, `run_started_utc`, `model` (id, revision, weights sha256, device, dtype, adapter, backend), `generation_config` (decoding), `system_prompt_sha256`, `pipeline_config_sha256`, `code_revision` (`git_commit`, `git_dirty`, `tracked_diff_sha256`), `evaluator` (`rubric_id`, `rubric_version`, `evaluator_version: null`: no such identifier exists), `benchmark` |
| `text.<name>` | object | `{state, text, sha256, chars, reason}` for `raw_model_output`, `validation_input`, `repair_output`, `delivered_answer` |
| `transformations` | object | what the pipeline recorded doing between raw output and validation: duplicate sentences removed, citations repointed, normalization, stop reason |
| `evidence` | object | `provenance` (`exact` or `missing`), `snapshot` (the `regulus_evidence_snapshot_v1` object: items in prompt order with exact text, section and paragraph, tier, requirement IDs, URL and the SOURCES-block hash), `fingerprint`, `item_text_sha256` |
| `validation` | object | `state`, `initial`, `final`, `repair`, plus `fallback_type`, `fallback_reason`, `answerability`, `generation_blocked`, `block_reason`, `citation_support` |
| `evaluator_inputs` | object | `model_called`, `scope_status`, `package_present`, `answer_plan` (the package's `AnswerPlan.to_dict()`, or null), `withheld` (`[citation, text]` rows the evidence ceiling kept out). These are what the evaluator reads beyond the evidence, text and validation. Absent from records built before it was added; such records are not offline-evaluable |
| `inferred` | object | text comparisons (delivered vs. raw, delivered vs. validated draft). **Inferred**, not a pipeline record |
| `evaluation` | object | `{state: "not_run", reason}`, or `{state: "captured", assessment, review}` when a caller attaches the evaluator's own output |
| `record_sha256` | str | integrity checksum (below) |

Field states: `captured` is the pipeline's own value. `not_applicable` means the stage did not run (for
example, no model call means no raw output). `not_exposed` means the stage ran but the pipeline does not
expose the value. `not_recorded` appears in historical rows only: the artifact predates that field.
`capture_failed` means the value existed but could not be captured.

## Verifying a record independently

1. `record_sha256 == sha256(canonical(record without "record_sha256"))`, where `canonical(x)` is
   `json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")`.
   Every other field is covered, `captured_utc` included.
2. For every `text.<name>` that has text: `sha256 == sha256(text.encode("utf-8"))`.
3. `evidence.item_text_sha256[i] == sha256(snapshot.items[i].text)`, and the snapshot's `fingerprint`
   recomputes from its items (`regulus.traceability.evidence.fingerprint`). So an edited evidence text is
   detected even if someone recomputes `record_sha256` afterwards.

`measurement.verify_record(record)` runs all three and returns the list of problems. These are checksums:
they show a record has not changed since capture. They do not show who wrote it.

## Historical runs

The three archived runs (`acceptance_rev02_*`, `acceptance_sft2_v1_*`, `acceptance_c123_*`) have no
`measurement.jsonl` and no evidence snapshot. `measurement.load_run(run_dir)` returns their rows as
`legacy_answers_row` views: `complete: false`, evidence `missing` with its labels only, validation
`status_only` with `problems: not_recorded`, and evaluation `not_recorded`. Nothing is reconstructed, and no
file in the run directory is written. Evidence rebuilt from the database for such a row is
`legacy_reconstructed` (`regulus.traceability`), never `exact`.

## Sample (scripted answer over the test fixture table; long texts trimmed)

```json
{
 "schema": "regulus_measurement_record_v1", "status": "captured", "complete": true, "gaps": [],
 "question_id": "SYN-001", "ordinal": 1, "captured_utc": "2026-01-01T00:00:01+00:00",
 "run": {"run_id": "acceptance_test_20260101T000000Z", "model": {"model_id": "scripted"}, "...": "..."},
 "question": {"text": "What are the personnel qualification requirements in 21 CFR 211.25?", "sha256": "5581e420...", "matches_pipeline_question": true},
 "text": {
  "raw_model_output": {"state": "captured", "text": "Each person engaged in ... unless the batch was destroyed. [1] ...", "sha256": "f1700b0a...", "chars": 1324},
  "validation_input": {"state": "captured", "text": "Each person engaged in ...", "sha256": "f1700b0a...", "chars": 1324},
  "repair_output":    {"state": "captured", "text": "Each person engaged in ...", "sha256": "b4f87b6a...", "chars": 1060},
  "delivered_answer": {"state": "captured", "text": "Each person engaged in ...", "sha256": "b4f87b6a...", "chars": 1060}
 },
 "evidence": {"provenance": "exact", "fingerprint": "aff4aaaa...", "item_text_sha256": ["20376612...", "5b299dc1...", "..."],
  "snapshot": {"schema": "regulus_evidence_snapshot_v1", "prompt_verified": true, "items": [
   {"order": 0, "index": 1, "citation": "21 CFR 211.25(a)", "section": "211.25", "paragraph": "(a)", "tier": "exact", "truncated": false, "text": "(a) Each person engaged in ..."}, "..."]}},
 "validation": {"state": "captured",
  "initial": {"status": "evidence_mismatched", "codes": ["invented_condition"], "problems": [{"code": "invented_condition", "detail": "condition 'unless' appears in no supplied source", "citation": 1, "sentence": "Training in current good manufacturing practice ..."}]},
  "final": {"status": "valid", "codes": [], "problems": []},
  "repair": "invented_conditions_removed", "fallback_type": null},
 "inferred": {"label": "inferred by text comparison - NOT a pipeline record ...", "delivered_equals_raw_output_stripped": false},
 "evaluation": {"state": "not_run", "reason": "scripts/run_acceptance_test.py records answers only and makes no evaluator call; ..."},
 "record_sha256": "..."
}
```

## Known limits

- **Validated draft without repair.** The pipeline records the text it validated only when repair runs
  (`metadata.repair_input`). For every other answer, `text.validation_input` is `not_exposed`. It is not a
  required field, and it is never reconstructed.
- **No evaluation while answering.** The answering run makes no evaluator call. Evaluation is the separate
  `--evaluate-offline` operation below.
- **Untracked files.** `code_revision.tracked_diff_sha256` covers tracked changes only.

## Offline evaluation (opt-in)

```
python scripts/run_acceptance_test.py --evaluate-offline artifacts/acceptance_test/<run dir> [--evaluation-out FILE]
                                      [--offline-aligner lexical|semantic]
```

This is a separate operation on a finished run. It loads no model, database or workbook, never calls
`pipeline.answer()`, and only reads the run's files. Without `--evaluation-out`, results go to the new file
`artifacts/offline_evaluation/<run>/<utc>_<execution id>.jsonl`. The output file is opened in
exclusive-create mode, so an existing file is never overwritten; the command fails instead. The exit status
is 0 when `answers.jsonl` and `measurement.jsonl` are byte-identical after the evaluation, and 1 otherwise.
Answering without the option is unchanged and never evaluates. Implementation:
`src/regulus/evaluation/offline_evaluation.py`. Tests: `tests/test_offline_evaluation.py`.

**Inputs.** `answers.jsonl` and `measurement.jsonl` in the run directory.

**Per row of `answers.jsonl`, in its order:**

1. Find the measurement record with the same `question_id`, never by position. A question ID that occurs
   more than once, in either file, makes those rows not evaluable.
2. `verify_record`: the record hash, the text hashes, and the evidence fingerprint recomputed from the
   item texts. Then the consistency checks: record status `captured`; `run.run_id` equals the run
   directory name; the pipeline answered the benchmark question (`matches_pipeline_question`); the row's
   question and answer equal the record's; the row's evidence fingerprint, where it has one, equals the
   record's.
3. Rebuild the evaluator's inputs from the record alone:
   - `validation` becomes a `ValidationReport`.
   - The repair record becomes `{initial, final, repair}` from `record.validation`. That is exactly the live
     UI's `RagAnswer.metadata["validation"]`, and it is `None` when validation did not run. The
     repair-aware completeness check reads the initial report's problems. So a captured validation whose
     initial report is missing, is not a lossless `ValidationReport` dict (for example an archived row's
     bare status string), or whose repair kind is not a string or null, makes the row **not evaluable**.
     It is never evaluated without the initial report, which could show a completeness PASS that live
     would withdraw.
   - `evaluator_inputs.answer_plan` becomes an `AnswerPlan`.
   - Both must serialise back to exactly the saved dict. A missing or unknown field, or an inconsistent
     derived field such as `ok`, makes the row not evaluable; nothing is dropped or guessed.
   - The package becomes an adapter holding exactly what `regulus.accuracy` reads from a package:
     `sources` (the snapshot items, in prompt order), `requirements`, `answer_plan` and `withheld`. A test
     scans the evaluator source to keep that set complete.
4. Call `regulus.accuracy.evaluate_safely(question, saved answer, evidence=saved snapshot, package=adapter,
   validation=..., citations=..., model_called=..., fallback_type=..., scope_status=..., answerability=...,
   repair=...)`.
   This is the same entry point as the live UI. It re-verifies the snapshot and labels the evidence EXACT.
   Coverage is read from the snapshot. No evaluator logic is copied.

**Outcomes:**
- `evaluated`: the evaluator returned an assessment, and `review_status` is its own PASS / FAIL / NOT
  EVALUATED (`regulus.accuracy.review`). A legitimate NOT EVALUATED is `evaluated` with
  `review_status: not_evaluated`.
- `not_evaluable`: the saved data cannot support an evaluation, and `reason` says why. This covers an
  archived row with no record, a missing or corrupt snapshot, a failed hash, a mismatch with the answers
  row, an unsupported field, a missing or malformed initial validation report, and a pipeline error.
- `evaluation_error`: the evaluator failed on a supported record.

A failure is confined to its row. Unreadable lines are listed in the summary's `problems`.

**Output schema `regulus_offline_evaluation_v1`** (one line per answers row):

| Field | Meaning |
|---|---|
| `execution` | `execution_id`, `started_utc`, `elapsed_ms`: this execution only, **not** hashed |
| `result.run_id`, `.question_id`, `.ordinal` | the key, with the row's position in `answers.jsonl` |
| `result.source` | `measurement_record_sha256`, `evidence_fingerprint`, `answers_row_sha256`: the exact inputs |
| `result.evaluator` | `rubric_id`, `rubric_version`, `evaluator_version` (null: none exists), `git_commit`, `git_dirty`, `tracked_diff_sha256` (from the repository at evaluation time), `entry_point`, `aligner`, `embedder` (null unless semantic), `identifier_index` (`not_used`), `repair_argument` (`passed`) |
| `result.outcome`, `.reason` | as above |
| `result.review_status`, `.review_label`, `.score`, `.live_check_score` | read from the evaluator's own output |
| `result.assessment` | the evaluator's `AccuracyAssessment.to_dict()` as returned, minus `elapsed_ms`: dimensions, deductions, answer verdict, and `checked` (claims and their verdicts, completeness, evidence provenance) |
| `result.review` | `question_review(assessment)` |
| `result.parity` | per input (`aligner`, `identifier_index`, `repair`): `identical`, `no_effect` or `limited` for this answer, plus `live_equivalent` (see Parity below) |
| `result_sha256` | SHA-256 of the canonical JSON of `result` (same canonicalization as the record). `offline_evaluation.verify_result` checks it |

The evaluator is deterministic with the lexical aligner, so evaluating the same records with the same code
gives the same `result_sha256` for every row (tested). Changed evaluator code changes `result.evaluator`,
and with it the hash.

**Illustrative result** (scripted answer over the test fixture table: a focused question answered with one
of three requirements; long parts elided):

```json
{"schema": "regulus_offline_evaluation_v1",
 "execution": {"execution_id": "d0a97f8a...", "started_utc": "2026-10-14T06:12:44+00:00", "elapsed_ms": 4.85},
 "result": {"run_id": "acceptance_test_20260101T000000Z", "question_id": "Q-005", "ordinal": 5,
  "source": {"measurement_record_sha256": "afee86da...", "evidence_fingerprint": "aff4aaaa...", "answers_row_sha256": "0e572a63..."},
  "evaluator": {"rubric_id": "regulus_live_evidence_assessment_v2", "rubric_version": "2.0.0", "evaluator_version": null,
                "git_commit": "d3531af5...", "git_dirty": true, "tracked_diff_sha256": "3a466930...",
                "entry_point": "regulus.accuracy.evaluate_safely", "aligner": "lexical",
                "identifier_index": "not_used", "repair_argument": "passed"},
  "outcome": "evaluated", "reason": null, "review_status": "fail", "review_label": "FAIL",
  "score": 75, "live_check_score": 75,
  "assessment": {"status": "evaluated", "accuracy": 75, "deductions": [{"dimension": "completeness", "state": "fail", "points": 25}], "...": "..."},
  "review": {"...": "..."}},
 "result_sha256": "c63d11fb..."}
```

**Historical records.** The archived runs have no `measurement.jsonl`. Every row is `not_evaluable`, with
a reason naming what the row holds (evidence `missing`, validation `status_only`), and nothing is
reconstructed. Evidence rebuilt from today's database is never substituted. Their files are only read.

## Parity with the live evaluation

The live reference is `scripts/serve_ui.py` `Engine.assess` in its default configuration. Tests drive the
real `Engine.assess`, with an injected aligner and identifier index, and compare against it
(`tests/test_offline_parity.py`).

| Evaluator input | Live (UI default) | Offline | Parity |
|---|---|---|---|
| question | `RagAnswer.question` | `record.question.text`; refused unless it equals the pipeline's question | identical |
| answer | `RagAnswer.answer` | `record.text.delivered_answer` (hash-verified, equal to the answers row) | identical |
| evidence | `RagAnswer.evidence_snapshot` | `record.evidence.snapshot`; the evaluator re-verifies its fingerprint | identical |
| package `sources` | snapshot items (`_ExactEvidence` replaces the package's own) | snapshot items | identical |
| package `requirements` | `package.requirements` | `snapshot.requirements`, captured from that same tuple | reconstructed, equivalent by construction |
| package `answer_plan` | `package.answer_plan` | rebuilt from `evaluator_inputs.answer_plan`; must round-trip to the saved dict | reconstructed, verified equivalent (dataclass equality tested) |
| package `withheld` | `package.withheld` | `evaluator_inputs.withheld` | reconstructed, verified equivalent |
| `coverage` | `RagAnswer.coverage` (reads `satisfied_ids`, `missing_labels`, `explicit`) | the snapshot's copies of those three fields | reconstructed, equivalent by construction |
| `validation` | `RagAnswer.validation` | rebuilt `ValidationReport`; must round-trip to the saved dict | reconstructed, verified equivalent |
| `citations` | `RagAnswer.citations` (only their count is read) | `record.citations` | identical |
| `model_called`, `fallback_type`, `scope_status`, `answerability` | `RagAnswer` / `metadata` | `evaluator_inputs`, `record.validation` | identical |
| `aligner` | semantic (pinned bge-small); **silently lexical if the embedder fails to load**, and the UI then still reports "semantic" | lexical; or `--offline-aligner semantic` (same embedder, no fallback) | intentionally different by default; `no_effect` per answer when no claim aligned |
| `identifier_index` | `DatabaseIdentifierIndex` over **today's** database | not used | unavailable in saved records; `no_effect` per answer when no lookup would be made |
| `repair` | `RagAnswer.metadata["validation"]` (`initial`, `final`, `repair`) | the same three fields from `record.validation`; a captured validation without a sound initial report is not evaluable | identical |
| rubric and thresholds | code constants (`rubric.py`, `RUBRIC_ID`/`RUBRIC_VERSION`) | the same code; identity in `result.evaluator` | identical for the same code revision |
| other state | none: no environment, file, database or clock is read. Two `lru_cache`s memoize pure functions | same | identical |

**Per-answer parity (`result.parity`).** Whether each differing input can change *this* answer's
assessment is measured, not assumed:

- **aligner:** `identical` when the offline aligner is semantic. Otherwise `no_effect` if no claim was
  aligned to any passage. Both aligners apply the same lexical floor first, so with nothing aligned the
  choice is moot. Otherwise `limited`.
- **identifier_index:** a second, discarded evaluation with a probe index records the lookups the live
  evaluator would make. `no_effect` if there are none, otherwise `limited`, and the lookups are listed.
  Whether any lookup is made does not depend on the index's answers.
- **repair:** always `identical`. Offline passes the saved validation record exactly as the live UI passes
  it, and refuses a record that cannot supply it.

`live_equivalent` is true only when all three are `identical` or `no_effect`. Since repair is always
identical, in practice that means the aligner and the identifier index. The offline assessment then
has the live one's verdicts, claims, dimensions, deductions, score and review status. It differs at most in
the recorded flags `checked.aligner` and `checked.identifier_index_used`.

Measured on the 13 deterministic fixture answers in `tests/test_offline_parity.py`:
- With the default lexical aligner, 4 of 13 rows are live-equivalent. The aligner limits 8 and the
  identifier index 2; a row can be limited by both.
- With `--offline-aligner semantic`, 11 of 13 rows are live-equivalent. The other 2 are limited only by
  the identifier index.
- Aligner choice alone turned one paraphrased answer from FAIL (lexical) into NOT EVALUATED (semantic).
- The index decides a named-but-absent section, and a refusal of a reserved section.
- The repair-aware check withdraws a PASS from an answer whose repair removed required content, offline
  exactly as live. A complete repaired answer keeps PASS 100 in both.

**Identifier index for future runs (proposal, not implemented).** Exact offline parity for the index needs
the lookup results as they were when the answer was produced. The minimal additive schema change:

```
evaluator_inputs.identifier_lookups: [{"kind": "section" | "part", "id": "211.999", "exists": bool, "live": bool}]
```

This would be captured by the answering run while its database connection is open. It would cover every CFR
section and part named in the delivered answer, and every requested provision, which is a superset of what
the evaluator can ask (see `_named_identifiers` and `abstention._reserved_requests`). Offline would then
answer the evaluator's lookups only from that list, and treat any lookup outside it as limited. It adds
database reads to the answering run, so it needs your approval. Archived records stay as they are.

**Repair metadata.** The record keeps `validation.initial`, `.final` and `.repair`, and offline passes them
as `repair=`, as the live UI does. Records that cannot supply a sound initial report are not evaluable, and
the missing state is never reconstructed. Archived runs have no measurement record at all, so they were
already not evaluable.

Offline evaluation measures a saved answer against saved evidence. It does not show that the original
model generation can be reproduced.
