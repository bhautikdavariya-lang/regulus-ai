# Regulus Qwen3-1.7B cosmetics failures: diagnosis and fixes (2026-10-22)

**Status:** code changes implemented and unit/regression-tested. The end-to-end 100-question re-run is NOT done: it
was blocked by the app's 2,000 MB memory preflight, and the user deferred the server start. No benchmark score has
changed yet. Baseline for any later comparison: run `cosmetics100_q17_20261022T035901Z` (Qwen3-1.7B MLX 4-bit
21457c6f, commit fbd2e60, 0 PASS / 8 PP / 5 PF / 87 FAIL). A prepared run directory with the identical selection
(sha256 0e632288…) is `cosmetics100_q17fix_20261022T044208Z/`.

## 1. Root causes (verified against the 22 Oct files; classification.json, per question)

| Category | Questions | Main evidence |
|---|---:|---|
| 1 Missing evidence (key section not in prompt) | 51 / 80 CFR-keyed | All required sections exist in the database. |
| 2 Retrieval/ranking | 56 (51 + 5 missing a companion) | First loss (21 Oct traces): section rank below 4th 38, the word "or" read as a search operator 10, coverage caps 9, guidance spending the budget first 3. |
| 3 Evidence present, model declined | 14 | e.g. 74.2052(c), 80.10(a), 82.6(a)(3), 700.18(b), 720.4(e), 740.12(b) were in the prompt (all tier "discovery"). |
| 4 Incomplete (restated, not applied) | 10 | e.g. 82.1205/1321/1327 quote the one-sentence section but never answer "is there a limit?". |
| 5 Incorrect interpretation | 5 | 82.304 inverts 82.5; 710.2 "should" → "must"; 82.50 wrong sections. |
| 6 Validator failure | 1 false negative, 0 false positives | 70.19-Q2 delivered "None (general question) [1]". The 4 withheld drafts were all justly withheld (degenerate loop; decline + unsupported claim; 82.1307 limit misattributed to (a); four certification rules mixed for Subpart D). |
| 7 Knowledge-source gap (FD&C Act) | 22 (20 statute-only) | No statute in the corpus. |
| 8 Other (presentation) | 5 | Echoed "r1:" labels; empty list items "2." "3.". |

**The binding cause is the model, not the prompt or retrieval alone.** New diagnostic (answerstage_extraction_diag_20261022,
pre-registered): asked to quote, per part of the question, the evidence sentence that answers it, 1.7B produced a
correct quote with nothing wrong in only 4–5 of 13 evidence-present questions, and produced a false "answer" for
14 of 15 negative controls (e.g. HCT/P donor rules quoted as colour-additive restrictions; a 700.18 quote that
reverses the answer). Together with the 21 Oct oracle (0/8 general questions answered with verified evidence) and
eight refuted prompt/thinking variants, this shows the 1.7B model does not tell relevant from irrelevant evidence.
Its 80 declines are currently protective: 1 invented requirement against 18 on 0.6B. Making it answer more often
would deliver grounded-looking wrong answers, so no "answer more" change was made.

**710.5:** not missing evidence. Both sentences were in the prompt. The plan made it a "focused" question whose
instruction says "state only what the provision says about the focus… do not describe the rest", and 1.7B kept only
the first of the section's two sentences.

**FD&C Act:** authoritative govinfo USCODE-2024 text already exists locally
(benchmark_verification/…/sources/usc_title21, URL + sha256 logged) for 21 U.S.C. 321, 361, 364, 364a–e, 364h.
It fully covers 17 of the 22 statute-dependent questions; 363, 364f, 364g, 364i, 364j are not fetched
(statute_coverage.json). Ingestion needs a new source type and DB writes. That is data work, not done here; another
session has taken it on.

## 2. Code changes (uncommitted)

| File | Change | Why / evidence |
|---|---|---|
| src/regulus/retrieval/lexical.py | Literal-"or" for general questions' eCFR search now **on by default** (`REGULUS_ECFR_LITERAL_OR=0` turns it off). | Confirmed mechanism: "certification **or** labeling" split the query, filling Part 73 prompts with 21 CFR 1271.90. Re-measured today on the current DB, retrieval-only: key section in context 29 → 33/80, 0 lost; 1271.90 in 9 → 0 contexts; 352-row baseline 264 → 267 targets (+4, −1: L-011 trades 101.54 for 101.13); 0 negative-control contexts changed. |
| src/regulus/system_identity.py | Comment only. | |
| src/regulus/rag/generation.py, answer_plan.py | A focused one-provision question whose EXACT text is ≤ 600 characters no longer gets the topic restriction ("state only… about the focus"). | 710.5. Prompt capture over 452 questions: exactly 6 prompts change (710.2, 710.4, 710.5, 82.1205, 82.1321, 82.1327), 0 of the 352 baseline set. |
| src/regulus/rag/shape_validation.py | "None (general question)" copied as the answer is a prompt echo → classed degenerate. | Validator false negative 70.19-Q2 (strengthens, does not weaken). |
| src/regulus/rag/answer_quality.py, pipeline.py | Remove echoed "rN:" labels and empty numbered items before validation; count recorded in generation metadata. | Replay on 22 Oct answers changes exactly 70.50-Q2, 82.101, 82.203, 82.304, 710.5. Presentation only; no words added or removed. |
| tests/test_retrieval_literal_or.py | Default test updated (on unless =0). | |
| tests/test_q17_answer_stage_fixes.py (new) | 10 tests: 710.5 short-provision scope with real text, long-provision restriction kept, echo classed degenerate, legitimate text untouched, label/empty-item removal. | |

Not changed: the validator's thresholds, the model, quantization, the rubric, the benchmark, the database.

## 3. Tests
- New + literal-or tests: 32 passed.
- Focused regression set (54 files): 1,528 passed, 7 failed, 7 xfailed. All 7 failures also fail on a clean
  checkout of HEAD fbd2e60 (verified in a temporary worktree): 2 accuracy_pass_integrity, 2 answer_length_policy,
  2 answer_quality, 1 answer_validation. So 0 new failures. tests/test_stage6_generators.py fails at collection with a
  pre-existing circular import (untouched code).

## 4. Benchmark comparison
Not run (deferred by the user). Expected effect on the 100 questions, not yet measured:
- 4 Part 73 questions gain their key section; 1.7B may still decline them.
- 70.19-Q2's echo becomes a withheld answer (still FAIL, but no longer a junk answer).
- Cleaner text in 5 answers.
- 710.5 may recover its PASS.
- No large score change is expected.

## 5. Remaining blockers
1. Model capability (decisive): 1.7B declines general questions even with verified evidence, and cannot
   discriminate relevance when pushed to answer.
2. Retrieval: 38 questions lose the key section at section ranking. Previous selection and budget levers were
   zero-sum on 21 Oct.
3. Statute corpus: 22 questions; text available for 17.
4. Source text: some lead-in rows still lack the announced text (e.g. 71.1(c), 73.2725(b)).

## 6. Next recommended action
Run the deferred 100-question re-run (≈10 min once 2,000 MB is free) to confirm these changes end-to-end. Then
take the model-capability decision: evaluate a larger answering model (GPU or remote) on the same 100 questions
with the evidence held fixed. Every measurement so far places the general-question failure in the model.

## 7. Git
Branch main, HEAD fbd2e60 (no commits made). Uncommitted: 7 modified source files plus 1 modified test, and 1 new
test file. Pre-existing untracked work by others is untouched (src/regulus/ingestion/, repair tests and fixtures).
Pre-edit SHA-256s: shape_validation 22149cc9…, answer_quality e9c3df2a…, pipeline 063ba218…, generation 511c62cb…,
answer_plan 5f2a565d…, lexical cb5f0c9c…, system_identity 161b5134…, test_retrieval_literal_or a8ebb7f9….
