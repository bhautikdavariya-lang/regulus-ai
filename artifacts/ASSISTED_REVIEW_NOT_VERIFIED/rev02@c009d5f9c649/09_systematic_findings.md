# Possible systematic problems in the benchmark key

> **ASSISTED REVIEW — NOT VERIFIED.** These are patterns observed while preparing
> proposals. They are not corrections, and nothing here has been applied to the
> workbook. Each item names the rows that show it, so an SME can check the pattern
> rather than take it on trust.

## 1. Citations stop one hop short of the governing text

**The most frequent pattern.** It accounts for most of the 44 proposed CORRECTED
rows. The cited provision itself points to an uncited section, and that section
holds one of column J's elements. Once the second pass retrieved the pointed-to
text, the element was found there.

Examples: 117.410 → 117.425, 117.155 → 117.165, 211.67(c) → 211.182,
211.137 → 201.17/211.166, 606 → 610.46/610.47, 830.320 → 830.330,
112.1(a) → 112.2, 1.1315 → 1.1320–1.1350, and 111.453–465 → 111.470
(S-025, similar in S-026 and S-027).

**Why it matters:** workbook gate G5 scores completeness ("all governing
sections surfaced"). A key that omits the governing section would score a
*correct* vendor answer as incomplete.

**Decision for the SME:** adopt a written rule on when a pointed-to section must
be in the key. Several of these rows can reasonably be accepted as drafted under
a looser rule; D-007 and D-017 are flagged that way. Apply the rule before
batch work begins.

## 2. The ISO "conflict" set is mostly a crosswalk granularity artefact

The internal crosswalk maps whole sections to one clause, taken from each
section's introductory sentence (820.35 → 4.2.5, 820.45 → 7.5.1). The benchmark
keys paragraphs, and the paragraphs name their own clauses:

- 820.35(a) names 8.2.2.
- 820.35(b) names 7.5.4.
- 820.35(c) names 7.5.1, 7.5.8 and 7.5.9.
- 820.45(b) names 4.2.5.

Of the 23 automated conflicts:

- **6 are resolved by the regulation's own text** (`T1_CFR_TEXT`).
- **5 are subclause refinements** of the crosswalk's clause, with a matching
  index title (`T2_CORROBORATED`).
- **4 are genuine disagreements** (`T3_UNRESOLVED`).
- **8 are "None" claims** (`NONE_CLAIM`).

**Recommendation:** treat the crosswalk as section-level only. Do not use it to
score paragraph-level keys.

## 3. "None" ISO keys can turn a correct answer into a G2 failure

Under the workbook's rules, an H value of `None` means that naming *any* clause
scores Q=0 **and triggers column M** (fabricated citation). G2 is absolute: one
fabrication fails the whole acceptance test.

On **M-024** (820.35(d)), the section's own introductory text frames the
paragraph as "in addition to … Clause 4.2.5". A vendor that names 4.2.5 there
would be failed as fabricating. The other 7 None rows (820.1(a)(2)–(d),
820.10(e)) are lower-risk but still need a confirmed position.

**Recommendation:** decide whether naming a real, arguably relevant clause on a
None row should count as fabrication. The current rule treats it as fabrication.

## 4. Column H omits clauses that the cited CFR text names

- **X-003:** 4.4(b)(1) enumerates 4.1, 5, 6.1, 7.3, 7.4, 7.5.3, 7.5.4, 8.2.2,
  8.4 and 8.5. The key lists 6 of these (7.3; 7.4; 7.5.3; 7.5.4; 8.5.2; 8.5.3).
- **M-029:** the cited provisions name 7.2.3, 7.3 and 8.3.3, which the key omits.
- **M-042 vs M-023:** both cite 820.35(c), which names 7.5.1, 7.5.8 and 7.5.9.
  M-023's key includes 7.5.1 and M-042's does not. **This is an internal
  inconsistency in the key.**

**Recommendation:** decide whether column H must list every clause the cited
paragraph names, or only the clauses the question reaches.

## 5. The review system cannot correct column J

A `Decision` can carry a corrected citation or a corrected ISO clause, but not
corrected answer elements. **32 rows** have a column J element that the
regulation text doesn't support, or that it contradicts. Examples:

- **S-028:** J says "date of manufacture", but 111.605(a) counts from the
  shelf-life date or from distribution of the last batch.
- **D-006:** J describes penicillin control as filtration, but 211.46(d)
  requires completely separate air-handling systems.
- **D-027:** J says "Part 310 or 314", but the text names 310.305 and 514.80.
- **E-005:** J says "all" controls apply, but 11.30 says they apply "as appropriate".
- **L-005:** J says metric declaration is mandatory, but 101.7 makes it optional.
- **S-024:** J lists "gang printing controls", which appear nowhere in the Part 111
  sections reviewed.

Column J drives G4 (substantive correctness). As things stand, an SME's only
choices for these rows are to accept an imprecise J or to reject the row.

**This is a process decision to take before sign-off, not an engineering
fix to make quietly.**

## 6. Column J contains a drafting note instead of answer elements

**X-003** ends with "SME to confirm how Part 4 cross-references read following
the February 2, 2026 restructuring of Part 820". That is an instruction to a
reviewer, not an answer element. The snapshot already answers it: 4.4(b)(1)
cites ISO clauses and 820.10/820.35 directly.

Other rows may carry similar residue.

## 7. Keys that rest on sources this project doesn't hold

- **26 rows** need FD&C Act text:
  - statute-only keys: T-011, T-012, C-001 and C-005;
  - mixed keys that include statute: T-001, T-002, T-004, P-006, L-010 and others.
- **9 rows** need the FDA guidance database. The project's `fda_guidance` table
  has 1,836 documents, but its coverage has not been assessed.
- **1 row** (D-023) rests on case law (*Barr*).

None of these rows can be verified inside the project.

**Time-dependent key:** T-011 asks for the "current status" of a rulemaking,
which can go stale between locking the key and administering the test.

## 8. Dates and wording that may predate the current rule

- **"[Reserved] as of February 2, 2026" dates:** the snapshot doesn't hold
  effective dates. Its `effective_date` field is the snapshot date on every
  record, and `federal_register_docs` is empty. The snapshot does carry
  **89 FR 82945 (Oct. 15, 2024)** alongside 89 FR 7523; the key never mentions it.
- **Possible drift from the pre-QMSR / pre-MoCRA text:**
  - **M-006:** J says refusing inspection is grounds for refusal of admission; the
    current 820.1(c) mentions only adulteration.
  - **G-009:** J uses "preparation, propagation, compounding, or processing"; the
    current 207.17(a) says "manufactures, repacks, relabels, or salvages".
  - **X-002:** J says "quality system"; the current text says QMSR.
  - **C-001:** CFR Part 710 still describes *voluntary* registration, although the
    question is about MoCRA's mandatory regime.

## 9. Citations that point at the wrong part or subpart

| Row | Key cites | What the text shows |
|---|---|---|
| **X-004** | 4.100–4.110 | Subpart B ends at 4.105 |
| **L-015** | "Subpart B of Part 101" | 102.5(d) refers to Part **102** Subpart B |
| **T-006** | Part 1114 | 1114.1(b) says the part does not apply to MRTP applications |
| **T-007** | Part 1140 ("related") | Part 1140 has no registration or listing text |
| **M-041** | 820.1(c), for "not exempt from inspection" | 820.1(c) is about refusal of imports |
| **S-004 / S-007 / S-021** | the neighbouring section | the text is in 111.10 / 111.15(e) / 111.315 |

## 10. Part-level and range citations

Several keys cite a whole part or a range, for example "21 CFR 1107",
"Part 225", "117.251 et seq." and "507.105–507.175".

Gate G1 scores citations "correct to the section/paragraph", so the SME needs to
decide how a precise vendor answer is scored against a part-level key.

## 11. Evidence-extraction defects in the eCFR snapshot

These are not key problems, but they affect packets and reviewer confidence:

- **Scrambled paragraph labels** in 111.3, 117.3, 117.5, 1.500, 1.1310, 1114.7
  (from (h)(3) on) and 1040.10(h).
- **Missing text:** the 740.10(a) warning statement is dropped at the colon.
- **Truncated title:** Part 117 Subpart G is stored as "Chain Program".
- **Very long sections:** 101.9 exceeds 80,000 characters, so its whole-section
  text is truncated.

Paragraph-level citations inside those sections should be checked against the
live eCFR.
