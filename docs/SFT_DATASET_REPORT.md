# SFT dataset for regulatory answer construction — build and audit report

Dataset construction only. No model was trained, no inference was run, no production code was
changed, and no benchmark result was modified.

```
.venv/bin/python scripts/sft_select.py           # select source questions, assemble verbatim evidence
.venv/bin/python scripts/sft_absence_checks.py   # verify the absences a false-premise answer rests on
.venv/bin/python scripts/sft_build.py            # audit, assemble, split
```

Artifacts: `artifacts/sft/train.jsonl`, `validation.jsonl`, `dataset_report.json`,
`selection.json`, `ideal_answers.jsonl`, `absence_checks.json`.

---

## 1. Totals

| | |
|---|---|
| Source questions selected | 59 (from a 150-row priority pool) |
| **Admitted to the dataset** | **57** |
| Rejected in the quality audit | 2 |
| **Train / validation** | **42 / 15** |
| Requiring SME review | 4 |
| Mean ideal-answer length | 1,903 characters |
| Examples whose answer rests on a verified absence | 17 |

## 2. Selection — why these questions

Priority went to what the measurement phases established, not to the benchmark as a whole. The pool
was Stage A's `MODEL_ANSWER` rows — the cases where **the system had the governing provision and
still answered wrongly** — plus the trap rows that need no provision, plus every Temporal/Version
row. Within a category, rows were ordered by number of key answer elements, then multi-section keys,
then whether the evidence had actually been supplied, then difficulty.

By the Stage A attribution the examples came from:

| Source population | Examples |
|---|---|
| `MODEL_ANSWER / governing_section_supplied` | 36 |
| `MODEL_ANSWER / no_governing_section_required` | 21 |

A per-CFR-part cap of 8 stops one part dominating. The cap is counted per (part, category), because
a flat cap silently excluded the whole Temporal/Version category — every temporal row in the bank is
a Part 820 reserved-section trap, and those are a structurally different question, not another
instance of the same template.

## 3. Distribution by benchmark category

| Category | Examples | In validation |
|---|---|---|
| Direct Lookup | 17 | 4 |
| Cross-Reference | 8 | 3 |
| Negative Control | 8 | 2 |
| Distinction | 7 | 2 |
| Scope/Boundary | 7 | 1 |
| Temporal/Version | 5 | 1 |
| Application | 4 | 1 |
| Abstention | 1 | 1 |

Direct Lookup is 63% of the 300-question bank but 30% here: the reasoning categories, which score
**0 passes** in the baseline, are deliberately over-weighted relative to their share of the bank.

By difficulty: Intermediate 19, Trap 18, Advanced 14, Basic 6.

By CFR part (16 parts represented): 117 (7), 820 (6), 11 (4), 111 (3), 211 (3), 803 (2), 806, 807,
801, 830, 7, 600, 606, 1003, 207, 4, 1, 210, 213 — plus 15 examples whose correct answer rests on a
verified absence rather than a provision.

## 4. Distribution by failure mode

Labels are multi-valued; totals exceed 57.

| Failure mode | Examples |
|---|---|
| incomplete_answer | 30 |
| cross_reference_reasoning | 26 |
| missing_subordinate_paragraphs | 18 |
| scope_applicability | 17 |
| wrong_provision_selection | 15 |
| evidence_faithful_interpretation | 15 |
| false_premise_handling | 15 |
| exceptions_and_conditions | 12 |
| abstention | 9 |
| distinction_reasoning | 7 |
| answer_completeness_discipline | 7 |
| temporal_version_reasoning | 6 |

All 12 labels appear in train; all 12 appear in validation.

## 5. How the ideal answers were written

One rule governs the dataset: **an ideal answer may rest only on text present in that example's own
evidence block.** The evidence is the governing section's paragraphs, read verbatim from the
read-only snapshot (877 paragraphs across the 59 records). Nothing was written from memory.

Three consequences of applying that rule honestly:

- **Where a required answer element lived in another provision, that provision was added to the
  evidence** rather than the element dropped or written from recall. Eleven examples carry such
  supporting sections, each recorded separately from the keyed sections so the addition is visible —
  for example 820.10 added to M-001, because the QMS duty the key element names sits there and not
  in 820.1; 117.165 added to F-012, because calibration, product testing and environmental
  monitoring are there.
- **A false-premise answer may only assert a negative that has been checked.** The 17 negative-control,
  scope and temporal examples carry verified-absence evidence: an actual query over the snapshot
  whose zero-row result is part of the evidence block. Asserting absence on faith is the same fault
  the dataset exists to correct. These checks also produced useful nuance — Part 111 mentions shelf
  life only conditionally ("if shelf life dating is used"), which is what makes NC-008's answer
  correct; and Part 11 addresses both biometric and non-biometric signatures at 11.200(a) and (b),
  which is what makes NC-010's answer correct.
- **Where neither the snapshot nor the guidance corpus could support an element, the example was
  rejected, not guessed.** See §7.

Answer style varies deliberately — enumerated lists where the provision enumerates, prose where it
does not, a flat one-sentence close for the abstention row, a refusal plus the provisions actually
available for the scope-boundary rows. Wording was not paraphrased in ways that change regulatory
meaning.

## 6. Quality audit

Six checks run mechanically in `scripts/sft_build.py` on every example before admission.

| Check | What it enforces | Result |
|---|---|---|
| A1 | every CFR section cited in the answer is in that example's own evidence, is one the answer correctly names as absent, or is named as a cross-reference inside the supplied text | 0 outstanding |
| A2 | every cited section exists in the snapshot — no fabricated identifiers | 0 outstanding |
| A3 | failure-mode labels from the controlled vocabulary | 0 outstanding |
| A4 | an answer is present, or the example is explicitly rejected with a reason | 2 rejections |
| A5 | evidence present unless the example is a pure scope/professional-role refusal | 0 outstanding |
| A6 | unique ids, each tracing to a real benchmark question | 0 duplicates |

**The audit caught four real defects in my own drafts, which were fixed by supplying evidence rather
than by softening the check:**

- R-006 quoted the exemptions at 806.1(b) while its evidence held only 806.10 and 806.20 → 806.1 added.
- E-010 opened from 11.1 while its evidence held only 11.10 and 11.30 → 11.1 added.
- SD-005 offered Part 7 provisions in place of a legal opinion with no evidence at all → 7.3, 7.41,
  7.46 added.
- E-010 quoted the 2003 Part 11 Scope and Application guidance verbatim, including its reference to
  211.180(c) and (d), while the guidance was not in its evidence → the guidance document, with its
  status, issue date, docket number and FDA's own disclaimer text, added as a source.

**Two miscalibrations in the audit itself were found and corrected**, which matters because both
would have silently deleted good examples: ISO 13485 clause numbers (`7.5.9.1`, `8.2.3`) were being
parsed as CFR section numbers and reported as fabricated citations — a CFR section carries exactly
one dot, an ISO clause two or more, which separates them; and reserved sections named *because they
do not exist* (820.30, 820.100, 820.198, 820.181) were reported as fabricated, which inverts the
point of every temporal and false-premise example. Before those fixes the audit rejected 15
examples and flagged 40, and the whole Temporal/Version category had disappeared.

## 7. Rejected, and referred for SME review

**Rejected (2).** Both for the same reason: the answer could not be sourced from the supplied
evidence, and writing it would have meant fabricating regulatory fact.

- **M-030** — "What changed when FDA amended Part 820 to the QMSR, and what is the compliance date?"
  The snapshot supports the structural half (six live sections; 820.5, 820.20–820.30 and 820.40
  reserved; Subparts C–O reserved; ISO 13485 incorporated at 820.7) but carries neither the 89 FR
  7523 citation nor the February 2, 2026 compliance date, and `effective_date` on these records is
  only the snapshot date.
- **PB-003** — "Give me the specific list of harmful and potentially harmful constituents." The
  requirement originates in FD&C Act section 904(a)(3) and the list is published in guidance;
  neither is in the corpus (0 guidance documents matched; the only Title 21 paragraphs using the
  phrase, 1107.12 and 1114.3, reference the concept without enumerating it). Writing ~90 named
  chemicals from memory is exactly the fabrication this dataset trains against.

Both become strong examples if the missing sources are added to the evidence corpus.

**Referred for SME review (4):** M-030 and PB-003 as above, plus two admitted examples flagged
rather than silently resolved:

- **D-023** — the Part 211 half (211.192 thorough investigation, 211.160(b) laboratory controls) is
  fully sourced, but the Barr decision framework is case law and guidance, not provision text. The
  ideal answer states the regulation and then says explicitly that it cannot set out the Barr
  two-phase structure from the supplied evidence.
- **M-034** — DMR / DHR / DHF. The answer correctly says the constructs are not in the current part
  and that 820.181, 820.184 and 820.30 have no live rows, but it declines to map the former
  definitions onto ISO 13485 clauses, because the regulation does not state that equivalence. An SME
  should decide whether the mapping should be asserted.

## 8. Train / validation split

**Leakage-free by construction, and verified.** Examples are joined into connected components by the
provisions they share, and whole components are assigned to one side. 43 components over 57
examples. The build asserts the property and reports it: **0 sections appear in both splits**, and
no source question appears in both.

The split is also stratified by benchmark category, so all eight categories and all twelve failure
modes appear in validation. An unstratified global fill put the large shared-provision components
into validation first and left only four of the eight categories represented.

Train 42 / validation 15 (26%).

## 9. Limitations — read before using this dataset

1. **57 examples is small for supervised fine-tuning.** This is a high-precision seed set built by
   hand against provision text, not a corpus. It is suitable for a LoRA pass on specific failure
   modes; it will not by itself teach general regulatory competence. The repository's existing
   mechanically-generated dataset (`data/training/datasets/training_v6.jsonl`, 4,756 train / 569
   test) is the opposite trade — large, templated, answers verbatim from the database.
2. **Single author, no second reviewer.** Every ideal answer and every failure-mode label is mine.
   There is no inter-rater agreement figure, exactly as in Stage A. The audit checks citation
   support and fabrication mechanically; it cannot check whether an answer is *regulatorily* right.
   The 15 validation examples are the ones most worth an SME pass.
3. **Answers are long** — a 1,903-character mean, and over 3,000 characters for the enumerated
   sections. That is faithful to provisions that genuinely enumerate, but it is a style the baseline
   model cannot currently produce without running to its token ceiling. Training on long answers may
   trade one failure mode (incompleteness) for another (non-termination), which is the pattern Stage
   B already observed when evidence improved.
4. **Evidence blocks are large** (up to ~19,000 characters), because they carry whole governing
   sections. They exceed the production prompt budget of 3,600 characters, so an example's evidence
   is not a thing production could currently supply. This dataset teaches answer construction given
   good evidence; it does not model the retrieval the system actually performs.
5. **The draft answer key is unverified.** 0 of 300 benchmark rows are SME-key-verified. Ideal
   answers were written against provision text rather than the key, which mitigates this, but the
   key still decided which provision counts as governing and therefore what each example selects.
6. **Three sections hit the 48-paragraph assembly cap** (606.160, 117.3, 803.3 — all long definition
   or record sections). Where a required element sat beyond the cap it was fetched individually, but
   a reviewer should confirm nothing else was truncated.
7. **No paraphrase augmentation.** Wording was not varied synthetically, because artificial
   paraphrase of regulatory text risks changing its meaning. Generalisation therefore rests on the
   genuine structural variety in the set — 16 CFR parts, eight question types, four answer shapes —
   not on volume.
8. **Guidance-tier coverage is thin.** Only one example (E-010) carries guidance text, and the two
   examples that most needed guidance (PB-003, PB-004) hit corpus gaps.

## 10. Confirmation

- **No model was trained.**
- **No inference was run.** No model was loaded at any point in these three scripts.
- **No production code was changed.** `src/regulus/` is untouched; the scripts import `Database`
  read-only and issue SELECT statements only.
- **No benchmark results were modified.** The benchmark workbook, the results workbook, the Stage A
  artifacts and the Stage B artifacts are all unchanged; the only new files are under
  `artifacts/sft/`, plus these three scripts and this report.
- **The frozen rubric was not reinterpreted**, and the span-support proxy was not used.
