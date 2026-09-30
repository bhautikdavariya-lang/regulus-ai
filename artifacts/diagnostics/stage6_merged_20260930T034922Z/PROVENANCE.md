# Stage 6 final result (merged)

* Base: `artifacts/diagnostics/stage6_final_20260929T110502Z` (full 79-question run with the exact-evidence context applied to every shape; determinism repeats 10/10 in its scorecard, copied as scorecard_full_run.json).
* Replaced: S5-022, AS-05 from `artifacts/diagnostics/stage6_comparison_targeted_20260930T034749Z`: the only two questions whose prompt changed when comparisons were exempted
  from the exact-evidence context. Verified before merging: every other generated question's prompt is
  hash-identical between the final code and the full run, and both replaced questions reproduce the Stage 5
  raw output and final answer byte for byte.
* One record per question (the first); nothing else edited.
