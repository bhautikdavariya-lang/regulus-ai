# Why 29 of 60 answers are UNVERIFIABLE: forensic report

Run analysed: `artifacts/accuracy/validation_semantic_2026-10-08T055521Z.json` (sha256 `3067c54f6d5a…`): 31 scored, 29 UNVERIFIABLE, Spearman 0.551. The earlier run `…055036Z` produced the same 29 rows. All 60 rows were re-run from the dataset and match the artifact exactly, verdict and score (`scripts/extract.py`). No production, evaluator, UI or test file was modified. Simulations patch code only inside a scratch process (`scripts/simulate.py`).

The 29 rows: A-001 A-002 A-003 A-004 B-004 C-003 C-005 D-005 D-006 E-001 E-007 E-010 F-004 F-007 G-005 H-001 H-006 K-003 L-010 M-020 M-031 M-032 M-033 M-034 M-035 M-036 M-037 M-038 PB-008.

## Executive summary

| Root cause | Rows | % |
|---|---:|---:|
| Evaluator: evidence present, evaluator can't use it | 7 | 24% |
| Evaluator, temporal: the data to decide already exists in the corpus | 6 | 21% |
| Harness: guidance text lost offline | 9 | 31% |
| Evidence: governing provision never retrieved, or corpus lacks the data | 6 | 21% |
| Inherent: the authority isn't in the corpus at all | 1 | 3% |

- **Evaluator-caused: 13.** Seven are segmentation and alignment problems (D-006, E-001, E-010, F-004, F-007, K-003, M-020). Six are temporal rows whose answer is already in corpus tables the evaluator doesn't read (M-031, M-032, M-034, M-035, M-036, PB-008).
- **Harness-caused: 9.**
- **Evidence-caused: 6.** Three are retrieval misses (B-004, C-003, G-005). Three are temporal rows needing data the corpus doesn't hold (M-033, M-037, M-038).
- **Genuinely unknowable: 1** (C-005, statutory MoCRA).

Could a human reviewer decide using the evidence the evaluator had? **YES 6, PARTIALLY 9, NO 14.**

Five findings change the picture:

1. **Answer complexity is not the cause.** UNVERIFIABLE answers are *simpler* than scored ones: 2.1 claims on average against 6.8. Answers with 9+ claims are never UNVERIFIABLE.
2. **"One bad claim blocks everything" is false.** None of the 29 UNVERIFIABLE rows has a single supported, contradicted or partially supported claim. 19 are never assessed at claim level at all: 10 have no evidence and the evaluator stops early, and 9 are refusals.
3. **Guidance loss is the largest single factor.** Guidance was lost in 22 of the 29 rows. Restoring it offline lifts coverage from 31 to 47 of 60 with no false highs.
4. **Restoring guidance exposes false contradictions the UNVERIFIABLE verdict currently hides.** Two correct (N=2) answers become INCORRECT 0: E-007 on polarity, and H-001 on duty-holder once more sentences are admitted. A "must" checked against guidance "should" reads as a modal conflict (K-003). A dietary-supplement guidance passes as support for a cosmetics (MoCRA) claim (C-005). The live UI sees guidance text, so it is probably exposed to these today. The 60-row validation cannot see them.
5. **The claim-sentence gate drops real propositions.** 43 of 377 answer sentences are dropped because they use "include / ensure / contain / affect", which aren't in the gate's verb list. That includes 9 of 12 sentences in F-007 and the human-flagged wrong sentence in E-010. They are labelled `too_short`, which hid the problem.

## 1. The 29 rows

Column A: was the governing provision present? Column B: was the evidence sufficient? Column C: could the evaluator use it? Column H: could a human decide? "live" means with the guidance text restored. The full table with explanations is in `ud_29_forensic_table.csv`, and per-row dossiers are in `dossiers/`.

| ID | N | Type | Cause | A | B | C | H | First undecidable claim | Recommendation |
|---|--:|---|---|---|---|---|---|---|---|
| A-001 | 1 | Direct | B harness | NO | NO (live PARTIAL) | n/a | NO (live YES) | #1 "PCAF … animal food", no evidence | restore guidance |
| A-002 | 0 | Direct | B harness | NO | NO | n/a | NO (live PARTIAL) | none (stops early) | restore guidance |
| A-003 | 1 | Cross-ref | B harness | part only | NO (live YES) | n/a | NO (live YES) | none (stops early) | restore guidance |
| A-004 | 1 | Cross-ref | B harness | NO | NO (live PARTIAL) | n/a | NO (live YES) | none (stops early) | restore guidance |
| B-004 | 1 | Direct | C missing CFR (601.12) | NO | NO | n/a | NO | none (stops early) | retrieval |
| C-003 | 0 | Direct | C missing CFR (740.10) | NO | NO | n/a | NO | none (refusal) | retrieval; add a domain check for refusal evidence |
| C-005 | 1 | Direct | A statute not in corpus | NO | NO | n/a | NO | none (stops early) | none (inherent) |
| D-005 | 0 | Direct | B harness | NO | live YES | YES | NO (live YES) | none (refusal) | restore guidance; add regression |
| D-006 | 0 | Direct | I false UD (headings ignored) | partial | YES | NO | **YES** | #1 the whole list, not decisive | use headings; split noun lists |
| E-001 | 1 | Direct | I false UD (framing lead, descriptive sentence) | YES | PARTIAL | NO | **YES** | #1 near-verbatim 11.1(a), not decisive | strip framing leads; check substitutions |
| E-007 | 2 | Direct | B harness (+ polarity defect) | NO | NO (live YES) | live NO | NO (live YES) | #1 signature linking, no evidence | restore guidance *with* the polarity fix |
| E-010 | 1 | Application | E segmentation | YES | PARTIAL | PARTIAL | PARTIALLY | #1 cloud LIMS, no evidence | widen the claim gate |
| F-004 | 1 | Direct | I false UD (claim spans two evidence sentences) | partial | YES | NO | **YES** | #1 grounds, not decisive | align against adjacent sentences |
| F-007 | 1 | Direct | I false UD (gate dropped 9 of 12 sentences) | partial | YES | NO | **YES** | #1 plan contents, not decisive | widen the claim gate |
| G-005 | 1 | Direct | C missing CFR (201.62) | NO | NO | n/a | NO | none (stops early) | retrieval |
| H-001 | 2 | Direct | B harness (+ duty-holder defect) | NO | NO (live YES) | live PARTIAL | NO (live YES) | none (stops early) | restore guidance; fix the duty-holder check |
| H-006 | 1 | Cross-ref | B harness (+ condition defect) | NO | NO | live NO | NO (live PARTIAL) | none (stops early) | restore guidance |
| K-003 | 0 | Cross-ref | I false UD (question echo fools relevance) | NO | YES for wrong-topic | NO | **YES** | #1 "children … device description", no evidence | strip embedded question echoes |
| L-010 | 2 | Direct | B harness | NO | NO (live PARTIAL) | live NO | NO (live YES) | none (stops early) | restore guidance; fix score saturation |
| M-020 | 2 | Direct | I false UD (list not split) | YES | YES | NO | **YES** | #1 the 12-item list, not decisive | split modal-less lists |
| M-031 | 1 | Temporal | G (reserved span not looked up) | NO | NO | NO | PARTIALLY | none (refusal) | section-range lookup |
| M-032 | 1 | Temporal | G (legacy_qsr_terms unused) | partial | PARTIAL | NO | PARTIALLY | none (refusal) | use legacy_qsr_terms + redirect map |
| M-033 | 1 | Temporal | G (no section-to-subpart map) | NO | NO | NO | PARTIALLY | none (refusal) | data: subpart map + redirect map |
| M-034 | 0 | Temporal | G (legacy_qsr_terms unused) | YES | PARTIAL | NO | PARTIALLY | #1 "DMR is required…", not decisive | use legacy_qsr_terms |
| M-035 | 1 | Temporal | G (reserved span) | NO | NO | NO | PARTIALLY | none (refusal) | section-range lookup |
| M-036 | 1 | Temporal | G (reserved span) | NO | NO | NO | PARTIALLY | none (refusal) | section-range lookup |
| M-037 | 1 | Temporal | G (no subpart map) | NO | NO | NO | PARTIALLY | none (refusal) | data: subpart map + redirect map |
| M-038 | 1 | Temporal | G (no subpart map) | NO | NO | NO | PARTIALLY | none (refusal) | data: subpart map + redirect map |
| PB-008 | 0 | Temporal | G (`cfr_subparts` unused) | NO | NO | NO | NO (YES via structure) | #1 "Subparts C–O still apply", no evidence | structure lookup |

## 2. Root-cause distribution

| Cause | Rows |
|---|--:|
| B: guidance lost in harness | 9 |
| G: temporal / regulatory logic | 9 |
| I: false UNVERIFIABLE (evaluator has the evidence, human decides) | 6 |
| C: governing CFR not retrieved | 3 |
| E: segmentation | 1 |
| A: evidence genuinely unavailable | 1 |
| D, F, H, J, K as primary cause | 0 |

D (evaluator can't interpret evidence) and F (question intent or relevance) appear as the *mechanism* behind the six I rows: D for E-001, F-004 and D-006; F for K-003; E for F-007 and M-020. No row is J (legitimately unverifiable to a human given the evaluator's evidence and the corpus). C-005 comes closest.

## 3. By question type (all 60 rows)

| Type | Total | UD | % |
|---|--:|--:|--:|
| Direct Lookup | 42 | 15 | 36% |
| Temporal/Version | 9 | 9 | **100%** |
| Cross-Reference | 5 | 4 | **80%** |
| Application | 1 | 1 | 100% |
| Distinction | 2 | 0 | 0% |
| Negative Control | 1 | 0 | 0% |

Temporal and cross-reference questions are disproportionately UNVERIFIABLE:

- **Temporal:** every row needs reserved-section status, and the evaluator doesn't read it from the corpus.
- **Cross-reference:** 3 of the 4 are guidance-only evidence lost in the harness.

## 4. By answer feature (non-exclusive)

| Feature | Total | UD | UD % |
|---|--:|--:|--:|
| Evidence includes guidance (all of it lost in harness) | 34 | 22 | 65% |
| Temporal / false-premise trap | 10 | 9 | 90% |
| Refusal | 11 | 9 | 82% |
| No citation markers | 8 | 5 | 62% |
| Human N=2 | 9 | 4 | 44% |
| Wrong topic (reviewer-confirmed) | 12 | 3 | 25% |
| Multi-claim (4+ claim sentences) | 23 | 5 | 22% |
| Withheld / suppressed | 2 | 0 | 0% |

## 5. Claim count

Claim count is the number of claim sentences per answer, from segmentation.

| Claims | Total | UD | UD % |
|---|--:|--:|--:|
| 0 | 11 | 9 | 82% |
| 1 | 6 | 5 | 83% |
| 2–3 | 20 | 10 | 50% |
| 4–5 | 7 | 3 | 43% |
| 6–8 | 6 | 2 | 33% |
| 9+ | 10 | 0 | 0% |

- **Scored answers:** mean 6.8 claims, median 5, maximum 23.
- **UNVERIFIABLE answers:** mean 2.1, median 2, maximum 7. Refusals excluded: mean 3.0.

UNVERIFIABLE falls as complexity rises, so complexity is not the cause. Long answers usually quote retrieved CFR text and get decided.

## 6. First undecidable claim, and the claim-exclusion test (§10–11)

**How the 29 rows split:**

| Path | Rows |
|---|--:|
| No evidence, evaluator stops before claims | 9 |
| Refusal (no claims to assess) | 9 |
| Claims assessed | 11 |

**The 11 rows with assessed claims:**
- 23 claims in total: 22 UNVERIFIABLE, 1 irrelevant. None supported, contradicted or partially supported.
- The first undecidable claim is always claim #1.
- 5 are "no evidence" (A-001, E-007, E-010, K-003, PB-008); 6 are "not decisive" (D-006, E-001, F-004, F-007, M-020, M-034).
- A human could decide claim #1 in 6 of them, partly in 2, and not in 3.

**Claim-exclusion simulation (drop UNVERIFIABLE claims, then judge the answer):**
- Changes 1 of the 29 rows: F-007 goes UNVERIFIABLE → off_topic 0, which is wrong (human N=1).
- On rows already scored, it inflates N=1 answers: C-002, E-009 and G-010 go to correct 85, and F-015 to correct 45. C-004 (N=2) goes 35 → 15.

The all-or-nothing aggregation is not what causes UNVERIFIABLE, and excluding unverified claims would make scores *less* trustworthy.

## 7. Lost N=2 answers (4)

| ID | Why missed | Category | After the obvious fix |
|---|---|---|---|
| E-007 | Guidance lost; with guidance restored, polarity reads "to ensure … *cannot* be excised" as negating the main clause | guidance reconstruction + operator logic | **INCORRECT 0** (false) |
| H-001 | Guidance lost | guidance reconstruction | partial 40; with the gate widened, **INCORRECT 0**: "FDA provides an abbreviated renewal" read as moving the duty onto FDA |
| L-010 | Guidance lost; statute 403(w) not in corpus | guidance reconstruction + scoring | partial 0: 5 claims not decisive against Q&A guidance, and the deductions add up to 0 |
| M-020 | One 12-item list sentence with no modal, never split; `[n]` markers break the verbatim run | segmentation | n/a (needs list splitting) |

## 8. N=0 rows left UNVERIFIABLE (7)

**Good uncertainty (the retrieved evidence can't establish the answer is wrong): A-002, C-003, PB-008.**
- PB-008 can be recovered without retrieval: the `cfr_subparts` row "C-O [Reserved]" directly contradicts the claim.

**Bad uncertainty (the evaluator already had, or could easily read, what proves it wrong): D-006, K-003, M-034, D-005.**
- **D-006:** the answer is a list of the evidence's own section headings.
- **K-003:** the answer's subject is visibly a device description, not children.
- **M-034:** `legacy_qsr_terms` lists DMR, DHR and DHF as *former* sections.
- **D-005:** the on-topic aseptic-processing guidance was lost by the harness.

No N=0 row became a false high in any simulation: zero false highs across all seven scenarios.

## 9. Missed incorrect refusals (§15)

**C-003**
1. Governing provision present? 740.10 is in the corpus but was never retrieved.
2. Did the answer incorrectly refuse? Yes.
3. Did the evaluator have enough evidence? No. Its only evidence was tobacco warning-plan guidance, and the harness lost even that.
4. Why UNVERIFIABLE? Nothing in its evidence covers the question.
5. Problem type: **evidence (retrieval)**. With the tobacco guidance restored, the evaluator calls the refusal incorrect. That's the right verdict for the wrong reason: the words "warning statement" match, and refusal evidence gets no product-domain check.

**D-005**
1. Governing provision present? 211.42 was not retrieved.
2. Did the answer incorrectly refuse? Yes.
3. Did the evaluator have enough evidence? Live, yes: the "Sterile Drug Products Produced by Aseptic Processing" guidance was in the evidence.
4. Why UNVERIFIABLE? The harness dropped that guidance. Restored, the verdict is abstention_incorrect 0, which is correct.
5. Problem type: **harness**.

Regression cases for later: D-005 with the guidance text should be abstention_incorrect. C-003 must not be marked incorrect on the strength of wrong-domain evidence.

## 10. Guidance loss (§6)

Guidance was lost in 22 of the 29 UNVERIFIABLE rows; every guidance label in the 60-row set is lost. The question is whether restoring the guidance *alone* would make the answer evaluable.

**The 15 non-temporal rows:**

| Restore alone works? | Rows | Notes |
|---|---|---|
| YES (4) | A-001, A-003, A-004, D-005 | |
| PARTIAL (3) | A-002, H-001, L-010 | evaluable, but scores are false-low or omissions can't be proven |
| NO (8) | B-004, G-005, C-003, C-005, E-007, H-006, K-003, PB-008 | see blockers below |

Remaining blockers for the NO rows:
- B-004 and G-005: the governing CFR section was never retrieved.
- C-003 and C-005: the guidance is from the wrong product domain.
- E-007: false polarity contradiction.
- H-006: probable false "invented condition" (the farm exception is real).
- K-003: correct verdict for the wrong reason (strength checked against guidance "should").
- PB-008: still UNVERIFIABLE.

**The 7 temporal refusals:** the lost guidance is unrelated (combination products, cybersecurity, ISO 10993). Five reach "partial 45" only through generic words like "design/control". That's coincidence, not a fix.

**Simulation totals:**
- Guidance ranked against the question: coverage 47 of 60, false highs 0. N=2 mean 59.4; N=1 mean 26.2; N=0 mean 8.2.
- Guidance ranked against the answer (upper bound): coverage 45 of 60.

**Caveat:** the live run recorded guidance *titles*, not chunk IDs. Restored chunks are the document's top full-text matches, so this is an approximation.

A second harness defect: labels are deduplicated and lost entries skipped, so `[n]` markers shift. In A-001, `[1]` points to guidance live but to 21 CFR 4.3 offline. This affects citation verdicts, not UNVERIFIABLE.

## 11. Temporal analysis (§16)

**What the corpus already has, unused:**
- **`cfr_sections` row "820.20-820.30 [Reserved]".** `DatabaseIdentifierIndex.section_status()` expands *part* ranges only. So `820.30` → `(False, False)`, exactly like `820.999`. That is why superseded and nonexistent look identical for 820.20, 820.22 and 820.30.
- **`cfr_subparts` "C-O [Reserved]".**
- **`legacy_qsr_terms` (5 rows):** 820.30 Design Controls, 820.30(j) DHF, 820.100 CAPA, 820.181 DMR, 820.184 DHR.

**What is genuinely missing:**
- A section-to-subpart map for the former Part 820, needed for 820.50, 820.75 and 820.198.
- Supersession dates: `effective_date` is null for Part 820, and `cfr_record_versions` has 0 rows, so there is no historical text.
- Redirect targets (820.30 → 820.10(c) and ISO 7.3): `part820_section_flags` has 0 rows, and `legacy_qsr_terms.iso_clause_id` is null.

A question date is not needed (there is one snapshot, 2026-09-03).

**Retrieval behaviour:** it returns number-alike sections (520.100, 522.820, 800.75), so redirect evidence can't be expected from retrieval.

**Can each distinction be made?**

| Distinction | Possible today? |
|---|---|
| Current vs nonexistent | Yes |
| Superseded vs nonexistent | Yes for 6 sections with existing data, no for the rest |
| Historical text | Impossible |

## 12. True scoreability (§17)

| Evidence lens | Clearly scoreable | Partially | Not scoreable |
|---|--:|--:|--:|
| What the evaluator saw (official run) | 6 | 3 | 20 |
| Plus guidance restored (what the live UI sees) | 11 | 7 | 11 |
| Plus corpus structure lookups | 15 | 10 | 4 |

**What the evaluator saw:**
- Clearly scoreable: D-006, E-001, F-004, F-007, K-003, M-020.
- Partially: E-010, M-032, M-034.

**After all lookups, still not scoreable:** B-004, G-005, C-003 (retrieval misses) and C-005 (inherent).

The evaluator problem is larger than "29 UNVERIFIABLE" suggests in one way, and smaller in another:
- Only 1 of the 29 is truly unknowable.
- Of the rest, 9 depend on harness fidelity and 13 on evaluator changes.
- 7 rows, though, are UNVERIFIABLE *protecting* us from false INCORRECT verdicts the evaluator would otherwise produce on guidance text.

## 13. Fix first (top 3)

**1. Make validation evidence identical to the answer's evidence.**
- **Problem:** the 60-row validation evaluates without guidance text, so it measures neither coverage nor trust for 34 of 60 answers.
- **Evidence:** 22 of 29 UNVERIFIABLE rows lost guidance. Restoration lifts coverage from 31 to 47 and exposes four operator defects.
- **Expected impact:** fixes 4 rows outright and makes 3 more evaluable. Most of all, it makes every other number real.
- **Risk:** none to production. This is recording or replaying the evidence text and chunk IDs per answer.

**2. Make the operators safe on guidance text.**
- **Problem:**
  - Guidance "should" contradicts a CFR "must".
  - Polarity reads purpose clauses ("to ensure … cannot").
  - The duty-holder check treats descriptive "FDA provides" as moving the duty onto FDA.
  - Guidance sources get no product-domain check.
- **Evidence:** E-007 and H-001 (N=2 → INCORRECT 0); K-003 (right outcome, wrong reason); C-005 (supplement guidance supports a MoCRA claim); H-006 (probable false condition).
- **Expected impact:** removes false INCORRECT verdicts that the live UI is probably already showing on guidance-backed answers.
- **Risk:** loosening could hide real contradictions. Each change needs a paired positive and negative regression.

**3. Fix segmentation and alignment.**
- **Problem:**
  - The verb gate drops "include / ensure / contain / affect" sentences.
  - Lists with no modal are never split.
  - Alignment is one evidence sentence at a time.
  - "X, which states that" leads aren't stripped.
  - Relevance ignores section headings and question echoes embedded mid-sentence.
- **Evidence:** 43 of 377 sentences dropped (27 in UD rows). False UNVERIFIABLE on D-006, E-001, F-004, F-007, K-003, M-020; E-010's wrong sentence never examined.
- **Expected impact:** 6–7 rows become decidable, 2 of them N=0 wrong-topic and 1 N=2.
- **Risk:** admitting more sentences surfaces more undecided claims. In simulation, removing the gate alone dropped G-004 (N=2) from 100 to 40 and C-004 from 35 to 0. It needs fix 3's alignment parts and a look at score saturation, and must be measured.

## 14. Do NOT fix yet

- **Claim-exclusion aggregation.** It inflates N=1 answers to 85 and flips F-007 to off_topic.
- **Score calibration, saturation and Spearman.** Measure only after fixes 1–3.
- **Temporal redirects.** These need curated data (`part820_section_flags`), not evaluator logic.
- **The section-range lookup.** It lives in `regulus.grounding`, which the production gate shares. The evaluator would need its own lookup so production behaviour doesn't change. Worth doing after fixes 1–3: it unlocks 3 rows outright and 3 with `legacy_qsr_terms` and subpart data.
- **Retrieval misses (B-004, C-003, G-005)** and the MoCRA corpus gap (C-005). Out of scope for the evaluator.
- **Treating absence as proof of falsity** (M-034). Use explicit metadata instead.

## 15. Final recommendation

The single most important change: **evaluate every answer against exactly the evidence it was generated from, guidance text included.** Persist the evidence text, or the chunk IDs, per answer, and validate on that.

Today, 65% of the UNVERIFIABLE verdicts and 34 of 60 rows sit on evidence the harness can't rebuild. That makes the validation blind to how the live evaluator behaves on guidance. The simulation shows that behaviour includes false INCORRECT verdicts on correct answers (E-007, H-001).

Until fixes 1 and 2 land, the earlier "YES WITH LIMITATIONS" for the per-question UI needs one more limitation: an INCORRECT verdict that rests only on an operator conflict with *guidance* text should not be trusted.
