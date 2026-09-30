# ISO 13485 conflict packet

> **ASSISTED REVIEW — NOT VERIFIED. These are proposals produced with AI assistance for a human SME. They are NOT SME decisions, are NOT recorded in the authoritative review store, and must NEVER be consumed by scoring or training.**


## Ground rules

* **No ISO 13485 text is held in this system** (`iso_clauses.body_text` is empty for all 88 clauses). No clause text was consulted or reproduced. Clauses are identified by number and title only.
* The **internal crosswalk** (189 rows, 87 sections) is a project artefact at **section** granularity. It is evidence of an internal position, **not authority**, and it never outranks the controlled standard.
* The **eCFR text itself** frequently names ISO clauses at **paragraph** level (820.10(b)–(d), 820.35(a)–(c), 820.45(b)–(c), 4.4(b)(1), 820.3(b)). Where it does, that is regulation text (a US Government work) and settles which clause the regulation invokes; the controlled copy is then needed only to confirm the title.
* **Workbook rule to keep in view:** a column H of `None` means naming *any* clause scores Q=0 **and triggers column M (fabricated citation)** — a G2 zero-tolerance failure.

## Evidence tiers

| Tier | Meaning | Proposal policy |
|---|---|---|
| `T1_CFR_TEXT` | the cited CFR paragraph names the draft clause | may be ACCEPTED; controlled copy optional (title check) |
| `T2_CORROBORATED` | crosswalk maps the section to the same clause or its parent; index title matches | ACCEPTED at MEDIUM, **controlled copy required** before recording |
| `T3_UNRESOLVED` | draft names a clause the crosswalk does not, CFR silent | NEEDS_RESEARCH |
| `NONE_CLAIM` | draft says no clause; crosswalk maps the section | NEEDS_RESEARCH (policy + controlled copy) |
| `RANGE` | whole standard / clause range | decided on the CFR text; scoring convention to confirm |

## The 23 automated ISO conflicts at a glance

| Row | Draft H | Crosswalk (section level) | Clauses named in cited CFR text | Tier | Proposed |
|---|---|---|---|---|---|
| M-002 | None | 820.1 -> 1, 4.1 (section level) | — | NONE_CLAIM | NEEDS_RESEARCH |
| M-003 | None | 820.1 -> 1, 4.1 (section level) | — | NONE_CLAIM | NEEDS_RESEARCH |
| M-004 | None | 820.1 -> 1, 4.1 (section level) | — | NONE_CLAIM | NEEDS_RESEARCH |
| M-005 | None | 820.1 -> 1, 4.1 (section level) | — | NONE_CLAIM | NEEDS_RESEARCH |
| M-006 | None | 820.1 -> 1, 4.1 (section level) | — | NONE_CLAIM | NEEDS_RESEARCH |
| M-007 | None | 820.1 -> 1, 4.1 (section level) | — | NONE_CLAIM | NEEDS_RESEARCH |
| M-019 | None | 820.10 -> no mapping | — | NONE_CLAIM | NEEDS_RESEARCH |
| M-021 | 8.2.2 | 820.35 -> 4.2.5 (section level, from the introductory text) | 8.2.2 | T1_CFR_TEXT | ACCEPTED |
| M-022 | 7.5.4 | 820.35 -> 4.2.5 (section level, from the introductory text) | 7.5.4 | T1_CFR_TEXT | ACCEPTED |
| M-023 | 7.5.1; 7.5.8; 7.5.9 | 820.35 -> 4.2.5 (section level, from the introductory text) | 7.5.1, 7.5.8, 7.5.9 | T1_CFR_TEXT | ACCEPTED |
| M-024 | None | 820.35 -> 4.2.5 (section level, from the introductory text) | 4.2.5 (section intro) | NONE_CLAIM | NEEDS_RESEARCH |
| M-027 | 4.2.5 | 820.45 -> 7.5.1 (section level, from the introductory text) | 4.2.5 | T1_CFR_TEXT | ACCEPTED |
| M-028 | 4.2.3; 4.2.5 | 820.45 -> 7.5.1 (section level, from the introductory text) | 4.2.5 | T3_UNRESOLVED | NEEDS_RESEARCH |
| M-029 | 4.2.5; 7.5.1; 7.5.4; 7.5.8; 7.5.9; 8.2.2; 8.2.3 | 820.10 -> none; 820.35 -> 4.2.5; 820.45 -> 7.5.1 | 7.5.8, 7.5.9.1, 8.2.3, 7.2.3, 8.3.3, 7.3, 7.5.9.2, 4.2.5, 8.2.2, 7.5.4, 7.5.1, 7.5.9 | T1_CFR_TEXT | CORRECTED |
| M-034 | 4.2.3; 4.2.5; 7.3.10 | 820.181 -> 4.2.3; 820.184 -> 4.2.5, 7.5.1; 820.30 -> 7.3 | — | T2_CORROBORATED | ACCEPTED |
| M-037 | 7.4; 7.4.1; 7.4.2; 7.4.3 | 820.50 -> 7.4 | — | T2_CORROBORATED | ACCEPTED |
| M-038 | 7.5.6; 7.5.7 | 820.75 -> 7.5.6 | — | T3_UNRESOLVED | NEEDS_RESEARCH |
| M-040 | 8.1; 8.2.6; 8.4 | 820.250 -> 8.1, 8.2.5, 8.4 | — | T3_UNRESOLVED | NEEDS_RESEARCH |
| M-042 | 7.5.8; 7.5.9 | 820.35 -> 4.2.5 | 7.5.8, 7.5.1, 7.5.9 | T3_UNRESOLVED | NEEDS_RESEARCH |
| PB-009 | 8.2.2 | 820.35 -> 4.2.5 (section level, from the introductory text) | 8.2.2 | T1_CFR_TEXT | CORRECTED |
| NC-005 | 5.6.1 | 820.20 -> 5 | — | T2_CORROBORATED | NEEDS_RESEARCH |
| NC-011 | 7.3.5 | 820.30 -> 7.3 | — | T2_CORROBORATED | NEEDS_RESEARCH |
| NC-016 | 7.3.10 | 820.30 -> 7.3 | — | T2_CORROBORATED | ACCEPTED |

Tier counts among the 23: {'NONE_CLAIM': 8, 'T1_CFR_TEXT': 6, 'T3_UNRESOLVED': 4, 'T2_CORROBORATED': 5}

**Reading.** The conflict set is dominated by one mechanism: the crosswalk assigns 820.35 → 4.2.5 and 820.45 → 7.5.1 for the whole section (from each section's introductory sentence), while the benchmark keys paragraphs. Where the paragraph names its own clause, the draft matches the regulation and the crosswalk is simply coarser. The genuinely open items are the eight `None` rows, sibling-clause disagreements (M-038 7.5.7; M-040 8.2.6 vs 8.2.5), M-028's 4.2.3, M-042's omitted 7.5.1 (inconsistent with M-023), and NC-005/NC-011, whose negative claims reach into the standard's text.

## Row detail — the 23 conflicts

### M-002 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Distinction · Medical Devices — 21 CFR 820 / QMSR*

**Question.** Are manufacturers of components and parts of finished devices subject to 21 CFR Part 820?

**Draft key G.** 21 CFR 820.1(a)(2)  
**Draft ISO H.** None  
**Key elements J.** Component and part manufacturers are outside the scope; FDA encourages voluntary application.

**Rationale.** CFR elements: all supported from 820.1(a)(2). The row is held at NEEDS_RESEARCH only because of the ISO key: column H = None, while the internal crosswalk maps the whole of 820.1 to clauses 1 and 4.1. The cited paragraph names no clause. Lean: ACCEPTED.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Component and part manufacturers are outside the scope · `820.1(a)(2)` — “The provisions of this part do not apply to manufacturers of components or parts of finished devices”
  - **SUPPORTED** · FDA encourages voluntary application · `820.1(a)(2)` — “such manufacturers are encouraged to consider provisions of this regulation as appropriate”

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `none` · internal crosswalk: `820.1 -> 1, 4.1 (section level)`  
Section-level crosswalk vs paragraph-level 'None'. Under the workbook rule, naming any clause on a None row scores Q=0 AND triggers column M (fabricated citation, G2 zero tolerance). Confirm the answer genuinely reaches no clause before accepting None.

**What the SME must establish:**
1. Controlled-source + scoring-policy decision: does an answer to this paragraph-level question reach ISO 13485 Clause 1 (Scope) or 4.1? If yes, H should name it; if no, accept None.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-003 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Distinction · Medical Devices — 21 CFR 820 / QMSR*

**Question.** Are manufacturers of blood and blood components subject to 21 CFR Part 820?

**Draft key G.** 21 CFR 820.1(a)(3); cross-ref 21 CFR Parts 606 and 640  
**Draft ISO H.** None  
**Key elements J.** Blood and blood components are excluded from Part 820; those manufacturers are subject to Part 606.

**Rationale.** CFR elements: see element notes from 820.1(a)(3). The row is held at NEEDS_RESEARCH only because of the ISO key: column H = None, while the internal crosswalk maps the whole of 820.1 to clauses 1 and 4.1. The cited paragraph names no clause. Lean: ACCEPTED.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Blood and blood components are excluded from Part 820 · `820.1(a)(3)` — “The provisions of this part do not apply to manufacturers of blood and blood components used for transfusion or for further manufacturing.”
  - **PARTIALLY_SUPPORTED** · those manufacturers are subject to Part 606 · `820.1(a)(3)` — “Such manufacturers are subject to subchapter F of this chapter.” _(The text routes them to subchapter F as a whole; J names Part 606 only (G also names 640).)_

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `none` · internal crosswalk: `820.1 -> 1, 4.1 (section level)`  
Section-level crosswalk vs paragraph-level 'None'. Under the workbook rule, naming any clause on a None row scores Q=0 AND triggers column M (fabricated citation, G2 zero tolerance). Confirm the answer genuinely reaches no clause before accepting None.

**Column J issue.** J narrows 'subchapter F' to Part 606.

**What the SME must establish:**
1. Controlled-source + scoring-policy decision: does an answer to this paragraph-level question reach ISO 13485 Clause 1 (Scope) or 4.1? If yes, H should name it; if no, accept None.
1. Decide whether J's 'Part 606' is acceptable given the text routes to subchapter F.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH); column J not fully supported by text

---

### M-004 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Cross-Reference · Medical Devices — 21 CFR 820 / QMSR*

**Question.** Are human cells, tissues, and cellular and tissue-based products regulated as devices subject to Part 820, and what else applies to them?

**Draft key G.** 21 CFR 820.1(a)(4); cross-ref 21 CFR Part 1271  
**Draft ISO H.** None  
**Key elements J.** HCT/Ps regulated as devices are in scope of Part 820 and are also subject to Part 1271; the specifically applicable regulation supersedes the more general one.

**Rationale.** CFR elements: all supported from 820.1(a)(4). The row is held at NEEDS_RESEARCH only because of the ISO key: column H = None, while the internal crosswalk maps the whole of 820.1 to clauses 1 and 4.1. The cited paragraph names no clause. Lean: ACCEPTED.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · HCT/Ps regulated as devices are in scope and also subject to Part 1271 · `820.1(a)(4)` — “HCT/Ps regulated as devices are also subject to the donor-eligibility requirements set forth in part 1271, subpart C”
  - **SUPPORTED** · the specifically applicable regulation supersedes the more general one · `820.1(a)(4)` — “the regulation specifically applicable to the device in question shall supersede the more general regulation”

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `none` · internal crosswalk: `820.1 -> 1, 4.1 (section level)`  
Section-level crosswalk vs paragraph-level 'None'. Under the workbook rule, naming any clause on a None row scores Q=0 AND triggers column M (fabricated citation, G2 zero tolerance). Confirm the answer genuinely reaches no clause before accepting None.

**What the SME must establish:**
1. Controlled-source + scoring-policy decision: does an answer to this paragraph-level question reach ISO 13485 Clause 1 (Scope) or 4.1? If yes, H should name it; if no, accept None.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-005 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Application · Medical Devices — 21 CFR 820 / QMSR*

**Question.** If a requirement of ISO 13485 conflicts with the Federal Food, Drug, and Cosmetic Act or another FDA regulation, which one governs?

**Draft key G.** 21 CFR 820.1(b)  
**Draft ISO H.** None  
**Key elements J.** Conflicts provision: the FD&C Act and the applicable FDA regulations govern over the incorporated standard.

**Rationale.** CFR elements: all supported from 820.1(b). The row is held at NEEDS_RESEARCH only because of the ISO key: column H = None, while the internal crosswalk maps the whole of 820.1 to clauses 1 and 4.1. The cited paragraph names no clause. Lean: ACCEPTED (weaker: the paragraph speaks of ISO clauses generally).

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · the FD&C Act and applicable FDA regulations govern over the incorporated standard · `820.1(b)` — “the Federal Food, Drug, and Cosmetic Act and/or its other implementing regulations will control”

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `none` · internal crosswalk: `820.1 -> 1, 4.1 (section level)`  
Section-level crosswalk vs paragraph-level 'None'. Under the workbook rule, naming any clause on a None row scores Q=0 AND triggers column M (fabricated citation, G2 zero tolerance). Confirm the answer genuinely reaches no clause before accepting None.

**What the SME must establish:**
1. Controlled-source + scoring-policy decision: does an answer to this paragraph-level question reach ISO 13485 Clause 1 (Scope) or 4.1? If yes, H should name it; if no, accept None.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-006 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Direct Lookup · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What does Part 820 provide with respect to foreign manufacturers that refuse to permit an FDA inspection?

**Draft key G.** 21 CFR 820.1(c); section 801(a) of the FD&C Act  
**Draft ISO H.** None  
**Key elements J.** Refusal to permit inspection is grounds for refusal of admission of the device into the United States.

**Rationale.** CFR elements: see element notes from 820.1(c). The row is held at NEEDS_RESEARCH only because of the ISO key: column H = None, while the internal crosswalk maps the whole of 820.1 to clauses 1 and 4.1. The cited paragraph names no clause. Lean: NEEDS J CHECK.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **NOT_FOUND_IN_EVIDENCE** · Refusal to permit inspection is grounds for refusal of admission · `820.1(c)` — “is subject to refusal of admission to the United States under section 801(a) of the Federal Food, Drug, and Cosmetic Act if, among other things, it appears to be adulterated” _(The snapshot's 820.1(c) says nothing about refusing inspection. The inspection element may come from the statute (801(a)) or from the pre-QMSR text; neither is in evidence.)_

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `none` · internal crosswalk: `820.1 -> 1, 4.1 (section level)`  
Section-level crosswalk vs paragraph-level 'None'. Under the workbook rule, naming any clause on a None row scores Q=0 AND triggers column M (fabricated citation, G2 zero tolerance). Confirm the answer genuinely reaches no clause before accepting None.

**Column J issue.** J asserts refusal of inspection as the ground; the snapshot 820.1(c) text does not mention inspection.

**What the SME must establish:**
1. Controlled-source + scoring-policy decision: does an answer to this paragraph-level question reach ISO 13485 Clause 1 (Scope) or 4.1? If yes, H should name it; if no, accept None.
1. Confirm what 820.1(c) says in the live eCFR and whether the 'refuses inspection' element comes from FD&C Act 801(a); J may reflect superseded text.

**External sources:** ISO_13485_CONTROLLED_COPY, LIVE_ECFR, STATUTE_FDCA · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH); conflicting evidence; column J not fully supported by text

---

### M-007 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Direct Lookup · Medical Devices — 21 CFR 820 / QMSR*

**Question.** How may a manufacturer obtain an exemption or variance from a requirement of Part 820?

**Draft key G.** 21 CFR 820.1(d); section 520(f) of the FD&C Act; 21 CFR 10.30  
**Draft ISO H.** None  
**Key elements J.** Exemption or variance under section 520(f)(2); requested by citizen petition under 10.30.

**Rationale.** CFR elements: all supported from 820.1(d). The row is held at NEEDS_RESEARCH only because of the ISO key: column H = None, while the internal crosswalk maps the whole of 820.1 to clauses 1 and 4.1. The cited paragraph names no clause. Lean: ACCEPTED.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Exemption or variance under section 520(f)(2) · `820.1(d)(1)` — “may petition for an exemption or variance from such requirement in accordance with section 520(f)(2) of the Federal Food, Drug, and Cosmetic Act”
  - **SUPPORTED** · requested by citizen petition under 10.30 · `820.1(d)(1); 10.30 heading 'Citizen petition.'` — “Petitions for an exemption or variance shall be submitted in accordance with the procedures set forth in § 10.30 of this chapter.”

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `none` · internal crosswalk: `820.1 -> 1, 4.1 (section level)`  
Section-level crosswalk vs paragraph-level 'None'. Under the workbook rule, naming any clause on a None row scores Q=0 AND triggers column M (fabricated citation, G2 zero tolerance). Confirm the answer genuinely reaches no clause before accepting None.

**What the SME must establish:**
1. Controlled-source + scoring-policy decision: does an answer to this paragraph-level question reach ISO 13485 Clause 1 (Scope) or 4.1? If yes, H should name it; if no, accept None.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-019 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Direct Lookup · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What is the consequence under Part 820 of failing to comply with the quality management system requirements?

**Draft key G.** 21 CFR 820.10(e); section 501(h) of the FD&C Act  
**Draft ISO H.** None  
**Key elements J.** The device is adulterated and the manufacturer is subject to enforcement action.

**Rationale.** 820.10(e) states both elements. Held only for the ISO 'None' key (820.10 has no crosswalk mapping; the paragraph names no clause). Lean: ACCEPTED.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · The device is adulterated · `820.10(e)` — “The failure to comply with any applicable requirement in this part renders a device adulterated under section 501(h) of the Federal Food, Drug, and Cosmetic Act.”
  - **SUPPORTED** · the manufacturer is subject to enforcement action · `820.10(e)` — “Such a device, as well as any person responsible for the failure to comply, is subject to regulatory action.”

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `none` · internal crosswalk: `820.10 -> no mapping`  
Enforcement paragraph; no clause named. Low risk, but None rows carry a G2 penalty for any clause named.

**What the SME must establish:**
1. Confirm None is intended (answer reaches no clause).

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-021 — proposed **ACCEPTED** (HIGH)
*Direct Lookup · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What must be recorded for complaints involving the possible failure of a device, labeling, or packaging to meet specifications?

**Draft key G.** 21 CFR 820.35(a)  
**Draft ISO H.** 8.2.2  
**Key elements J.** Records of review, evaluation and investigation, including the justification when no investigation is made.

**Rationale.** J is stated in 820.35(a). ISO CONFLICT RESOLVED BY CFR TEXT: 820.35(a) itself names clause(s) 8.2.2, exactly the draft. The crosswalk disagrees only because it maps the whole section to the single clause named in the section's introductory text — a granularity artefact, not evidence against the draft.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Records of review, evaluation and investigation · `820.35(a)` — “the manufacturer shall maintain records of the review, evaluation, and investigation for any complaints”
  - **SUPPORTED** · including the justification when no investigation is made · `820.35(a)` — “the manufacturer shall maintain records documenting justification for not performing such investigation”
  - **SUPPORTED** · ISO clause(s) 8.2.2 · `820.35(a)` — “In addition to Clause 8.2.2 in ISO 13485, Complaint Handling” _(Clause named in the regulation text.)_

**ISO assessment.** tier `T1_CFR_TEXT` · draft `8.2.2` · clauses named in cited CFR text: `8.2.2` · internal crosswalk: `820.35 -> 4.2.5 (section level, from the introductory text)`  
Section-level crosswalk vs paragraph-level key; the paragraph text names the draft clause.

**Uncertainty.** Human confirmation required because the automated pass flagged a crosswalk conflict.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated)

---

### M-022 — proposed **ACCEPTED** (HIGH)
*Direct Lookup · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What minimum data elements must a servicing record contain under Part 820?

**Draft key G.** 21 CFR 820.35(b)  
**Draft ISO H.** 7.5.4  
**Key elements J.** Six specified elements including device name, unique device identifier or other identification, date of service, individual servicing the device, service performed, and test and inspection data.

**Rationale.** J is stated in 820.35(b). ISO CONFLICT RESOLVED BY CFR TEXT: 820.35(b) itself names clause(s) 7.5.4, exactly the draft. The crosswalk disagrees only because it maps the whole section to the single clause named in the section's introductory text — a granularity artefact, not evidence against the draft.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · device name · `820.35(b)(1)` — “The name of the device serviced;”
  - **SUPPORTED** · UDI or other identification · `820.35(b)(2)` — “Any UDI or UPC, and any other device identification(s);”
  - **SUPPORTED** · date of service · `820.35(b)(3)` — “The date of service;”
  - **SUPPORTED** · individual servicing the device · `820.35(b)(4)` — “The individual(s) who serviced the device;”
  - **SUPPORTED** · service performed · `820.35(b)(5)` — “The service performed; and”
  - **SUPPORTED** · test and inspection data · `820.35(b)(6)` — “Any test and inspection data.”
  - **SUPPORTED** · ISO clause(s) 7.5.4 · `820.35(b)` — “In adhering to Clause 7.5.4 in ISO 13485, Servicing Activities” _(Clause named in the regulation text.)_

**ISO assessment.** tier `T1_CFR_TEXT` · draft `7.5.4` · clauses named in cited CFR text: `7.5.4` · internal crosswalk: `820.35 -> 4.2.5 (section level, from the introductory text)`  
Section-level crosswalk vs paragraph-level key; the paragraph text names the draft clause.

**Uncertainty.** Human confirmation required because the automated pass flagged a crosswalk conflict.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated)

---

### M-023 — proposed **ACCEPTED** (HIGH)
*Cross-Reference · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What does Part 820 require with respect to recording the unique device identifier, and which record control section states it?

**Draft key G.** 21 CFR 820.35(c)  
**Draft ISO H.** 7.5.1; 7.5.8; 7.5.9  
**Key elements J.** The UDI must be recorded for each medical device or batch of medical devices.

**Rationale.** J is stated in 820.35(c). ISO CONFLICT RESOLVED BY CFR TEXT: 820.35(c) itself names clause(s) 7.5.1; 7.5.8; 7.5.9, exactly the draft. The crosswalk disagrees only because it maps the whole section to the single clause named in the section's introductory text — a granularity artefact, not evidence against the draft.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · The UDI must be recorded for each medical device or batch · `820.35(c)` — “the UDI must be recorded for each medical device or batch of medical devices.”
  - **SUPPORTED** · ISO clause(s) 7.5.1; 7.5.8; 7.5.9 · `820.35(c)` — “In addition to the requirements of Clauses 7.5.1, 7.5.8, and 7.5.9 in ISO 13485” _(Clause named in the regulation text.)_

**ISO assessment.** tier `T1_CFR_TEXT` · draft `7.5.1; 7.5.8; 7.5.9` · clauses named in cited CFR text: `7.5.1, 7.5.8, 7.5.9` · internal crosswalk: `820.35 -> 4.2.5 (section level, from the introductory text)`  
Section-level crosswalk vs paragraph-level key; the paragraph text names the draft clause.

**Uncertainty.** Human confirmation required because the automated pass flagged a crosswalk conflict.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated)

---

### M-024 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Direct Lookup · Medical Devices — 21 CFR 820 / QMSR*

**Question.** How may a manufacturer indicate to FDA that a record it holds is confidential?

**Draft key G.** 21 CFR 820.35(d)  
**Draft ISO H.** None  
**Key elements J.** Records deemed confidential may be marked to aid FDA in determining whether the information may be disclosed.

**Rationale.** 820.35(d) states J. The ISO key 'None' is doubtful: 820.35's introductory text frames every paragraph as 'in addition to the requirements of Clause 4.2.5', and the crosswalk maps the section to 4.2.5. Under the workbook rule, a vendor naming 4.2.5 here would be scored as a FABRICATED citation (column M, G2 zero tolerance).

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Records deemed confidential may be marked to aid FDA in determining whether information may be disclosed · `820.35(d)` — “Records deemed confidential by the manufacturer may be marked to aid FDA in determining whether information may be disclosed under the public information regulation in part 20 of this chapter.”

**ISO assessment.** tier `NONE_CLAIM` · draft `None` · clauses named in cited CFR text: `4.2.5 (section intro)` · internal crosswalk: `820.35 -> 4.2.5 (section level, from the introductory text)`  
The section's own introductory text names 4.2.5; 'None' may penalise a correct answer as fabricated.

**What the SME must establish:**
1. Decide whether H should be 4.2.5 (section-intro framing) or None; consult the controlled standard's Control of records clause for scope.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH); conflicting evidence

---

### M-027 — proposed **ACCEPTED** (HIGH)
*Direct Lookup · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What must be documented when labeling is released for use?

**Draft key G.** 21 CFR 820.45(b)  
**Draft ISO H.** 4.2.5  
**Key elements J.** Release of labeling for use must be documented.

**Rationale.** J is stated in 820.45(b). ISO CONFLICT RESOLVED BY CFR TEXT: 820.45(b) itself names clause(s) 4.2.5, exactly the draft. The crosswalk disagrees only because it maps the whole section to the single clause named in the section's introductory text — a granularity artefact, not evidence against the draft.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Release of labeling for use must be documented · `820.45(b)` — “The release of the labeling for use must be documented in accordance with Clause 4.2.5 of ISO 13485.”
  - **SUPPORTED** · ISO clause(s) 4.2.5 · `820.45(b)` — “The release of the labeling for use must be documented in accordance with Clause 4.2.5 of ISO 13485.” _(Clause named in the regulation text.)_

**ISO assessment.** tier `T1_CFR_TEXT` · draft `4.2.5` · clauses named in cited CFR text: `4.2.5` · internal crosswalk: `820.45 -> 7.5.1 (section level, from the introductory text)`  
Section-level crosswalk vs paragraph-level key; the paragraph text names the draft clause.

**Uncertainty.** Human confirmation required because the automated pass flagged a crosswalk conflict.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated)

---

### M-028 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Application · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What controls does Part 820 require over labeling and packaging operations to prevent mixups, and what must be documented?

**Draft key G.** 21 CFR 820.45(c)  
**Draft ISO H.** 4.2.3; 4.2.5  
**Key elements J.** Labeling and packaging operations must be controlled to prevent mixups; inspection results must be documented.

**Rationale.** 820.45(c) states both J elements and names Clause 4.2.5. The draft also names 4.2.3 (Medical device file): the paragraph mentions 'the medical device file' as where labeling is specified, but does not invoke that clause. Whether 4.2.3 belongs in the key is an ISO/policy question.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Labeling and packaging operations must be controlled to prevent mixups · `820.45(c)` — “The manufacturer must ensure labeling and packaging operations have been established and maintained to prevent mixups”
  - **SUPPORTED** · inspection results must be documented · `820.45(c)` — “Results of such labeling inspection must be documented in accordance with Clause 4.2.5 of ISO 13485.”

**ISO assessment.** tier `T3_UNRESOLVED` · draft `4.2.3; 4.2.5` · clauses named in cited CFR text: `4.2.5` · internal crosswalk: `820.45 -> 7.5.1 (section level, from the introductory text)`  
4.2.5 named in CFR text. 4.2.3 inferred from the term 'medical device file' only.

**What the SME must establish:**
1. Controlled source: does the answer reach Clause 4.2.3 or only 4.2.5?

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-029 — proposed **CORRECTED** (MEDIUM)
*Distinction · Medical Devices — 21 CFR 820 / QMSR*

**Question.** Which provisions of Part 820 are FDA supplements to the incorporated standard rather than incorporation by reference?

**Draft key G.** 21 CFR 820.10(b) through (e); 820.35; 820.45  
**Draft ISO H.** 4.2.5; 7.5.1; 7.5.4; 7.5.8; 7.5.9; 8.2.2; 8.2.3  
**Key elements J.** 820.10(b)-(e), 820.35 and 820.45 impose FDA requirements in addition to the standard; the balance of the quality system reaches the manufacturer through incorporation by reference.

**Proposed correction (NOT applied).** ISO key (column H): 4.2.5; 7.2.3; 7.3; 7.5.1; 7.5.4; 7.5.8; 7.5.9 (incl. 7.5.9.1, 7.5.9.2); 8.2.2; 8.2.3; 8.3.3 — every clause named in the cited CFR text. Citation unchanged.

**Rationale.** Citation matches J. The ISO key omits clauses that the cited provisions themselves name: 820.10(b)(4) names 7.2.3 and 8.3.3, 820.10(c) names 7.3. The draft lists 4.2.5; 7.5.1; 7.5.4; 7.5.8; 7.5.9; 8.2.2; 8.2.3.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · 820.10(b)–(e), 820.35 and 820.45 impose FDA requirements in addition to the standard · `820.10(b)` — “Comply, as appropriate, with the other applicable regulatory requirements in this title, including, but not limited to the following, to fully comply with the listed ISO 13485 Clause:” _(820.10(e) is an enforcement provision rather than a supplement; SME may want to note that.)_
  - **SUPPORTED** · the balance of the quality system reaches the manufacturer through incorporation by reference · `820.10(a)` — “Document a quality management system that complies with the applicable requirements of ISO 13485 (incorporated by reference, see § 820.7) and other applicable requirements of this part”

**ISO assessment.** tier `T1_CFR_TEXT` · draft `4.2.5; 7.5.1; 7.5.4; 7.5.8; 7.5.9; 8.2.2; 8.2.3` · clauses named in cited CFR text: `7.5.8, 7.5.9.1, 8.2.3, 7.2.3, 8.3.3, 7.3, 7.5.9.2, 4.2.5, 8.2.2, 7.5.4, 7.5.1, 7.5.9` · internal crosswalk: `820.10 -> none; 820.35 -> 4.2.5; 820.45 -> 7.5.1`  
Draft is a subset of the clauses the cited text names; missing 7.2.3, 7.3, 8.3.3.

**Uncertainty.** Policy: should H list every clause named in the cited provisions, or only those an answer must reach?

**External sources:** ISO_13485_CONTROLLED_COPY (optional: clause named in CFR text) · **second review:** ISO conflict (mandated); proposed CORRECTED (key change); conflicting evidence

---

### M-034 — proposed **ACCEPTED** (MEDIUM)
*Temporal/Version · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What is the difference between a Device Master Record, a Device History Record, and a Design History File under the current Part 820?

**Draft key G.** TEMPORAL TRAP — 820.181, 820.184 and 820.30(j) are [Reserved]; those constructs are not in the current Part 820  
**Draft ISO H.** 4.2.3; 4.2.5; 7.3.10  
**Key elements J.** Must state that the DMR/DHR/DHF terms are not used in the current Part 820 and identify the medical device file, record control and design and development file clauses that carry the equivalent obligations.

**Rationale.** Established: none of 'master record', 'history record', 'design history', DMR, DHR or DHF appears anywhere in current Part 820; 'medical device file' does (820.3(b), 820.45(c)). 820.181/820.184 fall in reserved Subparts C–O, 820.30 in the reserved 820.20–820.30 range. ISO: 4.2.3 and 4.2.5 equal the crosswalk for 820.181/820.184; 7.3.10 refines the crosswalk's 7.3 for 820.30 (paragraph (j)) with a matching title.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · DMR/DHR/DHF terms are not used in the current Part 820 · `Part 820 (whole-part term search)` — “Subparts C-O [Reserved]” _(Term search over all live Part 820 records: 0 hits for each legacy term.)_
  - **SUPPORTED** · identify the medical device file clause · `820.45(c)` — “as specified in the medical device file”
  - **PARTIALLY_SUPPORTED** · record control and design and development file clauses · `crosswalk + index titles` _(Clause identities from internal index/crosswalk only.)_

**ISO assessment.** tier `T2_CORROBORATED` · draft `4.2.3; 4.2.5; 7.3.10` · clauses named in cited CFR text: `none` · internal crosswalk: `820.181 -> 4.2.3; 820.184 -> 4.2.5, 7.5.1; 820.30 -> 7.3`  
7.3.10 is a subclause of the crosswalk's 7.3 with a matching title (Design and development files).

**Uncertainty.** Flagged as ISO conflict by automation (7.3.10 vs 7.3); resolution rests on internal titles, not the standard.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); temporal/version (mandated)

---

### M-037 — proposed **ACCEPTED** (MEDIUM)
*Temporal/Version · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What are the purchasing control and supplier evaluation requirements of 21 CFR 820.50?

**Draft key G.** TEMPORAL TRAP — 820.50 is [Reserved]; the requirement reaches the manufacturer through 21 CFR 820.10(a)  
**Draft ISO H.** 7.4; 7.4.1; 7.4.2; 7.4.3  
**Key elements J.** Must state that 820.50 is reserved and route purchasing controls to 820.10(a) and the standard's purchasing clauses.

**Rationale.** Temporal status established: 820.50 is reserved in the snapshot, and 820.10(a) is live text that carries the obligation. Draft = crosswalk's 7.4 plus its subclauses (refinement within the parent). Flagged as an ISO conflict only because of the added subclauses.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · 820.50 is reserved · `Part 820 section list / reserved records` — “Subparts C-O [Reserved]” _(Snapshot holds the provision as [Reserved] (range record or reserved subpart).)_
  - **SUPPORTED** · route to 820.10(a) · `820.10(a)` — “Document a quality management system that complies with the applicable requirements of ISO 13485”

**ISO assessment.** tier `T2_CORROBORATED` · draft `7.4; 7.4.1; 7.4.2; 7.4.3` · clauses named in cited CFR text: `none` · internal crosswalk: `820.50 -> 7.4`  
Draft = crosswalk's 7.4 plus its subclauses (refinement within the parent). Flagged as an ISO conflict only because of the added subclauses.

**Uncertainty.** Temporal row — a wrong answer here is a citation failure by rule; independent second review required.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); temporal/version (mandated)

---

### M-038 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Temporal/Version · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What does 21 CFR 820.75 require for process validation?

**Draft key G.** TEMPORAL TRAP — 820.75 is [Reserved]; the requirement reaches the manufacturer through 21 CFR 820.10(a)  
**Draft ISO H.** 7.5.6; 7.5.7  
**Key elements J.** Must state that 820.75 is reserved and route process validation to 820.10(a) and the standard's validation clauses.

**Rationale.** Temporal status established: 820.75 is reserved in the snapshot, and 820.10(a) is live text that carries the obligation. Draft adds 7.5.7 (sterilization/sterile barrier validation), a sibling of the crosswalk's 7.5.6, not a subclause of it.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · 820.75 is reserved · `Part 820 section list / reserved records` — “Subparts C-O [Reserved]” _(Snapshot holds the provision as [Reserved] (range record or reserved subpart).)_
  - **SUPPORTED** · route to 820.10(a) · `820.10(a)` — “Document a quality management system that complies with the applicable requirements of ISO 13485”

**ISO assessment.** tier `T3_UNRESOLVED` · draft `7.5.6; 7.5.7` · clauses named in cited CFR text: `none` · internal crosswalk: `820.75 -> 7.5.6`  
Draft adds 7.5.7 (sterilization/sterile barrier validation), a sibling of the crosswalk's 7.5.6, not a subclause of it.

**What the SME must establish:**
1. Controlled source: does the 820.75 process-validation obligation reach 7.5.7 as well as 7.5.6?

**Uncertainty.** Temporal row — a wrong answer here is a citation failure by rule; independent second review required.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); temporal/version (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-040 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Temporal/Version · Medical Devices — 21 CFR 820 / QMSR*

**Question.** What statistical techniques does 21 CFR 820.250 require?

**Draft key G.** TEMPORAL TRAP — 820.250 is [Reserved]; the requirement reaches the manufacturer through 21 CFR 820.10(a)  
**Draft ISO H.** 8.1; 8.2.6; 8.4  
**Key elements J.** Must state that 820.250 is reserved and route statistical technique determination to 820.10(a) and the standard's measurement and analysis clauses.

**Rationale.** Temporal status established: 820.250 is reserved in the snapshot, and 820.10(a) is live text that carries the obligation. Genuine disagreement: draft 8.2.6 (monitoring and measurement of product) vs crosswalk 8.2.5 (of processes).

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · 820.250 is reserved · `Part 820 section list / reserved records` — “Subparts C-O [Reserved]” _(Snapshot holds the provision as [Reserved] (range record or reserved subpart).)_
  - **SUPPORTED** · route to 820.10(a) · `820.10(a)` — “Document a quality management system that complies with the applicable requirements of ISO 13485”

**ISO assessment.** tier `T3_UNRESOLVED` · draft `8.1; 8.2.6; 8.4` · clauses named in cited CFR text: `none` · internal crosswalk: `820.250 -> 8.1, 8.2.5, 8.4`  
Genuine disagreement: draft 8.2.6 (monitoring and measurement of product) vs crosswalk 8.2.5 (of processes).

**What the SME must establish:**
1. Controlled source: which of 8.2.5 / 8.2.6 (or both) carries the statistical-techniques obligation?

**Uncertainty.** Temporal row — a wrong answer here is a citation failure by rule; independent second review required.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); temporal/version (mandated); materially uncertain (NEEDS_RESEARCH)

---

### M-042 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Cross-Reference · Medical Devices — 21 CFR 820 / QMSR*

**Question.** Which parts of Title 21 govern device establishment registration, listing, and unique device identification, and how do they interact with Part 820?

**Draft key G.** 21 CFR Part 807; 21 CFR Part 830; 21 CFR 820.10(b)(1); 820.35(c)  
**Draft ISO H.** 7.5.8; 7.5.9  
**Key elements J.** Registration and listing under Part 807; UDI system under Part 830; Part 820 requires the UDI assignment system and the recording of the UDI.

**Rationale.** CFR elements supported (820.10(b)(1) UDI system per Part 830; 820.35(c) UDI recording). ISO key omits 7.5.1, which the cited 820.35(c) names — and M-023, citing the same paragraph, DOES list 7.5.1. The benchmark is internally inconsistent here.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · UDI system under Part 830 · `820.10(b)(1)` — “the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter”
  - **SUPPORTED** · Part 820 requires the recording of the UDI · `820.35(c)` — “the UDI must be recorded for each medical device or batch of medical devices.”
  - **NOT_FOUND_IN_EVIDENCE** · Registration and listing under Part 807 · `Part 807` _(Part-level citation; Part 807 text not in this row's evidence.)_

**ISO assessment.** tier `T3_UNRESOLVED` · draft `7.5.8; 7.5.9` · clauses named in cited CFR text: `7.5.8, 7.5.1, 7.5.9` · internal crosswalk: `820.35 -> 4.2.5`  
Inconsistent with M-023 (same paragraph, H includes 7.5.1).

**What the SME must establish:**
1. Resolve the M-023 / M-042 inconsistency: is 7.5.1 in or out for 820.35(c)?
1. Confirm Part 807 registration and listing element (part-level citation).

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH); conflicting evidence

---

### PB-009 — proposed **CORRECTED** (MEDIUM)
*Application · PLATFORM BEHAVIOR — Abstention & Guidance Tier*

**Question.** In plain English, why must a device manufacturer investigate a complaint, and what requires it?

**Draft key G.** 21 CFR 820.35(a)  
**Draft ISO H.** 8.2.2  
**Key elements J.** Plain-English explanation delivered with the citation attached. A correct explanation carrying no citation is a citation failure under the rubric.

**Proposed correction (NOT applied).** 21 CFR 820.35(a); 21 CFR 820.10(a)

**Rationale.** 820.35(a) names Clause 8.2.2 (ISO conflict resolved by CFR text, as in M-021). But the question asks what REQUIRES the investigation: 820.35(a) supplements Clause 8.2.2 with record requirements; the obligation to comply with 8.2.2 itself comes through 820.10(a). Proposed: add 820.10(a).

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Plain-English explanation delivered with the citation attached · `820.35(a)` — “In addition to Clause 8.2.2 in ISO 13485, Complaint Handling” _(Behaviour element.)_
  - **PARTIALLY_SUPPORTED** · what requires it · `820.10(a)` — “Document a quality management system that complies with the applicable requirements of ISO 13485” _(The investigation duty is in the standard's complaint-handling clause, reached through 820.10(a).)_

**ISO assessment.** tier `T1_CFR_TEXT` · draft `8.2.2` · clauses named in cited CFR text: `8.2.2` · internal crosswalk: `820.35 -> 4.2.5 (section level, from the introductory text)`  
Paragraph names the draft clause.

**Uncertainty.** Whether completeness requires 820.10(a) is a judgment; the row is also an ISO-conflict row.

**External sources:** ISO_13485_CONTROLLED_COPY (optional: clause named in CFR text) · **second review:** ISO conflict (mandated); proposed CORRECTED (key change)

---

### NC-005 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** How often does 21 CFR 820.20 require management review — is it quarterly?

**Draft key G.** FALSE PREMISE — 21 CFR 820.20 is [Reserved] as of February 2, 2026; no management review frequency is specified in Part 820 or the incorporated standard  
**Draft ISO H.** 5.6.1  
**Key elements J.** The regulation requires defined intervals per the manufacturer's procedures; no quarterly mandate. Must correct.

**Rationale.** Part 820 half established (whole part inspected; 'management review', 'quarter', 'interval', 'frequen' all 0). The key also asserts that no frequency is specified in the incorporated standard and J says reviews occur at defined intervals — both are ISO content not held here.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · no quarterly mandate in Part 820 · `Part 820 whole-part search` _(0 hits)_
  - **NOT_FOUND_IN_EVIDENCE** · The regulation requires defined intervals per the manufacturer's procedures · `` _(ISO 13485 content (management review), not held.)_

**ISO assessment.** tier `T2_CORROBORATED` · draft `5.6.1` · clauses named in cited CFR text: `none` · internal crosswalk: `820.20 -> 5`  
5.6.1 is a subclause of crosswalk's 5 with matching title (Management review — General).

**Absence assessment.** scope: 21 CFR Part 820 (whole) + ISO 13485 (NOT available) · method: term search · result: `NO_RESULT in Part 820; ISO not searchable` · **absence established: False**  
Absence in the incorporated standard cannot be established without the controlled copy.

**What the SME must establish:**
1. Controlled source: confirm the management-review clause sets no fixed frequency and what it does require.
1. Federal Register: confirm the effective/compliance date of the QMSR final rule (89 FR 7523). The snapshot carries the FR citation but not the effective date; federal_register_docs is empty.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** FEDERAL_REGISTER, ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### NC-011 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** How many design reviews does 21 CFR 820.30 require during development?

**Draft key G.** FALSE PREMISE — 21 CFR 820.30 is [Reserved] as of February 2, 2026; no number of design reviews is specified in Part 820 or the incorporated standard  
**Draft ISO H.** 7.3.5  
**Key elements J.** The regulation requires reviews at appropriate stages defined in the design plan; no fixed count. Must correct.

**Rationale.** 820.30 is reserved (range 820.20–820.30) and Part 820 contains no design-review count ('design review' 0). The key also asserts no count in the incorporated standard and J says reviews occur at planned stages — ISO content not held.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · no fixed count in Part 820 · `Part 820 whole-part search` _(0 hits)_
  - **NOT_FOUND_IN_EVIDENCE** · reviews at appropriate stages defined in the design plan · `` _(ISO 13485 design review clause, not held.)_

**ISO assessment.** tier `T2_CORROBORATED` · draft `7.3.5` · clauses named in cited CFR text: `none` · internal crosswalk: `820.30 -> 7.3`  
Subclause of crosswalk's 7.3 with matching title.

**Absence assessment.** scope: Part 820 whole + ISO 13485 (NOT available) · method: term search · result: `NO_RESULT in Part 820` · **absence established: False**  
ISO half cannot be established.

**What the SME must establish:**
1. Controlled source: confirm the design-review clause sets no fixed number.
1. Federal Register: confirm the effective/compliance date of the QMSR final rule (89 FR 7523). The snapshot carries the FR citation but not the effective date; federal_register_docs is empty.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** FEDERAL_REGISTER, ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated); materially uncertain (NEEDS_RESEARCH)

---

### NC-016 — proposed **ACCEPTED** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What does 21 CFR 820.30(j) require for the Design History File?

**Draft key G.** REPEALED PROVISION — 820.30 is [Reserved] as of February 2, 2026  
**Draft ISO H.** 7.3.10  
**Key elements J.** Correct response states that 820.30 is reserved and does not describe its former content as current.

**Rationale.** 820.30 exists only as part of the reserved range 820.20–820.30. ISO 7.3.10 refines the crosswalk's 7.3 with a matching title (Design and development files).

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · 820.30 is reserved · `section_state(820.30)` — “820.20-820.30” _(reserved=True, covered_by=820.20-820.30)_
  - **SUPPORTED** · does not describe its former content as current · `` _(Behaviour element.)_

**ISO assessment.** tier `T2_CORROBORATED` · draft `7.3.10` · clauses named in cited CFR text: `none` · internal crosswalk: `820.30 -> 7.3`  
Subclause of crosswalk's clause; flagged as conflict by automation.

**Absence assessment.** scope: Part 820 · method: section lookup · result: `RESERVED` · **absence established: True**  
Reserved, not absent — the false-premise distinction applies.

**What the SME must establish:**
1. Federal Register: confirm the effective/compliance date of the QMSR final rule (89 FR 7523). The snapshot carries the FR citation but not the effective date; federal_register_docs is empty.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** FEDERAL_REGISTER, ISO_13485_CONTROLLED_COPY · **second review:** ISO conflict (mandated)

---

## Other ISO-bearing rows (column H not '—'), for completeness

| Row | Draft H | Tier | Proposed | Confidence |
|---|---|---|---|---|
| M-001 | 1; 4.1 | T2_CORROBORATED | ACCEPTED | MEDIUM |
| M-008 | 3; ISO 9000 Clause 3 | T1_CFR_TEXT | ACCEPTED | MEDIUM |
| M-009 | 0.1; 3 | T1_CFR_TEXT | NEEDS_RESEARCH | MEDIUM |
| M-010 | 1 through 8 (entire standard); ISO 9000 Clause 3 | RANGE | ACCEPTED | HIGH |
| M-011 | 1 through 8 (entire standard) | RANGE | ACCEPTED | MEDIUM |
| M-012 | 4 through 8 | RANGE | NEEDS_RESEARCH | MEDIUM |
| M-013 | 7.5.8 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-014 | 7.5.9.1 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-015 | 8.2.3 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-016 | 7.2.3; 8.2.3; 8.3.3 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-017 | 7.3 and its subclauses | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-018 | 7.5.9.2 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-020 | 4.2.5 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-025 | 7.5.1 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-026 | 7.5.1 | T1_CFR_TEXT | ACCEPTED | HIGH |
| M-030 | 1 through 8 (entire standard) | RANGE | NEEDS_RESEARCH | MEDIUM |
| M-031 | 7.3 and its subclauses | T1_CFR_TEXT | ACCEPTED | MEDIUM |
| M-032 | 8.5.2; 8.5.3 | T2_CORROBORATED | ACCEPTED | MEDIUM |
| M-033 | 8.2.2 | T1_CFR_TEXT | ACCEPTED | MEDIUM |
| M-035 | 5 | T2_CORROBORATED | ACCEPTED | MEDIUM |
| M-036 | 8.2.4 | T2_CORROBORATED | ACCEPTED | MEDIUM |
| M-039 | 7.6 | T2_CORROBORATED | ACCEPTED | MEDIUM |
| M-041 | 1; 4.1 | T2_CORROBORATED | NEEDS_RESEARCH | MEDIUM |
| X-003 | 7.3; 7.4; 7.5.3; 7.5.4; 8.5.2; 8.5.3 | T1_CFR_TEXT | CORRECTED | MEDIUM |
| PB-005 | 7.4; 7.4.1 | T3_UNRESOLVED | NEEDS_RESEARCH | MEDIUM |
| PB-006 | 7.1 | T3_UNRESOLVED | NEEDS_RESEARCH | MEDIUM |
| PB-008 | 1 through 8 (entire standard) | RANGE | ACCEPTED | MEDIUM |
| SD-012 | 7.3.3 | T1_CFR_TEXT | ACCEPTED | MEDIUM |