# Live answer accuracy

The UI's per-answer accuracy indicator: what it measures, how the number is
derived, when it refuses to produce one, and why it refuses as often as it does.

> **Status (2026-10-13).** This document describes the rubric's first version,
> `regulus_live_evidence_assessment_v1`. The evaluator now emits
> `regulus_live_evidence_assessment_v2` (version 2.0.0, frozen 2026-10-08), and
> `src/regulus/accuracy/rubric.py` is authoritative wherever the two differ. v2:
>
> * adds **question relevance** ("Answers the question") as a seventh dimension and
>   makes it absolute, like fabrication and substantive correctness: an answer to a
>   different question is a FAIL (deduction 100) however true its statements are;
> * decides substantive correctness **per claim**: a statement is borne out when it is
>   verbatim in the evidence *or* a paraphrase whose regulatory operators (strength,
>   polarity, duty-holder, quantities, dates, conditions) all agree with it, and a
>   partially borne-out answer is a decided `partial` (deduction 45). Sections 2-4
>   and 11 below describe v1, where any paraphrase was "Unable to determine", and
>   section 5's table predates both changes;
> * passes evidence support when every statement that answers the question
>   corresponds to authoritative evidence and was compared with it operator by
>   operator.
>
> The page reads each result as PASS / FAIL / NOT EVALUATED with the evaluator's own
> score out of 100 (`regulus.accuracy.review`). A v2 score is not comparable with a
> v1 score.

**Rubric id described below:** `regulus_live_evidence_assessment_v1`
**Frozen:** 2026-10-07. Any change to a dimension's decision rule, to a
deduction or to the abstention rule takes a new rubric id.
**Code:** `src/regulus/accuracy/` — `rubric.py` (the rubric as data),
`attribution.py` (verbatim attribution), `evaluator.py` (the assessment).
**Not** the acceptance rubric. `regulus_substantive_rubric_v1`
([STAGE_A_RUBRIC.md](STAGE_A_RUBRIC.md)) is contractual and is read by nothing
here; the 300-question benchmark, its scoring and its artifacts are untouched.

---

## 1. What it is for

A user asks a question, Regulus answers, and the user has no way to tell
whether the answer is right. The indicator answers a narrower question that
*can* be answered without a subject-matter expert:

> given the authoritative regulatory evidence actually retrieved for this
> question, what can be established about this answer?

It is a measurement of the delivered answer against its own evidence. It is not
a model confidence, not a retrieval score, and not a prediction of how the
answer would score on the acceptance benchmark.

## 2. Why it abstains, and why that is the design

The obvious implementation — score the answer by how much of its wording the
evidence supports — was already built, already measured, and already refuted in
this repository. [STAGE_A_VALIDATOR_LIMITATION.md](STAGE_A_VALIDATOR_LIMITATION.md)
scored two mechanical judgements against the frozen rubric over the 299 scored
rows of `acceptance_rev02_20261001T083958Z`:

| | content-recall proxy | production grounding validator |
|---|---|---|
| Calls PASS | 69 | 230 |
| Rubric PASS | 10 | 10 |
| **False passes as a share of its own passes** | **85.5%** | **97.8%** |

The mechanism is structural, not a tuning problem: *a bag of words cannot see
negation, applicability or attribution*, and applicability is what a regulatory
answer is for. §7 of that document is a standing rule — no span-support or
content-recall score may produce a verdict.

So this rubric decides a dimension only from things that are decidable:

* **identifier comparison** — does `[3]` resolve to a supplied source; is the
  section this sentence cites the section the sentence is about; does the
  section the answer names exist in the verified snapshot;
* **verbatim containment** — is this claim's wording a *contiguous* run of the
  source it is attributed to;
* **the pipeline's own structural reports** — the Stage 3 coverage report and
  the Stage 4/7 validation problems, which are themselves identity findings.

Everywhere else it returns `not_established`, and where substantive correctness
is not established it issues no percentage at all. A correct answer written as
a paraphrase therefore gets **Unable to determine**, not a number. That is the
intended behaviour and must not be "fixed" by loosening the thresholds: the
failure mode being avoided is a false pass, and abstention is the safe error.

## 3. Verbatim attribution

The one new measurement. A claim is **verbatim-attributed** to a source when
the longest contiguous run of the claim's own words that appears in that source
covers at least **80%** of the claim and is at least **6 words** long.
Normalisation is case, citation markers and punctuation only — no stemming, no
stop-word removal, no synonyms, each of which would reintroduce the blindness
being avoided.

Contiguity is the whole point. The failure phase D1's H4 arm produced, which
recall scored as a pass in both arms:

```
source   The provisions of this part do not apply to manufacturers of
         components or parts of finished devices
answer   Manufacturers of components are subject to this part

bag-of-words recall              ~1.00      -> PASS
longest contiguous verbatim run  3/8 = 38%  -> NOT attributed
```

A claim is graded `verbatim_from_exact_source` when the run is found in the
authoritative text of the provision the claim itself names (or its
parent/child, by the pipeline's own identity relation),
`verbatim_from_other_source` when it is verbatim but from something else, and
`not_verbatim_in_any_source` otherwise. Only the first grade can establish
substantive correctness: verbatim text under the wrong identifier is a citation
problem, not a correct answer.

### What verbatim attribution does **not** establish

Responsiveness. A sentence quoted verbatim from the right provision can still
fail to answer the question that was asked, and the acceptance rubric scores
that in N. Nothing here detects it. `substantive_correctness = pass` therefore
asserts exactly what the UI says it asserts — *every requirement the answer
states is stated in the regulation's own words, under the identifier the
regulation gives it* — and no more.

## 4. The six dimensions

Each is `pass`, `fail`, `partial` (completeness only), `not_established` or
`not_applicable`. Conceptual definitions are taken from
`regulus_substantive_rubric_v1` §3 where they apply; the decision rules are
this rubric's own.

| Dimension | Acceptance analogue | Decided from |
|---|---|---|
| `substantive_correctness` | N | verbatim attribution to the named provision; **fail** on an applicability contradiction, `asserted_missing_provision`, `unsupported_premise`, `paragraph_misattribution`, `invented_condition`, degenerate or empty output |
| `evidence_support` | — | verbatim attribution to any supplied source; **fail** when a material claim cites nothing and is verbatim in nothing, or validation status is `unsupported` |
| `citation_correctness` | L | `invalid_citation`, `citation_mismatch`, `provision_citation_mismatch`, `discovery_cited_for_requirement`, `paragraph_misattribution`; also **fail** when a requirement is asserted with no citation at all (rubric L: correct but uncited = 0) |
| `fabrication_free` | M | `unsupported_figure`, `asserted_missing_provision`, `invented_condition`, plus the existence in the verified snapshot of every CFR section the answer names that the evidence does not account for |
| `completeness` | O | the Stage 3 coverage report, `requirement_not_addressed`, `enumeration_incomplete`, `material_group_uncovered` |
| `scope_correct` | P | the Stage 7 scope decision, `scope_expansion`, identifiers outside Title 21, and advice / compliance-guarantee phrasing |

### The applicability contradiction

The highest-value check, and the one the refuted metrics are blind to. It fires
on three structural facts and one verbatim containment, never on a score:

1. the EXACT text of a requested provision carries an explicit exclusion
   (`do not apply to`, `are exempt from`, `is not required to`, …);
2. the excluded subject appears **verbatim** in the answer, at least three
   words of it, contiguously;
3. the answer asserts an obligation for that subject positively, with no
   negation, and nowhere repeats the exclusion itself.

(3)'s last clause is what keeps a *correct* answer — one that states the rule
and its exclusion — from being flagged.

### Where a dimension cannot decide

* `completeness` is `not_established` when the question named no provision:
  which requirements are answer-bearing is not decidable without an answer key,
  and this rubric has none.
* `fabrication_free` is `not_established` for an identifier outside Title 21:
  the corpus is Title 21 only, so *absent* is not decidable — the same
  distinction `regulus.grounding.identifiers` already draws between "verified
  absent" and "cannot be verified".
* Every dimension is `not_applicable` where the answer declines or withholds:
  there is no regulatory claim to judge.

### A cross-reference is not a fabrication

The first live run caught this as a false positive, and the guard is worth
stating. The text of 820.10 says *"in accordance with the requirements of part
830 of this chapter"*. An answer repeating that names part 830, which no
supplied source *is* — so the naive check reported an invented part and scored a
legitimate answer 0%. An identifier is therefore accounted for when a supplied
source **is** that provision, when the question **requested** it, or when a
supplied source's own text **cross-references** it; only what survives all three
reaches the identifier index, and a part is checked with `part_status`, never by
asking for section `None`. `tests/test_accuracy_evaluation.py` pins both halves:
that a cross-referenced part never reaches the index, and that an
unreferenced one is checked as a part.

### Text appended after validation

The pipeline appends the Stage 5 limitation note, the unresolved-provision
statement and the mixed-scope note to the answer *after* `validate_answer` has
run, so those sentences are the only text in a delivered answer that no
`ValidationReport` describes. They are the pipeline's own wording, not claims
about the evidence, and `_PIPELINE_SENTENCE` excludes them from the claim set —
otherwise every partial answer would show a paraphrase it never made.

## 5. The formula

```
score = max(0, 100 - sum of deductions)
```

| Dimension | fail | partial | not_established |
|---|---|---|---|
| `fabrication_free` | **100** | — | 10 |
| `substantive_correctness` | **100** | — | *no score is issued* |
| `citation_correctness` | 40 | — | 10 |
| `scope_correct` | 40 | — | 5 |
| `evidence_support` | 35 | — | 15 |
| `completeness` | 25 | 10 | 5 |

Dimensions are **not averaged**. `fabrication_free` and
`substantive_correctness` are *absolute*: a failure of either is the verdict,
not a deduction to be offset by five passes, which mirrors the acceptance
rubric where fabrication fails a row outright (gate G2 is 0, absolute) and a
PASS requires N=2. The ordering of the rest is deliberate — a right rule under
a wrong number sends the user to the wrong provision and costs four times what
a disclosed missing cross-reference costs.

`not_established` deducts a little because an unchecked dimension is not a
checked-and-good one: the score cannot reach 100 on checks that were never
actually decided.

### The abstention rule

```
not_applicable        the answer asserts no regulatory requirement
                      (declined, withheld, out of scope, no evidence)
                      -> accuracy = null
evaluated             substantive_correctness is pass or fail,
                      OR an absolute dimension failed
                      -> accuracy = the score
unable_to_determine   otherwise
                      -> accuracy = null, with the reason
```

Three things this rule exists to prevent:

* **absence becoming 0%.** No evidence, or evidence that cannot decide, yields
  `null` and a reason, never a zero.
* **uncertainty becoming 100%.** A paraphrase is `not_established`, so no
  number is issued at all.
* **a measured failure being hidden behind an abstention.** A detected
  fabrication or contradiction scores 0 with status `evaluated`, because
  something was *measured*. That is the one case where a number is issued
  without the gating dimension passing.

## 6. Architecture: the evaluator is an observer

```
Question -> Retrieval -> Evidence -> Qwen -> Post-processing / validation -> Final Answer
                                                                                 |
                                                                  Accuracy evaluation (read-only)
                                                                                 |
                                                                                UI
```

The call site is `Engine.assess` in `scripts/serve_ui.py`, **after**
`pipeline.answer()` has returned. The only change under `src/regulus/rag/` is
the evidence capture described below, which reads and never writes, and
`tests/test_accuracy_observer.py` asserts that nothing under `regulus.rag`,
`regulus.retrieval` or `regulus.planning` imports `regulus.accuracy`. The evaluator receives strings and frozen dataclasses and
returns a new object; it holds no retriever, no generator and no corpus, and it
has no code path that can rewrite, regenerate, re-cite or suppress an answer.

Everything it reads is already computed: `RagAnswer.package` (the authoritative
evidence shown to the model, with tiers and citation fields), `.validation`,
`.coverage`, `.citations`, `.answer`. It re-derives nothing — provision identity
and the parent/child relation are imported from `regulus.rag.validation` rather
than redefined, because a second definition of "the same provision" would be a
second answer to that question.

### Exact evidence: capture, fingerprint, replay

The evaluator judges an answer against the exact evidence text placed in the
model's prompt — not a rebuild of it (`regulus.traceability.evidence`).

* **Capture.** `RagPipeline.answer` snapshots `GenerationPackage.sources`
  (the post-selection, post-truncation, post-ceiling text that `render_source`
  writes into the prompt), eCFR and FDA guidance alike, into
  `RagAnswer.evidence_snapshot`. When the model was called, every captured
  text is checked to appear, in order, in the SOURCES block of the user
  message actually sent (`prompt_verified`). That block's SHA-256 is
  `prompt_sha256`. A capture failure leaves the snapshot `None` and never
  touches the answer.
* **Fingerprint.** SHA-256 over the ordered items' identity, citation,
  heading, tier, truncation flag and **text**. It is recomputed on every load,
  and a record that does not match is rejected, not used.
* **Persistence.** `serve_ui` returns the record as `evidence_snapshot`, and
  `run_acceptance_test.py` writes it to each `answers.jsonl` row beside the
  existing label list.
* **Replay and provenance.** `evaluate(..., evidence=snapshot)` uses the
  snapshot's items as the sources: provenance **`exact`**. A package without
  a snapshot (e.g. the 60-row validation, which rebuilds evidence from the
  labels in an old artifact) is labelled **`legacy_reconstructed`** and can
  never be labelled exact. With neither, the provenance is **`missing`** and
  the answer is not judged. That means "the evidence was not captured", which
  is not the same as "the answer has no supporting evidence". A captured
  package with no items is `exact` and means nothing was retrieved.
* **No second retrieval.** The evaluator reads the snapshot only. Its one
  database touchpoint is the optional identifier index, which answers whether
  a section the answer names exists (two booleans), never with text.
  `tests/test_evidence_traceability.py` enforces all of this.

**Failure isolation.** `evaluate_safely` cannot raise: any exception becomes an
assessment with status `evaluator_error`, accuracy `null`, and a sanitised
reason. The answer is already in the response dict before the evaluator is
called, so there is no path by which an evaluator failure can withhold an
answer.

## 7. Cost

No model inference, no second generation, no extra retrieval. One indexed
read-only lookup per CFR section the answer names that the evidence does not
account for, through the existing `DatabaseIdentifierIndex`; usually zero.
Synchronous, because it is cheaper than the response serialisation it precedes.

Measured over the eight-question live run
(`artifacts/accuracy/regression_2026-10-07T122745Z.json`): **2.1 ms mean, 4.1 ms
worst case, 0.5 ms best**, against a 16.9 s mean per answer — around 0.01% of
the time the answer takes. The worst case is a whole-section answer naming a
dozen provisions. `scripts/accuracy_regression.py` records
`server_timings_ms.accuracy_ms` for every question, and
`tests/test_accuracy_observer.py` fails if an assessment ever exceeds 50 ms —
the tripwire for someone adding a query, a second pass or a model.

## 8. Turning it off, and the regression that proves it

* `python scripts/serve_ui.py --no-accuracy` — server-wide.
* `{"accuracy": false}` in a `/api/ask` or `/api/ask/stream` body — per request.

With it off, the response has no `accuracy` key and is otherwise identical.

* `tests/test_accuracy_observer.py` — eight questions through the real Stage 1–7
  pipeline with scripted generations, covering a clean answer, a paraphrase, a
  repaired answer, a blocked one, a provision with no evidence and an
  out-of-scope question. Asserts the answer is equal byte for byte, that the
  citations, evidence, validation, coverage, package and metadata are equal,
  and that `{"accuracy"}` is the *only* key that differs.
* `scripts/accuracy_regression.py` — the same comparison against the real model
  and the read-only database, in two arms. The *payload* arm proves the
  response differs only by the assessment. The *live* arm answers each question
  off, on, and off again, so that a difference can be attributed to the feature
  or to nondeterministic generation rather than confused between them.

## 9. What the UI may and may not say

The indicator always carries both lines:

> Based on the authoritative regulatory evidence retrieved for this answer.
> An evidence-based assessment of this one answer. It is not the 300-question
> acceptance-test score and does not mean this answer passed that rubric.

`tests/test_accuracy_ui.py` asserts the second line is present, that
`regulus_substantive_rubric_v1` is never named on the page, that an abstention
renders as "Unable to determine" with no `0%` or `100%` anywhere, and that the
answer renders unchanged when the server sends no assessment.

## 10. What it actually returned on the first live set

Over the eight default questions of `scripts/accuracy_regression.py`, against
the base Qwen3-0.6B and the 2026-09-03 snapshot:

| Status | Rows | Why |
|---|---|---|
| `not_applicable` | 4 | the answerability gate declined before the model was called |
| `unable_to_determine` | 4 | the answers are paraphrase; 0–3 of their statements were verbatim |
| `evaluated` | **0** | — |

**No question produced a percentage.** That is the rubric working as specified
rather than failing: four answers made no regulatory claim, and the other four
were paraphrase, which identity cannot judge. The component checks still fired
on all four — citation correctness failed on three of them, because the model
emitted no `[n]` markers at all — so the panel is informative without a score.

Read this as a measurement of the *current generator*, not of the indicator. The
number appears when the answer quotes its evidence; the 0.6B model's paraphrasing
is why it does not. Raising the rate is a generation change, measured against
`regulus_substantive_rubric_v1`, not a threshold change here.

## 11. Known limits

Stated here so they are not rediscovered as surprises.

1. **Responsiveness is not checked.** See §3. A verbatim quotation of the right
   provision that does not answer the question scores 100.
2. **A paraphrase gets no score.** On fluent prose the indicator will say
   *Unable to determine* often. That is honest, and it is also the thing a
   reviewer will most want to change; changing it means a new rubric id and a
   measured justification, not a lower threshold.
3. **The thresholds are reasoned, not fitted.** 80% coverage over 6 words, and
   the deduction table, were chosen from the rubric's own severity ordering. No
   two-arm experiment has been run against hand scoring, so their *calibration*
   is unmeasured. They are reported with every finding so a reader can see what
   was required.
4. **Scope and advice detection is phrase-based** and therefore incomplete; it
   can only ever fire on the phrasings it lists.
5. **It is not a substitute for the acceptance benchmark**, and no change to
   the system may be justified by moving this number. The rule in
   [STAGE_A_VALIDATOR_LIMITATION.md](STAGE_A_VALIDATOR_LIMITATION.md) §7
   applies to this rubric as much as to the two it replaces.
