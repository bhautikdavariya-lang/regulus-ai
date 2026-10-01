# Stage 8 (generation control) final result

* Final code: normalised repetition detection (generation stop + validator), loops rejected as degenerate (NOT trimmed:
  measured), exact duplicate-sentence removal in non-looping answers, lead-in chain completion of the exact-evidence
  context, question verbs not focus terms, evidence consolidation ([Reserved] rows). The synthesis prompt rule was
  measured live (stage8_generation_control_*) and REVERTED; prefix trimming was measured (stage8_result_2026*T045750Z)
  and REVERTED.
* 78 questions: replay `stage8_final_replay_20261001T045900Z` of stage7_final (identical prompts; recorded output through the final pipeline).
* BM-NC-003 (evidence changed): live output recorded in stage8_final_live_*, replayed through the final code: `stage8_final_live_replay_20261001T045932Z`.
* Determinism: 10/10 in the live run stage8_generation_control_*.
