# Measurement Audit, Phase 1: forensic report

Read-only. No production, evaluator, fixture or label changes.

**Data.**
- The frozen 60-row validation inputs (`priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json`). Evidence is LEGACY_RECONSTRUCTED; no row has an exact evidence snapshot.
- Human labels from `artifacts/stage_a/dataset.jsonl`, unchanged.
- The current evaluator (Priority 3 code) under the configuration of record (semantic aligner) and, for robustness, the lexical aligner.
- Trace: `audit_60_semantic_and_lexical.json`; script: `audit_readonly.py`.

## A. Executive conclusion

- **C-004 is a measurement defect: HUMAN LABEL VALID / EVALUATOR TOO STRICT.**
  - The cited source `[1]` = 21 CFR 700.11(a) contains the answer-bearing sentence ("…is deemed to be adulterated under section 601(a) of the Federal Food, Drug, and Cosmetic Act") at the same verbatim strength as 700.14(a): 84% coverage, 16-word run.
  - The evaluator checks the citation against one supporting passage chosen by an aligner tie-break (cosine 0.9205 vs 0.9041), so it reports "points elsewhere".
  - With the lexical aligner the same claim's citation is correct.
  - Correction: my Priority 3 report said 700.11's captured text lacks the sentence. That was wrong.
- **Substantive measurement is largely sound:**
  - no N=0 answer scores above 50;
  - one false high, B-002 (N=1 at 100);
  - one false low, C-004 (N=2 at 0);
  - verdict-to-N agreement 75.7% exact, 100% within one level, on the 37 decided rows.
- **Citation measurement is not the rubric's L.**
  - Agreement 22/35 on decided rows. 12 rows have human L=0 but evaluator PASS; 1 row (C-004) is the reverse.
  - The evaluator checks only `[n]` markers on claim sentences, at section level, against one selected passage.
  - It ignores inline citations, paragraph granularity, trailing markers, citations in non-claim sentences, block citation, and guidance cited as the source of a requirement.
- **Completeness is not the rubric's O.** The evaluator measures the question's elements; O measures the answer key's governing sections. This is the cause of the only false high (B-002).
- **The paraphrase rule can support a claim whose distinguishing term is absent** (≥70% term overlap plus two agreeing operators).
  - Official configuration: C-002 (half of a conjunction unsupported) and B-003 ("the application" where 601.28 concerns annual reports).
  - Lexical aligner: "the use of **bithionol** … is prohibited" supported by 700.23 (chlorofluorocarbons).
  - No false high results today, but the mechanism is unsafe.
- **Two false INCORRECTs on N=1 rows:**
  - H-003: "you **may** submit … through ABI/ACE/ITDS" (choice of channel) read as contradicting the mandatory duty;
  - D-019: a garbled artefact read as an invented condition.
- **The legacy validation harness cannot measure citations reliably.** In 20 of 60 rows a lost guidance source shifted the `[n]` numbering.
- **The score is a substance-weighted measure, not a rubric-PASS predictor.** 3 of the 6 rows the evaluator scores "correct 100" FAIL the rubric (B-002, D-013, M-020).
- **Decision: OPTION B.** Localized defects: generally valid for substantive correctness, not yet valid for citation, completeness or PASS-rule comparisons.

## B. Measurement architecture

```
Question ──> Intent (topic, domains, elements, kind)                     [E1]
Answer ───> Segmentation: CLAIM / NON_CLAIM / UNCERTAIN                  [E2]
        └─> Splitting: modal lists, include-lists; local "These" resolution [E3]
Evidence (exact snapshot | legacy rebuild) ─> passages, authority, domain filter [E4]
Claim ─> aligner top-3 (semantic or lexical) ─> judge():
         contradiction (all aligned passages conflict) > verbatim > paraphrase
         > item / descriptive / adjacent window > undecidable           [E5][E6]
       ─> regulatory operators: strength, polarity, actor, quantity, date, condition
          (guidance-aware, Priority 2)                                   [E7]
       ─> relevance: topic terms in the SELECTED passage's text           [E8]
       ─> citation: [n] marker vs the SELECTED passage, section level     [E9]
Claims ─> answer verdict (correct / partial / incorrect / off-topic / unverifiable / refusal) [E10]
       ─> 7 dimensions ─> score = 100 − Σ deductions                     [E11]
Refusal ─> abstention judgement (pipeline state + on-topic evidence)      [E12]
```

| Layer | Decision logic and thresholds | Deterministic | False positive possible | False negative possible |
|---|---|---|---|---|
| Relevance (E8) | stemmed topic terms in the selected passage; RELEVANT ≥ ceil(n/2); domain and provision checks | yes, given the aligner | low (D-009/D-010 partial ≤40) | yes: vocabulary of the chosen passage (C-004 s1); off-topic when evidence is absent (F-022) |
| Extraction (E2, E3) | non-claims by category; list-shape splitting | yes | low | low (no false discards found in disputed rows) |
| Matching (E5, E6) | top-3 aligner; verbatim ≥80% and run ≥6; paraphrase ≥0.7 overlap and 2 operators; item, descriptive and window paths | **depends on the aligner** for ties (4/60 rows differ) | **yes**: paraphrase without the distinguishing term | yes: no-modal statements, ties |
| Operators (E7) | strength, polarity (main clause), actor, quantity, date, condition | yes | low | yes: choice-of-means "may" (H-003), artefacts (D-019) |
| Substantive (E10) | contradicted → incorrect; any unverified, partial or irrelevant → partial | yes | rare (B-002) | yes: one unverifiable secondary claim → partial |
| Citation (E9) | `[n]` on the claim vs the selected passage, section-level `split("(")[0]` | depends on the aligner | **yes, 12/35** | yes (C-004) |
| Completeness | question elements covered / unverified / missing | yes | **yes (B-002)**; O is not measured | — |
| Scope | non-Title-21 named, out-of-scope state | yes | 0/50 | 1/50 |
| Fabrication | named identifiers absent from the corpus, validator codes | yes (database existence) | 0/50 | 0/50 |
| Refusal (E12) | pipeline reason + on-topic evidence | yes | none found | temporal and missing-evidence refusals left unverifiable |
| Guidance authority (E7) | strength, actor and condition relations; support block; domain filter | yes | none found | n/a on legacy data (guidance lost) |
| Aggregation (E11) | 100 − Σ deductions; partial substance −45 | yes | correct-but-incomplete = 100 (B-002) | partials saturate to 0 (11/19 N=1 rows) |

## C. C-004 forensic finding

| Item | Finding |
|---|---|
| Question | "Which ingredients are prohibited or restricted in cosmetics under Part 700?" |
| Answer, sentence 2 | "These ingredients are deemed to be adulterated under section 601(a) of the Federal Food, Drug, and Cosmetic Act. [1]" |
| `[1]` points to | 21 CFR 700.11(a) (run citations list, index 1) |
| Human | N=2, L=1, M=0, O=1, P=1, PASS. "Substantively correct and correctly cited throughout … with the adulteration consequence under section 601(a)." Reviewer: "every provision named matches the paragraph cited." |
| 700.11(a) text | ends "Accordingly, any cosmetic containing bithionol is deemed to be adulterated under section 601(a) of the Federal Food, Drug, and Cosmetic Act." |
| 700.14(a) text | ends "Accordingly, any cosmetic aerosol product containing vinyl chloride as an ingredient is deemed to be adulterated under section 601(a) …" (also 700.15(b), 700.16(b), 700.18(b), 700.19(b)) |
| Claim vs 700.11(a) | 84% verbatim, 16-word run |
| Claim vs 700.14(a) | 84% verbatim, 16-word run (identical) |
| Semantic aligner | 700.14(a) cos 0.9205 ranks above 700.11(a) cos 0.9041 |
| `judge()` | `max(verbatim, key=coverage)`: tie → first in aligner order → 700.14(a) |
| `_citation()` | compares marker sources only with that one passage → `points_elsewhere` → citation FAIL (−40) |
| Lexical aligner | 700.11(a) ranks first → citation **correct** for this claim |
| C1/C2/C3 | not involved. The labelled answer is from acceptance_rev02 (1 Oct). The C1–C3 run produced a different answer from different evidence (700.11 not retrieved). |

**Cases.**
- Case 1 (700.11 governs and 700.14 is detail): **no**. Each section governs its own substance, and the sentence is the same boilerplate in both.
- Case 2 (the answer's citation is wrong): **no**.
- Case 3 (ambiguous label): **no**.
- Case 4 (rule too strict): **yes, in a specific form.** The rule does not require the sentence to be "inside the cited section"; it already is. It requires the cited source to be *the single passage the aligner happened to rank first*.

> **C-004: HUMAN LABEL VALID / EVALUATOR TOO STRICT.**
> The Priority 4 citation rule must recognise: *a claim's citation is correct when ANY source its marker points to supports the claim to the same standard the support verdict used* (verbatim or paraphrase, no operator conflict). It is not correct only when that source is the one passage chosen by the aligner. Ties must never be broken against the cited source.

**Analogous cases.** Every other `points_elsewhere` claim in the 60 rows has a cited source covering ≤44% of the claim: B-001, B-003, B-005, D-019, F-004, F-007, F-012, all on human L=0 rows. D-007 is human L=1 at 33%, but it's an off-topic N=0 row. So the misfire is unique to C-004 here, but the rule is general and will recur wherever boilerplate is shared across sections, as Part 700, 211 and 117 boilerplate is.

## D. Human-vs-evaluator disagreement table (material)

| ID | N | Evaluator verdict | L | Evaluator citation | Human judgment | Agree? | Classification and layer |
|---|--:|---|--:|---|---|---|---|
| C-004 | 2 | partial 0 | 1 | fail | PASS, correctly cited | no | FALSE_NEGATIVE_MEASUREMENT · citation (tie-break) |
| B-002 | 1 | correct 100 | 1 | pass | narrow sub-paragraph, substance of section missing | no | FALSE_POSITIVE_MEASUREMENT · completeness construct |
| H-003 | 1 | incorrect 0 | 0 | pass | channels right, timing missing, wrong 1.279(e) pointer | no | FALSE_NEGATIVE · operator (choice-of-means "may"); citation FALSE_POSITIVE (inline citation, harness renumbering) |
| D-019 | 1 | incorrect 0 | 0 | — | gist right, wrong attribution, artefacts | partly | FALSE_NEGATIVE (minor) · operator reads an artefact as a condition |
| F-022 | 1 | off-topic 0 | 0 | pass | core distinction partly right; block citation | no | FALSE_NEGATIVE · relevance with missing evidence; citation FALSE_POSITIVE (block citation) |
| F-003 | 1 | off-topic 0 | 1 | — | names 117.10 only; lists Subpart C | partly | HUMAN_LABEL_UNCLEAR (evaluator defensible) |
| D-013 | 2 (FAIL) | correct 100 | 0 | pass | misdirected opening pointer to 211.100(a) | substance yes, citation no | citation FALSE_POSITIVE: pointer sentences unchecked |
| M-020 | 2 (FAIL) | correct 100 | 0 | pass | paragraph pointers shifted inside 820.35 | substance yes, citation no | citation FALSE_POSITIVE: section-level granularity |
| D-010 | 0 | partial 40 | 0 | pass | cites 111.113(b)(1) inline for 211.80(d) text | citation no | citation FALSE_POSITIVE: inline citations unchecked |
| D-015 | 0 | incorrect 0 | 0 | pass | cites 111.55 / nonexistent 111.54 | substance yes | citation FALSE_POSITIVE (inline); M agrees |
| E-001 | 1 | partial 40 | 0 | pass | trailing [1] points to 11.100(a), not 11.1 | citation no | citation FALSE_POSITIVE: trailing marker not verified |
| F-009 | 1 | partial 35 | 0 | pass | misattributes to 117.20(a), 117.1(a) inline | citation no | citation FALSE_POSITIVE (inline) |
| E-010 | 1 | unverifiable | 0 | pass | guidance cited as the source; uncited | citation no | citation FALSE_POSITIVE (guidance-as-source rule absent) |
| E-009, PB-008 | 1, 0 | partial / unverifiable | 0 | pass | a marker resolved to no source | citation no | INSUFFICIENT_EVIDENCE: legacy renumbering; PB-008 marker sits in a non-claim |
| B-001 | 1 | partial 45 | 0 | pass | markers shifted across sections | unclear | HUMAN_LABEL_UNCLEAR / harness: the first quotations verify to the cited sources |
| E-007, H-001, L-010 | 2 | unverifiable | 0/0/1 | — | correct | no decision | INSUFFICIENT_EVIDENCE (guidance lost in the legacy harness) |
| 15 × N=1, 5 × N=0 | — | unverifiable | — | — | — | no decision | EVALUATOR_UNCERTAIN / INSUFFICIENT_EVIDENCE (see the earlier forensic report) |

## E. False positive audit

| Pattern | Found? | Evidence |
|---|---|---|
| Wrong-topic answer scored high | no | 12 wrong-topic rows; max 40 (D-009, D-010) |
| Wrong product or section scored high | no | domain/provision checks; D-008 off-topic |
| Incorrect duty-holder / modal / number / negation scored high | no | operator conflicts give incorrect |
| **Partial or incomplete answer scored like N=2** | **yes: B-002** | completeness is question-based, not answer-key based |
| Incorrect refusal scored high | no | C-001, NC-003 at 0 |
| **Citation errors hidden** | **yes: 12 rows** | §D. The citation dimension passes; the substantive verdict is unaffected by design |
| **Support by shared terminology** | **yes, at claim level** | C-002, B-003 (official); C-004 s8 bithionol ← 700.23, F-007 ← 117.160 (lexical) |
| Adjacent but legally different provision | partly | C-002's conjunction half-supported by 701.12(a) |
| Guidance treated as binding | no on legacy data | Priority 2 support block; untested on exact guidance rows |
| Cross-section evidence as citation support | no | the section-level comparison is the opposite problem (too lax within a section) |

**Score vs rubric PASS.** Of the 6 rows the evaluator scores "correct 100", only 3 PASS the rubric. B-002 fails completeness; D-013 and M-020 fail citation (and M-020 also Q). The evaluator's top score is not a PASS signal.

## F. False negative audit

| Pattern | Found? | Evidence |
|---|---|---|
| Cross-section / shared boilerplate citation | **yes: C-004** | tie-break against the cited source |
| Choice-of-means "may" under a mandatory duty | **yes: H-003** | false INCORRECT |
| Artefact text read as a condition | yes: D-019 | false INCORRECT (human N=1) |
| Distinction answer with absent evidence called off-topic | yes: F-022 | should be unverifiable |
| One unverifiable secondary claim forces PARTIAL | latent | G-004 avoided only because its claims were verified |
| Partial answers saturate to 0 | yes | 11 of 19 scored N=1 rows = 0, equal to N=0 |
| List items, include-lists, descriptive statements | resolved by Priority 3 | M-020, G-004 correct |
| Correct abstentions | not measurable | no N=2 refusal in the set |
| Guidance-backed correct answers | not measurable on legacy data | E-007, H-001, L-010 unverifiable (guidance lost) |

**Claim extraction (§10).** No disputed row traces to a discarded, created, mis-split or mis-merged substantive statement. Two extraction-adjacent gaps affect *citation*, not substance:

- citations in NON_CLAIM sentences (pointers, trailing `[1]`, "the sources that support this are [1][2]") are never verified (D-013, E-001, PB-008);
- citations inline in claim text are ignored.

**Evidence matching (§11).**

| Row | Evidence present? | Evaluator finds it? | Assessment |
|---|---|---|---|
| C-004 | yes, in the cited source | yes | picks a tied neighbour (measurement defect) |
| H-003, D-019 | yes | yes | misreads operators |
| F-022 | no (FSVP not retrieved) | — | legitimate inability, mislabelled off-topic |
| E-007, H-001, L-010 | no (legacy harness lost guidance) | — | evidence limitation of the legacy set |

## G. Measurement defect taxonomy

- **Measurement defects (logic wrong):**
  - citation verified against one tie-broken passage (C-004);
  - citation concept narrower than L (inline, paragraph, trailing, non-claim, block, guidance-as-source; 11 rows);
  - completeness ≠ O (B-002);
  - paraphrase support without the distinguishing term (C-002, B-003);
  - choice-of-means modal (H-003);
  - relevance from the vocabulary of the selected passage (C-004 s1);
  - off-topic on missing evidence (F-022).
- **Coverage limitations:** descriptive and no-modal claims, and temporal refusals (see the earlier forensic report).
- **Evidence limitations:** the legacy set has no exact evidence, guidance text is lost (13 rows), and `[n]` numbering is shifted (20 rows).
- **Benchmark-label issues:**
  - F-003 (generous N=1);
  - B-001 (a citation-shift description that the trace only partly confirms);
  - O depends on an answer key the evaluator can't see. That isn't a label defect, but it makes O unmeasurable by design.
- **System/model errors (evaluator correct):** D-001, D-003, D-004, D-007, D-008 off-topic; C-001, NC-003 incorrect refusals; most N=1 partials.
- **Benign conservatism:** 23 unverifiable rows, none contradicting a positive human judgment the evidence could prove, apart from those listed above.

## H. Metrics (configuration of record: semantic aligner, legacy-reconstructed evidence)

| Metric | Value | Status |
|---|---|---|
| Coverage (definitive verdict) | 37/60 = 61.7% | reproduced (Priority 3 record) |
| Verdict→N exact agreement | 28/37 = 75.7% | new |
| Verdict→N within one level | 37/37 = 100% | new |
| False high (N<2 and ≥85) | 1/31 (B-002) | new |
| False low (N=2 and <50) | 1/6 (C-004) | new |
| N=0 scored >50 | 0 | reproduced |
| Mean by N (2 / 1 / 0) | 83.3 / 18.7 / 6.7 | reproduced |
| Spearman (scored rows) | 0.523 | reproduced |
| Citation agreement with L (decided) | 22/35 = 63%; 12 false PASS, 1 false FAIL | new |
| Fabrication agreement with M | 50/50 | new |
| Scope agreement with P | 49/50 | new |
| Completeness vs O | not comparable (different construct) | new |
| "Correct 100" → rubric PASS precision | 3/6 | new |
| Aligner sensitivity | 4/60 rows change a dimension or score | new |

N=1 vs N=0 separation is weak because partial scores saturate: 11 of 19 scored N=1 rows score 0.

## I. Severity ranking

- **CRITICAL:** none. There is no systematic false-high pathway on substance; N=0 high is 0/17.
- **HIGH:**
  1. Citation construct ≠ rubric L (11 rows false PASS).
  2. Completeness construct ≠ O (B-002 false high).
  3. Paraphrase support without the distinguishing term (claim-level false support).
  4. The legacy harness can't validate citation or guidance measurements (20 + 13 rows).
- **MEDIUM:**
  1. Citation tie-break (C-004, a false low on a PASS answer).
  2. Choice-of-means modal (H-003, false INCORRECT).
  3. Relevance and support depending on aligner tie-breaks (4 rows).
  4. Off-topic on missing evidence (F-022).
  5. Partial-score saturation.
- **LOW:** artefact text as a condition (D-019).

## J. Final decision

**OPTION B: measurement has localized defects.**

The evaluator is valid for comparing *substantive correctness*: no N=0 high, 1 false high and 1 false low in 37 decided rows, and all disagreements within one level. Specific rules in the citation, completeness, paraphrase and modal layers need correction.

Until they're corrected, it must **not** be used to compare experiments on citation accuracy, completeness or the rubric PASS rate. Its validation must move to a set generated with exact evidence capture.

## K. Phase 2 requirements (investigate; do not implement here)

1. **Citation grounding (fixes C-004).**
   - Defect: the citation is verified against one aligner-selected passage.
   - Root cause: `answer._citation` compares markers with `verdict.alignment.passage` only; `verdicts.judge` breaks verbatim ties by aligner order.
   - Impact: 1 row (C-004), recurring wherever boilerplate is shared.
   - Correction: a citation is correct if any marked source supports the claim to the support standard (verbatim, or paraphrase with no conflict).
   - Risk: a marker on a loosely related source could pass, so require the same standard as support.
   - Validation: C-004 → citation pass; every current `points_elsewhere` with cited coverage ≤44% stays a defect; result identical under both aligners.
2. **Citation construct alignment with L.**
   - paragraph-level comparison when the claim asserts a paragraph requirement (M-020);
   - parse and verify inline CFR citations in claim text (D-010, D-015, F-009, H-003);
   - verify trailing and paragraph markers against each claim they cover (E-001);
   - check markers in non-claim sentences, including pointers (D-013, PB-008);
   - block citation of all sources (F-022);
   - guidance cited as the source of a requirement → L=0 (E-010).

   Validate against L on an exact-evidence set. Risk: stricter citation lowers scores for correct answers with imprecise pointers, which the rubric already penalises.
3. **Completeness vs O.** Either measure against the answer key where one exists, or rename the dimension "question coverage" and stop it implying O. In particular, detect an answer that quotes only a sub-paragraph of the section the question asks about (B-002). Validate: B-002 is not "correct".
4. **Paraphrase support.**
   - Requirement: claim terms that distinguish its subject (substance, object, party, number) must appear in the passage.
   - Validate: C-002 is partial for its first conjunct; B-003 is not supported; bithionol ← 700.23 is not supported under either aligner.
   - Risk: legitimate paraphrases with synonym subjects become unverifiable.
5. **Modal choice-of-means.** "May submit through A or B", inside a mandatory duty, is not a strength conflict. Validate: H-003 has no contradiction, and test 14 (a genuine "may vs shall") still contradicts.
6. **Aligner-independence.** Ties are resolved deterministically and in favour of the cited source; relevance is computed over all equally supporting passages. Validate: the semantic and lexical arms agree on all 60 rows.
7. **Missing evidence ≠ off-topic** for distinction questions (F-022).
8. **Validation infrastructure.** Label a new set generated with exact evidence capture (Priority 1 snapshots preserve `[n]` indices and guidance text). The legacy 60 can't validate citation or guidance behaviour.

### Answers to the success questions

1. **Is C-004 a measurement defect?** Yes: a citation tie-break against the cited source. Human label valid; evaluator too strict.
2. **Other false negatives?** Yes: H-003 and D-019 (false INCORRECT), F-022 (off-topic on missing evidence), and partial-score saturation.
3. **Dangerous false positives?** No false highs on substance beyond B-002. False positives exist in citation (12 rows) and at claim level through paraphrase.
4. **Layer per disagreement:** see table D.
5. **Is the rubric precise enough?** Yes for N, L, M and P. O depends on an answer key the evaluator doesn't use. F-003 and B-001 are borderline.
6. **Trustworthy for comparisons?** Yes for substantive correctness, with known error modes. No for citation, completeness or PASS rate.
7. **Next correction:** citation grounding (items 1 and 2), then completeness (item 3) and paraphrase support (item 4).
