# Measurement Audit Phase 2E: legitimate paraphrase / false-negative validation

Investigation only. No production code, test, prompt, label or benchmark changed. Nothing under `src/`, `scripts/`, `tests/` or `web/` has been modified since this phase began. Candidate refinements were simulated on **offline copies** of `regulus.accuracy` (`work/variants/`), loaded into a separate process. No 300-question run.

**Data:**
- the frozen 60 rows, all LEGACY_RECONSTRUCTED evidence;
- both aligners;
- the Phase 2C hand-labelled set;
- every support decision the Phase 2D evaluator makes: 718 (359 unique claims × 2 aligners).

**Review standard.** §4 of the request: subject/object, actor, action, modality, polarity, applicability, conditions, exceptions, numbers, dates, domain, relationship. Word overlap was used only to *triage* cases for review, never to classify. Every classification was made by reading the claim against the captured source text. When the stating sentence was not in the captured text, the verdict is an evidence limitation, not a false negative.

## A. Decision

**SAFE TO LOCK**, for the Phase 2D content-support gate.

**Phase 2D's own added conservatism is small and partial-level:**
- It withholds 3 decisions that deserve credit. All three deserve *partial* credit, not full support, and none is on an N=2 row.
- It prevents 38 false credits. The ratio is 38 : 3.
- The upper-bound answer simulation shows none of the three changes an answer verdict.

**Most of the remaining false negatives predate Phase 2D.** 33 of 36 come from rules and limits that were already there:
- operator agreement on claims with no modal;
- unstemmed term overlap;
- single-passage matching;
- claim extraction.

These verdicts are conservative (unverifiable, never false credit). They touch no N=2 row and create no false high score. Crediting all of them would change at most 4 of 60 answer verdicts.

**The only narrow refinement that tested clean does not justify holding the lock.** That refinement is stemmed overlap (§G).
- It fixes 3 confirmed false negatives with zero regressions on every control.
- It also credits 2 ambiguous decisions, and changes no answer verdict.

**A separate defect matters before large-scale benchmarking.** It is in the Priority-2 operator logic, outside the gate (§D.3):
- a modality-scope error makes **2 false CONTRADICTIONS**, which turn H-003 (human N=1) into "incorrect, 0";
- a negation-scope error removes the stating candidate in a third case.

This is a harmful error, not conservatism, and it should be handled as its own task.


## B. False-negative audit (36 confirmed false negatives + 2 false contradictions)

Evidence is quoted from the captured text. "2D-caused" means the decision was credited before Phase 2D. Rows 1–3 are the only ones Phase 2D caused. Rows 37–38 are false contradictions (§D.3). The 30 ambiguous cases are in `work/p2e/classified.json`.

| # | Row (N) | Claim (abridged) | Evidence | Phase 2D verdict | Correct verdict | Root cause | 2D-caused |
|---|---|---|---|---|---|---|---|
| 1 | B-005 (1) | The use of plateletpheresis and leukapheresis procedures may vary with additional standard… | B-005: 2C correct verdict partial (drops 'for a specific recipient' and the proviso); Phase 2D returns unverifiable | unverifiable | **partial** | content gate | yes |
| 2 | D-008 (0) | - Calibration procedures and records must be maintained, as required by 21 CFR 111.30. | D-008: 2C correct verdict partial (211.68(a) states calibration records are maintained; 'procedures' is not); Phase 2D returns unverifiable; semantic arm only - the lexical arm credits 213.68(a) (Phase 2C para21 SAFE) | paraphrase (lex); unverifiable (sem) | **partial** | content gate | yes |
| 3 | F-003 (1) | - 21 CFR 117.160(a) requires validation of preventive controls. | 117.160(a) 'You must validate that the preventive controls ... are adequate ... as appropriate'; validation/validate stem differently (valid vs validat): 67% core < 70%. Documented in Phase 2C/2D | unverifiable | **partial** | terminology normalization | yes |
| 4 | B-005 (1) | Distribution and receipt procedures include a system to determine the recall of units [1]. | 606.165(a) states it ('shall include a system by which distribution or receipt of each unit can be readily determined to facilitate its recall'); modal-less claim gets 0 agreeing operators; descriptive path needs a 6-word run (has 4) | unverifiable | **supported** | operator logic | no |
| 5 | B-005 (1) | Reporting of deviations by licensed manufacturers, unlicensed registered blood establishme… | 606.171(a) heading and its 2nd sentence state who must report; the candidate chosen is the question sentence 'Who must report under this section?' (3 operators agree, 100% core) so term overlap is 50% - offline variant V1 (stemmed overlap) credits it: the unstemmed overlap missed deviations/deviation | unverifiable | **supported** | terminology normalization | no |
| 6 | C-002 (1) | The requirement applies to the label of a cosmetic in package form [1]. | 'The requirement' = the net-quantity declaration of the previous sentence; 701.13(a) 'The label of a cosmetic in package form shall bear a declaration of net quantity'; antecedent not carried, claim has no modal | unverifiable | **supported** | claim extraction | no |
| 7 | C-002 (1) | The declaration of net quantity shall be in terms of weight, measure, numerical count, or … | 701.13(a) states both halves in different sentences ('expressed in terms of weight, measure, numerical count, or a combination' ... 'Whenever the Commissioner determines ... he shall ... designate the appropriate term') | unverifiable | **supported** | other: claim spans several sentences of one source | no |
| 8 | D-007 (0) | The procedures shall include written procedures for charge-in of components, calculation o… | 'The procedures' = 211.100(a) production/process control procedures, which 'shall include all requirements in this subpart'; each listed item is a separate Subpart F section (211.101, .103, .105, .110, .111, .113), all captured. No single passage states the conjunction | unverifiable | **supported** | other: multi-source conjunction | no |
| 9 | D-009 (0) | Written procedures for production and process control must be established and followed, in… | 211.100(a) states written production/process control procedures, 'including any changes', designed to assure identity/strength/quality/purity; 'these characteristics' is a mid-sentence anaphor (antecedent in the previous sentence) and 'characteristic' is flagged as distinguishing; raw overlap 58% also below 70% | unverifiable | **supported** | distinguishing-term guard | no |
| 10 | D-009 (0) | Written procedures shall also include the calculation of yield, which shall be performed b… | 211.103 states yield calculation by one person independently verified by a second (or automated equipment under 211.68 verified by one person); 'written procedures shall include' needs 211.100(a) 'shall include all requirements in this subpart' | unverifiable | **supported** | other: multi-source conjunction | no |
| 11 | D-009 (0) | Written procedures shall also include time limitations on production to ensure the quality… | 211.111 time limits to assure quality + 211.100(a) 'procedures shall include all requirements in this subpart' | unverifiable | **supported** | other: multi-source conjunction | no |
| 12 | D-009 (0) | Written procedures shall include control of microbiological contamination to prevent objec… | 211.113(a) (ranked FIRST by both aligners) 'Appropriate written procedures, designed to prevent objectionable microorganisms in drug products not required to be sterile, shall be established and followed'; negation-scope logic reads the evidence's 'not required to be sterile' as negating the rule (claim affirm, evidence negate) -> polarity conflict removes the stating candidate | unverifiable | **supported** | operator logic | no |
| 13 | D-009 (0) | If appropriate, written procedures shall include the charge-in of components, ensuring tha… | semantic arm only: selects 211.100(a) (guard correctly blocks it); the lexical arm credits 211.101, heading 'Charge-in of components' (Phase 2C para28 SAFE) | paraphrase (lex); unverifiable (sem) | **supported** | alignment | no |
| 14 | D-010 (0) | - Testing and approval or rejection of components, containers, and closures (eCFR 21 CFR 2… | after the bold label the sentence is VERBATIM 213.84(c); the label ('Testing and approval or rejection of components, containers, and closures (eCFR 21 CFR 213.84(c))') is kept in the claim and dilutes verbatim coverage and overlap to 57%; offline variant V1 (stemmed overlap) credits it | unverifiable | **supported** | terminology normalization + claim extraction | no |
| 15 | D-015 (0) | The requirements to implement a production and process control system are outlined in 21 C… | pointer sentence ('requirements ... are outlined in 21 CFR 111.55'); 111.55 does require implementing a production and process control system; modal-less claim, 0 operators | unverifiable | **supported** | claim extraction | no |
| 16 | D-015 (0) | The requirements to review and investigate a product complaint are outlined in 21 CFR 111.… | pointer sentence; 111.560(a) 'A qualified person must: (1) review ... (2) investigate' - no candidate cleared the aligner floor | unverifiable (no candidate) | **supported** | claim extraction | no |
| 17 | D-019 (1) | Written procedures shall also include the calculation of yield, equipment identification, … | written procedures (211.100(a): 'shall include all requirements in this subpart') + 211.103 yield, 211.105 equipment identification, 211.110 sampling/testing; no single passage | unverifiable | **supported** | other: multi-source conjunction | no |
| 18 | D-019 (1) | General requirements include standards. | item of 'General requirements include establishing specifications, standards, sampling plans, test procedures, or other laboratory control mechanisms'; 211.160 (heading 'General requirements') (a) covers the establishment of standards; modal-less 1-term item: 0 operators, item path needs >= 2 terms | unverifiable | **supported** | operator logic | no |
| 19 | D-019 (1) | General requirements include sampling plans. | as #18 (sampling plans) | unverifiable | **supported** | operator logic | no |
| 20 | D-019 (1) | General requirements include test procedures. | as #18 (test procedures); semantic arm also selects 211.100(a) and the guard flags 'test' | unverifiable | **supported** | operator logic | no |
| 21 | D-019 (1) | General requirements include other laboratory control mechanisms. | as #18 (other laboratory control mechanisms) | unverifiable | **supported** | operator logic | no |
| 22 | D-019 (1) | General requirements requirements shall be documented and followed. | 211.160(a) first sentence: 'The requirements in this subpart shall be followed and shall be documented at the time of performance'; the gate examined the second sentence of the same source (gate established, raw overlap 67% < 70%); even on that sentence the raw overlap is 67%: 'general' is only in the heading 'General requirements.' | unverifiable | **supported** | alignment + heading excluded from overlap | no |
| 23 | D-019 (1) | Time limitations on production shall be established to ensure quality, and microbiological… | 211.111 (time limits ... to assure quality) + 211.113(a) (procedures to prevent objectionable microorganisms); each half stated by one source | unverifiable | **supported** | other: multi-source conjunction | no |
| 24 | D-019 (1) | General requirements include establishing specifications. | as #18: 211.160 general requirements cover establishing specifications; modal-less item | unverifiable | **supported** | operator logic | no |
| 25 | E-010 (1) | 21 CFR 11.100(a) and 21 CFR 11.10 ensure the authenticity, integrity, and confidentiality … | 11.10 states the closed-system controls ensure authenticity, integrity and, WHEN APPROPRIATE, confidentiality, and that the signer cannot readily repudiate; correct verdict partial (drops 'when appropriate'); modal-less claim: 0 operators | unverifiable | **partial** | operator logic | no |
| 26 | F-003 (1) | - 21 CFR 117.136(a) states that preventive controls are not required if a hazard is identi… | 117.136(a): 'you are not required to implement a preventive control when you identify a hazard ... and any of the following circumstances apply' - same proposition; only polarity agrees (1 operator) | unverifiable | **supported** | operator logic | no |
| 27 | F-003 (1) | - 21 CFR 117.139 mandates a recall plan for hazards requiring preventive controls. | 117.139: 'For food with a hazard requiring a preventive control: (a) You must establish a written recall plan'; strength+polarity agree, 100% core terms, but the unstemmed overlap misses hazards/hazard and controls/control (framed 67%, raw 57%) | unverifiable | **supported** | terminology normalization | no |
| 28 | F-003 (1) | - 21 CFR 117.145 mandates monitoring activities. | 117.145(b) 'You must monitor the preventive controls ...' is in the selected source; the guard blocks 'activ' ('monitoring activities') even on that sentence - 'activities' is a generic noun treated as distinguishing | unverifiable | **supported** | distinguishing-term guard | no |
| 29 | F-003 (1) | - 21 CFR 117.165(a) mandates verification of implementation and effectiveness. | 117.165(a) (captured, and named in the claim) 'You must verify that the preventive controls are consistently implemented and are effectively ... minimizing'; neither aligner ranked it first (117.145 selected), the claim's own named provision is not used | unverifiable | **supported** | alignment | no |
| 30 | F-003 (1) | - 21 CFR 117.254(a) requires approval for withdrawal. | 117.254(a): Division Director 'must approve an order to withdraw the exemption'; the lexical alignment floor is unstemmed (approval/approve, withdrawal/withdraw) so no candidate reaches the judge | unverifiable (no candidate) | **supported** | terminology normalization | no |
| 31 | F-004 (1) | The requirements include ensuring the grounds are kept in a condition that protects agains… | 117.20(a): 'The grounds ... must be kept in a condition that will protect against the contamination of food' - modal-less list-lead claim, 0 operators | unverifiable | **supported** | operator logic | no |
| 32 | F-004 (1) | The requirements include methods for adequate maintenance. | 117.20(a): 'The methods for adequate maintenance of grounds must include:' - modal-less claim, 0 operators, 100% terms | unverifiable | **supported** | operator logic | no |
| 33 | F-007 (1) | The requirements for plant and grounds include maintaining the grounds in a condition that… | 117.20(a): grounds 'must be KEPT in a condition that will protect against the contamination of food'; claim says 'maintaining the grounds'; list-item path counts 'maintain' as a missing term (80% < 85%) because it does not apply the generic-word exemption; modal-less claim gets 0 operators on the sentence path | unverifiable | **supported** | terminology normalization | no |
| 34 | G-010 (1) | [2] A manufacturer, repacker, relabeler, or private label distributor may voluntarily rese… | the pipeline's truncation notice '(Incomplete: generation stopped at the token limit ... finished ...' is merged into the claim; the proposition before it is verbatim 207.33 ('may voluntarily reserve a proposed NDC ... by submitting the following information'); the guard flags 'finish' from the notice | unverifiable | **supported** | claim extraction | no |
| 35 | G-010 (1) | [1] The National Drug Code (NDC) is a numeric code that identifies a drug and its products… | 207.33(a) 2nd sentence 'The NDC for a drug is a numeric code' + unique NDC 'to identify its labeler, product, and package size'; modal-less descriptive claim gets 0 operators even on that sentence (correct verdict partial: 'identifies a drug and its products' is loose) | unverifiable | **partial** | operator logic | no |
| 36 | H-003 (1) | Prior notice of imported food must be submitted to FDA, and it must be confirmed by FDA fo… | 1.279(a): 'Except as provided in paragraph (c) ..., you must submit the prior notice to FDA and the prior notice submission must be confirmed by FDA for review' - correct verdict partial (drops the exception); strength+polarity agree but unstemmed overlap misses submitted/submit and heading terms (57%) | unverifiable | **partial** | terminology normalization | no |
| 37 | H-003 (1) | If you are an authorized user of CBP’s ABI/ACE/ITDS, you may submit prior notice through e… | 'may submit ... through either ABI/ACE/ITDS or FDA PNSI' is a choice of CHANNEL, not permission to skip the duty; compared with 1.279(a) 'you must submit' as permissive-vs-mandatory. The channel rule is not in the captured text, so the correct verdict is unverifiable, not contradicted | contradicted | **unverifiable** | operator logic | no |
| 38 | H-003 (1) | If you are not an authorized user, you may submit prior notice through FDA PNSI. | as #37 | contradicted | **unverifiable** | operator logic | no |

## C. Quantification (diagnostic only; not Regulus accuracy)

| | Count |
|---|--:|
| Support decisions recorded (both aligners) | 718 (359 unique claims) |
| Unique claims credited (supported or partial) on at least one arm | 142 |
| Unique claims with a conservative verdict (unverifiable or partial), **all hand-reviewed** | 180 |
| … flagged by triage before review (overlap ≥ 60%, single-term or morphological guard block, gate-established without credit, aligner disagreement, 2D-changed) | 133 |
| Contradicted claims, also reviewed | 4 |
| No-evidence claims screened (≥ 60% of core terms in some captured passage → reviewed) | 44 screened, 6 reviewed |
| **Total claims classified** | **190** |
| Correct unverifiable | 113 (17 of them evidence limitations: the stating paragraph was not captured) |
| True partial (partial returned and correct) | 9 |
| Ambiguous (not counted as failure) | 30 |
| **Confirmed false negatives** | **36** |
| … caused by Phase 2D | **3** (drop15, B-005 desc00, D-008 para20). All three should be *partial*. |
| … inherited (unchanged by Phase 2D) | 33 |
| False contradictions (Priority-2 operator logic, inherited) | 2 (H-003) |

| Rate | Value |
|---|--:|
| False negatives among the 190 reviewed | 36/190 = 18.9% |
| False negatives among reviewed, excluding ambiguous | 36/160 = 22.5% |
| Claims that deserve credit but are withheld (FN ÷ (credited + FN)) | 36/176 = **20.5%** |
| … of which caused by Phase 2D | 3/176 = **1.7%** |
| Phase 2D trade-off: false credits prevented : legitimate credits lost | **38 : 3** |

**Rows affected (false negatives, by human N):**

| N | Claims | Rows |
|---|--:|---|
| 2 | 0 | none |
| 1 | 26 | B-005, C-002, D-019, E-010, F-003, F-004, F-007, G-010, H-003 (9) |
| 0 | 10 | D-007, D-008, D-009, D-010, D-015 (5) |

**Answer-level upper bound.** Every confirmed false negative was credited at its correct verdict and the 60 rows re-aggregated (semantic aligner of record):

| Metric | Value |
|---|--:|
| Answer verdicts changed | 4 |
| Scores changed | 4 |
| N=2 rows changed | 0 |
| N=0 rows newly scored > 50 | 0 |
| Rows with relevance ≠ pass newly scored > 50 | 0 |

The 4 changes:
- **F-004** (N=1): partial 0 → correct 60.
- **F-003** (N=1): unverifiable → partial 40.
- **E-010** (N=1): unverifiable → partial 20.
- **D-007** (N=0): off_topic 0 → partial 20. This is a simulation artefact: a credited claim keeps the relevance the evaluator gave it while it was unverifiable, so it is not re-judged.

The 3 false negatives Phase 2D caused change no answer verdict and no score.

**Aligners.**
- Credit status differs between the aligners on 2 of 359 claims: D-008 and D-009. Both are arm-specific false negatives in which the semantic aligner ranks a wrong candidate first. The gate correctly blocks that candidate, while the lexical arm selects the stating source.
- One claim has the same candidate under both aligners but a different verdict: G-004, paraphrase vs adjacent window. Both are credited.
- No case was found in which the aligner decided correctness. Where aligners differ, the difference is which candidate reaches the gate.

## D. Root causes (36 confirmed false negatives)

| Root cause | FN | Phase-2D-caused | Mechanism | Claims (table B #) |
|---|--:|--:|---|---|
| **Operator logic** | 12 | 0 | A claim with no modal ("X include Y", "states that", "are outlined in") gets 0 agreeing operators, and the paraphrase standard needs 2. The descriptive path needs a 6-word verbatim run. One case is a negation-scope error (#12). | 4, 12, 18–21, 24–26, 31, 32, 35 |
| **Terminology normalization** | 7 | 1 | The paraphrase overlap and the lexical alignment floor compare **unstemmed** words: hazards/hazard, submitted/submit, deviations/deviation, approval/approve. The stemmer splits validation/validate (#3). The list-item path does not exempt generic verbs: kept/maintaining (#33). | 3, 5, 14, 27, 30, 33, 36 |
| **Other: single-passage architecture** | 6 | 0 | The claim joins several provisions ("procedures shall include A, B and C", each in a different section) or several sentences of one source. No single passage or adjacent window states it. | 7, 8, 10, 11, 17, 23 |
| **Claim extraction** | 4 | 0 | Antecedent not carried ("The requirement applies…"); pointer sentences ("…are outlined in 111.55"); the pipeline's truncation notice merged into a claim (#34). | 6, 15, 16, 34 |
| **Alignment** | 3 | 0 | Wrong candidate ranked first: the claim's own named provision is not used (#29); arm-specific (#13); the right source but the wrong sentence, with "general" only in the heading (#22). | 13, 22, 29 |
| **Distinguishing-term guard** | 2 | 0 | Mid-sentence anaphor "these **characteristics**" is not exempted (only a leading anaphor is) (#9). A generic noun, "monitoring **activities**", is treated as distinguishing (#28). | 9, 28 |
| **Content gate** | 2 | 2 | A partial-worthy claim drops a condition **and** misses terms. The gate does not establish the common proposition, so no partial is given (B-005 desc00; D-008 para20, semantic arm). | 1, 2 |

### D.1 The distinguishing-term guard (§6)

- **Distinguishes correctly** in every Phase 2C false case. In the inherited set it also correctly blocks:
  - "qualified facility" for a rule that binds every operator;
  - "hazard analysis" as the list head for a preventive-controls item;
  - false list memberships.
- **Too strict in 2 cases:**
  - #9: a mid-sentence anaphor. Only leading anaphors are exempt.
  - #28: "activities", a generic noun.
- **Latent misclassifications that did not change a verdict:**
  - **prohibit** is flagged as an object term in 10 C-004 claims. It is an operator word. Those claims are unverifiable anyway, because the captured (a) paragraphs do not state the prohibition.
  - **question** is flagged from "in question".
  - **finish** is flagged from the truncation notice.
- **Morphology:** stems absorb singular/plural. validation/validate is the one split seen.
- **Headings:** headings count as the candidate's *own source* (correct for #13, 211.101 "Charge-in of components"), but not toward overlap (#22).
- **Exact corpus occurrences:** the guard is contrastive by design. A missing term that appears in no other captured source is never treated as distinguishing, so files ↔ records stays supported (§E).

### D.2 What Phase 2D itself added

| Decision | Correct | Phase 2D | Why |
|---|---|---|---|
| drop15 F-003 "117.160(a) requires validation of preventive controls" | partial | unverifiable | validation/validate: 2 of 3 core terms (67% < 70%). Documented in 2C. |
| desc00 B-005 "plateletpheresis … may vary with additional standards" | partial (2C) | unverifiable | drops the recipient scope and the proviso; 0 operators |
| para20 D-008 "Calibration procedures and records must be maintained" (semantic) | partial (2C) | unverifiable | blocked on "procedures"; the records half is stated by 211.68(a) |

C-002 para11 is ambiguous, and Phase 2C itself rated it "partial / unverifiable here".

**Correction to the Phase 2D report.** It cited "charge-in of components" credited to 211.101 as an example of a wrong new support, saying the passage "never says charge-in". That is wrong. 211.101's heading is "Charge-in of components", and Phase 2C labelled the same pairing SAFE (para28). The decision Phase 2D made there is unaffected: the gate still judges only the selected candidate. But the example was mistaken, and the semantic arm's unverifiable verdict on that claim is a real (alignment) false negative (#13).

### D.3 Operator-logic errors in the harmful direction (outside the gate)

1. **Modality scope: H-003, 2 false contradictions.**
   - The claim "If you are an authorized user …, you **may** submit prior notice through either ABI/ACE/ITDS or FDA PNSI" offers a choice of **channel**.
   - The operator compares it with 1.279(a) "you **must** submit the prior notice" as permissive vs mandatory, and records a conflict.
   - The correct verdict is unverifiable: the channel rule is not in the captured text.
   - Effect: H-003 (human N=1) is scored **incorrect, 0**. Its substantive dimension fails only because of these two contradictions.
2. **Negation scope: #12, D-009.**
   - 211.113(a), the passage ranked *first* by both aligners, says "written procedures, designed to prevent objectionable microorganisms in drug products **not required to be sterile**, shall be established".
   - The polarity operator reads that embedded "not required" as negating the rule in the evidence, but not in the claim, which contains the same phrase.
   - The resulting conflict removes the stating candidate. Here the result is unverifiable; in a row where every candidate shares the phrase, it would be a false contradiction.

Both predate Phase 2D (contradiction runs before the gate and was not changed). Both are Priority-2 logic.

## E. Legitimate paraphrases preserved (real rows, semantic arm)

| Variation | Row | Claim | Evidence | Verdict |
|---|---|---|---|---|
| files ↔ records | B-005 | "Adverse reaction **files** must be maintained for each unit of blood or blood product" | 606.170(a) "**Records** shall be maintained of any reports of complaints of adverse reactions …" | paraphrase support. "files" is in no other source, so nothing contrasts it. |
| safely ↔ safe | B-005 | "Supplies and reagents … must be stored **safely** and orderly" | 606.65 "… shall be stored in a **safe**, sanitary and orderly manner" | paraphrase support |
| maintained ↔ kept | F-004 | "The grounds must be **maintained** in a condition that will protect against the contamination of food, and the methods …" | 117.20(a) "… must be **kept** in a condition …" | support (adjacent window) |
| must ↔ shall, record restated | B-005 | "Records must be maintained concurrently with each significant step …" | 606.160(a)(1) | paraphrase support, 100% of core terms |
| numbers + actor | B-002, B-003 | adverse-experience reports (quantity:day); biologics licence (actor) | 600.80(c)(1)(iii); 601.22 | paraphrase support, operators agree |
| anaphora | C-004 | "**These ingredients** are deemed to be adulterated under section 601(a) …" | 700.11(a) / 700.14(a) | supported under both aligners; citation correct |
| list item | F-007 | "… reanalysis include conducting a reanalysis of the food safety plan as a whole at least once every 3 years" | 117.170(a) | list-item support |
| descriptive | G-004 | "The headings and subheadings … use uppercase letters …" | 201.66(d)(1) | descriptive support |
| condition dropped → partial | E-005, F-003, F-007 | "… including integrity", "117.140(a) requires preventive control management components" | 11.30 / 117.140(a) "as appropriate" | partial |

All 71 Phase 2C safe supports and 11 of 12 safe partials are unchanged (§F).

**One inconsistency.** The kept ↔ maintained paraphrase that F-004 credits (window path) is **not** credited on F-007's list-item path (table B #33). The list-item containment test does not apply the generic-word exemption the gate uses.

## F. Regression safety (current Phase 2D state)

| Check | Result |
|---|---|
| 38 Phase 2C false decisions | all still prevented. Recorded decisions are identical to the Phase 2D audit: 0 of 203 labelled aligner instances differ. |
| 83 Phase 2C safe decisions | 82 preserved; drop15 is the documented exception |
| 718 support decisions | identical to Phase 2D, re-recorded deterministically |
| 60-row answer level (semantic) | identical to the Phase 2D `answer_level_60.csv`: 0 of 60 rows differ |
| B-003 / C-002 / C-004 / D-007 / E-005 / F-003 / F-007 / F-012 / D-004 / M-034 | partial 0 / partial 40 / partial 35 (citation pass) / off_topic / partial 0 / unverifiable / partial 0 / partial 0 / off_topic / unverifiable, as in Phase 2D |
| G-004 / M-020 | correct 100 / correct, 12 of 12 supported, score 60 (citation fails on the three shifted paragraphs, as since 2A) |
| D-001 / D-008 | off_topic 0 |
| Default test suite | **1824 passed, 1 skipped, 0 failed** (includes the 240 content-gate tests) |

**Offline refinement simulations** (`work/variants/`, copies only; checked against every control):

| Variant | FN fixed | Correct-unverifiable credited | 2C false reopened | Safe lost | Ambiguous credited | Tests | Answer level |
|---|--:|--:|--:|--:|--:|---|---|
| V1 stemmed overlap (gate's framed overlap and the paraphrase raw overlap measured on stems) | 3 claims (6 instances: #5, #14, #27) | 0 | 0 | 0 | 2 | 1824 passed | 0 verdict changes; D-009 (N=0) 40 → 0 (a newly credited ambiguous claim exposes a wrong `[1]` to the citation layer) |
| V2 other sentences of the selected source | 0 | 0 | 0 | 0 | 2 (+1 named-provision attribution) | not run | not useful |
| V3 list-item generic-word exemption | 1 claim (#33) | **1** (F-022 supply-chain list item credited to 117.145) | 0 | 0 | 0 | not run | **unsafe as written** |

## G. Recommendation

**Freeze Phase 2D.**
1. The gate does what it was built to do: 38 false credits prevented, at a cost of 3 partial-level credits.
2. Every Phase 2C false decision stays prevented.
3. No aligner decides correctness. Where verdicts differ by aligner, the cause is which candidate reaches the gate, in 2 of 359 claims.
4. The remaining false negatives are conservative, unverifiable, inherited, and spread over N=1 and N=0 rows. None is on an N=2 row, none creates a false high score, and crediting all of them would change at most 4 of 60 answer verdicts.
5. The only narrow fix that tested clean (V1) changes no answer verdict. It should not hold the lock.

**Read benchmark results with this bias in mind.** About 20% of claims that deserve credit are returned unverifiable, almost all through mechanisms that predate Phase 2D. Evaluator scores are therefore a conservative lower bound on evidence support, mainly on N=1 rows. Coverage is not accuracy, and neither number is Regulus accuracy.

**Backlog, outside the lock, in recommended order. None is implemented.**

1. **Before large-scale benchmarking: Priority-2 operator scope (§D.3).**
   - **Modality:** a "may" that chooses a means or channel must not be compared with the obligation it serves.
   - **Negation:** a negation inside a scoping relative clause ("products not required to be sterile") must not set the rule's polarity.
   - These create false *contradictions* (H-003 scored incorrect, 0), the harmful direction. This needs its own investigation and tests; it is not a gate change.
2. **V1, stemmed overlap: the narrowest deterministic gate-side fix found.**
   - Fixes singular/plural and verb-form misses (hazards/hazard, submitted/submit), with zero regressions against all 38 / 83 / 718 controls and 1824 tests.
   - Adopt only if its 2 ambiguous credits are accepted:
     - D-009 "The records shall include component, … and labeling records";
     - F-009 implementation records attributed to § 117.1(a).
   - The same normalization in the lexical alignment floor (#30) is untested.
3. **Guard:**
   - exempt the head noun of a mid-sentence anaphor ("these characteristics", #9);
   - add generic nouns such as "activities" (#28);
   - move operator words such as "prohibit" out of the object vocabulary.

   These are untested; each needs the same 38 / 83 / 718 check.
4. **Not narrow; redesign-level, and each would need fresh false-support controls:**
   - **a standard for claims with no modal** (12 false negatives). Loosening operator agreement directly risks the strength-and-polarity-only false supports Phase 2C found;
   - **multi-source conjunction support** (6);
   - **extraction:** carry antecedents, treat pointer sentences as pointers, strip the truncation notice (4);
   - **use the claim's named provision as a candidate** (#29).
5. **Do not adopt:**
   - V3 as written (it reopens a correct unverifiable);
   - V2 (it fixes nothing).

## H. Production safety

- No file under `src/`, `scripts/`, `tests/` or `web/` was modified during Phase 2E (checked by modification time against the phase start).
- Simulations ran on copies in `artifacts/accuracy/measurement_audit_phase2e_2026-10-08/work/variants/`. They were loaded only inside separate processes, by prepending the copy to `regulus.__path__`.
- Unchanged: retrieval, generation, prompts, evidence capture, citations, model configuration, database, corpus, rubric definitions, benchmark and human labels.
- No 300-question benchmark was run.
- The live server was not touched.

## Artifacts (`work/`)

- `p2e/all.json`: all 718 decisions with full gate traces.
- `p2e/classified.json`: the 190 classifications, each with root cause and note.
- `p2e/cls_*.json`: the raw reviewer classifications.
- `table_fn.md`: table B.
- `p2e/impact_*.json`: answer-level base, upper bound and V1.
- `p2e/all_V*.json`: variant decisions.
- Scripts: `collect.py`, `triage.py`, `consolidate.py`, `score_variant.py`, `impact.py`, `make_variants.py`, `use_variant.py`, `run_suite_variant.py`.

**Note on provenance.** The session scratchpad was wiped partway through this phase. The classification files were restored verbatim from the session transcript. Every recorded decision was then regenerated deterministically and matched the earlier counts exactly. All working files now live in this artifact folder.
