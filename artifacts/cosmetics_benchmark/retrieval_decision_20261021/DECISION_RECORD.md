# Decision record — first retrieval improvement (2026-10-21)

**Decision:** the first improvement is to make the eCFR AND full-text leg treat the word "or" as a word, not an OR
operator. Behind a switch, off by default. Not implemented yet.

## 1. Evidence reused (no investigation repeated)
- **Step 2B was completed and met its criteria:** read-only, 68/68 registries reproduced exactly, H1-H3 tested,
  question IDs for all 54 missing-evidence cases. Report: evidence/step2b_report.md. Step 2A matrix (all 100):
  evidence/step2a_report.md.
- **The 2A/2B findings apply unchanged to the 1.7B baseline:** Step 6 arm A (Qwen3-1.7B MLX 4-bit, switch off) had
  byte-identical prompt sources (citation, method, tier, text) and selection drops to the analysed 20 Oct run on
  100/100 questions.
- **Outcomes:** Step 6 arm A blind verdicts (2 PASS / 2 PARTIALLY PASS / 9 PARTIALLY FAIL / 87 FAIL).
- **New work in this task:** none beyond read-only joins of these files (evidence/classify.py, evidence/classification.json).

## 2. Diagnosis: one primary cause per question (earliest stage that alone rules out a correct answer)

| Category | Count | Questions | Basis |
|---|---|---|---|
| Required source absent from the corpus | 0 | — | 2B: all 180 required paths are live rows. Content defect: rows 740.12(b) and 73.2725(b) end at "following statement:" / "following specifications" with no child rows (Step 3). |
| Source exists, not retrieved (no leg generated it) | 14 | 9 Part 73 (COS-73.2085, .2095, .2250, .2298, .2575, .2645, .2646, .2647, .2725), COS-71.1-Q2, 701.9-Q1, 720.7-Q1, 740.11-Q1, UC-COS-006 | 2B: H1 gate (9); no RC1 term overlap (5) |
| Source exists, required paragraph not retrieved (other evidence present) | 3 | COS-700.13-Q2, 701.3-Q4, 80.31-Q1 | 2A primary "evidence incomplete" |
| Matched by a leg, ranked or capped out before the registry | 37 | 30 RC1 rank > 4, incl. 16 colour additives that lost "No. N" (e.g. COS-74.2203, 74.2317, 82.1104, 82.50); 4 by the 4-row cap (COS-70.50-Q1, 74.2602a, 700.35, 740.11-Q2); 2 wrong paragraph (COS-700.15-Q1, 700.25-Q2); 1 AND rank 22 (COS-71.27-Q1) | 2B table §4 |
| In the registry, dropped by the context budget | 3 | COS-70.55-Q1, 701.3-Q1, 71.15-Q2 | 2B: RC1 rows placed last; the RC2 reserve admitted another row |
| Selected but omitted from the final context | 0 decisive | 70.3(f) truncated in COS-70.3-Q1 and -Q3; core definition visible, not the deciding cause | arm A `truncated` flags |
| Evidence reached the model, 1.7B answer wrong or incomplete | 19 | 8 declines, 2 withheld, 8 PARTIALLY FAIL, 1 FAIL (list in classification.json, category E) | 23 with sufficient evidence; 4 of them PASS/PARTIALLY PASS |
| Correct answer withheld by the validator | 0 confirmed | 4 withheld in arm A: COS-71.27-Q1, 74.2208-Q1 (no required evidence), 82.1307-Q1, 82.2050-Q1 (evidence present) | Drafts are not recorded by the app, so not determinable; counted above under their primary cause |
| Statute-only key (FD&C Act text not in the corpus) | 20 | COS-FDCA201(i), 601-Q3, 603, 605-Q1, 605-Q3, 606, 607-Q2, 607-Q3, 609-Q1, 609-Q2, 613, 614; UC-COS-009, 011, 013, 015, 016, 017, 020, 021 | Separate source-coverage track; not a ranking problem |

96 failing questions = 17 + 37 + 3 + 19 + 20, plus 4 passing.

**Facts:**
- 57 of 80 section-keyed questions lack their evidence because of retrieval (17 + 37 + 3), not the corpus.
- With evidence present, 1.7B delivers PASS/PARTIALLY PASS on only 4 of 23. Step 3 found 0 of 8 general questions
  answered from complete evidence.

**Hypothesis:** retrieval fixes raise what can be answered, but answer gains on 1.7B will be smaller than coverage gains.

## 3. Candidates ranked
| Candidate | Questions with evidence | Coverage effect | Misleading-context risk | Size / rollback | Testable without the model |
|---|---|---|---|---|---|
| **1. AND leg: "or" as an operator** | 9 (+1 possible, COS-71.27) | **Measured (2B counterfactual):** with the AND leg not saturated, RC1 ranks each target section 1st-4th | **Lowers it:** those 9 prompts are 8/8 rows of 21 CFR 1271.90 (HCT/P labeling) | One call site, switch off by default | Yes |
| 2. RC1 drops tokens with digits | up to 16 colour (26 lost a number) | Not measured: target ranked 4th-117th on "red" alone | Question figures ("2,000", "721") could pull wrong sections | One condition | Yes |
| 3. RC1 caps (4 rows, 2 per section) | 6 | Partly measured | Competes for the 3,600-char budget; past budget levers were zero-sum (Phases 2-4, P4/P5) | Small | Yes |
| 4. RC1 rows placed last | 3 | Measured (rows in registry) | Zero-sum (binding_first: 16 recovered, 4 lost) | Small | Yes |
| 5. FD&C Act text | 20 | Needs a new source | Provenance, effective dates, versioning and citation format must be assessed first | Large | No |
| — 1.7B with evidence present | 19 | Not a retrieval fix; prompt levers refuted (Steps 3, 6; 20 Oct) | — | — | — |

Candidate 2 reaches more questions, but its effect is unmeasured. Candidate 1 is the only one whose coverage effect
was measured and that also removes misleading context.

## 4. The recommended improvement
1. **Confirmed failure:**
   - `websearch_to_tsquery` reads "or" as OR. "…certification or labeling apply?" becomes `(…0 rows…) | 'label' & 'appli'`,
     which matches 415 rows, all 21 of 1271.90 at heading weight A.
   - The eCFR AND leg then returns ≥ 3 rows, so RC1 is skipped (lexical.py:557).
   - The 9 Part 73 prompts get only 1271.90 rows.
2. **Smallest change:**
   - For the general-question eCFR AND leg only (lexical.py:512, `full_text_ecfr(question, …)`), pass the question with
     standalone "or" removed. "or" is an English stop word, so no content term is lost.
   - Guarded by a switch, default off, recorded in the pipeline fingerprint only when on (as learned in Step 5 Part B).
   - Not changed: the guidance AND leg, the OR fallback, RC1, exact-citation paths, the budget.
3. **Files:**
   - src/regulus/retrieval/query.py: a helper of about 3 lines;
   - src/regulus/retrieval/lexical.py: one call site plus the switch;
   - src/regulus/system_identity.py: fingerprint entry when on;
   - new tests/test_retrieval_literal_or.py.
4. **Focused regression set:**
   - Unit tests: questions without "or" give a byte-identical AND query; the switch off changes nothing.
   - Retrieval-only replay (NoGenerator, read-only DB, the Step 2B harness pattern) on the 100 cosmetics questions,
     with the switch off and on.
   - `scripts/retrieval_baseline.py run` on the frozen 352-row set, off vs on, plus `compare`.
   - Existing suites: tests/test_retrieval_*.py, test_advanced_retrieval, test_retrieval_baseline, test_generation_contract.
   - The blast radius is the 15/100 and 17/352 questions containing a standalone "or". None of the 15 is currently
     PASS/PARTIALLY PASS. 3 of them (COS-82.1205, 82.1321, 82.2050) take exact-citation paths that must stay identical.
5. **Acceptance criteria:** deterministic, using the existing expected-section labels.
   - Switch off: retrieval records byte-identical to Step 6 arm A (100/100) and to reference run f8bb4322 (352/352).
   - Switch on, cosmetics: at least 7 of the 9 Part 73 questions have a key section in the final context, with the
     first required section ranked ≤ 4 among prompt eCFR rows. 0 prompt rows from 1271.90 in those 9. 0 of the 28
     questions that now have a key section in context lose it. Prompts change only for questions containing "or".
   - Switch on, 352 set: in-context required-section recall not lower overall or in any category; 0 changes to
     questions answered by exact citation; no negative control gains a required-looking section.
   - Only after these pass, and with separate authorization: a 1.7B MLX answer check on the changed questions. It must
     show 0 category regressions and 0 new fabrications. Answer gains are expected to be small.
6. **Risks and rollback:**
   - Questions whose OR branch currently helps could lose recall; this is measured by the 15 + 17 blast radius.
   - RC1 and the OR fallback will run more often.
   - The 4-row cap may cut a Part 73 paragraph (2B open question).
   - COS-73.2725-Q1's key row is truncated in the database, so this question cannot reach full marks from retrieval alone.
   - Rollback: switch off (default) restores byte-identical retrieval. Removing the helper and the one call site
     reverts the code.
