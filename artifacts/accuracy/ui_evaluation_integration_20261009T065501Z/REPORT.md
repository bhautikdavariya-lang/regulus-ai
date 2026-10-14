# Per-question evaluation in the UI: implementation report

**Date:** 2026-10-09 (started 06:55:01Z). **Branch:** `main`. **No commit made.**

**Status: implemented and tested.** Full suite: 1910 passed, 1 skipped, 3 xfailed, 0 failed. Live on/off regression through the real server path: PASS.

## 1. What existed, and what was missing

The live per-question evaluator was **already wired** end to end. Repository evidence:

```
web/index.html  ask()  POST /api/ask/stream   (or /api/ask)
  -> scripts/serve_ui.py  Handler._ask_stream / do_POST  -> Engine.ask(question)
       -> regulus.rag RagPipeline.answer()            retrieval, generation, validation -> RagAnswer
       -> Engine.assess(out)                           strictly after the final answer
            -> regulus.accuracy.evaluate_safely(...)   live evaluator: the exact evidence the prompt carried
       -> result["accuracy"] = AccuracyAssessment.to_dict()
  -> stream event {"type": "final", "result": ...}
-> web/index.html  render(result)
```

**What the evaluation is based on:**
- It is a **live evaluation of the answer against the evidence retrieved for that question**: rubric `regulus_live_evidence_assessment_v2`, `src/regulus/accuracy/rubric.py`.
- No benchmark reference answer and no benchmark artifact is used. The rubric itself states it is not the acceptance rubric (`is_acceptance_rubric: False`).
- Results are not persisted. They travel with each response only.

**What was missing:**
- The page headlined the evaluator's 0–100 *deduction* score as **"Answer Accuracy 90%"**, with an "accuracy 90%" pill. That presents a weighted check score as an accuracy percentage.
- It gave no PASS / FAIL / NOT EVALUATED status.
- A substantive pass could sit under a high percentage while another check had failed.

## 2. Files changed

| File | Change | Lines |
|---|---|---|
| `src/regulus/accuracy/review.py` | **new**: `question_review(assessment, question=)`, which *reads* the existing assessment and returns the per-question status | 120 |
| `scripts/serve_ui.py` | `Engine.accuracy_payload(out)`: the evaluator's dict, plus `question_review` **inside** it; `ask()` uses it | +10 / −1 |
| `web/index.html` | `evaluationOf()`, `evalPill()`, `renderEvaluation()` replace `accPill()` / `renderAccuracy()`; `render(r, asked)` receives the question this request sent | +59 / −31 |
| `tests/answer_ui_stream_harness.js` | a `file` scenario that renders a real, Python-built payload, with the page's own question | +9 / −1 |
| `tests/test_accuracy_question_review.py` | **new**: 17 tests | — |
| `tests/test_accuracy_ui.py` | **rewritten**: 5 tests replaced by 18 (see 4.2) | +142 / −44 |

**Untouched:**
- the evaluator: every module except `review.py` is byte-identical, including `operators.py` with the numeric fix, `verdicts.py` with the Phase 2D gate, `rubric.py` and `answer.py`;
- benchmark, frozen and fixture files: identical (`benchmark_manifest_before/after.sha256`);
- pre-existing user changes. `serve_ui.py`, `index.html` and the harness already carried uncommitted user edits; mine are additive on top, and the pre-task copies are in `snapshot_before/` with diffs in `*.diff`.

## 3. How a result travels, and what the user sees

1. `evaluate_safely()` returns the assessment, unchanged.
2. `review.question_review()` reads it and derives the status:
   - **PASS:** the assessment is `evaluated`, the answer verdict is *correct* or a *correct refusal*, and **every** dimension (relevance, substantive, evidence support, citation, unsupported claims, completeness, scope) passed or did not apply.
   - **FAIL:** the assessment is `evaluated`, and a dimension failed or is partial, or the answer verdict is incorrect, partial, off-topic or an incorrect refusal. The explanation names what failed. For example, the evaluator's own verdict can read "Correct" while completeness is partial, and the explanation then says "Completeness partial: …".
   - **NOT EVALUATED:** no assessment; the evaluator abstained (`unable_to_determine`); the answer states no requirement (`not_applicable`); an evaluator error; incomplete or malformed metadata; or a question mismatch. When nothing failed but some checks were undecided, the label is **NOT FULLY EVALUATED**, never PASS.
3. `serve_ui.accuracy_payload()` stores the result in `result["accuracy"]["question_review"]`. Keeping it inside `accuracy` preserves the observer contract: the response with evaluation on differs from the response with it off **only by the `accuracy` key** (`tests/test_accuracy_observer.py`; the payload arm of `scripts/accuracy_regression.py`).
4. **The page** (`evaluationOf`) shows the server's status, but downgrades to NOT EVALUATED if the review is missing or malformed, if the status or label is unknown, or if it claims PASS without an `evaluated` assessment plus a substantive pass and a passing (or not-applicable) citation check. It also downgrades if the result's question is not the question this request sent, or the review's question is not the result's. Only allow-listed labels are displayed.

**What is on screen,** in a block separate from the regulatory answer and below it:
- a header pill `evaluation: PASS | FAIL | NOT EVALUATED`;
- "Evaluation of this answer" with the status;
- the basis line: *"Live evidence assessment of this one answer: it is compared with the regulatory evidence retrieved for it. No reference answer is used, and this is not the 300-question acceptance-test result."*;
- **Substantive correctness** and **Citation correctness**, each with its state and the evaluator's detail;
- a concise explanation;
- in a collapsed "All checks" section: every dimension and the evaluator's score, shown as **"Live check score N/100 … it is not an accuracy percentage."**

**No accuracy percentage appears anywhere in the block.** With evaluation off, nothing is added and the page is as before. Rendered examples from the real evaluator are in `rendered_examples.txt`.

## 4. Tests (actual outcomes)

| Run | Result |
|---|---|
| `tests/test_accuracy_question_review.py` (new) | **17 passed** |
| `tests/test_accuracy_ui.py` (rewritten) | **18 passed** |
| The same 18 UI tests against the **pre-change page** (`work/test_ui_against_old_page.py`) | **17 failed, 1 passed**. The tests discriminate; the one that passes is the "evaluation off: page unchanged" preservation test, which should pass on both. |
| `test_streaming_ui.py` 3, `test_streaming.py` 15, `test_observatory_ui.py` 24 | all passed |
| Accuracy files: citation_grounding 19, claim_extraction 35, claims 41, **content_gate 240**, contradiction_scope 8, evaluation 31, guidance_logic 29, **numeric_limits 43**, observer 6, relative_clause 5 + 3 xfailed, relevance 67 | all passed (`tests_relevant_after.txt`) |
| Full suite `pytest -q tests/ -rs` | **1910 passed, 1 skipped (pre-existing), 3 xfailed, 0 failed**. That is 1880 before, − 5 replaced UI tests, + 18 + 17. |
| Live on/off regression through `serve_ui.Engine.ask` (local model, `--offline`, read-only DB, 3 questions) | **exact evidence PASS, payload arm PASS, live arm PASS**; answers byte-identical with evaluation on and off (`regression.log`, `artifacts/accuracy/regression_2026-10-09T070354Z.json`) |

**Coverage of the seven required cases:**

| Case | UI test | Python test |
|---|---|---|
| 1. passing | `…passing_answer_shows_pass…` | `…verbatim_answer_passes…` |
| 2. failing | `…failing_answer_shows_fail…` | `…incorrect_answer_fails…` |
| 3. partially correct, fails the full rubric | `…substantively_correct_but_incomplete…`, `…partially_correct_answer_fails` | `…substantive_correctness_alone_is_not_a_pass`, `…partially_correct…` |
| 4. no evaluation result | `…without_evaluation_the_page_is…`, `…abstaining_evaluator…` | `…abstention_of_the_evaluator…` |
| 5. missing or incomplete metadata | 7 parametrised cases plus an unrecognised label | 7 parametrised cases plus not-fully-evaluated |
| 6. evaluator error, never PASS | `…evaluator_error_is_not_evaluated…` | `…evaluator_error…never_a_pass` |
| 7. this question's own result | `…result_for_another_question…`, `…evaluation_of_another_question…`, `…each_question_shows_its_own_result` | `…another_questions_result_is_not_shown` |

The server attachment itself is tested by `test_the_server_adds_only_the_review_and_only_inside_the_assessment`, which runs the real `serve_ui.Engine.accuracy_payload` on real scripted pipeline answers.

### 4.1 Evidence base of the tests

- **Real evaluator output.** All UI and review tests use assessments produced by the real evaluator: the in-memory regulation table of `tests/test_accuracy_evaluation.py`, and the real pipeline with a scripted generator from `test_accuracy_observer.py`.
- **Synthetic parts.** The "damaged metadata" cases mutate a real assessment; the harness supplies the surrounding answer text and sources.
- **Not exercised in an automated test:** a real browser. Rendering is tested by running the page's own script under Node.

### 4.2 Existing tests changed

`tests/test_accuracy_ui.py` pinned the old "Answer Accuracy 90%" headline and the "accuracy 90%" pill, which the brief asked to remove. Its five tests were replaced. Their protective intent carries over:

| Old intent | Where it now lives |
|---|---|
| no number unless the server sent one | no percentage at all; the score appears only as a labelled detail |
| an abstention is never 0% | the NOT EVALUATED tests |
| never the acceptance-test score | the basis-line assertion |
| the answer is shown whatever the block does | `answer_shown` in every test |
| feature off means the page is unchanged | kept |

The old file is in `snapshot_before/test_accuracy_ui.py`. The harness's old static `accuracy_*` fixtures (v1 payloads) are left in place but no test uses them any more.

## 5. Live results observed (from the regression run)

Applying the status rules to the dimension states logged for the three live answers. The regression JSON records the states, not the rendered review.

| Question | What the user would see | Why |
|---|---|---|
| 21 CFR 820.35 record controls | **FAIL** | substantive pass, **citation fail** (the old page showed "accuracy 60%") |
| FDA facility registration | **FAIL** | substantive partial; evidence support not established |
| 211.180(a) retention | **FAIL** | the pipeline withheld the answer although the evidence was there: an incorrect refusal |

## 6. Limitations

**What the evaluation is and isn't.** It is a live evidence assessment of each answer. It is not a comparison with a benchmark reference answer and **not the acceptance rubric**, and the UI says so every time. A PASS means "every check this live rubric can decide passed against the retrieved evidence", not that the answer is independently verified or correct in every respect. The evaluator deliberately abstains on correct paraphrases (rubric design), so many correct answers will show NOT EVALUATED rather than PASS.

**The numeric fix.** It is inside the evaluator and applies to live answers, but its real-answer behaviour is still unmeasured (see the numeric-fix report).

**Implementation limits:**
- **The question match** compares the stripped question the page sent with `result.question`. It is exact-string, so a server that rewrote the question would show NOT EVALUATED, which is the safe direction.
- **No persistence.** A result is shown with the response that carries it; there is no history of per-question evaluations. The dashboard/observatory pages are untouched.
- **Correction to a previous report.** The numeric-fix report said the 211.180 live answer had "0 claims evaluated". That misread "evaluated 0" (status evaluated, score 0). It is corrected in that report with a dated note, and its conclusion is unchanged.

## 7. Final state

- **Changed:** `scripts/serve_ui.py`, `web/index.html`, `tests/answer_ui_stream_harness.js`, `tests/test_accuracy_ui.py`.
- **New:** `src/regulus/accuracy/review.py`, `tests/test_accuracy_question_review.py`.
- **Git status:** 64 → 65 lines; the new line is `?? tests/test_accuracy_question_review.py`, since `src/regulus/accuracy/` was already untracked. No other line changed (`git_status_before/after.txt`).
- **Whitespace:** `git diff --check` is clean on the tracked files; there is no trailing whitespace in the new files.
- **Syntax:** Python compiles; the page script and the harness parse under Node.
- **Not done:** no dependency installed, no database write (read-only connection only), no benchmark or rubric change, no 300-question run.
- **Note on order:** `review.py` was created a few minutes before `manifest_before.sha256` was recorded. The manifest was therefore taken excluding it, and it equals the end state of the numeric fix.

## Artifacts

- **Snapshots and diffs:** `snapshot_before/` (the four pre-task files), `*.diff`.
- **State:** `manifest_*`, `benchmark_manifest_*`, `git_status_*`.
- **Test outputs:** `tests_relevant_after.txt`, `tests_full_suite_after.txt`, `ui_tests_against_old_page.txt`.
- **Examples:** `rendered_examples.txt`.
- **Live regression:** `regression.log`, `regression_questions.txt`.
- **Work files:** `work/` (the old-page harness and test copy).
