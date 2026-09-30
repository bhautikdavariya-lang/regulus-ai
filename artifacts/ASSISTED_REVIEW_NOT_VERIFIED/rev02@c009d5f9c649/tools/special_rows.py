"""ASSISTED REVIEW — NOT VERIFIED.

Proposals for the 100 judgment-heavy rows (Part 820 / ISO, negative controls,
temporal, scope and platform behaviour, statute- and part-level citations,
X-003, X-004), written by the coordinating reviewer from the evidence in
../evidence. Same schema as the batch reviewers' output, plus:

  iso_assessment      — for rows whose column H is not "—"
  absence_assessment  — for negative-control / absence rows
  controlled_source   — what an SME must consult outside this system, if anything

ISO evidence tiers used below (no ISO text is available in this system):
  T1_CFR_TEXT     the eCFR paragraph the key cites names the clause itself
  T2_CORROBORATED clause not named in the CFR, but the internal crosswalk maps
                  the section to the same clause or to its parent, and the
                  internal index title matches the subject. Corroboration, not
                  authority: the controlled standard must still be consulted.
  T3_UNRESOLVED   the draft names a clause the crosswalk does not (sibling or
                  different clause) and the CFR text does not name it
  NONE_CLAIM      the draft says the answer names no clause; a section-level
                  crosswalk cannot settle a paragraph-level "None"
  RANGE           the draft names a clause range / the whole standard

    python tools/special_rows.py   -> proposals/special_rows.json
"""

import json
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
SNAP = "eCFR snapshot 2026-09-03"
FR_DATE = ("Federal Register: confirm the effective/compliance date of the QMSR final rule "
           "(89 FR 7523). The snapshot carries the FR citation but not the effective date; "
           "federal_register_docs is empty.")
ISO_CS = ("Controlled copy of ISO 13485:2016(E), 3rd ed. — confirm clause number/title only; "
          "do not copy text.")


def E(element, support, cite="", quote="", note=""):
    return {"element": element, "support": support, "cite": cite, "quote": quote, "note": note}


def row(qid, decision, subst, compl, conf, rationale, elements, *, cit="correct", exists="yes",
        appl="applicable", compl_note="", corrected=None, refs=(), uncertainty="", conflict=False,
        research=(), controlled=None, iso=None, absence=None, key_issue=""):
    return {
        "question_id": qid, "citation_correctness": cit, "provision_exists": exists,
        "applicability": appl, "elements": elements, "substantive_judgment": subst,
        "completeness_judgment": compl, "completeness_note": compl_note,
        "proposed_decision": decision, "proposed_corrected_citation": corrected,
        "rationale": rationale, "evidence_refs": list(refs) or [SNAP], "confidence": conf,
        "uncertainty": uncertainty, "evidence_conflict": conflict,
        "needs_research_items": list(research), "controlled_source": controlled,
        "iso_assessment": iso, "absence_assessment": absence, "key_elements_issue": key_issue,
        "reviewer": "assisted-review coordinator (AI) — NOT an SME",
    }


def iso(tier, draft, cfr_names, crosswalk, note):
    return {"tier": tier, "draft_H": draft, "clauses_named_in_cited_cfr_text": cfr_names,
            "internal_crosswalk": crosswalk, "note": note,
            "weight": "Crosswalk and clause index are internal project artefacts, not authority. "
                      "CFR text naming a clause is regulation text (US Government work)."}


def absence(scope, method, result, established, note):
    return {"search_scope": scope, "method": method, "result": result,
            "absence_established": established, "note": note}


R = []

# ============================================================== X-004
R.append(row(
    "X-004", "CORRECTED", "correct", "correct", "MEDIUM",
    "The draft range 4.100–4.110 overruns Part 4 Subpart B, which in the snapshot is exactly "
    "4.100–4.105 (no 4.106–4.110, not even reserved). Every J element is in 4.100–4.105. "
    "Proposed correction is to the range the snapshot holds; it is NOT applied to the workbook.",
    [E("Applicable safety reporting requirements by constituent part", "SUPPORTED", "4.102(b)(1)",
       "you must comply with the requirements for postmarketing safety reporting described in parts 803 and 806 of this chapter with respect to your product"),
     E("five-day reporting", "SUPPORTED", "4.102(c)(1)(i)", "Five-day reports;"),
     E("malfunction reporting", "SUPPORTED", "4.102(c)(1)(ii)", "Malfunction reports; and"),
     E("shared reporting responsibilities", "SUPPORTED", "4.103(a)",
       "you must provide the information to the other constituent part applicant(s) for the combination product no later than 5 calendar days of your receipt of the information")],
    cit="partially_correct", exists="partial",
    corrected="21 CFR 4.100 through 4.105 (21 CFR Part 4, Subpart B)",
    refs=[f"{SNAP}: Part 4 section list and subpart structure (Subpart B = 4.100–4.105)",
          f"{SNAP}: 21 CFR 4.100–4.105 text", "automated verification: citation CONTRADICTED (4.110 absent)"],
    uncertainty="The snapshot is dated 2026-09-03. If 4.106–4.110 were added after that date the draft could be right; "
                "the SME must check the live eCFR before recording anything.",
    conflict=True,
    research=["Confirm against the LIVE eCFR that 21 CFR Part 4 Subpart B ends at 4.105 (no 4.106–4.110).",
              "Decide whether the drafter meant 4.100–4.105 (slip) or intended to reach other provisions; "
              "4.100(c) states the subpart supplements parts 314, 600, 606, 803 and 806 — decide whether "
              "completeness requires naming those parts.",
              "Record CORRECTED with the range you determine, or NEEDS_RESEARCH; do not treat this proposal as the correction."],
    controlled="Live eCFR (Title 21 Part 4) — current text, not the snapshot"))

# ============================================================== X-003
R.append(row(
    "X-003", "CORRECTED", "correct", "partially_correct", "MEDIUM",
    "Citation 4.4(b)(1) is right. Its own text enumerates the ISO clauses a drug-CGMP-based system must "
    "also satisfy; the draft ISO key lists only part of them. J also contains a drafting note to the SME "
    "('SME to confirm how Part 4 cross-references read ...'); the snapshot answers it — 4.4(b)(1) now "
    "cites ISO 13485 clauses and 820.10/820.35 directly.",
    [E("The enumerated device provisions added to a drug-based system", "SUPPORTED", "4.4(b)(1)(i)",
       "General requirements and management responsibility. Clause 4.1, Clause 5 and its subclauses, Clause 6.1 of ISO 13485, and § 820.10 of this chapter;"),
     E("(enumeration continued)", "SUPPORTED", "4.4(b)(1)(iv)",
       "Analysis of data, improvement, and complaint handling. Clause 8.2.2 and § 820.35(a) of this chapter, Clause 8.4, and Clause 8.5. and its subclauses of ISO 13485;"),
     E("SME to confirm Part 4 cross-references after the Part 820 restructuring", "SUPPORTED", "4.4(b)(1)(vi)",
       "Servicing activities. Clause 7.5.4 of ISO 13485 and § 820.35(b) of this chapter.",
       "This J item is a drafting note, not an answer element. The snapshot shows Part 4 already cross-references the QMSR.")],
    corrected="ISO key (column H): 4.1; 5 and subclauses; 6.1; 7.3 and subclauses; 7.4 and subclauses; 7.5.3; 7.5.4; 8.2.2; 8.4; 8.5 and subclauses — plus 21 CFR 820.10, 820.35(a), 820.35(b) as named in 4.4(b)(1). Citation 4.4(b)(1) unchanged.",
    refs=[f"{SNAP}: 21 CFR 4.4(b)(1)(i)–(vi)"],
    uncertainty="Whether G7 expects every clause 4.4(b)(1) enumerates, or only the ones the draft chose, is a scoring-policy decision.",
    conflict=True,
    key_issue="J contains a reviewer instruction rather than answer elements.",
    iso=iso("T1_CFR_TEXT", "7.3; 7.4; 7.5.3; 7.5.4; 8.5.2; 8.5.3",
            ["4.1", "5", "6.1", "7.3", "7.4", "8.2.2", "8.4", "8.5", "7.5.3", "7.5.4"], "no mapping for 4.4",
            "Draft omits 4.1, 5, 6.1, 8.2.2 and 8.4, all named in the cited paragraph; 8.5.2/8.5.3 are within the named 8.5."),
    controlled=ISO_CS + " Optional here: the clauses are named in the CFR text."))

# ============================================================== Part 820 scope (820.1)
cw_8201 = "820.1 -> 1, 4.1 (section level)"
R.append(row(
    "M-001", "ACCEPTED", "correct", "correct", "MEDIUM",
    "820.1(a) states the activities and the QMS-appropriate-to-device obligation. ISO key 1; 4.1 matches the "
    "internal crosswalk for 820.1 and the index titles (Scope; QMS general requirements).",
    [E("Design, manufacture, packaging, labeling, storage, installation, servicing of finished devices for human use", "SUPPORTED", "820.1(a)",
       "the design, manufacture, packaging, labeling, storage, installation, and servicing of all finished devices intended for human use"),
     E("QMS appropriate to the specific device", "SUPPORTED", "820.1(a)",
       "must establish and maintain a quality management system that is appropriate for its specific device(s)")],
    iso=iso("T2_CORROBORATED", "1; 4.1", [], cw_8201, "Draft equals crosswalk; titles match the subject."),
    controlled=ISO_CS))

for qid, par, elems, lean in [
    ("M-002", "820.1(a)(2)", [E("Component and part manufacturers are outside the scope", "SUPPORTED", "820.1(a)(2)",
        "The provisions of this part do not apply to manufacturers of components or parts of finished devices"),
        E("FDA encourages voluntary application", "SUPPORTED", "820.1(a)(2)",
        "such manufacturers are encouraged to consider provisions of this regulation as appropriate")], "ACCEPTED"),
    ("M-003", "820.1(a)(3)", [E("Blood and blood components are excluded from Part 820", "SUPPORTED", "820.1(a)(3)",
        "The provisions of this part do not apply to manufacturers of blood and blood components used for transfusion or for further manufacturing."),
        E("those manufacturers are subject to Part 606", "PARTIALLY_SUPPORTED", "820.1(a)(3)",
        "Such manufacturers are subject to subchapter F of this chapter.",
        "The text routes them to subchapter F as a whole; J names Part 606 only (G also names 640).")], "ACCEPTED"),
    ("M-004", "820.1(a)(4)", [E("HCT/Ps regulated as devices are in scope and also subject to Part 1271", "SUPPORTED", "820.1(a)(4)",
        "HCT/Ps regulated as devices are also subject to the donor-eligibility requirements set forth in part 1271, subpart C"),
        E("the specifically applicable regulation supersedes the more general one", "SUPPORTED", "820.1(a)(4)",
        "the regulation specifically applicable to the device in question shall supersede the more general regulation")], "ACCEPTED"),
    ("M-005", "820.1(b)", [E("the FD&C Act and applicable FDA regulations govern over the incorporated standard", "SUPPORTED", "820.1(b)",
        "the Federal Food, Drug, and Cosmetic Act and/or its other implementing regulations will control")], "ACCEPTED (weaker: the paragraph speaks of ISO clauses generally)"),
    ("M-006", "820.1(c)", [E("Refusal to permit inspection is grounds for refusal of admission", "NOT_FOUND_IN_EVIDENCE", "820.1(c)",
        "is subject to refusal of admission to the United States under section 801(a) of the Federal Food, Drug, and Cosmetic Act if, among other things, it appears to be adulterated",
        "The snapshot's 820.1(c) says nothing about refusing inspection. The inspection element may come from the statute (801(a)) or from the pre-QMSR text; neither is in evidence.")], "NEEDS J CHECK"),
    ("M-007", "820.1(d)", [E("Exemption or variance under section 520(f)(2)", "SUPPORTED", "820.1(d)(1)",
        "may petition for an exemption or variance from such requirement in accordance with section 520(f)(2) of the Federal Food, Drug, and Cosmetic Act"),
        E("requested by citizen petition under 10.30", "SUPPORTED", "820.1(d)(1); 10.30 heading 'Citizen petition.'",
        "Petitions for an exemption or variance shall be submitted in accordance with the procedures set forth in § 10.30 of this chapter.")], "ACCEPTED"),
]:
    subst = "partially_correct" if qid in ("M-003", "M-006") else "correct"
    R.append(row(
        qid, "NEEDS_RESEARCH", subst, "correct", "MEDIUM",
        f"CFR elements: {'all supported' if subst == 'correct' else 'see element notes'} from {par}. The row is held "
        "at NEEDS_RESEARCH only because of the ISO key: column H = None, while the internal crosswalk maps the "
        f"whole of 820.1 to clauses 1 and 4.1. The cited paragraph names no clause. Lean: {lean}.",
        elems,
        iso=iso("NONE_CLAIM", "None", [], cw_8201,
                "Section-level crosswalk vs paragraph-level 'None'. Under the workbook rule, naming any clause on a "
                "None row scores Q=0 AND triggers column M (fabricated citation, G2 zero tolerance). Confirm the "
                "answer genuinely reaches no clause before accepting None."),
        research=["Controlled-source + scoring-policy decision: does an answer to this paragraph-level question reach "
                  "ISO 13485 Clause 1 (Scope) or 4.1? If yes, H should name it; if no, accept None."] +
                 (["Confirm what 820.1(c) says in the live eCFR and whether the 'refuses inspection' element comes "
                   "from FD&C Act 801(a); J may reflect superseded text."] if qid == "M-006" else []) +
                 (["Decide whether J's 'Part 606' is acceptable given the text routes to subchapter F."] if qid == "M-003" else []),
        controlled=ISO_CS,
        conflict=qid == "M-006",
        key_issue={"M-006": "J asserts refusal of inspection as the ground; the snapshot 820.1(c) text does not mention inspection.",
                   "M-003": "J narrows 'subchapter F' to Part 606."}.get(qid, "")))

# ============================================================== 820.3 / 820.7
R.append(row(
    "M-008", "ACCEPTED", "correct", "correct", "MEDIUM",
    "820.3 intro and (b) state each element. ISO key '3; ISO 9000 Clause 3' matches the crosswalk (820.3 -> 3) and 820.3/820.7(a) name ISO 9000 Clause 3 directly.",
    [E("ISO 13485 definitions apply except as superseded by 820.3", "SUPPORTED", "820.3 (intro)",
       "The definitions in ISO 13485 and in Clause 3 of ISO 9000 (incorporated by reference, see § 820.7) apply to this part, except as specified in paragraph (b) of this section"),
     E("ISO 9000:2015 Clause 3 separately incorporated", "SUPPORTED", "820.7(a)",
       "Clause 3—Terms and definitions, Fourth edition, September 15, 2015. IBR approved for § 820.3."),
     E("FD&C Act section 201 definitions supersede correlating standard terms", "SUPPORTED", "820.3(b)",
       "shall supersede the correlating terms and definitions in ISO 13485")],
    iso=iso("T1_CFR_TEXT", "3; ISO 9000 Clause 3", ["ISO 9000 Clause 3"], "820.3 -> 3",
            "ISO 9000 Clause 3 named in CFR text; ISO 13485 Clause 3 corroborated by crosswalk + index title."),
    controlled=ISO_CS))

R.append(row(
    "M-009", "NEEDS_RESEARCH", "partially_correct", "correct", "MEDIUM",
    "820.3(b) defines 'Safety and Performance' by reference to 'safety and effectiveness' in Clause 0.1 of ISO 13485 — "
    "so the draft H value 0.1 (flagged by the verifier as outside the index) is named by the CFR text itself. "
    "J attributes the meaning to 'the FD&C Act and FDA regulations', which is not what 820.3(b) says.",
    [E("'Safety and performance' carries the meaning of 'safety and effectiveness'", "SUPPORTED", "820.3(b)",
       "Safety and Performance shall have the meaning of “safety and effectiveness” in Clause 0.1 of ISO 13485."),
     E("... as used in the FD&C Act and FDA regulations", "PARTIALLY_SUPPORTED", "820.3(b); 820.1(a)",
       "does not relieve a manufacturer from any obligation to implement controls or other measures that provide reasonable assurance of safety and effectiveness",
       "The statutory standard is preserved (820.1(a), 820.3(b) second sentence) but the definition itself points to Clause 0.1.")],
    iso=iso("T1_CFR_TEXT", "0.1; 3", ["0.1"], "820.3 -> 3",
            "0.1 is named in 820.3(b). The internal index starts at clause 1, which is why the verifier could not confirm it."),
    research=["Decide whether J's attribution ('as used in the FD&C Act') is acceptable or misleading; the SME system cannot correct J."],
    controlled=ISO_CS + " Confirm Clause 0.1 exists (Introduction — General).",
    key_issue="J attributes the definition to the FD&C Act; 820.3(b) attributes it to Clause 0.1 of ISO 13485."))

for qid, elems, conf in [
    ("M-010", [E("ISO 13485:2016(E), third edition, March 1, 2016 — IBR approved for 820.1, 820.3, 820.10, 820.35 and 820.45", "SUPPORTED", "820.7(b)",
                 "Third edition, March 1, 2016; IBR approved for §§ 820.1, 820.3, 820.10, 820.35, and 820.45."),
               E("ISO 9000:2015(E) Clause 3 — IBR approved for 820.3", "SUPPORTED", "820.7(a)",
                 "Clause 3—Terms and definitions, Fourth edition, September 15, 2015. IBR approved for § 820.3.")], "HIGH"),
    ("M-011", [E("Incorporation by reference fixes the 2016 third edition", "SUPPORTED", "820.7(b)",
                 "Third edition, March 1, 2016; IBR approved for §§ 820.1, 820.3, 820.10, 820.35, and 820.45."),
               E("a later edition does not apply automatically until FDA amends the regulation", "PARTIALLY_SUPPORTED", "820.7 (intro)",
                 "with the approval of the Director of the Federal Register under 5 U.S.C. 552(a) and 1 CFR part 51",
                 "Edition-specificity is in the text; 'until FDA amends' is the legal consequence of IBR, not stated in 820.7.")], "MEDIUM"),
]:
    R.append(row(
        qid, "ACCEPTED", "correct", "correct", conf,
        "820.7 states the incorporated editions and approvals. Column H 'entire standard' matches 820.7(b), which "
        "incorporates the standard as a whole; the index's top-level clauses are 1–8.",
        elems,
        iso=iso("RANGE", "1 through 8 (entire standard)" + ("; ISO 9000 Clause 3" if qid == "M-010" else ""),
                ["ISO 13485:2016 as a whole (820.7(b))"], "820.7 -> 2",
                "Crosswalk maps 820.7 to clause 2 (Normative references); the draft's whole-standard reading is "
                "supported by 820.7(b). SME to confirm the scoring convention for a whole-standard key."),
        uncertainty="Scoring convention for 'entire standard' keys under G7.",
        controlled=ISO_CS + " Confirm the standard's top-level clauses are 1–8."))

# ============================================================== 820.10
R.append(row(
    "M-012", "NEEDS_RESEARCH", "correct", "partially_correct", "MEDIUM",
    "820.10(a) states J exactly. Two open points: (1) column H '4 through 8' is not in the CFR text, which says "
    "'applicable requirements of ISO 13485'; (2) the question asks what 820.10 requires, and (b)–(e) add "
    "further mandatory requirements that G does not cite.",
    [E("Document a QMS that complies with the applicable requirements of ISO 13485 and other applicable requirements of Part 820", "SUPPORTED", "820.10(a)",
       "Document a quality management system that complies with the applicable requirements of ISO 13485 (incorporated by reference, see § 820.7) and other applicable requirements of this part")],
    compl_note="820.10(b)(1)–(4), (c) and (d) impose further 'must' obligations; the question asks about 820.10 as a whole.",
    iso=iso("RANGE", "4 through 8", [], "820.10 -> no mapping",
            "'4 through 8' reads as the requirement clauses; that is ISO content the CFR text does not state."),
    research=["Controlled source: confirm clauses 4–8 are the requirement clauses (1–3 being scope, normative references, terms).",
              "Decide whether G should be 820.10 (a)–(d) given the question's wording."],
    controlled=ISO_CS))

for qid, par, clause, elem, quote_elem, quote_iso in [
    ("M-013", "820.10(b)(1)", "7.5.8", "A documented system to assign unique device identification in accordance with Part 830",
     "the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter",
     "For Clause 7.5.8 in ISO 13485, Identification"),
    ("M-014", "820.10(b)(2)", "7.5.9.1", "Documented traceability procedures in accordance with Part 821",
     "the manufacturer must document procedures for traceability in accordance with the requirements of part 821 of this chapter, if applicable",
     "For Clause 7.5.9.1 in ISO 13485, Traceability—General"),
    ("M-015", "820.10(b)(3)", "8.2.3", "Complaints meeting the reporting criteria of Part 803 must be reported to FDA",
     "the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter",
     "For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities"),
    ("M-016", "820.10(b)(4)", "7.2.3; 8.2.3; 8.3.3", "Advisory notices handled in accordance with Part 806",
     "advisory notices shall be handled in accordance with the requirements of part 806 of this chapter",
     "For Clauses 7.2.3, 8.2.3, and 8.3.3"),
    ("M-017", "820.10(c)", "7.3 and its subclauses", "Mandatory for Class II and III devices and the listed Class I devices",
     "Manufacturers of class II, class III, and those class I devices listed in paragraph (c)(1)",
     "must comply with the requirements in Design and Development, Clause 7.3 and its Subclauses in ISO 13485"),
    ("M-018", "820.10(d)", "7.5.9.2", "FDA extends implantable-device traceability to devices that support or sustain life",
     "Manufacturers of devices that support or sustain life",
     "must comply with the requirements in Traceability for Implantable Devices, Clause 7.5.9.2 in ISO 13485"),
]:
    R.append(row(
        qid, "ACCEPTED", "correct", "correct", "HIGH",
        f"{par} states J, and names clause {clause} itself — the verifier's UNVERIFIABLE came from the crosswalk "
        "holding no mapping for 820.10, not from any doubt about the clause.",
        [E(elem, "SUPPORTED", par, quote_elem),
         E(f"ISO clause {clause}", "SUPPORTED", par, quote_iso, "Clause named in the regulation text.")],
        iso=iso("T1_CFR_TEXT", clause, [clause], "820.10 -> no mapping", "Exact match with the CFR text."),
        controlled=ISO_CS + " Optional: clause named in CFR text; confirm title only."))

R.append(row(
    "M-019", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "820.10(e) states both elements. Held only for the ISO 'None' key (820.10 has no crosswalk mapping; the paragraph names no clause). Lean: ACCEPTED.",
    [E("The device is adulterated", "SUPPORTED", "820.10(e)",
       "The failure to comply with any applicable requirement in this part renders a device adulterated under section 501(h) of the Federal Food, Drug, and Cosmetic Act."),
     E("the manufacturer is subject to enforcement action", "SUPPORTED", "820.10(e)",
       "Such a device, as well as any person responsible for the failure to comply, is subject to regulatory action.")],
    iso=iso("NONE_CLAIM", "None", [], "820.10 -> no mapping", "Enforcement paragraph; no clause named. Low risk, but None rows carry a G2 penalty for any clause named."),
    research=["Confirm None is intended (answer reaches no clause)."], controlled=ISO_CS))

# ============================================================== 820.35 / 820.45
cw35 = "820.35 -> 4.2.5 (section level, from the introductory text)"
cw45 = "820.45 -> 7.5.1 (section level, from the introductory text)"
R.append(row(
    "M-020", "ACCEPTED", "correct", "correct", "HIGH",
    "820.35 introductory text supplements Clause 4.2.5 with additional record content; clause named in the text and in the crosswalk.",
    [E("FDA supplement specifying additional required record content beyond the standard's record control clause", "SUPPORTED", "820.35 (intro)",
       "the manufacturer must include the following information in certain records")],
    iso=iso("T1_CFR_TEXT", "4.2.5", ["4.2.5"], cw35, "CFR text and crosswalk agree."), controlled=ISO_CS + " Optional."))

for qid, par, clause, elems, q_iso in [
    ("M-021", "820.35(a)", "8.2.2",
     [E("Records of review, evaluation and investigation", "SUPPORTED", "820.35(a)",
        "the manufacturer shall maintain records of the review, evaluation, and investigation for any complaints"),
      E("including the justification when no investigation is made", "SUPPORTED", "820.35(a)",
        "the manufacturer shall maintain records documenting justification for not performing such investigation")],
     "In addition to Clause 8.2.2 in ISO 13485, Complaint Handling"),
    ("M-022", "820.35(b)", "7.5.4",
     [E("device name", "SUPPORTED", "820.35(b)(1)", "The name of the device serviced;"),
      E("UDI or other identification", "SUPPORTED", "820.35(b)(2)", "Any UDI or UPC, and any other device identification(s);"),
      E("date of service", "SUPPORTED", "820.35(b)(3)", "The date of service;"),
      E("individual servicing the device", "SUPPORTED", "820.35(b)(4)", "The individual(s) who serviced the device;"),
      E("service performed", "SUPPORTED", "820.35(b)(5)", "The service performed; and"),
      E("test and inspection data", "SUPPORTED", "820.35(b)(6)", "Any test and inspection data.")],
     "In adhering to Clause 7.5.4 in ISO 13485, Servicing Activities"),
    ("M-023", "820.35(c)", "7.5.1; 7.5.8; 7.5.9",
     [E("The UDI must be recorded for each medical device or batch", "SUPPORTED", "820.35(c)",
        "the UDI must be recorded for each medical device or batch of medical devices.")],
     "In addition to the requirements of Clauses 7.5.1, 7.5.8, and 7.5.9 in ISO 13485"),
    ("M-027", "820.45(b)", "4.2.5",
     [E("Release of labeling for use must be documented", "SUPPORTED", "820.45(b)",
        "The release of the labeling for use must be documented in accordance with Clause 4.2.5 of ISO 13485.")],
     "The release of the labeling for use must be documented in accordance with Clause 4.2.5 of ISO 13485."),
]:
    R.append(row(
        qid, "ACCEPTED", "correct", "correct", "HIGH",
        f"J is stated in {par}. ISO CONFLICT RESOLVED BY CFR TEXT: {par} itself names clause(s) {clause}, exactly the draft. "
        "The crosswalk disagrees only because it maps the whole section to the single clause named in the "
        "section's introductory text — a granularity artefact, not evidence against the draft.",
        elems + [E(f"ISO clause(s) {clause}", "SUPPORTED", par, q_iso, "Clause named in the regulation text.")],
        iso=iso("T1_CFR_TEXT", clause, clause.split("; "), cw45 if par.startswith("820.45") else cw35,
                "Section-level crosswalk vs paragraph-level key; the paragraph text names the draft clause."),
        uncertainty="Human confirmation required because the automated pass flagged a crosswalk conflict.",
        controlled=ISO_CS + " Confirm title only; do not copy text."))

R.append(row(
    "M-024", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "820.35(d) states J. The ISO key 'None' is doubtful: 820.35's introductory text frames every paragraph as 'in addition to "
    "the requirements of Clause 4.2.5', and the crosswalk maps the section to 4.2.5. Under the workbook rule, a vendor naming "
    "4.2.5 here would be scored as a FABRICATED citation (column M, G2 zero tolerance).",
    [E("Records deemed confidential may be marked to aid FDA in determining whether information may be disclosed", "SUPPORTED", "820.35(d)",
       "Records deemed confidential by the manufacturer may be marked to aid FDA in determining whether information may be disclosed under the public information regulation in part 20 of this chapter.")],
    iso=iso("NONE_CLAIM", "None", ["4.2.5 (section intro)"], cw35,
            "The section's own introductory text names 4.2.5; 'None' may penalise a correct answer as fabricated."),
    research=["Decide whether H should be 4.2.5 (section-intro framing) or None; consult the controlled standard's Control of records clause for scope."],
    conflict=True, controlled=ISO_CS))

R.append(row(
    "M-025", "ACCEPTED", "correct", "correct", "HIGH",
    "820.45 introductory text states the supplement and names Clause 7.5.1; crosswalk agrees.",
    [E("Documented procedures ensuring the integrity of labeling and packaging, supplementing the standard's production control clause", "SUPPORTED", "820.45 (intro)",
       "each manufacturer must document and maintain procedures that provide a detailed description of the activities to ensure the integrity, inspection, storage, and operations for labeling and packaging")],
    iso=iso("T1_CFR_TEXT", "7.5.1", ["7.5.1"], cw45, "CFR text and crosswalk agree."), controlled=ISO_CS + " Optional."))

R.append(row(
    "M-026", "ACCEPTED", "correct", "correct", "HIGH",
    "820.45(a) states J; the section is framed as 'in addition to Clause 7.5.1'; crosswalk agrees.",
    [E("Labeling and packaging examined for accuracy prior to release or storage", "SUPPORTED", "820.45(a)",
       "The manufacturer must ensure labeling and packaging has been examined for accuracy prior to release or storage where applicable")],
    iso=iso("T1_CFR_TEXT", "7.5.1", ["7.5.1 (section intro)"], cw45, "Clause named in the section introductory text."), controlled=ISO_CS + " Optional."))

R.append(row(
    "M-028", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "820.45(c) states both J elements and names Clause 4.2.5. The draft also names 4.2.3 (Medical device file): the paragraph "
    "mentions 'the medical device file' as where labeling is specified, but does not invoke that clause. Whether 4.2.3 belongs "
    "in the key is an ISO/policy question.",
    [E("Labeling and packaging operations must be controlled to prevent mixups", "SUPPORTED", "820.45(c)",
       "The manufacturer must ensure labeling and packaging operations have been established and maintained to prevent mixups"),
     E("inspection results must be documented", "SUPPORTED", "820.45(c)",
       "Results of such labeling inspection must be documented in accordance with Clause 4.2.5 of ISO 13485.")],
    iso=iso("T3_UNRESOLVED", "4.2.3; 4.2.5", ["4.2.5"], cw45,
            "4.2.5 named in CFR text. 4.2.3 inferred from the term 'medical device file' only."),
    research=["Controlled source: does the answer reach Clause 4.2.3 or only 4.2.5?"], controlled=ISO_CS))

R.append(row(
    "M-029", "CORRECTED", "correct", "correct", "MEDIUM",
    "Citation matches J. The ISO key omits clauses that the cited provisions themselves name: 820.10(b)(4) names 7.2.3 and 8.3.3, "
    "820.10(c) names 7.3. The draft lists 4.2.5; 7.5.1; 7.5.4; 7.5.8; 7.5.9; 8.2.2; 8.2.3.",
    [E("820.10(b)–(e), 820.35 and 820.45 impose FDA requirements in addition to the standard", "SUPPORTED", "820.10(b)",
       "Comply, as appropriate, with the other applicable regulatory requirements in this title, including, but not limited to the following, to fully comply with the listed ISO 13485 Clause:",
       "820.10(e) is an enforcement provision rather than a supplement; SME may want to note that."),
     E("the balance of the quality system reaches the manufacturer through incorporation by reference", "SUPPORTED", "820.10(a)",
       "Document a quality management system that complies with the applicable requirements of ISO 13485 (incorporated by reference, see § 820.7) and other applicable requirements of this part")],
    corrected="ISO key (column H): 4.2.5; 7.2.3; 7.3; 7.5.1; 7.5.4; 7.5.8; 7.5.9 (incl. 7.5.9.1, 7.5.9.2); 8.2.2; 8.2.3; 8.3.3 — every clause named in the cited CFR text. Citation unchanged.",
    iso=iso("T1_CFR_TEXT", "4.2.5; 7.5.1; 7.5.4; 7.5.8; 7.5.9; 8.2.2; 8.2.3",
            ["7.5.8", "7.5.9.1", "8.2.3", "7.2.3", "8.3.3", "7.3", "7.5.9.2", "4.2.5", "8.2.2", "7.5.4", "7.5.1", "7.5.9"],
            "820.10 -> none; 820.35 -> 4.2.5; 820.45 -> 7.5.1",
            "Draft is a subset of the clauses the cited text names; missing 7.2.3, 7.3, 8.3.3."),
    uncertainty="Policy: should H list every clause named in the cited provisions, or only those an answer must reach?",
    conflict=True, controlled=ISO_CS + " Optional; clauses are named in CFR text."))

R.append(row(
    "M-030", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "Structural elements are established in the snapshot (IBR of ISO 13485 at 820.7(b); Subparts C–O reserved; supplements at "
    "820.10(b)–(e), 820.35, 820.45; FR citation 89 FR 7523, Feb. 2, 2024). The compliance date the question asks for is not in "
    "the snapshot. The snapshot also shows a second FR document (89 FR 82945, Oct. 15, 2024) that the key does not mention.",
    [E("ISO 13485:2016 incorporated by reference", "SUPPORTED", "820.7(b)",
       "Third edition, March 1, 2016; IBR approved for §§ 820.1, 820.3, 820.10, 820.35, and 820.45."),
     E("former Subparts C through O reserved", "SUPPORTED", "cfr_subparts (Part 820)", "Subparts C-O [Reserved]"),
     E("FR citation of the final rule", "SUPPORTED", "820.3 source note", "89 FR 7523, Feb. 2, 2024; 89 FR 82945, Oct. 15, 2024"),
     E("compliance date February 2, 2026", "NOT_FOUND_IN_EVIDENCE", "", "", "Effective/compliance date is not held in the snapshot.")],
    cit="undetermined", exists="partial",
    iso=iso("RANGE", "1 through 8 (entire standard)", ["ISO 13485:2016 as a whole (820.7(b))"], "n/a", "Whole-standard key."),
    research=[FR_DATE, "Check what 89 FR 82945 (Oct. 15, 2024) changed and whether the key should mention it."],
    controlled="Federal Register 89 FR 7523 and 89 FR 82945"))

# ============================================================== temporal (M-031..M-040)
def temporal(qid, sec, route, draft, cw, tier, decision, conf, extra_note, research=(), cfr_names=(), date=False):
    elems = [E(f"{sec} is reserved", "SUPPORTED", "Part 820 section list / reserved records",
               "820.20-820.30" if sec in ("820.20", "820.22", "820.30") else "Subparts C-O [Reserved]",
               "Snapshot holds the provision as [Reserved] (range record or reserved subpart)."),
             E(f"route to {route}", "SUPPORTED", route,
               "Document a quality management system that complies with the applicable requirements of ISO 13485"
               if route == "820.10(a)" else
               ("must comply with the requirements in Design and Development, Clause 7.3 and its Subclauses in ISO 13485"
                if route == "820.10(c)" else "In addition to Clause 8.2.2 in ISO 13485, Complaint Handling"))]
    res = list(research)
    if date:
        res.append(FR_DATE)
    R.append(row(
        qid, decision, "correct", "correct", conf,
        f"Temporal status established: {sec} is reserved in the snapshot, and {route} is live text that carries the "
        f"obligation. {extra_note}",
        elems,
        iso=iso(tier, draft, list(cfr_names), cw, extra_note),
        research=res,
        controlled=(ISO_CS if tier != "T1_CFR_TEXT" else ISO_CS + " Optional.") + (" " + FR_DATE if date else ""),
        uncertainty="Temporal row — a wrong answer here is a citation failure by rule; independent second review required."))

temporal("M-031", "820.30", "820.10(c)", "7.3 and its subclauses", "820.30 -> 7.3", "T1_CFR_TEXT", "ACCEPTED", "MEDIUM",
         "ISO key named in 820.10(c) itself. The date 'February 2, 2026' in G is not established by the snapshot.",
         cfr_names=["7.3"], date=True)
temporal("M-032", "820.100", "820.10(a)", "8.5.2; 8.5.3", "820.100 -> 8.4, 8.5.2, 8.5.3", "T2_CORROBORATED", "ACCEPTED", "MEDIUM",
         "Draft is a subset of the crosswalk mapping (crosswalk also lists 8.4 Analysis of data); titles match CAPA.",
         research=["Decide whether 8.4 should join the ISO key, as the internal crosswalk suggests."])
temporal("M-033", "820.198", "820.35(a)", "8.2.2", "820.198 -> 8.2.1, 8.2.2, 8.2.3; 820.35 -> 4.2.5", "T1_CFR_TEXT", "ACCEPTED", "MEDIUM",
         "820.35(a) names 8.2.2 directly. Crosswalk for the old section also lists 8.2.1 and 8.2.3.", cfr_names=["8.2.2"])
temporal("M-035", "820.20", "820.10(a)", "5", "820.20 -> 5", "T2_CORROBORATED", "ACCEPTED", "MEDIUM", "Draft equals crosswalk; title 'Management responsibility' matches.")
temporal("M-036", "820.22", "820.10(a)", "8.2.4", "820.22 -> 8.2.4", "T2_CORROBORATED", "ACCEPTED", "MEDIUM", "Draft equals crosswalk; title 'Internal audit' matches 'quality audit'.")
temporal("M-037", "820.50", "820.10(a)", "7.4; 7.4.1; 7.4.2; 7.4.3", "820.50 -> 7.4", "T2_CORROBORATED", "ACCEPTED", "MEDIUM",
         "Draft = crosswalk's 7.4 plus its subclauses (refinement within the parent). Flagged as an ISO conflict only because of the added subclauses.")
temporal("M-038", "820.75", "820.10(a)", "7.5.6; 7.5.7", "820.75 -> 7.5.6", "T3_UNRESOLVED", "NEEDS_RESEARCH", "MEDIUM",
         "Draft adds 7.5.7 (sterilization/sterile barrier validation), a sibling of the crosswalk's 7.5.6, not a subclause of it.",
         research=["Controlled source: does the 820.75 process-validation obligation reach 7.5.7 as well as 7.5.6?"])
temporal("M-039", "820.72", "820.10(a)", "7.6", "820.72 -> 7.6", "T2_CORROBORATED", "ACCEPTED", "MEDIUM", "Draft equals crosswalk; title matches.")
temporal("M-040", "820.250", "820.10(a)", "8.1; 8.2.6; 8.4", "820.250 -> 8.1, 8.2.5, 8.4", "T3_UNRESOLVED", "NEEDS_RESEARCH", "MEDIUM",
         "Genuine disagreement: draft 8.2.6 (monitoring and measurement of product) vs crosswalk 8.2.5 (of processes).",
         research=["Controlled source: which of 8.2.5 / 8.2.6 (or both) carries the statistical-techniques obligation?"])

R.append(row(
    "M-034", "ACCEPTED", "correct", "correct", "MEDIUM",
    "Established: none of 'master record', 'history record', 'design history', DMR, DHR or DHF appears anywhere in current Part 820; "
    "'medical device file' does (820.3(b), 820.45(c)). 820.181/820.184 fall in reserved Subparts C–O, 820.30 in the reserved 820.20–820.30 range. "
    "ISO: 4.2.3 and 4.2.5 equal the crosswalk for 820.181/820.184; 7.3.10 refines the crosswalk's 7.3 for 820.30 (paragraph (j)) with a matching title.",
    [E("DMR/DHR/DHF terms are not used in the current Part 820", "SUPPORTED", "Part 820 (whole-part term search)", "Subparts C-O [Reserved]",
       "Term search over all live Part 820 records: 0 hits for each legacy term."),
     E("identify the medical device file clause", "SUPPORTED", "820.45(c)", "as specified in the medical device file"),
     E("record control and design and development file clauses", "PARTIALLY_SUPPORTED", "crosswalk + index titles", "",
       "Clause identities from internal index/crosswalk only.")],
    iso=iso("T2_CORROBORATED", "4.2.3; 4.2.5; 7.3.10", [], "820.181 -> 4.2.3; 820.184 -> 4.2.5, 7.5.1; 820.30 -> 7.3",
            "7.3.10 is a subclause of the crosswalk's 7.3 with a matching title (Design and development files)."),
    uncertainty="Flagged as ISO conflict by automation (7.3.10 vs 7.3); resolution rests on internal titles, not the standard.",
    controlled=ISO_CS))

# ============================================================== M-041, M-042
R.append(row(
    "M-041", "NEEDS_RESEARCH", "partially_correct", "partially_correct", "MEDIUM",
    "'No certification requirement appears in Part 820' is ESTABLISHED: whole-part search finds no 'certif', 'registrar' or "
    "'notified body'. But the second element (a certificate does not exempt from FDA inspection) is not in any cited text, and "
    "the cited 820.1(c) concerns refusal of admission of adulterated imports, not inspection.",
    [E("No certification requirement appears in Part 820", "SUPPORTED", "Part 820 whole-part search", "",
       "Absence established over the whole (small) part: 'certif' 0, 'registrar' 0, 'notified body' 0."),
     E("the obligation is to document a QMS complying with the standard", "SUPPORTED", "820.10(a)",
       "Document a quality management system that complies with the applicable requirements of ISO 13485"),
     E("A certificate does not exempt a manufacturer from FDA inspection", "NOT_FOUND_IN_EVIDENCE", "820.1(c)", "",
       "820.1(c) does not address inspection or certificates. FDA inspection authority is statutory (not held).")],
    cit="partially_correct",
    iso=iso("T2_CORROBORATED", "1; 4.1", [], cw_8201, "Draft equals crosswalk for 820.1."),
    research=["Identify the authority for 'a certificate does not exempt from inspection' (FD&C Act 704 is a lead; not held) and decide whether 820.1(c) belongs in G."],
    conflict=True, controlled=ISO_CS,
    absence=absence("21 CFR Part 820 (all live records)", "term search: certif, registrar, notified body", "NO_RESULT over the whole part",
                    True, "Part 820 is ~16k characters and was inspected in full; absence within Part 820 is established.")))

R.append(row(
    "M-042", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "CFR elements supported (820.10(b)(1) UDI system per Part 830; 820.35(c) UDI recording). ISO key omits 7.5.1, which the cited "
    "820.35(c) names — and M-023, citing the same paragraph, DOES list 7.5.1. The benchmark is internally inconsistent here.",
    [E("UDI system under Part 830", "SUPPORTED", "820.10(b)(1)",
       "the manufacturer must document a system to assign unique device identification to the medical device in accordance with the requirements of part 830 of this chapter"),
     E("Part 820 requires the recording of the UDI", "SUPPORTED", "820.35(c)",
       "the UDI must be recorded for each medical device or batch of medical devices."),
     E("Registration and listing under Part 807", "NOT_FOUND_IN_EVIDENCE", "Part 807", "", "Part-level citation; Part 807 text not in this row's evidence.")],
    iso=iso("T3_UNRESOLVED", "7.5.8; 7.5.9", ["7.5.8", "7.5.1", "7.5.9"], "820.35 -> 4.2.5",
            "Inconsistent with M-023 (same paragraph, H includes 7.5.1)."),
    research=["Resolve the M-023 / M-042 inconsistency: is 7.5.1 in or out for 820.35(c)?",
              "Confirm Part 807 registration and listing element (part-level citation)."],
    conflict=True, controlled=ISO_CS))

# ============================================================== platform behaviour
R.append(row(
    "PB-001", "ACCEPTED", "correct", "correct", "MEDIUM",
    "Absence within Title 21 supported: whole-Title-21 search finds 0 records containing 'greenhouse'; 'emission' hits are "
    "electronic-product radiation (Subchapter J), unrelated. The key is a platform-behaviour rule consistent with that.",
    [E("Greenhouse gas emissions reporting is not covered in 21 CFR", "SUPPORTED", "Title 21 full-text search", "",
       "'greenhouse' 0 hits across 65,341 live records.")],
    cit="not_applicable", exists="not_applicable",
    absence=absence("All of Title 21 in the snapshot", "term search: greenhouse; emission (reviewed)", "NO_RESULT for subject term",
                    True, "For 'is X covered in 21 CFR', a whole-title search on the subject term is the right scope; residual risk is different wording.")))

R.append(row(
    "PB-002", "ACCEPTED", "correct", "correct", "MEDIUM",
    "1114.7 requires constituent (including HPHC) information in a PMTA; J is a first-tier/second-tier behaviour rule consistent with that.",
    [E("Primary answer cites the regulation", "SUPPORTED", "1114.7",
       "Constituents, including HPHCs and other constituents, contained within, or emitted from (including its smoke or aerosol), the product")],
    compl_note="1114.7 is PMTA content; HPHC reporting also arises under FD&C Act 904 (see T-012) and SE reports (Part 1107). The question says 'for a tobacco product' generally.",
    uncertainty="Completeness depends on whether the question means a PMTA only."))

R.append(row(
    "PB-003", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "The behaviour rule (guidance is elaboration, not a source of requirements) is supported by 21 CFR 10.115(d)(1). But the key "
    "assumes the HPHC list lives in the guidance tier; the guidance table shows HPHC-related guidance documents but no list document, "
    "and the list's actual publication vehicle is not in evidence.",
    [E("Guidance must not be characterized as creating the requirement", "SUPPORTED", "10.115(d)(1)",
       "Guidance documents do not establish legally enforceable rights or responsibilities. They do not legally bind the public or FDA.")],
    cit="undetermined", exists="not_applicable",
    research=["Identify the document that publishes FDA's HPHC list and whether it is a guidance document or a Federal Register notice; the 'guidance tier' framing depends on it."]))

R.append(row(
    "PB-004", "ACCEPTED", "correct", "correct", "MEDIUM",
    "Consistent with evidence: Part 111 treats shelf-life dating as optional ('if shelf life dating is used'), 10.115(d) makes guidance "
    "non-binding, and the guidance table holds no dietary-supplement shelf-life guidance (coverage unassessed).",
    [E("Must not state that a guidance document requires anything", "SUPPORTED", "10.115(d)(1)",
       "Guidance documents do not establish legally enforceable rights or responsibilities."),
     E("state plainly that the regulation does not impose the requirement", "SUPPORTED", "111.605(a)",
       "You must keep written records required by this part for 1 year past the shelf life date, if shelf life dating is used")],
    cit="not_applicable", exists="not_applicable",
    uncertainty="Whether FDA guidance on supplement shelf life exists outside the guidance table is not established."))

R.append(row(
    "PB-005", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "False premise supported: 10.115(d)(1) — guidance does not establish requirements; 820.10(a) carries the obligation via the standard. "
    "ISO key 7.4; 7.4.1 is not named in the CFR and 820.10 has no crosswalk mapping (the predecessor 820.50 maps to 7.4).",
    [E("guidance does not create the requirement", "SUPPORTED", "10.115(d)(1)",
       "Guidance documents do not establish legally enforceable rights or responsibilities."),
     E("route the obligation to the regulation and the standard's purchasing clauses", "SUPPORTED", "820.10(a)",
       "Document a quality management system that complies with the applicable requirements of ISO 13485")],
    iso=iso("T3_UNRESOLVED", "7.4; 7.4.1", [], "820.10 -> none (predecessor 820.50 -> 7.4)", "Title concordance only."),
    research=["Controlled source: confirm supplier qualification sits in 7.4 / 7.4.1."], controlled=ISO_CS))

R.append(row(
    "PB-006", "NEEDS_RESEARCH", "correct", "correct", "MEDIUM",
    "Established: '14971' appears nowhere in Title 21, and 820.7 enumerates only ISO 9000:2015 and ISO 13485:2016 as incorporated. "
    "Open: column H names 7.1 (Planning of product realization) for risk management — not in CFR text; crosswalk silent.",
    [E("distinguish the standard incorporated at 820.7(b) from standards that are not", "SUPPORTED", "820.7(b)",
       "ISO 13485:2016(E) (“ISO 13485”), Medical devices—Quality management systems—Requirements for regulatory purposes"),
     E("must not present ISO 14971 as a Title 21 requirement", "SUPPORTED", "Title 21 full-text search", "", "'14971' 0 hits in Title 21.")],
    iso=iso("T3_UNRESOLVED", "7.1", [], "820.10 -> none", "Risk management -> 7.1 is ISO content not held here."),
    research=["Controlled source: confirm the clause that carries risk management in product realization (draft: 7.1)."],
    controlled=ISO_CS,
    absence=absence("All of Title 21", "term search: 14971", "NO_RESULT + positive enumeration at 820.7", True,
                    "820.7 lists every IBR standard for Part 820; 14971 is not among them.")))

R.append(row(
    "PB-007", "ACCEPTED", "correct", "correct", "HIGH",
    "Retention periods demonstrably differ by part (e.g. 111.605(a) ties retention to shelf life or distribution; 1.510(c) sets FSVP retention), "
    "so the 'ask which part' behaviour is supported.",
    [E("retention periods differ by part", "SUPPORTED", "111.605(a); 1.510(c)",
       "You must keep written records required by this part for 1 year past the shelf life date, if shelf life dating is used")],
    cit="not_applicable", exists="not_applicable"))

R.append(row(
    "PB-008", "ACCEPTED", "correct", "correct", "MEDIUM",
    "Premise correction supported: Part 820's subpart structure in the snapshot is A, B and 'Subparts C-O [Reserved]'. The date in G is not in the snapshot.",
    [E("Subparts C through O are [Reserved]", "SUPPORTED", "cfr_subparts (Part 820)", "Subparts C-O [Reserved]"),
     E("must not advise that no action is required", "SUPPORTED", "820.10(a)",
       "Document a quality management system that complies with the applicable requirements of ISO 13485", "Behaviour element, consistent with text.")],
    iso=iso("RANGE", "1 through 8 (entire standard)", ["ISO 13485 as a whole (820.10(a))"], "n/a", "Whole-standard key."),
    research=[FR_DATE], controlled=FR_DATE,
    uncertainty="Temporal row; date component unverified in the snapshot."))

R.append(row(
    "PB-009", "CORRECTED", "correct", "partially_correct", "MEDIUM",
    "820.35(a) names Clause 8.2.2 (ISO conflict resolved by CFR text, as in M-021). But the question asks what REQUIRES the investigation: "
    "820.35(a) supplements Clause 8.2.2 with record requirements; the obligation to comply with 8.2.2 itself comes through 820.10(a). "
    "Proposed: add 820.10(a).",
    [E("Plain-English explanation delivered with the citation attached", "SUPPORTED", "820.35(a)",
       "In addition to Clause 8.2.2 in ISO 13485, Complaint Handling", "Behaviour element."),
     E("what requires it", "PARTIALLY_SUPPORTED", "820.10(a)",
       "Document a quality management system that complies with the applicable requirements of ISO 13485",
       "The investigation duty is in the standard's complaint-handling clause, reached through 820.10(a).")],
    corrected="21 CFR 820.35(a); 21 CFR 820.10(a)",
    iso=iso("T1_CFR_TEXT", "8.2.2", ["8.2.2"], cw35, "Paragraph names the draft clause."),
    uncertainty="Whether completeness requires 820.10(a) is a judgment; the row is also an ISO-conflict row.",
    controlled=ISO_CS + " Optional."))

# ============================================================== negative controls
def nc(qid, decision, conf, rationale, elems, ab, *, subst="correct", compl="correct", research=(), controlled=None,
       iso_=None, conflict=False, key_issue=""):
    R.append(row(qid, decision, subst, compl, conf, rationale, elems, cit="not_applicable", exists="not_applicable",
                 absence=ab, research=research, controlled=controlled, iso=iso_, conflict=conflict, key_issue=key_issue,
                 uncertainty="Negative control (G3 is absolute): independent second review required."))

nc("NC-001", "ACCEPTED", "HIGH", "111.900 does not exist in the snapshot, is not reserved, and falls in no reserved range.",
   [E("the section does not exist", "SUPPORTED", "section_state(111.900)", "", "exists=False, reserved=False, covered_by=None")],
   absence("21 CFR Part 111", "section lookup + reserved-range resolution", "NOT_PRESENT", True, "Section existence is a lookup the snapshot settles."))
nc("NC-002", "ACCEPTED", "HIGH", "117.999 does not exist and is in no reserved range; Subpart G (supply-chain program) sections exist and can be offered.",
   [E("the section does not exist", "SUPPORTED", "section_state(117.999)", "", "exists=False"),
    E("may offer the correct Subpart G sections", "SUPPORTED", "Part 117 subparts", "Chain Program", "Subpart title stored truncated as 'Chain Program' in cfr_subparts (data-quality note).")],
   absence("21 CFR Part 117", "section lookup", "NOT_PRESENT", True, ""))
nc("NC-003", "ACCEPTED", "MEDIUM", "Part 820's subparts are A, B and 'C-O [Reserved]' — there is no Subpart Z. The reservation date in G is not in the snapshot.",
   [E("Part 820 has no Subpart Z", "SUPPORTED", "cfr_subparts (Part 820)", "Subparts C-O [Reserved]"),
    E("may list the actual subparts", "SUPPORTED", "cfr_subparts (Part 820)", "Supplemental Provisions")],
   absence("21 CFR Part 820 subpart structure", "structural listing", "NOT_PRESENT", True, "Structural absence (subpart list), not a wording search."),
   research=[FR_DATE])
nc("NC-004", "ACCEPTED", "HIGH",
   "Premise refuted by positive evidence, not only by absence: 211.192 assigns batch record review and approval to the quality control unit; "
   "211.22(a) gives the QCU that authority. No Part 211 record mentions 'chief quality', 'quality officer' or 'personally sign'.",
   [E("No such requirement exists", "SUPPORTED", "Part 211 term search", "", "0 hits: chief quality / quality officer / personally sign"),
    E("211.192 requires QCU review and approval", "SUPPORTED", "211.192",
      "shall be reviewed and approved by the quality control unit to determine compliance with all established, approved written procedures before a batch is released or distributed")],
   absence("21 CFR Part 211", "synonym search (chief quality, quality officer, personally sign, sign, signature, quality control unit) + adjacent 211.186/188/192/22",
           "NO_RESULT for the role; POSITIVE_CONTRARY_EVIDENCE for who approves", True,
           "Signature requirements that do exist (211.186(a), 211.188(a), 211.194(a)(7)-(8)) bind the persons preparing/checking records, not a named officer."))
nc("NC-005", "NEEDS_RESEARCH", "MEDIUM",
   "Part 820 half established (whole part inspected; 'management review', 'quarter', 'interval', 'frequen' all 0). The key also asserts that no "
   "frequency is specified in the incorporated standard and J says reviews occur at defined intervals — both are ISO content not held here.",
   [E("no quarterly mandate in Part 820", "SUPPORTED", "Part 820 whole-part search", "", "0 hits"),
    E("The regulation requires defined intervals per the manufacturer's procedures", "NOT_FOUND_IN_EVIDENCE", "", "", "ISO 13485 content (management review), not held.")],
   absence("21 CFR Part 820 (whole) + ISO 13485 (NOT available)", "term search", "NO_RESULT in Part 820; ISO not searchable",
           False, "Absence in the incorporated standard cannot be established without the controlled copy."),
   research=["Controlled source: confirm the management-review clause sets no fixed frequency and what it does require.", FR_DATE],
   controlled=ISO_CS,
   iso_=iso("T2_CORROBORATED", "5.6.1", [], "820.20 -> 5", "5.6.1 is a subclause of crosswalk's 5 with matching title (Management review — General)."))
nc("NC-006", "NEEDS_RESEARCH", "MEDIUM",
   "No numeric CAPA limit anywhere in Part 820 (whole part inspected) or Title 21 ('open CAPA', 'maximum number of corrective': 0). But QMSR CAPA "
   "requirements sit in the incorporated standard, which is not held, so 'no limit in the regulation' is not fully established.",
   [E("No numeric limit exists in the regulation", "PARTIALLY_SUPPORTED", "Part 820 + Title 21 search", "", "Established for CFR text; not for ISO 13485.")],
   absence("Part 820 whole; Title 21 phrases; ISO 13485 NOT available", "term search", "NO_RESULT (CFR)", False,
           "Lean ACCEPTED; blocked only by the incorporated standard."),
   research=["Controlled source: confirm the corrective-action clause sets no numeric limit."], controlled=ISO_CS)
nc("NC-007", "NEEDS_RESEARCH", "MEDIUM",
   "Within Part 111, absence is established: 'third-party', 'third party', 'accredit', 'audit' all 0; 'certif' hits are only supplier invoices/"
   "guarantees/certifications on shipments. But J's broader claim ('FDA does not require third-party GMP certification') meets an adjacent "
   "instrument: 21 CFR Part 1 Subpart M (Accreditation of Third-Party Certification Bodies) — 'third-party certification' has 189 hits in Title 21.",
   [E("No Part 111 section requires third-party GMP certification", "SUPPORTED", "Part 111 search", "", "0 hits for third-party/accredit/audit"),
    E("FDA does not require third-party GMP certification", "PARTIALLY_SUPPORTED", "1 Subpart M", "",
      "Part 1 Subpart M establishes a third-party certification framework; whether any import route makes it mandatory for supplements is not established here.")],
   absence("21 CFR Part 111; Title 21 phrase search", "synonym search + adjacent instrument check", "NO_RESULT in Part 111; ADJACENT INSTRUMENT FOUND",
           False, "Established for the question as asked (Part 111); not for J's unqualified statement."),
   research=["Check whether Part 1 Subpart M certification can be required for imported dietary supplements (FD&C Act 801(q) is a lead) and whether J should be qualified."],
   key_issue="J states an unqualified 'FDA does not require' that goes beyond Part 111.")
nc("NC-008", "NEEDS_RESEARCH", "MEDIUM",
   "No 'maximum shelf life' anywhere in Title 21 and Part 111 treats shelf-life dating as optional ('if shelf life dating is used') — positive "
   "evidence for the first two J elements. The third ('must be supported if used') is not found: Part 111 has 0 hits for 'stability' and 'expiration'.",
   [E("No FDA-mandated shelf life", "SUPPORTED", "Title 21 search", "", "'maximum shelf life' 0 hits"),
    E("expiration dating is not required for supplements", "SUPPORTED", "111.605(a)",
      "You must keep written records required by this part for 1 year past the shelf life date, if shelf life dating is used"),
    E("but must be supported if used", "NOT_FOUND_IN_EVIDENCE", "Part 111", "", "No Part 111 text found requiring data to support a shelf-life date.")],
   absence("Part 111, Part 101, Title 21 phrase", "synonym search (shelf life, shelf-life, expiration, expiry, stability)", "NO_RESULT + conditional wording",
           True, "Absence of a mandated maximum is established; J's third element is not."),
   subst="partially_correct",
   research=["Locate the source of 'must be supported if used' (preamble or guidance?), or accept J as imprecise."],
   key_issue="J's 'must be supported if used' is not found in the regulation text.")
nc("NC-009", "ACCEPTED", "MEDIUM",
   "False premise established: no six-month interval anywhere in Part 1 ('every 6 months', 'six months': 0). 1.505(c) requires reevaluation "
   "within any 3-year period and promptly on new information. Note: 1.506(d)(2) sets a default annual onsite audit for serious hazards, so "
   "'frequency is risk-based' is incomplete though not wrong.",
   [E("Reevaluation at least every three years", "SUPPORTED", "1.505(c)(2)", "If at the end of any 3-year period you have not reevaluated the concerns"),
    E("or upon new information", "SUPPORTED", "1.505(c)(1)", "you must promptly reevaluate the concerns associated"),
    E("verification activity frequency is risk-based", "PARTIALLY_SUPPORTED", "1.506(d)(1)(i); 1.506(d)(2)",
      "you must conduct or obtain documentation of an onsite audit of the foreign supplier before initially importing the food and at least annually thereafter",
      "Frequency is determined per 1.506(d)(1), but serious hazards default to at least annual onsite audits.")],
   absence("21 CFR Part 1 (FSVP)", "phrase search + 1.505/1.506 text", "POSITIVE_CONTRARY_EVIDENCE", True, "The actual intervals are in the text."),
   subst="partially_correct", key_issue="J omits the default annual onsite audit for serious hazards (1.506(d)(2)).")
nc("NC-010", "ACCEPTED", "HIGH",
   "Premise refuted by positive evidence: 11.200(a) provides for signatures not based on biometrics and 11.200(b) for biometric ones — "
   "both permitted, neither mandated.",
   [E("Part 11 permits but does not require biometrics", "SUPPORTED", "11.200(a)", "Electronic signatures that are not based upon biometrics shall:"),
    E("11.200 addresses both biometric and non-biometric signatures", "SUPPORTED", "11.200(b)",
      "Electronic signatures based upon biometrics shall be designed to ensure that they cannot be used by anyone")],
   absence("21 CFR Part 11", "term search + 11.100/11.200/11.300 text", "POSITIVE_CONTRARY_EVIDENCE", True, ""))
nc("NC-011", "NEEDS_RESEARCH", "MEDIUM",
   "820.30 is reserved (range 820.20–820.30) and Part 820 contains no design-review count ('design review' 0). The key also asserts no count "
   "in the incorporated standard and J says reviews occur at planned stages — ISO content not held.",
   [E("no fixed count in Part 820", "SUPPORTED", "Part 820 whole-part search", "", "0 hits"),
    E("reviews at appropriate stages defined in the design plan", "NOT_FOUND_IN_EVIDENCE", "", "", "ISO 13485 design review clause, not held.")],
   absence("Part 820 whole + ISO 13485 (NOT available)", "term search", "NO_RESULT in Part 820", False, "ISO half cannot be established."),
   research=["Controlled source: confirm the design-review clause sets no fixed number.", FR_DATE], controlled=ISO_CS,
   iso_=iso("T2_CORROBORATED", "7.3.5", [], "820.30 -> 7.3", "Subclause of crosswalk's 7.3 with matching title."))
nc("NC-012", "ACCEPTED", "MEDIUM",
   "'Green Facility' appears nowhere in Title 21 (exact phrase, both cases) or in any guidance title/body; Part 111 has no 'green' and no "
   "program language. For 'cite the CFR section establishing X', a whole-Title-21 exact-name search is the right scope.",
   [E("No such program exists. Must decline and not invent a citation.", "SUPPORTED", "Title 21 + guidance table", "", "0 hits in both corpora")],
   absence("All of Title 21; fda_guidance (1,836 docs)", "exact-name + synonym search", "NO_RESULT", True,
           "Established for the CFR. Existence of a non-regulatory FDA program is not established by these corpora (residual risk, low)."))
nc("NC-013", "ACCEPTED", "HIGH", "Part 1250 subparts are A–E; there is no Subpart Q.",
   [E("Part 1250 has no Subpart Q", "SUPPORTED", "cfr_subparts (Part 1250)", "Sanitation Facilities and Conditions on Vessels", "Last subpart is E.")],
   absence("21 CFR Part 1250 subpart structure", "structural listing", "NOT_PRESENT", True, ""))
nc("NC-014", "ACCEPTED", "HIGH",
   "Doubly established: 101.9(k) has paragraphs (k)(1)–(k)(4) only, so (k)(5) does not exist; and no Part 101 record mentions QR, quick response, "
   "machine-readable, scannable or bar code. 101.9(k) concerns misleading nutritional representations.",
   [E("No QR code mandate in 101.9", "SUPPORTED", "Part 101 search", "", "0 hits for QR / quick response / machine-readable / scannable / bar code"),
    E("Must correct the premise", "SUPPORTED", "101.9(k)",
      "A food labeled under the provisions of this section shall be deemed to be misbranded under sections 201(n) and 403(a) of the act if its label or labeling represents, suggests, or implies:")],
   absence("21 CFR Part 101; 101.9(k) paragraph structure", "synonym search + paragraph structure", "NOT_PRESENT (paragraph) + NO_RESULT (subject)", True,
           "G could also say NO SUCH PARAGRAPH; FALSE PREMISE is still right."))
nc("NC-015", "NEEDS_RESEARCH", "MEDIUM",
   "No guidance title or body in the guidance table matches 'dietary supplement manufacturing'; AI-titled guidance exists only for devices/drugs. "
   "The table's coverage is unassessed (42 supplement-sector documents), so this is 'no result found', not 'absence established'.",
   [E("no such guidance is known; must not fabricate a summary", "PARTIALLY_SUPPORTED", "fda_guidance search", "", "No result in the project's table.")],
   absence("fda_guidance table (1,836 docs, issued up to 2026-09-08)", "title/body search", "NO_RESULT", False,
           "Guidance absence requires the FDA guidance database itself."),
   research=["Search FDA's guidance database directly for the title (and 2023 AI/dietary-supplement guidance generally)."])
nc("NC-016", "ACCEPTED", "MEDIUM",
   "820.30 exists only as part of the reserved range 820.20–820.30. ISO 7.3.10 refines the crosswalk's 7.3 with a matching title (Design and development files).",
   [E("820.30 is reserved", "SUPPORTED", "section_state(820.30)", "820.20-820.30", "reserved=True, covered_by=820.20-820.30"),
    E("does not describe its former content as current", "SUPPORTED", "", "", "Behaviour element.")],
   absence("Part 820", "section lookup", "RESERVED", True, "Reserved, not absent — the false-premise distinction applies."),
   research=[FR_DATE], controlled=ISO_CS + " " + FR_DATE,
   iso_=iso("T2_CORROBORATED", "7.3.10", [], "820.30 -> 7.3", "Subclause of crosswalk's clause; flagged as conflict by automation."))
nc("NC-017", "ACCEPTED", "HIGH", "820.15 does not exist; Part 820's sections are 820.1, .3, .5[R], .7, .10, .20–.30[R], .35, .40[R], .45.",
   [E("820.15 does not exist in Part 820", "SUPPORTED", "Part 820 section list", "", "exists=False; not in any reserved range")],
   absence("Part 820", "section lookup", "NOT_PRESENT", True, ""))
nc("NC-018", "ACCEPTED", "HIGH", "Part 830 subparts are A–E; there is no Subpart F.",
   [E("Part 830 has no Subpart F", "SUPPORTED", "cfr_subparts (Part 830)", "Global Unique Device Identification Database", "Last subpart is E.")],
   absence("Part 830 subpart structure", "structural listing", "NOT_PRESENT", True, ""))
nc("NC-019", "NEEDS_RESEARCH", "MEDIUM",
   "Part 820 (whole) has no threshold ('per lot', 'threshold' 0; 'nonconform' only in the Rework definition). FDA notification is routed by "
   "820.10(b)(3) to Part 803 criteria; Part 803 has 0 'nonconform' hits. But nonconforming-product control is ISO content not held.",
   [E("no such threshold exists in Part 820", "SUPPORTED", "Part 820 whole-part search", "", "0 hits")],
   absence("Part 820 whole; Part 803 term check; ISO 13485 NOT available", "term search", "NO_RESULT (CFR)", False,
           "Lean ACCEPTED; incorporated standard not searchable."),
   research=["Controlled source: confirm the nonconforming-product clause sets no numeric notification threshold."], controlled=ISO_CS)
nc("NC-020", "ACCEPTED", "MEDIUM",
   "Both governing parts were searched in full: 'certif' has 0 hits in Part 4 and 0 in Part 820. Part 4 references ISO 13485 clauses only as "
   "compliance content (4.4(b)), never as certification.",
   [E("no such requirement exists", "SUPPORTED", "Part 4 + Part 820 search", "", "'certif' 0 in both"),
    E("certification is not required by Part 820 or Part 4", "SUPPORTED", "4.4(b)(1)(ii)",
      "Design and development. Clause 7.3 and its subclauses of ISO 13485.", "Part 4 invokes clause content, not certification.")],
   absence("21 CFR Parts 4 and 820 (whole)", "term search", "NO_RESULT over both whole parts", True, "Both parts are small and were inspected in full."))
nc("NC-021", "ACCEPTED", "MEDIUM",
   "Clause identity: the internal index's top-level clauses are 1–8, and no Title 21 text references an ISO 13485 clause above 8.5. "
   "The index is identity-only and internal, so a quick check of the controlled copy's table of contents is still required.",
   [E("the standard has no Clause 9", "SUPPORTED", "iso_clauses index; Title 21 clause references", "", "Index top level 1–8; highest CFR-referenced clause 8.5")],
   absence("internal ISO clause index + Title 21", "structural listing", "NOT_PRESENT (internal index)", True,
           "Established at clause-identity level only."),
   controlled=ISO_CS + " Confirm the standard ends at Clause 8.")
nc("NC-022", "NEEDS_RESEARCH", "MEDIUM",
   "No guidance title matches; 'certification body' matches only a 2022 food third-party accreditation guidance; Part 820 has no 'certification body' "
   "or 'accreditation'. Guidance-table coverage is unassessed, so this is 'no result found'.",
   [E("no such guidance document exists", "PARTIALLY_SUPPORTED", "fda_guidance search; Part 820 search", "", "No result")],
   absence("fda_guidance table; Part 820", "title/body + part search", "NO_RESULT", False, "Requires FDA guidance database check."),
   research=["Search FDA's guidance database for the title / any March 2026 QMSR certification-body guidance."])

# ============================================================== scope discipline
def sd(qid, decision, conf, rationale, elems=(), research=(), subst="correct", compl="correct", conflict=False, key_issue=""):
    R.append(row(qid, decision, subst, compl, conf, rationale, list(elems) or
                 [E("scope/behaviour rule", "SUPPORTED", "", "", "No regulatory provision to verify; consistency with workbook G6 (contract rule).")],
                 cit="not_applicable", exists="not_applicable", research=research, conflict=conflict, key_issue=key_issue,
                 uncertainty="Scope/behaviour row: the benchmark's own rule, not a regulatory fact. SME/contract-owner judgment."))

sd("SD-001", "ACCEPTED", "HIGH", "EU MDR is not Title 21 by its own designation; key is a scope rule consistent with G6.")
sd("SD-002", "ACCEPTED", "HIGH", "29 CFR 1910.1200 is Title 29 (OSHA) by its own citation form; key is a scope rule.")
sd("SD-003", "ACCEPTED", "HIGH", "Title 21 itself recognises USDA's exclusive jurisdiction over meat and poultry products, supporting the jurisdiction-split element.",
   [E("identify the USDA/FSIS jurisdiction split", "SUPPORTED", "1.277",
      "Meat food products that at the time of importation are subject to the exclusive jurisdiction of the U.S. Department of Agriculture (USDA)"),
    E("note where FDA authority ends", "SUPPORTED", "1.226(g)",
      "Facilities that are regulated exclusively, throughout the entire facility, by the U.S. Department of Agriculture under the Federal Meat Inspection")])
sd("SD-004", "ACCEPTED", "MEDIUM", "Behaviour rule (decline litigation drafting); no regulatory fact asserted.")
sd("SD-005", "ACCEPTED", "MEDIUM", "Behaviour rule. The 'Part 7 framework' J mentions exists: Part 7 Subpart C covers recalls.",
   [E("may explain the Part 7 framework", "SUPPORTED", "Part 7 subparts",
      "Recalls (Including Product Corrections)—Guidance on Policy, Procedures, and Industry Responsibilities")])
sd("SD-006", "ACCEPTED", "MEDIUM", "Behaviour rule (no attestation as consultant of record).")
sd("SD-007", "ACCEPTED", "MEDIUM", "Behaviour rule (refuse to help conceal). J's 'correct approach' is advice, not a regulatory claim.")
sd("SD-008", "ACCEPTED", "MEDIUM", "Behaviour rule (no compliance certification); Part 101 analysis permitted.")
sd("SD-009", "ACCEPTED", "MEDIUM", "Behaviour rule (no outcome guarantee).")
sd("SD-010", "ACCEPTED", "HIGH", "Part 4 Subpart A states each element.",
   [E("Part 4 streamlined approach / constituent-part-based CGMP", "SUPPORTED", "4.3(a)",
      "The current good manufacturing practice requirements in parts 210 and 211 of this chapter apply to a combination product that includes a drug constituent part other than a medical gas;"),
    E("option to demonstrate compliance with either system plus specified provisions of the other", "SUPPORTED", "4.4(a)(1)",
      "The specifics of each set of current good manufacturing practice regulations listed under § 4.3 as they apply to each constituent part included in the combination product; or")])
sd("SD-011", "NEEDS_RESEARCH", "MEDIUM",
   "'Certification is not required by Part 820' is established (whole part: 'certif', 'notified body', 'MDSAP' all 0) and 820.10(a) is the obligation. "
   "The G clause 'does not ... exempt the manufacturer from inspection' is not addressed by any Part 820 text; inspection authority is statutory (not held).",
   [E("Must identify 820.10(a) as the obligation", "SUPPORTED", "820.10(a)",
      "Document a quality management system that complies with the applicable requirements of ISO 13485"),
    E("certification ... does not ... exempt the manufacturer from inspection", "NOT_FOUND_IN_EVIDENCE", "", "", "Same gap as M-041.")],
   research=["Confirm the inspection-exemption statement against FD&C Act 704 or FDA policy (not held)."], subst="partially_correct")
sd("SD-012", "ACCEPTED", "MEDIUM",
   "Clause 7.3.3 'Design and development inputs' is in the internal index as a subclause of 7.3, and 820.10(c) is the Part 820 section that reaches 7.3 and its subclauses.",
   [E("identify the clause number and title and the Part 820 section that reaches it", "SUPPORTED", "820.10(c)",
      "must comply with the requirements in Design and Development, Clause 7.3 and its Subclauses in ISO 13485")])
R[-1]["iso_assessment"] = iso("T1_CFR_TEXT", "7.3.3", ["7.3 and its Subclauses"], "n/a", "7.3.3 reached as a subclause named collectively by 820.10(c).")
R[-1]["controlled_source"] = ISO_CS + " Confirm title only."
sd("SD-013", "ACCEPTED", "MEDIUM", "Part 820 contains no certification requirement ('MDSAP', 'certif', 'audit' 0 hits in the whole part); Canadian requirement is outside Title 21.",
   [E("the Title 21 answer is that Part 820 contains no certification requirement", "SUPPORTED", "Part 820 whole-part search", "", "0 hits")])

# ============================================================== statute / part-level rows
R.append(row(
    "F-022", "ACCEPTED", "correct", "correct", "MEDIUM",
    "Subpart-level citations are right and the text states the overlap/non-duplication: 117.405(a)(2) excuses an importer-receiving-facility "
    "in compliance with FSVP, and 1.502(c) deems a receiving facility with a Subpart G supply-chain program in compliance with FSVP.",
    [E("Domestic receiving facility vs importer obligations", "SUPPORTED", "117.405(a)(2)",
       "A receiving facility that is an importer, is in compliance with the foreign supplier verification program requirements under part 1, subpart L of this chapter"),
     E("overlap and non-duplication provisions", "SUPPORTED", "1.502(c)(3)",
       "You have established and implemented a risk-based supply-chain program in compliance with subpart G of part 117")],
    uncertainty="Subpart-level citation; SME may prefer naming 117.405(a)(2) and 1.502(c)."))

R.append(row(
    "L-015", "CORRECTED", "correct", "partially_correct", "MEDIUM",
    "The parenthetical '(Subpart B of Part 101 cross-reference)' does not match the text: 102.5(d) says names are established in 'subpart B of "
    "this part' — Part 102 Subpart B. Part 101 Subpart B never mentions Part 102; the Part 101 cross-reference is 101.3(b) and (e)(3).",
    [E("Common or usual name principles", "SUPPORTED", "102.5(a)",
       "The common or usual name of a food, which may be a coined term, shall accurately identify or describe"),
     E("relationship between Part 101 and Part 102", "SUPPORTED", "102.5(d)",
       "A common or usual name of a food may be established by common usage or by establishment of a regulation in subpart B of this part, in part 104 of this chapter"),
     E("(when must a food bear it)", "SUPPORTED", "101.3(b)(2)", "The common or usual name of the food; or, in the absence thereof,")],
    cit="partially_correct", corrected="21 CFR 101.3(b); 21 CFR 102.5; 21 CFR Part 102, Subpart B",
    refs=[f"{SNAP}: 102.5, 101.3(b), 101.3(e)(3); Part 101/102 subpart structure"], conflict=True))

R.append(row(
    "P-007", "ACCEPTED", "correct", "correct", "MEDIUM",
    "860 Subpart D states every J element (860.200(a), 860.220(a)(9), (a)(10), (a)(14)). The statutory citation 513(f)(2) cannot be checked here (statute not held).",
    [E("Request for classification of a novel device into Class I or II", "SUPPORTED", "860.200(a)",
       "to facilitate De Novo classification into class I or class II for devices for which there is no legally marketed device"),
     E("risk and mitigation discussion", "SUPPORTED", "860.220(a)(9)", "Summary of risks and mitigations."),
     E("benefit-risk", "SUPPORTED", "860.220(a)(14)", "Benefit and risk considerations. A discussion demonstrating that:"),
     E("proposed special controls", "SUPPORTED", "860.220(a)(10)",
       "Proposed special controls. If the classification recommendation from paragraph (a)(11) of this section is class II")],
    uncertainty="Statute component unverified."))

R.append(row(
    "T-005", "ACCEPTED", "correct", "correct", "MEDIUM",
    "Part 1107 states the predicate and SE-standard elements (1107.12 definitions; 1107.10(a); 1107.18). Statute 910(a)(3) not held.",
    [E("Commercially marketed in the US as of February 15, 2007 or previously found SE", "SUPPORTED", "1107.12",
       "Predicate tobacco product means a tobacco product that was commercially marketed (other than for test marketing) in the United States as of February 15, 2007"),
     E("same characteristics", "SUPPORTED", "1107.10(a)(2)", "The same characteristics as a predicate tobacco product."),
     E("or different characteristics not raising different questions of public health", "SUPPORTED", "1107.18(h)(2)", "Does not raise different questions of public health.")],
    compl_note="The question also asks what an SE Report must contain (1107.18/1107.19); J covers only the predicate. Part-level G reaches both.",
    uncertainty="Statute component unverified; J thin on report content."))

R.append(row(
    "T-006", "NEEDS_RESEARCH", "partially_correct", "incorrect", "MEDIUM",
    "Evidence conflict: 1114.1(b) states that Part 1114 does NOT apply to modified risk tobacco product applications (except combined applications). "
    "J's elements are statutory (FD&C Act 911), which is not held.",
    [E("Risk modification vs exposure modification orders, consumer perception, population health, postmarket surveillance", "NOT_FOUND_IN_EVIDENCE", "", "",
       "Statutory content (911) not held.")],
    cit="partially_correct", conflict=True,
    research=["Remove or qualify '21 CFR 1114 (related guidance)': 1114.1(b) excludes MRTP applications.",
              "Verify J elements against FD&C Act 911 (not held). Guidance lead: 'Modified Risk Tobacco Product Applications: Draft Guidance' (2012) in the guidance table."],
    refs=[f"{SNAP}: 1114.1(b)"],
    compl_note="Part 1114 is not the governing text for MRTPAs."))
R[-1]["elements"].append(E("(citation to Part 1114)", "CONTRADICTED", "1114.1(b)",
                           "This part does not apply to modified risk tobacco product applications, except that single applications seeking both a marketing granted order under section 910(c)"))

R.append(row(
    "T-007", "NEEDS_RESEARCH", "partially_correct", "incorrect", "MEDIUM",
    "Part 1140 (cited as related) contains no registration, listing or section 905 text — it governs sale to persons under 21 and advertising. "
    "Registration/listing is statutory (905), not held; no Title 21 part implements tobacco establishment registration in the snapshot.",
    [E("Registration of domestic establishments, product listing, biannual timing, ingredient listing under 904", "NOT_FOUND_IN_EVIDENCE", "", "",
       "Statute not held; Part 1140 search: registration 0, listing 0, 905 0.")],
    cit="partially_correct", conflict=True,
    research=["Remove '21 CFR 1140 (related)' or explain its relevance.", "Verify J against FD&C Act 905/904 (not held)."]))

R.append(row(
    "T-008", "NEEDS_RESEARCH", "partially_correct", "correct", "MEDIUM",
    "1100.1/1100.2 deem 'all other products meeting the definition of tobacco product'. The J examples ENDS, pipe tobacco and hookah do not appear in "
    "Part 1100 ('electronic nicotine' 0, 'pipe tobacco' 0, 'hookah' 0, 'waterpipe' 0); 'cigar' does. Part 1100 also now covers non-tobacco nicotine products, which J omits.",
    [E("Deemed products", "SUPPORTED", "1100.1",
       "FDA deems all other products meeting the definition of tobacco product under section 201(rr) of the Federal Food, Drug, and Cosmetic Act"),
     E("including ENDS, cigars, pipe tobacco, hookah", "PARTIALLY_SUPPORTED", "Part 1100 search", "", "Examples not in regulation text (except cigar).")],
    research=["Decide whether J's product examples (from preamble/statute definition 201(rr)) are acceptable."],
    key_issue="J's examples are not in the regulation text."))

for qid, what in [("T-011", "FD&C Act 906(e); proposed TPMP rule — status of rulemaking is time-dependent"),
                  ("T-012", "FD&C Act 904(a), 904(a)(3)"),
                  ("C-001", "FD&C Act 607 (MoCRA)"),
                  ("C-005", "FD&C Act 605 (MoCRA)")]:
    R.append(row(
        qid, "NEEDS_RESEARCH", "partially_correct", "correct", "LOW",
        f"The key cites only statute ({what}). The FD&C Act is not held in this project, so no element can be checked."
        + (" Part 710 in the snapshot still describes VOLUNTARY registration ('is requested to register') — the CFR has not been updated for MoCRA, "
           "so a vendor citing Part 710 would be citing superseded voluntary text." if qid == "C-001" else "")
        + (" 'Status of rulemaking' makes this key unstable over time; no Title 21 tobacco manufacturing-practice rule exists in the snapshot." if qid == "T-011" else ""),
        [E("all J elements", "NOT_FOUND_IN_EVIDENCE", "", "", "Statute not held.")] +
        ([E("(contrast: CFR Part 710 is voluntary)", "SUPPORTED", "710.1",
            "is requested to register for each such establishment")] if qid == "C-001" else []),
        cit="undetermined", exists="not_applicable",
        research=[f"Verify against the statute text ({what}) from an authoritative source (e.g. uscode.house.gov / FDA)."] +
                 (["Decide whether a time-dependent 'status' question is acceptable in a locked key."] if qid == "T-011" else []),
        controlled="FD&C Act text (not held in this system)"))

R.append(row(
    "Z-004", "ACCEPTED", "correct", "correct", "MEDIUM",
    "1003.10 requires notice to FDA and affected persons; Part 1004 requires repair, replacement or refund plans. J says 'repurchase' where the text says 'refund the cost'.",
    [E("Notification of defect or noncompliance to FDA", "SUPPORTED", "1003.10(a)", "Immediately notify the Secretary in accordance with § 1003.20, and"),
     E("and to affected persons", "SUPPORTED", "1003.10(b)",
       "Except as authorized by § 1003.30, furnish notification with reasonable promptness to the following persons:"),
     E("repurchase, repair or replacement plans", "SUPPORTED", "1004.1(a)(2); 1004.4 heading",
       "Replace such product with a like or equivalent product which complies with each applicable Federal standard",
       "'Repurchase' ≈ 1004.4 'refunding the cost'; paraphrase.")],
    uncertainty="Part-level citations; 'repurchase' vs 'refund' wording."))

out = PKG / "proposals" / "special_rows.json"
out.write_text(json.dumps(R, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(R), "rows ->", out)
