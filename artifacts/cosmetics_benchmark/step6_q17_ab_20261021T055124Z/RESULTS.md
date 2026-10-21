# Step 6 results — controlled A/B on Qwen3-1.7B MLX 4-bit (2026-10-21)

Pre-registration: PREREGISTRATION.md (sha256 4c004cc5…, written 05:51 UTC, before any answer). Raw data:
arm_A_switch_off/ and arm_B_switch_on/ (results.jsonl, responses/, ui_measurements/, serve_ui.log, runner.log,
run_log.jsonl), scoring/ (packets, blind verdicts, blind_map.json, facts.json, analysis.json).

## Set-up as run
- Model, both arms: Qwen/Qwen3-1.7B MLX 4-bit g128, revision 21457c6f51ed54a7c16e988c0844db973815c137, MLX worker
  (mlx 0.32.3, mlx-lm 0.32.0), greedy. Confirmed on all 100 responses and all 101 measurement records per arm
  (100 questions + warm-up). No load failure, no fallback; the server could not have used another model.
- Path: scripts/serve_ui.py /api/ask, the 20 Oct client unchanged, one question at a time, warm-up excluded.
- Code: identical at start and finish of both arms (HEAD 6f94938, tracked diff d5c4fbb5…, 232 changed/untracked
  files, combined 282b2c4d…). Only difference: REGULUS_GENERAL_ANSWER_FORMAT (A off: pipeline 6cd19913…, B on: 5443a944…).
- Questions: the same 100 as 20 Oct (selection.json 0e632288…); key Regulus_QBank_Cosmetics_REV01.xlsx.
- Scoring: the 20 Oct rubric and category mapping, unchanged; 131 distinct (question, answer) items scored by 9
  blind scorers (arm hidden; identical answers scored once; differing pairs side by side in random order).
- Baseline: no same-model baseline existed; arm A is a new same-model, same-runtime, same-session baseline.
  The 20 Oct 0.6B result (1 / 2 / 14 / 83) is historical only: different model and a different scorer.

## Results
| Category | A: switch off | B: switch on |
|---|---|---|
| PASS | 2 (2%) | 2 (2%) |
| PARTIALLY PASS | 2 (2%) | 2 (2%) |
| PARTIALLY FAIL | 9 (9%) | 8 (8%) |
| FAIL | 87 (87%) | 88 (88%) |
| NOT EVALUABLE / NOT EVALUATED | 0 / 0 | 0 / 0 |
| Substantive 2 / 1 / 0 | 4 / 9 / 87 | 4 / 8 / 88 |
| Completeness 2 / 1 / 0 | 2 / 11 / 87 | 2 / 10 / 88 |
| Citation exact = 1 | 12 | 12 |
| Fabricated = 1 | 0 | 0 |
| Scope failures | 0 | 0 |
| Delivered: answer / decline / withheld / fallback | 15 / 79 / 4 / 2 | 10 / 71 / 17 / 2 |
| Wrong answers delivered (validator false negatives: delivered, Substantive 0) | 4 | 0 |
| Answers given with no key section in evidence | 3 | 0 |
| Execution errors / timeouts / load failures | 0 / 0 / 0 | 0 / 0 / 0 |
| Seconds per question, mean (median) | 4.17 (3.4) | 4.06 (3.4) |
| Input / output tokens, mean | 1,429 / 57.5 | 1,399 / 56.2 |

Same in both arms (the switch cannot change them): retrieval identical on 100/100; key section in evidence for
28 of 80 section-keyed questions; 22 questions keyed to the FD&C Act (not in the corpus); required evidence cut by
the context budget on 5 questions. Validator false positives (correct drafts withheld) cannot be measured: the UI
records only hashes of withheld drafts.

## Paired comparison
- The switch changed the prompt of the 88 general questions; 31 answers changed. The 12 questions with
  byte-identical prompts gave byte-identical answers (run-to-run noise 0).
- Improvements: none (0 of 88).
- Regression: COS-82.50-Q1, PARTIALLY FAIL -> FAIL. A delivered a directionally right answer (batch usable in
  cosmetics if it meets 82.5 and the subpart specifications) with wrong citations (82.1050/82.2050); B declines.
  The key section 82.50 was not in the evidence.
- Category-neutral changes (FAIL -> FAIL):
  - 4 wrong answers delivered in A are no longer delivered in B: COS-70.19-Q2 ("None (general question) [1]",
    an echo of the prompt), COS-74.2602a-Q1 (says no particular requirement applies; the key requires part 80
    certification), COS-700.25-Q2 (misleading on exemption), COS-FDCA605-Q3 (a wrong 15-business-day figure).
  - 13 declines became drafts the validator withheld: COS-71.26-Q1, COS-73.2095-Q1, COS-74.2052-Q1,
    COS-74.2304-Q1, COS-74.2322-Q1, COS-80.10-Q1, COS-700.35-Q1, COS-701.13-G1, COS-720.4-Q3, COS-FDCA607-Q2,
    COS-FDCA609-Q1, UC-COS-011, UC-COS-021. 1 withheld became a decline (COS-74.2208-Q1).
  - 12 declines gained a stray source marker ("... to answer this. [1]").

## Decision (rule fixed in PREREGISTRATION.md)
KEEP needs improvements > regressions: 0 vs 1, not met. REVERT applies (improvements <= regressions).
Recommendation: REVERT. The change's purpose was to turn general-question declines into supported answers; it
turned none of the 88 into a better answer. Its only benefit, 4 wrong answers no longer shown, comes from the model
declining more, not from better answers, and costs one partially useful answer. The 1-question category difference
is within what this design can resolve, so the harm is not established; the absence of benefit is.
