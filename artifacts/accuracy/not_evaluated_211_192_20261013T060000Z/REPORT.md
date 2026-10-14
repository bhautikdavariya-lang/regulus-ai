# Forensic diagnosis: NOT EVALUATED for 21 CFR 211.192

Date: 2026-10-13. Read-only investigation. No repository code changed. The candidate correction exists
only as `candidate_window_gate.diff` and was exercised in a scratch copy of `src/`.

## 1. The original case

**Not located.** `scripts/serve_ui.py` does not persist questions, answers or assessments. No artifact
pairs a 21 CFR 211.192 question with a live NOT EVALUATED label. The benchmark rows that cite 211.192
(D-023, D-026) hold recorded answers that do not cover the reported content.

What is needed to replay the exact case: the question text, the displayed answer text, and the adapter
and top_k. The code has changed several times today, so the question alone may not reproduce the answer.

Below, the original is therefore **reproduced by mechanism, not replayed**. Every test answer is labelled
by what it is.

## 2. Regulatory source (verified)

21 CFR 211.192 "Production record review.", a single undivided paragraph: `cfr_records` ordinal 0,
snapshot 2026-09-03, sha256 `623102175ff6…48ad`, 883 chars. It holds four sentences, all explicit
requirements ("shall"):

| | Requirement (explicit text) |
|---|---|
| S1 | QCU must review and approve all production and control records (incl. packaging/labeling) for compliance with written procedures **before a batch is released or distributed** |
| S2 | Any unexplained discrepancy (incl. theoretical-yield excursions), or a failure of a batch/component to meet any specification, **shall be thoroughly investigated, whether or not the batch has already been distributed** |
| S3 | The investigation **shall extend to other batches** of the same drug product **and other drug products** that may have been associated with the failure or discrepancy |
| S4 | A **written record** of the investigation shall be made and shall include **conclusions and followup** |

The reported answer covers S2–S4. **S1 is an additional material obligation** of the section that the
reported answer does not mention. "Whether or not the batch has already been distributed" is an explicit
condition of S2. Anything about root-cause method, CAPA or timelines would be interpretation; the section
states none of it.

## 3. Reproduction

| Run | Path | Result |
|---|---|---|
| `reproduce.py`, three natural wordings | `serve_ui.Engine.ask` (greedy, configured adapter, top_k 8, exact evidence snapshot) | PASS 100, PASS 100, **FAIL 55**. No NOT EVALUATED |
| `versions.py`, the FAIL-55 answer re-scored | evaluator as at start of day / after focus fix / current | FAIL 55 under all three. **Not a regression from today's changes** |
| `matrix.py`, 9 answers × 3 questions | production pipeline (validation, repair, snapshot) with a scripted model; assessed exactly as `Engine.assess` | **NOT EVALUATED reproduced in exactly one cell** |

The reproducing cell:

- Question: *"Under 21 CFR 211.192, what must a manufacturer do when a batch fails to meet specifications?"*
- Answer (constructed; it covers investigation, extension to other batches/products, and written
  records): *"Any unexplained discrepancy or batch failure to meet specifications must be thoroughly
  investigated, and that investigation must extend to other batches of the same drug product and other
  associated drug products. A written record of the investigation, including conclusions and followup,
  must be made. [1]"*
- Evidence: one source, [1] 21 CFR 211.192, all four sentences. Nothing was dropped by selection.
- Exact displayed reason: **"Cannot be verified: 1 statement(s) address the question but none could be
  verified against the retrieved evidence"**. Status `unable_to_determine`; substantive correctness
  `not_established`.

## 4. Claim-by-claim mapping (the reproducing cell)

| Claim | Supporting text | Support | Relevance | Effect |
|---|---|---|---|---|
| C1 "…must be thoroughly investigated, and that investigation must extend to other batches … and other associated drug products" | S2 + S3 (adjacent) | **unverifiable** (`not_decisive`): against a single sentence only 62% of terms / 75% of core terms. The S2+S3 window was judged paraphrase_equivalent (overlap 1.0, 100% core terms) **but rejected** | relevant | the only claim counted as answering, and it is unverified |
| C2 "A written record of the investigation, including conclusions and followup, must be made [1]" | S4 | supported (paraphrase), citation correct | **irrelevant**: S4 alone shares no word with the topic batch/fail/meet/specific | excluded from "answering" |

Derivation: answering claims = {C1}; none supported or partial → `answer.verdict` returns
ANSWER_UNVERIFIABLE ([answer.py:596](../../../src/regulus/accuracy/answer.py)) → substantive
`not_established` → `rubric.status_for` → UNABLE → `review.question_review` → **NOT EVALUATED**.

## 5. Root cause (exact failure point)

**Primary:** `verdicts.judge_window`, gate `WINDOW_MIN_RUN_EACH = 5`
([verdicts.py:671](../../../src/regulus/accuracy/verdicts.py)). A window must have a verbatim run of at
least 5 words into **each** sentence. The gate guards row F-007 (one sentence carries the match, the
other only adds terms). The 211.192 paraphrase compresses S2's long parenthetical, leaving a run of 3
words into S2 (and 11 into S3). Probe (`window_probe.out`):

| claim | verdict on S2+S3 | overlap | runs into S2 / S3 | judge_window |
|---|---|---|---|---|
| merged paraphrase | paraphrase_equivalent | 1.00 | **3** / 11 | **None** (rejected) |
| merged near-verbatim | paraphrase_equivalent | 1.00 | 20 / 16 | paraphrase_equivalent |

**Compounding (already known in this task, not new):** relevance is judged on the single aligned
sentence in isolation (`relevance.assess`, `judged_against`). A continuation sentence such as "A written
record of the investigation…" names none of the question's words, so it reads as off-topic. On its own
this produces FAIL 55 (the closest-match generated answer). Combined with the primary defect it removes
the last answering claim, which produces NOT EVALUATED.

**Classification: D, claim-matching / semantic verification failure.** It is not:

- A (retrieval): one row, complete, nothing withheld.
- B (generation): the answer is faithful.
- C (citation): the citation defect on C1 is a consequence of C1 being unverified.
- E (completeness): completeness is not_established only because of D.
- F (insufficient evidence): the evidence fully states every claim.

The abstention was a **false abstention on a correct, supported answer.**

## 6. Focused matrix (current code → with candidate)

Answers are built from the verbatim database text unless marked otherwise.

| answer | broad "What does 211.192 require?" | "investigation requirements under 211.192?" | focused "…batch fails to meet specifications?" |
|---|---|---|---|
| 1 verbatim S1–S4 | PASS 100 | FAIL 55 (S1 judged irrelevant to "investigation") | FAIL 55 (S4 irrelevant) |
| 1b verbatim S2–S4 | PASS 100 ⚠ | PASS 100 | FAIL 55 (S4 irrelevant) |
| 2 paraphrase S1–S4 | FAIL 40 (S4 paraphrase unverifiable) | FAIL 40 | FAIL 40 |
| 3 + one fabricated claim ("notify FDA within 3 working days") | PASS 100: repair removed the sentence before delivery | FAIL 0: answer withheld (correct) | FAIL 0: withheld (correct) |
| 4 omits S2 (investigation duty) | **PASS 100 ⚠** | FAIL 55 | FAIL 30 (completeness fail) |
| **5 S2+S3 merged (adjacent support)** | FAIL 40 → **PASS 100** | FAIL 40 → **PASS 100** | **NOT EVALUATED → FAIL 55** |
| 6 closest-match generated answer (Engine.ask, greedy) | PASS 100 | PASS 100 | FAIL 55 |
| 7 = 6 without the [1] marker | PASS 100 | PASS 100 | FAIL 55 |
| 8 pronoun-led ("It must also cover…") | FAIL 40 | FAIL 40 | FAIL 40 |

Only the three case-5 cells change, all toward the correct verdict. No cell containing an unsupported
claim or an omission moves.

## 7. Proposed correction (not applied)

`candidate_window_gate.diff`, verdicts.py only. The window keeps every existing gate (borne-out verdict,
≥ 85% overlap), and the verbatim-run gate gains one alternative: the window also counts as needed and
used when **each sentence alone carries ≥ 3 of the claim's core terms that the other sentence lacks**.
Test 13b / F-007 (one sentence contributes no term of its own) is still rejected.

Validation in the scratch copy:

- Accuracy, answer-plan and IND suites: **735 passed, 4 xfailed, 0 failed**, identical to current code.
  An initial 36 UI-test failures were a scratch-path artifact (`scripts/`, `web/` missing) and passed
  (56/56) once those were linked.
- The 211.192 matrix: as in §6.

Safeguards preserved:

- A window can still only support, never contradict.
- Two sentences, one source, never across sources.
- No change to contradiction, fabrication, citation, scope or completeness checks.
- Unverified claims stay unverified when either sentence is merely decorative.

What it does **not** fix: the focused cell becomes FAIL 55 rather than PASS, because the
relevance-isolation defect remains. Fixing that requires relevance to read a continuation sentence with
its antecedent: a definite reference ("the investigation") resolved to the preceding sentence of the same
source. That changes how relevance is decided for every answer and feeds verdict, completeness and focus
logic. It is a design decision, so it is **presented here, not implemented**.

## 8. New findings vs known limitations

- **New:** the window verbatim-run gate rejects legitimate two-sentence paraphrases. This is the
  NOT EVALUATED cause.
- **New:** broad-synthesis completeness passes an answer that omits S1 or S2 of 211.192 (cells 1b and
  4, PASS 100). `_synthesis_gap` counts top-level *rows*; 211.192 is one undivided row holding four
  obligations, so any one verified sentence "covers" it. This is a limitation of the synthesis check
  shipped in the previous task (sentence-level obligations inside one paragraph are not units). Separate
  from NOT EVALUATED; not fixed here.
- **Known (this task, earlier):** sentence-isolated relevance (S4 "irrelevant" to a batch-failure
  question).
- **Observed, judgement call:** for "investigation requirements", the S1 records-review sentence is
  judged irrelevant, giving FAIL 55 for a complete verbatim answer.
- **Observed:** single-sentence paraphrase of S4 ("The firm must keep a written record…") is unverifiable
  (cell 2). This is a paraphrase limit of `judge`, not of the window.

## 9. Remaining uncertainty

- The user's actual answer is unknown. The reproduction matches the reported content and symptom, but a
  different wording could reach NOT EVALUATED by another route, e.g. pronoun-led claims whose relevance is
  undetermined (cell 8 comes close).
- The candidate was not run against the frozen benchmark (not authorised), so its effect on false
  supports across the corpus is unmeasured beyond the test suite.
- The ≥ 3 own-terms threshold is untuned. It was chosen so that F-007 / test 13b (0 own terms) stays
  rejected and the 211.192 merge (≥ 5 per side) is admitted.

## Files

`work/versions.py`, `work/matrix.py` (+ `matrix.json`, `matrix_candidate.json`), `work/window_probe.py`
(+ `.out`), `work/cell_focused_5.json`, `candidate_window_gate.diff`. No file under `src/`, `tests/`,
`configs/`, benchmark or rubric was modified.
