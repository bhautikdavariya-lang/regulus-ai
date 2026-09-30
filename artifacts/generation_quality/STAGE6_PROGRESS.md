# STAGE 6 COMPLETE (2026-09-30): see docs/generation_quality_stage6.md and artifacts/diagnostics/stage6_result_final_20260930T040757Z.
# The notes below are the pause record of 2026-09-29, kept for history; the AS-05 decision was a scoped revert (comparisons and fragmentary texts keep the Stage 5 context).

# Stage 6 progress (paused 2026-09-29, session limit)

Stage 6 is NOT finished. Nothing below is final; no report has been written.

## Done
- Baseline = Stage 5 final run `artifacts/diagnostics/stage5_final_20260929T093254Z` (with its manual_review.jsonl).
- Generation failure matrix: `scripts/generation_matrix.py` → `artifacts/generation_quality/matrix_stage5_final_20260929T093254Z.jsonl`.
- Prompt/context experiments: `scripts/generation_experiments.py` (prompt-hash cache `generation_cache.jsonl`; base pinned to optional_context="always" = Stage 5 prompts, verified hash-identical).
  - `experiments_20260929T110032Z`: base / h1 / h1h2 / h1h3 / h1h2h3.
    - base→h1: 9 questions better, 0 worse (valid 45→50, keyed 43→47 of 51, citation errors 17→13, unsupported 1→0, prompt chars 4135→2314).
    - h2 (item count instead of copyable list) and h3 (inline conditions): mixed, as many regressions as fixes → rejected (the 0.6B model trades qualifier vs citation correctness).
  - `experiments_20260929T114821Z`: h1s (drop only supporting/discovery) ≈ base → most of H1's gain comes from dropping non-requested structural sources too.
  - latest experiments dir: h1r (H1 + keep structural children the requested text references by "paragraph (x)(n)"): valid 49, keyed 46 (AS-04 worse in raw, AS-05 better).
- Code (all tests pass, 1178 passed / 1 skipped):
  - `RagConfig.optional_context` = "incomplete_only" (default, Stage 6) | "always" (Stage 5); fingerprint v4.
  - `regulus/rag/selection.py`: `required_only(selection, keep_referenced=True)` + `referenced_paragraphs` (H1r is what is currently in production code).
  - `tests/test_generation_quality.py` (15 tests); one test pinned to optional_context="always".
  - S5-091 focus-shape change was tried live and REVERTED (model echoed "r1:/r2:" and validation passed an uncited answer).
- Full run with H1 (protected-only, before the H1r refinement): `artifacts/diagnostics/stage6_final_20260929T110502Z`
  - determinism repeats: **10/10 identical (already complete)**.
  - `comparison_vs_baseline.json` (scripts/compare_runs.py): PASS 45→46 automatic/carried, FAIL 16→13; S5-007, S5-024, S5-031, AS-02 FAIL→PASS; median latency 13.9→10.7 s, first token 2.0→1.56 s, median prompt tokens 1441→1148.
  - Protected-PASS check: S5-101 and AS-05 not PASS (see findings).
- Targeted H1r run for AS-04 + AS-05: `artifacts/diagnostics/stage6_h1r_targeted_20260929T115126Z` → AS-04 PASS, AS-05 FAIL (F08). All other questions' prompts are hash-identical between H1 and H1r (dry run), so their stage6_final results carry over.

## Findings so far (developer, not SME)
- S5-101: the Stage 4 developer PASS was wrong: the Stage 4/5 answer already misattributes 101.54 text to 101.3 rows; Stage 6 answer also misattributes (3 rows). FAIL in both; validator only warns (low_overlap).
- AS-05: H1 answer overstates (c) applicability ("class I, II and III"); H1r answer and full pipeline still FAIL (F08) → a protected-PASS regression still open.
- S5-090: gate correct; 820.10(b)(3) never retrieved (exact-only fetch of part 803; text search does not find it either) → retrieval (reverse cross-reference) limitation.
- S5-061: evidence lacks the UDI content definition → retrieval limitation; withholding is correct.
- S5-091: fails with exact evidence too; answer-plan variant made it worse → model capability.
- General knowledge: OR-fallback-only retrieval flags 5/6 unanswerable general questions but also 1 genuine one (BM-S-017) → document, no classifier.
- Validator gaps: uncited answers can pass (S5-062, BM-S-015); row misattribution only a warning.

## Next steps when resuming
1. Decide AS-05: options = exempt/adjust H1 for the comparison shape, or revert H1 (invariant 39/39 requires a fix or revert). Measure with generation_experiments.py + targeted run.
2. Merge final results (stage6_final + targeted), run scripts/compare_runs.py, developer review of changed answers (list in comparison_vs_baseline.json).
3. Integrity checks: benchmark c009d5f9c649…, stage5_v1 7cf80fda674f…, weights f47f71177f32…, diagnostic_v1 unchanged, DB read-only 65,341 rows.
4. Write docs/generation_quality_stage6.md (sections 1–6 of the brief). STOP.
