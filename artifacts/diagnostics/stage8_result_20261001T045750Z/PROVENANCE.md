# Stage 8 (generation control) result

* Final code: repetition guard with normalised sentences + valid-prefix trimming, exact duplicate-sentence removal,
  lead-in chain completion of the exact-evidence context, question verbs not focus terms, evidence consolidation.
  The system-prompt synthesis rule was measured (live run stage8_generation_control_*) and REVERTED.
* 78 questions: offline replay `stage8_final_replay_20261001T045232Z` of `stage7_final_20260930T111007Z` (prompt hash identical; recorded output
  through the Stage 8 pipeline). 1 question (BM-NC-003, evidence changed: [Reserved] rows removed): live `stage8_final_live_20261001T045250Z`.
* Determinism: 10/10 in the live run stage8_generation_control_* (same model, same decoding).
