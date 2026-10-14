# Priority 1 — question-relevant evidence selection: synonyms and cross-references

Continues `artifacts/accuracy/ind_deadline_20261012T000000Z/`, which left two recorded
limitations in evidence selection. This addresses the first and the side effect it exposes.

## Root cause addressed

**Shared wording was the only relevance signal.** `_required_order` ranked the paragraphs of a
requested section by counting the question's own terms in each. A question can name the *kind* of
value it wants without using any of the regulation's words, and then the ranking misses the answer:

> "What are the IND safety reporting **timeframes** under 21 CFR 312.32?"

"timeframes" appears nowhere in §312.32. `(c)(2)` — the 7-calendar-day rule, and the answer —
scored **1** shared word, because it says "notify FDA" rather than "IND safety report", while the
`(c)(1)` family scored **3**. `(c)(2)` lost the 9,000-character ceiling to paragraphs that did not
answer the question. Only **4 of the section's 25 paragraphs state a time period at all**, and
`(c)(2)` is one of them, so the information needed to rank it correctly was present and unused.

**A second defect, exposed by fixing the first.** Preferring period-bearing paragraphs split a
cross-referenced list: `(c)(1)`'s 15-day clock runs from a determination "under paragraph
(c)(1)(i), (c)(1)(ii), (c)(1)(iii), or (c)(1)(iv) of this section", and ranking those four against
each other on incidental word overlap kept `(ii)` and `(iii)` and dropped `(i)` and `(iv)` — half
of one list. Stating a deadline against half its conditions is how a deadline gets attached to the
wrong provision, which is the failure class the previous task fixed.

## Files changed

| File | Change |
|---|---|
| `src/regulus/rag/evidence_values.py` (+32) | `selection_value_kind()` and `_PERIOD_SYNONYMS`: the kinds the answerability gate recognises, plus the period wordings it does not act on ("timeframes", "time limits", "time periods", "timeline", "how quickly"). |
| `src/regulus/rag/selection.py` (+72/−11) | `_required_order` now ranks on `(states the value asked for, term overlap, document order)`; `_referenced_paths()` reads intra-section paragraph references, and a referenced paragraph inherits the referring paragraph's term score when a value kind was asked for. |
| `tests/test_ind_safety_deadlines.py` (+34 tests, 19 → 53) | Priority-1 section: synonyms, the gate boundary, list coherence, the reference parser, ceiling and order invariants. |

`VALUE_KINDS` itself is untouched by this task, so **the answerability gate's triggers are
unchanged**: it still withholds on exactly the wordings it withheld on before. That split is
deliberate — ranking can only reorder a competition the ceilings already force, so a wrong answer
there costs a less relevant paragraph, while a wrong answer in the gate costs a withheld answer.

## Tests

| Suite | Result |
|---|---|
| Full unit suite | **2,047 passed**, 1 skipped, 3 xfailed (was 2,013 before the 34 new tests) |
| Protected contradiction / negation / modality: content gate, contradiction scope, numeric limits, relative clause, pass integrity, claims, relevance, answer validation, answerability | **495 passed, 3 xfailed** — the three strict relative-clause xfails remain xfail, not xpass |
| Selection: evidence coverage, answer shape, generation contract, range expansion, IND deadlines | **164 passed** before the new tests; **53 passed** in the IND file after |
| Integration (`-m integration`) | 41 passed, **1 failed** — `test_rag_end_to_end_one_question`, pre-existing, asserting `len(context.text) <= 3600` and failing at the identical value **4828** that it fails at with the change reverted |

Nothing existing was removed, weakened or rewritten. The new tests use their own fixture
(`_xref_table`) so the fixture the earlier tests assert against is unchanged.

## Before/after evidence-selection differences

`work/snapshot.py` builds the bundle for the 300 frozen benchmark questions plus 15 probe and
control wordings, recording the selected citations and a SHA of the rendered context.
`work/before.json` → `work/after.json`.

* **Benchmark: 0 of 300 contexts changed.** No ceiling violation (max 9,000 characters).
* **Deadline probes: 8 of 8 improved.** `(c)(2)` now reaches the context in all eight, three of
  them newly (`timeframes`, `time limits`, `how quickly`); and the `(c)(1)(i)–(iv)` list is
  complete in all eight, where before it was a partial subset in every one.
* **Controls: 0 of 7 changed** — "Summarize", "definitions", "requires", "follow-up", record
  retention (211.180), personnel (211.25), complaints (820.198).

What the three newly-fixed wordings traded: they gained `(c)(2)`, `(c)(1)(iv)` and `(c)(1)(i)(C)`,
and lost `(b)` "Review of safety information" (a general lead-in stating no period) and `(e)`
"Disclaimer" (not a requirement).

### An unexpected difference, investigated and fixed

With the cross-reference propagation applied unconditionally, one **control** moved: "What
follow-up does 21 CFR 312.32 require after an IND safety report?" dropped `(d)(1)` — "The sponsor
must promptly investigate all safety information it receives", a core follow-up duty, 77
characters — to make room for `(c)(1)(i)` and `(c)(1)(iv)`, which are reporting conditions rather
than follow-up. Worse evidence for that question. The propagation is therefore applied **only when
a value kind was asked for**, which is the only case it repairs: the value flag ranks ahead of term
overlap and so can separate members of one list, whereas plain term overlap breaks its ties by
document order, which already keeps a list together. After gating, the control is byte-identical to
baseline and the benchmark stays at 0 of 300.

## Existing cases verified unchanged

* the 300 frozen benchmark contexts (0 changed) and the 7 control wordings (0 changed)
* every protected contradiction, negation and modality case (495 passed, 3 xfails still xfail)
* the earlier IND-deadline protections, including the four inertness cases — no question, no
  salient terms ("Summarize 21 CFR 312.32."), terms that appear nowhere in the section, and
  evidence that all fits
* the hard ceilings (24 sources, 9,000 characters) and presentation in document order, asserted
  across every probe and control wording
* `requested_value_kind` is unchanged for every wording tested, so the answerability gate withholds
  on exactly what it withheld on before

## Evaluation ON/OFF

`scripts/accuracy_regression.py` on two targeted wordings and two controls: **exact evidence PASS,
payload arm PASS, live arm PASS** — answers and citations byte-identical with the evaluator on and
off. Record: `artifacts/accuracy/regression_2026-10-12T052617Z.json`.

## Observed generation effect — NOT an accuracy claim

Four probe questions, one generation each, outside the frozen benchmark. These are single samples
on a 0.6B model and establish nothing about accuracy.

| question | live evaluation score | note |
|---|---|---|
| "IND safety reporting **timeframes**" | **15 → 55** | the only wording with a pre-change live measurement. The answer now states **both** the 15-day and the 7-day rule and reproduces the whole `(c)(1)(i)–(iv)` cross-reference |
| "How **quickly** must IND safety reports be submitted" | 75 | `(c)(2)` is now in its evidence; the model used only the 15-day rule. Evidence improved, generation did not follow |
| "What **follow-up** does 312.32 require" (control) | 75 | evidence byte-identical to baseline, so this measures generation noise, not the change |
| "personnel qualification requirements in 211.25" (control) | 100 | evidence byte-identical to baseline |

## Remaining limitations

* **Synonym handling is a fixed vocabulary, not semantics.** `_PERIOD_SYNONYMS` covers the period
  family. A question naming a different kind of value by synonym ("what spend is permitted" for an
  amount) is still ranked on shared wording alone.
* **Better evidence is not a better answer.** "How quickly …" now has `(c)(2)` in front of the
  model and still answers with the 15-day rule only. Selection can supply the paragraph; it cannot
  make the model use it.
* **The reference parser is literal.** It reads the explicit "paragraph(s) (x)(y)" form. "paragraphs
  (a) through (c)" yields the endpoints `(a)` and `(c)` but not `(b)`; a reference carried only by
  prose ("the conditions listed above") is not read; references to another section are correctly
  ignored but also not followed.
* **List coherence is confined to value questions.** A question that asks for no value and overflows
  the ceiling can still receive a partial list. That is pre-existing behaviour from the first fix,
  left alone because repairing it unconditionally was measured to produce worse evidence for
  "follow-up".
* Unchanged and still open from the previous report: the compound-sentence citation on the
  "difference between the two deadlines" wording, the over-refusal of `312.32(c)` as
  `provision_not_found`, and the relevance false negative that caps a correct two-deadline answer
  at `partial`.

## Scope

The frozen 300-question benchmark was not run; `Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx`
and all historical result artifacts are untouched. No model weights, no rubric, no citation policy.
Nothing committed. No pre-existing uncommitted work was modified: the tracked-modified file set is
the same 33 files as at task start, and the only files this task wrote are the two sources, the one
test file, and this directory.
