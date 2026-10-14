# Phase 2C: paraphrase support safety (forensic report)

Investigation only. No source, test or script changed (verified: nothing under `src/`, `tests/` or `scripts/` is newer than the Phase 2A regression).

- **Data:** the frozen 60 validation inputs, all LEGACY_RECONSTRUCTED evidence (none exact), human labels unchanged.
- **Method:** both aligners. Every supported or partial claim decision was recorded (338). The 121 unique decisions that were not an exact verbatim match were each classified by hand against the passage and source text.
- **Artifacts:** `support_decisions_labelled.json`, `candidate_rule_offline_test.json`, `scripts/`.

## A. Executive decision

**FAIL: a material false-support defect is confirmed.**

38 of the 121 reviewed non-trivial support decisions are false:
- 12 false supports;
- 26 false partials, from a separate mechanism.

They occur on 15 rows: N=1 ×9, N=0 ×5, N=2 ×1. On this set the answer-level impact is small (2 rows), and no false high results. But the mechanisms are systemic, feed Phase 2A citation grounding, and are visible in every claim trace.

## B. Root cause (exact logic, `src/regulus/accuracy/verdicts.py`)

1. **FALSE_PARTIAL (26/35 partial decisions).** In `judge()`, once the verbatim test fails, `if comparison.omissions: return PARTIAL` runs **before any test that the passage supports the claim's content**.
   - An "omission" is any conditional qualifier the passage carries and the claim doesn't ("as appropriate", "except as provided", "where appropriate"), and these are ubiquitous in eCFR.
   - Any aligned passage above the aligner's 25% overlap floor that carries one grants partial support.
   - Example: a Design History File claim gets partial support from 820.45 (labeling and packaging), at 9% coverage.
2. **FALSE_SUPPORT via paraphrase (8/45).** `judge()` accepts PARAPHRASE when at least 2 operators agree and content-term overlap is at least 0.7.
   - The operators that agree are almost always strength (mandatory = mandatory) and polarity (affirm = affirm), which carry no subject information.
   - Up to 30% of the claim's terms may be absent, including the one that names the regulated object.
3. **Other paths:**
   - `judge_item` checks conflicts but **not omissions** (E-005: "as appropriate" dropped, still SUPPORTED).
   - Its head-membership test accepts a generic structural word (F-003: "Subpart B" matched by a Subpart C source whose heading says "this subpart").
   - `judge_descriptive` misses the qualifier "provided that" (B-005).
   - `judge_window` lets an object substitution through in the lexical arm (F-012: "validation" vs 117.165 verification).
4. **Verbatim (0/22 false).** In this set the ≥80% rule caused no false support. The Phase 2A boilerplate test shows it can (81% coverage with the substance name uncovered); Phase 2A's coverage-dominance rule guards that only for citations.

## C. Evidence table (all 38 false decisions, condensed by pattern)

| Question | Claim | Evidence | Current | Correct | Why |
|---|---|---|---|---|---|
| B-003 | "The **application** must be submitted within 60 days of the anniversary date…" | 601.28: sponsors shall submit the following **information** each year within 60 days… | supported (paraphrase) | unverifiable | object substitution (application vs annual information) |
| B-003 | "The application **must be submitted in electronic format**…" | 601.14(a): electronic format submissions must be in a form FDA can process | supported | unverifiable | adds a mandate the passage doesn't state |
| C-002 | "The label shall specify **the identity of the commodity** and the name and place of business…" | 701.12(a): name and place of business only | supported | partial / unverifiable here (identity is 701.11) | half-conjunction unsupported by this passage |
| C-004 (lexical) | "The use of **bithionol** in cosmetics is prohibited" | 700.23: chlorofluorocarbons … prohibited | supported | unverifiable | substance substitution |
| D-007 | "…procedures for packaging and labeling **operations**" | 211.122(a): labeling and packaging **materials** | supported | unverifiable here (true per 211.130) | object substitution |
| D-008 | "Calibration **procedures** and records…, as required by 21 CFR 111.30" | 211.68(a): records of calibration checks | supported | partial | missing object, wrong named provision |
| F-007 (lexical) | "a food safety plan must contain … hazard analysis and preventive controls" | 117.160(a): validation of controls | supported | unverifiable | object substitution |
| F-012 (lexical window) | "requires **validation** that the preventive controls…" | 117.165(a): **verify** | supported | unverifiable | object substitution |
| D-004 (lexical) | "The written procedures shall include the following sub-requirements: [1]…[18]" | 211.101 "shall include the following" | supported | not a claim | vacuous lead-in extracted as a claim |
| E-005 | "requires … confidentiality of electronic records" | 11.30: "…and, **as appropriate**, the confidentiality" | supported (list item) | partial | item path ignores dropped conditions |
| B-005 | "plateletpheresis … may vary with additional standards in part 640" | 606.110(a): may be at variance … **provided that** | supported (descriptive) | partial | "provided that" not a recognised condition |
| F-003 | "The CGMP requirements under Part 117 **Subpart B** include food safety plan" | 117.190(a) (Subpart C) | supported (list item) | unverifiable / wrong | structural head matched by the generic "subpart" |
| D-004, D-010, E-005, F-003 ×9, F-007, F-009 ×5, F-022 ×8, M-034 (26 rows of this kind) | e.g. "A sanitation preventive control is a measure to prevent hazards related to sanitation…" | e.g. 117.140(a) "Except as provided by paragraphs (b) and (c)…" | partially supported | unverifiable | the passage doesn't state the claim; partial granted because the passage carries a condition |

## D. Quantification (diagnostic, not benchmark accuracy)

| | Count |
|---|---|
| Support decisions recorded (both aligners) | 338 |
| Unique non-exact-verbatim decisions examined | 121 (paraphrase 45, partial 35, verbatim with missing terms 22, list item 14, descriptive 3, window 2) |
| SAFE_SUPPORT | 71 |
| SAFE_PARTIAL | 12 |
| FALSE_SUPPORT | 12 |
| FALSE_PARTIAL | 26 |
| CORRECT_UNVERIFIABLE | 0 (only supported or partial decisions were in scope) |
| INSUFFICIENT_EVIDENCE | 0 per decision. The *whole set* is legacy-reconstructed evidence, so no decision is exact-evidence validated |

**False rate among examined:** 38/121 = 31%.

| Path | False / examined |
|---|---|
| Partial | 26/35 |
| Paraphrase | 8/45 |
| List item | 2/14 |
| Descriptive | 1/3 |
| Window | 1/2 |
| Verbatim | 0/22 |

**Aligners:**
- In both: 19 false decisions.
- Semantic only: 11.
- Lexical only: 8, including C-004 bithionol, F-007 and F-012.

The aligner only picks the candidate passage, but because it decides *which* passage reaches the permissive paths, it effectively decides correctness in these cases.

**Rows affected:** 15 (N=1: 9, N=0: 5, N=2: 1, C-004 lexical only).

**Answer-level impact (scratch simulation, semantic aligner of record):** making all 30 semantic-arm false decisions unverifiable changes 2 rows:
- B-003: partial 15 → 0.
- M-034: partial 0 → unverifiable, so score coverage drops 37 → 36 at most.

No row crosses 50 either way. Most false decisions sit on rows already judged off-topic or partial.

## E. Root-cause classification

| Defect | Layer |
|---|---|
| Partial granted on a condition without content support (26) | **EVIDENCE MATCHING** (support ladder ordering in `judge`) |
| Paraphrase object/substance substitution (6) | **EVIDENCE MATCHING**; **ALIGNMENT** for the lexical-only cases |
| Item path ignores omissions (E-005) | **EVIDENCE MATCHING** |
| Structural head matched generically (F-003) | **EVIDENCE MATCHING** |
| "provided that" not a condition (B-005) | **REGULATORY OPERATOR LOGIC** |
| Vacuous "include the following [n]…" claim (D-004) | **CLAIM EXTRACTION** |
| Wrong named provision in claim text (D-008) | EVIDENCE MATCHING (substance), plus citation (2A handles text citations) |

## F. Proposed fix (not implemented)

**F1. Partial requires content support.** In `judge()`, apply the omission downgrade only to a candidate that already meets the verbatim or paraphrase standard for the claim's content. Otherwise the verdict is UNDECIDABLE. The same omission check is added to `judge_item` (E-005) and `judge_window`, as `judge_descriptive` already has.

**F2. Contrastive distinguishing-term guard** on the non-exact paths (paraphrase, descriptive, item by terms, window, and verbatim below 100%). A claim content term is *distinguishing* when it is:
- absent from the supporting source (its text and heading, stemmed, same-term matching); **and**
- present in a *different* evidence source.

If any distinguishing term exists, that source cannot support the claim, and the verdict is UNDECIDABLE for it.

How it handles each concern:
- **What counts as distinguishing.** The evidence itself shows that the term names something another provision governs: bithionol is in 700.11, not 700.23; "operations" is in 211.130, not 211.122; "validation" is in 117.160, not 117.165; "identity of the commodity" is in 701.11, not 701.12.
- **Generic words.** A closed list of modal and operation verbs and discourse words never counts (require, must, shall, ensure, establish, maintain, follow, apply, include, contain, provide, conduct, implement, specify, add, achieve, also, additional, general, certain…). Words found in *no* source (e.g. "adds", "specifically") cannot be contrastive. A word found in the supporting source is not missing.
- **Anaphora.** Nouns in a leading "These / Those / Such &lt;noun&gt;" phrase are anaphoric, not distinguishing. This protects C-004 "These ingredients…" and with it the Phase 2A citation fix.
- **Actor, product, condition, number, date.** Handled as now by the Priority 2 operators (actor conflict, domain filter, quantity and date conflicts, conditions), unchanged. The guard covers the remaining gap: a different *object or substance* named with identical operators.
- **Legitimate paraphrases.** Synonyms that appear in no other source (files ↔ records, kept ↔ maintained, safely ↔ safe) are untouched, because nothing contrasts them.
- **Uncertainty.** The guard only withholds support (UNDECIDABLE → unverifiable). It never creates a contradiction.

**Offline test against the 121 hand labels (F1 + F2):**
- It catches **34 of 38** false decisions.
- It blocks **2 of 83** safe ones:
  - C-004 "These ingredients…" (fixed by the anaphora exemption);
  - one 3-term safe partial at 0.67 overlap (conservative direction).

**F3. The 4 it doesn't catch need separate small rules:**
- add "provided that" to the condition vocabulary (B-005);
- a structural term in a list head (Subpart X, Part N) must match the source's own structure, not just appear in its heading (F-003);
- a list lead with no content but markers is a non-claim (D-004);
- the omission check in `judge_item` (E-005, covered by F1).

These belong to operator logic, matching and extraction. They should go in as separate, individually validated changes.

## G. Regression plan (must pass before a future fix is accepted)

- **Test files:**
  - `tests/test_accuracy_claim_extraction.py`: G-004 = 100, M-020 correct, F-007 recovery, E-010, D-001, D-002.
  - `tests/test_accuracy_citation_grounding.py`: C-004 citation correct under both aligners; M-020's three paragraph mismatches; shared-boilerplate rejection.
  - `tests/test_accuracy_guidance_logic.py`: all Priority 2 guidance, actor, negation and domain cases.
  - `tests/test_accuracy_relevance.py`: D-001, D-003, D-008 wrong-topic; temporal refusals.
  - `tests/test_accuracy_evaluation.py`, `tests/test_accuracy_claims.py`, `tests/test_accuracy_observer.py`.
  - `tests/test_evidence_traceability.py`: exact evidence and fingerprints.
- **Fixtures:** `accuracy_real_rows.json`, `accuracy_guidance_rows.json`, `accuracy_extraction_rows.json`.
- **New regression cases from this report:**
  - each of the 38 false decisions becomes unverifiable;
  - each of the 83 safe decisions keeps its verdict, apart from documented conservative exceptions;
  - semantic and lexical arms agree on every C-004 claim.
- **Answer level, on the 60 rows:** verdict changes limited to rows containing a corrected false decision; no new N=0 score above 50; G-004, M-020, D-002 unchanged; Phase 2A citation agreement not reduced.
- **Live:** the regression (`scripts/accuracy_regression.py`): answers byte-identical, fingerprints unchanged.

## H. Production safety

- No production, retrieval, generation, prompt or evidence-capture file changed.
- No source, test or script changed at all; the only new files are analysis artifacts.
- No benchmark rerun; no labels or rubric changed.
- The answer-impact simulation patched `assess_claims` inside a throwaway process only.
