# Evidence-oracle experiment: pre-registration (written before any inference in this task, 2026-10-21)

## Reuse, not repetition
- **Condition B already ran.** It is Step 3 of this programme: 2026-10-21 04:58Z, Qwen3-1.7B MLX 4-bit, the same 12 questions.
- **Its working files were lost** when the session scratchpad was emptied. This folder holds what was recovered from
  the session transcript (recovered_step3/):
  - the harness oracle_run.py (sha256 c9bfee3e…);
  - the packet builder build_packets.py (2d9cdcef…);
  - the pre-registered checklist criteria.json, sha256 66354f8a…, byte-identical to the hash recorded when it was
    written at 04:56:35Z, before Step 3's inference;
  - the 12 raw model outputs with their token counts (recovered_outputs.json).
- **One verified restoration run.** Condition B is re-run once with the recovered harness and rebuilt packets, only
  to restore complete artifacts (the full prompts, and the full delivered text of COS-70.50-Q2). Decoding is greedy,
  and Step 6 measured 0 run-to-run differences on identical prompts.
- **Validity rule, fixed now:** the restoration counts only if:
  - every raw output equals the recovered Step 3 raw output byte for byte;
  - the delivered text of COS-82.101-Q1 equals the recovered full text;
  - COS-70.50-Q2's delivered text starts with the recovered first 900 chars and ends with the recovered last 1,500.
- **If any check fails,** the recovered Step 3 text is the record, and only questions with complete recovered text
  are scored. This is not a new attempt: nothing is changed and nothing is retried.
- **Condition A is not re-run.** It is Step 6 arm A (artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off):
  the same model through the production app path, with saved prompt evidence, answers and blind verdicts.

## Model and runtime (both conditions)
- Model: Qwen/Qwen3-1.7B, MLX 4-bit (g128), revision 21457c6f51ed54a7c16e988c0844db973815c137.
- Worker: scripts/mlx_worker.py on mlx 0.32.3 / mlx-lm 0.32.0. Greedy decoding, thinking off.
- Tokenizer: tokenizer.json and tokenizer_config.json are byte-identical between the caches used by A and B.
- Same RagPipeline, prompt template, validator and repair code. generation.py is at the pre-Part-B hash 511c62cb.
  The literal-OR switch is off and is overridden by the oracle retriever in any case.
- Known differences, besides the evidence:
  - A runs through serve_ui; B runs the pipeline directly.
  - B raises the context limits to the hard ceilings (24 sources, 4,000 chars each, 9,000 total) so the whole packet is
    delivered. In Step 3 this mattered only for COS-720.4-Q3.

## Sample (12) and reasons
| ID | Condition A (1.7B pipeline) | A evidence coverage | Failure category | Why included |
|---|---|---|---|---|
| COS-710.5-Q1 | PARTIALLY PASS (answer) | full | evidence present | control |
| COS-70.50-Q2 | PASS (answer) | full | evidence present | control; careful conditions (external use) |
| COS-70.3-Q3 | PASS (definitions-quoted fallback, not model text) | full | evidence present | control; definitions and exemption conditions |
| COS-700.18-Q1 | FAIL (decline) | full | wrong despite evidence | residue-vs-ingredient exception |
| COS-82.101-Q1 | PARTIALLY FAIL | full | wrong despite evidence | wrong-subpart limits risk |
| COS-82.1321-Q1 | PARTIALLY FAIL | partial | wrong despite evidence | invented-restriction risk |
| COS-740.12-Q1 | FAIL (decline) | partial | wrong despite evidence | inverted-rule risk; 740.12(b) row truncated in DB |
| COS-720.4-Q3 | FAIL (decline) | partial | wrong despite evidence | exception that flips the answer |
| COS-80.10-Q1 | FAIL (decline) | partial | wrong despite evidence | fee arithmetic, payment method |
| COS-73.2725-Q1 | FAIL (decline) | none (all 1271.90) | AND-leg gate (not retrieved) | Part 73; 73.2725(b) truncated in DB |
| COS-74.2317-Q1 | FAIL (decline) | none | section-coverage ranking | ranking problem |
| COS-700.15-Q1 | FAIL (decline) | none (wrong paragraph) | 2-row cap | selection problem |

## Evidence packets
- Rows are built by recovered_step3/build_packets.py from the live read-only database (snapshot 2026-09-03).
- Each row carries its citation, sha256 and snapshot_date.
- Rows are checked against Step 3's printed packet text (recovered_step3/packet_printout_0454.txt).
- Nothing is repaired. Elements absent from the stored text are listed in criteria.json `not_in_evidence` and are not
  expected from either condition:
  - the 740.12(b) caution wording;
  - the 73.2725 specification values;
  - the 74.101 values.

## Scoring (fixed now, identical for A and B)
- **Benchmark rubric:** the Step 6 SCORER_INSTRUCTIONS.md, unchanged. ce, fab, sub 0–2, comp 0–2 and scope are mapped
  to PASS / PARTIALLY PASS / PARTIALLY FAIL / FAIL by the Step 6 `category()`. NOT EVALUABLE only where the scoring
  basis genuinely fails.
- **Question checklist:** criteria.json (required elements R1…, critical errors, cite), marked present / absent /
  contradicted per answer.
- **Dimensions reported:**
  - regulatory correctness (sub);
  - completeness (comp, and required elements present);
  - citation accuracy and support (ce, and whether cited sources support the claims);
  - conditions and exceptions (critical errors and condition elements);
  - abstention (was a decline appropriate given that condition's evidence?).
- **Blindness:** both conditions' answers are scored side by side per question, in random order, unlabelled. Scorers
  also see the evidence each answer was given. Adversarial verifiers re-check the scores. Not expert-validated.

## Interpretation and decision rules (fixed now)
- **Per question:**
  - *evidence-sensitive improvement*: B ranks higher than A, and A's evidence lacked a required element;
  - *generation failure persists*: B is FAIL or PARTIALLY FAIL with a sufficient packet;
  - *citation/validation problem*: content correct (sub 2) but ce = 0 or validator/repair defects;
  - *inconclusive*: the packet is insufficient or the comparison is invalid.
- **Result A (prioritise retrieval):** at least 3 of the 9 non-control questions move from FAIL/PARTIALLY FAIL in A to
  PASS/PARTIALLY PASS in B, and no control drops.
- **Result B (prioritise answer generation):** at most 1 of the 9 improves, and at least 5 remain FAIL/PARTIALLY FAIL
  with a sufficient packet.
- **Result C:** anything else.
- **Result D:** the restoration fails and fewer than 9 questions have complete text, or any model-identity check fails.
