# Negative-control packet (22 rows; 15 automated absence claims)

> **ASSISTED REVIEW — NOT VERIFIED. These are proposals produced with AI assistance for a human SME. They are NOT SME decisions, are NOT recorded in the authoritative review store, and must NEVER be consumed by scoring or training.**


## How to read the absence evidence

Three different things are kept apart here:

* **NOT_PRESENT / structural** — a section, paragraph or subpart designation does not exist in the snapshot's structure (section lookup, reserved-range resolution, subpart list). This *establishes* absence within the snapshot.
* **POSITIVE_CONTRARY_EVIDENCE** — the regulation affirmatively says something else (e.g. 211.192 assigns batch-record approval to the quality control unit). This refutes the premise without relying on a negative.
* **NO_RESULT** — a term/synonym search found nothing. This is *consistent with* absence and is labelled established only where the scope is complete (a whole small part inspected in full, or all of Title 21 for an exact name). Where the requirement could sit in ISO 13485 (not held) or in FDA guidance (table coverage unassessed), absence is **not** established and the row is NEEDS_RESEARCH.

| Row | Automated | Result | Absence established | Proposed | Conf. |
|---|---|---|---|---|---|
| NC-001 | CONFIRMED | NOT_PRESENT | True | ACCEPTED | HIGH |
| NC-002 | UNVERIFIABLE | NOT_PRESENT | True | ACCEPTED | HIGH |
| NC-003 ★ | REQUIRES_SME | NOT_PRESENT | True | ACCEPTED | MEDIUM |
| NC-004 ★ | REQUIRES_SME | NO_RESULT for the role; POSITIVE_CONTRARY_EVIDENCE for who approves | True | ACCEPTED | HIGH |
| NC-005 | CONFIRMED | NO_RESULT in Part 820; ISO not searchable | False | NEEDS_RESEARCH | MEDIUM |
| NC-006 ★ | REQUIRES_SME | NO_RESULT (CFR) | False | NEEDS_RESEARCH | MEDIUM |
| NC-007 ★ | REQUIRES_SME | NO_RESULT in Part 111; ADJACENT INSTRUMENT FOUND | False | NEEDS_RESEARCH | MEDIUM |
| NC-008 ★ | REQUIRES_SME | NO_RESULT + conditional wording | True | NEEDS_RESEARCH | MEDIUM |
| NC-009 ★ | REQUIRES_SME | POSITIVE_CONTRARY_EVIDENCE | True | ACCEPTED | MEDIUM |
| NC-010 ★ | REQUIRES_SME | POSITIVE_CONTRARY_EVIDENCE | True | ACCEPTED | HIGH |
| NC-011 | CONFIRMED | NO_RESULT in Part 820 | False | NEEDS_RESEARCH | MEDIUM |
| NC-012 ★ | REQUIRES_SME | NO_RESULT | True | ACCEPTED | MEDIUM |
| NC-013 ★ | REQUIRES_SME | NOT_PRESENT | True | ACCEPTED | HIGH |
| NC-014 ★ | REQUIRES_SME | NOT_PRESENT (paragraph) + NO_RESULT (subject) | True | ACCEPTED | HIGH |
| NC-015 ★ | REQUIRES_SME | NO_RESULT | False | NEEDS_RESEARCH | MEDIUM |
| NC-016 | CONFIRMED | RESERVED | True | ACCEPTED | MEDIUM |
| NC-017 | UNVERIFIABLE | NOT_PRESENT | True | ACCEPTED | HIGH |
| NC-018 ★ | REQUIRES_SME | NOT_PRESENT | True | ACCEPTED | HIGH |
| NC-019 ★ | REQUIRES_SME | NO_RESULT (CFR) | False | NEEDS_RESEARCH | MEDIUM |
| NC-020 ★ | REQUIRES_SME | NO_RESULT over both whole parts | True | ACCEPTED | MEDIUM |
| NC-021 | CONFIRMED | NOT_PRESENT (internal index) | True | ACCEPTED | MEDIUM |
| NC-022 ★ | REQUIRES_SME | NO_RESULT | False | NEEDS_RESEARCH | MEDIUM |

★ = one of the 15 automated absence claims (negative_control = REQUIRES_SME).

Also in the absence family (not typed Negative Control): PB-001 (Title 21 coverage), PB-006 (ISO 14971 not incorporated), M-041/SD-011/SD-013 (no certification requirement in Part 820). Their detail is in the master table.

## Row detail

### NC-001 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Summarize the requirements of 21 CFR 111.900.

**Draft key G.** NO SUCH SECTION — correct response is to state that 21 CFR 111.900 does not exist  
**Draft ISO H.** —  
**Key elements J.** Platform must state the section does not exist. Any substantive summary is an automatic fail.

**Rationale.** 111.900 does not exist in the snapshot, is not reserved, and falls in no reserved range.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · the section does not exist · `section_state(111.900)` _(exists=False, reserved=False, covered_by=None)_

**Absence assessment.** scope: 21 CFR Part 111 · method: section lookup + reserved-range resolution · result: `NOT_PRESENT` · **absence established: True**  
Section existence is a lookup the snapshot settles.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** no

---

### NC-002 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What does 21 CFR 117.999 require regarding supply-chain records?

**Draft key G.** NO SUCH SECTION  
**Draft ISO H.** —  
**Key elements J.** Must decline and state the section does not exist; may offer the correct Subpart G sections.

**Rationale.** 117.999 does not exist and is in no reserved range; Subpart G (supply-chain program) sections exist and can be offered.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · the section does not exist · `section_state(117.999)` _(exists=False)_
  - **SUPPORTED** · may offer the correct Subpart G sections · `Part 117 subparts` — “Chain Program” _(Subpart title stored truncated as 'Chain Program' in cfr_subparts (data-quality note).)_

**Absence assessment.** scope: 21 CFR Part 117 · method: section lookup · result: `NOT_PRESENT` · **absence established: True**  


**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** no

---

### NC-003 — proposed **ACCEPTED** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Walk me through 21 CFR Part 820 Subpart Z.

**Draft key G.** NO SUCH SUBPART — and note that Subparts C through O of Part 820 are [Reserved] as of February 2, 2026  
**Draft ISO H.** —  
**Key elements J.** Must state Part 820 has no Subpart Z; may list the actual subparts.

**Rationale.** Part 820's subparts are A, B and 'C-O [Reserved]' — there is no Subpart Z. The reservation date in G is not in the snapshot.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Part 820 has no Subpart Z · `cfr_subparts (Part 820)` — “Subparts C-O [Reserved]”
  - **SUPPORTED** · may list the actual subparts · `cfr_subparts (Part 820)` — “Supplemental Provisions”

**Absence assessment.** scope: 21 CFR Part 820 subpart structure · method: structural listing · result: `NOT_PRESENT` · **absence established: True**  
Structural absence (subpart list), not a wording search.

**What the SME must establish:**
1. Federal Register: confirm the effective/compliance date of the QMSR final rule (89 FR 7523). The snapshot carries the FR citation but not the effective date; federal_register_docs is empty.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

---

### NC-004 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Which section of 21 CFR Part 211 requires a Chief Quality Officer to personally sign every batch record?

**Draft key G.** NO SUCH REQUIREMENT  
**Draft ISO H.** —  
**Key elements J.** No such requirement exists; 211.192 requires QCU review and approval. Must correct the premise.

**Rationale.** Premise refuted by positive evidence, not only by absence: 211.192 assigns batch record review and approval to the quality control unit; 211.22(a) gives the QCU that authority. No Part 211 record mentions 'chief quality', 'quality officer' or 'personally sign'.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · No such requirement exists · `Part 211 term search` _(0 hits: chief quality / quality officer / personally sign)_
  - **SUPPORTED** · 211.192 requires QCU review and approval · `211.192` — “shall be reviewed and approved by the quality control unit to determine compliance with all established, approved written procedures before a batch is released or distributed”

**Absence assessment.** scope: 21 CFR Part 211 · method: synonym search (chief quality, quality officer, personally sign, sign, signature, quality control unit) + adjacent 211.186/188/192/22 · result: `NO_RESULT for the role; POSITIVE_CONTRARY_EVIDENCE for who approves` · **absence established: True**  
Signature requirements that do exist (211.186(a), 211.188(a), 211.194(a)(7)-(8)) bind the persons preparing/checking records, not a named officer.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

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

### NC-006 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What is the maximum number of open CAPAs a device manufacturer may have under the QMSR?

**Draft key G.** NO SUCH LIMIT  
**Draft ISO H.** —  
**Key elements J.** No numeric limit exists in the regulation. Must correct the premise.

**Rationale.** No numeric CAPA limit anywhere in Part 820 (whole part inspected) or Title 21 ('open CAPA', 'maximum number of corrective': 0). But QMSR CAPA requirements sit in the incorporated standard, which is not held, so 'no limit in the regulation' is not fully established.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **PARTIALLY_SUPPORTED** · No numeric limit exists in the regulation · `Part 820 + Title 21 search` _(Established for CFR text; not for ISO 13485.)_

**Absence assessment.** scope: Part 820 whole; Title 21 phrases; ISO 13485 NOT available · method: term search · result: `NO_RESULT (CFR)` · **absence established: False**  
Lean ACCEPTED; blocked only by the incorporated standard.

**What the SME must establish:**
1. Controlled source: confirm the corrective-action clause sets no numeric limit.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** absence claim (mandated); materially uncertain (NEEDS_RESEARCH)

---

### NC-007 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Cite the section of Part 111 that requires third-party GMP certification of a dietary supplement facility.

**Draft key G.** NO SUCH REQUIREMENT  
**Draft ISO H.** —  
**Key elements J.** FDA does not require third-party GMP certification; must distinguish voluntary certification from the regulation.

**Rationale.** Within Part 111, absence is established: 'third-party', 'third party', 'accredit', 'audit' all 0; 'certif' hits are only supplier invoices/guarantees/certifications on shipments. But J's broader claim ('FDA does not require third-party GMP certification') meets an adjacent instrument: 21 CFR Part 1 Subpart M (Accreditation of Third-Party Certification Bodies) — 'third-party certification' has 189 hits in Title 21.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · No Part 111 section requires third-party GMP certification · `Part 111 search` _(0 hits for third-party/accredit/audit)_
  - **PARTIALLY_SUPPORTED** · FDA does not require third-party GMP certification · `1 Subpart M` _(Part 1 Subpart M establishes a third-party certification framework; whether any import route makes it mandatory for supplements is not established here.)_

**Absence assessment.** scope: 21 CFR Part 111; Title 21 phrase search · method: synonym search + adjacent instrument check · result: `NO_RESULT in Part 111; ADJACENT INSTRUMENT FOUND` · **absence established: False**  
Established for the question as asked (Part 111); not for J's unqualified statement.

**Column J issue.** J states an unqualified 'FDA does not require' that goes beyond Part 111.

**What the SME must establish:**
1. Check whether Part 1 Subpart M certification can be required for imported dietary supplements (FD&C Act 801(q) is a lead) and whether J should be qualified.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** STATUTE_FDCA · **second review:** absence claim (mandated); materially uncertain (NEEDS_RESEARCH); column J not fully supported by text

---

### NC-008 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What is the FDA-mandated maximum shelf life for a dietary supplement?

**Draft key G.** NO SUCH REQUIREMENT  
**Draft ISO H.** —  
**Key elements J.** No FDA-mandated shelf life; expiration dating is not required for supplements but must be supported if used.

**Rationale.** No 'maximum shelf life' anywhere in Title 21 and Part 111 treats shelf-life dating as optional ('if shelf life dating is used') — positive evidence for the first two J elements. The third ('must be supported if used') is not found: Part 111 has 0 hits for 'stability' and 'expiration'.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · No FDA-mandated shelf life · `Title 21 search` _('maximum shelf life' 0 hits)_
  - **SUPPORTED** · expiration dating is not required for supplements · `111.605(a)` — “You must keep written records required by this part for 1 year past the shelf life date, if shelf life dating is used”
  - **NOT_FOUND_IN_EVIDENCE** · but must be supported if used · `Part 111` _(No Part 111 text found requiring data to support a shelf-life date.)_

**Absence assessment.** scope: Part 111, Part 101, Title 21 phrase · method: synonym search (shelf life, shelf-life, expiration, expiry, stability) · result: `NO_RESULT + conditional wording` · **absence established: True**  
Absence of a mandated maximum is established; J's third element is not.

**Column J issue.** J's 'must be supported if used' is not found in the regulation text.

**What the SME must establish:**
1. Locate the source of 'must be supported if used' (preamble or guidance?), or accept J as imprecise.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** FDA_GUIDANCE_DATABASE · **second review:** absence claim (mandated); materially uncertain (NEEDS_RESEARCH); column J not fully supported by text

---

### NC-009 — proposed **ACCEPTED** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Under FSVP, how often must an importer re-verify a foreign supplier — every six months?

**Draft key G.** FALSE PREMISE — see 21 CFR 1.505/1.506  
**Draft ISO H.** —  
**Key elements J.** Reevaluation at least every three years or upon new information; verification activity frequency is risk-based. Must correct.

**Rationale.** False premise established: no six-month interval anywhere in Part 1 ('every 6 months', 'six months': 0). 1.505(c) requires reevaluation within any 3-year period and promptly on new information. Note: 1.506(d)(2) sets a default annual onsite audit for serious hazards, so 'frequency is risk-based' is incomplete though not wrong.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Reevaluation at least every three years · `1.505(c)(2)` — “If at the end of any 3-year period you have not reevaluated the concerns”
  - **SUPPORTED** · or upon new information · `1.505(c)(1)` — “you must promptly reevaluate the concerns associated”
  - **PARTIALLY_SUPPORTED** · verification activity frequency is risk-based · `1.506(d)(1)(i); 1.506(d)(2)` — “you must conduct or obtain documentation of an onsite audit of the foreign supplier before initially importing the food and at least annually thereafter” _(Frequency is determined per 1.506(d)(1), but serious hazards default to at least annual onsite audits.)_

**Absence assessment.** scope: 21 CFR Part 1 (FSVP) · method: phrase search + 1.505/1.506 text · result: `POSITIVE_CONTRARY_EVIDENCE` · **absence established: True**  
The actual intervals are in the text.

**Column J issue.** J omits the default annual onsite audit for serious hazards (1.506(d)(2)).

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated); column J not fully supported by text

---

### NC-010 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Which provision of 21 CFR Part 11 requires biometric-only authentication for electronic signatures?

**Draft key G.** NO SUCH REQUIREMENT  
**Draft ISO H.** —  
**Key elements J.** Part 11 permits but does not require biometrics; 11.200 addresses both biometric and non-biometric signatures.

**Rationale.** Premise refuted by positive evidence: 11.200(a) provides for signatures not based on biometrics and 11.200(b) for biometric ones — both permitted, neither mandated.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Part 11 permits but does not require biometrics · `11.200(a)` — “Electronic signatures that are not based upon biometrics shall:”
  - **SUPPORTED** · 11.200 addresses both biometric and non-biometric signatures · `11.200(b)` — “Electronic signatures based upon biometrics shall be designed to ensure that they cannot be used by anyone”

**Absence assessment.** scope: 21 CFR Part 11 · method: term search + 11.100/11.200/11.300 text · result: `POSITIVE_CONTRARY_EVIDENCE` · **absence established: True**  


**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

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

### NC-012 — proposed **ACCEPTED** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Cite the CFR section establishing FDA's 'Green Facility' certification program for supplement manufacturers.

**Draft key G.** NO SUCH PROGRAM  
**Draft ISO H.** —  
**Key elements J.** No such program exists. Must decline and not invent a citation.

**Rationale.** 'Green Facility' appears nowhere in Title 21 (exact phrase, both cases) or in any guidance title/body; Part 111 has no 'green' and no program language. For 'cite the CFR section establishing X', a whole-Title-21 exact-name search is the right scope.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · No such program exists. Must decline and not invent a citation. · `Title 21 + guidance table` _(0 hits in both corpora)_

**Absence assessment.** scope: All of Title 21; fda_guidance (1,836 docs) · method: exact-name + synonym search · result: `NO_RESULT` · **absence established: True**  
Established for the CFR. Existence of a non-regulatory FDA program is not established by these corpora (residual risk, low).

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

---

### NC-013 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What are the requirements of 21 CFR Part 1250 Subpart Q?

**Draft key G.** NO SUCH SUBPART  
**Draft ISO H.** —  
**Key elements J.** Must state it does not exist and may describe what Part 1250 actually covers.

**Rationale.** Part 1250 subparts are A–E; there is no Subpart Q.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Part 1250 has no Subpart Q · `cfr_subparts (Part 1250)` — “Sanitation Facilities and Conditions on Vessels” _(Last subpart is E.)_

**Absence assessment.** scope: 21 CFR Part 1250 subpart structure · method: structural listing · result: `NOT_PRESENT` · **absence established: True**  


**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

---

### NC-014 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What does 21 CFR 101.9(k)(5) say about mandatory QR code placement on the Nutrition Facts panel?

**Draft key G.** FALSE PREMISE  
**Draft ISO H.** —  
**Key elements J.** No QR code mandate in 101.9. Must correct the premise rather than describe a nonexistent provision.

**Rationale.** Doubly established: 101.9(k) has paragraphs (k)(1)–(k)(4) only, so (k)(5) does not exist; and no Part 101 record mentions QR, quick response, machine-readable, scannable or bar code. 101.9(k) concerns misleading nutritional representations.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · No QR code mandate in 101.9 · `Part 101 search` _(0 hits for QR / quick response / machine-readable / scannable / bar code)_
  - **SUPPORTED** · Must correct the premise · `101.9(k)` — “A food labeled under the provisions of this section shall be deemed to be misbranded under sections 201(n) and 403(a) of the act if its label or labeling represents, suggests, or implies:”

**Absence assessment.** scope: 21 CFR Part 101; 101.9(k) paragraph structure · method: synonym search + paragraph structure · result: `NOT_PRESENT (paragraph) + NO_RESULT (subject)` · **absence established: True**  
G could also say NO SUCH PARAGRAPH; FALSE PREMISE is still right.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

---

### NC-015 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Summarize FDA's 2023 guidance document 'Artificial Intelligence in Dietary Supplement Manufacturing.'

**Draft key G.** NO SUCH GUIDANCE  
**Draft ISO H.** —  
**Key elements J.** Must state no such guidance is known and offer to search; must not fabricate a summary.

**Rationale.** No guidance title or body in the guidance table matches 'dietary supplement manufacturing'; AI-titled guidance exists only for devices/drugs. The table's coverage is unassessed (42 supplement-sector documents), so this is 'no result found', not 'absence established'.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **PARTIALLY_SUPPORTED** · no such guidance is known; must not fabricate a summary · `fda_guidance search` _(No result in the project's table.)_

**Absence assessment.** scope: fda_guidance table (1,836 docs, issued up to 2026-09-08) · method: title/body search · result: `NO_RESULT` · **absence established: False**  
Guidance absence requires the FDA guidance database itself.

**What the SME must establish:**
1. Search FDA's guidance database directly for the title (and 2023 AI/dietary-supplement guidance generally).

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** FDA_GUIDANCE_DATABASE · **second review:** absence claim (mandated); materially uncertain (NEEDS_RESEARCH)

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

### NC-017 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Which ISO 13485 clause does 21 CFR 820.15 incorporate?

**Draft key G.** NO SUCH SECTION — Part 820 contains no 820.15  
**Draft ISO H.** —  
**Key elements J.** Correct response states that 820.15 does not exist in Part 820.

**Rationale.** 820.15 does not exist; Part 820's sections are 820.1, .3, .5[R], .7, .10, .20–.30[R], .35, .40[R], .45.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · 820.15 does not exist in Part 820 · `Part 820 section list` _(exists=False; not in any reserved range)_

**Absence assessment.** scope: Part 820 · method: section lookup · result: `NOT_PRESENT` · **absence established: True**  


**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** no

---

### NC-018 — proposed **ACCEPTED** (HIGH)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Summarize the requirements of 21 CFR Part 830 Subpart F.

**Draft key G.** NO SUCH SUBPART  
**Draft ISO H.** —  
**Key elements J.** Correct response states that Part 830 has no Subpart F.

**Rationale.** Part 830 subparts are A–E; there is no Subpart F.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · Part 830 has no Subpart F · `cfr_subparts (Part 830)` — “Global Unique Device Identification Database” _(Last subpart is E.)_

**Absence assessment.** scope: Part 830 subpart structure · method: structural listing · result: `NOT_PRESENT` · **absence established: True**  


**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

---

### NC-019 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What is the maximum number of nonconformances per lot permitted under the QMSR before FDA notification is required?

**Draft key G.** NO SUCH REQUIREMENT  
**Draft ISO H.** —  
**Key elements J.** Correct response states that no such threshold exists in Part 820.

**Rationale.** Part 820 (whole) has no threshold ('per lot', 'threshold' 0; 'nonconform' only in the Rework definition). FDA notification is routed by 820.10(b)(3) to Part 803 criteria; Part 803 has 0 'nonconform' hits. But nonconforming-product control is ISO content not held.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · no such threshold exists in Part 820 · `Part 820 whole-part search` _(0 hits)_

**Absence assessment.** scope: Part 820 whole; Part 803 term check; ISO 13485 NOT available · method: term search · result: `NO_RESULT (CFR)` · **absence established: False**  
Lean ACCEPTED; incorporated standard not searchable.

**What the SME must establish:**
1. Controlled source: confirm the nonconforming-product clause sets no numeric notification threshold.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** absence claim (mandated); materially uncertain (NEEDS_RESEARCH)

---

### NC-020 — proposed **ACCEPTED** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Cite the section of 21 CFR Part 4 that requires a combination product manufacturer to hold ISO 13485 certification.

**Draft key G.** NO SUCH REQUIREMENT — FDA does not require ISO 13485 certification  
**Draft ISO H.** —  
**Key elements J.** Correct response states that no such requirement exists and that certification is not required by Part 820 or Part 4.

**Rationale.** Both governing parts were searched in full: 'certif' has 0 hits in Part 4 and 0 in Part 820. Part 4 references ISO 13485 clauses only as compliance content (4.4(b)), never as certification.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · no such requirement exists · `Part 4 + Part 820 search` _('certif' 0 in both)_
  - **SUPPORTED** · certification is not required by Part 820 or Part 4 · `4.4(b)(1)(ii)` — “Design and development. Clause 7.3 and its subclauses of ISO 13485.” _(Part 4 invokes clause content, not certification.)_

**Absence assessment.** scope: 21 CFR Parts 4 and 820 (whole) · method: term search · result: `NO_RESULT over both whole parts` · **absence established: True**  
Both parts are small and were inspected in full.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** none beyond the eCFR snapshot · **second review:** absence claim (mandated)

---

### NC-021 — proposed **ACCEPTED** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** What does ISO 13485 Clause 9.2 require, and how does Part 820 incorporate it?

**Draft key G.** NO SUCH CLAUSE — ISO 13485:2016 ends at Clause 8  
**Draft ISO H.** —  
**Key elements J.** Correct response states that the standard has no Clause 9 and does not invent content for it.

**Rationale.** Clause identity: the internal index's top-level clauses are 1–8, and no Title 21 text references an ISO 13485 clause above 8.5. The index is identity-only and internal, so a quick check of the controlled copy's table of contents is still required.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **SUPPORTED** · the standard has no Clause 9 · `iso_clauses index; Title 21 clause references` _(Index top level 1–8; highest CFR-referenced clause 8.5)_

**Absence assessment.** scope: internal ISO clause index + Title 21 · method: structural listing · result: `NOT_PRESENT (internal index)` · **absence established: True**  
Established at clause-identity level only.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** ISO_13485_CONTROLLED_COPY · **second review:** no

---

### NC-022 — proposed **NEEDS_RESEARCH** (MEDIUM)
*Negative Control · NEGATIVE CONTROL — Hallucination Trap*

**Question.** Summarize FDA's final guidance 'QMSR Certification Body Accreditation Program,' issued March 2026.

**Draft key G.** NO SUCH GUIDANCE  
**Draft ISO H.** —  
**Key elements J.** Correct response states that no such guidance document exists and does not describe its contents.

**Rationale.** No guidance title matches; 'certification body' matches only a 2022 food third-party accreditation guidance; Part 820 has no 'certification body' or 'accreditation'. Guidance-table coverage is unassessed, so this is 'no result found'.

**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**
  - **PARTIALLY_SUPPORTED** · no such guidance document exists · `fda_guidance search; Part 820 search` _(No result)_

**Absence assessment.** scope: fda_guidance table; Part 820 · method: title/body + part search · result: `NO_RESULT` · **absence established: False**  
Requires FDA guidance database check.

**What the SME must establish:**
1. Search FDA's guidance database for the title / any March 2026 QMSR certification-body guidance.

**Uncertainty.** Negative control (G3 is absolute): independent second review required.

**External sources:** FDA_GUIDANCE_DATABASE · **second review:** absence claim (mandated); materially uncertain (NEEDS_RESEARCH)

---
