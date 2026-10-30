"""DR1 (30 Oct, off until measured): route a question to the regulatory programme it names - its 21 CFR parts and the
FD&C Act sections that programme is issued under - before the section picker reads its candidates. The query
classification + metadata filter step of search systems; cosmetics questions have had it since 22 Oct
(section_index.COSMETIC_PARTS).

full300d (29 Oct, client keys), the five weakest domains: food labeling 13 of 16 below PASS/PP, tobacco 10/12, device
submissions 8/12, radiological health 5/6, combination products 4/4. The candidates of a tobacco question were mostly
other programmes' sections (25.35, 1.79, 16.1, 606.121) and 1114.7 was not among them; the Act sections the tobacco
keys cite (904-911) were never offered although the store holds them - the picker named "FD&C Act 910(a)(2)(B)" for
T-001 and it was discarded. Other programmes' sections were picked for X-003 (820.1 for 4.4) and P-012 (830 for 801.20).

A question is routed only when it names exactly one programme by its own vocabulary and no 21 CFR part; a question
naming none ("How must net quantity of contents be declared?" - food 101.7, drug 201.62, device 801.62, cosmetic
701.13) is left as it is."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Programme:
    name: str
    parts: frozenset[str]
    act: tuple[str, ...]            # FD&C Act sections offered to the picker, when the statute store holds them
    words: re.Pattern               # case-insensitive programme vocabulary
    acronyms: re.Pattern | None     # case-sensitive ("ENDS", "PMA", "IDE" are words in lower case)
    # words other programmes use too ("principal display panel" is also an OTC drug's, 201.60): they count only beside
    # `context` ("food")
    shared: re.Pattern | None = None
    context: re.Pattern | None = None


# word edges by lookaround, not \b: "510(k)" ends in a parenthesis
def _ci(*alts: str) -> re.Pattern:
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.I)


def _cs(*alts: str) -> re.Pattern:
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)")


PROGRAMMES: tuple[Programme, ...] = (
    Programme(
        "tobacco", frozenset({"1100", "1105", "1107", "1114", "1140", "1141", "1143", "1150"}),
        ("900", "904", "905", "906", "907", "910", "911"),
        _ci(r"tobacco", r"e-?cigarettes?", r"electronic nicotine", r"cigars?", r"cigarettes?", r"smokeless", r"nicotine",
            r"vap(?:e|es|ing)", r"modified risk", r"harmful and potentially harmful", r"deeming rule",
            # "substantial equivalence" alone is also the 510(k) standard (P-002); its report and the exemption are tobacco
            r"substantial equivalence reports?", r"exemption from (?:the )?(?:substantial equivalence|SE)"),
        _cs(r"ENDS", r"PMTAs?", r"MRTPA?s?", r"HPHCs?", r"SE reports?")),
    Programme(
        "food_labeling", frozenset({"101", "102", "104", "105"}), ("403",),
        _ci(r"food labels?", r"food labeling", r"nutrition facts", r"nutrition labeling", r"nutrient content claims?",
            r"(?:qualified )?health claims?", r"structure/function claims?", r"reference amounts? customarily consumed",
            r"supplement facts", r"menu labeling",
            # allergens on a label, not cross-contact in a plant (117.135)
            r"allergens?\W+(?:\w+\W+){0,6}(?:label\w*|declar\w*)", r"(?:label\w*|declar\w*)\W+(?:\w+\W+){0,6}(?:food )?allergens?"),
        _cs(r"RACCs?"),
        shared=_ci(r"statement of identity", r"principal display panel", r"serving sizes?", r"vending machines?",
                   r"common or usual name"),
        context=_ci(r"foods?", r"beverages?", r"dietary supplements?")),
    Programme(
        "device_submissions", frozenset({"807", "812", "814", "860"}), ("510", "513", "515", "520"),
        _ci(r"510\(k\)s?", r"premarket notifications?", r"premarket approval", r"De Novo", r"investigational device(?: exemptions?)?",
            r"device classification", r"reclassification", r"classification panels?", r"humanitarian device exemptions?",
            r"513\(g\)", r"device listing"),
        _cs(r"PMAs?", r"IDEs?", r"HDEs?")),
    Programme(
        "radiological_health", frozenset({"900", "1000", "1002", "1003", "1004", "1005", "1010", "1020", "1030", "1040"}), (),
        _ci(r"mammograph\w*", r"radiation[- ]emitting", r"electronic products?", r"electronic product radiation",
            r"laser products?", r"x-ray", r"sunlamps?", r"accession numbers?", r"microwave ovens?", r"radiation safety"),
        _cs(r"MQSA")),
    Programme(
        "combination_products", frozenset({"3", "4"}), ("503",),
        _ci(r"combination products?", r"constituent parts?", r"primary mode of action", r"lead (?:agency )?center",
            r"requests? for designation", r"Office of Combination Products"),
        _cs(r"PMOA", r"RFDs?")),
)

_PART_NAMED = re.compile(r"\b(?:21\s*CFR|Part|Parts|§)\s*\d", re.I)
# another product programme or the import entry filing (ACE, Part 1 Subpart D) named: routing would hide its sections.
# Not for combination products, which are drug-device-biologic by definition
_OTHER = _ci(r"drugs?", r"over-the-counter", r"imports?", r"imported", r"importers?", r"cosmetics?", r"colou?r(?:s|ed|ing)?",
             r"colou?r additives?", r"colou?rants?", r"animal (?:food|feed)", r"clinical (?:trials?|investigations?)", r"research",
             r"IRBs?")
_OTHER_ACRONYMS = _cs(r"OTC", r"IND", r"NDAs?", r"ANDAs?", r"ACE", r"D&C")


def programme_for(question: str) -> Programme | None:
    """The one programme the question names, or None (none, several, or a 21 CFR part named - the part decides)."""
    q = question or ""
    if _PART_NAMED.search(q):
        return None
    hits = [p for p in PROGRAMMES
            if p.words.search(q) or (p.acronyms is not None and p.acronyms.search(q))
            or (p.shared is not None and p.shared.search(q) and p.context is not None and p.context.search(q))]
    if len(hits) != 1 or (hits[0].name != "combination_products" and (_OTHER.search(q) or _OTHER_ACRONYMS.search(q))):
        return None
    return hits[0]
