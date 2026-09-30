# Benchmark-key integrity investigation (REV02, 300 questions)

This investigation runs before any SME adjudication. It decides no row and
changes no key.

- The benchmark is byte-identical: sha256 `c009d5f9c649…`, 76,773 bytes.
- 0 SME decisions and 0 sign-offs have been recorded.
- No locked key exists.
- Scoring and training are blocked.
- The only code change lets an SME **record** a column-J correction (§8). It
  applies nothing.

Machine-readable outputs are in
`artifacts/ASSISTED_REVIEW_NOT_VERIFIED/rev02@c009d5f9c649/integrity_investigation/`.
The main file is `affected_rows.csv`: 279 row-issue lines across 192 rows. The
tables were computed mechanically from the eCFR snapshot (2026-09-03), the frozen
baseline, the assisted-review proposals and the benchmark's own rubric tables,
using `tools/investigate.py` and `tools/affected_rows.py`.

Every issue is classified as follows:

| Code | Meaning |
|---|---|
| **A** | Clearly acceptable |
| **B** | Clearly requires a key correction: the eCFR text shows the key is wrong |
| **C** | Requires an SME policy decision |
| **D** | Requires an external authoritative source |
| **E** | Requires the benchmark rubric to be clarified |

"B" never means a row was corrected. The SME still decides every row, through
the review tool.

## 0. What the rubric actually says

These rubric rules are relevant here and were not used in earlier planning.
They come from the workbook's scoring-rubric and instructions tabs, as held in
the database.

- **Completeness (column O)** is scored against "all governing sections *listed
  in the answer key* … **including cross-referenced recordkeeping and general
  provisions**".
- **Citation accuracy (column L)** requires every citation given to be "correct
  to the section, and to the paragraph where the response asserts a
  paragraph-level requirement". It judges whether a citation is correct, not
  whether it matches the key.
- **ISO concordance (column Q)**: score 1 if the response names "the clause or
  clauses given in column H". On `None` rows, "naming a clause … scores 0 **and
  also triggers column M**".
- **Fabricated citation (column M)** is defined as citing "any … ISO clause …
  **that does not exist**".
- **Reserved-section rule (criterion 4)**: "score 0 if the response describes a
  section reserved **on February 2, 2026** as though it were in force". The §6
  worked example marks M-033 down for not stating that date.
- **Platform failure rule `ISO-APPROVED-MAPPING-ONLY`**: the platform names an ISO
  clause "only from the Customer-approved crosswalk". That crosswalk maps at
  **section** level.

## 1. Citations stop one step short (Finding 1)

**How many rows.**

- 252 rows cite CFR provisions. In **163** of them, the cited text
  cross-references another section of the same part that the key does not cite.
- A pointer alone is **not** a defect. In 92 of those rows, the assisted review
  found every column J element inside the cited text and accepted the key as
  drafted.
- **44 rows** have a proposed correction:
  - **37 are additive**: they keep every cited section and add one.
  - **4 are substitutive**: the key cites the wrong or neighbouring section
    (S-004 → 111.10, S-007 → 111.15(e), S-021 → 111.315, and X-004's range).
  - **2 are ISO-only** (X-003, M-029).
  - The remaining one is **L-015**, a part-level key naming the wrong subpart:
    "Subpart B of Part 101" where 102.5(d) means Part 102 Subpart B. It is
    **B**, and appears again under part-level keys in §6.
- In **10 rows**, the added section is exactly the one the cited text points to
  (the "confirmed one-hop" rows): S-012, F-002, F-012, L-003, D-017, R-006,
  C-002, U-010, Y-001 and H-006. In the other 27 additive rows, the added
  section was reached through a sibling section or the question itself.

**Defect or acceptable practice?** It depends on what the pointed-to section
contains:

| Pointed-to section | Class | Rows | Why |
|---|---|---|---|
| Recordkeeping section | **B/E** | D-007 → 211.182, S-027 → 111.570, H-002 → 1.360, T-003 → 1114.45, Y-006 → 114.100, P-010 → 812.140, F-019 → 117.320 (records availability) | Column O literally includes cross-referenced recordkeeping, so omitting it is a key defect under the rubric. |
| Section holding a J element, but not recordkeeping | **C** | The other 30 additive rows | The rubric does not say whether the key must name it. |
| Key cites the wrong section | **B** | The 4 substitutive rows | A correct answer citing the right section would be scored against the wrong one. |

**Does the rubric define the expected granularity?** Partly.

- Column L sets the granularity of a *response*: section, or paragraph when a
  paragraph-level requirement is asserted.
- Column O sets completeness against the *key's list*, and names recordkeeping
  and general provisions.
- **Nothing sets the granularity of the key itself.** The key mixes 171
  section-only citations, 27 paragraph-only citations, and part, subpart, range
  and statute forms (`xq_citation_granularity.csv`).

**Is the practice consistent?** No.

- Cross-referenced **recordkeeping** targets are cited by the key **1** time and
  omitted **19** times.
- General/scope provisions are cited 9 times and omitted 45.
- 92 pointer rows stand as drafted, while 37 need an addition.

**Could a correct answer be scored as incomplete?** Mostly **no, for column O**,
because completeness is scored against the key's own list. A fuller answer is
never short of it. The risks lie elsewhere:

- **Column L.** Where the key cites the wrong section (the 4 substitutive rows),
  a scorer who compares against column G could mark the correct citation wrong.
- **Column N.** Where a J element lives in an uncited section, a scorer may
  penalise an answer that correctly cites that section, or credit one that
  doesn't.
- **G5.** The key *under-demands*. An answer that omits the governing
  recordkeeping section still scores O=2, so the gate measures less than the
  rubric says it does.

**Policy needed:** P1 (§7).

Examples:

| Row | Key G | Points to (uncited) | Holds J element |
|---|---|---|---|
| F-012 | 117.155; 117.160 | 117.155(a)(4) → 117.165 | calibration, product testing, environmental monitoring, records review |
| D-007 | 211.67 | 211.67(c) → 211.180/211.182 | the cleaning log (recordkeeping) |
| U-010 | 830.300–830.320 | 830.320(c)(3) → 830.330 | the submission deadline |
| Y-001 | 112.1; 112.4; 112.5 | 112.1(a) → 112.2 | the "rarely consumed raw" exclusion |
| S-004 | 111.13 (supervisors) | — | hygiene is in 111.10: **wrong section** |

## 2. "None" ISO keys (Finding 2)

**Affected rows** (column H = None): M-002, M-003, M-004, M-005, M-006, M-007,
M-019 and M-024.

**Does the regulation name a clause?**

| Row | Cited paragraph | Clause named by the paragraph | Clause named by the section's introductory text | Section-level crosswalk |
|---|---|---|---|---|
| M-002–M-007 | 820.1(a)(2)–(d) | none (820.1(b) mentions "ISO 13485" only generically) | none | 1; 4.1 |
| M-019 | 820.10(e) | none | none | no mapping |
| **M-024** | 820.35(d) | none | **4.2.5**: "In addition to the requirements of Clause 4.2.5…" | 4.2.5 |

**Rubric.** On a `None` row, naming any clause gives Q=0 *and* M=1. But M is
defined as citing something that **does not exist**, and clauses 1, 4.1 and
4.2.5 exist. **The two rubric rules contradict each other (E).**

**Is None defensible?** Under the key's *own* implicit rule, yes: the key uses
the clause the cited paragraph names, and None where it names none. All eight
rows follow that rule, and the six 820.35/820.45 paragraph rows omit the
introductory clause the same way (A). **M-024 is the weakest case (C/E).** Its
section frames every paragraph as a supplement to 4.2.5, so answering "4.2.5" is
defensible, yet it would be scored as fabrication.

**Would accepting a clause incorrectly fail the test?** Under the rubric as
written, yes. One such answer on any of these rows sets M=1, and G2 is absolute.

The platform's declared rule makes this concrete. It names clauses only from the
section-level crosswalk, so it would name 1/4.1 on M-002–M-007 and 4.2.5 on
M-024: **7 G2 fabrication findings for real clauses**.

**Internally consistent?** Mostly, with one exception: **820.1(c) is keyed None
on M-006 but "1; 4.1" on M-041** (C).

**Policy needed:** P2 (§7). No key has been changed.

## 3. ISO inconsistency (Finding 3)

**The four named rows:**

| Rows | Difference | Verdict |
|---|---|---|
| **X-003** | 4.4(b)(1) enumerates 4.1, 5, 6.1, 7.3, 7.4, 7.5.3, 7.5.4, 8.2.2, 8.4 and 8.5 (plus ISO 9000 Clause 3). H lists 7.3; 7.4; 7.5.3; 7.5.4; 8.5.2; 8.5.3. The question asks *which provisions must be satisfied*. | **B/E**: H omits clauses the cited text enumerates. Whether "8.5 and its subclauses" equals "8.5.2; 8.5.3" is a naming rule. |
| **M-029** | The cited 820.10(b)(4) and (c) name 7.2.3, 8.3.3 and 7.3; H omits all three. | **B/C**, under P3 |
| **M-023 vs M-042** | Both cite 820.35(c), which names 7.5.1, 7.5.8 and 7.5.9. M-023's H includes 7.5.1; M-042's doesn't. | **C: an actual inconsistency** |

**Other same-provision clusters** (`f3_same_provision_iso.csv`):

| Rows | Difference | Verdict |
|---|---|---|
| M-006 / M-041 | 820.1(c): None vs 1; 4.1 | **C: actual inconsistency** |
| M-018 / M-029 | 820.10(d): 7.5.9.2 vs parent 7.5.9 | **E: clause naming** |
| 820.10(a) across 11 rows | 11 different H values | **A**: 820.10(a) is the generic gateway; H follows the question's subject |
| M-031 / NC-011 / NC-016 | 820.30: 7.3+subclauses vs 7.3.5 vs 7.3.10 | **A**: each follows its question (design controls / design reviews / DHF) |
| M-021 / M-033 / PB-009 | 820.35(a): all 8.2.2 | **A**: consistent |
| M-008 / M-009, M-010 / M-011 | Differ by question scope | **A** |
| 8 paragraph rows under 820.35 / 820.45 | Omit the introductory clause | **A** under the paragraph rule |

**Naming style is inconsistent (E):**

- "7.3 and its subclauses" in M-017 and M-031;
- "7.4; 7.4.1; 7.4.2; 7.4.3" in M-037;
- the subset "7.4; 7.4.1" for supplier qualification in PB-005;
- "8.5.2; 8.5.3" in X-003, where the CFR says "8.5 and its subclauses".

Q requires "the clause or clauses given in column H", so the style decides what
counts as a match.

**Structural conflict with the platform's crosswalk (C/E).** Comparing the
crosswalk-only rule with H over all 51 G7 rows:

| Outcome | Rows |
|---|---|
| **Match** | **10** |
| Crosswalk names different clauses | 14 |
| Crosswalk silent (no 820.10 mapping; 4.4 not mapped) | 13 |
| Crosswalk names a subset of H | 4 |
| Crosswalk names a superset of H | 2 |
| None row, crosswalk names a clause (G2 risk) | 7 |
| None row, crosswalk silent | 1 |

G7 needs ≥95%, which is 49 of 51. Either the crosswalk must be refined to
paragraph level, or the authority for G7 must be restated. **This is the single
largest integrity risk found**, and it is a decision for the contract owner and
the SME, not the key reviewer alone (`platform_crosswalk_vs_H.json`). It rests
on the platform's *declared* rule, not on a live run.

## 4. Column J (Finding 4): infrastructure gap, fixed (§8)

32 rows have column J wording that the regulation text does not fully support.
Examples:

- **S-028:** "date of manufacture", but 111.605(a) counts from the shelf-life
  date or from distribution of the last batch.
- **D-006:** penicillin "filtration", but 211.46(d) requires separate
  air-handling systems.
- **D-027:** "Part 310 or 314", but the text names 310.305 and 514.80.
- **E-005:** "all" closed-system controls, but 11.30 says "as appropriate".
- **G-009:** pre-2016 wording for 207.17.
- **X-003:** J contains a reviewer instruction instead of answer elements.

Before this change, an SME's only options for these rows were to accept an
imprecise J or to withdraw the row. Each row is now **C** (the SME decides the
wording). G-009 and X-003 are **B** because the snapshot text shows the key is
outdated or malformed.

## 5. Outdated or time-sensitive wording (Finding 5)

| Rows | Issue | Nature | Source that settles it | Class |
|---|---|---|---|---|
| M-030, M-031, PB-008, NC-003, NC-005, NC-011, NC-016 | State "[Reserved] as of February 2, 2026" | temporal status / wording | Federal Register **89 FR 7523** (effective/compliance date). Also check **89 FR 82945 (Oct 15, 2024)**, which the snapshot lists and the key never mentions. The snapshot's `effective_date` is only the snapshot date. | **D** |
| M-032–M-040 (9 rows) | Same reserved status, **no** date | benchmark wording | Rubric decision: is the date required in answers? The §6 example says yes. | **E** |
| C-001, C-005 (C-002 possibly) | MoCRA obligations. CFR Part 710 still says registration is voluntary ("is requested to register"). | substantive answer / citation | FD&C Act §§604–609 as added by MoCRA; FDA's current cosmetics registration and listing materials | **D** |
| M-006 | J: refusal of inspection → refusal of admission. The current 820.1(c) says only "adulterated". | substantive answer | live eCFR 820.1(c); FD&C Act §801(a) | **D** |
| G-009 | J uses superseded 207.17 wording | benchmark wording | the snapshot already shows the current text | **B** |
| X-002 | J says "device quality system requirements" (now QMSR) | wording | — | **C** |
| T-011 | "Current status" of a proposed rule | time-dependent key | Unified Agenda / Federal Register at lock date, plus a policy decision | **C/D** |
| NC-015, NC-022 | "No such guidance" (2023; March 2026) | absence claim that can go stale | FDA guidance database on the lock date | **D** |
| PB-003 | Whether the HPHC list is a guidance document or an FR notice | citation tier | FDA / Federal Register | **D** |

The scan also flagged P-001, P-007, T-005, A-001, X-001 and M-034 on
"current" / "as of" wording. On inspection, these are correct uses (for example,
T-005's "as of February 15, 2007" is the regulatory definition). **A.**

## 6. Cross-question consistency (clusters)

1. **Same provision, different expectation.** Two real conflicts: 820.1(c)
   (M-006 vs M-041) and 820.35(c) (M-023 vs M-042). Every other multi-row
   provision cluster is explained by the question's subject (§3). 40 sections are
   cited by two or more rows (`xq_same_section_clusters.csv`), and 13 of them
   are cited at mixed granularity (section in one row, paragraph in another):
   111.75, 117.5, 211.160, 820.35, 820.45, 820.30, 11.10, 812.3, 806.10, 7.3,
   1114.7, 900.12 and 4.4. Mixed granularity is harmless under column L unless a
   paragraph-level requirement is asserted.
2. **Same topic, inconsistent completeness criteria.** The recordkeeping
   asymmetry in §1: cross-referenced recordkeeping cited 1 time, omitted 19.
3. **Same ISO clause, inconsistent naming.** Subclause style, 7.5.9 vs 7.5.9.2,
   and 8.5 vs 8.5.2/8.5.3 (§3). **E.**
4. **Negative-control logic.**
   - 820.30 is labelled three ways (TEMPORAL TRAP, FALSE PREMISE, REPEALED
     PROVISION).
   - Reserved sections NC-005, NC-011 and NC-016 are scored under G3, whose
     criterion is "states that the section … does not exist", while the temporal
     rule requires "reserved".
   - NC-014 (a nonexistent *paragraph*) is labelled FALSE PREMISE, while
     nonexistent sections are labelled NO SUCH SECTION.

   **E.**
5. **Duplicates with different keys.** None. The near-duplicate pairs
   (`xq_near_duplicates.csv`, 33) are template wording across different parts, or
   the deliberate reserved-section family. **A.**
6. **Citation granularity.** Part- or subpart-level keys (F-022, L-015, P-007,
   T-005–T-008, A-004, Z-004, M-042) sit alongside paragraph keys. How a precise
   answer scores against a part-level key is undefined. **E.**
7. **Temporal rules.** The date appears in 7 of 16 reserved-section rows.
   M-030 (a Direct Lookup row) carries temporal content. The instructions say
   "ten temporal questions" but there are 11. **E.**
8. **Column-J expectations.** The reserved-section family uses one consistent J
   template, and the complaint rows are consistent. No equivalent-requirement
   pair was found with conflicting J. Individual J defects are listed under §4.

## 7. Policies requiring SME / benchmark-owner approval

Each policy can be approved or rejected independently. None has been applied.

- **P1 — Key citation completeness.** The key names the primary provision, plus
  any cross-referenced **recordkeeping and general provisions** the primary
  provision points to, as rubric O states. Other pointed-to sections are added
  only where they hold a column-J element. A correct citation that goes beyond
  the key is never an L failure. *Decides:* the 37 additive corrections and the
  consistency of the 92 pointer rows.
- **P2 — `None` ISO keys.**
  - (a) Keep None to mean "the cited paragraph names no clause".
  - (b) Amend the rubric so that naming an **existing** clause on a None row
    scores Q=0 but **not** M=1, because M is reserved for nonexistent citations
    by its own definition.
  - (c) Adjudicate M-024 individually.
  - (d) Align 820.1(c) across M-006 and M-041.
- **P3 — What H must contain.** When the cited paragraph names clauses, H lists
  every one of them. Otherwise H lists the clause(s) for the question's subject,
  from the controlled ISO 13485:2016. Section-introductory clauses are not
  required. Naming a real extra clause does not zero Q.
  *Decides:* X-003, M-029, M-023/M-042 and M-028.
- **P4 — ISO authority vs the platform crosswalk.** Before the test, state
  whether G7 is judged against the CFR text plus the controlled standard (the
  key), or against the approved crosswalk. As declared, the two disagree on 41
  of 51 G7 rows and create 7 G2 exposures. The crosswalk needs paragraph-level
  entries, or the gate definition must change.
- **P5 — Column J.** J may be corrected only through the review tool, only as
  part of a CORRECTED decision, and only with recorded evidence. J states
  regulation-supported answer elements and never reviewer notes.
- **P6 — Reserved-section date.** Decide whether answers must state "February 2,
  2026". Make all 16 reserved-section keys consistent either way, and confirm
  the date and the 89 FR 82945 amendment against the Federal Register.
- **P7 — Time-dependent and external-source keys.**
  - Keys that depend on statute text, guidance existence or rulemaking status
    are locked with the source consulted and its date recorded in the evidence
    field.
  - Rows that cannot be stabilised (T-011) are REJECTED.
- **P8 — Negative-control taxonomy.**
  - Reserved sections are "reserved", never "nonexistent".
  - The G3 criterion for NC-005, NC-011 and NC-016 accepts "reserved / false
    premise".
  - A nonexistent paragraph is treated like a nonexistent section.
- **P9 — Part-level keys.** A section-level answer inside a part cited by a
  part-level key scores L=1. Paragraph precision is required only where rubric L
  requires it.

## 8. Can the review workflow represent these decisions?

| Decision an SME may need | Supported before | Now |
|---|---|---|
| Correct the citation (G) | yes, `corrected_citation` | yes |
| Correct the ISO clause (H), including to or from None | yes, `corrected_iso_clause` | yes |
| **Correct the key answer elements (J)** | **no** | **yes** (below) |
| Withdraw a row | yes, REJECTED | yes |
| Park a row pending an external source, and record the source | yes, NEEDS_RESEARCH and `evidence_refs` | yes |
| Apply a policy to many rows | per row, citing the policy ID in the rationale | unchanged (deliberately; no batch mechanism) |
| Clarify the rubric | outside the key; record in sign-off `notes` | unchanged |
| Change question text (F), type or labels | **not supported, deliberately**: that makes a different test; use REJECTED plus a new benchmark version | unchanged |

**The change** (in `src/regulus/evaluation/key_review.py` and
`scripts/review_benchmark_key.py`):

- `Decision` gains `original_key_elements`, captured automatically from the
  workbook, and `corrected_key_elements`.
- Only a CORRECTED decision may carry a corrected J. The correction must not be
  blank, must not be identical to the original, and **must carry evidence**.
  Reviewer, rationale, timestamp and review version are already mandatory.
- The locked key keeps `original_key_elements` on every row. It adds
  `accepted_key_elements` **only for VERIFIED rows** (None otherwise), and a
  `key_elements_corrected` flag. The workbook and the baseline are never written.
- Decisions recorded before this change load unchanged (the new fields default).
- The CLI gains `--corrected-key-elements`, and prints original and corrected J.
- The review summary counts J corrections.

The following are untouched: state machine, append-only log, sign-off, gate,
baseline freezing, and the rule that a person can never assert VERIFIED.

## 9. Tests

`tests/test_key_review_column_j.py` adds 18 tests:

| Property | Tests |
|---|---|
| Original J preserved | original kept beside the correction; frozen baseline untouched; locked key carries both |
| Corrected J is versioned | a J correction in v2 does not alter v1 on disk; hashes differ |
| Correction auditable | append-only log carries reviewer, rationale, timestamp, evidence, version, original and corrected J; history survives reload |
| Unreviewed J cannot enter scoring | no locked key before sign-off and the gate refuses; a withdrawn row has no accepted J; a correction without judgments cannot be signed off |
| Historical reproducibility | a locked key rebuilds byte for byte from its record; pre-change decisions still load |
| Validation | only CORRECTED may carry J; evidence required; blank or unchanged J refused; a J-only correction is complete |
| CLI | records a J correction into an isolated key root; refuses without evidence; the workbook bytes are unchanged |

**Full suite: 790 passed, 26 deselected.** Before the change it was 772 passed;
the 26 deselected are the existing `slow` and `integration` markers.

## 10. Where things stand

| | |
|---|---|
| Benchmark | sha256 `c009d5f9c649822097b02a6c6aba415715fb0929914ef452acb03c8c3ac4a110`, 76,773 bytes, **unchanged** |
| `artifacts/benchmark_keys` | the same 3 files, byte-identical |
| SME decisions | **0** |
| Sign-offs | **0** |
| Locked key | **none** |
| Scoring | **BLOCKED** |
| Training (and Stage 6 preparation) | **BLOCKED** |
