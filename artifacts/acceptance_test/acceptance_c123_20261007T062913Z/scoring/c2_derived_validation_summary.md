# Independent validation of the 66 DERIVED paragraph annotations

Read-only forensic validation of the rows in `c2_paragraph_ground_truth.csv` whose
`provenance` is `DERIVED`. No production code, configuration, benchmark, prompt,
ceiling or scoring logic was touched, no model generation was run, and the source
CSV was not modified. Per-row results: `c2_derived_validation_report.csv`.

## 0. Method and independence

- **66 of 66 received independent reconstruction.** For every case I read the
  question, the SME key and `key_answer_elements`, then read **every paragraph of
  the governing section** (ordinal, paragraph path, length, body) and decided which
  paragraph(s) a correct answer must rest on **before** looking at the annotation.
  Sections longer than 26 rows were re-read in full from the underlying record set
  so that no deep paragraph was judged from its label alone.
- Operative standard used:
  - **VALID** — the paragraph is the (or a) governing paragraph and contains the
    operative rule the question asks for; an answer built on it would be
    substantively correct.
  - **PARTIALLY_VALID** — it contains a genuine element, but an answer built on it
    alone would be substantively incomplete in a way that misses the question's point.
  - **INVALID** — lexical overlap only; not governing for any element.
  - **AMBIGUOUS** — the corpus does not contain the governing text, so no paragraph
    annotation is determinable.
- Confidence is confidence in the **verdict**, not in the annotation.

## 1. Overall counts

| Status | n | % of 66 |
|---|---|---|
| VALID | 18 | 27.3% |
| PARTIALLY_VALID | 42 | 63.6% |
| INVALID | 5 | 7.6% |
| AMBIGUOUS | 1 | 1.5% |

Confidence: VALID 15 HIGH / 3 MEDIUM; PARTIALLY_VALID 35 HIGH / 7 MEDIUM;
INVALID 5 HIGH; AMBIGUOUS 1 HIGH.

**Reported separately, as required:**

- **VALID alone: 18 / 66 = 27.3%.** These are the only cases where the annotated
  paragraph is, on its own, a sufficient basis for a correct answer.
- **"Strongly valid" (VALID + high-confidence PARTIALLY_VALID): 53 / 66 = 80.3%.**
  This is a *relevance* metric: it says the annotation points at genuinely
  answer-bearing regulatory text. It is **not** a sufficiency metric and must not
  be read as one.
- Annotations that point at genuinely answer-bearing text at all (VALID +
  PARTIALLY_VALID): **60 / 66 = 90.9%**.

## 2. What the DERIVED methodology actually measures

The annotations are **accurate about relevance and systematically wrong about
sufficiency**. In 60 of 66 cases the identified paragraph really is part of the
answer. But in only 18 cases is it the whole of the operative answer. The dominant
failure mode is a **single pick out of a multi-paragraph answer set**:

- corrected answer set needs **4 or more paragraphs**: 36 / 66 (54.5%)
- corrected answer set is **non-contiguous** within its section: 25 / 66 (37.9%)
- corrected answer **requires at least one other section**: 25 / 66 (37.9%)

Consequence: **any design tuned to "reach the annotated paragraph" is optimising
the wrong target.** Reaching it is neither necessary (S-002, F-001, F-014) nor
sufficient (42 PARTIALLY_VALID cases) for a correct answer.

## 3. Corrected position analysis

Measured against my reconstructed answer set, not the annotation. C2 currently
supplies ordinals {0, 1, 2} of a selected section (stem + `part_expand_rows = 2`).

| Where the corrected answer sits | n | % |
|---|---|---|
| Entirely within the first three rows (o0–o2) | 24 | 36.4% |
| Begins within o0–o2 but extends beyond | 36 | 54.5% |
| Entirely beyond o2 | 6 | 9.1% |

So **60 of 66 (90.9%) corrected answers begin inside C2's existing window**, and
only 6 lie wholly outside it (D-009, D-022, E-003, F-005, P-005, R-002).

### Quantified correction to the earlier position statistic

As annotated, **25 of 66 (37.9%)** DERIVED answers have `answer_min_ordinal > 2`,
i.e. appear to sit entirely outside C2's window, and 30 of 66 (45.5%) are not
fully inside it. After independent reconstruction, the share lying **entirely**
outside the window falls to **6 of 66 (9.1%)** — a correction of roughly four
times. I could not reproduce a "70% outside window" figure from this artifact; the
figures the artifact does support are the 37.9% / 45.5% above, and both are
inflated by the bias described next. **The claim "C2's window is too shallow"
is not supported in the form it was stated.**

## 4. Bias check — and it runs in both directions

**Lead-in bias (annotation points at a stem, introduction, general-applicability
statement, definition or cross-reference rather than the operative rule): 1 case of
pure lead-in, plus 6 related general-duty or wrong-topic picks.**

- **F-014 — pure lead-in, the textbook case.** The annotation is ordinal 0 of
  §117.139, the 54-character fragment *"For food with a hazard requiring a
  preventive control:"*. It states no requirement. All four elements are at
  ordinals 1–6.
- **S-012** — §111.73 is a single-row 83-character general duty ("you must determine
  whether the specifications you establish are met"). It matches element 1 verbatim
  and answers neither half of the question asked.
- **S-025** — §111.453 is the written-procedures requirement for the subpart; the
  three substantive requirements are in §§111.455, 111.465, 111.470.
- **F-019** — §117.305(g) is the Part 11 exemption. **F-020** — §117.405(a)(2) is the
  FSVP-importer exemption. Both are wrong-topic paragraphs that answer no element.
- **S-002** — the annotation is a *definition* ("Microorganisms") in a definitions
  section, while the question asks where the definitions are located.

**Reverse bias — the annotation is deeper than the true answer: 9 cases**
(F-001, F-012, F-017, F-018, F-021, S-002, S-020, S-028, Y-005). These are the
reason the as-annotated depth statistic is inflated:

- **S-002** — annotated at ordinal 9; the true answer is a single paragraph at
  **ordinal 0**, already inside C2's window.
- **F-001** — annotated at ordinals 19 / 45 / 84; the principal exemptions the
  question names (qualified facilities, seafood HACCP, juice HACCP) are at
  **ordinals 0, 1, 2**.
- **F-018** — annotated at the pre-order procedure; "the circumstances that may lead
  FDA to withdraw", the section's title subject and the question's first element,
  is at **ordinals 0–2**.
- **F-017** — annotated at two record leaves (o12, o13); the four substantive
  requirements are at **o1, o2, o3, o7**.
- **Y-005** — annotated at (b) o8; the governing records paragraph is (a) at
  **ordinal 0**. **S-028** — annotated at (b) o1; the question leads with "how long",
  which is (a) at **ordinal 0**.

## 5. V3 (DESIGN_D) relevance split — corrected

V3's reach was previously summarised as roughly 60% HIGH-confidence. Measured
against the annotations, V3 supplies the annotated paragraph in **38 / 66 = 57.6%**
of cases, which reproduces that figure. Decomposed by whether the annotation is
actually a correct answer:

| V3 outcome against the **annotated** paragraph | n | % |
|---|---|---|
| Reaches it and the annotation is VALID | 15 | 22.7% |
| Reaches it but the annotation is only PARTIALLY_VALID | 19 | 28.8% |
| Reaches it but the annotation is INVALID / AMBIGUOUS | 4 | 6.1% |
| Does not reach it | 28 | 42.4% |

Measured against the **corrected** answer set, as the task requires:

| V3 relevance | n | % |
|---|---|---|
| Genuinely reaches the answer (supplies a corrected paragraph that alone suffices) | 17 | 25.8% |
| Reaches only a partial element or a lead-in / non-sufficient paragraph | 37 | 56.1% |
| Still misses the answer entirely | 12 | 18.2% |

V3 supplies **at least one** corrected answer paragraph in 54 / 66 (81.8%) but
**fully covers** the corrected answer set in only **20 / 66 (30.3%)**.

**Correction, stated plainly: the apparent ~58–60% reach is overstated as a quality
signal by a factor of about 2.3.** The honest figure for "V3 supplies a paragraph
that by itself answers the question" is 25.8%, and for "V3 supplies the complete
answer" it is 30.3%. The 12 cases V3 still misses entirely are B-001, B-005, C-004,
D-001, D-018, E-010, F-013, F-019, F-021, P-005, R-002, R-007 — nine of which need
another section, not more depth.

## 6. Major problematic cases

1. **F-014** — annotation is a pure lead-in fragment carrying no requirement. INVALID.
2. **F-019** — §117.305(g) (Part 11 exemption) answers none of the five elements. INVALID.
3. **F-020** — §117.405(a)(2) is an exemption from the programme, annotated as a
   programme inclusion. INVALID.
4. **S-002** — annotation at ordinal 9 (a definition); the true one-paragraph answer
   is at ordinal 0. INVALID, and the single strongest piece of evidence that the
   depth diagnosis is partly an artefact of the annotation.
5. **S-025** — §111.453 is a written-procedures requirement; the three substantive
   requirements are in three other sections. INVALID.
6. **E-010** — every element is stated in the 2003 FDA Part 11 Scope and Application
   guidance, which is **not in the eCFR corpus**. AMBIGUOUS: a corpus gap, not a
   retrieval or allocation defect. No paragraph strategy can fix it.
7. **F-009** — for a three-way Distinction question the ground truth omits one of the
   three terms being distinguished (food allergen controls, (c)(2) o9) and
   substitutes a category the question does not ask about ((c)(6) "other controls").
8. **R-002** — both terms named in the question (malfunction (k) o20, serious injury
   (w) o57) are absent from the annotation, and one annotated row is the
   remedial-action definition. The true answer spans ordinals 20–57 of a 76-row section.
9. **E-003, F-007, P-005** — answers require roughly 8 to 12 paragraphs (all of
   §11.10; §117.126(b) plus seven items; eleven PMA content paragraphs). No row cap
   short of the whole section serves these.
10. **C-004** — a cross-section enumeration (§§700.11–700.35, one section per
    substance). Paragraph expansion inside the chosen section is structurally
    incapable of answering it.

## 7. Decision

**PROCEED WITH CAUTION.**

- The DERIVED annotations are not fabricated: 60 / 66 (90.9%) point at genuinely
  answer-bearing regulatory text, and 53 / 66 (80.3%) are "strongly valid" in the
  relevance sense. The set is usable as evidence.
- But only **18 / 66 (27.3%)** are sufficient answers on their own. The methodology
  is sound as a *relevance* label and unsound as a *sufficiency* label, and it was
  being read as the latter.
- **5 INVALID + 1 AMBIGUOUS (9.1%) must be corrected or excluded** before the set is
  used to score any design. F-014 is lead-in; F-019, F-020, S-002, S-025 are
  wrong-topic or general-duty picks; E-010 is ungroundable in this corpus.
- **Bias runs both ways.** Nine reverse-bias cases mean the as-annotated depth
  statistic overstates how deep the answers are. Corrected, 90.9% of answers *begin*
  inside C2's existing stem+2 window and only 9.1% lie wholly beyond it.
- Therefore the diagnosis "C2's window is too shallow" is **not supported as
  stated**. The binding constraints are **paragraph breadth within a section**
  (54.5% need 4+ paragraphs, 37.9% non-contiguous) and **cross-section coverage**
  (37.9% need another section) — not depth alone.
- **V3's apparent ~58–60% reach is overstated by roughly 2.3x** as a quality signal:
  25.8% genuine reach, 30.3% complete coverage. V3 must not be adopted on the
  strength of the reach figure.
- Nine of the twelve cases V3 still misses need a different *section*, which no
  paragraph-allocation change can supply. This caps what any C2 variant can achieve.
- Six cases (E-003, F-007, P-005, C-004, R-002, and E-010) are structurally outside
  reach of any allocation respecting the 24-source and 9,000-character ceilings.
- **Next step before any implementation:** correct the 6 bad rows, then re-score the
  V0–V6 simulation against the corrected answer *sets* rather than single annotated
  paragraphs. The existing variant ranking rests on a target now shown to be the
  wrong one.
- Nothing here justifies implementing V3, changing C2, or running the 300-question
  benchmark yet; the validation does not block continued diagnosis.
