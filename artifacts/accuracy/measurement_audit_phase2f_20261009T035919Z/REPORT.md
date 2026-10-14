# Measurement Audit Phase 2F: contradiction logic safety (modality scope and negation scope)

Investigation and offline validation only. No production module, test, fixture, benchmark, label, rubric, prompt or configuration changed (§H, hash-verified). Candidate corrections exist only as patched **copies** in `work/variants/`, loaded into separate processes. No 300-question run, no LLM judge, no new retrieval. The live server was not touched.

**Evidence provenance.**

| Dataset | Rows | Evidence |
|---|--:|---|
| **F60** (`frozen_inputs_60.json`) | 60 | **LEGACY_RECONSTRUCTED**: none of it is exact-evidence. This includes H-003 and D-009. |
| **GUIDE8** (`tests/fixtures/accuracy_guidance_rows.json`) | 8 | Test fixture; guidance text present. The only place Priority-2 guidance authority is exercised on real rows. |
| **REAL17** (`tests/fixtures/accuracy_real_rows.json`) | 17 | Test fixture |

Every dataset was run under both aligners: 170 row-runs and **5,833 operator comparisons, all recorded** by instrumenting `operators.compare`.

## A. Executive decision

**NEEDS A NARROW REFINEMENT.**

Both defects are real and reproduced from the actual code (§B). Each has one exact cause (§D). A two-rule correction, **`VT_targeted`**, fixes exactly H-003 and D-009 and changes nothing else, measured on every recorded comparison, every claim and every answer:
1. Do not read a bare, copula-less "not required" as negation.
2. A permission over a channel or means is not a modal conflict with a mandate for the same act that names no means.

`VT_targeted` keeps:
- 19/19 genuine-contradiction controls;
- 44/44 real negation and modality readings on the frozen data;
- 6/6 verbatim operator-reading tests;
- 18/18 invented-condition conflicts;
- all Priority-2 guidance tests and all Phase 2D gate decisions;
- the full suite: **1824 passed, 1 skipped, 0 failed**.

**Implementing it in production is justified.** Four conditions apply; they are in §G.

**The broader negation-scope sets are NOT safe.** These cover relative clauses, purpose complements and nouns. They remove 65–76 false operator conflicts, but they **break the locked Phase 2D gate**:
- one new false support: F-007's wrong "hazard analysis" list head;
- one lost safe support: F-009 para40, which fails a Phase 2D test.

Many of today's supports and blocks rest on two false negations that cancel each other out. Removing one of them changes support decisions.

## B. Defect reproduction (actual evaluator logic; trace in `work/traces/`)

### Case A: H-003 (human N=1), two claims, both aligners

| | |
|---|---|
| **Claim 1** | "If you are an authorized user of CBP's ABI/ACE/ITDS, you may submit prior notice through either the ABI/ACE/ITDS interface or FDA PNSI." |
| **Claim 2** | "If you are not an authorized user, you may submit prior notice through FDA PNSI." |
| **Evidence** | 21 CFR 1.279(a), binding eCFR, the only aligned candidate: "(a) Except as provided in paragraph (c) of this section, you must submit the prior notice to FDA and the prior notice submission must be confirmed by FDA for review as follows:" |
| **Claim operators** | `main_clause` = "you may submit prior notice through either the ABI/ACE/ITDS interface or FDA PNSI." (the "If …," condition is removed correctly); strength **permissive** (deontic: "you" precedes "may"); polarity affirm |
| **Evidence operators** | `main_clause` = "(a) you must submit the prior notice to FDA and … confirmed by FDA for review as follows:"; strength **mandatory**; polarity affirm |
| **Conflict** | `compare()` (operators.py:535): (permissive, mandatory) ∈ `_STRENGTH_CONFLICTS` gives "the answer states a permissive requirement where the evidence is mandatory" |
| **Verdict before** | the single candidate is conflicted, so `judge()` finds no clean candidate (verdicts.py:276–280) and returns **CONTRADICTED**, under both aligners. The answer is **incorrect, 0** (substantive_correctness fail). |
| **Why it is not a contradiction** | "may submit … through either A or B" permits a **channel** for the act. It does not make the act optional. 1.279(a) mandates the act and names no channel, so the two statements are compatible. |
| **Correct verdict** | **UNVERIFIABLE.** The channel rule (ABI/ACE/ITDS vs PNSI) is not in the captured text, so the claim cannot be supported either. |

### Case B: D-009 (human N=0), both aligners

| | |
|---|---|
| **Claim** | "Written procedures shall include control of microbiological contamination to prevent objectionable microorganisms in drug products not required to be sterile." |
| **Evidence** | 21 CFR 211.113(a), binding eCFR, ranked **first** by both aligners: "(a) Appropriate written procedures, designed to prevent objectionable microorganisms in drug products not required to be sterile, shall be established and followed." |
| **Claim operators** | `main_clause` = "Written procedures shall include control of microbiological contamination": the purpose clause "to prevent …" runs to the end and contains no modal, so it is removed. Strength mandatory, polarity **affirm**. |
| **Evidence operators** | The purpose span "to prevent …" (operators.py:277, "runs to the end of its sentence") **swallows the modal "shall be established"**. `main_clause` then hits its fallback (operators.py:288–289: "the condition carried the obligation; judge the whole sentence") and returns the **whole sentence**. In it, `_NEGATE_RE`'s bare alternative `\bnot\s+required\b` matches "drug products **not required** to be sterile". Strength mandatory, polarity **negate**. |
| **Conflict** | `compare()` (operators.py:546): affirm ≠ negate gives "the answer is affirm where the evidence is negate" |
| **Verdict before** | 211.113(a) is removed from `clean` (verdicts.py:276). The gate examines the next candidate (211.100(a) semantic, 211.101 lexical) and blocks it on "contamin, microbiological, …". Result: **UNVERIFIABLE**. This was Phase 2E false negative #12. |
| **Why it is not a contradiction** | "not required to be sterile" modifies "drug products" (which products). It does not negate the duty, which is "shall be established and followed". The claim contains the same phrase and was read as affirm only because its purpose span happened to cover it. |
| **Correct verdict** | **Supported** by 211.113(a), as Phase 2E established. |

## C. Frozen control set

Built from (1) **every conflicting operator comparison** the evaluator actually made on the frozen data (156 unique claim/evidence pairs, hand-reviewed), and (2) the repository's **existing tests**. Nothing is fabricated: frozen controls use captured text verbatim, test controls use the tests' strings verbatim. Full records: `work/controls_frozen.json`, `controls_tests.json`, `controls_readings.json`.

| Class | Pairs | Expected |
|---|--:|---|
| False conflict, in scope (modality / negation scope) | 88 | the false operator conflict disappears; the claim's verdict becomes what the evidence supports (H-003: UNVERIFIABLE; D-009: supported) |
| Real operator difference vs an unrelated passage (preservation controls) | 44 | the real negation / modality reading is kept |
| Invented-condition (Priority-2 rule, out of scope) | 18 | unchanged |
| Claimed conditional exception vs general rule (not a scope defect) | 6 | reported only |
| Genuine contradictions from existing tests | 19 | the conflict (and the test's CONTRADICTED / INCORRECT verdict) is kept |
| Verbatim operator-reading assertions from tests | 6 | reading kept |

### C.1 False-contradiction controls (all 88; VT = VT_targeted, VT2 = VT2_targeted_span)

| ID | Rows (provenance) | Mechanism | Claim | Evidence | Base conflict | Expected | VT | VT2 |
|---|---|---|---|---|---|---|---|---|
| P005 | F60:B-002 (LEGACY_RECONSTRUCTED evidence… | modality: permission over a means/channel | Under this circumstance, a person who elects to submit reports to the applicant … | To avoid unnecessary duplication in the submission to FDA of reports required by paragraph… | strength | no strength conflict | remains | removed |
| P130 | F60:H-003 (LEGACY_RECONSTRUCTED evidence… | modality: permission over a means/channel | If you are an authorized user of CBP’s ABI/ACE/ITDS, you may submit prior notice… | (a) Except as provided in paragraph (c) of this section, you must submit the prior notice … | strength | no strength conflict | removed | removed |
| P131 | F60:H-003 (LEGACY_RECONSTRUCTED evidence… | modality: permission over a means/channel | If you are not an authorized user, you may submit prior notice through FDA PNSI. | (a) Except as provided in paragraph (c) of this section, you must submit the prior notice … | strength | no strength conflict | removed | removed |
| P000 | F60:B-001, REAL17:B-001 (LEGACY_RECONSTR… | negation: bare 'not required' (reduced relative) | Precautions shall be taken to exclude extraneous infectious agents from manufact… | All rooms and work areas where products are manufactured or stored shall be kept orderly, … | polarity | no polarity conflict | removed | removed |
| P001 | F60:B-001, REAL17:B-001 (LEGACY_RECONSTR… | negation: bare 'not required' (reduced relative) | Work rooms shall be well lighted and ventilated. | All rooms and work areas where products are manufactured or stored shall be kept orderly, … | polarity | no polarity conflict | removed | removed |
| P033 | F60:D-001, REAL17:D-001 (LEGACY_RECONSTR… | negation: bare 'not required' (reduced relative) | [7] 21 CFR 211.113(a) [7]: Appropriate written procedures, designed to prevent o… | Written procedures describing the warehousing of drug products shall be established and fo… | polarity | no polarity conflict | removed | removed |
| P034 | F60:D-001, REAL17:D-001 (LEGACY_RECONSTR… | negation: bare 'not required' (reduced relative) | [7] 21 CFR 211.113(a) [7]: Appropriate written procedures, designed to prevent o… | There shall be written procedures designed to assure that correct labels, labeling, and pa… | polarity | no polarity conflict | removed | removed |
| P036 | F60:D-001, REAL17:D-001 (LEGACY_RECONSTR… | negation: bare 'not required' (reduced relative) | [5] 21 CFR 211.110(a) [5]: To assure batch uniformity and integrity of drug prod… | (a) Appropriate written procedures, designed to prevent objectionable microorganisms in dr… | polarity | no polarity conflict | removed | removed |
| P037 | F60:D-001, REAL17:D-001 (LEGACY_RECONSTR… | negation: bare 'not required' (reduced relative) | [7] 21 CFR 211.113(a) [7]: Appropriate written procedures, designed to prevent o… | (a) To assure batch uniformity and integrity of drug products, written procedures shall be… | polarity | no polarity conflict | removed | removed |
| P045 | F60:D-009 (LEGACY_RECONSTRUCTED evidence… | negation: bare 'not required' (reduced relative) | Written procedures shall include control of microbiological contamination to pre… | (a) Appropriate written procedures, designed to prevent objectionable microorganisms in dr… | polarity | no polarity conflict | removed | removed |
| P052 | F60:D-019 (LEGACY_RECONSTRUCTED evidence… | negation: bare 'not required' (reduced relative) | Time limitations on production shall be established to ensure quality, and micro… | (a) Appropriate written procedures, designed to prevent objectionable microorganisms in dr… | polarity | no polarity conflict | removed | removed |
| P012 | F60:B-005 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Supplies and reagents used in processing must be stored safely and orderly [1]. | (c) Representative samples of each lot of the following reagents or solutions shall be tes… | polarity | no polarity conflict | remains | remains |
| P013 | F60:B-005 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Equipment used in blood and blood component processing must be clean and orderly… | (c) Representative samples of each lot of the following reagents or solutions shall be tes… | polarity | no polarity conflict | remains | remains |
| P015 | F60:B-005 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Equipment used in blood and blood component processing must be clean and orderly… | (c) Representative samples of each lot of the following reagents or solutions shall be tes… | polarity | no polarity conflict | remains | remains |
| P035 | F60:D-001, REAL17:D-001 (LEGACY_RECONSTR… | negation: inside a relative clause | [8] 21 CFR 211.115(a) [8]: Written procedures shall be established and followed … | (a) To assure batch uniformity and integrity of drug products, written procedures shall be… | polarity | no polarity conflict | remains | remains |
| P038 | F60:D-001, REAL17:D-001 (LEGACY_RECONSTR… | negation: inside a relative clause | [8] 21 CFR 211.115(a) [8]: Written procedures shall be established and followed … | Written procedures shall be established, and followed, describing the distribution of drug… | polarity | no polarity conflict | remains | remains |
| P041 | F60:D-007 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | The procedures shall establish and follow written procedures for reprocessing ba… | Any deviation from the written specifications, standards, sampling plans, test procedures,… | polarity | no polarity conflict | remains | remains |
| P042 | F60:D-007 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | The procedures shall establish and follow written procedures for reprocessing ba… | (a) The establishment of any specifications, standards, sampling plans, test procedures, o… | polarity | no polarity conflict | remains | remains |
| P046 | F60:D-009 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Written procedures shall establish a system for reprocessing batches that do not… | Any deviation from the written specifications, standards, sampling plans, test procedures,… | polarity | no polarity conflict | remains | remains |
| P047 | F60:D-009 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Written procedures shall establish a system for reprocessing batches that do not… | (a) The establishment of any specifications, standards, sampling plans, test procedures, o… | polarity | no polarity conflict | remains | remains |
| P048 | F60:D-009 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Written procedures shall also include general requirements for specifications, s… | (a) Written procedures shall be established and followed prescribing a system for reproces… | polarity | no polarity conflict | remains | remains |
| P057 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.126(a) requires a food safety plan. | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P059 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.139 mandates a recall plan for hazards requiring preventive control… | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P060 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.139 mandates a recall plan for hazards requiring preventive control… | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P062 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.150(a) requires corrective action procedures. | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P063 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.150(a) requires corrective action procedures. | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P071 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.130(a) mandates a hazard analysis. | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P079 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.165(a) mandates verification of implementation and effectiveness. | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P080 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | - 21 CFR 117.165(a) mandates verification of implementation and effectiveness. | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P083 | F60:F-004 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | The grounds must be maintained in a condition that will protect against the cont… | (4) Removing all unsecured jewelry and other objects that might fall into food, equipment,… | polarity, strength | no polarity conflict | remains | remains |
| P092 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: inside a relative clause | Under Part 117, a process preventive control is a measure implemented to prevent… | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P102 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: inside a relative clause | The preventive controls must be implemented and verified as appropriate to ensur… | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P107 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: inside a relative clause | The implementation records must be maintained as required in § 117.1(a). | (4) Removing all unsecured jewelry and other objects that might fall into food, equipment,… | polarity, strength | no polarity conflict | remains | remains |
| P110 | F60:F-012 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Part 117 requires a qualified facility to maintain grounds in a condition that w… | (4) Removing all unsecured jewelry and other objects that might fall into food, equipment,… | polarity, strength | no polarity conflict | remains | remains |
| P116 | F60:F-012 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Part 117 requires a qualified facility to maintain grounds in a condition that w… | (3) Washing hands thoroughly (and sanitizing if necessary to protect against contamination… | polarity, strength | no polarity conflict | remains | removed |
| P118 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | The program requires the establishment to ensure the lowest possible defect leve… | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P119 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | The program requires the establishment to ensure the lowest possible defect leve… | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P120 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | It also mandates the provision of assurances and the requirement for recall plan… | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P122 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | It also mandates the provision of assurances and the requirement for recall plan… | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P124 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Each provision in Part 117 requires specific sub-requirements to ensure the effe… | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P125 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Each provision in Part 117 requires specific sub-requirements to ensure the effe… | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P127 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Each provision in Part 117 requires specific sub-requirements to ensure the effe… | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P128 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Each provision in Part 117 requires specific sub-requirements to ensure the effe… | (b) The written recall plan must include procedures that describe the steps to be taken, a… | polarity | no polarity conflict | remains | remains |
| P129 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside a relative clause | Each provision in Part 117 requires specific sub-requirements to ensure the effe… | For food with a hazard requiring a preventive control: (a) You must establish a written re… | polarity | no polarity conflict | remains | remains |
| P058 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | - 21 CFR 117.135(a)(1) requires preventive controls to minimize or prevent hazar… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P061 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | - 21 CFR 117.140(a) requires preventive control management components. | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P065 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | - 21 CFR 117.206(a) requires temperature control activities for unexposed packag… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P075 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | - 21 CFR 117.137 requires written assurances to act consistently with them. | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P076 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | - 21 CFR 117.139 mandates a recall plan for hazards requiring preventive control… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P078 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | - 21 CFR 117.160(a) requires validation of preventive controls. | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P088 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: inside 'provide assurances that ...' | Under Part 117, a process preventive control is a measure implemented to prevent… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P089 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: inside 'provide assurances that ...' | Under Part 117, a process preventive control is a measure implemented to prevent… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P091 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: inside 'provide assurances that ...' | Under Part 117, a process preventive control is a measure implemented to prevent… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P101 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: inside 'provide assurances that ...' | The preventive controls must be implemented and verified as appropriate to ensur… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | invented_condition, polarity | no polarity conflict | remains | remains |
| P117 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | The program requires the establishment to ensure the lowest possible defect leve… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P121 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | It also mandates the provision of assurances and the requirement for recall plan… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P123 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | Each provision in Part 117 requires specific sub-requirements to ensure the effe… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P126 | F60:F-022 (LEGACY_RECONSTRUCTED evidence… | negation: inside 'provide assurances that ...' | Each provision in Part 117 requires specific sub-requirements to ensure the effe… | (a)(1) You must identify and implement preventive controls to provide assurances that any … | polarity | no polarity conflict | remains | remains |
| P064 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: the noun 'exemption(s)' | - 21 CFR 117.201(a) requires modified requirements for a qualified facility. | (a) FDA may withdraw a qualified facility exemption under § 117.5(a): | polarity, strength | no polarity conflict | remains | remains |
| P067 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: the noun 'exemption(s)' | - 21 CFR 117.251(a) states that FDA may withdraw an exemption. | A qualified facility must submit the following attestations to FDA: | polarity, strength | no polarity conflict | remains | remains |
| P081 | F60:F-003 (LEGACY_RECONSTRUCTED evidence… | negation: the noun 'exemption(s)' | - 21 CFR 117.201(a) requires modified requirements for a qualified facility. | (a) An FDA Division Director in whose division the qualified facility is located (or, in t… | polarity | no polarity conflict | remains | remains |
| P106 | F60:F-009, REAL17:F-009 (LEGACY_RECONSTR… | negation: the noun 'exemption(s)' | The issuance of an order to withdraw a qualified facility exemption is approved … | A qualified facility must submit the following attestations to FDA: | polarity | no polarity conflict | remains | remains |
| P113 | F60:F-012 (LEGACY_RECONSTRUCTED evidence… | negation: the noun 'exemption(s)' | Part 117 requires FDA to approve an order to withdraw a qualified facility exemp… | A qualified facility must submit the following attestations to FDA: | polarity | no polarity conflict | remains | remains |
| P135 | GUIDE8:H-006 (test fixture evidence) | negation: the noun 'exemption(s)' | The recordkeeping requirements apply to all persons subject to the Food Traceabi… | 22 S. What Records Must I Maintain if I Am Subject to FDA’s Food Facility Registration Req… | polarity | no polarity conflict | remains | remains |
| P136 | GUIDE8:H-006 (test fixture evidence) | negation: the noun 'exemption(s)' | The recordkeeping requirements apply to all persons subject to the Food Traceabi… | However, records that satisfy the requirements of the Food Traceability Rule but that are … | polarity | no polarity conflict | remains | remains |
| P138 | GUIDE8:H-006 (test fixture evidence) | negation: the noun 'exemption(s)' | The recordkeeping requirements apply to all persons subject to the Food Traceabi… | 20 P. What Records Must I Keep When I Receive a Food on the FTL from a Person Who Is Not S… | polarity | no polarity conflict | remains | remains |
| P139 | GUIDE8:H-006 (test fixture evidence) | negation: the noun 'exemption(s)' | The recordkeeping requirements apply to all persons subject to the Food Traceabi… | (§ 1.1345(a), (c)) .................. 20 P. What Records Must I Keep When I Receive a Food… | polarity | no polarity conflict | remains | remains |
| P043 | F60:D-009 (LEGACY_RECONSTRUCTED evidence… | negation: 'are not limited to' | These procedures shall be approved by the appropriate organizational units and r… | Such control procedures shall include, but are not limited to, the following, where approp… | polarity | no polarity conflict | remains | remains |
| P006 | F60:B-003 (LEGACY_RECONSTRUCTED evidence… | negation: inside a condition the span rule misses | Under Part 601, a biologics license application must be approved upon examinatio… | A biological product undergoing development, but not yet ready for a biologics license, ma… | polarity, strength | no polarity conflict | remains | remains |
| P016 | F60:C-002 (LEGACY_RECONSTRUCTED evidence… | negation: inside a condition the span rule misses | The declaration of net quantity shall be in terms of weight, measure, numerical … | Whenever the Commissioner determines for a specific packaged cosmetic that an existing pra… | polarity | no polarity conflict | remains | remains |
| P018 | F60:C-002 (LEGACY_RECONSTRUCTED evidence… | negation: inside a condition the span rule misses | The declaration of net quantity shall be in terms of weight, measure, numerical … | If there is a firmly established, general consumer usage and trade custom of declaring the… | polarity | no polarity conflict | remains | remains |
| P019 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | Under Part 700, prohibited or restricted ingredients in cosmetics include vinyl … | (a) Vinyl chloride has been used as an ingredient in cosmetic aerosol products including h… | polarity | no strength/polarity conflict (recital states no rule) | remains | remains |
| P020 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | Under Part 700, prohibited or restricted ingredients in cosmetics include methyl… | Based on these findings and on estimates of human exposure from the customary use of hair … | polarity | no strength/polarity conflict (recital states no rule) | remains | remains |
| P021 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | Under Part 700, prohibited or restricted ingredients in cosmetics include methyl… | In a 2-year animal inhalation study sponsored by the National Toxicology Program, methylen… | polarity | no strength/polarity conflict (recital states no rule) | remains | remains |
| P022 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of methylene chloride as an ingredient in aerosol cosmetic products is p… | Based on these findings and on estimates of human exposure from the customary use of hair … | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P023 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of methylene chloride as an ingredient in aerosol cosmetic products is p… | In a 2-year animal inhalation study sponsored by the National Toxicology Program, methylen… | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P024 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of vinyl chloride as an ingredient in aerosol products is prohibited [3]… | (a) Vinyl chloride has been used as an ingredient in cosmetic aerosol products including h… | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P025 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of vinyl chloride as an ingredient in aerosol products is prohibited [3]… | Where such aerosol products are used in the confines of a small room, as is often the case… | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P026 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of vinyl chloride as an ingredient in aerosol products is prohibited [3]… | Where such aerosol products are used in the confines of a small room, as is often the case… | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P027 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of bithionol in cosmetics is prohibited [1]. | It is, therefore, the view of the Food and Drug Administration that bithionol is a deleter… | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P028 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of bithionol in cosmetics is prohibited [1]. | It is, therefore, the view of the Food and Drug Administration that bithionol is a deleter… | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P029 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | Under Part 700, prohibited or restricted ingredients in cosmetics include vinyl … | Where such aerosol products are used in the confines of a small room, as is often the case… | polarity | no strength/polarity conflict (recital states no rule) | remains | remains |
| P030 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | Under Part 700, prohibited or restricted ingredients in cosmetics include vinyl … | Where such aerosol products are used in the confines of a small room, as is often the case… | polarity | no strength/polarity conflict (recital states no rule) | remains | remains |
| P031 | F60:C-004, REAL17:C-004 (LEGACY_RECONSTR… | modality: epistemic 'may' read as permission | The use of methylene chloride as an ingredient in aerosol cosmetic products is p… | (a) Vinyl chloride has been used as an ingredient in cosmetic aerosol products including h… | polarity, strength | no strength/polarity conflict (recital states no rule) | remains | remains |
| P085 | F60:F-004 (LEGACY_RECONSTRUCTED evidence… | modality: epistemic 'may' read as permission | The grounds must be maintained in a condition that will protect against the cont… | (3) Washing hands thoroughly (and sanitizing if necessary to protect against contamination… | strength | no strength/polarity conflict (recital states no rule) | remains | removed |
| P114 | F60:F-012 (LEGACY_RECONSTRUCTED evidence… | modality: epistemic 'may' read as permission | Part 117 requires a qualified facility to maintain grounds in a condition that w… | (3) Washing hands thoroughly (and sanitizing if necessary to protect against contamination… | strength | no strength/polarity conflict (recital states no rule) | remains | removed |
| P115 | F60:F-012 (LEGACY_RECONSTRUCTED evidence… | modality: epistemic 'may' read as permission | Part 117 requires a qualified facility to maintain grounds in a condition that w… | (2) Maintaining adequate personal cleanliness. (3) Washing hands thoroughly (and sanitizin… | strength | no strength/polarity conflict (recital states no rule) | remains | removed |
| P002 | F60:B-001, REAL17:B-001 (LEGACY_RECONSTR… | modality: participle read as recommendation | If such rooms are used for other purposes, they shall be cleaned and prepared pr… | (j) A product is deemed applicable to the prevention, treatment, or cure of diseases or in… | strength | no strength conflict | remains | remains |

### C.2 Genuine-contradiction and reading controls (existing tests)

| ID | Source test | Kind | Claim | Evidence | Authority | Expected |
|---|---|---|---|---|---|---|
| G01 | test_3_wrong_modal_strength_is_contradicted | must vs may (wrong modal) | Each manufacturer of any class III device may establish procedures to control th… | Each manufacturer of any class III or class II device shall establish and mainta… | binding_ | strength → CONTRADICTED |
| G02 | test_3b_stating_a_permission_as_a_requirement_is_also_contra… | permission stated as a requirement | Each manufacturer shall establish a quality audit schedule. | Each manufacturer may establish a quality audit schedule at its own discretion. | binding_ | strength → CONTRADICTED |
| G03 | test_4_wrong_polarity_is_contradicted | prohibited (may not) vs permitted | A device may be released for distribution until the acceptance activities are co… | A device may not be released for distribution until the acceptance activities ar… | binding_ | polarity → CONTRADICTED |
| G04 | test_5_wrong_numeric_value_is_contradicted | conflicting time period | Each manufacturer shall review and evaluate all complaints within 90 days of rec… | Each manufacturer shall review and evaluate all complaints within 30 days of rec… | binding_ | quantity → CONTRADICTED |
| G05 | test_6_wrong_actor_is_contradicted | different duty holder | Each manufacturer shall submit a report to FDA no later than 30 calendar days af… | Each importer shall submit a report to FDA no later than 30 calendar days after … | binding_ | actor → CONTRADICTED |
| G06 | test_7b_inventing_a_condition_is_contradicted | conflicting applicability condition (invented) | Each manufacturer of any class III device shall establish and maintain procedure… | Each manufacturer of any class III or class II device shall establish and mainta… | binding_ | invented_condition → CONTRADICTED |
| G07 | test_4_an_actual_negation_is_still_a_contradiction[binding] | must vs must not | The manufacturer must submit the report to FDA. | The manufacturer must not submit the report to FDA. | binding_ | polarity → CONTRADICTED |
| G08 | test_4_an_actual_negation_is_still_a_contradiction[guidance] | must vs must not (guidance) | The manufacturer must submit the report to FDA. | The manufacturer must not submit the report to FDA. | guidance | polarity → CONTRADICTED |
| G09 | test_5_prohibited_versus_permitted_is_still_a_contradiction[… | required/prohibited vs permitted | The use of vinyl chloride in cosmetic aerosol products is prohibited. | The use of vinyl chloride in cosmetic aerosol products is permitted. | binding_ | polarity → CONTRADICTED |
| G10 | test_5_prohibited_versus_permitted_is_still_a_contradiction[… | prohibited vs permitted (guidance) | The use of vinyl chloride in cosmetic aerosol products is prohibited. | The use of vinyl chloride in cosmetic aerosol products is permitted. | guidance | polarity → CONTRADICTED |
| G11 | test_1_should_in_guidance_does_not_contradict_must (binding … | must vs should in regulation | Each manufacturer must maintain complaint files. | Manufacturers should maintain complaint files. | binding_ | strength → CONTRADICTED |
| G12 | test_a_modal_mismatch_against_binding_regulation_is_still_a_… | shall vs may (verbatim 820.30(a) text) | Each manufacturer of any class III or class II device may establish procedures t… | Each manufacturer of any class III or class II device shall establish procedures… | binding_ | strength → CONTRADICTED |
| G13 | test_a_duty_on_a_different_regulated_party_is_still_a_contra… | different duty holder | Each manufacturer shall submit a report to FDA no later than 30 calendar days af… | Each importer shall submit a report to FDA no later than 30 calendar days after … | binding_ | actor → CONTRADICTED |
| G14 | test_a_different_number_is_still_a_contradiction_against_gui… | conflicting time limit (guidance) | Complaints must be evaluated within 90 days of receipt. | FDA recommends that complaints be evaluated within 30 days of receipt. | guidance | quantity → CONTRADICTED |
| G15 | test_an_invented_condition_is_judged_only_against_a_passage_… | requirement vs invented exception | Records must be kept for two years, except when the product is exported. | Records must be kept for two years. | binding_ | invented_condition → CONTRADICTED |
| G16 | test_a_guidance_exclusion_is_not_the_governing_provision_exc… | applies vs does not apply (applicability / exception) | The recordkeeping requirements apply to farms that sell directly to consumers. | The recordkeeping requirements do not apply to farms that sell directly to consu… | binding_ | verdict-level (suite) → INCORRECT answer |
| G17 | test_14_a_close_match_that_says_the_opposite_is_contradicted… | shall not vs may (discard) | Records may be discarded and retained for a period of two years. | Records shall not be discarded and shall be retained for a period of two years. | binding_ | polarity → CONTRADICTED |
| G18 | test_12_multi_claim_answer_mixing_correct_and_incorrect | shall vs may (verbatim 820.50(a) text) | 21 CFR 820.50(a): Each manufacturer may establish procedures to ensure that all … | Each manufacturer shall establish and maintain procedures to ensure that all pur… | binding_ | strength → CONTRADICTED |
| G19 | test_a_conflict_outranks_every_amount_of_surface_agreement | verbatim except the modal | Each manufacturer of any class III or class II device may establish procedures t… | Each manufacturer of any class III or class II device shall establish and mainta… | binding_ | strength → CONTRADICTED |

| ID | Source test | Text | Expected polarity |
|---|---|---|---|
| R01 | test_accuracy_guidance_logic.py::test_6 | Records must not be altered, so that the audit trail is complete. | negate |
| R02 | test_accuracy_guidance_logic.py::test_6 | The process shall be validated where the results cannot be fully verified. | affirm |
| R03 | test_accuracy_guidance_logic.py::test_6 | Electronic signatures must be linked to their respective electronic records to ensure that the signa… | affirm |
| R04 | test_accuracy_guidance_logic.py::test_6b | The manufacturer shall ensure that devices are not adulterated. | affirm |
| R05 | test_accuracy_guidance_logic.py::test_6b | The manufacturer must not ship devices that are adulterated. | negate |
| R06 | test_accuracy_guidance_logic.py::test_6 | The procedure is designed to ensure that the signature cannot be excised. | not negate |

### C.3 Preservation controls (real operator differences against unrelated passages) and claimed exceptions

| ID | Rows | Class | Claim | Evidence | Real operator difference |
|---|---|---|---|---|---|
| P003 | F60:B-001, REAL17:B-001 (LEGAC… | UNREL_REAL | 21 CFR 600.21 [7]: The inspection of an establishment for which a biol… | (ll) Complete response letter means a written communication to an appl… | polarity |
| P004 | F60:B-001, REAL17:B-001 (LEGAC… | UNREL_REAL | Biological products samples must not be sent to this address but must … | Samples retained as required in this section shall be in addition to s… | polarity |
| P007 | F60:B-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | A biologics license issued to a manufacturer covering all locations of… | For persons and places authorized under this section to conduct the in… | invented_condition, polarity |
| P008 | F60:B-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | It does not apply to radiopharmaceuticals intended for therapeutic pur… | In situations where a particular radiopharmaceutical is proposed for b… | polarity |
| P009 | F60:B-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | For foreign establishments and products, samples for each importation … | Sponsors of licensed biological products shall submit the following in… | actor |
| P010 | F60:B-005 (LEGACY_RECONSTRUCTE… | UNREL_REAL | Under Part 606, blood and blood components must comply with CGMP requi… | (a) In all instances, except clinical investigations, standard operati… | polarity |
| P011 | F60:B-005 (LEGACY_RECONSTRUCTE… | UNREL_REAL | Equipment used in blood and blood component processing must be clean a… | All supplies and reagents used in the collection, processing, compatib… | polarity |
| P014 | F60:B-005 (LEGACY_RECONSTRUCTE… | UNREL_REAL | Equipment used in blood and blood component processing must be clean a… | Where any defect is observed, the container shall not be used, or, if … | polarity |
| P017 | F60:C-002 (LEGACY_RECONSTRUCTE… | UNREL_REAL | The declaration of net quantity shall be in terms of weight, measure, … | If there is a firmly established, general consumer usage and trade cus… | strength |
| P032 | F60:D-001, REAL17:D-001 (LEGAC… | UNREL_REAL | Such deviation shall be justified and documented. | Deviation from this requirement is permitted if such deviation is temp… | strength |
| P039 | F60:D-002, REAL17:D-002 (LEGAC… | UNREL_REAL | - [4] Adequate laboratory facilities for the testing and approval (or … | The quality control unit shall be responsible for approving or rejecti… | actor |
| P040 | F60:D-002, REAL17:D-002 (LEGAC… | UNREL_REAL | - [4] Adequate laboratory facilities for the testing and approval (or … | (c) The quality control unit shall have the responsibility for approvi… | actor |
| P044 | F60:D-009 (LEGACY_RECONSTRUCTE… | UNREL_REAL | Equipment identification shall be properly maintained to indicate the … | Identification need not be applied to each individual container but sh… | polarity |
| P056 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | The CGMP requirements under Part 117 Subpart B include circumstances i… | (a) One or more preventive controls qualified individuals must do or o… | polarity |
| P066 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - 21 CFR 117.251(a) states that FDA may withdraw an exemption. | (a) An FDA Division Director in whose division the qualified facility … | strength |
| P068 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | The CGMP requirements under Part 117 Subpart B include circumstances i… | You must verify that the preventive controls are consistently implemen… | polarity |
| P069 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | The CGMP requirements under Part 117 Subpart B include circumstances i… | You must verify that the preventive controls are consistently implemen… | polarity |
| P070 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - 21 CFR 117.130(a) mandates a hazard analysis. | If you are a manufacturer/processor, you are not required to implement… | polarity |
| P072 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - 21 CFR 117.136(a) states that preventive controls are not required i… | (a) You must validate that the preventive controls identified and impl… | polarity |
| P073 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - 21 CFR 117.136(a) states that preventive controls are not required i… | You must verify that the preventive controls are consistently implemen… | polarity |
| P074 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - 21 CFR 117.136(a) states that preventive controls are not required i… | You must verify that the preventive controls are consistently implemen… | polarity |
| P077 | F60:F-003 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - 21 CFR 117.140(a) requires preventive control management components. | If you are a manufacturer/processor, you are not required to implement… | polarity |
| P082 | F60:F-004 (LEGACY_RECONSTRUCTE… | UNREL_REAL | The grounds must be maintained in a condition that will protect agains… | If such hand jewelry cannot be removed, it may be covered by material … | strength |
| P084 | F60:F-004 (LEGACY_RECONSTRUCTE… | UNREL_REAL | The grounds must be maintained in a condition that will protect agains… | If such hand jewelry cannot be removed, it may be covered by material … | strength |
| P090 | F60:F-009, REAL17:F-009 (LEGAC… | UNREL_REAL | Under Part 117, a process preventive control is a measure implemented … | If you are a manufacturer/processor, you are not required to implement… | polarity |
| P105 | F60:F-009, REAL17:F-009 (LEGAC… | UNREL_REAL | The implementation records must be maintained as required in § 117.1(a… | If such hand jewelry cannot be removed, it may be covered by material … | strength |
| P108 | F60:F-009, REAL17:F-009 (LEGAC… | UNREL_REAL | The implementation records must be maintained as required in § 117.1(a… | If such hand jewelry cannot be removed, it may be covered by material … | strength |
| P109 | F60:F-012 (LEGACY_RECONSTRUCTE… | UNREL_REAL | Part 117 requires a qualified facility to maintain grounds in a condit… | If such hand jewelry cannot be removed, it may be covered by material … | strength |
| P111 | F60:F-012 (LEGACY_RECONSTRUCTE… | UNREL_REAL | Part 117 requires a qualified facility to maintain grounds in a condit… | If such hand jewelry cannot be removed, it may be covered by material … | strength |
| P112 | F60:F-012 (LEGACY_RECONSTRUCTE… | UNREL_REAL | Part 117 requires FDA to approve an order to withdraw a qualified faci… | (a) FDA may withdraw a qualified facility exemption under § 117.5(a): | strength |
| P132 | F60:M-034 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - A Device Master Record is a record of the device's information, incl… | If an investigation has already been performed for a similar complaint… | polarity |
| P133 | F60:M-034 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - A Device History Record is a record of the device's history, includi… | If an investigation has already been performed for a similar complaint… | polarity |
| P134 | F60:M-034 (LEGACY_RECONSTRUCTE… | UNREL_REAL | - A Design History File is a record of the design of the device, inclu… | If an investigation has already been performed for a similar complaint… | polarity |
| P137 | GUIDE8:H-006 (test fixture evi… | UNREL_REAL | The consequences of failure to comply with the Food Traceability Rule … | However, records that satisfy the requirements of the Food Traceabilit… | polarity |
| P140 | GUIDE8:H-006 (test fixture evi… | UNREL_REAL | The consequences of failure to comply with the Food Traceability Rule … | If I Already Keep Records of Some of the Information Required Under th… | polarity |
| P141 | GUIDE8:K-003 (test fixture evi… | UNREL_REAL | If the device contains multiple functions, the FDA does not regulate t… | However, FDA may assess the impact that such Non-Device-MDDS and Devic… | polarity |
| P142 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | The FDA requires that major food allergens be declared either in the i… | Although sensitive individuals may react to other foods, the labels of… | polarity |
| P143 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | The FDA requires that major food allergens be declared either in the i… | Although sensitive individuals may react to other foods, the labels of… | polarity |
| P144 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | If the food source is declared in the ingredient list and a "Contains"… | Although sensitive individuals may react to other foods, the labels of… | polarity |
| P145 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | If the food source is declared in the ingredient list and a "Contains"… | There are over 160 foods that have been reported to cause allergic rea… | polarity |
| P146 | GUIDE8:L-010 (test fixture evi… | FS_EXC | If the major food allergen is already declared within the Supplement F… | Generally, major food allergens must be identified either in a stateme… | polarity |
| P147 | GUIDE8:L-010 (test fixture evi… | FS_EXC | If the major food allergen is already declared within the Supplement F… | D. Allergen Statement Section 403(w) of the FD&C Act (21 U.S.C. 343(w)… | polarity |
| P148 | GUIDE8:L-010 (test fixture evi… | FS_EXC | If the major food allergen is already declared within the Supplement F… | D. Allergen Statement Section 403(w) of the FD&C Act (21 U.S.C. 343(w)… | polarity |
| P149 | GUIDE8:L-010 (test fixture evi… | FS_EXC | If the major food allergen is already declared within the Supplement F… | Manufacturers who wish to include religious statements on infant formu… | polarity |
| P150 | GUIDE8:L-010 (test fixture evi… | FS_EXC | If the major food allergen is already declared within the Supplement F… | Generally, major food allergens must be identified either in a stateme… | polarity |
| P151 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | If the major food allergen is declared in the ingredient list and a "C… | Although sensitive individuals may react to other foods, the labels of… | polarity |
| P152 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | If the major food allergen is declared in the ingredient list and a "C… | There are over 160 foods that have been reported to cause allergic rea… | polarity |
| P153 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | The FDA guidance also specifies that infant formulas must declare the … | Although sensitive individuals may react to other foods, the labels of… | polarity |
| P154 | GUIDE8:L-010 (test fixture evi… | UNREL_REAL | The FDA guidance also specifies that infant formulas must declare the … | Although sensitive individuals may react to other foods, the labels of… | polarity |
| P155 | GUIDE8:L-010 (test fixture evi… | FS_EXC | If the major food allergen is already declared within the Supplement F… | Contains Nonbinding Recommendations 12 Infant formulas, like other foo… | polarity |

## D. Root causes

| Defect | Function / rule | Exact mechanism |
|---|---|---|
| H-003 | `operators.compare` (strength block, operators.py:523–540) with `_STRENGTH_CONFLICTS` | Modality is compared clause-to-clause without asking **what the modal governs**. A permission over a *means* ("may submit … through …") is compared with a mandate over the *act* ("must submit"). Nothing checks that the same act is meant and that the mandate names no means. |
| D-009 (primary) | `operators._NEGATE_RE` (operators.py:106–110), alternative `\bnot\s+required\b` | A copula-less "not required" is a reduced relative modifying a noun ("products not required to be sterile"). It is not a negated duty. A negated requirement normally carries a copula or modal ("is/are not required", "need not"), which other alternatives of the same regex already capture. In all 954 captured texts the evaluator compared, every copula-less "not required" was a modifier like this one. |
| D-009 (enabling) | `operators.main_clause` (operators.py:276–289) | A purpose span runs to the end of the sentence even when the main modal lies inside it. The fallback then judges the **whole** sentence, so every embedded negative becomes the rule's polarity. |

**Other false-conflict mechanisms found** (all in §C; none changes a verdict today):
- negation inside a relative clause (33 pairs);
- inside "provide assurances that …" (14);
- the noun "exemption(s)" (9);
- "are not limited to" (1);
- conditions whose internal commas end the span early (3);
- an epistemic "may" read as a permission in recitals (16);
- a participle read as a recommendation (1);
- a claimed conditional exception compared with the general rule (6; not a scope defect).

**Why none of these changes a verdict today.** A conflict only produces CONTRADICTED when **every** candidate conflicts. Of 156 conflicting pairs, only H-003 (and D-019's garbled invented-condition claim) reach that point. The others silently remove a candidate, as in D-009.

## E. Candidate correction experiments

Each rule is a flag in a patched copy of `operators.py`, built by `work/make_variants.py`. **`V0_identity`** applies the patch scaffolding with no rule enabled. It reproduces production exactly: 0 changed comparisons, claims and answers. This validates the harness.

| Rule | Change (offline copy only) | Why |
|---|---|---|
| **BARE** | Ignore a `_NEGATE_RE` match that is the bare "not required" (no copula). | D-009 primary cause |
| **SPAN** | A condition or purpose span that would contain the main modal is ended just before that modal. | D-009 enabling cause (`main_clause` fallback) |
| **MEANS** | In `compare()`, when one side is permissive and the other mandatory, the conflict becomes a recorded relation (`permission_over_means`), i.e. undetermined. Three conditions must all hold: (i) the permissive clause has a means marker after its modal (*through, via, using, by means of, by way of, either … or*); (ii) the verb after the modal also appears in the mandatory clause; (iii) the mandatory clause names **no** means of its own. Otherwise the conflict stands. | H-003 |
| REL | Ignore a negation directly after *that/which/who*, unless the word before is complement-taking (ensure, require, provide, state, …). | relative-clause class |
| COMPL | Add "to provide assurance(s)" to the purpose boundaries. | complement class |
| NOUN | Drop the nouns "exemption(s)" from `_NEGATE_RE`; "exempt/exempted" stay. | noun class |
| IDIOM | Ignore "(are) not limited to". | idiom class |
| EPI | A "may" inside a relative clause ("which may render", "to which … may be exposed") is not a deontic permission. | epistemic class |

**Variants:**
- each rule alone;
- **VT_targeted** = BARE + MEANS;
- **VT2_targeted_span** = BARE + SPAN + MEANS;
- **VN_all** = BARE + NOUN + IDIOM + REL + COMPL;
- **VA_all** = VN_all + MEANS + EPI.

None of them ignores "may", "must" or "not" wholesale.

## F. Regression results

### F.1 Operator-level controls (all 156 frozen pairs + 19 genuine + 6 readings + replay of every recorded comparison)

| Variant | False conflicts removed (of 88) | Genuine kept (of 19) | Real readings kept (of 44) | Invented-condition unchanged (of 18) | Verbatim readings (of 6) | New conflicts (replay of 2,105 unique pairs) |
|---|--:|--:|--:|--:|--:|--:|
| V0_identity | 0 | 19 | 44 | 18 | 6 | 0 |
| VN_bare | 8 | 19 | 44 | 18 | 6 | 1 |
| VN_span | 11 | 19 | 44 | 18 | 6 | 1 |
| VM_means | 2 | 19 | 44 | 18 | 6 | 0 |
| VN_noun | 9 | 19 | 44 | 18 | 6 | 0 |
| VN_idiom | 1 | 19 | 44 | 18 | 6 | 0 |
| VN_rel | 33 | 19 | 44 | 18 | 6 | 2 |
| VN_compl | 14 | 19 | 44 | 18 | 6 | 2 |
| VM_epi | 9 | 19 | 44 | 18 | 6 | 0 |
| **VT_targeted** | **10** (all 8 bare + H-003's 2) | **19** | **44** | **18** | **6** | **1** |
| VT2_targeted_span | 15 | 19 | 44 | 18 | 6 | 1 |
| VN_all | 65 | 19 | 44 | 18 | 6 | 2 |
| VA_all | 76 | 19 | 44 | 18 | 6 | 2 |

**The new conflicts are all unmasking.** Two false negations previously "agreed"; fixing one exposes the other.
- **VT/VT2, 1 new pair:** D-001's claim "reprocessing batches **that do not** conform" (a false relative-clause negation) against 211.113(a), now read affirm. It changes no verdict: the claim stays credited by its own source.
- **VN_all/VA_all, 2 new pairs:** F-003 claims stating the 117.136(a) *exception* against 117.135(a)(1)'s general rule. The general rule's false "will not be adulterated" negation had been hiding the mismatch.

**Genuine-contradiction coverage, exactly as found:**
- must vs may (G01, G12, G18, G19);
- permission stated as a requirement (G02);
- may not vs may (G03);
- must vs must not (G07, G08);
- prohibited vs permitted (G09, G10);
- shall not vs may (G17);
- must vs should in regulation (G11);
- numbers and time periods (G04, G14);
- a different duty-holder (G05, G13);
- invented condition or exception (G06, G15);
- applies vs does not apply, verdict-level through the suite (G16).

All are from existing tests. Several use regulation text adapted in those tests, not captured benchmark evidence.

**Limitation: no genuine same-proposition contradiction exists in the frozen benchmark data.** All 156 conflicting pairs on real rows are one of:
- false scope conflicts (88);
- real operator differences against an *unrelated* passage (44, kept as preservation controls);
- invented-condition conflicts (18);
- claimed exceptions (6).

There is also no existing control where a claim permits one means and the evidence **mandates a different means**. That is the branch MEANS must leave as a conflict, and it is covered only by condition (iii) of the rule, not by data. I did not fabricate one.

### F.2 Claim- and answer-level changes (170 row-runs, both aligners)

| Variant | Claim changes | Answer changes | CONTRADICTED claims | Support (gate) transitions |
|---|--:|--:|---|---|
| V0_identity | 0 | 0 | 6 → 6 | none |
| VN_bare / VN_span | 2 (D-009 ×2 arms) | 0 | 6 → 6 | D-009: uncredited → credited by 211.113(a) |
| VM_means | 4 (H-003, 2 claims × 2 arms) | 2 (H-003 ×2 arms) | 6 → 2 | none (H-003 stays uncredited) |
| **VT_targeted** | **6** | **2** | **6 → 2** | D-009 credited (211.113(a)); nothing else |
| VT2_targeted_span | 6 (identical to VT) | 2 | 6 → 2 | identical to VT |
| VN_all | 8 | 0 | 6 → 6 | + F-007 "requirements for a **hazard analysis** include … preventive controls" newly **credited** (Phase 2E: a correctly unverifiable wrong list head); F-009 117.254(a) support **lost** (Phase 2C para40 SAFE) |
| VA_all | 12 | 2 | 6 → 2 | as VN_all, plus H-003 |

- **H-003 under VT:** both claims go contradicted → **unverifiable** (`not_decisive`, gate not established on 1.279(a)). The answer goes **incorrect 0 → unverifiable**, under both aligners.
- **D-009 under VT:** the claim is now credited (paraphrase) by 211.113(a), its stating source, under both aligners. Its final status is "irrelevant" because the relevance layer judges it off the question (component testing). The answer score is unchanged: 40 semantic, 35 lexical.
- **The 2 CONTRADICTED instances left** are D-019's garbled claim "such as where appropriate, "except" [12]". That is the Priority-2 invented-condition rule, out of scope.

**Aligners:** every VT change is identical under the semantic and lexical aligners.

### F.3 Named rows (VT = VT2; frozen 60 = legacy-reconstructed; GUIDE8 / REAL17 = fixtures)

| Row | Dataset | Base (sem / lex) | VT (sem / lex) | Contradicted claims |
|---|---|---|---|---|
| **H-003** (N=1) | F60 | incorrect 0 / incorrect 0 | **unverifiable / unverifiable** | 2 → 0 per arm |
| **D-009** (N=0) | F60 | partial 40 / partial 35 | partial 40 / partial 35 (the claim is now credited) | 0 → 0 |
| D-001 (N=0) | F60, REAL17 | off_topic 0 | off_topic 0 | 0 |
| D-008 (N=0) | F60, REAL17 | off_topic 0 | off_topic 0 | 0 |
| D-002 (N=2) | F60, REAL17 | correct 100 | correct 100 | 0 |
| C-004 (N=2) | F60, REAL17 | partial 35 | partial 35 | 0 |
| E-007 (N=2) | F60 / GUIDE8 | unverifiable / unverifiable | unchanged | 0 |
| H-001 (N=2) | F60 / GUIDE8 | unverifiable / partial 40 sem, 55 lex | unchanged | 0 |
| H-006 (N=1) | F60 / GUIDE8 | unverifiable / unverifiable | unchanged | 0 |
| K-003 (N=0) | F60 / GUIDE8 | unverifiable / partial 0 | unchanged | 0 |
| G-004 (N=2) | F60 | correct 100 | correct 100 | 0 |
| M-020 (N=2) | F60 | correct 60 | correct 60 | 0 |

### F.4 Test suite and guidance logic

| Run | Result |
|---|---|
| Production (start and end) | 1824 passed, 1 skipped |
| V0_identity | 1824 passed |
| **VT_targeted** | **1824 passed, 1 skipped, 0 failed** |
| VT2_targeted_span | 1824 passed |
| VN_span | 1824 passed |
| VN_all | **2 failed**: `test_the_83_safe_decisions_are_preserved_except_the_documented_one[para40-F-009-*]` (the Phase 2D lock) |

**Guidance (Priority 2):**
- MEANS sits *after* the guidance branch in `compare()`, so guidance modality relations are untouched.
- All of `test_accuracy_guidance_logic.py` passes under VT and VT2.
- The guidance-fixture rows (E-007, H-001, H-006, K-003, L-010, C-005, D-005, C-003) are unchanged.

**Phase 2D gate:**
- Gate logic is untouched.
- Under VT, the only change to what the gate decides is D-009, which now reaches its stating candidate. That is the intended fix.
- All 203 labelled Phase 2C/2D instances still pass (they are part of the suite).

## G. Residual limitations and recommendation

**Fixed (offline):**
- H-003's false contradictions, and so its incorrect-0 answer;
- D-009's lost stating candidate;
- 8 more bare "not required" false conflicts.

None of this weakens a genuine-contradiction control.

**Recommendation: implement VT_targeted (BARE + MEANS) in production as its own change.**

SPAN (VT2) is an equally safe, verdict-identical addition. It fixes the *enabling* cause and 5 more false operator readings. Adopt it if you prefer fixing the mechanism over the token; it is not needed for H-003 or D-009.

**Conditions for the production change:**
1. Add the genuine **means-conflict control** this data lacks: a mandate that names a means, compared with a permission over a different means, must stay CONFLICTED. Have a reviewer approve the text, with no invented regulation. Also add H-003 and D-009 as frozen regression tests.
2. Keep the change confined to `operators.py`. Re-run the full suite, the 203 labelled Phase 2C/2D instances and this phase's control evaluation (`work/eval_controls.py`). Run the live evaluator ON/OFF regression; answers and fingerprints must be unchanged.
3. Optionally, before shipping BARE: scan the local eCFR snapshot for copula-less "not required" in a main clause. In the 954 captured texts there were none, but corpus-wide frequency was not measured here (no database queries this phase).
4. **Do not ship REL, COMPL, NOUN, IDIOM or EPI**, singly or together, until the Phase 2D gate decisions that rest on cancelling false negations are separated from operator reading. VN_all shows such changes create a false support and lose a safe one.

**Remains uncertain or unfixed:**
- **Most false operator conflicts (78 of 88 under VT; 73 under VT2) remain.** They change no verdict today because other candidates exist, but they can remove a stating candidate (the D-009 pattern) on new rows.
- **The claimed-exception vs general-rule pattern** (6 pairs; L-010 Supplement Facts) is not a scope defect. A conditional negation is not contradicted by an unconditional rule. That needs its own rule.
- **The invented-condition rule** still contradicts D-019's garbled claim. That is out of scope.
- **Validation is on legacy-reconstructed evidence** for H-003 and D-009. No exact-evidence capture exists for either row.
- **Nothing here measures Regulus accuracy.** The evidence is limited to the tested controls.

## H. Production-safety verification

| Check | Result |
|---|---|
| `src/`, `scripts/`, `tests/`, `web/` | **identical**: SHA-256 manifests of all 301 files at start and end match (`work/production_manifest_*.sha256`) |
| Benchmark dataset, frozen inputs, test fixtures | **identical**: manifests of `artifacts/stage_a/`, `priority3_claim_extraction_ab_2026-10-08/`, `tests/fixtures/` match |
| Files written | only under `artifacts/accuracy/measurement_audit_phase2f_20261009T035919Z/` |
| Locked Phase 2D gate | untouched (`verdicts.py` not modified in any variant; only `operators.py` copies were patched) |
| Retrieval, generation, prompts, citations, evidence capture, model configuration, DB, corpus, rubric, labels | unchanged; nothing was retrieved, the model was not loaded, no LLM judge |
| Live server | not restarted or touched |
| 300-question benchmark | **not run** |
| Tests run | production suite at start and end (1824 passed); full suite under V0, VT, VT2, VN_span (all 1824 passed) and VN_all (2 failed, reported) |

## Artifacts (`work/`)

- **Collection and tracing:** `collect_compares.py` (instrumented comparison recorder), `trace_cases.py` with `traces/defect_traces_lexical.json`.
- **Controls:** `annotate_pairs.py`, `label_controls.py`, `controls_frozen.json` (156), `controls_tests.json` (19), `controls_readings.json` (6), `table_*.md`.
- **Variants:** `make_variants.py`, `variants/*` (offline copies), `use_variant.py`, `run_suite_variant.py`.
- **Results:** `eval_controls.py` with `controls_result_*.json`; `compares_*.json` with `diff_verdicts.py` and `verdict_diffs.json`; `named_rows.json`.
- **Integrity:** `production_manifest_*.sha256`, `benchmark_fixture_manifest_*.sha256`.
