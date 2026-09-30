# Stage 6 final result

* Code: exact-evidence context applied only when every requested provision has complete exact text and the
  question is not a comparison (`RagConfig.optional_context="incomplete_only"`, `RagPipeline.build_bundle`).
* Full 79-question run: `artifacts/diagnostics/stage6_final_20260929T110502Z` (determinism 10/10; scorecard_full_run.json).
* Re-run with the final code: AS-04, AS-05, S5-003, S5-007, S5-010, S5-011, S5-022, S5-023, S5-024, S5-032, S5-033, S5-101 from `artifacts/diagnostics/stage6_fragment_targeted_20260930T040118Z` - the only questions whose prompt the final code
  changed relative to the full run (scripts/prompt_diff.py). All 12 reproduce the Stage 5 raw output and final
  answer byte for byte (their prompts are the Stage 5 prompts).
* Every other generated question's prompt is hash-identical between the final code and the full run.
* Superseded intermediate results (kept, not used): stage6_merged_*, stage6_result_2026*T035724Z, stage6_*_targeted for
  comparison/lead-in variants.
