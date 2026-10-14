# Progress (paused 2026-10-13): Stage A window gate + Stage B obligation completeness

Status: **paused by user, final reports not yet written.** Nothing committed and no benchmark run. Production
code is unchanged (`verdicts.py` sha fc69001c…, `evaluator.py` sha a0eab063…).

## Files added (only these)
- `tests/test_accuracy_window_support.py`: 16 tests (10 pass, 6 strict xfail on current code).
- `tests/fixtures/accuracy_211_192_rows.json`: verbatim 211.192 (snapshot 2026-09-03, sha 623102…48ad).
- Artifacts: this folder, and `artifacts/accuracy/obligation_completeness_stage_b_20261013T090000Z/`.

Git state vs start: the only new entry is `?? tests/test_accuracy_window_support.py`. The fixture sits in the
already-untracked `tests/fixtures/`.

## Stage A: window gate. Verdict: NOT APPLIED (stop condition met)
- Census (`work/window_census.py`, 274 offline row-runs, 6,288 window calls, no generation): 8 distinct windows
  reach the run gate.
  - Accepted today: F-004 own-terms [5,3], G-004 [3,3].
  - Rejected today: min own-terms 0, 0, 1, 1, 1, 2. The 2 is D-009, a false support.
  - So a threshold of 3 is inert on frozen data, and 2 would be unsafe.
- `work/window_cases.py`: the candidate turns 3 negatives into SUPPORTED/"correct":
  - N1 fabricated "within 30 days"
  - N2 actor swapped to "FDA"
  - N6 narrowed scope "only … not distributed"
  - On current code these are rejected ONLY by the 5-word run gate.
- `work/single_sentence_probe.py`: these are **pre-existing gaps in the single-sentence paraphrase judge**.
  - "FDA must thoroughly investigate…" scores PASS 100 on current production.
  - "Only … not distributed …" scores PASS 100.
  - "within 30 days" is supported by the evaluator; the pipeline withholds it (FAIL 0).
  - N8 (omitted "if fails specs" condition) is also a pre-existing single-sentence false support.
- The clause-split variant (`work/clause_probe.py`) does not help: the single-sentence judge accepts N1/N2/N6 clauses too.
- Candidate vs new tests: 3 safeguard tests fail, so the candidate is rejected.
- Prerequisite for any window relaxation: add actor-substitution, restrictive-scope ("only/solely") and
  evaluator-side unsupported-figure checks to the paraphrase judge first.
- Broad FAIL 40→PASS 100 cells (report step 5): the merged answer omits S1, so PASS 100 on "What does 211.192
  require?" would be a FALSE pass (the Stage B defect). On "investigation requirements" (focused), S2–S4 is complete,
  so a PASS there would be legitimate.

## Stage B: obligation-level completeness. Design prototyped in SCRATCH only
- Root cause: `evaluator._synthesis_gap` uses source indices as units (`covered`, `represented(i)`). 211.192 is one
  row, so any one verified sentence covers it.
- Prototype: `prototype_obligation_units.diff`. Units are the mandatory sentences of a unit row when there are
  more than one.
  - A unit is represented by a decided answering claim aligned to that sentence, or by a verbatim reproduction
    (same run/share rule, per sentence).
  - "Addressed but unverified" means an unverifiable claim with `core_overlap` ≥ 0.5 to the sentence; that gives
    NOT_ESTABLISHED, not FAIL.
  - Lead-in rows (ending ":") keep the row-level rule.
- Results:
  - `work/stage_b_matrix.py` (lexical production path), broad question: complete verbatim/paraphrase PASS 100;
    each of S1–S4 omitted (verbatim and paraphrase) FAIL 75; bare heading FAIL 75; unsupported claim FAIL 40.
  - Real path (`real_path_matrix_prototype.json`, semantic aligner, live DB): broad cells 1b/4/6/7 PASS 100 →
    FAIL 75; paraphrase with an unverifiable S4 → completeness not_established; repair-supplied verbatim text
    keeps PASS 100.
  - Suite on prototype: 745 passed (only the intended XPASS of the Stage B strict xfail).
- Further false-pass routes NOT yet covered by the prototype (design needed):
  1. "What are the production record review requirements in 211.192?" is planned FOCUSED: its focus = the section
     heading, so it bypasses synthesis and every omission scores PASS 100. Proposal: treat a focus equal to the
     provision heading as a synthesis for completeness.
  2. `_focus_gap` has the same paragraph granularity. "Investigation requirements" answered with S2 only scores
     PASS 100. Proposal: focused units = mandatory sentences whose own text carries the focus terms. No anaphora,
     to stay out of the excluded relevance change.
- Risk: 3,282/15,933 obligation-bearing eCFR rows have ≥2 mandatory sentences (139 have ≥5) per
  `work/corpus_survey.json`, so broad questions on those become stricter. Frozen F60 cannot measure this
  (its Pkg has no answer_plan).
- Imprecision seen: a pronoun-led unverifiable claim can fall below the 0.5 overlap and be counted missing.

## To resume
1. Write the Stage A REPORT.md (this folder) and the Stage B REPORT.md (design, matrix, risks); then report to the user.
2. Final test command: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_accuracy_*.py
   tests/test_answer_value_plan.py tests/test_ind_safety_deadlines.py` → 745 passed, 10 xfailed (current code).
3. Scratch copies (temporary): `scratchpad/v2_window_candidate`, `scratchpad/v3_obligation_units`. The diffs are
   saved in the artifact folders, so the scratch copies can be rebuilt from them.
