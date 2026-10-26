"""Cosmetic manufacturing practices the regulations do not address (fix P1, 26 Oct 2026; plan-to-55pct lever 1).

"How often must we calibrate our scales?", "Do we need written cleaning SOPs and sanitation logs?", "Do we legally need
a pest-control contractor?", "Must our mixers be FDA certified?" - for cosmetics, no provision of Title 21 or of the
FD&C Act sets any of these, because the good manufacturing practice regulations FD&C Act section 606 calls for have not
been issued. The right answer says so, and says what does apply: section 601(c) (a cosmetic prepared, packed or held
under insanitary conditions is adulterated), 601(b) for filth, 601(f) once GMP rules exist, and section 610 for access
to records. Retrieval cannot find "the provision that is not there", so these questions got unrelated sources or a
decline (UC-004, -005, -008, -010, -012 on the 22 Oct holdout).

The silence is never assumed. It is a SEARCH, run on the text in the database: the general cosmetic provisions (21 CFR
Parts 700-740) and FD&C Act sections 601-614 are searched for the practice's terms, and only when nothing matches is
the absence stated - with that basis written into the answer. A provision added later (a GMP rule ingested into the
corpus) ends the silence automatically. The answer then quotes the Act's own text, each quotation cited; nothing else
is asserted. Switched by "P1" in regulus.rag.validator_switches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

GENERAL_COSMETIC_PARTS = ("700", "701", "710", "720", "740")
ACT_SECTIONS = tuple(str(s) for s in range(601, 615))
SEARCHED = "21 CFR Parts 700-740 and FD&C Act sections 601-614"
NOTE_PREFIX = "practice_silence:"
# the answer's first sentence: the search and its result, written by the pipeline (not a claim about the evidence)
SEARCH_SENTENCE_RE = re.compile(r"A search of 21 CFR Parts 700-740 and FD&C Act sections 601-614 in this system's "
                                r"verified text found no provision[^\n]*")


@dataclass(frozen=True)
class Practice:
    key: str
    asked: re.Pattern              # the question asks about the practice
    corpus: re.Pattern             # a provision about it would carry one of these words
    phrase: str                    # what the answer says no provision mentions
    absence: str                   # what is therefore not set
    filth: bool = False            # 601(b) (filthy substance) applies as well
    deleterious: bool = False      # 601(a) (poisonous or deleterious substance) applies as well


PRACTICES = (
    Practice("calibration", re.compile(r"\bcalibrat\w*", re.I), re.compile(r"calibrat", re.I),
             "the calibration of scales, meters or other instruments",
             "no calibration frequency and no calibration-record requirement"),
    # practice words only: "an inspector saw rodent droppings" asks who is covered, not whether a practice is
    # required (UC-011: answering it as a pest-control question was judged incomplete and potentially misleading)
    Practice("pest_control", re.compile(r"\bpest[- ](?:control|management)\b|\btrap maps?\b|\bpesticide logs?\b|"
                                        r"\bexterminat\w*", re.I),
             re.compile(r"\bpests?\b|pest control|rodent|vermin|exterminat", re.I),
             "pest control", "no pest-control contractor, program or record requirement", filth=True),
    Practice("sanitation_records", re.compile(r"\bcleaning\b|\bsanitation\b|\bsanitiz\w*|\bSOPs?\b|"
                                              r"standard operating procedures?", re.I),
             re.compile(r"sanitation|cleaning|sanitiz|standard operating procedure|\bSOPs?\b", re.I),
             "written cleaning or sanitation procedures or logs",
             "no requirement for written cleaning procedures or sanitation logs, and no retention period for them"),
    Practice("equipment_certification", re.compile(r"\b(?:equipment|mixers?|homogeni[sz]ers?|filling machines?|"
                                                   r"tanks?|kettles?)\b", re.I),
             re.compile(r"\bequipment\b", re.I),
             "the certification or qualification of manufacturing equipment",
             "no FDA certification, qualification or calibration requirement for manufacturing equipment",
             deleterious=True),
)
# the question must ask whether something is required (not "how do I clean my mixer?")
_ASKS_REQUIREMENT = re.compile(r"\b(?:require[sd]?|requirements?|must|need(?:s|ed)?|have to|has to|legally|"
                               r"mandatory|obligat\w*|how often|how long|certif\w*|qualif\w*|records?)\b", re.I)
_EQUIPMENT_ASK = re.compile(r"\bcertif\w*|\bqualif\w*|\bvalidat\w*|\bapprov\w*|\bregister\w*", re.I)
_RECORDS = re.compile(r"\brecords?\b|\blogs?\b|\bkeep\b|\bretain\w*|\bretention\b|\bhow long\b|\bfiles?\b", re.I)
_COSMETIC = re.compile(r"\bcosmetics?\b|\blotions?\b|\bcreams?\b|\bshampoos?\b|\bserums?\b|\bmakeup\b|\bsoaps?\b|"
                       r"\blipsticks?\b|\bbody washe?s?\b|\bskin ?care\b|\bfragrances?\b|\bnail polish", re.I)


# a product that may be a drug (sunscreen, antiperspirant, anti-dandruff, fluoride, acne...) falls under drug CGMP
# (21 CFR 210/211): "no requirement" would be wrong for it (UC-006: a face cream and an SPF 30 moisturizer on one kettle)
_DRUG = re.compile(r"\bSPF\b|\bsunscreens?\b|\bsun ?protect\w*|\bdrugs?\b|\bOTC\b|\bover[- ]the[- ]counter\b|"
                   r"\bantiperspirants?\b|\bdandruff\b|\bfluoride\b|\bacne\b|\banti-?bacterial\b|\bantiseptic\b|"
                   r"\bmedicat\w*|\btherapeutic\b", re.I)


def asked_practices(question: str) -> list[Practice]:
    """The practices a cosmetics requirement question asks about (empty when it asks none of them, or when the product
    may be a drug)."""
    q = question or ""
    if not (_COSMETIC.search(q) and _ASKS_REQUIREMENT.search(q)) or _DRUG.search(q):
        return []
    out = [p for p in PRACTICES if p.asked.search(q)]
    if any(p.key == "equipment_certification" for p in out) and not _EQUIPMENT_ASK.search(q):
        out = [p for p in out if p.key != "equipment_certification"]      # "clean the mixer" is not certification
    return out


_LICENSING = re.compile(r"\blicens\w*", re.I)
LICENSING_NOTE = "State or local licensing requirements are not part of FDA's regulations and are not addressed here."


def asks_records(question: str) -> bool:
    return bool(_RECORDS.search(question or ""))


_CFR_SQL = ("SELECT section_number, body_text FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved "
            "AND part_number = ANY(%(p)s)")


def silent(db, statute, practice: Practice) -> bool:
    """True when no general cosmetic provision and no cosmetics section of the Act mentions the practice. Run on every
    question it applies to (one query of about 2,600 rows; these questions are rare), so a provision added to the
    database is found without a restart."""
    rows = db.query(_CFR_SQL, {"p": list(GENERAL_COSMETIC_PARTS)})
    if any(practice.corpus.search(r["body_text"] or "") for r in rows):
        return False
    return not (statute is not None and any(practice.corpus.search(statute.rows[i]["body_text"] or "")
                                            for s in ACT_SECTIONS for i in statute.by_sec.get(s, ())))


def statute_paths(practices: list[Practice], records: bool) -> list[tuple[str, str]]:
    """The Act paragraphs the answer quotes: 606(a) and (c), 601(c) and (f), 601(b) for filth, 610(a) for records."""
    paths = [("606", "(a)"), ("606", "(c)"), ("601", "")]                     # 601's lead-in: "deemed adulterated"
    if any(p.deleterious for p in practices):
        paths.append(("601", "(a)"))
    paths.append(("601", "(c)"))
    if any(p.filth for p in practices):
        paths.append(("601", "(b)"))
    paths.append(("601", "(f)"))
    if records:
        paths.append(("610", "(a)"))
    return paths


def notes_for(practices: list[Practice]) -> tuple[str, ...]:
    return tuple(NOTE_PREFIX + p.key for p in practices)


def practices_of(notes) -> list[Practice]:
    keys = [n[len(NOTE_PREFIX):] for n in notes or () if str(n).startswith(NOTE_PREFIX)]
    return [p for p in PRACTICES if p.key in keys]


def _source(package, section: str, path: str):
    want = f"FD&C Act § {section}{path}"
    return next((s for s in package.sources if (s.citation or "").split(" [")[0].strip() == want), None)


def _quote(source) -> str:
    text = " ".join((source.text or "").split())
    return f"{source.citation.split(' [')[0]} states: \"{text}\" [{source.index}]."


def compose(package, question: str, notes) -> str | None:
    """The answer for a practice question the regulations do not address, or None when the promotion was not this one
    or a paragraph to quote is missing from the evidence."""
    practices = practices_of(notes)
    if not practices:
        return None
    needed = statute_paths(practices, asks_records(question))
    found = {(s, p): _source(package, s, p) for s, p in needed}
    if any(src is None for src in found.values()):
        return None
    what = "; ".join(p.absence for p in practices)
    mentions = " or ".join(p.phrase for p in practices)
    lines = [f"A search of {SEARCHED} in this system's verified text found no provision that mentions {mentions}: "
             f"for cosmetics there is {what}."]
    lines.append(_quote(found[("606", "(a)")]))
    lines.append(_quote(found[("606", "(c)")]))
    lines.append(_quote(found[("601", "")]))
    if ("601", "(a)") in found:
        lines.append(_quote(found[("601", "(a)")]))
    lines.append(_quote(found[("601", "(c)")]))
    if ("601", "(b)") in found:
        lines.append(_quote(found[("601", "(b)")]))
    lines.append(_quote(found[("601", "(f)")]))
    if ("610", "(a)") in found:
        lines.append(_quote(found[("610", "(a)")]))
    if _LICENSING.search(question or ""):
        lines.append(LICENSING_NOTE)       # "Do we legally need a LICENSED pest-control contractor?" (UC-010 key)
    return "\n".join(lines)
