"""Regulatory operators: the parts of a statement that decide what it requires.

Measured on the repository's own embedder (BAAI/bge-small-en-v1.5, the model
already pinned in `regulus.retrieval.semantic`), cosine similarity cannot see
any of them:

    evidence "shall establish and maintain procedures"
      vs "may establish procedures"                  cos 0.974   <- WRONG
      vs "must create and maintain documented …"     cos 0.959   <- RIGHT
    "within 30 days"      vs "within 90 days"        cos 0.892
    "the manufacturer"    vs "the importer"          cos 0.909
    "may not be shipped"  vs "may be shipped"        cos 0.951

The wrong modal scores HIGHER than the right paraphrase, so no similarity
threshold can separate them. Every one of these distinctions is therefore
decided here, by extraction and comparison, and similarity is confined to
choosing WHICH evidence sentence a claim is compared against
(`regulus.accuracy.alignment`).

Six operators, each extracted from the claim and from the evidence and then
compared:

    strength      MANDATORY / RECOMMENDED / PERMISSIVE / none
    polarity      AFFIRM / NEGATE / none
    actor         manufacturer, importer, applicant, …
    quantities    numbers with their unit kind (days, percent, degrees, …)
    dates         calendar dates and years
    conditions    the conditional qualifiers of regulus.rag.answer_plan

`compare` returns one `OperatorComparison` whose `conflicts` are hard
disagreements and whose `omissions` are things the evidence carries and the
claim drops. **Fail closed**: an operator that cannot be extracted from BOTH
sides is `undetermined` and never counted as agreement.

Reused rather than redefined: `extract_qualifiers`, `QUALIFIER_EQUIVALENTS`,
`CONDITIONAL_QUALIFIERS` and `extract_applicability` from
`regulus.rag.answer_plan`, which the generation prompt and shape validation
already use for the same operators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from regulus.rag.answer_plan import (
    CONDITIONAL_QUALIFIERS,
    QUALIFIER_EQUIVALENTS,
    extract_applicability,
    extract_qualifiers,
)

# ------------------------------------------------------------ strength

# ------------------------------------------------------------ source authority

# Binding regulation (eCFR) states requirements; FDA guidance is non-binding and
# conventionally writes "should" / "FDA recommends" even when it restates a rule.
# The two are compared differently: a modality, actor or condition that differs
# from GUIDANCE is not, by itself, a contradiction of a regulatory claim.
BINDING = "binding_regulation"
GUIDANCE = "guidance"
_GUIDANCE_CORPORA = frozenset({"fda_guidance", "guidance"})


def authority_of(corpus: str | None) -> str:
    """The authority of a source, from its corpus (eCFR -> binding, FDA guidance -> guidance)."""
    return GUIDANCE if (corpus or "").lower() in _GUIDANCE_CORPORA else BINDING


MANDATORY = "mandatory"
RECOMMENDED = "recommended"
PERMISSIVE = "permissive"
STRENGTHS = (MANDATORY, RECOMMENDED, PERMISSIVE)

# Ordered: the first pattern that matches a statement fixes its strength, and
# "may not" is a prohibition (mandatory) rather than a permission, so it is
# tested before "may".
_STRENGTH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (MANDATORY, re.compile(
        r"\b(?:shall|must)\s+not\b|\bmay\s+not\b|\bis\s+prohibited\b|\bare\s+prohibited\b|\bis\s+not\s+permitted\b"
        r"|\bshall\b|\bmust\b|\bis\s+required\b|\bare\s+required\b|\bis\s+obligated\b|\bare\s+obligated\b"
        r"|\brequires?\b|\brequired\s+to\b|\bhas\s+to\b|\bhave\s+to\b|\bmandate[sd]?\b", re.I)),
    (RECOMMENDED, re.compile(
        r"\bshould\b|\brecommend(?:s|ed|ation)?\b|\bis\s+encouraged\b|\bare\s+encouraged\b|\bbest\s+practice\b"
        r"|\bnon-?binding\b", re.I)),
    (PERMISSIVE, re.compile(
        r"\bmay\b|\bis\s+permitted\b|\bare\s+permitted\b|\bis\s+allowed\b|\bare\s+allowed\b|\bcan\b"
        r"|\bat\s+(?:its|their|the)\s+(?:option|discretion)\b|\boptional\b", re.I)),
)

# ------------------------------------------------------------ polarity

AFFIRM = "affirm"
NEGATE = "negate"

# A negated obligation: the statement says the thing must NOT happen, is
# prohibited, is not required, or does not apply.
#
# Measured on `main_clause` only, never on the whole sentence. Regulatory text
# is full of negatives inside CONDITIONS - "shall validate the process where the
# results cannot be fully verified by inspection" is an affirmative obligation
# whose condition contains "cannot" - and reading those as the obligation's
# polarity inverts the rule.
#
# "not required" counts only with its copula or modal ("is/are not required",
# "shall not be required", "need not"), which the alternatives below match. A
# bare "not required" qualifies a noun - "drug products not required to be
# sterile" in 21 CFR 211.113(a) - and was measured to negate that section's duty
# "shall be established and followed" and discard it as evidence (row D-009).
_NEGATE_RE = re.compile(
    r"\b(?:shall|must|may|can|will|does|do|is|are|were|was)\s+not\b|\bcannot\b|\bcan't\b"
    r"|\bis\s+prohibited\b|\bare\s+prohibited\b|\bprohibit(?:s|ed)\b|\bexempt(?:s|ed|ion|ions)?\b"
    r"|\bno\s+(?:person|manufacturer|device|product)\b|\bneed\s+not\b|\bnot\s+subject\s+to\b"
    r"|\bdo(?:es)?\s+not\s+apply\b|\bnot\s+applicable\b", re.I)

# Where a subordinate condition begins. The main clause is what precedes the
# first one of these that follows the obligation's modal.
_CONDITION_BOUNDARY_RE = re.compile(
    r"\b(?:where|when|whenever|if|unless|except|provided that|to the extent|in cases? where)\b", re.I)

# A purpose or result clause states what the obligation is FOR, not whether it
# applies: "signatures must be linked to their records to ensure that the
# signatures cannot be excised" is an affirmative duty whose purpose contains
# "cannot" (21 CFR 11.70; acceptance row E-007, read as a negated duty and
# marked contradicted). Like a condition, it is outside the obligation's scope.
#
# The same holds for the COMPLEMENT of ensure / assure / guarantee with or
# without "to": "these provisions ensure ... that electronic signatures cannot
# be repudiated" and "the manufacturer shall ensure that devices are not
# adulterated" are affirmative duties; the negative is part of what is ensured.
_PURPOSE_BOUNDARY_RE = re.compile(
    r"\b(?:(?:in\s+order\s+)?to\s+(?:prevent|avoid|protect)|so\s+that|such\s+that|so\s+as\s+to|in\s+order\s+that"
    r"|(?:(?:in\s+order\s+)?to\s+)?(?:ensure[sd]?|assure[sd]?|insure[sd]?|make\s+sure|guarantee[sd]?))\b", re.I)

# ------------------------------------------------------------ actor

# The parties a Title 21 requirement is placed on. Distinct parties, not
# synonyms: putting a manufacturer's duty on an importer is a different rule.
ACTORS: dict[str, re.Pattern[str]] = {
    "manufacturer": re.compile(r"\bmanufactur(?:er|ers|ing\s+establishment)\b", re.I),
    "importer": re.compile(r"\bimporters?\b", re.I),
    "distributor": re.compile(r"\bdistributors?\b", re.I),
    "applicant": re.compile(r"\bapplicants?\b", re.I),
    "sponsor": re.compile(r"\bsponsors?\b", re.I),
    "specification_developer": re.compile(r"\bspecification\s+developers?\b", re.I),
    "repackager": re.compile(r"\brepackagers?\b|\brelabelers?\b", re.I),
    "establishment": re.compile(r"\b(?:blood\s+)?establishments?\b", re.I),
    # Food and feed: 21 CFR 1.225 (food facility registration), parts 117 and 507
    # (receiving facility, supply-chain program). A facility is a regulated
    # party distinct from a manufacturer for these rules.
    "facility": re.compile(r"\b(?:food\s+|receiving\s+|foreign\s+|domestic\s+)?facilit(?:y|ies)\b", re.I),
    # Clinical: parts 50, 56, 312, 812 place distinct duties on each of these.
    "investigator": re.compile(r"\b(?:clinical\s+)?investigators?\b", re.I),
    "irb": re.compile(r"\bIRBs?\b|\binstitutional\s+review\s+boards?\b", re.I),
    "registrant": re.compile(r"\bregistrants?\b", re.I),
    "packer": re.compile(r"\bpackers?\b", re.I),
    "quality_unit": re.compile(r"\bquality\s+(?:control\s+)?unit\b", re.I),
    "practitioner": re.compile(r"\b(?:licensed\s+)?practitioners?\b|\bphysicians?\b", re.I),
    "laboratory": re.compile(r"\blaborator(?:y|ies)\b", re.I),
    "fda": re.compile(r"\bFDA\b|\bFood and Drug Administration\b|\bthe\s+agency\b", re.I),
}
# "person", "owner or operator" and "you" are deliberately NOT actors: they are
# open classes that a specific party legitimately instantiates, so treating them
# as distinct from "manufacturer" would manufacture conflicts.
_OPEN_ACTOR_RE = re.compile(r"\b(?:any\s+)?person\b|\bowner\s+or\s+operator\b|\byou\b|\beach\s+of\s+you\b", re.I)

# ------------------------------------------------------------ quantities

# (kind, pattern over "<number> <unit>"). The kind matters: 30 days and 30
# percent are not the same quantity, and a claim may legitimately carry a
# quantity of a kind the evidence does not mention at all.
_QUANTITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("percent", re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", re.I)),
    ("day", re.compile(r"(\d+(?:\.\d+)?)[\s-]*(?:calendar\s+|working\s+|business\s+)?days?\b", re.I)),
    ("month", re.compile(r"(\d+(?:\.\d+)?)[\s-]*months?\b", re.I)),
    ("year", re.compile(r"(\d+(?:\.\d+)?)[\s-]*years?\b", re.I)),
    ("hour", re.compile(r"(\d+(?:\.\d+)?)[\s-]*hours?\b", re.I)),
    ("degree", re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°|degrees?)\s*[CF]?", re.I)),
    ("dollar", re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")),
    ("form", re.compile(r"\bForm\s+(?:FDA\s+)?(\d{3,4}[A-Za-z]?)\b", re.I)),
)
_NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
              "eight": "8", "nine": "9", "ten": "10", "twelve": "12", "fifteen": "15", "twenty": "20",
              "thirty": "30", "sixty": "60", "ninety": "90"}
_WORD_QUANTITY_RE = re.compile(
    rf"\b({'|'.join(_NUM_WORDS)})[\s-]*(days?|months?|years?|hours?|percent)\b", re.I)

# ------------------------------------------------------------ dates

_DATE_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(\d{4})\b"
    r"|\b(\d{1,2}/\d{1,2}/(?:19|20)\d{2})\b"
    r"|\b((?:19|20)\d{2})\b")

# ------------------------------------------------------------ model


def _normalise_number(value: str) -> str:
    v = value.replace(",", "").strip()
    try:
        f = float(v)
    except ValueError:
        return v.lower()
    return str(int(f)) if f.is_integer() else str(f)


# Verbs by which one party directs another: the requirement they introduce
# belongs to the party named after them. Auxiliaries are deliberately absent.
_DIRECTIVE_RE = re.compile(
    r"\s*(?:recommend(?:s|ed)?|require[sd]?|expect(?:s|ed)?|encourage[sd]?|advise[sd]?|mandate[sd]?|ask(?:s|ed)?)\b",
    re.I)

# "may" and "can" are deontic only when they grant or withhold a permission. In
# regulatory recitals they are just as often EPISTEMIC - "bithionol may produce
# cross-sensitization", "exposure can cause cancer" - which states a possibility
# and grants nothing. Measured on acceptance row C-004, where the recital of
# 21 CFR 700.19(a) was read as a permission and a correct "is prohibited" claim
# was scored as contradicting it.
#
# A permissive modal counts as deontic when either the clause names a party the
# permission is granted to, or it is a passive permission over a regulated thing
# ("a device may not be shipped", "the product may be marketed").
_PASSIVE_PERMISSION_RE = re.compile(r"\b(?:may|can)\s+(?:not\s+)?be\s+[a-z]+(?:ed|en)\b", re.I)
_PERMISSIVE_MODAL_RE = re.compile(r"\b(?:may|can)\b", re.I)


def _deontic_permission(text: str) -> bool:
    if _PASSIVE_PERMISSION_RE.search(text):
        return True
    m = _PERMISSIVE_MODAL_RE.search(text)
    if not m:
        return True   # a non-modal permissive marker ("is permitted", "optional") is always deontic
    head = text[: m.start()]
    return any(pattern.search(head) for pattern in ACTORS.values()) or bool(_OPEN_ACTOR_RE.search(head))


def strength(text: str) -> str | None:
    """The deontic strength of the obligation the text states, or None when it
    states none (a recital, a definition, a description of history)."""
    body = main_clause(text or "")
    for name, pattern in _STRENGTH_PATTERNS:
        if pattern.search(body):
            if name == PERMISSIVE and not _deontic_permission(body):
                continue
            return name
    return None


def _first_modal(text: str) -> int | None:
    best: int | None = None
    for _, pattern in _STRENGTH_PATTERNS:
        m = pattern.search(text)
        if m and (best is None or m.start() < best):
            best = m.start()
    return best


def main_clause(text: str) -> str:
    """The clause carrying the obligation, with every conditional clause removed.

    A condition can sit before the obligation as easily as after it, and
    regulatory text puts it in both places:

        "Where the results of a process CANNOT be fully verified by subsequent
         inspection and test, the process shall be validated ..."
        "The process shall be validated where the results CANNOT be verified."

    Both are affirmative obligations whose CONDITION contains a negative, and
    reading that negative as the obligation's polarity inverts the rule. So each
    conditional clause - from its connector to the comma that closes it, or to
    the end of the sentence - is removed, and what remains is the obligation.
    Removal is abandoned if it would take the modal verb with it, which would
    leave nothing to judge.
    """
    body = text or ""
    spans: list[tuple[int, int]] = []
    for m in _CONDITION_BOUNDARY_RE.finditer(body):
        comma = body.find(",", m.end())
        spans.append((m.start(), comma if comma != -1 else len(body)))
    for m in _PURPOSE_BOUNDARY_RE.finditer(body):     # a purpose clause runs to the end of its sentence
        spans.append((m.start(), len(body)))
    spans.sort()
    if not spans:
        return body
    kept, cursor = [], 0
    for start, end in spans:
        if start >= cursor:
            kept.append(body[cursor:start])
            cursor = end + 1
    kept.append(body[cursor:])
    out = " ".join(part.strip() for part in kept if part.strip())
    if _first_modal(body) is not None and _first_modal(out) is None:
        return body          # the condition carried the obligation; judge the whole sentence
    return out or body


def polarity(text: str) -> str | None:
    """AFFIRM or NEGATE for a statement of an obligation; None for anything else.

    Polarity is a property of an obligation, so a sentence that states none - a
    recital such as "(a) Vinyl chloride has been used as an ingredient in
    cosmetic aerosol products" - has no polarity at all. Defaulting it to AFFIRM
    was measured to mark the correct claim "the use of vinyl chloride ... is
    prohibited" as contradicting that recital (acceptance row C-004), when the
    recital simply does not state the rule.
    """
    body = main_clause(text or "")
    if not body.strip():
        return None
    if _p2i_negations(body):
        return NEGATE
    return AFFIRM if strength(text) is not None else None


def duty_holder(text: str) -> str | None:
    """The party the obligation is placed ON: the actor nearest before the modal.

    Every actor mentioned in a sentence is not the duty-holder. "The importer
    shall submit the report to FDA" mentions both the importer and FDA; only the
    importer carries the duty, and comparing the full actor sets would let the
    shared mention of FDA hide the difference.
    """
    body = main_clause(text)
    modal = _first_modal(body)
    head = body[:modal] if modal is not None else body

    def nearest(segment: str, *, last: bool) -> str | None:
        best: tuple[int, str] | None = None
        for name, pattern in ACTORS.items():
            for m in pattern.finditer(segment):
                if best is None or (m.start() > best[0] if last else m.start() < best[0]):
                    best = (m.start(), name)
        return best[1] if best else None

    holder = nearest(head, last=True)
    # "FDA recommends that the manufacturer validate ..." / "FDA requires each
    # manufacturer to ...": with a DIRECTIVE verb the agency is the speaker and
    # the party carrying the requirement is named after it. With an AUXILIARY
    # ("FDA may withdraw ...", "FDA shall respond ...") the agency is itself the
    # actor, and a party named later is part of the object. Redirecting on an
    # auxiliary read "FDA may withdraw a qualified facility exemption" as a duty
    # on the facility and marked a correct claim contradicted (row F-003).
    if holder == "fda" and modal is not None and _DIRECTIVE_RE.match(body, modal):
        after = nearest(body[modal:], last=False)
        if after is not None and after != "fda":
            return after
    return holder


def actors(text: str) -> frozenset[str]:
    return frozenset(name for name, pattern in ACTORS.items() if pattern.search(text or ""))


def has_open_actor(text: str) -> bool:
    return bool(_OPEN_ACTOR_RE.search(text or ""))


def quantities(text: str) -> frozenset[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for kind, pattern in _QUANTITY_PATTERNS:
        for m in pattern.finditer(text or ""):
            out.add((kind, _normalise_number(m.group(1))))
    for m in _WORD_QUANTITY_RE.finditer(text or ""):
        unit = m.group(2).lower().rstrip("s")
        out.add(("percent" if unit == "percent" else unit, _NUM_WORDS[m.group(1).lower()]))
    return frozenset(out)


def dates(text: str) -> frozenset[str]:
    out: set[str] = set()
    for m in _DATE_RE.finditer(text or ""):
        out.add(next(g for g in m.groups() if g))
    return frozenset(out)


# "shall be approved ONLY upon examination" makes examination necessary; drop
# "only" and it reads as sufficient. regulus.rag.answer_plan's qualifier list
# (which serves the generation prompt and is not modified here) has no entry for
# it, so it is recognised here. Measured on row B-003, where the dropped "only"
# let a misleading restatement pass as a paraphrase.
RESTRICTIVE_ONLY = "only (restrictive)"
_RESTRICTIVE_ONLY_RE = re.compile(
    r"\bonly\s+(?:if|when|where|upon|after|before|for|to the extent|in accordance|as provided|with)\b", re.I)


# "provided that" states a condition the permission or requirement depends on
# (21 CFR 606.110(a): "may be at variance with the additional standards ...
# provided that: ..."). answer_plan's list has no entry for it (row B-005).
PROVIDED_THAT = "provided that"
_PROVIDED_THAT_RE = re.compile(r"\bprovided\s+(?:that|further\s+that|however\s+that)\b|\bon\s+condition\s+that\b", re.I)
_PROVIDED_EQUIVALENTS = re.compile(r"\bprovided\s+that\b|\bon\s+condition\s+that\b|\bonly\s+if\b|\bas\s+long\s+as\b|"
                                   r"\bsubject\s+to\b|\bif\b", re.I)


def conditions(text: str) -> frozenset[str]:
    """The conditional qualifiers this text carries: those of
    regulus.rag.answer_plan, plus a restrictive "only" and "provided that"."""
    out = {q for q in extract_qualifiers(text or "") if q in CONDITIONAL_QUALIFIERS}
    if _RESTRICTIVE_ONLY_RE.search(text or ""):
        out.add(RESTRICTIVE_ONLY)
    if _PROVIDED_THAT_RE.search(text or ""):
        out.add(PROVIDED_THAT)
    return frozenset(out)


def condition_preserved(qualifier: str, text: str) -> bool:
    """Whether `text` keeps `qualifier`, allowing the wordings the generation
    prompt itself treats as equivalent (QUALIFIER_EQUIVALENTS)."""
    if qualifier == PROVIDED_THAT:
        return bool(_PROVIDED_EQUIVALENTS.search(text or ""))
    if qualifier == RESTRICTIVE_ONLY:
        return bool(_RESTRICTIVE_ONLY_RE.search(text or "")) or bool(
            re.search(r"\b(?:solely|exclusively|unless|not\s+\w+\s+(?:until|unless|before))\b", text or "", re.I))
    low = (text or "").lower()
    return any(alt in low for alt in QUALIFIER_EQUIVALENTS.get(qualifier, (qualifier,)))


@dataclass(frozen=True)
class Operators:
    strength: str | None
    polarity: str | None
    actors: frozenset[str]
    duty_holder: str | None
    open_actor: bool
    quantities: frozenset[tuple[str, str]]
    dates: frozenset[str]
    conditions: frozenset[str]
    applicability: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"strength": self.strength, "polarity": self.polarity, "actors": sorted(self.actors),
                "duty_holder": self.duty_holder, "open_actor": self.open_actor, "quantities": sorted(f"{k}={v}" for k, v in self.quantities),
                "dates": sorted(self.dates), "conditions": sorted(self.conditions),
                "applicability": self.applicability}


def extract(text: str) -> Operators:
    return Operators(
        strength=strength(text), polarity=polarity(text), actors=actors(text), duty_holder=duty_holder(text),
        open_actor=has_open_actor(main_clause(text)),
        quantities=quantities(text), dates=dates(text), conditions=conditions(text),
        applicability=extract_applicability(text or ""),
    )


# ------------------------------------------------------------ comparison

CONFLICT_STRENGTH = "strength"
CONFLICT_POLARITY = "polarity"
CONFLICT_ACTOR = "actor"
CONFLICT_QUANTITY = "quantity"
CONFLICT_DATE = "date"
CONFLICT_CONDITION = "invented_condition"
OMISSION_CONDITION = "dropped_condition"

# A claim may state a weaker form of a mandatory rule only by being wrong about
# it; it may not state a stronger form of a permission either. Both directions
# are conflicts, because both misinform.
_STRENGTH_CONFLICTS = {
    (MANDATORY, RECOMMENDED), (MANDATORY, PERMISSIVE),
    (RECOMMENDED, MANDATORY), (PERMISSIVE, MANDATORY),
    (RECOMMENDED, PERMISSIVE), (PERMISSIVE, RECOMMENDED),
}


@dataclass(frozen=True)
class OperatorComparison:
    conflicts: tuple[dict[str, Any], ...] = ()
    omissions: tuple[dict[str, Any], ...] = ()
    undetermined: tuple[str, ...] = ()
    agreed: tuple[str, ...] = ()
    # Differences that were deliberately NOT counted as conflicts, with why
    # (operator, relation, claim value, evidence value): the forensic trace.
    relations: tuple[dict[str, Any], ...] = ()
    # Set when this passage cannot SUPPORT the claim although it does not
    # contradict it: guidance recommends what the claim states as a requirement.
    support_blocked: str | None = None
    authority: str = BINDING
    claim_operators: dict[str, Any] | None = None
    evidence_operators: dict[str, Any] | None = None

    @property
    def conflicted(self) -> bool:
        return bool(self.conflicts)

    def to_dict(self) -> dict[str, Any]:
        return {"authority": self.authority, "conflicts": list(self.conflicts), "omissions": list(self.omissions),
                "undetermined": list(self.undetermined), "agreed": list(self.agreed),
                "relations": list(self.relations), "support_blocked": self.support_blocked,
                "claim_operators": self.claim_operators, "evidence_operators": self.evidence_operators}


_STRENGTH_RANK = {PERMISSIVE: 0, RECOMMENDED: 1, MANDATORY: 2}

# A means or channel of performing an act: "through", "via", "using", "by means
# of", "either ... or".
_MEANS_RE = re.compile(r"\b(?:through|via|using|by\s+means\s+of|by\s+way\s+of|either)\b", re.I)


def _permission_over_means(claim: str, evidence: str, c_strength: str | None, e_strength: str | None) -> bool:
    """One side PERMITS a channel or means for the act the other side MANDATES,
    and the mandate names no means of its own: the permission is about how, not
    whether, so it is no modal conflict. "you may submit prior notice through
    either ABI/ACE/ITDS or FDA PNSI" against 21 CFR 1.279(a) "you must submit
    the prior notice to FDA" was measured as a contradiction (row H-003). A
    mandate that names its own channel still conflicts with a permission to use
    another, and a permission without a means, or over a different act, is
    still a modal conflict."""
    from regulus.accuracy.intent import stem

    if {c_strength, e_strength} != {PERMISSIVE, MANDATORY}:
        return False
    permitted, mandated = (claim, evidence) if c_strength == PERMISSIVE else (evidence, claim)
    permitted, mandated = main_clause(permitted), main_clause(mandated)
    modal = re.search(r"\b(?:may|can)\s+(?:be\s+)?([a-z]+)\b", permitted, re.I)
    if not modal or not _MEANS_RE.search(permitted[modal.end():]) or _MEANS_RE.search(mandated):
        return False
    act = stem(modal.group(1).lower())
    return any(stem(word.lower()) == act for word in re.findall(r"[A-Za-z]+", mandated))


def compare(claim: str, evidence: str, *, authority: str = BINDING) -> OperatorComparison:
    """Compare one claim with one aligned evidence passage, operator by operator.

    Fail closed: where an operator is absent from either side it is listed in
    `undetermined` and contributes neither a conflict nor an agreement. A
    contradiction needs a determinate conflict; an uncertain reading is never one.

    `authority` is the passage's source authority. Against GUIDANCE, a
    difference in modality, a different duty-holder or a condition the passage
    does not carry is recorded in `relations` and is not a conflict: guidance
    recommends, describes and addresses its reader, and none of that negates a
    regulatory requirement. A genuine opposite (must vs must not, prohibited vs
    permitted) and a different number or date are conflicts against either.
    """
    c, e = extract(claim), extract(evidence)
    conflicts: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    undetermined: list[str] = []
    agreed: list[str] = []
    relations: list[dict[str, Any]] = []
    support_blocked: str | None = None

    def note(kind: str, detail: str, claim_value: Any, evidence_value: Any) -> dict[str, Any]:
        return {"operator": kind, "detail": detail, "claim": claim_value, "evidence": evidence_value}

    def relate(kind: str, relation: str, claim_value: Any, evidence_value: Any, why: str) -> None:
        relations.append({"operator": kind, "relation": relation, "claim": claim_value, "evidence": evidence_value,
                          "authority": authority, "why": why, "verdict": "not_contradiction"})
        undetermined.append(kind)

    # -- strength: the measured blind spot of every similarity score
    if c.strength is None or e.strength is None:
        undetermined.append(CONFLICT_STRENGTH)
    elif authority == GUIDANCE and (c.strength, e.strength) in _STRENGTH_CONFLICTS:
        if _STRENGTH_RANK[c.strength] > _STRENGTH_RANK[e.strength]:
            relate(CONFLICT_STRENGTH, "guidance_weaker", c.strength, e.strength,
                   "guidance recommends or permits what the answer states as a requirement; non-binding wording "
                   "does not contradict a requirement")
            support_blocked = (f"the guidance passage is {e.strength}, so it does not establish the {c.strength} "
                               f"requirement the answer states")
        else:
            relate(CONFLICT_STRENGTH, "guidance_stronger", c.strength, e.strength,
                   "the guidance restates as a requirement what the answer states more weakly")
    elif _permission_over_means(claim, evidence, c.strength, e.strength):
        relate(CONFLICT_STRENGTH, "permission_over_means", c.strength, e.strength,
               "one side permits a channel or means for the act the other mandates, and the mandate names no means")
    elif (c.strength, e.strength) in _STRENGTH_CONFLICTS:
        conflicts.append(note(CONFLICT_STRENGTH,
                              f"the answer states a {c.strength} requirement where the evidence is {e.strength}",
                              c.strength, e.strength))
    else:
        agreed.append(CONFLICT_STRENGTH)

    # -- polarity: an obligation compared with an obligation, never with a
    # recital. A passage that states no rule cannot contradict one.
    if c.polarity is None or e.polarity is None or e.strength is None:
        undetermined.append(CONFLICT_POLARITY)
    elif c.polarity != e.polarity:
        conflicts.append(note(CONFLICT_POLARITY,
                              f"the answer is {c.polarity} where the evidence is {e.polarity}",
                              c.polarity, e.polarity))
    else:
        agreed.append(CONFLICT_POLARITY)

    # -- actor: the DUTY-HOLDER, not every party mentioned. A conflict only when
    # both sides state an obligation and name a determinate, different regulated
    # party for it; an open class ("any person", "you") on either side
    # legitimately instantiates the other.
    if c.duty_holder is None or e.duty_holder is None:
        undetermined.append(CONFLICT_ACTOR)
    elif c.duty_holder == e.duty_holder:
        agreed.append(CONFLICT_ACTOR)
    elif c.open_actor or e.open_actor:
        undetermined.append(CONFLICT_ACTOR)
    elif c.strength is None or e.strength is None:
        # a sentence that states no obligation has no duty-holder to transfer:
        # "FDA provides an abbreviated renewal process" describes, it does not
        # place the facility's renewal duty on FDA (acceptance row H-001)
        relate(CONFLICT_ACTOR, "no_obligation_compared", c.duty_holder, e.duty_holder,
               "one side states no obligation, so there is no duty whose holder could differ")
    elif "fda" in (c.duty_holder, e.duty_holder):
        relate(CONFLICT_ACTOR, "agency_action", c.duty_holder, e.duty_holder,
               "what FDA does (reviews, provides, recommends) does not negate what a regulated party must do")
    elif authority == GUIDANCE:
        relate(CONFLICT_ACTOR, "guidance_addressee", c.duty_holder, e.duty_holder,
               "guidance addresses its own reader; a different addressee is not an incompatible obligation")
    else:
        conflicts.append(note(CONFLICT_ACTOR,
                              f"the answer places the requirement on the {c.duty_holder.replace('_', ' ')} "
                              f"where the evidence places it on the {e.duty_holder.replace('_', ' ')}",
                              c.duty_holder, e.duty_holder))

    # -- quantities, compared within a kind. A claim value of a kind the
    # evidence also quantifies, but differently, is a conflict; a kind the
    # evidence never mentions cannot be judged from this passage.
    claim_kinds = {k for k, _ in c.quantities}
    for kind in sorted(claim_kinds):
        mine = {v for k, v in c.quantities if k == kind}
        theirs = {v for k, v in e.quantities if k == kind}
        if not theirs:
            undetermined.append(f"{CONFLICT_QUANTITY}:{kind}")
        elif mine & theirs:
            agreed.append(f"{CONFLICT_QUANTITY}:{kind}")
        else:
            conflicts.append(note(CONFLICT_QUANTITY,
                                  f"the answer states {kind} {sorted(mine)} where the evidence states {sorted(theirs)}",
                                  sorted(mine), sorted(theirs)))
    if not claim_kinds:
        undetermined.append(CONFLICT_QUANTITY)
    if "QSCOPE" in _P2I_FLAGS and support_blocked is None:      # Phase 2M
        support_blocked = _p2m_qscope(claim, evidence)
    if "DAYQ" in _P2I_FLAGS and support_blocked is None:        # Phase 2M
        support_blocked = _p2m_dayq(claim, evidence)

    # -- dates
    if not c.dates:
        undetermined.append(CONFLICT_DATE)
    elif not e.dates:
        undetermined.append(CONFLICT_DATE)
    elif c.dates & e.dates:
        agreed.append(CONFLICT_DATE)
    else:
        conflicts.append(note(CONFLICT_DATE,
                              f"the answer states {sorted(c.dates)} where the evidence states {sorted(e.dates)}",
                              sorted(c.dates), sorted(e.dates)))

    # -- conditions: one asymmetric pair of findings.
    # a condition the claim adds and the evidence does not carry -> conflict,
    # but only against a passage that states the rule: a passage stating no
    # obligation cannot show that the rule is unconditional (row H-006), and
    # guidance routinely leaves out exceptions it does not discuss.
    for qualifier in sorted(c.conditions - e.conditions):
        if qualifier == PROVIDED_THAT:
            # a proviso the evidence does not state is not shown wrong by it: recorded, never a conflict
            relate(CONFLICT_CONDITION, "proviso_not_in_evidence", qualifier, None,
                   "the passage does not carry this proviso; that does not show the rule has none")
        elif e.strength is None:
            relate(CONFLICT_CONDITION, "evidence_states_no_rule", qualifier, None,
                   "the passage states no obligation, so it cannot show the rule is unconditional")
        elif authority == GUIDANCE:
            relate(CONFLICT_CONDITION, "guidance_silent_on_condition", qualifier, None,
                   "guidance not mentioning a condition does not show the requirement has none")
        else:
            conflicts.append(note(CONFLICT_CONDITION,
                                  f"the answer conditions the requirement on '{qualifier}', which this evidence does not",
                                  qualifier, None))
    # a condition the evidence carries and the claim drops -> omission, not a conflict
    for qualifier in sorted(e.conditions):
        if not condition_preserved(qualifier, claim):
            omissions.append(note(OMISSION_CONDITION,
                                  f"the evidence limits the requirement with '{qualifier}' and the answer does not",
                                  None, qualifier))
    if e.conditions and not omissions and not (c.conditions - e.conditions):
        agreed.append(CONFLICT_CONDITION)

    return OperatorComparison(tuple(conflicts), tuple(omissions), tuple(undetermined), tuple(agreed),
                              relations=tuple(relations), support_blocked=support_blocked, authority=authority,
                              claim_operators=c.to_dict(), evidence_operators=e.to_dict())


# ---------------- Phase 2I OFFLINE candidates (flags set per copy)
_P2I_FLAGS: frozenset = frozenset(['DAYQ'])
_P2I_COMPLEMENT = frozenset("""ensure ensures ensured assure assures assured insure require requires required provide provides
state states stated specify specifies specified mean means determine determines determined certify certifies demonstrate
demonstrates show shows so such indicate indicates document documents verify verifies confirm confirms assurance assurances
evidence notify notifies inform informs agree agrees certification statement""".split())
_P2I_REL_NEG = re.compile(r"\b(that|which|who)\s+(?:(?:do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+not|cannot)\b", re.I)


def _p2i_relative_negation(body: str, m: "re.Match") -> bool:
    """B: the negation directly follows a relative pronoun that does not open a complement clause."""
    before = re.findall(r"[A-Za-z]+", body[: m.start()])
    return (len(before) >= 2 and before[-1].lower() in ("that", "which", "who")
            and before[-2].lower() not in _P2I_COMPLEMENT)


def _p2i_negations(body: str) -> list:
    out = []
    for m in _NEGATE_RE.finditer(body):
        if "REL" in _P2I_FLAGS and _p2i_relative_negation(body, m):
            continue
        if "EXN" in _P2I_FLAGS and m.group(0).lower().startswith("exempt") and not _p2m_exempt_predicate(body, m):
            continue                                      # 2M EXN: the noun 'exemption' is not a negated duty
        out.append(m)
    return out


_P2I_UNIT_SPLIT = re.compile(r"(?<=[.;:])\s+(?=\(?[A-Za-z0-9]{1,4}\)|[A-Z])|\n+(?=\s*\(?[A-Za-z0-9]{1,4}\))")


def _p2i_units(text: str) -> list:
    return [u.strip() for u in _P2I_UNIT_SPLIT.split(text or "") if u and u.strip()]


def _p2i_best_unit(text: str, other: str) -> str:
    """A: the sentence / enumerated unit of `text` that best matches `other` (stemmed content overlap)."""
    from regulus.accuracy.intent import stem
    units = _p2i_units(text)
    if len(units) < 2:
        return text
    want = {stem(w.lower()) for w in re.findall(r"[A-Za-z]{3,}", other or "")}
    def score(u):
        have = {stem(w.lower()) for w in re.findall(r"[A-Za-z]{3,}", u)}
        return len(want & have) / (len(have) or 1) + len(want & have)
    return max(units, key=score)


_P2I_REL_Q = re.compile(r"\b(?:that|which|who)\s+(?:(?:do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+)?(not\s+|cannot\s+)?(?:be\s+|been\s+)?([a-z]{3,})\b", re.I)
_P2I_AUX = frozenset("do does did is are was were will can could may must shall has have had would should be been not".split())


def _p2i_qualifiers(text: str) -> dict:
    """QUAL: {verb stem: negated?} for each relative clause ('batches that do not conform' -> conform: True)."""
    from regulus.accuracy.intent import stem
    out = {}
    for m in _P2I_REL_Q.finditer(text or ""):
        verb = m.group(2).lower()
        if verb in _P2I_AUX:
            continue
        neg = bool(m.group(1)) or bool(re.search(r"cannot\s*$", text[m.start():m.start(2)], re.I))
        out.setdefault(stem(verb), set()).add(neg)
    return out


_P2J_NOT_NOUN = frozenset("""a an the and or but of to for in on at by with from into onto upon as than that which who whom whose this these those
is are was were be been being am do does did has have had will would shall should may might must can could not no nor any each every all
some such its their his her our your it they he she we you if when where while whether""".split())
_P2J_PREP_PARTICIPLE = frozenset("""including following regarding concerning according excluding pending during notwithstanding using
involving considering beginning ending""".split())
_P2J_PART = re.compile(r"\b([a-z][a-z'\-]*)\s+(not\s+)?([a-z]{3,}ing)\b", re.I)
_P2J_WITHOUT = re.compile(r"\bwithout\s+([a-z]{3,}ing)\b", re.I)


def _p2j_key(word: str) -> str:
    w = word.lower()
    for suf in ("ing", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _p2j_same(a: str, b: str) -> bool:
    if "QEXACT" in _P2I_FLAGS:      # morphological identity only ("requir" ~ "require"), never prefix similarity
        return a == b or a + "e" == b or b + "e" == a
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long.startswith(short) and len(long) - len(short) <= 2


def _p2j_qualifiers(text: str) -> list:
    """[(verb key, negated)] for relative clauses AND participle / 'without' qualifiers."""
    out = []
    for m in _P2I_REL_Q.finditer(text or ""):
        verb = m.group(2).lower()
        if "QEXACT" in _P2I_FLAGS and verb.endswith("ly"):      # skip an adverb to reach the verb
            nxt = re.match(r"\s+([a-z]{3,})\b", text[m.end():], re.I)
            verb = nxt.group(1).lower() if nxt else verb
        if verb in _P2I_AUX:
            continue
        neg = bool(m.group(1)) or bool(re.search(r"cannot\s*$", text[m.start():m.start(2)], re.I))
        out.append((_p2j_key(verb), neg))
    if "QPART" in _P2I_FLAGS:
        for m in _P2J_PART.finditer(text or ""):
            head, neg, part = m.group(1).lower(), bool(m.group(2)), m.group(3).lower()
            if head in _P2J_NOT_NOUN or part in _P2J_PREP_PARTICIPLE or head.endswith("ing"):
                continue
            out.append((_p2j_key(part), neg))
        for m in _P2J_WITHOUT.finditer(text or ""):
            if m.group(1).lower() not in _P2J_PREP_PARTICIPLE:
                out.append((_p2j_key(m.group(1)), True))
    return out


def _p2j_qualifier_conflict(claim: str, evidence: str):
    qc, qe = _p2j_qualifiers(claim), _p2j_qualifiers(evidence)
    for kc, nc in qc:
        same = [ne for ke, ne in qe if _p2j_same(kc, ke)]
        if same and len(set(same)) == 1 and same[0] != nc and len({n for k, n in qc if _p2j_same(k, kc)}) == 1:
            return kc, nc, same[0]
    return None


# ---------------- Phase 2K fallbacks
_P2K_SKIP = frozenset("""the a an this that these those its their his her our your any each every all some such no
be been being is are was were do does did have has had will would shall should may might must can could to""".split())
_P2K_NEGATORS = frozenset("not no without never non".split())


def _p2k_key_after(body: str, m) -> str | None:
    """The qualifier's content word after the negation: skip auxiliaries, determiners and -ly adverbs
    ('that are not the subject' -> 'subject'; 'that cannot be adequately sanitized' -> 'sanitized')."""
    for w in re.findall(r"[A-Za-z][A-Za-z\-']*", body[m.end():])[:6]:
        lw = w.lower()
        if lw in _P2K_SKIP or lw.endswith("ly"):
            continue
        return _p2j_key(lw)
    return None


def _p2k_rel_qualifiers(text: str) -> list:
    """JR: [(key, negated)] for relative clauses only, determiner/adverb-aware."""
    out = []
    for m in re.finditer(r"\b(?:that|which|who)\b", text or "", re.I):
        before = re.findall(r"[A-Za-z]+", text[: m.start()])
        if before and before[-1].lower() in _P2I_COMPLEMENT:
            continue
        rest = text[m.end():]
        neg = bool(re.match(r"\s+(?:(?:do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+not\b|cannot\b)", rest, re.I))
        key = None
        for w in re.findall(r"[A-Za-z][A-Za-z\-']*", rest)[:6]:
            lw = w.lower()
            if lw in _P2K_SKIP or lw in ("not", "cannot") or lw.endswith("ly"):
                continue
            key = _p2j_key(lw); break
        if key and not (before and before[-1].lower() in ("to", "so", "such")):
            out.append((key, neg))
    return out


def _p2k_jr_conflict(claim: str, evidence: str):
    qc, qe = _p2k_rel_qualifiers(claim), _p2k_rel_qualifiers(evidence)
    for kc, nc in qc:
        same = [ne for ke, ne in qe if ke == kc or ke + "e" == kc or kc + "e" == ke]
        if same and len(set(same)) == 1 and same[0] != nc:
            return kc, nc, same[0]
    return None


def _p2k_mentioned_unnegated(key: str, other: str) -> bool:
    toks = re.findall(r"[A-Za-z][A-Za-z\-']*", other or "")
    for i, t in enumerate(toks):
        k = _p2j_key(t.lower())
        if k == key or k + "e" == key or key + "e" == k:
            prev = toks[i - 1].lower() if i else ""
            if prev not in _P2K_NEGATORS and not t.lower().startswith("non"):
                return True
    return False


def _p2k_relc_polarity(op, text: str, other: str):
    """JRC: drop a NEGATE that comes ONLY from relative-clause negations, unless the other side mentions
    that qualifier's word un-negated (then keep the production reading - the conservative choice)."""
    if op.polarity != NEGATE:
        return op
    body = main_clause(text or "")
    negs = list(_NEGATE_RE.finditer(body))
    rel = [m for m in negs if _p2i_relative_negation(body, m)]
    if not rel or len(rel) < len(negs):
        return op
    for m in rel:
        key = _p2k_key_after(body, m)
        if key is None or _p2k_mentioned_unnegated(key, other):
            return op
    import dataclasses as _dc
    return _dc.replace(op, polarity=AFFIRM if strength(text) is not None else None)


# ---------------- Phase 2L NUM: limit direction on the SAME quantity (independent of the clause logic)
_P2L_NUMW = "one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|sixty|ninety"
_P2L_NUM = rf"(\d+(?:,\d{{3}})*(?:\.\d+)?|{_P2L_NUMW})"
_P2L_UNIT = (r"(percent|%|(?:calendar\s+|business\s+|working\s+)?days?|weeks?|months?|years?|hours?|minutes?|"
             r"milligrams?|mg|grams?|g|kilograms?|kg|milliliters?|ml|liters?|ppm|ppb|degrees?)\b")
_P2L_PATTERNS = (   # longest / negation-bearing forms first; a span is claimed by the first pattern that matches it
    ("<=", r"\b(?:(?:do|does|did|shall|must|may|will|can|should)\s+not\s+exceed|not\s+to\s+exceed|not\s+exceeding|no\s+more\s+than|"
           r"not\s+more\s+than|at\s+most|up\s+to|no\s+longer\s+than|not\s+longer\s+than|maximum\s+of|within)"),
    (">=", r"\b(?:at\s+least|not\s+less\s+than|no\s+less\s+than|no\s+fewer\s+than|not\s+fewer\s+than|minimum\s+of)"),
    ("<",  r"\b(?:less\s+than|fewer\s+than|below|under|shorter\s+than)"),
    (">",  r"\b(?:exceed(?:s|ed|ing)?|more\s+than|greater\s+than|above|over|longer\s+than|in\s+excess\s+of)"),
)
_P2L_TIME = ("day", "calendar day", "business day", "working day", "week", "month", "year", "hour", "minute")
_P2L_NEGATORS = re.compile(r"\b(?:not|no|never|cannot|neither|nor)\b", re.I)
_P2L_STOP = frozenset("""a an the of to for in on at by with from and or that which who is are be been may must shall can will
used use any each such its their this these those than as""".split())


def _p2l_unit(u: str) -> str:
    u = re.sub(r"\s+", " ", u.lower()).strip()
    if u in ("%", "percent"): return "percent"
    for a, b in (("milligram", "mg"), ("gram", "g"), ("kilogram", "kg"), ("milliliter", "ml"), ("liter", "l")):
        if u.rstrip("s") == a: return b
    return u[:-1] if u.endswith("s") and u not in ("ppms",) else u


def _p2l_bounds(text: str) -> list:
    """[(relation, value, unit, context stems)] for each unambiguous bound; ambiguous ones are dropped."""
    from regulus.accuracy.intent import stem
    t = text or ""
    taken, out = [], []
    _all = []                                             # NUM2: every bound span, to discount their own negations
    for rel, phrase in _P2L_PATTERNS:
        for m in re.finditer(phrase + r"\s+(?:a\s+(?:period|total|level)\s+of\s+)?" + _P2L_NUM + r"\s*" + _P2L_UNIT, t, re.I):
            _all.append((m.start(), m.end()))
    for rel, phrase in _P2L_PATTERNS:
        for m in re.finditer(phrase + r"\s+(?:a\s+(?:period|total|level)\s+of\s+)?" + _P2L_NUM + r"\s*" + _P2L_UNIT, t, re.I):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            unit = _p2l_unit(m.group(m.lastindex))
            if rel == "<=" and re.match(r"\s*within", t[m.start():], re.I) and unit not in _P2L_TIME:
                continue                                  # 'within' bounds only durations
            clause = re.split(r"[.;:]\s", t[: m.start()])[-1]
            cstart = m.start() - len(clause)
            scan = clause
            if "NUM2" in _P2I_FLAGS:                       # discount negations inside OTHER bound phrases
                for s0, e0 in _all:
                    if e0 <= m.start() and s0 >= cstart:
                        scan = scan[: s0 - cstart] + " " * (e0 - s0) + scan[e0 - cstart:]
            if _P2L_NEGATORS.search(scan):                # a negation outside the bound phrase: scope ambiguous
                if "NNEG" in _P2I_FLAGS and _p2m_neg_governs(scan):
                    rel = _P2M_FLIP[rel]                  # 2M NNEG: 'shall not be retained for more than' = '<='
                else:
                    out.append(("ambiguous", None, None, None, None)); continue
            ctx = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", clause) if w.lower() not in _P2L_STOP][-4:]
            tail = frozenset()
            if "NUM2" in _P2I_FLAGS:                       # what the quantity is OF ('by weight of twine')
                after = re.split(r"[.;:]\s", t[m.end():])[0]
                tail = frozenset(stem(w.lower()) for w in [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", after)
                                 if w.lower() not in _P2L_STOP and w.lower() not in ("weight", "after", "before", "per")][:4])
            out.append((rel, _normalise_number(_NUM_WORDS.get(m.group(m.lastindex - 1).lower(), m.group(m.lastindex - 1))), unit,
                        frozenset(stem(w.lower()) for w in ctx), tail))
    return out


def _p2l_compare(claim: str, evidence: str):
    """('conflict' | 'boundary', detail) for the same value+unit+context, or None (no finding / ambiguous)."""
    bc, be = _p2l_bounds(claim), _p2l_bounds(evidence)
    if any(b[0] == "ambiguous" for b in bc):
        return None
    upper, lower = {"<=", "<"}, {">=", ">"}
    for rc, vc, uc, cc, tc in bc:
        same = [(re_, ce) for re_, ve, ue, ce, te in be if re_ != "ambiguous" and ve == vc and ue == uc and cc & ce
                and not ("NUM2" in _P2I_FLAGS and tc and te and not (tc & te))]
        rels = {r for r, _ in same}
        if not same or len(rels) != 1:
            continue                                      # nothing comparable, or the evidence reads two ways
        re_ = rels.pop()
        if re_ == rc:
            continue
        if (rc in upper) != (re_ in upper):
            return ("conflict", f"the answer bounds {vc} {uc} as '{rc}' where the evidence bounds it as '{re_}'")
        return ("boundary", f"the answer's boundary '{rc}' {vc} {uc} differs from the evidence's '{re_}'")
    return None

# ---------------- Phase 2M OFFLINE candidates (each an independent switch)
_P2M_STOP = frozenset("a an the of to for in on at by with from and or that which who is are be been may must shall can will its their this these those than as not no any each such".split())


def _p2m_stems(text):
    from regulus.accuracy.intent import stem
    return {stem(w.lower()) for w in re.findall(r"[A-Za-z]{3,}", text or "") if w.lower() not in _P2M_STOP}


def _p2m_units(text):
    # sentences; and '; '-separated clauses when EVERY clause carries its own modal (independent propositions)
    out = []
    for s_ in re.split(r"(?<=[.])\s+(?=\(?[A-Za-z0-9]{1,4}\)|[A-Z])", text or ""):
        parts = re.split(r";\s+", s_)
        if len(parts) > 1 and all(_first_modal(p) is not None for p in parts):
            out.extend(parts)
        else:
            out.append(s_)
    return [u.strip() for u in out if u.strip()]


def _p2m_anchor(evidence, claim):
    # PROP: the ONE evidence proposition the claim is anchored to, or None (ambiguous: keep the passage reading)
    units = _p2m_units(evidence)
    if len(units) < 2 or ";" in (claim or ""):
        return None
    want = _p2m_stems(claim)
    if len(want) < 3:
        return None
    sc = sorted((len(want & _p2m_stems(u)) / len(want) for u in units), reverse=True)
    best = max(units, key=lambda u: len(want & _p2m_stems(u)))
    if sc[0] >= 0.8 and sc[0] - sc[1] >= 0.25 and strength(best) is not None:
        return best
    return None


_P2M_REL_MODAL = re.compile(r"\b(?:that|which|who)\s+(?:may|shall|must|can|will)\s+(?:not\s+)?[a-z]+", re.I)


def _p2m_strip_rel_modal(body):
    # MODREL: a modal inside a relative clause ('a period that may not exceed') is not the main clause's modality
    out = body
    for m in reversed(list(_P2M_REL_MODAL.finditer(body))):
        before = re.findall(r"[A-Za-z]+", body[: m.start()])
        if before and before[-1].lower() in _P2I_COMPLEMENT:
            continue
        out = out[: m.start()] + out[m.end():]
    return out if _first_modal(out) is not None else body


def _p2m_qscope(claim, evidence):
    # QSCOPE: the answer's number matches only an evidence number that bounds a DIFFERENT stated quantity ('of twine' vs 'of glycol')
    bc, be = _p2l_bounds(claim), _p2l_bounds(evidence)
    if any(b[0] == "ambiguous" for b in bc):
        return None
    for rc, vc, uc, cc, tc in bc:
        same = [b for b in be if b[0] != "ambiguous" and b[1] == vc and b[2] == uc]
        if not same or not tc:
            continue
        scoped = [b for b in same if not (b[4] and not (tc & b[4]))]
        if not scoped:
            return f"the answer's {vc} {uc} bounds a different quantity in the evidence"
    return None


_P2M_DAYQ = re.compile(r"(\d+(?:\.\d+)?)[\s-]*(calendar|business|working)[\s-]+days?\b", re.I)


def _p2m_dayq(claim, evidence):
    # DAYQ: the same number of days counted by a different, explicitly stated convention
    norm = lambda q: "business" if q.lower() in ("business", "working") else q.lower()
    def read(t):
        d = {}
        for m in _P2M_DAYQ.finditer(t or ""):
            d.setdefault(_normalise_number(m.group(1)), set()).add(norm(m.group(2)))
        return d
    qc, qe = read(claim), read(evidence)
    for v, qs in qc.items():
        if v in qe and not (qs & qe[v]):
            return f"the answer counts {v} {'/'.join(sorted(qs))} days where the evidence counts {v} {'/'.join(sorted(qe[v]))} days"
    return None


_P2M_FLIP = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}


def _p2m_neg_governs(scan):
    # NNEG: the clause's ONLY negator is a modal negation directly governing the verb the bound completes
    if len(_P2L_NEGATORS.findall(scan)) != 1:
        return False
    return bool(re.search(r"\b(?:shall|must|may|will)\s+not\s+(?:be\s+)?[a-z]+(?:\s+(?:for|to|by))?\s*$", scan, re.I))


_P2M_COP = frozenset("be is are was were been being remain remains".split())


def _p2m_exempt_predicate(body, m):
    # EXN: 'exempt' negates a duty only as a predicate ('shall be exempt from', 'are exempted', 'FDA exempts')
    w = m.group(0).lower()
    if w in ("exemption", "exemptions"):
        return False
    if w == "exempts":
        return True
    before = [x.lower() for x in re.findall(r"[A-Za-z]+", body[: m.start()])[-2:]]
    return bool(before) and (before[-1] in _P2M_COP or (len(before) == 2 and before[0] in _P2M_COP and before[1].endswith("ly")))


_P2M_APPLY = re.compile(r"\b(?:(?:do|does|shall|will|did)\s+(not)\s+)?appl(?:y|ies)\s+to\b", re.I)


def _p2m_applic(text):
    # APPL: 'applies to' / 'does not apply to' in the main clause (not inside a relative clause)
    body = main_clause(text or "")
    found = set()
    for m in _P2M_APPLY.finditer(body):
        before = re.findall(r"[A-Za-z]+", body[: m.start()])
        if before and before[-1].lower() in ("that", "which", "who"):
            continue
        found.add("does not apply" if m.group(1) else "applies")
    return found.pop() if len(found) == 1 else None

