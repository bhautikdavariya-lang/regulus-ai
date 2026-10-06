# Benchmark-derived SFT dataset v2 — build, audit and comparison

Dataset construction only. **No model was trained, no inference was run, no production code was
changed, no retrieval behaviour or prompt was changed, and the 300-question benchmark was not
modified.**

```
.venv/bin/python scripts/sft2_select.py        # select over all 300, pack production-sized evidence
.venv/bin/python scripts/sft_absence_checks.py # verify the absences a false-premise answer rests on
.venv/bin/python scripts/sft2_build.py         # audit, assemble, split
```

Data: `artifacts/sft2/train.jsonl`, `validation.jsonl`. Metadata: `dataset_report2.json`,
`selection2.json`, `selection_log.json`, `ideal_answers2.jsonl`,
`artifacts/sft/absence_checks.json`. The v1 dataset is untouched at `artifacts/sft/`.

---

## 1. Required figures

| | |
|---|---|
| **Previous total (v1)** | **57** |
| **New total** | **152** |
| **Number added** | **95** |
| Carried from the v1 core | 57 (all of them) |
| …of which revised | 26 |
| **Number rejected** | **10** |
| **Train** | **129** |
| **Validation** | **23** (15.1%) |
| Requiring SME review | **13** (5 admitted, 8 rejected) |
| Using verified-absence evidence | **38** |
| Source rows selected | 162 |

**Evidence length:** mean **1,948**, median **2,388**, max **3,321** (`sft2-B-003`).
**Answer length:** mean **1,270**, median **1,308**, max **2,466** (`sft2-F-005`).

## 2. Category distribution

| Category | v2 | share | share of the 300-question bank |
|---|---|---|---|
| Direct Lookup | 44 | 29% | 63% |
| Negative Control | 22 | 14% | 7% |
| Distinction | 21 | 14% | 8% |
| Cross-Reference | 20 | 13% | 7% |
| Application | 18 | 12% | 7% |
| Scope/Boundary | 15 | 10% | 5% |
| Temporal/Version | 11 | 7% | 4% |
| Abstention | 1 | 1% | 0.3% |

Direct Lookup is held to 29% against 63% of the bank. Every remaining Cross-Reference,
Application, Distinction, Temporal/Version, Negative Control and Scope/Boundary question in the
benchmark was taken; Direct Lookup is the only capped category, at 32 new rows with a
per-CFR-part cap of 6.

By difficulty: Intermediate 51, Advanced 45, Trap 45, Basic 11.
By behaviour: **answer 98, abstention-or-correction 54** — a third of the set teaches the model
*not* to answer, or to correct the question.
By CFR part: **28 parts represented**. Largest are 820 (38), 117 (14), 111 (14), 211 (9), Part 1 (5),
11 (4), Part 4 (4); 28 examples carry no provision of their own and rest on verified absence instead.
By baseline attribution: EVIDENCE_SUPPLY 59, MODEL_ANSWER with the provision supplied 50,
MODEL_ANSWER needing no provision 31, UNDETERMINED 6, PASS 6.

## 3. Failure-mode distribution

| Failure mode | Examples |
|---|---|
| incomplete_answer | 82 |
| cross_reference_reasoning | 64 |
| scope_applicability | 45 |
| false_premise_handling | 41 |
| exceptions_and_conditions | 39 |
| missing_subordinate_paragraphs | 35 |
| evidence_faithful_interpretation | 35 |
| distinction_reasoning | 28 |
| wrong_provision_selection | 17 |
| abstention | 17 |
| temporal_version_reasoning | 16 |
| answer_completeness_discipline | 13 |
| citation_selection | 8 |

All thirteen labels appear in train; validation covers twelve of thirteen.

## 4. Evidence is now production-sized — the main change from v1

v1 handed whole governing sections to the model, up to **19,000 characters** against a production
prompt budget of 3,600. v2 packs a compact package instead.

| | v1 | v2 |
|---|---|---|
| Mean evidence | 5,327 chars (full sections) | **1,948** |
| Max evidence | 19,208 | **3,321** |
| In the 1,500–3,200 preferred band | — | 98 of 152 |
| Below 1,500 (short provisions) | — | 49 |
| Above 3,200 | — | 5 (all under the 3,600 production ceiling) |

The packer claims the budget in a fixed order: paragraphs the ideal answer cites, then each
section's operative stem and its applicability or exception paragraphs, then the best lexical
matches, emitted in document order. **A pinned paragraph is added regardless of the preferred
budget**, up to the production ceiling — because dropping a paragraph the answer cites would make
the answer unsupportable by its own evidence, which is the one defect packing must not introduce.

Where a question genuinely needed more provisions than a production budget can hold, the example was
**rejected rather than truncated** — see C-004 and Z-002 in §7.

## 5. Preserving the v1 core

All 57 v1 examples are carried, with provenance and audit metadata intact (`extra.in_v1_core`).
**26 were revised**, each with `revised_from_v1: true` and a `revision_note` recording why. The
reasons fall into two groups:

- **Length (16 rows).** Under the v2 standard an answer runs 400–1,200 characters. A v1 answer of
  2,000–4,200 characters is a defect against that standard, not a style preference. F-004 went from
  4,216 to 1,608; B-005 from 3,979 to 1,664; G-010 from 3,771 to 1,316; Z-004 from 3,680 to 1,304.
- **Evidence support (10 rows).** Trimming the evidence to production size exposed answers resting
  on provisions outside their own package. M-004's answer was condensed so that 820.1(b), the
  conflict rule the question turns on, would fit within the production budget; M-001 dropped a
  1271.3 reference it could not support; B-001, X-002, Z-004 and M-042 stopped citing sections their
  packed evidence does not carry.

No v1 example was discarded. The two v1 rejections (M-030, PB-003) remain rejected for the same
reasons.

## 6. Audit

Ten checks run mechanically in `scripts/sft2_build.py`; A1, A2, A3, A5, A7 and A7b reject.

| Check | What it enforces | Outstanding |
|---|---|---|
| A1 | every cited CFR section is in the example's evidence, correctly named as absent, or named as a cross-reference inside the supplied text | 0 |
| A2 | every cited section exists in the snapshot — no fabricated identifiers | 0 |
| A3 | failure-mode labels from the controlled vocabulary | 0 |
| A4 | an answer, or an explicit rejection with a reason | 10 rejections |
| A5 | evidence present unless a pure scope/role refusal | 0 |
| A6 | unique ids, traceable to a real benchmark question | 0 duplicates |
| **A7** | **every `section(paragraph)` cited is in the packed evidence, as that paragraph, a descendant, or an ancestor whose own text carries the child marker** | 0 |
| **A7b** | **every lettered-list item and citation continuation is in the packed evidence — `"21 CFR 807.87"` followed by a list containing `(d)` and `(f)`, or `"830.320(c)(1), (2)"`** | 0 |
| A8 | evidence production-sized | 5 over the preferred band, reported |
| A9 | answer concise, no visible reasoning | 88 over 1,200, reported (see §9) |

**A7 is the check that makes evidence packing safe.** It fails loudly when compaction drops a
paragraph the answer needs, and it caught real defects repeatedly during the build — L-013 citing
101.36(h) and 101.12 that the package did not carry, B-003 citing 601.2(d), Y-004 citing 108.35(d)
and (g), S-012 citing 111.87. Each was fixed by supplying the paragraph or rewording the answer,
never by relaxing the check.

### A7b, and the two maskers A7 was carrying

A7 as first written could not see two whole classes of paragraph claim, and two shortcuts inside it
silently satisfied the claims it could see. A final QA pass found P-001 asserting the content of
807.87(d) and (f) and U-010 asserting 830.320(c)(2) with none of those paragraphs in the evidence,
and A7 passed all three. Four changes, each of which makes the check stricter:

1. **Lettered-list claims (new, A7b).** An answer that writes `"...listed in 21 CFR 807.87:"` and
   then enumerates `(a)`, `(b)`, `(d)`, `(f)` makes a claim about each of those paragraphs without
   citing any of them in `section(paragraph)` form. A7 saw nothing to check. A7b resolves each list
   marker against the nearest preceding section number and requires the paragraph.
2. **Citation continuations (new, A7b).** `830.320(c)(1), (2)` and `601.2(g)(2) and (3)` name further
   paragraphs by continuing a citation rather than repeating the section. Which depth a continuation
   means is not recoverable from the text, so both readings — sibling of the leaf and absolute path —
   are offered, and the claim counts as supported if either is in the evidence.
3. **The undesignated stem no longer satisfies a paragraph claim.** A7 returned "covered" whenever
   the section's `—` stem was packed. Because almost every section is packed stem-first, that one
   line made nearly every paragraph-level claim unverifiable — it is precisely why P-001 passed. A
   statement that names only the section is still covered by A1.
4. **An ancestor must carry the child.** A7 accepted a claim about `(c)(2)` whenever `(c)` was
   packed. In this corpus a parent paragraph is usually a bare heading with its children in separate
   rows — `830.320(c)` is `"Waiver"`, `108.35(c)` is `"Registration and process filing—"` — so the
   ancestor shortcut was accepting claims with no supporting text at all. An ancestor now counts only
   when its own text contains the remaining marker inline.

The same reasoning produced one deliberate **relaxation**, which is A1's existing carve-out moved
down a level: where the section's own supplied text names the paragraph as a cross-reference —
117.430(a) reads *"Except as provided by paragraph (c), (d), or (e) of this section"* — an answer
that says (d) and (e) provide exceptions rests on text that was supplied. Without this, F-021 was a
false positive.

**Verified by reversion.** With the P-001 and U-010 evidence pins removed, the audit rejects exactly
those two rows, naming `807.87(d)`, `807.87(f)` and `830.320(c)(2)`, and no other row changes
verdict. Restoring the pins reproduces `train.jsonl` and `validation.jsonl` byte-for-byte.

### What the extended check then found

Run across all 152, A7b found **six further unsupported paragraph-level claims that A7 had never
been able to see**. Four were repaired by supplying the paragraph, each measured against the
3,600-character production ceiling first; two could not be, because the paragraph does not fit, and
were repaired by removing the claim.

| Example | Unsupported claim | Resolution |
|---|---|---|
| B-001 | 600.10(c) — the personnel restrictions the answer states | 600.10(c), (c)(1), (c)(2) supplied (+420 → 3,144) |
| F-004 | 117.35(e) — non-food-contact surfaces | 117.35(e) supplied (+315 → 3,037) |
| R-007 | 7.41(b) — the recall classification step | 7.41(b) supplied (+262 → 3,123) |
| S-012 | 111.75(d)(2) — quality-control approval of the exemption | 111.75(d)(2) supplied (+141; paragraph budget 3,067) |
| Y-004 | 108.35(c)(2) — the process-filing obligation | **cannot fit**: (c)(1) is 1,987 characters and (c)(2) is 2,060, so the pair is 4,047. Claim removed; answer now states that the filing paragraph was not supplied. Flagged for SME — the key element *"scheduled processes filed before packing"* is only partly covered |
| B-003 | 601.2(g)(3) and (g)(4) — master-file incorporation by reference | **cannot fit**: the restriction actually sits in (g)(1), and (a) 2,713 + (c)(1) 591 + (g)(1) 677 = 3,981. Attributing the prohibition to the packed (g)(2) would have been a mis-citation, since (g)(2) is an exception. Paragraph removed; no key element affected, all of them sit in 601.2(a) |

P-001 needed one further step. Its answer enumerates 807.87(a) through (h) as a list, so the
automatic pin derivation — which reads `section(paragraph)` citations — had never seen those
paragraphs, and each time (d), (f) and (g) were pinned the lexical fill evicted a different one of
them. All eight are now pinned explicitly; together they are 2,068 characters, and the row's
rendered evidence *fell* from 3,013 to 2,860.

**Four audit miscalibrations were found and corrected**, each of which was silently deleting good
examples:

1. **ISO clause numbers read as CFR sections.** `Clause 7.5.9.1` and `8.2.3` parsed as fabricated
   citations. A CFR section carries exactly one dot, an ISO clause two or more — that separates them.
2. **Reserved sections read as fabricated.** 820.30, 820.100, 820.198 and 820.181 are named by the
   temporal examples *because they do not exist*; flagging them inverts the point of the example.
3. **A measurement read as a citation.** "121.5 degrees C maintained for 20 minutes" in 606.11(b)
   was parsed as 21 CFR 121.5.
4. **Another CFR title read as Title 21.** A scope refusal names "29 CFR 1910.1200" precisely in
   order to place it outside Title 21; that is not a fabricated Title 21 section.

**Two packing bugs were also found and fixed.** A definitions section gives every row the same
undesignated paragraph path, so de-duplicating by path collapsed them into one key and then kept all
of them — 117.3 packed 48 definitions and 16,446 characters that way; position is the stable
identity. And a flat sort of pinned paragraphs starved short sections: every pin of 606.100 and
606.160 was taken before the first pin of 606.20, so the answer lost support for the section it
cited last. Pins are now taken round-robin across sections.

## 7. Selection and rejection log

Full per-row log in `artifacts/sft2/selection_log.json`. 10 rejections, all for the same underlying
reason — **the answer could not be sourced from the supplied evidence** — in three groups:

**Requirement originates outside the CFR snapshot (5):** M-030 (QMSR compliance date and 89 FR 7523),
PB-003 (HPHC analyte list, in guidance absent from the corpus), PB-002 (HPHC data requirement),
T-001 (section 910(b) of the Act), L-012 (qualified health claim standard, an enforcement-discretion
construct in guidance).

**More provisions than a production evidence budget can hold (3):** C-004 (eight prohibited-ingredient
sections across 700.11–700.35; packing carried three), Z-002 (five mammography QA subjects across
separate Part 900 sections), K-010 (significant-risk definition at 812.3(m) plus IDE contents at
812.20). Each is recommended for splitting into narrower questions.

**Not selected rather than rejected:** Direct Lookup rows beyond the 32-row target or past the
per-part cap of 6, each logged with its reason.

**11 examples referred for SME review**, including three admitted ones that state their own limit
rather than guessing: D-023 (the Barr framework is case law, and the answer says so explicitly),
M-034 (declines to map DMR/DHR/DHF onto ISO clauses because the regulation does not state the
equivalence), X-003 (Part 4's cross-references predate the February 2026 Part 820 restructuring).

## 8. Train / validation split

**Leakage-free by construction and verified.** Examples are joined into connected components by the
provisions they share — 103 components over 152 examples — and whole components are assigned to one
side. The build asserts and reports: **0 sections and 0 source questions appear in both splits.**

The split is stratified by category, so validation covers **all eight categories** (Direct Lookup 8,
Negative Control 3, Cross-Reference 3, Distinction 3, Application 2, Scope/Boundary 2, Abstention 1,
Temporal/Version 1) and twelve of thirteen failure modes. 23 of 152 is 15.1%, inside the 15–20%
target.

## 9. Limitations

1. **Answer length misses its own target on 88 of 152 examples.** Mean 1,270, median 1,308 against a
   400–1,200 target; 41 sit at 1,201–1,500, 41 at 1,501–2,000 and 6 above 2,000. Most are genuine
   enumerations — a section with nine lettered paragraphs cannot be stated completely in 1,200
   characters without dropping paragraphs, which is the failure the dataset exists to correct — but
   this is a real deviation from the brief and not all 88 are unavoidable. A further editing pass
   could bring the 1,201–1,500 band down; the 6 over 2,000 (F-005, S-011, K-005, D-016, G-009, K-003)
   should be reviewed first.
2. **Still a seed set.** 152 hand-built examples is a targeted corrective, not a general-competence
   corpus.
3. **Single author, no second reviewer.** Every answer and every label is mine; there is no
   inter-rater agreement figure. The audit checks citation support and fabrication mechanically; it
   cannot check that an answer is *regulatorily* right. The 23 validation examples are the ones most
   worth an SME pass.
4. **Evidence is realistic in size but not in composition.** The packages are production-sized, and
   each contains the governing provision — which is precisely what production fails to supply on
   43% of its failures. So the dataset teaches answer construction given *good* evidence; it does not
   model the retrieval the system actually performs.
5. **Concentration remains, and Part 820 is the outlier.** Parts 820, 117 and 111 account for
   **66 of 152, with Part 820 alone at 38 (25%)**. The per-CFR-part cap of 6 applies only to the new
   Direct Lookup slice, so it does not restrain the reasoning categories - and Part 820 supplies most
   of the benchmark's Temporal/Version traps, its QMSR cross-references and much of its Distinction
   set, all of which were taken in full by design. A future pass should either cap Part 820 across
   all categories or add reasoning examples from other parts to balance it.
6. **The draft answer key is unverified** (0 of 300 rows SME-key-verified). Answers were written
   against provision text, which mitigates this, but the key still decided which provision counts as
   governing.
7. **Guidance-tier coverage is thin.** Only one example (E-010) carries guidance text, and the three
   rows that most needed guidance were rejected for corpus gaps.
8. **No paraphrase augmentation**, deliberately: artificial paraphrase of regulatory text risks
   changing its meaning. Generalisation rests on genuine structural variety — 28 CFR parts, eight
   question types, answer and abstention behaviours — not on volume.

## 10. On `training_v6.jsonl`

**Not merged, and none of it recommended for merging as-is.** The existing dataset
(`data/training/datasets/training_v6.jsonl`, 4,756 train / 569 test) is mechanically generated: its
answers are verbatim database text inside a fixed template. That makes it leakage-safe and
large-scale, but it cannot teach the failure modes measured here, for three reasons: a template
answer cannot demonstrate selecting between competing provisions, it cannot demonstrate correcting a
false premise (its abstention examples abstain on *unrecorded data*, not on a premise that is wrong),
and a model trained on templates learns the template.

One subset is worth a separate look rather than a merge: its `abstention` category, which teaches
refusal when the database does not record an attribute. That behaviour is adjacent to this dataset's
abstention examples and is not in conflict with them. It should be evaluated on its own before being
combined, and if used it should stay identifiable as a separate source — this dataset's
`generator` field is `sft/hand_authored/v2` throughout, so the benchmark-derived set remains
distinguishable in any mixture.

## 11. Confirmation

- **No model was trained.** **No inference was run** — no model was loaded at any point.
- **No production code was changed**; `src/regulus/` is untouched and database access is SELECT-only.
- **No retrieval behaviour and no prompt was changed.**
- **The 300-question benchmark was not modified**, nor were the Stage A/Stage B artifacts, the
  results workbook, the frozen rubric, or the v1 dataset.
- **No chain-of-thought is used as a training target.** A9 scans for visible reasoning; the target is
  the answer only.
- **No regulatory evidence was fabricated.** Every statement rests on provision text in that
  example's own evidence block, and every asserted absence rests on a snapshot query.
