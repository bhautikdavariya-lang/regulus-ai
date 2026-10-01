# COMPLETE (2026-10-01): see docs/generation_control_stage8.md and artifacts/diagnostics/stage8_result_final_20261001T045933Z.
# The notes below are the pause record of 2026-09-30, kept for history (prefix trimming and the prompt rule were later reverted on measurement).

# Repetition / runaway-generation fix: progress (paused 2026-09-30)

NOT finished. No report written, no commit made. Servers are STOPPED.

## Diagnosis of "What does 21 CFR 830.20 address?" (done, measured)
Reproduced live: 1,216 tokens / 173 s, the sentence "The UDI must be presented in two forms on the device label ..."
repeated with incrementing markers [5], [6] ... [13]; validation then withheld the whole answer.

Root cause is a COMBINATION, and NOT duplicate retrieval (the context had 8 distinct items, 0 duplicate texts):
1. Context assembly: an off-target guidance chunk (about 801.40, not 830.20) was in the prompt. The Stage 6 fragment
   safeguard kept full context because 830.20's lead-in "A unique device identifier (UDI) must:" ends with ":",
   although its own subparagraphs (a)-(c) were all present as exact evidence. The looped sentence came from that chunk.
2. Prompt construction: shape analysis took the question verb as a topic ("focus: address").
3. Repetition guard (the reason it RAN AWAY): the Stage 7 stop compared sentences verbatim; each copy carried a
   different citation number, so no two copies were identical and the guard never fired.
4. Citation assembly: the model invented markers [9]-[13] with 8 sources (model behaviour; the pipeline does not
   create them; repair strips invalid markers).

## Implemented so far (all 1,221 default tests pass)
- `src/regulus/inference/repetition_text.py` (new, torch-free): normalised sentence comparison (markers "[n]",
  "SOURCE n", case, spacing, trailing punctuation removed), `repeated_sentence`, `trim_repetition` (keep text up to
  the first occurrence of the repeated sentence). `inference/repetition.py` (stop criterion) re-exports it.
- `rag/validation.py::_degenerate` uses the same normalised comparison (stop remains a subset of the validator).
- `rag/pipeline.py`: after generation, a detected loop is trimmed to its valid prefix BEFORE validation
  (raw output kept; `generation.repetition_trimmed_sentences` recorded; the prefix still must pass validation).
- `rag/selection.py::completed_by_protected_children` + pipeline condition: a lead-in whose own subparagraphs are
  protected evidence counts as complete -> exact-evidence context applies (drops off-target related material).
- `planning/shape.py`: question verbs (address, concern, govern, regulate, establish, specify, ...) are not focus terms.
- Tests: loop fixtures in test_answerability.py / test_generation_quality.py / test_answer_validation.py changed to
  an in-sentence loop (a repeated whole sentence is now trimmed, not withheld).
- Backups of the pre-change files are in the session scratchpad (not needed if git is used: `git diff` shows all).

## Measured: duplicate evidence in the prompt (379 diagnostic + benchmark questions, retrieval only)
- exact-duplicate items: 62 in 32 questions. 60 of them are "[Reserved]" placeholder rows of DIFFERENT sections
  (e.g. 820.5, 820.40, 820.20-820.30 in part-level Part 820 questions); 2 are identical text in different parts
  (117.180(d) vs 507.53(d), human vs animal food).
- near-duplicate pairs (>=0.8 3-gram overlap): 183 in 59 questions, mostly DIFFERENT provisions with parallel
  wording (111.155(a) / 111.160(a) / 111.165(a)) -> must NOT be merged.
=> Next step for dedup: drop content-free "[Reserved]" rows from the prompt (general rule), merge exact-text
   duplicates only when they are the same provision identity or non-CFR chunks; never merge different provisions.

## Remaining steps (estimate 2.5-3 h, ~1 h of it model time)
1. Evidence consolidation in selection/package: reserved-row removal, exact/normalised dedup with the identity rule
   above, near-dup only for non-identity (guidance) chunks; keep strongest occurrence; record merges; tests.
2. System-prompt synthesis rule (state each requirement once; cite supporting sources together; stop when answered).
   NOTE: changes every prompt -> full live diagnostic rerun required.
3. Tests for: normalised repetition, trimming, lead-in completion, focus verbs, dedup (keep 830.20(a)/(b) distinct).
4. Targeted live evaluation of the 12 questions in the brief (retrieval success, evidence uniqueness, correctness,
   exact-section accuracy, citation correctness, repetition count, length, unsupported claims).
5. Full live diagnostic run (`run_diagnostics.py --label stage8_repetition --repeat 10`), compare with
   `artifacts/diagnostics/stage7_final_20260930T111007Z` (protected set, changed answers, developer review).
6. Report `docs/generation_control_stage8.md`; decide whether training is needed (no training started).
