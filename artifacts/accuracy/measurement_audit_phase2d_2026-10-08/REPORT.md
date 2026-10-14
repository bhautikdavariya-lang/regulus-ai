# Measurement Audit Phase 2D: regulatory content support gate

**Invariant enforced:** evidence receives support credit only after it has independently established the core proposition the claim expresses. A condition mismatch can downgrade an established proposition. It can never establish one.

**Scope of validation:**
- the 121 hand-labelled Phase 2C decisions (frozen; 203 aligner instances);
- every support decision on the frozen 60 rows (both aligners);
- the 60-row answer level;
- the live ON/OFF regression.

All 60-row figures use LEGACY_RECONSTRUCTED evidence. None of them is exact-evidence validation. No 300-question benchmark was run. Nothing here is "Regulus accuracy".

**Before = pre-Phase-2D evaluator.** The accuracy package is not under version control, so the pre-2D code was rebuilt in a scratch directory by reversing this phase's 52 recorded edits (`scripts/pre2d_*.py`). The rebuilt code reproduces Phase 2C's recorded support decisions exactly: 338/338 decided, identical basis and source. Production files were not touched by the rebuild.

## A. Implementation summary

Four evaluator modules changed, and nothing else under `src/`:

| File | Change |
|---|---|
| `src/regulus/accuracy/verdicts.py` | **Content gate** (`content_gate`, `core_terms`, `distinguishing_terms`, `framed_overlap`, `core_overlap`) applied before any SUPPORTED or PARTIAL verdict on every path (sentence, list item, descriptive, adjacent window). Gate trace attached to each verdict (`ClaimVerdict.gate`). |
| `src/regulus/accuracy/answer.py` | Passes the row's evidence pool to every judge path, including citation grounding's `support_against`, so the contrastive guard can see the other sources. Puts the gate trace in `operator_trace.content_gate`. Phase 2A logic is otherwise unchanged. |
| `src/regulus/accuracy/operators.py` | `provided that` (and `provided further that`, `provided however that`, `on condition that`) is a condition. Equivalent wordings preserve it. A proviso only the claim states is recorded (`proviso_not_in_evidence`), never a conflict. |
| `src/regulus/accuracy/claims.py` | A sentence that ends in a colon once its citation markers are stripped is a list lead-in with no list: NON_CLAIM (heading). |

**Support decision pipeline (verdicts.judge)**
1. **Candidate selection** (unchanged). The aligner proposes passages; contradiction and Priority-2 support-blocking run over all candidates, as before. The candidate used is the one the pre-2D judge used: the best verbatim candidate, otherwise the top clean one. It is recorded as `candidate_selection` and never decides support.
2. **Content gate** on that candidate:
   - **blocked**: the claim names a *distinguishing term*. That is a core term absent from the candidate's own source (its text and heading) and present in another evidence source. Skipped at 100% verbatim coverage.
   - **established**: verbatim (≥80% coverage with a run of ≥6 words). Otherwise: ≥2 operators agree, ≥70% of the claim's *framed* terms (framing words excluded) are present, and ≥70% of its *core* terms are present.
   - **established_terms_only**: the passage states no strength and no polarity, so operator agreement can't be tested, and every core term plus ≥90% of the framed terms is present. This status can found a PARTIAL only, never a full support.
   - **not_established**: otherwise.
3. **Verdict:**
   - not established → UNDECIDABLE (unverifiable);
   - established with material omissions → PARTIAL;
   - verbatim → SUPPORTED;
   - otherwise PARAPHRASE, and only at the unchanged paraphrase standard (≥2 operators agree, raw term overlap ≥70%).

   The gate never moves on to a lower-ranked candidate.

**Vocabularies**, documented in `verdicts.py`:
- `_GENERIC_WORDS`: modal and "require" family; ensure, establish, maintain, follow, apply, include, contain, provide, conduct, implement, specify, state, submit, comply, record, report, keep, use, make, add, achieve; discourse words (also, additional, general, certain, specific, such, these, those, this, that, other, any, each, all, same); structural words (part, subpart, section, paragraph, chapter, title, cfr); fda, agency, regulation, provision.

  These never distinguish. The head noun of a leading anaphor ("These *ingredients*…") is not a core term.
- `_FRAMING_WORDS`: the modal and require family, fda, agency, commissioner, and discourse words. These are excluded from the overlap used to found content. Action verbs still count.

**List items:**
- a "Subpart X" label in the list head must appear as "subpart X" in the passage text or heading;
- items pass the contrastive guard;
- an item that drops a condition is PARTIAL (E-005).

**Trace** (`operator_trace.content_gate`, on every gated decision): `content_gate_verdict`, `distinguishing_terms`, `distinguishing_term_sources`, `core_subject_match`, `core_object_match`, `core_action_match`, `core_actor_match`, `condition_match`, `material_omissions`, `content_support_reason`, `support_block_reason`, `core_overlap`, `term_overlap`, `raw_term_overlap`, `operators_agreed`, `operator_silent_passage`, `candidate_selection`. `match_path` stays on the claim (sentence / descriptive / list_item / adjacent_window).

**Three implementation decisions forced by measurement** (each a tightening):
1. **The gate stays on the selected candidate.** Letting it walk down the candidate list granted 9 supports the pre-2D judge never gave, e.g. "117.190(a) requires attestations" credited to 117.201(a).
2. **Discounting framing words founds partials only.** Full paraphrase keeps the raw-overlap standard.
3. **Term-only content never gives full support.** "(a) Corrective action procedures.", a bare heading, holds every term of "requires corrective action procedures" and states no rule.

## B. Root cause → fix mapping

| Defect | Root cause | Fix | Test (`tests/test_accuracy_content_gate.py`) |
|---|---|---|---|
| 26 false partials | `judge()` returned PARTIAL on any omission before checking content | Omission downgrades only a gate-established proposition, on every path | `test_all_38_false_decisions_are_prevented`, `test_condition_mismatch_without_content_support_is_not_partial`, F-009/F-022/M-034/E-005 tests |
| Object substitution (B-003, C-002, C-004 lex, D-007, D-008, F-007 lex) | ≥2 agreeing operators (strength and polarity) and ≥70% overlap let the object differ | Contrastive distinguishing-term guard | `test_B003_…`, `test_C002_…`, `test_C004_bithionol_…`, `test_D007_…`, `test_object_substitution_is_blocked_with_its_contrasting_source` |
| E-005 item drops "as appropriate" | `judge_item` ignored omissions | Item omissions → PARTIAL | `test_E005_list_item_that_drops_as_appropriate_is_partial_not_supported` |
| F-003 "Subpart B" matched by a Subpart C source | Structural word matched generically | Subpart label must be established by the passage | `test_F003_subpart_b_label_must_be_established_by_the_source` |
| B-005 "provided that" | Not a recognised condition | PROVIDED_THAT operator | `test_B005_…`, five `provided that` tests (without/with, equivalents, nested, claim-only proviso) |
| D-004 "include the following: [1]…[18]" | Lead-in extracted as a claim | Colon-ended lead-in → NON_CLAIM | `test_D004_content_free_list_lead_is_a_non_claim` |
| F-012 window "validation" vs "verification" | Window judged by shared words | Window verdict goes through `judge`, so through the gate | `test_F012_validation_is_not_supported_by_a_verification_window` |
| Anaphora (C-004 "These ingredients") | Would be blocked by "ingredient" | Anaphor head excluded from core terms | `test_C004_anaphora_these_ingredients_is_preserved_under_both_aligners` |

## C. Before/after on the Phase 2C labelled set (support level, diagnostic)

| Metric | Before | After |
|---|--:|--:|
| False support (of 12) | 12 | **0** |
| False partial (of 26) | 26 | **0** |
| Safe support preserved (of 71) | 71 | **71** |
| Safe partial preserved (of 12) | 12 | **11**. The one change is the Phase 2C-documented conservative case (drop15). |
| False-support rate among examined supports | 12/83 = 14% | 0/71 = 0% |
| False-partial rate among examined partials | 26/38 = 68% | 0/12 = 0% (plus 1 E-005 item, now a correct partial) |

**Outside the labelled set** (all 718/720 decisions on the frozen 60, both aligners):
- 0 new supported or partial decisions;
- 0 unlabelled pre-2D decisions changed;
- 0 decisions now credited to a different source.

The gate only withdrew credit.

**Answer level, frozen 60** (semantic aligner of record; lexical in brackets):

| Metric | Before | After |
|---|--:|--:|
| Answer verdicts changed | — | 2 (F-003, M-034) [1: F-003] |
| Rows whose score changed | — | 3 (B-003, F-003, M-034) [4: + C-004, F-012] |
| N=0 rows scored > 50 | 0 [0] | 0 [0] |
| Rows with question relevance ≠ pass scored > 50 | 0 [0] | 0 [0] |
| Off-topic rows with score > 0 | 0 [0] | 0 [0] |
| Incorrect refusals scored > 50 | 0 [0] | 0 [0] |
| Citation dimension vs human L (2A metric) | 28/31, 3 FP, 0 FN [28/32, 1 FN] | 29/32, 3 FP, 0 FN [29/32, 0 FN] |

**The changes:**
- **B-003** (N=1): partial 15 → 0. The two "application" claims lost their false support.
- **M-034** (N=0): partial 0 → unverifiable. The Design History File claim lost its 820.45 partial.
- **F-003** (N=1): off_topic 0 → unverifiable, no score. "Off-topic" had rested on the false partials. Those credited Subpart C passages to claims asserting "Subpart B includes…". Without them, what those claims rest on can't be established.
- **C-004 lexical**: 0 → 35. The bithionol false support no longer makes `[1]` look mis-cited, so the citation dimension is now correct under both aligners.
- **F-012 lexical**: 15 → 0. The window false support was removed.

Both Phase 2C's predicted impacts (B-003, M-034) are reproduced.

## D. False-decision audit: all 38

"Arm(s)" lists the aligners that made the false decision; every arm now gives the verdict shown. The "why" column is generated from the gate trace of the final verdict (terms are stems; at most three contrasting sources are listed). For #21 and #29 the passage named is the one the final, sentence-level verdict was checked against; the list-item (117.190(a)) and window (117.165(a)) credits are gone.

| # | Row | Phase 2C | Claim (abridged) | Was credited to | Arm(s) | New verdict | Why (gate trace) |
|---|---|---|---|---|---|---|---|
| 1 | B-003 | false support (paraphrase) | The application must be submitted in electronic format, with the electronic… | 21 CFR 601.14(a) | sem+lex | **unverifiable** | blocked: claim names *applic*, absent from 21 CFR 601.14(a), stated in 21 CFR 601.12(a); 21 CFR 601.20(a); 21 CFR 601.22 |
| 2 | B-003 | false support (paraphrase) | The application must be submitted within 60 days of the anniversary date of… | 21 CFR 601.28 | sem+lex | **unverifiable** | blocked: claim names *applic*, absent from 21 CFR 601.28, stated in 21 CFR 601.12(a); 21 CFR 601.20(a); 21 CFR 601.22 |
| 3 | B-005 | false support (descriptive) | The use of plateletpheresis and leukapheresis procedures may vary with addi… | 21 CFR 606.110(a) | sem+lex | **unverifiable** | not established: 0 operators agree, 83% of terms / 80% of core terms in 21 CFR 606.110(a) |
| 4 | C-002 | false support (paraphrase) | The label shall specify the identity of the commodity and the name and plac… | 21 CFR 701.12(a) | sem+lex | **unverifiable** | blocked: claim names *commod, ident*, absent from 21 CFR 701.12(a), stated in 21 CFR 701.11(a); 21 CFR 701.3(a) |
| 5 | C-004 | false support (paraphrase) | The use of bithionol in cosmetics is prohibited [1]. | 21 CFR 700.23 | lex | **unverifiable** | blocked: claim names *bithionol*, absent from 21 CFR 700.23, stated in 21 CFR 700.11(a) |
| 6 | D-004 | false partial (partial) | Under Part 211, the consultant requirements include microbiological contami… | 21 CFR 211.110(a) | sem | **unverifiable** | blocked: claim names *contamin, microbiological*, absent from 21 CFR 211.110(a), stated in 21 CFR 211.113(a); 21 CFR 211.130 |
| 7 | D-004 | false partial (partial) | Under Part 211, the consultant requirements include drug product inspection. | 21 CFR 211.101 | lex | **unverifiable** | blocked: claim names *inspect*, absent from 21 CFR 211.101, stated in 21 CFR 211.130; 21 CFR 211.134(a) |
| 8 | D-004 | false support (paraphrase) | The written procedures shall include the following sub-requirements: [1][2]… | 21 CFR 211.101 | lex | **non-claim** | list lead-in with no proposition: a non-claim |
| 9 | D-007 | false support (paraphrase) | Written procedures shall be established and followed for packaging and labe… | 21 CFR 211.122(a) | sem+lex | **unverifiable** | blocked: claim names *oper*, absent from 21 CFR 211.122(a), stated in 21 CFR 211.101; 21 CFR 211.125(a); 21 CFR 211.130 |
| 10 | D-008 | false support (paraphrase) | - Calibration procedures and records must be maintained, as required by 21 … | 21 CFR 211.68(a) | sem | **unverifiable** | blocked: claim names *procedur*, absent from 21 CFR 211.68(a), stated in 21 CFR 213.68(a) |
| 11 | D-010 | false partial (partial) | - Quality control operations for components, packaging, and labels (eCFR 21… | 21 CFR 111.113(b)(1) | sem | **unverifiable** | blocked: claim names *suitabl*, absent from 21 CFR 111.113(b)(1), stated in 21 CFR 111.120(d) |
| 12 | E-005 | false partial (partial) | The Replacement Reagent Policy applies only to open systems. | 21 CFR 11.30 | sem+lex | **unverifiable** | not established: 0 operators agree, 33% of terms / 40% of core terms in 21 CFR 11.30 |
| 13 | E-005 | false support (list item) | The FDA requires additional controls for open systems, including confidenti… | 21 CFR 11.30 | sem+lex | **partial** | item established; omits "as appropriate" → partial (Phase 2C's correct verdict) |
| 14 | F-003 | false partial (partial) | The CGMP requirements under Part 117 Subpart B include preventive controls. | 21 CFR 117.140(a) | sem | **unverifiable** | not established: 0 operators agree, 50% of terms / 67% of core terms in 21 CFR 117.140(a) |
| 15 | F-003 | false partial (partial) | The CGMP requirements under Part 117 Subpart B include circumstances in whi… | 21 CFR 117.140(a) | sem | **unverifiable** | blocked: claim names *circumstanc*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.136(a); 21 CFR 117.145; 21 CFR 117.251(a) |
| 16 | F-003 | false partial (partial) | The CGMP requirements under Part 117 Subpart B include assurances under pre… | 21 CFR 117.140(a) | sem | **unverifiable** | blocked: claim names *assuranc*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.135(a)(1); 21 CFR 117.137; 21 CFR 117.145 |
| 17 | F-003 | false partial (partial) | The CGMP requirements under Part 117 Subpart B include recall plans. | 21 CFR 117.139 | sem | **unverifiable** | not established: 0 operators agree, 25% of terms / 67% of core terms in 21 CFR 117.139 |
| 18 | F-003 | false partial (partial) | The CGMP requirements under Part 117 Subpart B include preventive control m… | 21 CFR 117.140(a) | sem+lex | **unverifiable** | not established: 0 operators agree, 67% of terms / 80% of core terms in 21 CFR 117.140(a) |
| 19 | F-003 | false partial (partial) | - 21 CFR 117.135(a)(1) requires preventive controls to minimize or prevent … | 21 CFR 117.140(a) | sem | **unverifiable** | blocked: claim names *hazard, minimiz*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.130(a); 21 CFR 117.135(a)(1); 21 CFR 117.136(a) … |
| 20 | F-003 | false partial (partial) | - 21 CFR 117.135(a)(1) requires preventive controls to minimize or prevent … | 21 CFR 117.206(a) | lex | **unverifiable** | blocked: claim names *hazard*, absent from 21 CFR 117.206(a), stated in 21 CFR 117.130(a); 21 CFR 117.135(a)(1); 21 CFR 117.136(a) |
| 21 | F-003 | false support (list item) | The CGMP requirements under Part 117 Subpart B include food safety plan. | 21 CFR 117.190(a) | sem+lex | **unverifiable** | not established: 0 operators agree, 60% of terms / 75% of core terms in 21 CFR 117.190(a) |
| 22 | F-007 | false partial (partial) | The requirements for monitoring include conducting activities that include … | 21 CFR 117.155(a) | sem | **unverifiable** | blocked: claim names *monitor, reanalysi, valid*, absent from 21 CFR 117.155(a), stated in 21 CFR 117.145; 21 CFR 117.160(a); 21 CFR 117.170(a) |
| 23 | F-007 | false support (paraphrase) | Under Part 117, a food safety plan must contain requirements for hazard ana… | 21 CFR 117.160(a) | lex | **unverifiable** | blocked: claim names *analysi, plan*, absent from 21 CFR 117.160(a), stated in 21 CFR 117.126(a); 21 CFR 117.130(a); 21 CFR 117.139 … |
| 24 | F-009 | false partial (partial) | Under Part 117, a process preventive control is a measure implemented to pr… | 21 CFR 117.160(a) | sem+lex | **unverifiable** | blocked: claim names *contamin, growth, measur, microbial, proces*, absent from 21 CFR 117.160(a), stated in 21 CFR 117.10; 21 CFR 117.135(a)(1); 21 CFR 117.136(a) … |
| 25 | F-009 | false partial (partial) | Under Part 117, a process preventive control is a measure implemented to pr… | 21 CFR 117.140(a) | sem+lex | **unverifiable** | blocked: claim names *hazard, measur, proces*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10; 21 CFR 117.130(a); 21 CFR 117.135(a)(1) … |
| 26 | F-009 | false partial (partial) | A sanitation preventive control is a measure to prevent hazards related to … | 21 CFR 117.140(a) | sem+lex | **unverifiable** | blocked: claim names *hazard, measur*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10; 21 CFR 117.130(a); 21 CFR 117.135(a)(1) … |
| 27 | F-009 | false partial (partial) | An allergen preventive control is a measure to prevent allergens, such as i… | 21 CFR 117.140(a) | sem+lex | **unverifiable** | blocked: claim names *allergen, measur*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10 |
| 28 | F-009 | false partial (partial) | The modified requirements apply to a qualified facility solely engaged in t… | 21 CFR 117.206(a) | sem+lex | **unverifiable** | blocked: claim names *qualif*, absent from 21 CFR 117.206(a), stated in 21 CFR 117.180(a); 21 CFR 117.201(a); 21 CFR 117.251(a) |
| 29 | F-012 | false support (adjacent window) | Part 117 also requires validation that the preventive controls are effectiv… | 21 CFR 117.165(a) | lex | **unverifiable** | blocked: claim names *effectively, hazard, minimiz, significantly, valid*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10; 21 CFR 117.130(a); 21 CFR 117.135(a)(1) … |
| 30 | F-022 | false partial (partial) | The Part 117 supply-chain program differs from the FSVP requirements for im… | 21 CFR 117.140(a) | sem+lex | **unverifiable** | blocked: claim names *measur, qual*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10; 21 CFR 117.110(a) |
| 31 | F-022 | false partial (partial) | The Part 117 supply-chain program differs from the FSVP requirements for im… | 21 CFR 117.160(a) | sem+lex | **unverifiable** | blocked: claim names *analysi, measur, qual*, absent from 21 CFR 117.160(a), stated in 21 CFR 117.10; 21 CFR 117.110(a); 21 CFR 117.130(a) |
| 32 | F-022 | false partial (partial) | The Part 117 supply-chain program differs from the FSVP requirements for im… | 21 CFR 117.155(a) | sem+lex | **unverifiable** | blocked: claim names *measur, process, qual*, absent from 21 CFR 117.155(a), stated in 21 CFR 117.10; 21 CFR 117.110(a); 21 CFR 117.135(a)(1) … |
| 33 | F-022 | false partial (partial) | The program requires the establishment to ensure the lowest possible defect… | 21 CFR 117.155(a) | sem | **unverifiable** | blocked: claim names *component, defect, level, lowest, manag, plan*, absent from 21 CFR 117.155(a), stated in 21 CFR 117.10; 21 CFR 117.110(a); 21 CFR 117.126(a) … |
| 34 | F-022 | false partial (partial) | Each provision in Part 117 requires specific sub-requirements to ensure the… | 21 CFR 117.140(a) | sem+lex | **unverifiable** | blocked: claim names *hazard, identify, measur*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10; 21 CFR 117.130(a); 21 CFR 117.135(a)(1) … |
| 35 | F-022 | false partial (partial) | Each provision in Part 117 requires specific sub-requirements to ensure the… | 21 CFR 117.140(a) | sem+lex | **unverifiable** | blocked: claim names *measur*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10 |
| 36 | F-022 | false partial (partial) | The program requires the establishment to ensure the lowest possible defect… | 21 CFR 117.140(a) | lex | **unverifiable** | blocked: claim names *defect, level, lowest, plan*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.110(a); 21 CFR 117.126(a); 21 CFR 117.139 … |
| 37 | F-022 | false partial (partial) | Each provision in Part 117 requires specific sub-requirements to ensure the… | 21 CFR 117.140(a) | lex | **unverifiable** | blocked: claim names *measur*, absent from 21 CFR 117.140(a), stated in 21 CFR 117.10 |
| 38 | M-034 | false partial (partial) | - A Design History File is a record of the design of the device, including … | 21 CFR 820.45 | sem | **unverifiable** | blocked: claim names *design*, absent from 21 CFR 820.45, stated in 21 CFR 820.1(a); 21 CFR 820.10; 21 CFR 820.3 |

**More conservative than Phase 2C's "correct" verdict** (no credit where 2C would have given a partial):
- #3 B-005: the passage states the permission for "a specific recipient" with a proviso. The claim drops both, and 0 operators can be compared.
- #4 C-002 and #10 D-008: blocked by the missing object; the common half is not credited separately.

All three are now unverifiable, the safe direction under §23.

## E. Legitimate-paraphrase audit (remain credited)

All 71 safe supports and 11 of 12 safe partials keep their verdict and source under every arm. Representative cases, semantic arm:

| Kind | Row | Claim | Source | Gate |
|---|---|---|---|---|
| files ↔ records | B-005 | "Adverse reaction **files** must be maintained for each unit of blood…" | 606.170(a) (records) | established: strength and polarity agree, 83% of core terms; "files" is in no other source |
| maintained | B-005 | "Records must be maintained concurrently with each significant step…" | 606.160(a)(1) | established, 100% of core terms |
| paraphrase with numbers | B-002 | "If a person elects to submit adverse experience reports to the applicant…" | 600.80(c)(1)(iii) | strength, polarity, quantity:day agree, 100% of core terms |
| paraphrase with actor | B-003 | "A biologics license issued to a manufacturer covering all locations…" | 601.22 | strength, polarity, actor agree, 100% of core terms |
| list item | F-007 | "…reanalysis include conducting a reanalysis of the food safety plan as a whole at least once every 3 years" | 117.170(a) | 94% verbatim item |
| descriptive | G-004 | "The headings and subheadings … use uppercase letters…" | 201.66(d)(1) | descriptive standard, recorded in the gate trace |
| adjacent window | F-004 | "The grounds must be maintained in a condition that will protect against contamination…" | 117.20(a) | window through the gate |
| partial (condition) | E-005 | "…open systems, including ensuring the authenticity" | 11.30 | established; omits "as appropriate" → partial |
| partial, operator-silent passage | F-003 / F-007 | "117.140(a) requires preventive control management components" | 117.140(a) "are subject to the following … components as appropriate" | established_terms_only; omits "as appropriate" → partial |
| anaphora | C-004 | "These ingredients are deemed to be adulterated under section 601(a)…" | 700.11(a) | supported; citation correct under both aligners |

Synthetic controls (tests):
- kept ↔ maintained, safely ↔ "in a safe manner", and files ↔ records are supported or not distinguishing;
- generic words (FDA, regulation, requires) never distinguish.

**The one lost safe decision (documented in Phase 2C):** drop15, "21 CFR 117.160(a) requires validation of preventive controls", against "You must validate that the preventive controls…". "Validation" and "validate" stem differently, so 2 of 3 core terms match (67% < 70%). It is now unverifiable, which is conservative.

## F. Regression results

Default suite: **1824 passed, 1 skipped, 0 failed.** That is the Phase 2A/2B baseline of 1584, plus 240 new tests.

| Suite | Result |
|---|---|
| test_accuracy_content_gate (new: 36 functions; 240 cases including all 203 labelled aligner instances) | 240 passed |
| test_accuracy_claim_extraction | 35 passed |
| test_accuracy_citation_grounding | 19 passed |
| test_accuracy_guidance_logic (Priority 2) | 29 passed |
| test_accuracy_relevance (incl. refusals, D-001/D-003/D-008 off-topic) | 67 passed |
| test_accuracy_evaluation (incl. incorrect abstention detected) | 31 passed |
| test_accuracy_claims | 41 passed |
| test_accuracy_observer | 6 passed |
| test_evidence_traceability | 19 passed |
| test_accuracy_ui | 5 passed |

**Opt-in integration suite** (`-m integration`, needs PostgreSQL): **41 passed, 1 failed.**
- The failure is `tests/integration/test_rag_slow.py::test_rag_end_to_end_one_question`: the production context bundle is 4,828 characters against the test's 3,600 limit.
- It is **pre-existing and unrelated to Phase 2D**. It fails identically (4,828) with the reconstructed pre-2D evaluator, and `regulus.rag` does not import `regulus.accuracy`.
- The cause is in production context assembly, which this phase must not change. It needs a separate decision.

**Required confirmations:**
- **G-004**: correct/100, both aligners.
- **M-020**: correct, with all 12 enumerated statements supported, on the frozen row and on its exact live snapshot (`fa2451337503d884`). Its composite score is 60, not 100, and was 60 before this phase. Since Phase 2A the citation dimension fails on the three shifted paragraphs (human L=0). Those mismatches are still detected (`test_M020_the_three_shifted_items_and_only_those_are_paragraph_mismatches`).
- **C-004**: citation correct under both aligners. The lexical-arm row citation dimension improved from fail to pass.
- **D-001 and D-008**: off_topic, score 0, both aligners.
- **Priority-2 guidance:** tests unchanged and passing. No guidance row changed at answer level.
- **Refusals:** the temporal-refusal tests pass and incorrect abstention is still detected. `abstention_incorrect` stays 2 → 2 on the 60 rows.
- **Determinism:** two runs of the 60 rows produce byte-identical results. No LLM is involved. Embeddings select candidates only.

## G. Production safety

Live ON/OFF regression, `artifacts/accuracy/regression_2026-10-08T093941Z.json`, 2 questions:

| Check | Result |
|---|---|
| Answer bytes, ON vs OFF | identical (live arm PASS; payload arm PASS: only difference is the assessment) |
| Answers vs Phase 2A run (`regression_2026-10-08T082132Z.json`) | identical. Every non-timing field matches: answer, citations, payload, evidence, prompts, replay verdicts. |
| Citations | identical |
| Evidence snapshot / fingerprints | exact; `fa2451337503d884…`, `678b0d62c082e609…`; stored = recomputed = live = replay |
| Prompt | verified, SHA-256 unchanged vs Phase 2A |
| Model calls | one per answer (`model_called`), unchanged |
| Retrieval, generation configuration | unchanged; no file under rag, retrieval, planning, traceability, config or scripts modified since Phase 2D began |
| Evaluator cost | 278.9 ms mean (max 410.7) vs 262.0 in 2A, against ≈16.4 s per answer |

**Files modified since Phase 2D began:**
- the 4 evaluator modules;
- the new test and fixture;
- the regression artifact;
- `artifacts/dashboard/registry.json`. This was written by the running `serve_ui` dashboard scan (`last_scan` 09:32Z), not by this phase.

`serve_ui` was stopped for the timed run and restarted afterwards with the same command.

## Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | 38 false decisions prevented | **Met.** 38/38; E-005 item now the correct partial |
| 2 | No systematic false-support increase elsewhere | **Met.** 0 new credited decisions over all 718 recorded decisions, both aligners |
| 3 | Legitimate paraphrases remain supported | **Met.** 71/71 safe supports; synonym controls pass |
| 4 | 83 safe preserved except the documented case | **Met.** 82/83; the change is drop15, documented in Phase 2C |
| 5 | No N=0 row scored high | **Met.** 0 before, 0 after |
| 6 | No wrong-topic answer scored high | **Met.** 0 rows with relevance ≠ pass above 50; D-001 and D-008 off-topic |
| 7 | Priority-2 guidance intact | **Met.** 29/29; no guidance row changed |
| 8 | Phase 2A citation grounding intact | **Met.** 19/19; agreement with L 28/31 → 29/32, 0 false fails |
| 9 | All existing tests pass | **Met for every suite this phase can affect** (1824/1824 default; 41/42 integration). The one failure predates Phase 2D, fails identically without it, and is in production context assembly, which this phase may not change. |
| 10 | Production answer bytes unchanged | **Met** |
| 11 | Evidence fingerprints unchanged | **Met** |
| 12 | No retrieval/generation/prompt/capture changes | **Met** |
| 13 | No 300-question run | **Met** |
| 14 | Deterministic, no LLM judge | **Met** |

## Remaining limitations

- **No grammatical roles are parsed.**
  - Subject and object are tested together by the contrastive core-term test.
  - The action's modality and polarity are tested by the Priority-2 operators. Its verb is tested through the core terms, with generic verbs exempt.
  - `core_subject_match`, `core_object_match` and `core_action_match` report exactly that.
- **The contrastive guard needs a contrasting source.** A substituted object that appears in no other captured source is not caught. Only the overlap thresholds stand behind it.
- **Gating only the selected candidate** means a claim that a lower-ranked candidate states correctly is left unverifiable. D-007 "operations" is true per 211.130, for example. The cost is false negatives, never false credit.
- **Validation scope.** Every figure on the 60 rows is legacy-reconstructed evidence. Exact-evidence validation covers only the two live questions. O remains NOT MEASURED.

## H. Final decision

**PASS**

Criterion 9 is met on the reading that no test is broken by this phase. If it is read as "every test in the repository, including opt-in integration tests that already failed", the decision would be FAIL because of the pre-existing `test_rag_end_to_end_one_question`, which this phase is not permitted to fix.

## Artifacts

- `support_decisions_replay.json`: the 203 labelled aligner instances, before and after.
- `answer_level_60.csv`: per-row verdict and score, before and after, both aligners.
- `scripts/`:
  - `forensic_all.py`, `replay.py`, `drift.py`, `answers60.py`, `emulate.py`;
  - the pre-2D reconstruction: `pre2d_extract.py`, `pre2d_reverse.py`, `use_pre2d.py`.
- Tests: `tests/test_accuracy_content_gate.py`, `tests/fixtures/accuracy_content_gate_rows.json` (26 frozen rows, 203 labelled instances).
