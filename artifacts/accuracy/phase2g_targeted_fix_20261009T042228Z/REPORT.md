# Phase 2G: targeted contradiction fix (implementation and verification)

**Verdict: PASS**

The two approved `VT_targeted` rules from Phase 2F are implemented in `operators.py`. Permanent regression tests were written first, failed on the old code, and pass on the new. The production result is identical to the offline candidate across all 170 row-runs and all 5,829 operator comparisons. Nothing else changed.

## 1. Files changed

| File | Change | Purpose |
|---|---|---|
| `src/regulus/accuracy/operators.py` | modified: +32 / −1 lines (`operators.diff`) | the two rules |
| `tests/test_accuracy_contradiction_scope.py` | new: 8 tests | H-003, D-009, mandatory-channel negative controls, guards |
| `tests/fixtures/accuracy_contradiction_rows.json` | new | rows H-003 and D-009, copied verbatim from the frozen inputs (legacy-reconstructed) |

No other file under `src/`, `scripts/`, `tests/` or `web/` changed. This was verified by a SHA-256 manifest before and after (`manifest_before.sha256`, `manifest_after.sha256`).

`src/regulus/accuracy/` and these tests are **untracked in git**, so `git diff` cannot show the change. The pre-change copy is in `snapshot_before/`.

## 2. Implementation

**Rule 1: negation scope (D-009).**
- The bare `\bnot\s+required\b` alternative is removed from `_NEGATE_RE`. `polarity()` is its only user.
- "is/are/was/were not (required)", "shall/must not", "need not", "does not apply" and the other alternatives still mark a negated duty.
- So "drug products **not required** to be sterile" no longer negates 211.113(a)'s "shall be established and followed".

**Rule 2: permission over a means (H-003).**
- `compare()` has a new branch in its strength block, after the guidance branch and before the conflict branch. It records the relation `permission_over_means` (operator undetermined) instead of a conflict.
- All four conditions must hold:
  1. one side is permissive and the other mandatory;
  2. the permissive main clause has a means marker after its modal (*through, via, using, by means of, by way of, either*);
  3. the verb after the modal also appears in the mandatory main clause;
  4. the mandatory main clause names **no** means of its own.
- If any condition fails, the modal conflict stands.
- Guidance modality handling is untouched: the guidance branch runs first.

**Untouched:** claim extraction, alignment, the Phase 2D content gate (`verdicts.py`), answer aggregation, rubric, retrieval, generation, prompts, citations.

## 3. Test results (commands run in this phase)

**New tests first.**
- Command: `pytest -q tests/test_accuracy_contradiction_scope.py`
- Before the change: **4 failed, 4 passed.** The 4 defect tests fail; the guards and negative controls pass.
- After the change: **8 passed.**

**Relevant files after the change:**

| Test file | Result |
|---|---|
| contradiction_scope | 8 passed |
| claims | 41 passed |
| guidance_logic | 29 passed |
| content_gate (203 labelled Phase 2C/2D instances + gate controls) | 240 passed |
| claim_extraction | 35 passed |
| citation_grounding | 19 passed |
| relevance | 67 passed |
| evaluation | 31 passed |
| observer | 6 passed |
| evidence_traceability | 19 passed |
| ui | 5 passed |

**Full suite.**
- Command: `pytest -q tests/ -rs`
- Result: **1832 passed, 1 skipped, 0 failed**, 47 deselected. That is 1824 before plus the 8 new tests.
- The skip is pre-existing: `tests/test_dashboard_health.py:576`, "no current evaluation in this repository".

**Opt-in integration and slow tests.**
- Command: `pytest -q -m "integration or slow" tests/`
- Result: **44 passed, 3 failed.**
- All 3 **fail identically on the pre-change code** (`run_tests_before.py`, which loads `snapshot_before/`). None of them imports `regulus.accuracy`:
  - `integration/test_rag_slow.py::test_rag_end_to_end_one_question`: context of 4,828 characters against a limit of 3,600. Already documented in Phase 2D.
  - `test_evaluation_smoke.py::test_single_question_end_to_end`: `assert 0 == 1`.
  - `test_model_smoke.py::test_model_generates_text`: `TypeError: 'module' object is not callable`.

## 4. H-003, D-009 and the negative control

| Case | Before | After |
|---|---|---|
| **H-003** channel claims ("you may submit … through either ABI/ACE/ITDS or FDA PNSI"; "… through FDA PNSI") vs 1.279(a) | CONTRADICTED (strength conflict); answer **incorrect, 0** (both aligners) | **unverifiable** (`not_decisive`; the relation `permission_over_means` is recorded; the gate does not establish the channel rule); answer **unverifiable** (both aligners) |
| **D-009** "Written procedures shall include control of microbiological contamination …" | 211.113(a) discarded (polarity conflict); unverifiable | **credited (paraphrase) by 21 CFR 211.113(a)**, both aligners. The final status is "irrelevant": the relevance layer judges it off this row's question (component testing). Answer unchanged (partial 40 / 35). |
| **Negative control C1**: "may submit … through either ABI/ACE/ITDS or email" vs "must submit … through FDA PNSI; … through ABI/ACE/ITDS or by email is not accepted" | — | **CONTRADICTED**; answer **INCORRECT** |
| **Negative control C2**: the same permission vs "must submit … through FDA PNSI" (names its channel, no exclusion) | — | strength conflict kept; **CONTRADICTED**; no `permission_over_means` relation |
| **Guards** | — | A permission without a means (820.30(a) "may establish" vs "shall establish"), and a means over a different act ("store … using" vs "retain"), keep the modal conflict. Copula "are not required" (117.136(a)) and "need not" (211.130) are still NEGATE. |

The C1/C2 texts are **constructed** in 1.279's wording. No captured regulation in the repository mandates one named channel and excludes the others. The test file states this.

## 5. Phase 2D and production safety

**Phase 2F verification, re-run on production code** (`work/`; the Phase 2F inputs were copied here and the Phase 2F folder left untouched):

| Check | Result |
|---|---|
| Recorded comparisons (5,829) and all 170 row-runs | **identical to the offline `VT_targeted`** |
| Claim changes | exactly 6: D-009 ×2 arms credited; H-003 2 claims × 2 arms contradicted → unverifiable |
| Answer changes | exactly 2: H-003 ×2 arms, incorrect 0 → unverifiable |
| CONTRADICTED claims | 6 → 2. The remaining one claim × 2 arms is D-019's garbled invented-condition claim, out of scope. |
| Genuine-contradiction controls | **19/19 kept** |
| Real operator readings | 44/44 kept |
| Invented-condition cases | 18/18 unchanged |
| Verbatim reading tests | 6/6 |
| False operator conflicts removed | 10/88 (the 8 bare "not required" + H-003's 2) |
| New conflicts | 1, unmasked: D-001's "batches that do not conform" vs 211.113(a). It changes no verdict. |
| **F-007, F-009** | unchanged at claim and answer level (F60 and REAL17, both aligners). No new credit, no lost credit. |
| Named controls D-001, D-002, D-008, C-004, E-007, H-001, H-006, K-003, G-004, M-020 | answer verdict, score and every claim **unchanged** (F60 / GUIDE8 / REAL17, both aligners) |
| Credit transitions | only D-009 uncredited → credited (intended). No other support credit gained or lost. |

**Live evaluator ON/OFF.**
- Command: `scripts/accuracy_regression.py --arms both`, giving `artifacts/accuracy/regression_2026-10-09T043045Z.json`.
- Payload arm PASS, live arm PASS, exact evidence PASS.
- Answer bytes, citations, evidence, prompt SHA-256, model calls and evaluator replay are identical to the Phase 2D run (`regression_2026-10-08T093941Z.json`): **0 non-timing differences**.
- Fingerprints are unchanged: `fa2451337503d884…`, `678b0d62c082e609…`.

**Unchanged:** benchmark dataset, frozen inputs, scoring criteria, retrieval and generation code. `serve_ui` was not running and was not touched. No 300-question run.

## 6. Limitations

- **Legacy evidence only.** H-003 and D-009 are verified on **legacy-reconstructed** evidence (the frozen acceptance inputs). Neither has an exact prompt-evidence snapshot. The live regression covers two other questions, so it is not an exact-evidence validation of either row.
- **The channel rule's boundary is pinned only by constructed controls**, because no real mandated-channel text exists in the repository's evidence.
- **Not validated corpus-wide.** Removing the bare "not required" was checked against the 954 captured texts, where every bare occurrence was a modifier. It was not checked against the whole eCFR snapshot.
- **78 of the 88 false operator conflicts from Phase 2F remain, by design**, as does the claimed-exception pattern. Neither is in this phase's scope.

## 7. Git

- **Before:** 61 status lines.
- **After:** 62. The only new line is `?? tests/test_accuracy_contradiction_scope.py`. `operators.py` and `tests/fixtures/` were already untracked, so they add no lines.
- No other status line changed. No commits were made.

## Artifacts

- **Pre-change state:** `snapshot_before/` (accuracy package and tests), `shim_before/`.
- **Diffs and manifests:** `operators.diff`, `manifest_before.sha256`, `manifest_after.sha256`, `git_status_before.txt`, `git_status_after.txt`.
- **Verification:** `work/` (Phase 2F scripts and controls; `compares_production_2G.json`, `controls_result_production_2G.json`, `verdict_diffs.json`), `regression.log`, `regression_questions.txt`, `run_tests_before.py`.
