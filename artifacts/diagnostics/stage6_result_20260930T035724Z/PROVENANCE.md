# Stage 6 result

* Full 79-question run: `artifacts/diagnostics/stage6_final_20260929T110502Z` (determinism 10/10, scorecard_full_run.json).
* Questions re-run with the final code (only questions whose prompt the final code changed; every other generated
  question's prompt is hash-identical to the full run, verified with scripts/prompt_diff.py):
  * AS-04: `stage6_leadin_targeted_20260930T035351Z`
  * AS-05: `stage6_comparison_targeted_20260930T034749Z`
  * S5-007: `stage6_leadin_targeted_20260930T035351Z`
  * S5-010: `stage6_leadin_targeted_20260930T035351Z`
  * S5-011: `stage6_leadin_targeted_20260930T035351Z`
  * S5-022: `stage6_comparison_targeted_20260930T034749Z`
  * S5-024: `stage6_leadin_targeted_20260930T035351Z`
* One record per question; nothing else edited.
