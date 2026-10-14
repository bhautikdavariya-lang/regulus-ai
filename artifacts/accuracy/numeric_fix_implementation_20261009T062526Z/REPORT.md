# Numeric comparison fix: implementation handoff

**Date:** 2026-10-09 (started 06:25:26Z). **Branch:** `main`. **No commit made.**

**Status: IMPLEMENTED; every test and protected check run passed; no regressions.**
- Ready for a *controlled* acceptance evaluation, with the caveats in sections 6 and 8.
- Real-answer accuracy improvement is **not** claimed: nothing in this work measured it.

## 1. Summary

The evaluator's quantity operator agreed whenever a claim and a passage shared a number of the same kind. It therefore credited claims that:
- reverse a limit ("less than 1 year" against "at least 1 year");
- attach a number to the wrong quantity (0.1 % of twine against 0.1 % of a glycol impurity);
- change the counting convention or scale (15 business vs 15 calendar days; 143 °C vs 143 °F).

This change adds a numeric-limit check inside `operators.compare()`:

| Situation | Outcome | Why |
|---|---|---|
| A **reversed limit** | `limit_direction` conflict; the claim is contradicted | Opposite directions on the same quantity are opposite rules. |
| The **same number with another boundary** (at least vs more than) | Support blocked: unverifiable | Same direction, different boundary. |
| The same number for a **different measured quantity or event** | Support blocked: unverifiable | QSCOPE: the number belongs to something else. |
| The same number in a **different day-count convention or temperature scale** | Support blocked: unverifiable | DAYQ, extended to °C/°F. |
| A **reversed age threshold** | Support blocked: unverifiable | It names another population, not a reversed limit. |
| A **negated verb directly governing a limit** ("shall not be retained for more than 1 year") | Read as the reversed limit (≤ 1 year) | NNEG. Any other negation leaves the scope unclear, and the check abstains. |
| Nothing comparable, or an ambiguous reading | No finding | |

**Not included:** JR, PROP, MODREL, EXN, APPL, and no proposition-level logic. No other operator changed.

## 2. Files

| File | Change |
|---|---|
| `src/regulus/accuracy/operators.py` | **modified, +188 / −0 lines** (`operators.diff`): a docstring line, an `intent.stem` import, a new "numeric limits" section, and one hook in `compare()` after the quantity block |
| `tests/test_accuracy_numeric_limits.py` | **new:** 43 tests |
| `tests/fixtures/accuracy_numeric_limit_rows.json` | **new:** 38 rows |

**Verified:**
- No other file under `src/`, `scripts/`, `tests/` or `web/` changed; the other 304 files are identical by SHA-256 (`manifest_before/after.sha256`).
- The 23 benchmark, frozen-input and existing-fixture files are identical (`benchmark_manifest_before/after.sha256`).

**Git:**
- `src/regulus/accuracy/` and `tests/fixtures/` are untracked, so `git diff` cannot show this change. The pre-change package is in `snapshot_before/`.
- Status went from 63 lines to 64. The only new line is `?? tests/test_accuracy_numeric_limits.py`, and no existing line changed (`git_status_before/after.txt`).
- Pre-existing user changes were not touched: no reset, clean, stash or revert.

## 3. Logic and why

**Where it lives:** in `operators.py`, the functions `numeric_limits()`, `compare_limits()`, `measured_quantity_mismatch()` and `convention_mismatch()`, plus the hook in `compare()`.

**What a limit is.** A bound phrase, a number and a unit: `Limit(relation, value, unit, before, after, age)`.
- `before`: stems of the last 4 content words before the limit in its clause.
- `after`: stems of the first 4 content words after it.
- Recognised phrases: ≤ (not to exceed, no more than, at most, up to, within *durations only* …), ≥ (at least, not less than …), < (less than, below, under …), > (exceeding, more than, above, over …). Negation-bearing forms are matched first.
- Units: percent and %, days with a calendar/business/working qualifier, weeks, months, years, hours, minutes, mg, g, kg, ml, l, ppm, ppb, and degrees with **scale kept** ("°F" → `degree f`; a bare "degrees" → `degree`).

**When two limits are compared.** Only when the value and unit are identical (never converted), at least one `before` word is shared, and the `after` words overlap whenever both sides have them.
- **Opposite directions:** a conflict.
- **Same direction, different inclusivity:** blocked.
- **The evidence reads the same quantity two ways:** no finding.

**Negation.**
- A negation inside *another* limit's phrase ("not more than 0.1 percent … not to exceed 0.3 percent") is discounted.
- One modal negation directly before the limited verb flips the relation (NNEG).
- Anything else makes that limit ambiguous, and a claim with an ambiguous limit gets no numeric finding at all.

**On a block,** the `quantity:` agreement for that comparison is withdrawn and recorded as a relation (`not_the_same_limit`). A matching number is never counted toward the Phase 2D two-operator rule there. The block reaches every support path, because all three `compare()` consumers in `verdicts.py` honour `support_blocked`.

**Deliberate deviations from the Phase 2M offline candidate.** Each was found in a critical review of that code, and each has its own test.
1. **Temperature scale.** Offline read "degrees" without a scale and did not read "°F" at all; the existing quantity operator still agrees on 143 °C vs 143 °F. Now °F/°C are distinct units, and a different explicit scale blocks support (NL11, NL28, NL44). The snapshot has 141 sentences with temperature limits (`work/scan_temp_age.json`).
2. **Age thresholds.** "Children under 12 years of age" is a condition on who is covered, not a limit, and offline would have contradicted "over 12". A reversed age threshold now blocks support (NL45, NL46). The snapshot has 313 such sentences.
3. **Multiple limits in one claim.** Offline returned at the first finding, so a strictness difference on one limit could mask a reversal on another. A conflict now takes precedence (NL10).
4. **"%".** Offline's trailing `\b` meant "0.1%" was never read. Now it is (a reader test covers it).
5. **The quantity agreement is withdrawn on a block** (above), so a matching number never counts as agreement there.

## 4. Tests run (actual outcomes)

| Step | Command | Result |
|---|---|---|
| Tests first, on **unchanged** production (only the constant's name supplied, `work/run_tests_first.py`) | pytest on the new file, excluding the 4 reader tests that need the new API | **20 failed, 19 passed** (`tests_first_behavioural.txt`). All 11 reversed limits and all 9 boundary/blocked rows fail; all 9 equivalent and 9 abstention rows pass, so they act as non-regression guards. Without the name: 42 failed, 1 passed (`tests_first_before_change.txt`). |
| New tests, after the change | `pytest tests/test_accuracy_numeric_limits.py` | **43 passed** |
| Each accuracy test file | `pytest tests/test_accuracy_<x>.py` | all pass: citation_grounding 19, claim_extraction 35, claims 41, **content_gate 240**, contradiction_scope 8, evaluation 31, guidance_logic 29, numeric_limits 43, observer 6, **relative_clause 5 passed + 3 xfailed**, relevance 67, ui 5 (`tests_accuracy_files_after.txt`) |
| Relative-clause assertions | `pytest tests/test_accuracy_relative_clause.py --runxfail` | RC4–RC7 pass. RC1–RC3 fail exactly as their strict-xfail reasons document, the same as before. Markers and assertions are untouched. |
| Full suite, after | `pytest -q tests/ -rs` | **1880 passed, 1 skipped, 3 xfailed, 0 failed** |
| Full suite, before (pre-change package, new file excluded) | `run_suite_variant.py snapshot … --ignore=<new file>` | 1837 passed, 1 skipped, 3 xfailed. The difference is exactly the 43 new tests; no existing outcome changed. |
| Evaluator on/off byte identity (live model, read-only DB, `--offline`, no download) | `scripts/accuracy_regression.py --questions regression_questions.txt --arms both --offline` | **exact evidence PASS, payload arm PASS, live arm PASS**; no question changed by the feature; no nondeterminism (`regression.log`, `artifacts/accuracy/regression_2026-10-09T063859Z.json`) |

**About the live regression:**
- Q1 and Q2 (the Phase 2G questions) have answer bytes and citations **identical to the Phase 2G run**, with the same evidence fingerprints `fa2451337503d884` and `678b0d62c082e609`.
- Q3 (211.180 retention) was added to exercise the new code on a real answer, but the pipeline withheld that answer (pre-existing validation). The withheld answer states no regulatory requirement, so the numeric check had no limit to compare. The new code was not exercised on a live answer.
  - *Correction, added 2026-10-09 during the UI-integration task:* this line first said "0 claims were evaluated". That misread the log line "accuracy: evaluated 0", which means *status evaluated, score 0*. The evaluator did assess the withheld answer, as an incorrect refusal (substantive correctness fail; see `artifacts/accuracy/regression_2026-10-09T070354Z.json`). The conclusion is unchanged.

**Not run:**
- the 300-question benchmark;
- the opt-in slow and integration tests, which are not relevant: they don't import the evaluator's numeric path, and 3 of them fail before this change as well (Phase 2G);
- package installation and model download.

## 5. Protected behaviour

| Safeguard | How checked | Result |
|---|---|---|
| Phase 2D content gate | `test_accuracy_content_gate.py` (240) | **passed** |
| F-007, F-009 incl. **s10** | the 170 frozen row-runs before vs after; the content-gate lock tests | **unchanged** (0 claim changes; para40 F-009 lock passes) |
| 7 relative-clause assertions | test file plus `--runxfail` | **unchanged** (RC4–RC7 pass; RC1–RC3 strict-xfail as before) |
| 19 genuine contradictions | `eval_controls_h.py` on production, before and after | **19/19** both |
| 44 real negation/modality readings | same | **44/44** both; also 18/18 invented-condition, 6/6 readings |
| 170 frozen row-runs | `collect_h.py` + `diff_cf.py` against the reference | **0 claim, answer or dimension changes**, before and after |
| Frozen comparisons | `compare_diff.py` plus a field diff | **0 of 2,103** unique comparisons changed in conflicts, agreements, relations or blocks |
| Evaluator on vs off answer bytes | live regression | **PASS** (above) |
| Rubric and citation checks | rubric unchanged (not edited); `test_accuracy_citation_grounding.py` 19 passed; full suite | **passed** |
| Phase 2I checks / decision cases | `eval_real_controls.py`, `eval_diagnostics.py` | **unchanged** at production's own level: 9/15 and 7/11, same failing IDs, which belong to JR/PROP mechanisms out of scope |

**Not verifiable here:** whether the change improves scores on real generated answers.
- The frozen set contains 4 claim/evidence pairs that share a numeric limit, all genuine agreements, and the change fires on none of the frozen comparisons.

## 6. Limitations and remaining risks

**What the evidence is:**
- All positive evidence for the change comes from **constructed claims** against **verbatim eCFR snapshot text** (38 fixture rows plus the Phase 2L/2M labelled sets).
- On those sets, credited wrong claims fall from 19 to 0 (fixture rows), and false supports fall from 21 to 7 on the Phase 2M sets; the remaining 7 are non-numeric. False contradictions are unchanged at 6.
- The snapshot is **not** the exact evidence of a model prompt.

**Known gaps:**
- **No unit conversion.** 12 months vs 1 year, ppm vs percent, and parts per million spelled out are never compared. That is safe, but those reversals are missed.
- **Exact values only.** Nested or overlapping ranges (a claim of ">0.1 %" against an evidence limit of "≤0.3 %") are not judged.
- **Scope is lexical.** "Same quantity" means sharing a word before the limit, and a word after it when both sides have one. A generic shared word could pair different quantities. Mismatched wording for the same quantity blocks credit, which is a possible false negative but never a false support.
- **NNEG** reads only "shall/must/may/will not (be) <verb> (for/to/by) <limit>". "Need not", "stored at", quantifier negations and double negations abstain.
- **Age detection** relies on "of age" or "old" after the number. Other population thresholds ("infants up to 12 months") are read as ordinary limits.
- **The minimum vs maximum rule:** "≤ X" against "≥ X" is a conflict even though X itself satisfies both, because a minimum and a maximum are opposite rules. Example: NL09, "shall not be retained for more than 1 year" against "at least 1 year".

**Out of scope, unchanged:** N12 ("may not exceed" read as a modal conflict), NN2 and the "exemption" polarity reading, cross-sentence negation, and applicability. These remain as Phase 2M recorded them.

**Labels changed during this task.** NL56 and NL57 (the same number for a different event) were first labelled `no_finding`, a label taken from the Phase 2M probes, which only checked limit direction.
- The implementation also blocks support there, which is the intended behaviour: a number bounding a different event is not agreement.
- They were relabelled `not_the_same_limit` (no limit conflict, support blocked, not credited; final verdict not asserted, because pre-existing strength/polarity conflicts decide it).
- The first version is kept as `work/fixture_v1_before_relabel.json`.
- No existing test or label was changed.

## 7. Final state

- **Changed:** `src/regulus/accuracy/operators.py`.
- **New:** `tests/test_accuracy_numeric_limits.py`, `tests/fixtures/accuracy_numeric_limit_rows.json`.
- **Whitespace:** `git diff --check` is clean on tracked files; its only output is a CRLF notice about a pre-existing user file, `docs/model_dashboard_architecture.md`. The three new or changed files have no trailing whitespace or tabs. The fixture ends without a final newline, like every existing fixture.
- **Compiles:** yes (`py_compile`).
- **Database:** read-only only, and asserted. All database access (fixture texts, the live regression) went through the server-enforced read-only connection.
- **Unchanged:** dependencies, benchmark files and the rubric.
- **Generated (all untracked, under `artifacts/accuracy/`):** this folder, and `regression_2026-10-09T063859Z.json` from the regression script.

## 8. Readiness

**Ready for a controlled acceptance evaluation.** The change is local, additive and reversible: restore `snapshot_before/accuracy/operators.py` and delete the two new test files. Every protected check passes, and the frozen data and live answers are unchanged.

**What an acceptance run can and cannot show:**
- On the frozen data the change is inert, so any score change in an acceptance run would come from answers that state numeric limits.
- That is precisely the population whose real-answer behaviour is unmeasured.
- Recommendation: review score changes on numeric rows **claim by claim**, distinguishing new contradictions (reversed limits) from new unverifiable outcomes (blocked supports), before drawing accuracy conclusions.

## Artifacts

- **Pre-change state:** `snapshot_before/`, `manifest_before.sha256`, `benchmark_manifest_before.sha256`, `git_status_before.txt`.
- **Post-change state:** `manifest_after.sha256`, `benchmark_manifest_after.sha256`, `git_status_after.txt`.
- **The change:** `operators.diff`.
- **Test runs:** `tests_first_*.txt`, `tests_accuracy_files_after.txt`, `tests_full_suite_{before,after}.txt`, `tests_relative_clause_runxfail_after.txt`.
- **Protected checks:**
  - `protected_battery_{before,after}.txt`, `frozen_170_diff.txt`, `frozen_compare_diff.txt`, `error_counts.txt`;
  - `work/` holds the harness scripts and their JSON outputs, `rows_before.json` / `rows_after.json`, the fixture builder `build_fixture.py`, and `scan_temp_age.py`.
- **Live regression:** `regression.log`, `regression_questions.txt`.
