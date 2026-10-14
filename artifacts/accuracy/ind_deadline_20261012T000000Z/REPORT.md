# IND safety-reporting deadline failure: root cause and fix

**Reported failure.** An answer confused the 15-calendar-day reporting rule of 21 CFR 312.32(c)(1)
with the 7-calendar-day rule of §312.32(c)(2) for unexpected fatal or life-threatening suspected
adverse reactions.

**Ground truth** (read-only eCFR snapshot, `cfr_records`, section 312.32):

| ordinal | paragraph | rule |
|---|---|---|
| 7 | (c)(1) | IND safety reports — "no case later than **15 calendar days** after the sponsor determines that the information qualifies" |
| 16 | (c)(2) | Unexpected fatal or life-threatening suspected adverse reaction reports — "no case later than **7 calendar days** after the sponsor's initial receipt of the information" |

## Phase 1 — reproduction and attribution

Reproduced through the real server engine (`serve_ui.Engine.ask`, local weights, read-only
database, page defaults), five wordings, each answered with evaluation ON and again OFF:
`work/repro.py` → `work/repro.json`.

The reported failure reproduced exactly on **D4**, "What is the difference between the
15-calendar-day and 7-calendar-day IND safety reporting deadlines in 21 CFR 312.32?":

> … the 15-calendar-day deadline applies to reports that qualify for reporting under paragraph
> (c)(1)(i), (c)(1)(ii), (c)(1)(iii), or (c)(1)(iv) of this section, while **the 7-calendar-day
> deadline applies to reports that qualify under paragraph (c)(1)(i)** of this section. [1]

…citing **[1] = 312.32(a)**, the Definitions paragraph, and evaluated as **NOT EVALUATED**.

### The primary cause is evidence selection, not generation and not the evaluator

Retrieval returned all 25 paragraphs of §312.32. Selection kept 14 and dropped 11, and the drop
ledger is decisive (`work/repro.json`, `selection.dropped`):

```
  1 312.32(a)          block  250   running  250     <- six (a) definition paragraphs
  …
  6 312.32(a)          block 1364   running 4416     <- 49% of the 9,000-char ceiling spent
  7 312.32(b)          block  721   running 5139
  8 312.32(c)(1)       block  989   running 6130     <- the 15-day rule
  …
 13 312.32(c)(1)(ii)   block  802   running 8734
 14 312.32(d)          block  190   running 8926
 DROPPED (hard_ceiling_chars): (c)(1)(iii) (c)(1)(iv) (c)(1)(v) (c)(2) (c)(3) (c)(4) (c)(5) …
```

`select_evidence` Phase 1 spent the 9,000-character hard ceiling in **document order**. The six
`(a)` definition paragraphs took 4,416 characters before any requirement text was reached, and
`(c)(2)` — 298 characters, and the entire answer to the question — was dropped as overflow. The
question literally contains "7-calendar-day"; the paragraph stating it was never put in front of
the model. Scores confirm pure document order: 100.000, 99.999, 99.998 … = `100 − 0.001 × ordinal`.

Coverage said `COMPLETE` and answerability said `ANSWERABLE` because both reason at *requirement*
granularity ("21 CFR 312.32 has exact evidence"); neither notices that the one paragraph the
question needs was dropped. The model then invented the attribution.

Three further defects sat on the path of the same answer:

2. **Answerability.** "What is the reporting deadline for …?" (D1) was classified as asking for a
   calendar **date** (`VALUE_KINDS` maps any `\bdeadline\b` to the `date` kind, whose evidence
   pattern matches only month-day-year, dd/mm/yyyy or a bare year). "7 calendar days" is not a
   date, so the gate withheld the answer — `value_not_established` — even once `(c)(2)` was
   supplied. A correct, fully-supported answer was being refused.
3. **Evaluator abstains where it can decide.** A claim that puts `(c)(1)`'s figure on `(c)(2)`'s
   subject matter aligns to `(c)(1)` (they share "no later than N calendar days"), agrees with it
   about 15 days, and the content gate then blocks support because the claim's distinguishing
   terms ("fatal", "life", "initial", "receipt", …) belong to `(c)(2)`. The verdict became
   `undecidable`. `OP.compare` on the claim against `(c)(2)` returns
   `quantity: the answer states day ['15'] where the evidence states ['7']` — the evaluator
   stopped one step short of the source its own gate had already named.
4. **Fabrication check blind to one-digit quantities.** `_FIGURE_RE` requires `\d{2,}`, so with
   `(c)(2)` missing the invented "7-calendar-day deadline" was not reported: the evidence
   contained only the numbers `1` and `15`, and `fabrication_free` returned **pass** with
   "every figure, condition and identifier in the answer appears in the supplied evidence".

Post-processing was **not** a cause: `citation_repair` correctly declined, because D4's sentence is
a paraphrase drawing on two sources, which it excludes by design.

## Phase 2 — the fixes, and what each was measured against

| # | File | Change |
|---|---|---|
| 1 | `src/regulus/rag/selection.py`, `src/regulus/rag/pipeline.py` | Required evidence competes for the hard ceiling by relevance to the question (`_required_order`) instead of document order; the kept sources are still **presented** in document order. Engages only when every required row is a paragraph of the **same** section. |
| 2 | `src/regulus/rag/evidence_values.py` | New `deadline` value kind ahead of `date`: a deadline is established by a calendar date **or** a time period. |
| 3 | `src/regulus/accuracy/verdicts.py` | `_conflict_elsewhere`: when the content gate blocks support because the claim's distinguishing terms belong to another supplied source, compare the claim with **that** source; a **numeric** conflict there makes the claim contradicted instead of undecidable. |
| 4 | `src/regulus/rag/validation.py` | A number carrying a time unit is a figure however few digits it has; a source supplies the periods it states and the periods it spells out ("seven calendar days"). |

### Measured blast radius

**Fix 1** — `work/selection_ab.py` builds the bundle twice from the same retrieval for all 300
benchmark questions. A first, unrestricted version changed **50 of 300** contexts and caused real
regressions on part-level questions, dropping the very sections the question named (21 CFR 111.105
for "what must quality control personnel do", 111.210 for "what must the master manufacturing
record include") — because for a requested PART the registry order is already relevance-ranked by
the retriever (C1) and a cruder second ranking overrode a better one. Restricted to the
single-section case: **0 of 300 contexts change**, `chars_off == chars_on` for all 300, no ceiling
violation (max 9,000).

**Fix 2** — no benchmark question contains "deadline"; exactly one is classified `date` (M-030, a
genuine compliance date) and it is unaffected.

**Fix 3** — `scripts/accuracy_validate.py --size 120` over hand-scored acceptance rows. A first
version that accepted **any** operator conflict from the named source moved four substantively
correct or merely incomplete answers to "incorrect" — including **C-004, which the rubric scores
N=2** — and dropped Spearman ρ from 0.627 to 0.541. Restricted to numeric conflicts (quantity,
limit direction, date), because a number means the same thing read against a neighbouring
paragraph while strength and polarity do not: **0 of 120 rows change**, ρ unchanged at 0.627,
score coverage unchanged at 57.4 %.

**Fix 4** — `work/figure_ab.py` recomputes the stray-figure set for all 300 recorded acceptance
answers against evidence reconstructed from the recorded labels. A first version that counted every
digit run in a source suppressed seven findings the old rule made, one on an N=2 row. The adopted
form: **2 newly flagged, both on N=0 (substantively wrong) rows; 0 findings lost**.

## Phase 3 — tests

`tests/test_ind_safety_deadlines.py`, 19 tests, all passing. Regulatory text is verbatim snapshot
text; answers are constructed and several are deliberately wrong.

* selection: the answer-bearing paragraph is no longer dropped for the definitions; drops are still
  recorded; presentation stays in document order; both ceilings respected; **byte-identical with no
  question, with a question that has no salient terms ("Summarize 21 CFR 312.32."), with a question
  whose terms appear nowhere in the section, and whenever the evidence all fits**
* answerability: a deadline may be a period; "by what date" / "compliance date" / "effective date"
  still ask for a calendar date
* the six required answer scenarios: both deadlines correct → credited, nothing fails; the two
  reversed → `incorrect`, substantive **fail**, reason naming 7 and 15; right deadline under the
  wrong subsection → not `correct`; right citation with the wrong deadline → contradicted; a
  partially correct answer whose 15-day statement is still credited but whose reversed deadline
  fails the answer; a deadline absent from the evidence → reported unsupported, while a period the
  evidence spells out is not called invented

Suites: **2,013 passed, 1 skipped, 3 xfailed** (full unit suite); **41 passed, 1 failed**
(integration). The failure is `tests/integration/test_rag_slow.py::test_rag_end_to_end_one_question`,
asserting `len(context.text) <= 3600`; it is pre-existing and reproduces at the identical value
**4828** with Fix 1 reverted.

## End-to-end effect (same five wordings, before → after)

| | question | before | after |
|---|---|---|---|
| D1 | reporting deadline for an unexpected fatal / life-threatening reaction | FAIL 0, withheld (`value_not_established`) | **PASS 100** — "no later than 7 calendar days after the sponsor's initial receipt of the information", cited to **(c)(2)** |
| D2 | how quickly must a sponsor report … | FAIL 40 (answer already correct) | FAIL 40 (unchanged) |
| D3 | IND safety reporting **timeframes** | FAIL 75 | FAIL 15 |
| D4 | difference between the 15- and 7-calendar-day deadlines | NOT EVALUATED, **deadlines confused** | NOT EVALUATED, **answer now correct**: "the 15-calendar-day deadline applies to reports of potential serious risks, while the 7-calendar-day deadline applies to reports of unexpected fatal or life-threatening suspected adverse reactions" |
| D5 | when must a sponsor submit an IND safety report under 312.32(c) | FAIL 45, `provision_not_found` | FAIL 45 (unchanged) |

## Remaining limitations

* **D4 still cites (a).** The answer is now substantively correct but attaches one marker to a
  compound sentence whose support is split across (c)(1) and (c)(2), and picks source 1.
  `citation_repair` declines by design (paraphrase, two sources). The evaluator therefore cannot
  verify it and reports NOT EVALUATED — the claim is not credited, but the citation is not right.
  Fixing it means changing generation or the prompt, which was out of scope.
* **Lexical relevance misses synonyms.** "IND safety reporting **timeframes**" (D3) scores (c)(2)
  at 1 term and the (c)(1) family at 3, because (c)(2) says "notify FDA" rather than "IND safety
  report" and "timeframes" appears nowhere in the section. (c)(2) is still not selected for that
  wording. D3's score also moved 75 → 15: its context changed, the 0.6B model produced a longer,
  less verifiable enumeration. Both verdicts are FAIL and neither answer states the 7-day rule.
* **A separate, unfixed defect: `312.32(c)` is reported as not found** (D5). A paragraph-level
  requirement `(c)` is not satisfied by its stored children `(c)(1)`…`(c)(5)`, which are classed
  `structural`/`child`, so coverage is INCOMPLETE and the answer is refused although all of (c)
  is in the evidence. Reported, not fixed: it is a different defect in reference resolution, and a
  refusal is safe rather than wrong.
* **Relevance false negative on a correct answer.** A correct (c)(2) statement is judged
  `irrelevant` ("the regulation it corresponds to says nothing about ind/safety/report/deadlin"),
  which caps a fully correct two-deadline answer at `partial`. Pre-existing in the relevance
  module; deliberately untouched, and the regression test asserts only that nothing fails.
* Fix 1 helps only when the needed paragraph shares wording with the question. A section whose
  paragraphs all score zero keeps document order, by design.

## Evaluation ON/OFF

`scripts/accuracy_regression.py` on three questions (two deadline wordings and one unrelated
question): **exact evidence PASS, payload arm PASS, live arm PASS** — answers and citations are
byte-identical with the evaluator on and off, and the only difference in the response is the
assessment object. All five repro wordings also report
`answer_identical_when_off = citations_identical_when_off = True`.
Record: `artifacts/accuracy/regression_2026-10-12T044437Z.json`.

## Scope

The 300-question benchmark was not run; `Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx` and all
historical result artifacts are untouched. `regulus_substantive_rubric_v1` and the citation policy
are unchanged. Nothing is committed.
