# Evaluation score beside the PASS/FAIL status: implementation report

**Date:** 2026-10-09 (started 07:20:52Z). **Branch:** `main`. **No commit made.**

**Status: implemented and tested.**
- Full suite: 1931 passed, 1 skipped, 3 xfailed, 0 failed.
- Live on/off regression through the real server: PASS.
- Headless-Chrome render: done (section 6).

## 1. Files changed

| File | Change |
|---|---|
| `src/regulus/accuracy/review.py` (+7 / −2) | `_score()`: the score passed to the page (`live_check_score`) is the evaluator's value only if it is an `int` (not `bool`) from 0 to 100; otherwise `None`. **The status logic is unchanged.** |
| `web/index.html` (+18 / −3) | `evaluationScore()` validates the score again on the page. The main evaluation block shows **"Evaluation score N/100"**, or **"Score unavailable"**, directly under the status, with the note *"Evaluation score based on the system's checks; it is not a percentage of factual accuracy."* The details no longer repeat the number; they say how it is calculated ("100 minus the deductions for these checks …, never below 0"). |
| `tests/test_accuracy_ui.py` (+96 / −3) | 17 new tests. Two existing assertions were updated, because they pinned the old wording ("Live check score 100/100" in the details) that this task replaces. |
| `tests/test_accuracy_question_review.py` (+18) | 4 new tests for the score field |
| `tests/answer_ui_stream_harness.js` (+47 / −16) | Two additions: `sequence`, several answers asked in one page session (for stale-score tests), and `scores`, which calls the page's own `evaluationScore()` and `renderEvaluation()` with values JSON cannot carry (NaN, ±Infinity, undefined). The stream builder became a function; existing scenarios are unchanged, and `test_streaming_ui.py` passes. |

**Untouched:**
- `scripts/serve_ui.py`;
- the evaluator (scoring formula, rubric, content gate, citation validation, numeric fix);
- the status rules;
- retrieval, prompts and generation;
- benchmark, frozen and fixture files (`benchmark_manifest_before/after.sha256` identical).

Git status is unchanged at 65 lines. Pre-task copies are in `snapshot_before/`, and diffs are in `*.diff`.

## 2. The score: field and scale, verified

| | Value |
|---|---|
| **Source** | `AccuracyAssessment.accuracy` (`src/regulus/accuracy/evaluator.py:111`), emitted as JSON `"accuracy"`; set only when the assessment status is `evaluated` (`evaluator.py:517`) |
| **Formula** | `rubric.score()` = `max(0, 100 − sum of deductions)` (`rubric.py:169-171`); every deduction in `DEDUCTIONS` is positive |
| **Scale** | an integer from 0 to 100 by construction; no conversion applied |
| **Forwarded as** | `accuracy.question_review.live_check_score` (`review.py`), the field the page reads |
| **Meaning** | a deduction score over the live rubric's checks. It is not a percentage of correct claims, and the UI does not say it is. |

## 3. Missing and invalid scores

- **Displayed** only when the value is an integer from 0 to 100. That is checked in `review.py` and checked again on the page.
- **Shown as "Score unavailable"** when the value is missing, `null`, non-numeric (`"90"`, `[90]`, `{…}`, `true`), NaN, ±Infinity, fractional (90.5, 99.9), or out of range (−1, 101, 150). It is never replaced with 0 or 100.
- **No score at all** when the evaluator abstained or failed, when the result is incomplete, or when it belongs to another question (the page's existing downgrade carries no score).
- **The score never decides the status.** 90 sits under FAIL; 5 under NOT FULLY EVALUATED stays NOT FULLY EVALUATED. An invalid score leaves a PASS a PASS, with "Score unavailable".
- **One existing rule is kept unchanged:** an *evaluated* assessment arriving without an integer score is treated as incomplete metadata (NOT EVALUATED). That is the existing incompleteness safeguard, not a status decided by the score's value. The brief said to leave the status rules alone, so it was not modified.

## 4. Not presented as factual accuracy

The page says "Evaluation score N/100" with the note above. No "%", "Accuracy" or "Correctness %" appears in the evaluation block; tests assert this, as does the Chrome-rendered DOM. The existing basis line remains: it is a live assessment against the retrieved evidence, uses no reference answer, and is not the 300-question acceptance result.

## 5. Tests (actual outcomes)

| Command | Result |
|---|---|
| `pytest tests/test_accuracy_ui.py` | **35 passed** (18 existing, 2 of them updated; 17 new) |
| `pytest tests/test_accuracy_question_review.py` | **21 passed** (17 existing, 4 new) |
| The same UI tests against the **pre-task page** (`work/test_ui_against_old_page.py`) | **19 failed, 16 passed**. All new score tests fail there; the 16 earlier status and safety tests pass, as they should. |
| `test_streaming_ui` 3, `test_streaming` 15, `test_accuracy_observer` 6, `test_accuracy_content_gate` 240, `test_accuracy_numeric_limits` 43, `test_accuracy_evaluation` 31, `test_accuracy_citation_grounding` 19, `test_accuracy_relative_clause` 5 + 3 xfailed, `test_observatory_ui` 24 | all passed (`tests_relevant_after.txt`) |
| `pytest -q tests/ -rs` | **1931 passed, 1 skipped (pre-existing), 3 xfailed, 0 failed** (1910 + 21) |
| `scripts/accuracy_regression.py --questions regression_questions.txt --arms both --offline` (real `serve_ui.Engine.ask`, local model, read-only DB) | **exact evidence PASS, payload arm PASS, live arm PASS**. With evaluation on vs off the answers are byte-identical and the response differs only by `accuracy`. Answers, citations, scores (60, 40, 0) and dimensions are identical to the previous task's run. |

**Coverage of the ten required checks:**

| # | Requirement | Test |
|---|---|---|
| 1 | a valid score shown out of 100 | `test_the_score_is_the_evaluators_own_number_out_of_100_beside_the_status` (real 90) |
| 2 | 0 and 100 | `…score_of_zero…` (real 0), the passing test (real 100), and `values_json_cannot_carry…` (0 and 100 through the page's function) |
| 3 | intermediate, not labelled accuracy | test 1, plus "no %" and "no Accuracy" in the block |
| 4 | missing or invalid → neutral fallback | `…invalid_score…` (8 values), `…missing_score_field…`, `…values_json_cannot_carry…` (NaN, ±Infinity, undefined, null, −1, 101, 99.9, "58") |
| 5 | the score does not override the status | 90 under FAIL; `…low_score_does_not_turn_not_evaluated_into_fail`; an invalid score leaves PASS |
| 6 | substantive and citation explanations still visible | tests 1 and 3, `…partial_answer_keeps_its_explanations…` |
| 7 | evaluation off unchanged | `test_without_evaluation_the_page_is_the_page_it_was` |
| 8 | no stale score | `test_no_stale_score_after_a_later_answer_without_evaluation`: three answers in **one page session** (scored, then evaluation off, then a null assessment) |
| 9 | incomplete or mismatched results cannot give a misleading PASS | `…no_score_without_a_legitimate_result`, `…result_for_another_question_shows_no_score`, plus the earlier metadata tests |
| 10 | status logic and safeguards intact | the earlier review and UI tests, the observer test, the content gate, the numeric-limit tests, the full suite |

Evaluation payloads in these tests are **real evaluator output** (the in-memory regulation table and the real pipeline with a scripted generator). The invalid-score cases mutate a real payload.

## 6. Real-browser validation

**Partly.** No browser automation framework is installed (no Playwright, Selenium or Puppeteer), and none was installed.

**What was done:** the locally installed Google Chrome was run headless (`--headless=new --dump-dom` and `--screenshot`, with a throwaway profile in the session scratchpad) on stand-alone copies of `web/index.html`.
- `fetch()` was stubbed to stream one final result whose `accuracy` is real evaluator output; the page's script was unchanged and asked automatically (`work/build_browser_pages.py`).
- Results:

  | Page | Status | Score line |
  |---|---|---|
  | `pass_100` | PASS | "Evaluation score 100/100" |
  | `fail_90` | FAIL | "Evaluation score 90/100" |
  | `not_evaluated` | NOT EVALUATED | "Score unavailable" |

  Each has the accuracy disclaimer and no percentage inside the evaluation block (`browser/*.dom.html`, `browser/*.png`). The screenshots were inspected.

**Limits of that check:**
- It is a real browser engine rendering the real page script, but **not the live server**. The server path is covered by the regression in section 5.
- Interaction (clicking Ask) was not automated; the stub page calls `ask()` itself.
- Chrome did not always exit after dumping, so each render was time-limited and its process stopped. The captured output was complete.

## 7. Confirmation

- **Answer generation:** unchanged. Answers are byte-identical with evaluation on and off, and identical to the previous run.
- **Unchanged:** the evaluator scoring formula, the status rules, the content gate, citation validation, the numeric fix, F-007/F-009, the rubric, and the benchmark questions, answers and results.
- **Not done:** no 300-question run, no dependency installed, no database write (read-only connection only).

## 8. Limitations

- **The score's meaning.** It is the live rubric's deduction score. Its weights are a design choice documented in `rubric.py`, not a calibrated probability or a share of correct claims. The UI says only "based on the system's checks".
- **NOT FULLY EVALUATED shows a score.** It shows the evaluator's score, because the evaluator did issue one for that assessment. The score includes small deductions for undecided checks.
- **Question matching** is exact-string (from the previous task). A server that rewrote the question would show NOT EVALUATED and "Score unavailable", which is the safe direction.
- **The harness's old static `accuracy_*` fixtures** (v1 payloads) remain unused, as before.

## Artifacts

- **Snapshots and diffs:** `snapshot_before/`, `*.diff`.
- **State:** `manifest_*`, `benchmark_manifest_*`, `git_status_*`.
- **Test outputs:** `tests_relevant_after.txt`, `tests_full_suite_after.txt`, `ui_tests_against_old_page.txt`.
- **Live regression:** `regression.log`, `regression_questions.txt`, `artifacts/accuracy/regression_2026-10-09T073356Z.json`.
- **Browser check:** `browser/` (stub pages, rendered DOMs, screenshots) and `work/build_browser_pages.py`.
