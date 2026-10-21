# Step 7 — decision on the general-question format change (2026-10-21)

**Decision: REVERT.** The expected benefit was not demonstrated: 0 of the 88 questions the change affects improved.

## The change decided on
- `REGULUS_GENERAL_ANSWER_FORMAT=1` (Step 5 Part B). For general questions, the answer plan's format line, which
  speaks of "the requested provision", is replaced by the existing general-question line plus the keep-conditions sentence.
- Scope: src/regulus/rag/generation.py (+21/-2), src/regulus/system_identity.py (+9/-3),
  tests/test_general_answer_format.py (new, 104 lines). Exact patch: change_under_test_part_B.patch (this directory).
- Default off. With the switch unset the pipeline fingerprint is 6cd19913…, the baseline (arm A).
- Not part of this decision: Step 5 Part A (the app locked to Qwen3-1.7B MLX 4-bit), which is not a pipeline change.

## Evidence and comparison basis
Step 6 (RESULTS.md, PREREGISTRATION.md): paired A/B on the 100 cosmetics questions. Same model (Qwen3-1.7B MLX 4-bit,
revision 21457c6f, confirmed on 200/200 responses), same app path, code and session; only the switch differs. Blind
scoring with the fixed 20 Oct rubric. Run-to-run noise on byte-identical prompts: 0 of 12 answers changed.

| | A: off (baseline) | B: on |
|---|---|---|
| PASS / PARTIALLY PASS / PARTIALLY FAIL / FAIL | 2 / 2 / 9 / 87 | 2 / 2 / 8 / 88 |
| Delivered answers / declines / withheld / fallback | 15 / 79 / 4 / 2 | 10 / 71 / 17 / 2 |
| Fabricated / citation exact | 0 / 12 | 0 / 12 |
| Wrong answers delivered | 4 | 0 |

## Decision rules applied
| Rule | Met? | Evidence |
|---|---|---|
| KEEP: intended 1.7B MLX 4-bit model used | Yes | 200/200 responses and 202/202 records name it; no fallback possible |
| KEEP: predefined primary criterion (improvements > regressions) | **No** | 0 improved, 1 regressed (COS-82.50-Q1) |
| KEEP: improvement supported by question-level evidence | **No** | no question improved |
| KEEP: no unacceptable regression (citations, grounding, abstention, unrelated behaviour) | Mostly | 0 fabrications either arm; citation exact 12 = 12; 12 questions without the general shape byte-identical; abstention rose (declines + withheld 83 -> 88), costing one partially useful answer and adding a stray [n] marker to 12 declines |
| REVISE: a specific, bounded defect with evidence for a targeted correction | No | the model responds to the new line by declining or by drafts the validator withholds; nothing points to a wording fix, and prompt variants for 1.7B general questions already failed on 20 Oct |
| REVERT: expected benefit not demonstrated | **Yes** | 0 / 88 |
| REVERT: material regressions | Not established | one question, PARTIALLY FAIL -> FAIL |
| REVERT: violates a stated constraint / cannot be verified | No | |
| INCONCLUSIVE | No | the paired, noise-free design over 88 affected questions is enough to say the benefit is absent |

## Question-level wins and regressions
- Regression: COS-82.50-Q1. A gave a directionally right answer with wrong citations (PARTIALLY FAIL); B declines (FAIL).
- No category wins. Category-neutral (FAIL -> FAIL) safety effect: 4 wrong answers delivered in A are not shown in B
  (COS-70.19-Q2, COS-74.2602a-Q1, COS-700.25-Q2, COS-FDCA605-Q3), because B declines rather than answers better.
- 13 declines became drafts that the validator withheld (listed in RESULTS.md); those drafts are not recorded.

## Remaining known limitations
- Scoring is AI-assisted (9 blind scorer agents, one pass, no inter-rater check), not SME-signed.
- Validator false positives cannot be measured from the app: it records only hashes of withheld drafts.
- One question set (100 cosmetics questions); greedy decoding, so one run per arm.
- The dominant limits are outside this change: the key section reached the model in 28 of 80 section-keyed
  questions; 22 questions need FD&C Act text the corpus lacks; 1.7B declines 79 of 88 general questions.

## Rollback status and next action
- Not yet rolled back. With the switch unset (the default), the app already runs the baseline pipeline.
- Next action: remove the Part B code. Restore generation.py (pre-edit sha256 511c62cb…47a3) and system_identity.py
  (4f9fb807…fa6f) from the verified pre-edit copies, delete tests/test_general_answer_format.py, then confirm the
  baseline fingerprint 6cd19913… and the pre-Part-B focused test result (494 passed, the same 4 pre-existing
  failures, 1 skipped). Nothing is committed or pushed.
