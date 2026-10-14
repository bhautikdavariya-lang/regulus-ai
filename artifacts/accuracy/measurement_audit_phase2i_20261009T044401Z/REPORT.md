# Measurement Audit Phase 2I: relative-clause negation (investigation and test design)

Investigation only. No production code, test, fixture, benchmark file or frozen answer changed (§8, hash-verified). The candidates exist only as offline copies (`work/variants/`). The regulatory corpus was read through the server-enforced **read-only** connection. No 300-question run.

**Recommendation: INVESTIGATE FURTHER.** Do not implement a relative-clause fix yet. Reject approach A, and reject approach B on its own. §9 explains why.

## 1. Executive summary

- **The 33 cases reproduce exactly.** 25 are cross-sentence (23 on the evidence side, 2 on the claim side) and 8 are same-sentence (4 and 4). All 33 still produce a polarity conflict in production, and none changes a verdict on the 170 frozen row-runs.
  - Correction to the Phase 2H report: 6 is the *claim-side total*; 4 of the 8 same-sentence cases are claim-side.
- **The real corpus changes the question.** The local eCFR snapshot (65,341 records) has **1,077 sentences** with a negation directly after *that/which/who*. Production reads 890 of them as negated rules. Approach B would flip **735**, and at least **73** of those flips are negations that **are the substance of the rule**:
  - 21 CFR 1.379(a): "a reasonable period **that may not exceed 20 calendar days**";
  - 73.3110(c)(1): "levels **that do not exceed 0.003 percent**";
  - 109.15(b)(2)(i): "a heat exchange fluid **that does not contain PCB's**".
- **Production is already wrong in both directions on real text** (15 controls built from verbatim regulation text; most claims are constructed one-qualifier or one-modal edits):
  - **3 false CONTRADICTED claims** on category qualifiers (213.122(e), 211.115(a), 606.65(d));
  - **1 false support:** "… that are not present **shall be declared**" is credited against 101.36(b)(2)(i) "… **shall not be declared**";
  - **1 false partial:** "You **must use** … any lot that does not meet …" against 212.40(c) "You **must not use** …".

  In the last two, the relative-clause "not" makes both sides read NEGATE, so a genuine must / must-not contradiction becomes a false *agreement*.
- **Approach A, sentence-local polarity:** it fixes 22 of the 33 cases and nothing on the real controls. It loses 5 of the 44 real-negation preservation controls, because it picks the sentence to read by word overlap, which puts *selection* inside the operator layer. **Reject.**
- **Approach B, relative-clause scope:** it fixes all 33 cases and the production errors above. But on real text it creates **5 false supports**, one credited as **verbatim**: claims that invert a material qualifier ("batches **that conform**", "levels **that exceed**", "fluid **that contains** PCB's"). **Reject on its own.**
- **B with a qualifier check (BQ),** which flags opposite negation on the same relative-clause verb: it fixes all 33 cases and scores **13/15** on real text. It still gives **1 false support**, when the inversion is phrased without a relative pronoun ("levels **exceeding** 0.003 percent"). The semicolon-joined passage (T3c) also stays wrong.
- **All five candidates, including the identity copy, pass the full existing suite (1832 passed) and change zero verdicts on the 170 frozen row-runs.** The existing tests and the frozen data **cannot distinguish a safe candidate from an unsafe one** here. The proposed real-text tests (§7) can.

## 2. The 33 cases: classification and reproducibility

**Reproducibility:**
- The tree is identical by SHA-256 to the end of Phase 2H.
- The current production run (`work/h_current.json`) is identical to the Phase 2H recorded run: all 5,829 comparisons and 170 row-runs.
- The 33 NEG-REL cases come from `measurement_audit_phase2h_…/work/cases_classified.json`, with the original claim and evidence text and every occurrence.

**Do they change a comparison?** Yes, all 33 currently produce a polarity conflict.

**Do they affect a verdict?** No. Phase 2H removed exactly these conflicts and measured 0 claim, 0 answer and 0 score changes. Every candidate here re-confirms that (§5.3).

**Evidence provenance.** All F60 evidence is **LEGACY_RECONSTRUCTED**, and the reconstruction concatenates a section's paragraphs into one passage. The current snapshot shows 21 CFR 117.139(b)(2) reads "Notify the public … when appropriate to protect public health". The "diverting to a use **that does not** present a safety concern" text sits in another paragraph of the same section. So part of the cross-sentence count comes from how the legacy evidence was rebuilt. Production does join paragraphs too, though: Phase 2D documented a single 4,828-character context source for 820.10. Exact prompt evidence for these rows does not exist, so the share that would recur on exact evidence is **unknown**.

### 2.1 The 33 cases (Prod = production, A/B/BQ = offline candidates; 'removed' = the false polarity conflict is gone)

| Case | Rows (claims) | Side | Cross-sentence | Trigger in context | Relation | Prod | A | B | BQ |
|---|---|---|---|---|---|---|---|---|---|
| P012 | F60:B-005:s12 | evidence | yes | 'do not' … rocedures Manual to determine their capacity to perform as required: (d) Supplies and reagents that do not bea… | RELATED | conflict | conflict | removed | removed |
| P013 | F60:B-005:s11 | evidence | yes | 'do not' … rocedures Manual to determine their capacity to perform as required: (d) Supplies and reagents that do not bea… | UNRELATED | conflict | removed | removed | removed |
| P015 | F60:B-005:s11 | evidence | yes | 'do not' … rocedures Manual to determine their capacity to perform as required: (d) Supplies and reagents that do not bea… | UNRELATED | conflict | removed | removed | removed |
| P035 | F60:D-001:s13, REAL17:D-001:s13 | claim | yes | 'do not' … ten procedures shall be established and followed prescribing a system for reprocessing batches that do not con… | UNRELATED | conflict | conflict | removed | removed |
| P038 | F60:D-001:s13, REAL17:D-001:s13 | claim | yes | 'do not' … ten procedures shall be established and followed prescribing a system for reprocessing batches that do not con… | UNRELATED | conflict | conflict | removed | removed |
| P057 | F60:F-003:s3 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P059 | F60:F-003:s8 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | STATING | conflict | removed | removed | removed |
| P060 | F60:F-003:s8 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | STATING | conflict | removed | removed | removed |
| P062 | F60:F-003:s11 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P063 | F60:F-003:s11 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P071 | F60:F-003:s4 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P079 | F60:F-003:s14 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P080 | F60:F-003:s14 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P092 | F60:F-009:s0.2, REAL17:F-009:s0.2 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P102 | F60:F-009:s4, REAL17:F-009:s4 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P116 | F60:F-012:s8 | evidence | yes | 'cannot' … d other objects that might fall into food, equipment, or containers, and removing hand jewelry that cannot be … | UNRELATED | conflict | removed | removed | removed |
| P118 | F60:F-022:s1 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P119 | F60:F-022:s1 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P120 | F60:F-022:s2 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | RELATED | conflict | removed | removed | removed |
| P122 | F60:F-022:s2 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | RELATED | conflict | removed | removed | removed |
| P124 | F60:F-022:s4.1 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P125 | F60:F-022:s4.1 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | removed | removed | removed |
| P127 | F60:F-022:s4.2 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | conflict | removed | removed |
| P128 | F60:F-022:s4.3 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | conflict | removed | removed |
| P129 | F60:F-022:s4.3 | evidence | yes | 'does not' … lic about any hazard presented by the food through reprocessing, reworking, diverting to a use that does not p… | UNRELATED | conflict | conflict | removed | removed |
| P041 | F60:D-007:s3 | claim | no | 'do not' … The procedures shall establish and follow written procedures for reprocessing batches that do not conform to s… | UNRELATED | conflict | conflict | removed | removed |
| P042 | F60:D-007:s3 | claim | no | 'do not' … The procedures shall establish and follow written procedures for reprocessing batches that do not conform to s… | UNRELATED | conflict | conflict | removed | removed |
| P046 | F60:D-009:s8 | claim | no | 'do not' … Written procedures shall establish a system for reprocessing batches that do not conform to standards or speci… | UNRELATED | conflict | conflict | removed | removed |
| P047 | F60:D-009:s8 | claim | no | 'do not' … Written procedures shall establish a system for reprocessing batches that do not conform to standards or speci… | UNRELATED | conflict | conflict | removed | removed |
| P048 | F60:D-009:s12 | evidence | no | 'do not' … ten procedures shall be established and followed prescribing a system for reprocessing batches that do not con… | UNRELATED | conflict | conflict | removed | removed |
| P083 | F60:F-004:s2 | evidence | no | 'cannot' … d other objects that might fall into food, equipment, or containers, and removing hand jewelry that cannot be … | UNRELATED | conflict | removed | removed | removed |
| P107 | F60:F-009:s6, REAL17:F-009:s6 | evidence | no | 'cannot' … d other objects that might fall into food, equipment, or containers, and removing hand jewelry that cannot be … | UNRELATED | conflict | removed | removed | removed |
| P110 | F60:F-012:s8 | evidence | no | 'cannot' … d other objects that might fall into food, equipment, or containers, and removing hand jewelry that cannot be … | UNRELATED | conflict | removed | removed | removed |

## 3. The two approaches compared

| | **A: sentence-local negation** | **B: relative-clause scope** |
|---|---|---|
| Linguistic principle | A rule's polarity is a property of the sentence (or enumerated unit) that states it. A negation in another sentence belongs to another rule. | A negation governed by a relative pronoun belongs to the clause that restricts a noun ("batches that do not conform"), not to the main verb carrying the duty. |
| Mechanism tested | Split the passage into sentences and enumerated units; read polarity from the unit that best matches the other side (stemmed overlap). | Skip a negation directly after *that/which/who* unless the preceding word takes a complement (ensure, require, provide, …). |
| Parsing needed | Sentence and enumeration segmentation **plus a unit-selection step** | A narrow pattern: pronoun + auxiliary + *not*, with a complement-verb exclusion list. No parser. |
| The 33 cases addressed | **22** (19 of 25 cross-sentence, 3 of 8 same-sentence) | **33** (25/25 and 8/8) |
| Real controls (15) | 9/15, identical to production | 9/15: fixes 4 production errors, creates 5 false supports |
| Wrongly suppressed genuine readings | **5 of 44** real-negation preservation controls lost (606.65 "the container **shall not** be used"; 820 "another investigation **is not** necessary"; L-010 guidance "**are not** required to list"), because the unit chosen for the claim is not the unit holding the negation | 0 of 44 preservation controls; but on real text it misses every **material** relative-clause negation that the claim inverts (T4a, T4c, T4d, T4e, T5a), and credits them as support |
| Main risk | It decides which rule is compared by word overlap: aligner-like **selection inside the operator layer**, which Phase 2D separated from judgement. It cannot split "…; a decimal fraction shall not …" (T3c). | Removes the only protection production has (accidental) against category-inverting claims. Those then pass the content gate as paraphrase or verbatim. |

**Combining them.** A+BQ adds A's 5 lost preservation readings and gains nothing over BQ: identical real-control results (13/15), and the same 33 cases fixed, since every A fix is also a B fix. **Keep them separate. A is not recommended at all.**

**BQ, the qualifier check, is what makes B defensible.** If both sides contain a relative clause on the same verb stem with opposite negation, that is a `qualifier_polarity` conflict. On real text it restores all four relative-clause inversions (T4a, T4c, T4d, T4e). It cannot see an inversion phrased as a participle or a "without" phrase (T5a: "levels **exceeding** 0.003 percent").

## 4. Real regulatory examples (traceable)

Every evidence text below is verbatim from the local eCFR snapshot (`cfr_records`, snapshot 2026-09-03), with its `content_sha256`, in `work/real_texts.json`. **The claims are constructed edits** (one qualifier or modal changed) and are labelled as such. No regulatory text was invented. The corpus scan is in `work/corpus_rel_negations.json` (1,077 sentences) and `work/corpus_flips_B.json` (B's 735 flips, 73 regex-flagged as material).

**Required categories:**

| Required category | Real text found |
|---|---|
| 1. Negated relative clause that must not negate the duty | 213.122(e), 211.115(a), 606.65(d) (T1a–c), plus the 33 original cases |
| 2. Genuine negated duty that must remain a contradiction | 212.40(c) "You must not use … any lot that does not meet its specifications"; 101.36(b)(2)(i) "… that are not present … shall not be declared" (T2a–c) |
| 3. Multi-sentence passage | 701.13(d) (T3b genuine, T3c false); the original 117.139 cases P059 and P060 |
| 4. Material relative-clause negation | 73.3110(c)(1), 1.379(a), 109.15(b)(2)(i), 211.115(a), 507.27(e) (T4a–e) |
| 5. Counterexamples found | T5a (an inversion phrased as a participle defeats BQ); T5b (133.111(d) "of which **shall** not exceed": protected in every candidate only because the "shall" inside the relative clause is misread as the rule's modal, i.e. accidental) |

### 4.1 Real-text controls and results

| ID | Type | Evidence (real, snapshot 2026-09-03; sha256 prefix) | Claim (constructed edit) | Expected | Production | A | B | BQ | A+BQ |
|---|---|---|---|---|---|---|---|---|---|
| T1a | 1 category qualifier must not negate the duty | 21 CFR 213.122(e) (ab14c46ade): "(e) Labels, labeling, and other packaging materials that are obsolete, outdated, or that do not meet applicable requirements shall be destroyed." | "Labels, labeling, and other packaging materials that are obsolete or outdated shall be destroyed." | no conflict | **false polarity conflict** | **false polarity conflict** | ok | ok | ok |
| T1b | 1 category qualifier must not negate the duty | 21 CFR 211.115(a) (6c7007ac67): "(a) Written procedures shall be established and followed prescribing a system for reprocessing batches that do not conform to standards or specificati…" | "Written procedures shall be established and followed for reprocessing batches." | no conflict | **false polarity conflict** | **false polarity conflict** | ok | ok | ok |
| T1c | 1 category qualifier must not negate the duty | 21 CFR 606.65(d) (ada228b346): "(d) Supplies and reagents that do not bear an expiration date shall be stored in such a manner that the oldest is used first." | "Supplies and reagents shall be stored in such a manner that the oldest is used first." | no conflict | **false polarity conflict** | **false polarity conflict** | ok | ok | ok |
| T2a | 2 genuine negated duty must stay a contradiction | 21 CFR 212.40(c) (3005e2bcc7): "You must not use in PET drug production any lot that does not meet its specifications, including any expiration date if applicable, or that has not ye…" | "You may use in PET drug production a lot that does not meet its specifications." | conflict | ok | ok | ok | ok | ok |
| T2b | 2 genuine negated duty must stay a contradiction | 21 CFR 212.40(c) (3005e2bcc7): "You must not use in PET drug production any lot that does not meet its specifications, including any expiration date if applicable, or that has not ye…" | "You must use in PET drug production any lot that does not meet its specifications." | conflict | **FALSE PARTIAL (drops_a_condition)** | **FALSE PARTIAL (drops_a_condition)** | ok | ok | ok |
| T2c | 2 genuine negated duty must stay a contradiction | 21 CFR 101.36(b)(2)(i) (20614d372e): "Any (b)(2)-dietary ingredients that are not present, or that are present in amounts that can be declared as zero in § 101.9(c), shall not be declared …" | "Any (b)(2)-dietary ingredients that are not present shall be declared." | conflict | **FALSE SUPPORT (paraphrase)** | **FALSE SUPPORT (paraphrase)** | ok | ok | ok |
| T3b | 3 multi-sentence: a real negated duty in another sentence | 21 CFR 701.13(d) (ea48022d88): "(d) The declaration may contain common or decimal fractions. A common fraction shall be in terms of halves, quarters, eighths, sixteenths, or thirty-s…" | "A decimal fraction may be carried out to more than two places." | conflict | ok | ok | ok | ok | ok |
| T3c | 3 multi-sentence: a positive duty beside a negated one | 21 CFR 701.13(d) (ea48022d88): "(d) The declaration may contain common or decimal fractions. A common fraction shall be in terms of halves, quarters, eighths, sixteenths, or thirty-s…" | "A common fraction shall be reduced to its lowest terms." | no conflict | **false polarity conflict** | **false polarity conflict** | **false polarity conflict** | **false polarity conflict** | **false polarity conflict** |
| T4a | 4 material relative negation (claim inverts it) | 21 CFR 73.3110(c)(1) (009ef7a88a): "Chlorophyllin-copper complex may be used at levels that do not exceed 0.003 percent by weight of the bone cement." | "Chlorophyllin-copper complex may be used at levels that exceed 0.003 percent by weight of the bone cement." | conflict | ok | ok | **FALSE SUPPORT (paraphrase)** | ok | ok |
| T4b | 4 material relative negation (claim inverts it) | 21 CFR 1.379(a) (51cbb3aa28): "(a) FDA may detain an article of food for a reasonable period that may not exceed 20 calendar days after the detention order is issued." | "FDA may detain an article of food for a reasonable period that may exceed 20 calendar days after the detention…" | conflict | ok | ok | ok | ok | ok |
| T4c | 4 material relative negation (claim inverts it) | 21 CFR 109.15(b)(2)(i) (51d2dc011f): "On or before Sept. 4, 1973, any such fluid formulated with PCB's must to the fullest extent possible commensurate with current good manufacturing prac…" | "On or before Sept. 4, 1973, any such fluid formulated with PCB's must to the fullest extent possible commensur…" | conflict | ok | ok | **FALSE SUPPORT (verbatim)** | ok | ok |
| T4d | 4 material relative negation (claim inverts it) | 21 CFR 211.115(a) (6c7007ac67): "(a) Written procedures shall be established and followed prescribing a system for reprocessing batches that do not conform to standards or specificati…" | "Written procedures shall be established and followed prescribing a system for reprocessing batches that confor…" | conflict | ok | ok | **FALSE SUPPORT (paraphrase)** | ok | ok |
| T4e | 4 material relative negation (claim inverts it) | 21 CFR 507.27(e) (913336e1b6): "(e) Unpackaged or bulk animal food must be held in a manner that does not result in unsafe cross contamination with other animal food." | "Unpackaged or bulk animal food must be held in a manner that results in unsafe cross contamination with other …" | conflict | ok | ok | **FALSE SUPPORT (paraphrase)** | ok | ok |
| T5a | 5 counterexample: the inversion phrased without a relative pronoun | 21 CFR 73.3110(c)(1) (009ef7a88a): "Chlorophyllin-copper complex may be used at levels that do not exceed 0.003 percent by weight of the bone cement." | "Chlorophyllin-copper complex may be used at levels exceeding 0.003 percent by weight of the bone cement." | conflict | ok | ok | **FALSE SUPPORT (paraphrase)** | **FALSE SUPPORT (paraphrase)** | **FALSE SUPPORT (paraphrase)** |
| T5b | 5 counterexample: a limit inside 'of which shall not exceed' | 21 CFR 133.111(d) (e0f7246179): "(d) Safe and suitable antimycotic agent(s), the cumulative levels of which shall not exceed current good manufacturing practice, may be added to the c…" | "Safe and suitable antimycotic agents may be added to the cheese at cumulative levels exceeding current good ma…" | conflict | ok | ok | ok | ok | ok |
| | **passed** | | | | 9/15 | 9/15 | 9/15 | 13/15 | 13/15 |

## 5. Offline candidate comparison

### 5.1 The 33 relative-clause cases

| Candidate | Fixed (of 33) | Cross-sentence (of 25) | Same-sentence (of 8) | Other 45 remaining false conflicts changed | New conflicts (replay of all recorded comparisons) |
|---|--:|--:|--:|---|--:|
| A (sentence-local) | 22 | 19 | 3 | 6 changed (C-004 epistemic pairs P019, P024, P028, P030, P031; H-006 P136) | 0 |
| B (relative-clause) | 33 | 25 | 8 | 0 | 1 (H-006: claim noun 'exemptions' unmasked; no verdict effect) |
| BQ | 33 | 25 | 8 | 0 | 1 (same) |
| A+BQ | 33 | 25 | 8 | 6 (as A) | 0 |

### 5.2 Real-text controls

See §4.1: production 9/15, A 9/15, B 9/15 (5 false supports), BQ 13/15, A+BQ 13/15.

### 5.3 Claim, answer and score changes over the 170 frozen row-runs

| Candidate | Claim changes | Answer changes | Score changes | Dimension changes |
|---|--:|--:|--:|--:|
| I0_identity | 0 | 0 | 0 | 0 |
| IA_sent | 0 | 0 | 0 | 0 |
| IB_rel | 0 | 0 | 0 | 0 |
| IBQ_rel_qual | 0 | 0 | 0 | 0 |
| IABQ_combined | 0 | 0 | 0 | 0 |

Each was measured by a full re-run (`work/h_cf_*.json`, `cf_diffs.json`). The identity copy reproduces production exactly.

## 6. Regression-control and Phase 2D safety results

| Check | Production | A | B | BQ | A+BQ |
|---|---|---|---|---|---|
| Genuine-contradiction tests (19) | 19 | 19 | 19 | 19 | 19 |
| Verbatim reading tests (6) | 6 | 6 | 6 | 6 | 6 |
| Real-negation preservation pairs (44) | 44 | **39** | 44 | 44 | **39** |
| Invented-condition pairs unchanged (18) | 18 | 18 | 18 | 18 | 18 |
| Full suite (incl. 240 Phase 2D gate tests, 8 Phase 2G contradiction tests) | 1832 passed, 1 skipped | same | same | same | same |
| F-007 / F-009 / every Phase 2D decision | unchanged | unchanged | unchanged | unchanged | unchanged |
| **Real-text controls (15)** | **9** | **9** | **9** | **13** | **13** |

**The existing safety net does not see the real-text failures.** Every candidate passes all 1832 tests and changes no frozen verdict, yet B creates five false supports on real text. The tests in §7 close that gap.

## 7. Proposed minimal regression tests (not added in this phase)

Seven tests: verbatim eCFR evidence, constructed claims labelled as such, a relevant question, asserting the **support basis** as well as the final verdict.

| # | Evidence | Claim | Assert | Today |
|---|---|---|---|---|
| 1 | 213.122(e) | "… that are obsolete or outdated shall be destroyed." | not CONTRADICTED; no polarity conflict | **fails** (CONTRADICTED) |
| 2 | 212.40(c) "You must not use …" | "You must use … any lot that does not meet its specifications." | polarity conflict; not credited | **fails** (false partial) |
| 3 | 101.36(b)(2)(i) "… shall not be declared" | "… that are not present shall be declared." | polarity conflict; not credited | **fails** (false support) |
| 4 | 211.115(a) "batches that do not conform" | "… batches that conform to standards or specifications." | a conflict; **not credited** | passes (by accident) |
| 5 | 109.15(b)(2)(i) "fluid that does not contain PCB's" | "… fluid that contains PCB's." | a conflict; **not credited** (B alone credits it verbatim) | passes (by accident) |
| 6 | 73.3110(c)(1) "levels that do not exceed 0.003 percent" | "… levels exceeding 0.003 percent …" | **not credited** | passes (by accident); BQ fails it |
| 7 | 701.13(d) (multi-sentence) | "A decimal fraction may be carried out to more than two places." | conflict | passes |

Optional 8th: T3c (701.13(d) vs "A common fraction shall be reduced to its lowest terms."). It needs semicolon-level scope, which is out of this phase's scope.

The frozen cases P059 and P060 (117.139) can serve as the real-claim regression, but their evidence is legacy-reconstructed.

**Coverage today vs this set:**
- **Positive duty with a negated relative clause:** no test today (tests 1, 4).
- **Genuine negated duty with a negated relative clause:** R05 checks only a single reading (tests 2, 3).
- **Negation in an adjacent sentence:** no test (test 7).
- **Category qualification vs obligation polarity:** no test (tests 4, 5, 6).

## 8. Limitations

- **Evidence.** The 33 cases use legacy-reconstructed evidence that joins paragraphs. Exact prompt-evidence snapshots do not exist for these rows. That production also merges paragraphs is shown only indirectly (the 820.10 context source).
- **Claims.** The real-text controls use verbatim regulation but **constructed** claims (single edits). No real answer in the frozen data inverts a relative-clause qualifier, so the false-support risk of B is demonstrated, not observed in production answers.
- **Corpus counts.** The 73 "material" flips come from a lexical filter (exceed, contaminate, result, contain, …) and are a lower bound, not a hand-verified count. The 1,077 / 890 / 735 figures are exact for the regex.
- **Candidate detail.** The candidates are prototypes. BQ's verb-stem matching, A's segmentation and B's complement list are heuristic, and different choices would move the numbers.
- **The qualifier check depends on phrasing.** It only sees inversions that keep a relative pronoun.
- **Scope.** The purpose-phrase and "exemption" mechanisms, and the H-006 conflict unmasked by B, were not investigated (out of scope).

## 9. Recommendation: investigate further

1. **Reject approach A** (sentence-local by overlap). It addresses only 22/33, does nothing for the real controls, loses real negation readings, and moves selection into the operator layer.
2. **Reject approach B on its own.** On verbatim regulatory text it creates false supports, including one verbatim credit, whenever a claim inverts a material qualifier. Production at least catches those, by accident.
3. **Continue with BQ, but do not implement it yet.** It is the only candidate that fixes all 33 cases *and* production's false contradiction, false partial and false support on real text (13/15 vs 9/15). One false-support class remains (inversions without a relative pronoun). Next step, as its own phase:
   - (a) add the seven real-text tests in §7, which are expected to fail today on 1–3;
   - (b) design the qualifier comparison to cover participle and "without" phrasings, and re-test against the corpus's material flips;
   - (c) re-run this phase's comparison.

   Implement only if all seven pass, with no change to the 170 frozen verdicts and no loss of preservation readings.
4. **Note for prioritisation.** Production's current behaviour on this mechanism is not merely noisy. On real text it credits a genuine must / must-not contradiction as support (tests 2–3). That is a reason to complete this work rather than leave the mechanism as is.

## 10. Confirmation of no changes

| Check | Result |
|---|---|
| `src/`, `scripts/`, `tests/`, `web/` (303 files) | identical by SHA-256, start and end (`work/manifest_*.sha256`) |
| Benchmark dataset, frozen inputs, test fixtures | identical (`work/benchmark_manifest_*.sha256`) |
| Git status | identical, 62 lines, start and end (`work/git_status_*.txt`) |
| Database | read-only connection (`default_transaction_read_only = on`); SELECT only |
| Files written | only under `artifacts/accuracy/measurement_audit_phase2i_20261009T044401Z/` |
| 300-question benchmark / live server | not run / not touched |

## Artifacts (`work/`)

- **Scans:** `corpus_scan.py` → `corpus_rel_negations.json`; `corpus_flips.py` → `corpus_flips_B.json`.
- **Real texts and controls:** `real_texts.json`, `controls_real.json`.
- **Variants:** `make_variants_i.py` → `variants/{I0_identity, IA_sent, IB_rel, IBQ_rel_qual, IABQ_combined}`.
- **Evaluation:** `eval_real_controls.py` → `real_controls_*.json`; `eval_controls_h.py` → `controls_result_*.json`; `collect_h.py` → `h_current.json` and `h_cf_*.json`; `diff_cf.py` → `cf_diffs.json`; `run_suite_variant.py`.
- **Tables:** `table_33.md`, `table_real_controls.md`.
