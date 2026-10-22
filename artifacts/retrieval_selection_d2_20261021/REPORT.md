# Retrieval repair D, Experiment 2 (one-passage guidance floor): result (2026-10-21)

**Decision: FAIL — REMOVE CANDIDATE AND RESTORE BASELINE.** Criteria A1, A2 and A5 failed. The candidate has been
removed and the source files restored byte-for-byte.

## 1. Baseline protection
- **Repository:** branch main, HEAD fbd2e60, nothing staged.
- **Production files** matched experiment 1's pre-edit copies and HEAD (selection.py `2470fb2b…`, context.py
  `0123fe6e…`), and experiment 1's candidate was absent.
- **Prior work and the source-text repair** were preserved (diff hash `1bdb467e…` before and after).
- **Fingerprints** ([baseline/fingerprints.json](baseline/fingerprints.json)):
  - eCFR 65,280 / `4f0457d7…`, guidance `428b3dbd…`;
  - datasets: cosmetics `0e632288…`, 352-row `b0893eb8…`.
- **Baseline reused** after verifying it was produced on identical code and the same database identity: experiment 1's
  352-row run `retrieval_baseline_20261021T102326Z_16fa796d` and its test results (2,744 passed, 9 pre-existing
  failures).
- **Disclosed:** a fresh baseline test run I started was cut off at 70% when its launching command returned
  ([baseline/pytest_full_ABORTED_at_70pct.log](baseline/pytest_full_ABORTED_at_70pct.log)).
- **Disclosed:** during the experiment, another Claude Code session ran the repository's test suite concurrently. It
  changed no file this experiment touched.

## 2. Pre-registration
[PREREGISTRATION.md](PREREGISTRATION.md) `9c31ba25…`, locked at 16:26:33, before any implementation. It records:
- the same criteria A1–A7 and thresholds as experiment 1;
- the hypothesis (H) and the uncertain prediction;
- the exact datasets and scripts;
- the reuse of experiment 1's blind labels for identical passages;
- the mechanical decision rule.

Script hashes are in [RUN_MANIFEST.json](RUN_MANIFEST.json), written before the evaluation run.

## 3. Candidate (default off; archived in [candidate_patch/](candidate_patch/))
`general_evidence_order="ecfr_discovery_first_guidance_floor"`, for general questions only.
- **Discovery-tier order:** the highest-ranked guidance passage, then every eCFR passage, then the remaining guidance.
- **Unchanged:** everything else.
- **Diff** (`candidate.diff`, `5329f4b4…`):
  - context.py: +1 constant and a comment;
  - selection.py: the flag, `_optional_order` branch, presentation re-sort and diagnostic, 25 lines;
  - retrieval_baseline.py: the CLI choice.
- **Tests:** 12 focused tests (`test_selection_guidance_floor.py`, `9a29342e…`). They cover the floor, regulatory
  retention, limits, the usefulness filter, supporting guidance, and unaffected named-provision and guidance questions.
  All 12 pass.

## 4. Results (same questions, corpus and criteria as experiment 1)

| Criterion | Result | Evidence |
|---|---|---|
| A1 required paragraphs ≥ +3, 0 lost | **FAIL**: 18 → 18 of 174 (0 gained, 0 lost) | [evaluation.json](evaluation.json) |
| A2 70.55, 71.15(b), 701.3(b) enter | **FAIL**: 0 of 3 | idem |
| A3 0 R2 guidance removed | PASS: 72 removed = 42 R0 + 30 R1 + 0 R2 | [relevance.json](relevance.json) (all 72 reuse experiment-1 blind labels; 0 new items) |
| A4 12 named-provision contexts identical | PASS: 12/12 | evaluation.json |
| A5 352-row baseline loses no keyed target | **FAIL**: X-001 loses 21 CFR 4.1 | [eval/compare_352.json](eval/compare_352.json) |
| A6 tests | PASS: 2,756 passed (2,744 + 12), the same 9 pre-existing failures; integration 50/50 | eval/pytest_full_with_candidate.log |
| A7 budget and order | PASS: max 3,600 chars, 8 sources; registry order (unit-tested) | evaluation.json |

**Hypothesis H: supported.** All four experiment-1 regressions are prevented:
- COS-701.12-Q2 keeps the R2 OTC-drug labeling passage;
- retrieval-031, -034 and -039 keep their guidance-docket targets.

**Prediction: resolved negatively.** With one guidance passage competing first, none of the three target paragraphs
fits the unchanged 3,600-char budget.

**New regression (X-001, "How is a combination product defined…").**
- In the baseline, this question's eCFR discovery rows already outranked every guidance passage: 8 eCFR sources, no
  guidance.
- The floor moved the top guidance passage (1,489 chars) ahead of all of them, so 21 CFR 4.1, the last source, fell out
  of the budget.
- **The design flaw:** the floor promotes guidance even where guidance was not being displaced.

**Measured changes:**
- **352 rows:** plain-language in context 90 → 95. Identifiers unchanged at 108. 7 keyed targets gained: L-007
  101.9(c), L-008 101.9(b), L-013 101.36, U-010 830.320, G-007 201.100, Y-004 108.35, PB-006 part 820. 1 lost (X-001
  4.1). 79 records changed context.
- **100 cosmetics questions:** 76 contexts changed, with no required paragraph gained or lost and no eCFR row
  displaced.
- **Guidance passages:** 152 → 80. eCFR chars 58,821 → 107,639. Guidance chars 142,863 → 93,207.

## 5. State now
- **Restored byte-for-byte from [pre_edit/](pre_edit/):**
  - selection.py `2470fb2b…`;
  - context.py `0123fe6e…`;
  - scripts/retrieval_baseline.py `3d163b32…`;
  - the diff against HEAD is empty.
- **Removed:** the candidate test file. It is archived.
- **Production behaviour is the baseline.**
- **Nothing committed or pushed.** No database change, no index rebuild, no embedding model, no model inference.

## 6. What the two experiments establish (for the next decision)
- **Both trade-offs are confirmed:**
  - ordering eCFR discovery rows ahead of guidance recovers required paragraphs, but loses top-ranked guidance;
  - flooring one guidance passage keeps that guidance, but leaves no room for the target paragraphs and can displace
    eCFR rows that already ranked first.
- **Budget:** under the unchanged 3,600-char budget, no ordering tested so far meets all seven criteria.
- **No further candidate was run.** Any next step needs a new authorization.
