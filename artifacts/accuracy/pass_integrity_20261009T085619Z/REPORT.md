# PASS integrity: evaluation reliability

**Date:** 2026-10-09 (started 08:56:19Z). **Branch:** `main`. **No commit.** The 300-question benchmark was not run.

**Summary:**
- **One confirmed false-PASS path, fixed:** a *focused* question answered with only part of the requested provision's on-topic requirements.
- **One unsafe re-pointing case, fixed:** a sentence drawing on two sources could lose its citation to one of them.
- **Every other probed false-PASS shape already fails to PASS,** and is now pinned by tests.
- **One open policy question, not changed:** must every substantive statement carry its own citation? See §6.

## 1. How PASS is decided (traced in code)

`review.question_review` returns PASS only when:
- the assessment status is `evaluated`;
- the answer verdict is `correct` (or a correct refusal);
- **every** dimension is `pass` or `not_applicable`.

The dimensions are decided in `evaluator._evaluate`:

| Dimension | How it is decided |
|---|---|
| Relevance | per claim (`relevance.assess`) |
| Substantive correctness | the answer verdict: any contradicted claim, unverified claim or irrelevant claim prevents `correct` |
| Evidence support | every answering claim decided against evidence |
| Citation | any attached citation that is wrong → fail; no citation at all → fail; an uncited statement in a cited answer → **not** a defect (rubric L, §6) |
| Unsupported claims | validator figure, condition and identifier checks |
| Completeness | validator completeness codes, the question's elements, coverage, `validation.unaddressed`, otherwise "pass if anything answers" |
| Scope | |

## 2. Probes

**Setup.** Real evaluator, verbatim snapshot text, constructed answers (`work/probe.py`, `work/realistic.py`, `work/production_path.py`).

**Already prevented before this change** (each gives FAIL or NOT EVALUATED, never PASS):
- four supported claims plus one fabricated requirement;
- an uncited fabricated requirement beside a correctly cited one;
- a valid marker attached to an unsupported neighbouring sentence;
- a wrong exception (5 years instead of 3);
- an invented exception;
- a correct number attached to the wrong requirement (cited either way);
- §820.35(b) servicing items stated as complaint-record contents;
- correct statements plus a reversed limit;
- several requested paragraphs with only one answered (the validator's `requirement_not_addressed`);
- an answer with no citation at all;
- definitions: a definition plus an unsupported extra claim; a wrong or partial expansion (tests from the previous task).

**Confirmed false PASS, reproduced on the production configuration** (`configured_rag_config`, the real pipeline with validation and repair, scripted model output):

| Question | Delivered answer | Before |
|---|---|---|
| "What are the personnel qualification requirements in 21 CFR 211.25?" (shape `focused`) | §211.25(c) only | **PASS 100** |
| same | §211.25(a) only | **PASS 100** |

All three §211.25 paragraphs state personnel-qualification requirements; the section heading is "Personnel qualifications."

**Root cause:**
- `rag/shape_validation.py` §4 checks group coverage, and repairs it by appending the group, **only in `synthesis` mode**. A `focused` answer is never checked. (The unrestricted "What does 21 CFR 211.25 require?" is synthesis: the pipeline appends (a) and (b), and the delivered answer is complete.)
- `evaluator._evaluate`'s completeness then falls through to "the statements that answer the question cover what it asks for".
- Under the contractual rubric this is **O = 0**: "a material governing requirement is omitted such that a user acting on the answer would be out of compliance".

**Unsafe re-pointing (confirmed):** for "Training shall be in the particular operations … [from (a)], and there shall be an adequate number of qualified personnel … [from (c)] [1]", the previous code moved `[1]` to `[3]`, dropping the citation to §211.25(a), which states the first part.

## 3. Changes

| File | Change |
|---|---|
| `src/regulus/accuracy/evaluator.py` (+59 / −0) | `_focus_gap()`. For a **focused** answer plan, it finds the requirement groups of the requested provision that state an obligation (mandatory modal), are on the question's topic (`relevance.on_topic`, which reads the section heading), and that no answering statement covers (via its decided evidence). If any are found, a completeness **PASS** becomes **FAIL**, naming the groups. If a group is touched only by statements that could not be verified, it becomes **NOT ESTABLISHED** instead. A PASS can only be withdrawn, never granted. It reads only what the RagAnswer carries (the package's answer plan). |
| `src/regulus/rag/citation_repair.py` (+13 / −3) | No re-pointing when a cited source states a run of 5 or more words from the text *outside* the target's verbatim run (a sentence drawing on two sources). Exact text in several sources, paraphrase, a cited source that states the text, and nonexistent sources were already left alone. |
| `tests/test_accuracy_pass_integrity.py` (new, 13 tests) | The fixed path on the production configuration, with positive controls (a complete focused answer; a complaint-records question that does **not** demand §820.35(b) servicing records; an unrestricted question the pipeline repairs) and the pinned negatives. |
| `tests/test_citation_repair.py` (+4 tests) | two-source sentence; a group already naming the stating source; a unique partial quotation; a corrected marker does not hide a contradiction |

**Unchanged:** the rubric and its deduction table, the status rules in `review.py`, the content gate, operators and the numeric fix, the definition fix, claim extraction, retrieval, generation and the pipeline's validation and repair.

## 4. Before and after

| Example | Before | After |
|---|---|---|
| focused §211.25 answer, (c) only | PASS 100 | **FAIL 75**: "does not address 21 CFR 211.25(a), 21 CFR 211.25(b)" |
| focused §211.25 answer, all three paragraphs | PASS 100 | PASS 100 |
| (a) paraphrased (unverifiable) + (c) | FAIL (partial) | FAIL; completeness names (b) only. (a) is "unverified", not "omitted". |
| (a) paraphrased + (b) + (c) | FAIL (partial) | completeness NOT ESTABLISHED (not called an omission) |
| complaint records answered with all of §820.35(a) | — | completeness pass: (b) servicing records not demanded |
| two-source sentence `[1]` | re-pointed to `[3]` | left `[1]` |
| negated claim with a wrong marker | — | re-pointed **and** still FAIL (contradicted) |

**Live** (real engine, local model `--offline`, read-only DB; `work/repro_live.json`). Answers are byte-identical to the previous run, and identical with evaluation on and off, for all 7.

| Case | Before | After | Omitted group named (checked against the regulation) |
|---|---|---|---|
| 1 §211.25 | PASS 100 | PASS 100 | — |
| 2 §312.32 | FAIL 40 | FAIL 15 | (b) review of safety information |
| 3 §314.50 | FAIL 0 | FAIL 0 | (b) index |
| 4 §801.15 | FAIL 40 | FAIL 15 | (c) symbols |
| 5a M-020 §820.35 | **PASS 100** | **FAIL 75** | **(c) "the UDI must be recorded for each medical device or batch"**, a requirement §820.35 adds that the answer leaves out |
| 5b | NOT EVALUATED | NOT EVALUATED | — |
| 6 FDA | PASS 100 | PASS 100 | — |

## 5. Tests and safeguards

- **New / extended:** 13 + 17 passed.
- **Discrimination:**
  - against the pre-fix evaluator, exactly the 4 tests of the new behaviour fail (the pinned negatives and positives pass on both);
  - against the previous re-pointing code, the two-source sentence is wrongly re-pointed.
- **Full suite:** **1994 passed, 1 skipped (pre-existing), 3 xfailed (RC1–RC3, unchanged), 0 failed.**
- **Frozen safeguards:**
  - 170 row-runs: 0 claim, answer or dimension changes; 984 claims;
  - 0 of 2,103 comparisons changed;
  - 19/19 genuine contradictions, 44/44 real readings, 18/18 invented-condition cases;
  - F-009 s10 unchanged.
  - The frozen packages carry no focused answer plan, so the check does not apply to them.
- **Unchanged and passing:** content gate (240), numeric limits (43), definition fix (16 + 17), observer on/off equivalence (6).
- **Repository state:**
  - only the 4 files above changed;
  - benchmark, frozen and fixture files identical;
  - git status 71 → 72, adding only the new test file;
  - LF files stayed LF.

## 6. Open policy question (not changed)

Case 1 (§211.25) is PASS with 4 of its 5 statements carrying no marker of their own. All of them are verbatim and verified against the retrieved evidence.

**This is what the contractual rubric prescribes.** `docs/STAGE_A_RUBRIC.md` column L:
- **1** = "every citation **attached to a statement** is correct …";
- **0** = "any citation is to the wrong section or paragraph, **or** the answer is correct but carries **no citation at all**".

The evaluator implements exactly that (`evaluator.py`, citation block; its comment cites acceptance row C-004 scored L=1 with one uncited sentence). Each uncited statement is still flagged at claim level (`supported_with_citation_defect`).

Requiring a citation on **every substantive statement** would be a stricter standard than L. It would conflict with how the frozen benchmark was scored. I have not invented it: it needs your decision.

**What is guaranteed today:**
- an uncited statement is still verified against the evidence (unsupported → not PASS);
- one valid citation cannot make an unsupported statement PASS (probes A2, A3).

## 7. Remaining limitations

- **The completeness check applies to focused answers only.**
  - Direct answers are exempt by the pipeline's design ("says what something is").
  - Synthesis answers are already checked and repaired by the pipeline.
- **"Requirement group" is the pipeline's paragraph grouping, filtered to groups with a mandatory modal.**
  - A material requirement phrased without "shall/must" is not demanded.
  - A long section with many on-topic mandatory paragraphs makes completeness strict: an answer that summarises well but skips one paragraph FAILs (as cases 2 and 4 now do). That is consistent with rubric O = 0; it is not a measured calibration.
- **Topic matching is lexical** (`on_topic`, including the section heading). A heading that shares the question's words puts every mandatory paragraph of the section in scope.
- **Case 5b** (cross-subsection items) remains NOT EVALUATED, not FAIL. It is still never PASS.

**Impact:** these changes improve **evaluation reliability**: false PASSes are removed, and the PASS rate on these questions went down. They do not change any delivered answer. No improvement in actual answer accuracy is claimed or measured.

## Artifacts

- `snapshot_before/`, `changes.patch`, `manifest_*`, `benchmark_manifest_*`, `git_status_*`;
- `work/` (probes, realistic and production-path harnesses, live repro);
- `frozen/` (170-row battery);
- `tests_full_suite_after.txt`.
