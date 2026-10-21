# Step 6 — controlled A/B, written before any answer was generated (2026-10-21 05:51 UTC)

## What is evaluated
- Change under evaluation: `REGULUS_GENERAL_ANSWER_FORMAT=1` (Step 5 Part B). For a general question (prompt says
  "REQUESTED PROVISIONS: none (general question)"), the final ANSWER FORMAT line becomes the existing
  general-question line + the keep-conditions sentence, instead of the answer plan's line (which speaks of
  "the requested provision"). Provision and docket prompts are byte-identical with the switch on or off.
- Arm A (baseline): switch OFF — pipeline_config_sha256 6cd19913cc7b83b4302d1bffdfb439fc2384ab7ca51a8af4adc84cbd2627796c
  (identical to the 20 Oct cosmetics run's pipeline fingerprint).
- Arm B (treatment): switch ON — pipeline_config_sha256 5443a944f5077d9bff3f7a7b6a114f31c9f2f4d6a7b17a9a0771139bf04c8211.
- Code: HEAD 6f949381550fb96e49219a1b8679b3806b1126e5 + uncommitted tree (tracked diff vs HEAD sha256
  d5c4fbb5e48311ded40167bc41b710a1de3fe556d587ff53213bc56b99526137); full per-file fingerprint logged by the runner
  at start and finish of each arm. generation.py 5c0defb7…, system_identity.py 2e4cb276…, serve_ui.py 5fbd65c8….

## Model and runtime (both arms, nothing else)
- Qwen/Qwen3-1.7B, MLX 4-bit (group size 128), snapshot revision 21457c6f51ed54a7c16e988c0844db973815c137,
  run by scripts/mlx_worker.py under ~/regulus_eval_runs/q17_feasibility/mlx_venv (mlx 0.32.3, mlx-lm 0.32.0).
  Greedy decoding, thinking off. Tokenizer: the loaded Qwen3 tokenizer, tokenizer.json byte-identical to the
  snapshot's (checked at start-up by serve_ui).
- Application path: scripts/serve_ui.py (Step 5A: this model only, no fallback; a load failure stops the server),
  POST /api/ask on 127.0.0.1:8765, one question at a time, by the unchanged 20 Oct client
  (cosmetics100_20261020T124217Z/tools/run_benchmark.py), warm-up "What does 21 CFR 11.10 require for closed
  systems?" excluded from all statistics. Server flags identical across arms: --port 8765 --offline
  --accuracy-alignment lexical (no second model loaded; the live evaluator never decides a category).
- Each response's `model` field and each measurement record's run.model are checked to name Qwen/Qwen3-1.7B,
  backend mlx, 4-bit, revision 21457c6f. Any other value invalidates the arm.

## Question set and rubric (fixed)
- The same 100 questions as the 20 Oct run: selection.json sha256 0e63228864bc3b67d7ae7022662100babd05b7b701da87a3e52c1742da9e15c4,
  from Regulus_QBank_Cosmetics_REV01.xlsx (sha256 c7d4e026…); scored against its VERIFIED key.
- Rubric: unchanged from the 20 Oct run (build_workbook.py MAPPING_TEXT + fabrication rule in
  scoring/fabrication_review.json): Citation Exact 0/1, Fabricated 0/1, Substantive 0-2, Completeness 0-2,
  Scope 0/1, mapped deterministically to PASS / PARTIALLY PASS / PARTIALLY FAIL / FAIL; NOT EVALUATED only when no
  answer was returned. A decline or withheld answer on a question the key answers is FAIL.
- Scoring is blind to arm: each distinct (question, delivered answer) is scored once; identical answers in both
  arms share one score. Where the arms differ, both answers are scored side by side in random order, unlabelled.

## Baseline status
- No same-model baseline exists for this question set: the 20 Oct cosmetics run used Qwen3-0.6B (transformers,
  CPU); earlier 1.7B runs used the REV02 300-question set through scripts. Arm A is therefore a NEW same-model,
  same-runtime, same-session baseline. The 0.6B results are historical context only and are not compared to.

## Decision rule (primary comparison: paired A vs B, category order FAIL < PARTIALLY FAIL < PARTIALLY PASS < PASS)
- KEEP: improvements > regressions, AND no new Fabricated=1, AND no new wrong answer on a question whose key says
  the regulation does not cover it / must be declined, AND non-general questions unchanged (byte-identical prompts).
- REVERT: improvements <= regressions, or the change introduces a fabrication or a safety regression that its
  improvements do not clearly outweigh.
- REVISE: improvements > regressions but with at least one new fabrication / safety regression attributable to
  the change.
- With n=100 and expected small counts, a difference of 1-2 questions is reported as inconclusive (within the
  run-to-run noise measured by comparing the two arms on questions whose prompts are byte-identical).
