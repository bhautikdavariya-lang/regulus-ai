# Stage B: obligation-level completeness. DESIGN FOR REVIEW (not implemented)

Date: 2026-10-13. The production completeness logic is unchanged (`evaluator.py` sha a0eab063…). The design was
exercised only in a scratch copy (`prototype_obligation_units.diff`). Nothing committed, no benchmark run.

## Root cause (verified)

`evaluator._synthesis_gap` takes its units from **source rows**:

- `covered` = the source index of each decided answering claim's first evidence passage;
- `represented(i)` = `i in covered or reproduced(i)`, where `reproduced` tests the whole row text.

21 CFR 211.192 is one undivided row holding four obligations. Any one verified statement therefore marks the whole
provision represented, and an answer omitting S1, S2, S3 or S4 scores PASS 100 on "What does 21 CFR 211.192
require?". Current code, `work/stage_b_matrix.py`: every single-obligation omission, verbatim or paraphrased, gets
PASS 100, and so does "S1 only".

Two further routes reach the same false pass:

- **R2, heading-worded questions.** "What are the production record review requirements in 21 CFR 211.192?" is
  planned *focused* because its focus words equal the section heading. It never reaches `_synthesis_gap`; every
  omission scores PASS 100.
- **R3, `_focus_gap` granularity.** It also works per row. "What are the investigation requirements under 21 CFR
  211.192?" answered with S2 alone (no extension, no record) scores PASS 100.

## Source obligations (211.192, verbatim text; explicit requirements only)

| unit | obligation | carried by |
|---|---|---|
| S1 | QCU reviews and approves all production and control records (incl. packaging/labeling) for compliance with written procedures **before a batch is released or distributed** | "shall be reviewed and approved" |
| S2 | Any unexplained discrepancy (incl. theoretical-yield excursions) or failure of a batch/component to meet specifications **shall be thoroughly investigated, whether or not the batch has already been distributed** | "shall be thoroughly investigated" |
| S3 | The investigation **shall extend** to other batches of the same drug product and other drug products that may have been associated | "shall extend" |
| S4 | A **written record** of the investigation **shall be made** and include conclusions and followup | "shall be made … shall include" |

The design derives these units from the text by rule (mandatory sentences); nothing about 211.192 is hardcoded.
Root-cause analysis, CAPA, timelines and "manufacturer" as the actor are interpretation; the section states none
of them.

## Design

### D1. Units (synthesis of a named provision)

Within each top-level obligation row selected as today, split the row with the evaluator's own sentence splitter
(`alignment.passages`) and keep the sentences whose `OP.strength` is MANDATORY.

- A row with one mandatory sentence, or a lead-in row ending ":" with items, keeps today's row-level rule.
- A row with several mandatory sentences contributes **one unit per mandatory sentence**.

Non-mandatory sentences (definitions, exemptions, "may") are never units.

### D2. Represented

A unit is represented when either holds:

- a **decided** answering claim's aligned passage is that sentence (supported, citation-defect, partially
  supported or contradicted, the same set as today; a window credits both of its sentences); or
- the answer reproduces that sentence verbatim under today's rule, applied per sentence: run ≥ max(min(8, n),
  0.6·n). This is what makes text appended by post-processing count *when it genuinely states the requirement*,
  while a bare heading or a stock phrase never does. Headings are not mandatory sentences, so they are never units
  and never stand in for one.

### D3. Addressed but unverified

A unit is addressed but unverified when an unverifiable claim holds ≥ 50% of its core terms in that sentence
(`verdicts.core_overlap`). That yields completeness NOT_ESTABLISHED, not FAIL: the evidence was retrieved but the
evaluator did not recognise it.

Two rules were tried and rejected:

- using only the first aligned passage marked paraphrased obligations as missing;
- using all aligned candidates masked a genuinely omitted S1.

### D4. Outcome (precedence unchanged)

| outcome | completeness |
|---|---|
| any unit missing | FAIL |
| otherwise any unit unverified | NOT_ESTABLISHED |
| otherwise mandatory rows withheld by the selection ceiling (`package.withheld`) | NOT_ESTABLISHED (as today) |
| otherwise | PASS |

Evidence never retrieved at all stays with the coverage check (`coverage.missing_labels`), as today. Labels name the
provision plus the sentence's first words, so the reader sees *which* obligation is missing.

### D5. Heading-worded questions (R2)

When the focus terms of a focused question are all contained in the requested provision's own heading, and the
question names that provision, apply D1–D4 as for a synthesis: the question asks for the provision as a whole,
in its own title words.

### D6. Focused granularity (R3)

In `_focus_gap`, split on-topic rows into mandatory sentences. A sentence is required when **its own text**
carries the question's distinguishing focus terms; D2/D3 apply per sentence.

There is deliberately no anaphora resolution: "A written record of the investigation …" is required for an
"investigation" question because it names "investigation", not because it follows S3. The follow-on-sentence
relevance change stays out of scope, as instructed.

## Evidence from the prototype (D1–D4 only; D5/D6 not prototyped)

### Lexical production path (`work/stage_b_matrix.py`; pipeline with validation, repair and snapshot)

Broad question "What does 21 CFR 211.192 require?":

| answer | current | prototype |
|---|---|---|
| complete verbatim | PASS 100 | PASS 100 |
| complete paraphrase | PASS 100 | PASS 100 |
| omits S1 / S2 / S3 / S4, verbatim | PASS 100 ×4 | **FAIL 75 ×4** (completeness fail names the sentence) |
| omits S1 / S2 / S3 / S4, paraphrase | PASS 100 ×4 | **FAIL 75 ×4** |
| complete + unsupported claim ("notify FDA of every investigation") | FAIL 40 | FAIL 40 (support dimensions; completeness pass) |
| bare heading "Production record review." + S2–S4 | PASS 100 | **FAIL 75** (heading supplies nothing) |
| S1 only | PASS 100 | **FAIL 75** |

Focused and heading-worded questions are unchanged by D1–D4, as intended. The two routes below remain false passes
until D5/D6:

| question | answer | current | prototype |
|---|---|---|---|
| production record review requirements (R2) | each omission | PASS 100 | PASS 100 ✘ |
| investigation requirements (R3) | S2 only | PASS 100 | PASS 100 ✘ |
| investigation requirements | S2–S4 | PASS 100 | PASS 100 ✔ |
| batch fails to meet specifications | S2 only | PASS 100 | PASS 100 (S4 has no focus word, so D6 would not require it; S3 contains "batch") |
| batch fails to meet specifications | complete or S2–S4 | FAIL 55 | FAIL 55 (S4 judged off-topic in isolation: known relevance limitation, out of scope) |

### Real path (semantic aligner, live DB, `Engine.assess` arguments; `work/real_path_matrix_prototype.json`)

| broad cell | current | prototype | why |
|---|---|---|---|
| verbatim S1–S4 | PASS 100 | PASS 100 | complete |
| verbatim S2–S4 | PASS 100 | **FAIL 75** | S1 missing |
| omits S2 | PASS 100 | **FAIL 75** | S2 missing |
| closest-match generated answer (S2–S4) | PASS 100 | **FAIL 75** | S1 missing |
| same, no [1] marker | PASS 100 | **FAIL 75** | S1 missing |
| fabricated sentence → repair replaced the answer with the verified provision text | PASS 100 | PASS 100 | S1–S4 reproduced verbatim by post-processing: a genuine supply |
| paraphrase S1–S4, S4 paraphrase unverifiable | FAIL 40 | FAIL 35 | completeness **not established** (unverified, not missing) |
| merged S2+S3 (unverifiable) + S4 | FAIL 40 | FAIL 15 | S1 genuinely missing → FAIL |
| pronoun-led claims | FAIL 40 | FAIL 15 | S1 missing (correct); S4 also listed missing although an unverifiable claim addresses it (imprecision, below) |

All "investigation" and "focused" cells are unchanged, including the NOT EVALUATED cell.

### Suite

The prototype gives 745 passed, 9 xfailed. The only difference from current code is the intended XPASS of
`test_a_broad_answer_omitting_the_record_review_obligation_does_not_pass`. The 312.32 synthesis tests, the 211.25
repair tests, the focus-gap tests and the IND tests are all unchanged.

## Proposed tests (to add with the implementation)

1. Broad 211.192: complete verbatim → PASS 100; complete paraphrase → PASS 100.
2. Broad 211.192: omit each of S1–S4, verbatim and paraphrase (8 cases) → completeness FAIL naming that sentence;
   never PASS 100.
3. Broad: one obligation addressed only by an unverifiable paraphrase → completeness NOT_ESTABLISHED (not FAIL).
4. Broad: bare heading + S2–S4 → FAIL; repair-appended verbatim provision text → PASS.
5. Broad: complete + one unsupported claim → not PASS (support dimensions), completeness PASS.
6. A single-mandatory-sentence row and a lead-in-with-items row behave exactly as today (312.32, 211.25 tests kept).
7. D5: the heading-worded 211.192 question with S1 omitted → not PASS 100.
8. D6: "investigation requirements" with S2 only → completeness FAIL (S3/S4 missing); with S2–S4 → PASS.
9. Focused "batch fails to meet specifications" with S2 only → unchanged. This documents that D6 requires only
   sentences naming the focus.
10. Ceiling-withheld obligations → NOT_ESTABLISHED (existing test kept).

## Expected score behaviour

- Complete answers keep PASS 100.
- An incomplete broad answer cannot get PASS 100: completeness FAIL costs 25 (FAIL 75 when nothing else fails).
- Obligations addressed only by unverified statements give NOT_ESTABLISHED (NOT FULLY EVALUATED when nothing
  else fails), never PASS.

## Risks

1. **Strictness on long paragraphs (measured).** 3,282 of 15,933 obligation-bearing eCFR rows (21%) have ≥ 2
   mandatory sentences, and 139 have ≥ 5 (`work/corpus_survey.json`). Broad answers to those provisions must
   cover every mandatory sentence. Some are minor procedural sentences, so expect more completeness FAILs on
   broad questions. Whether every mandatory sentence is *material* is a policy decision, not something the code
   can settle.
2. **Not measurable on frozen data.** F60's package shim carries no answer plan, so `_synthesis_gap` never runs on
   it. The effect on real answers is unmeasured until stored answers with plans are re-scored.
3. **Alignment-to-sentence mapping.** The prototype matches a claim's aligned passage to a sentence by normalised
   text prefix, because `Passage.to_dict` does not carry `seq`. Production should add `seq` to the evidence
   record (additive) instead.
4. **Unverified-vs-missing threshold (≥ 50% core terms).** This is a heuristic. Pronoun-led claims whose resolved
   text is diluted can fall below it and be called missing (cell 8). The error direction is FAIL instead of
   NOT_ESTABLISHED, never a false PASS.
5. **Sentence splitting.** Abbreviations and "§" citations can split or join sentences wrongly. The splitter is
   the one the evaluator already relies on, but completeness would now depend on it directly.
6. **D5/D6 not prototyped.** Their exact trigger (focus ⊆ heading; sentence carries the focus terms) needs its own
   matrix before implementation.

## Remaining false passes / false failures / NOT EVALUATED (211.192, all stages)

| Type | Cases |
|---|---|
| False PASS 100 (current) | broad omissions (fixed by D1–D4 in the prototype); heading-worded omissions (D5); focused "investigation" S2 only (D6); single-sentence FDA actor and narrowed scope (Stage A judge gaps) |
| False FAIL | focused S2–S4 / complete answers FAIL 55 (S4 off-topic in isolation); paraphrased S4 unverifiable (FAIL 40); pronoun-led claims FAIL 40 |
| NOT EVALUATED | focused merged S2+S3 answer (window gate + isolated relevance) |
