"""BR1 (29 Oct 2026): requests a regulatory research tool must not carry out as asked, answered before retrieval decides.

A production assistant routes these by intent before it searches - a guardrail, not an answer from the evidence: a
certification or guarantee of compliance, a signature or attestation, help keeping a missing record from an investigator,
a court filing, the text of a copyrighted standard, another agency's rules, and a question too unscoped to answer. Each
gets a fixed answer that says what the tool cannot do, why, and what it can do instead. 300Q full300c: 10 of these
questions failed - the model answered a 211.34 paragraph to "sign it as my consultant of record", "certified" an invented
label, and declined USDA and OSHA questions as missing data instead of naming the agency.

`classify` returns (kind, detail) or None. Patterns are first-person and request-shaped on purpose: a question about what
the regulations say on falsified records, complaint files or certification is a regulatory question and is not caught.
"""
from __future__ import annotations

import re

# certify / guarantee an outcome: "Confirm that it is legally compliant", "Can you guarantee this answer would hold up"
_CERTIFY = re.compile(
    r"\b(?:confirm|certify|verify|guarantee|warrant|assure|promise)\b[^?.]{0,80}?\b(?:(?:is|are|it'?s|they'?re|will\s+be)\s+"
    r"(?:legally\s+|fully\s+)?(?:compliant|legal|lawful|approvable|in\s+compliance)|hold\s+up|pass(?:es)?\s+(?:an?\s+)?"
    r"(?:FDA\s+)?inspection|survive\s+(?:an?\s+)?(?:FDA\s+)?(?:inspection|challenge|review))\b"
    r"|\bguarantee\b[^?.]{0,60}\b(?:FDA|inspection|approv\w+|clear\w*|outcome)\b", re.I)
# act as a signatory / consultant of record / attest on someone's behalf
_ATTEST = re.compile(
    r"\b(?:sign|signs|signing|attest|countersign)\b[^?.]{0,60}?\b(?:as\s+(?:my|our|the)\b|on\s+(?:my|our)\s+behalf|of\s+record)\b"
    r"|\b(?:act|serve)\s+as\s+(?:my|our)\s+(?:regulatory\s+)?(?:consultant|agent|signatory)\b|\bconsultant\s+of\s+record\b", re.I)
# keep a missing record / gap from an investigator: "a record we never created. What should I tell him so it doesn't
# become an observation?"
_CONCEAL = re.compile(
    r"\bso\s+(?:that\s+)?(?:it|this|that)\s+(?:does\s*n[o']t|doesn'?t|won'?t|will\s+not)\s+(?:become|turn\s+into|end\s+up\s+as)\s+"
    r"(?:an?\s+)?(?:observation|483|finding|citation|warning\s+letter)\b"
    r"|\b(?:hide|conceal|cover\s+up|keep)\b[^?.]{0,40}\bfrom\s+(?:the\s+)?(?:FDA|investigator|inspector|auditor)\b"
    r"|\b(?:backdate|back-date|create\s+the\s+record\s+now|recreate\s+the\s+record)\b", re.I)
_CONCEAL_ACTOR = re.compile(r"\b(?:I|we|our|my|us)\b", re.I)
# a court filing: "Draft the complaint I should file in federal court" (a complaint FILE under 211.198 / 820 is not one)
_LITIGATION = re.compile(
    r"\b(?:draft|write|prepare|file)\b[^?.]{0,60}\b(?:complaint|lawsuit|petition|brief|motion|pleading|suit)\b[^?.]{0,60}"
    r"\b(?:court|lawsuit|litigation|sue|judge)\b|\bsue\s+(?:my|our|the|a)\b|\bfile\s+(?:a\s+)?(?:lawsuit|suit)\b", re.I)
# the text of a copyrighted standard: "Reproduce the full text of ISO 13485 Clause 7.3.3"
_REPRODUCE = re.compile(
    r"\b(?:reproduce|copy|paste|give\s+me|provide|quote|print|show\s+me)\b[^?.]{0,40}\b(?:full\s+text|verbatim|word[- ]for[- ]word|"
    r"entire\s+text|exact\s+text|text)\b[^?.]{0,30}\b(?P<std>ISO|IEC|ASTM|AAMI|ANSI|CLSI)\s*(?P<num>[\d:-]+)?", re.I)
_CLAUSE = re.compile(r"\bclause\s+(\d+(?:\.\d+)*)", re.I)
# another agency's rules, asked as such: "Which USDA FSIS regulation applies ...", "What does OSHA 29 CFR 1910.1200 require"
_AGENCIES = {
    "USDA": ("the U.S. Department of Agriculture's Food Safety and Inspection Service (FSIS), in 9 CFR",
             "FSIS regulates the labeling of meat, poultry and certain egg products; FDA regulates the labeling of most other "
             "foods, under 21 CFR Part 101. Which agency has a product that contains meat or poultry depends on its content, "
             "so the FSIS rules themselves are needed for that product"),
    "OSHA": ("the Occupational Safety and Health Administration (OSHA), in 29 CFR",
             "Workplace safety rules such as hazard communication are OSHA's, not FDA's; Title 21 governs the product - for "
             "example manufacturing practice, labeling and records - not the safety of the workers making it"),
    "EPA": ("the Environmental Protection Agency (EPA), in 40 CFR",
            "Pesticide registration, air and water discharges and hazardous-waste rules are EPA's; FDA's part is the safety of "
            "food, drugs, devices and cosmetics, including pesticide residue tolerances it enforces in food"),
    "CPSC": ("the Consumer Product Safety Commission (CPSC), in 16 CFR",
             "General consumer-product safety is CPSC's; FDA regulates foods, drugs, devices, biologics, cosmetics and tobacco"),
}
_ALIAS = {"FSIS": "USDA", "9CFR": "USDA", "29CFR": "OSHA", "40CFR": "EPA"}
_AGENCY = re.compile(r"\b(USDA|FSIS|OSHA|EPA|CPSC)\b|\b(9|29|40)\s*C\.?F\.?R\b")
_AGENCY_ASKED = re.compile(r"\b(?:which|what)\b[^?.]{0,40}\b(?:regulation|rule|requirement|standard|section)s?\b|\bwhat\s+does\b|"
                           r"\brequire[sd]?\b", re.I)
_FDA_TOO = re.compile(r"\bFDA\b|\b21\s*C\.?F\.?R\b|\bFD&C\b|\bTitle\s+21\b", re.I)
# a records question that names no product, sector or part: "What are the record retention requirements?"
_RETENTION = re.compile(r"^\s*(?:what|which)\s+(?:are|is)\s+the\s+(?:general\s+)?(?:record(?:s)?[- ]?(?:retention|keeping)|"
                        r"retention|recordkeeping)\s+(?:requirements?|periods?|rules?)\s*\??\s*$", re.I)

KINDS = ("certify", "attest", "conceal", "litigation", "reproduce_standard", "other_agency", "unscoped")


def classify(question: str) -> tuple[str, str] | None:
    """(kind, detail) for a boundary request, else None. Most specific first."""
    q = question or ""
    m = _REPRODUCE.search(q)
    if m:
        clause = _CLAUSE.search(q)
        std = f"{m.group('std').upper()} {(m.group('num') or '').strip(':- ')}".strip()
        return "reproduce_standard", f"{std}|{clause.group(1) if clause else ''}"
    if _CONCEAL.search(q) and _CONCEAL_ACTOR.search(q):
        return "conceal", ""
    if _LITIGATION.search(q):
        return "litigation", ""
    if _ATTEST.search(q):
        return "attest", ""
    if _CERTIFY.search(q):
        return "certify", ""
    a = _AGENCY.search(q)
    if a and _AGENCY_ASKED.search(q) and not _FDA_TOO.search(q):
        key = a.group(1).upper() if a.group(1) else f"{a.group(2)}CFR"
        return "other_agency", _ALIAS.get(key, key)
    if _RETENTION.match(q):
        return "unscoped", "retention"
    return None


_TOOL = "Regulus AI is an informational research tool for U.S. FDA regulations (21 CFR) and FDA guidance."
_LABEL_PARTS = ("For a label, the governing requirements are in 21 CFR Part 101 (food), Part 201 (human drugs), Part 801 "
                "(devices) and Part 701 (cosmetics); ask what one of them requires and each requirement is quoted and cited.")


def answer(kind: str, detail: str = "", question: str = "") -> str:
    if kind == "certify":
        return (f"{_TOOL} It cannot certify that a product, label, submission or answer is compliant, and it cannot guarantee "
                "how FDA would view it in an inspection, a review or an enforcement action: that depends on the facts of the "
                "case and on FDA's own determination. What it can do is set out what the governing regulations require, "
                "quoted and cited to the 21 CFR text, so that you - with qualified regulatory or legal advice - can check your "
                "case against them. " + (_LABEL_PARTS if re.search(r"\blabel", question or "", re.I) else ""))
    if kind == "attest":
        return (f"{_TOOL} It cannot sign, attest to or submit any document, and it cannot act as a consultant of record or on "
                "anyone's behalf: a response to FDA is signed by a responsible person who can vouch for it. It can help with "
                "the structure and the regulatory content of a draft"
                + (" - for a response to an FDA Form 483: each observation restated, the investigation of its cause, the "
                   "corrections and corrective actions with their dates, and the records that show them" if "483" in (question or "") else "")
                + " - which you then review, complete and sign yourselves.")
    if kind == "conceal":
        return ("Regulus AI cannot help keep a missing record or a gap from an FDA investigator, or suggest what to say so that it "
                "does not become an observation. Misleading an investigator, or creating a record afterwards so that it "
                "appears to have existed, can itself be a serious violation. The appropriate course is to tell the "
                "investigator plainly that the record was not created, then investigate why, assess the effect on the product, "
                "and document the correction and the corrective action under your quality system; if an observation is made, "
                "it is answered with that investigation and corrective action.")
    if kind == "litigation":
        return (f"{_TOOL} It cannot draft court filings or give legal advice. Under the FD&C Act, actions to enforce the Act are "
                "brought by the United States (section 310(a), 21 U.S.C. 337(a)), so a concern about another firm's product is "
                "reported to FDA - for example through MedWatch or the Safety Reporting Portal - and a private lawsuit is a "
                "matter for an attorney. Regulus AI can set out what the regulations require of the product, quoted and cited.")
    if kind == "reproduce_standard":
        std, clause = (detail.split("|", 1) + [""])[:2]
        named = f"{std} clause {clause}" if clause else std
        tail = (" Part 820 (the Quality Management System Regulation) incorporates ISO 13485:2016 by reference (21 CFR "
                "820.7) and states its requirements as supplements to the standard's clauses; ask what 21 CFR Part 820 "
                "requires on the subject and the relevant section is quoted and cited." if "13485" in std else
                " Where 21 CFR incorporates or recognises the standard, the regulation's own text can be quoted and cited.")
        return (f"Regulus AI cannot reproduce the text of {named}: the standard is copyrighted, and its text is not in Regulus "
                f"AI's sources. The standard can be obtained from its publisher.{tail}")
    if kind == "other_agency":
        agency = _AGENCIES.get(detail) or _AGENCIES["USDA"]
        return (f"This question is about the rules of {agency[0]}, not FDA, and is outside what Regulus AI covers: it answers "
                f"from U.S. FDA regulations (21 CFR) and FDA guidance only. {agency[1]}.")
    if kind == "premise_fact":
        return detail   # composed from the database by its caller (regulus.rag.nonexistence.subpart_statement)
    if kind == "unknown_guidance":
        title, documents, retrieved = (detail.split("|") + ["", ""])[:3]
        return (f"No FDA guidance document titled “{title}” is in FDA's guidance listing as Regulus AI holds it "
                f"({documents} documents, retrieved {retrieved}), so Regulus AI does not summarise or describe it: any "
                "summary would be invented. If the document has a different title or was issued after that date, FDA's "
                "guidance search on fda.gov is the place to confirm it; the regulation on the subject can be asked about here.")
    if kind == "unscoped":
        return ("Record retention periods differ by the kind of product and by the part of 21 CFR that governs it, so the "
                "answer depends on which applies - for example drug manufacturing (21 CFR Part 211), medical devices (Part "
                "820), dietary supplements (Part 111) or human food (Part 117). Which product or part do you mean? The "
                "retention requirements of that part can then be quoted and cited.")
    raise ValueError(f"unknown boundary kind {kind!r}")
