# COMPLETE (2026-10-01): all 300 questions scored; the workbook Regulus_AI_Acceptance_Benchmark_REV02_300Q_TEST_RESULTS.xlsx carries a per-question verdict.
# Result: 10 PASS, 289 FAIL, 1 ERROR (S-025, database statement timeout). Pass rate 3.3% of scored rows.
# All seven acceptance gates fail; see final_qc.txt in this directory and the Summary sheet.
# Rebuild command: PYTHONPATH=<openpyxl dir> python scripts/build_acceptance_results.py --run <run dir> --verdicts <run dir>/scoring

# Acceptance-test scoring: progress (paused 2026-10-01)

Task: complete question-by-question PASS/FAIL scoring of all 300 benchmark questions **in the existing
workbook** `Regulus_AI_Acceptance_Benchmark_REV02_300Q_TEST_RESULTS.xlsx` (do not create a new workbook,
do not modify the benchmark).

## Done

- All 300 answers were collected live: `../answers.jsonl` (299 OK, 1 ERROR = S-025, database statement
  timeout). Benchmark sha256 unchanged, recorded in `../run_metadata.json`.
- Workbook v1 built (7 sheets, 300 rows, machine indicators only, every executed row "REQUIRES SME REVIEW").
- **Scoring evidence built**: `scripts/build_scoring_evidence.py` writes 12 chunk files of 25 questions each
  (question, draft key citation, key answer elements, the *actual regulation text* of the draft-key sections
  from the read-only database, model answer, marker-to-source citation map, pipeline state). Run:

      .venv/bin/python scripts/build_scoring_evidence.py <run dir> <out dir>

- **125 of 300 questions scored** (chunks 1-5): `verdicts_01.jsonl` … `verdicts_05.jsonl`.
  Fields per row: `id, result, L, M, N, O, P, Q, notes, eval`.
  Running tally: **2 PASS (L-010, D-002), 122 FAIL, 1 ERROR (S-025)**.

## Remaining

1. Score chunks 6-12 (175 questions: D-029 onward through SD-013, i.e. the rest of M-*, E-*, V-*, SB-*,
   PM-*, T-*, C-*, B-*, U-*, DL-*, CR-*, FS-*, FF-*, AF-*, RH-*, CP-*, PB-*, NC-*, SD-*).
   Write `verdicts_06.jsonl` … `verdicts_12.jsonl` in this directory, same format.
2. Extend `scripts/build_acceptance_results.py` with a `--verdicts <dir>` option and rebuild the SAME
   workbook path in place: Result column from the verdicts, rubric columns L-Q added, Scoring Notes and
   Evaluator Notes from `notes`/`eval`, Failed Questions sheet limited to actual FAILs, Summary and
   Category Analysis recomputed (pass rate = PASS/(PASS+FAIL)), Priority flag cleared where a row passed.
3. Final QC: 300 unique ids, PASS+FAIL+ERROR+SME = 300, Summary agrees with Detailed Results, workbook
   reopens, benchmark hash unchanged.

## Scoring rules in force (from the workbook's own rubric, Instructions & Gates + Scoring Rubric tabs)

- L citation exact (1/0): every citation attached to a statement is right to the section/paragraph, and the
  governing provision is identified. Negative control: 1 = correctly declined.
- M fabricated citation (1 = failure): cites a provision, clause or guidance that does not exist. A
  *superseded* provision (e.g. 820.30 under the QMSR) is a citation error (L=0), not fabrication.
- N substantive 0/1/2, O completeness 0/1/2, P scope discipline 1/0, Q ISO clause 1/0/blank
  (blank only where column H reads "—").
- Question verdict: **PASS** iff L=1, M=0, N=2, O>=1, P=1 and Q in (1, blank); **FAIL** otherwise;
  **ERROR** only for technical execution failure; **REQUIRES SME REVIEW** only for genuine ambiguity.
- The draft key is the starting point, not the authority: every row's key was checked against the
  regulation text in the read-only snapshot. Where the key itself is wrong (S-004, S-007, S-021 so far),
  the model is not penalised for disagreeing with it and the discrepancy is recorded in `eval`.
- Borderline rows flagged for SME attention in `notes`: D-013, M-020, M-027, M-031.

## Failure patterns so far (first 125)

Answer withheld by validation (no substantive answer); right subject matter cited to the wrong part
(111.x for 211.x questions, 801/800 device sections for a food label, 507.53(d) for 117.180(d));
guidance documents cited where a binding section was asked for; section lists returned instead of
requirement content; invented retention period (S-028, "5 years"); fabricated sections (111.17, 111.54);
one inverted answer (M-011: says a new ISO edition applies automatically).
