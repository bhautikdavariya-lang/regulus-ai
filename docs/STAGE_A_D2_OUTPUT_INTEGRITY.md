# Stage A / D2 — output-integrity diagnostic

Stage A deliverable 4: does the system change or damage model output between RAW MODEL OUTPUT and
FINAL USER-FACING ANSWER, and if so, where?

Reproduce with `python3 scripts/stage_a_output_integrity.py`; figures from
`artifacts/stage_a/output_integrity.json`, per-row detail in `output_integrity_rows.jsonl`, and the
hand review in `artifacts/stage_a/d2_candidate_review.jsonl`. No production source was modified and
nothing was re-executed: the run already recorded both texts and every stage field.

**Finding in one line:** post-processing changes the text on 164 of 300 rows and removes 574
sentences, but on **0 rows did it turn an answer that would have passed into one that failed**. It is
a real defect surface, with five named defects, and it is not the cause of the baseline failure rate.

---

## 1. Method

For every row, `raw_model_output` is compared with the delivered `answer` and the difference is
attributed to the stage that caused it, from the fields the run recorded (`repair`, `fallback_type`,
`validation_initial`, `validation_final`, `stop_reason`, `model_called`).

One correction matters for every number below. The repair path calls `attach_trailing_markers`,
which moves `[n]` citation markers inside the sentence they belong to. A verbatim comparison
therefore reports a sentence as deleted when only its marker moved: that inflated the removed-sentence
count from 574 to 747 and mislabelled 33 rows as content edits. All content comparisons here are
made on marker-free text.

## 2. What changes between raw and final

| Change class | Rows | What it means |
|---|---|---|
| `none` | 117 | the delivered answer is the raw output, byte for byte |
| `edited` | 75 | sentences replaced or removed |
| `replaced_by_safe_message` | 46 | the whole draft was withheld and a canned message shown |
| `markers_only` | 33 | every word the model wrote survives; citation markers changed |
| `declined_before_model` | 19 | the pipeline declined before generation; there is no raw output |
| `appended_only` | 10 | the raw output survives in full, verbatim provision text was added |

**164 of 300 rows (54.7%) are not shown what the model produced.** All 33 `markers_only` rows are
invalid-citation stripping, not marker re-shuffling: every word survives and a citation marker that
pointed at nothing is removed. They are counted in the citation diagnostic rather than dismissed as
cosmetic, because a stripped marker changes what the answer claims to be grounded in.

Which stages fire (a row can fire several):

| Stage | Rows | Direction |
|---|---|---|
| `invented_conditions_removed` | 51 | deletes a sentence carrying a condition no source contains |
| `unvalidated_answer_withheld` | 46 | replaces the whole answer with a safe message |
| `invalid_citations_removed` | 41 | strips markers pointing at nothing |
| `mismatched_statements_replaced` | 25 | deletes a statement whose cited sources are unrelated |
| `provision_not_found` | 17 | pre-model decline |
| `appended_missing_items` | 15 | adds verbatim provision text |
| `failed_repair_fallback` | 11 | the repaired answer still failed; withheld |
| `misattributed_statements_replaced` | 3 | replaces a statement in place with its provision's text |
| `truncation_noted` | 3 | appends an incompleteness notice |

Volume: **116 rows lose at least one sentence; 574 sentences and 76,343 characters are removed in
total.** 30 rows lose a CFR identifier the raw output had named.

## 3. Was useful content removed? The decisive test

Volume is not damage. The question is whether the removed text was *right*.

The one content test that does not depend on lexical overlap: does the text name the benchmark's
governing section?

| | Rows |
|---|---|
| Governing section named in raw **and** final | 46 |
| Named in **final only** — processing *added* it | **25** |
| Named in **raw only** — processing *removed* it | **5** |
| Named in neither | 224 |

Processing supplies the governing section five times more often than it loses it. And in 224 rows —
three quarters of the benchmark — the governing section is absent from the raw output too, so no
post-processing stage can be responsible for its absence.

## 4. The bounded candidate set, and what reading it showed

A row can only be an output-processing failure if (a) the delivered answer failed, (b) processing
edited or replaced text, and (c) the **raw** text named the governing section — necessary, because
the rubric's PASS rule requires L=1 and a correct citation. That is **24 rows**. Every one was read
in full: question, key, key answer elements, raw output, removed sentences, delivered answer, rubric
notes. Judgements are recorded per row in `artifacts/stage_a/d2_candidate_review.jsonl`.

**Rows where the raw output, delivered unchanged, would have met the PASS rule: 0.**

**Rows where processing removed real substance without changing the verdict: 5.**
In the remaining 19, what was removed was the model's own invention — overwhelmingly sentences
opening "If applicable, …" that the evidence did not support — or artefact fragments (`"except"`,
`"as appropriate"`, `r1:` scaffolding). Those removals were correct.

## 5. The five real defects

Ordered by how clearly they are defects of text handling rather than of the model.

**D2-1 — whole-sentence deletion for one unsupported clause. `invented_conditions_removed`. Row U-006.**
The clearest case in the run. Question: in what form must a UDI appear on a label? The raw output
said:

> "… If applicable, the UDI must be presented in either easily readable plain-text or AIDC
> technology, or any alternative technology that provides the UDI on demand."

That sentence contains the entire key answer element — *easily readable plain text* and *AIDC
technology*. It also carries a fabricated hedge and an unsupported trailer borrowed from 801.45. The
repair deletes the whole sentence, because there is no mechanism to keep the supported clause, so
the delivered answer says the UDI "must appear in two forms" and never names them. 51 rows fire this
stage; U-006 is the one where it is demonstrably the correct answer that was deleted.

**D2-2 — the mismatch repair deletes by marker attachment, not by relevance. `mismatched_statements_replaced`. Row R-007.**
Every statement in the raw output carried marker `[1]`. The repair removed the statements naming
7.40 recall policy, 7.41 health hazard evaluation and 7.42 recall strategy — the governing sections
— and kept the off-point 7.12 guaranty and 7.55 termination lines. The surviving answer is about
guaranties against adulteration, on a question about recall classification. The selection was driven
by source attachment, which is uniform, so relevance played no part.

**D2-3 — withholding is all-or-nothing. `unvalidated_answer_withheld`. Row M-012.**
The raw output's first item was the correct answer, correctly cited:

> "1. [1] 21 CFR 820.10(a) … A manufacturer subject to this part must document a quality management
> system that complies with the applicable requirements of ISO 13485 … and other applicable
> requirements of this part."

The draft then enumerated further paragraphs, one of which misattributed 820.10(b)(3)'s text to
(b)(4). The whole draft was suppressed, so the correct governing duty never reached the user. 46 rows
are withheld; this is the one whose suppressed draft contained a correct, correctly cited statement
of the governing rule. (It would still not have passed: the misattribution is an L=0 citation error.)

**D2-4 — misattributed statements are replaced rather than re-aligned. `misattributed_statements_replaced`. Row B-001.**
The raw output's markers were shifted by one, so each accurate quotation carried the *next* section's
number. The repair replaced the misattributed statements; 600.11(a) survives and the accurate
quotations of 600.12(a), 600.13, 600.14(a) and 600.15 do not. A one-position marker shift is
detectable and in principle correctable; replacement discards four correct quotations to fix it.

**D2-5 — true content removed because retrieval did not supply it. Row H-006.**
Two removed sentences state true Part 1 content (the 2026-01-20 compliance date; the 1.1315(a)(1)
records format duty) that the supplied evidence did not contain. This is a retrieval–validation
interaction, not a text-handling fault: the validator behaved exactly as designed. Noted because the
behaviour will look like corruption in any future review that does not check the evidence package.

One further defect is visible in the raw output and therefore **not** attributable to post-processing:
generation emits `r1:` scaffolding artefacts and bare `"except"` / `"as appropriate"` tokens
(M-008, M-029, M-013, M-014, M-017). 18 rows stopped on repetition; 2 carry a truncation notice.

## 6. Answers to the questions D2 was asked to settle

- **What changed?** 164 of 300 answers. 574 sentences and 76,343 characters removed; 41 answers
  stripped of an invalid citation marker; 25 answers given a governing section the model had not
  named.
- **Which stage changed it?** Table in §2. The deleting stages are `invented_conditions_removed`
  (51), `unvalidated_answer_withheld` (46), `invalid_citations_removed` (41) and
  `mismatched_statements_replaced` (25).
- **Was useful content removed?** Yes, on 5 rows, with a named mechanism for each. On 19 of the 24
  rows where it was possible, what was removed was invented or artefactual.
- **Were citations altered?** Yes. 41 rows had invalid markers stripped; on 33 of those that was the
  only change made. Stripping rarely leaves an answer bare: just 1 of the 41 ends with no citation of
  any kind. No stage rewrites a citation to a different provision; `misattributed_statements_replaced`
  replaces the *statement* with the cited provision's own text (3 rows).
- **Did truncation occur?** Generation hit its limit or looped on 18 rows (`stop_reason=repetition`);
  the truncation notice was appended on 3. Truncation is a generation-budget effect, not a
  post-processing one — post-processing only labels it.
- **Did formatting or parsing cause the change?** No. Marker re-attachment alone accounted for 0
  rows once markers were normalised. The earlier 747-sentence figure was a measurement artefact of
  comparing marked text, not a pipeline fault.
- **Is post-processing corruption a real causal problem?** **No, not for the baseline failure rate.**
  0 of 290 failures are caused by it. It is a real quality problem on 5 rows and a real safety asset
  on 46 (every withheld draft reviewed was correctly withheld).

## 7. Recommendations — for Stage B, not now

Production is unchanged by this document, as Stage A requires. In priority order, with the evidence
each would need:

1. **Clause-level repair instead of sentence-level deletion** (D2-1). Highest value: 51 rows fire
   this stage. Would need a substantive re-score to confirm it helps rather than letting unsupported
   clauses through.
2. **Partial delivery instead of all-or-nothing withholding** (D2-3) — show the statements that
   validate, suppress the rest, label what was suppressed. Note the countervailing evidence: H4
   showed that loosening the gate let two wrong answers through. Any change here must be measured on
   substantive correctness **and** on the wrong-answer-delivery rate.
3. **Relevance-aware mismatch repair** (D2-2): when every statement shares one marker, attachment
   carries no information and the stage should decline to act rather than delete arbitrarily.
4. **Marker re-alignment before replacement** (D2-4). 3 rows; low priority.
