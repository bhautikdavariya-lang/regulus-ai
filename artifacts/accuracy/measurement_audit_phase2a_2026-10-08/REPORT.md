# Measurement Audit Phase 2A: citation grounding correction

## 1. Summary

A claim's citation is now judged by whether **a source it cites supports it**, to the same standard as the support verdict. It is no longer judged by whether its marker names the one passage the support aligner ranked first. The changes are confined to the evaluator's citation layer. No answer verdict, claim support or relevance result changed on any of the 60 rows, under either aligner. Production answers and evidence fingerprints are unchanged.

## 2. Files changed

- `src/regulus/accuracy/answer.py`:
  - citation grounding: `judge_citation`, `support_against`, `_verbatim_coverage`, `_named_sources`, `nonclaim_citation_defects`;
  - per-claim `citation_trace`.
  The old `_citation` is removed.
- `src/regulus/accuracy/evaluator.py`: the citation dimension's aggregation only.
- `tests/test_accuracy_citation_grounding.py`: new, 19 tests.
- `tests/test_accuracy_claim_extraction.py`: test 9's fixture text. That test passed before only through the removed "correct, unchecked" path.
- `tests/test_evidence_traceability.py`: test 15 no longer compares wall-clock `retrieval_timings_ms`. That was a latent flake, the same exclusion `test_accuracy_observer` already makes.

## 3. Citation logic: before → after

| | Before | After |
|---|---|---|
| What is compared | the claim's markers vs **one** aligner-selected passage | each **cited** source, judged on its own (lexical, deterministic) |
| Granularity | section (`citation.split("(")[0]`) | the cited source's own: a paragraph when it is one; section level for a standalone marker line |
| Claim with no supporting passage | "correct", unchecked | **unverified** (neither correct nor a defect) |
| Unmarked claim followed by a marker | "correct", unchecked | cited by that marker **if it supports it**, otherwise uncited (rows P-010, C-002, G-004) |
| Standalone marker line | "correct", unchecked | cites the statements before it, section level (row E-001) |
| Provision named in text, no marker | "correct", unchecked | that provision is the citation, checked (row D-010) |
| Shared boilerplate | n/a | when some source states the claim verbatim, a cited source must state it at least as completely (C-004's 84%/84% tie counts) |
| Guidance cited for a binding requirement the regulation states | not detected | `guidance_for_requirement` defect |
| Cited source cross-references the stating provision | not handled | correct |
| Marker matching no source, on a non-claim sentence | ignored | defect |
| Dimension | FAIL on points-elsewhere/invalid or all uncited; otherwise PASS | FAIL on any defect (wrong source, wrong paragraph, guidance-for-requirement, invalid) or all uncited; NOT_ESTABLISHED when no cited statement could be checked; PASS when at least one is verified and none is wrong |

**Mapping from L to the machine rule.**

- **L=1** ("every regulatory citation is correct to the section, and to the paragraph where the response asserts a paragraph-level requirement") means: no citation is *shown* to name a source that does not state its statement.
- **L=0** "any citation to the wrong section or paragraph" maps to `points_elsewhere` / `paragraph_mismatch` / `guidance_for_requirement` / `invalid`.
- **L=0** "a correct explanation with no citation at all" maps to every answering statement being uncited.

## 4. C-004 forensic regression

| | Semantic aligner | Lexical aligner |
|---|---|---|
| Support aligner's winner for "These ingredients are deemed to be adulterated … [1]" | 21 CFR 700.14(a) | 21 CFR 700.11(a) |
| Citation [1] → 700.11(a) | **correct** (84% verbatim) | **correct** (84% verbatim) |
| Row citation dimension | fail → **PASS** (score 0 → 35) | fail → fail |

The lexical row still fails for a *different* claim. "The use of bithionol in cosmetics is prohibited [1]" is falsely *supported* by 700.23 (chlorofluorocarbons) through shared terminology: the Phase 1 paraphrase defect, out of scope for 2A. The citation layer correctly reports that `[1]` does not support it while the (false) substantive verdict says another source does. Claim-level aligner independence is proven in `test_C004_the_cited_source_supports_the_claim_whichever_source_the_aligner_ranks_first`.

## 5. Citation-specific tests

19 added, 19 passed, 0 failed. Full suite: **1584 passed, 1 skipped, 0 failed.**

The cases covered:
- C-004 under two different winners;
- a false citation;
- multiple citations (one supporting suffices, both traced);
- shared boilerplate (wrong section rejected);
- paragraph mismatch, plus M-020's three real shifted items;
- inline markers;
- a trailing marker that supports (P-010) and one that doesn't (C-002);
- a standalone marker line (E-001);
- an invalid marker on a non-claim sentence;
- a valid marker on a pointer, not judged;
- guidance for a requirement;
- recommendation-only guidance;
- guidance cited for guidance;
- cross-reference;
- unverified;
- a named textual citation (D-010);
- no substantive change.

## 6. Before/after on the frozen 60 (legacy-reconstructed evidence, semantic aligner of record)

| Row | Human L | Before | After | Substance changed? | Explanation |
|---|--:|---|---|---|---|
| C-004 | 1 | fail | **pass** | no | `[1]` → 700.11(a) states it; the tie-break no longer decides |
| M-020 | 0 | pass | **fail** | no | 3 items cite the paragraph before the one that states them; exactly the reviewer's three |
| E-001 | 0 | pass | **fail** | no | standalone `[1]` → 11.100(a); the quotation is 11.1(a) |
| D-010 | 0 | pass | **fail** | no | cites 111.120(d) for 111.113(b)(1) content |
| F-022 | 0 | pass | **fail** | no | its one answering statement is uncited (the block citation sits on a non-claim) |
| H-003 | 0 | pass | fail | no | `[3]` invalid: **legacy renumbering artefact** |
| E-009 | 0 | pass | fail | no | `[2]` invalid: **legacy renumbering artefact** |
| PB-008 | 0 | pass | fail | no | `[2]` invalid: **legacy renumbering artefact** |
| D-015 | 0 | pass | fail | no | `[4]` invalid in a pointer: **legacy renumbering artefact** |
| D-007, F-003, G-010 | 1 | pass | not established | no | every cited statement is unverifiable from the captured evidence |
| E-010 | 0 | pass | not established | no | as above |

| Metric | Before | After |
|---|---|---|
| Agreement with L, all decided | 22/35 = 63% | **28/31 = 90%** |
| False pass (L=0, evaluator pass) | 12 | **3** (B-001, D-013, F-009) |
| False fail (L=1, evaluator fail) | 1 (C-004) | **0** |
| Answer-verdict changes | — | **0** (both aligners) |
| Claim support / relevance changes | — | **0** (both aligners) |

**Legacy split (§16).** No 60-row result is exact-evidence validation.

| Subset | Agreement before → after | False passes | False fails |
|---|---|---|---|
| 40 rows with intact `[n]` mapping (still legacy evidence) | 16/25 = 64% → **18/21 = 86%** | 8 → **3** | 1 → **0** |
| 20 rows whose markers were shifted by lost guidance | 6/10 → 10/10 | — | — |

The second row is **not valid**: H-003, E-009, PB-008 and D-015 agree only through markers that the renumbering itself made invalid.

**Exact evidence (the only human-labelled case).** The live M-020 answer is byte-identical to the labelled rev02 answer. On its exact snapshot (provenance `exact`, fingerprint `fa2451337503d884…`) the evaluator flags exactly the three items the reviewer named:
- (a)(5) content cited to (a)(3);
- (a)(6) content cited to (a)(5);
- (a)(7) content cited to (a)(6).

Before 2A it scored this citation PASS.

## 7. False positive audit

- No row moved from fail to pass except C-004 (human L=1).
- Wrong-section boilerplate is rejected (test).
- A citation to an unrelated source is rejected (test).
- Guidance recommending what a claim states as a requirement is not a correct citation (test).
- Remaining false passes:
  - **B-001**: the first quotations verify to their cited sources; the human's "shift" is not reproduced.
  - **D-013**: the misdirected pointer is a non-claim sentence; pointer wording is not judged.
  - **F-009**: the misattributions are inline "§ 117.20(a)" provisions inside claims that also carry `[n]` markers; a marker takes precedence over named text.

## 8. False negative audit

- None on the configuration of record.
- The lexical arm's C-004 failure comes from the out-of-scope paraphrase false support (§4).
- Four L=1 rows (C-004's 6 unverified claims, D-007, F-003, G-010) carry unverified citations. That isn't failing, but it isn't confirmed either: the captured evidence (often recital-only) cannot verify those statements.

## 9. Production safety

Live regression `artifacts/accuracy/regression_2026-10-08T082132Z.json`:
- payload arm PASS, live arm PASS, exact evidence PASS;
- no answer-bearing field differs between evaluator on and off;
- answers are byte-identical to the Priority 3 run;
- evidence fingerprints are unchanged (`fa2451337503d884…`, `678b0d62c082e609…`);
- stored = recomputed = live evaluator = replay;
- one model call per answer.

No file under rag, retrieval, planning, traceability or scripts changed in 2A.

## 10. Performance

Evaluator mean 252.5 ms → 262.0 ms (+4%), max 393.6 → 381.6 ms, against about 16 s per answer.

## 11. Remaining limitations

- **Pointer and meta sentences:** only invalid markers are checked; what the sentence says about its source is not (D-013).
- **Block citations of every source** are not themselves a defect; doing that would need a threshold the rubric does not define (F-009, F-022).
- **A marker takes precedence over an inline provision named in the same claim** (F-009).
- **Unverified citations:** whether a statement the captured evidence cannot establish is cited correctly is not decided. The PASS detail states how many.
- **The support standard is inherited.** Any false *support* (the paraphrase defect) can turn into a false `points_elsewhere` (the lexical-arm C-004).
- **Validation:** exact-evidence citation validation exists for one human-labelled answer (M-020). The 60-row figures are legacy-reconstructed; the 20 renumbered rows are not valid for citations.

## 12. Decision

**PHASE 2A — PASS**

Citation grounding now evaluates the actual cited source(s), rather than the single aligner-selected support passage, and C-004 is correctly measured without changing substantive evaluation or production answers.
