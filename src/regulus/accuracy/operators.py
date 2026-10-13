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
                  and, for a numeric LIMIT, its direction, boundary and what it measures
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

from regulus.accuracy.intent import stem
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
    if _NEGATE_RE.search(body):
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


# ------------------------------------------------------------ numeric limits

# A number is evidence of agreement only together with what it bounds. The
# quantity operator compares values within a kind, so it agreed that "at least
# 1 year" and "less than 1 year" state the same rule, that "not more than 0.1
# percent" of an impurity is the 0.1 percent use level a claim attached it to,
# that 15 business days are 15 calendar days and 143 °C is 143 °F. Each of those
# claims was credited (measured in artifacts/accuracy/measurement_audit_phase2l_*
# and _phase2m_*; regression rows in tests/test_accuracy_numeric_limits.py).
#
# A limit is a bound phrase, a number and a unit, with the words before and
# after it. Two limits are compared only when the value and the unit are
# identical - nothing is ever converted - and the surrounding words show they
# bound the same thing. Anything less certain is no finding.

CONFLICT_LIMIT = "limit_direction"

_LIMIT_NUMBER = rf"(\d+(?:,\d{{3}})*(?:\.\d+)?|{'|'.join(_NUM_WORDS)})"
_LIMIT_UNIT = (r"(percent|%|°\s*[CF]|degrees?(?:\s+(?:C|F|Celsius|Fahrenheit))?|"
               r"(?:calendar\s+|business\s+|working\s+)?days?|weeks?|months?|years?|hours?|minutes?|"
               r"milligrams?|mg|grams?|g|kilograms?|kg|milliliters?|ml|liters?|ppm|ppb)(?![A-Za-z])")
# Ordered: the negation-bearing and longer forms first, so "not more than" is
# never read as "more than"; a span belongs to the first pattern that claims it.
_LIMIT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("<=", r"\b(?:(?:do|does|did|shall|must|may|will|can|should)\s+not\s+exceed|not\s+to\s+exceed|not\s+exceeding|"
           r"no\s+more\s+than|not\s+more\s+than|at\s+most|up\s+to|no\s+longer\s+than|not\s+longer\s+than|maximum\s+of|within)"),
    (">=", r"\b(?:at\s+least|not\s+less\s+than|no\s+less\s+than|no\s+fewer\s+than|not\s+fewer\s+than|minimum\s+of)"),
    ("<", r"\b(?:less\s+than|fewer\s+than|below|under|shorter\s+than)"),
    (">", r"\b(?:exceed(?:s|ed|ing)?|more\s+than|greater\s+than|above|over|longer\s+than|in\s+excess\s+of)"),
)
_LIMIT_RE = tuple((relation, re.compile(phrase + r"\s+(?:a\s+(?:period|total|level)\s+of\s+)?" + _LIMIT_NUMBER
                                         + r"\s*" + _LIMIT_UNIT, re.I))
                  for relation, phrase in _LIMIT_PATTERNS)
_LIMIT_UPPER = frozenset({"<=", "<"})
_LIMIT_REVERSED = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}
_LIMIT_TIME = frozenset({"day", "calendar day", "business day", "working day", "week", "month", "year", "hour", "minute"})
_LIMIT_NEGATOR_RE = re.compile(r"\b(?:not|no|never|cannot|neither|nor)\b", re.I)
# "shall not be retained for more than 1 year" is "at most 1 year": a modal
# negation directly governing the verb the limit completes turns the limit
# around. Any other negation ("No record shall ...", a second "not") leaves its
# scope unclear, and the limit is not read.
_GOVERNING_NEGATION_RE = re.compile(r"\b(?:shall|must|may|will)\s+not\s+(?:be\s+)?[a-z]+(?:\s+(?:for|to|by))?\s*$", re.I)
_LIMIT_STOP = frozenset("""a an the of to for in on at by with from and or that which who is are be been may must shall can
will used use any each such its their this these those than as""".split())
_LIMIT_AFTER_SKIP = frozenset({"weight", "after", "before", "per"})
# "children under 12 years of age" says WHO a provision covers, not a limit the
# provision imposes: reversing it names another population, which no wording
# comparison can judge.
_AGE_RE = re.compile(r"\s*(?:of\s+age|old)\b", re.I)
_CLAUSE_SPLIT_RE = re.compile(r"[.;:]\s")


@dataclass(frozen=True)
class Limit:
    relation: str | None          # "<=", "<", ">=", ">"; None when the reading is ambiguous
    value: str | None = None
    unit: str | None = None
    before: frozenset[str] = frozenset()    # stems of the words that name what is bounded
    after: frozenset[str] = frozenset()     # ... and of what it is measured of or counted from
    age: bool = False

    @property
    def ambiguous(self) -> bool:
        return self.relation is None


def _limit_unit(unit: str) -> str:
    u = re.sub(r"\s+", " ", unit.lower()).strip()
    if u in ("%", "percent"):
        return "percent"
    scale = re.fullmatch(r"(?:°|degrees?)\s*(c|f|celsius|fahrenheit)?", u)
    if scale:
        return "degree" + (f" {scale.group(1)[0]}" if scale.group(1) else "")
    for name, short in (("milligram", "mg"), ("kilogram", "kg"), ("gram", "g"), ("milliliter", "ml"), ("liter", "l")):
        if u.rstrip("s") == name:
            return short
    return u[:-1] if u.endswith("s") else u


def _limit_terms(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[A-Za-z][A-Za-z\-]+", text) if w.lower() not in _LIMIT_STOP]


def numeric_limits(text: str) -> list[Limit]:
    """Every numeric limit the text states, in order. A limit whose clause
    carries a negation outside its own bound phrase is returned ambiguous."""
    t = text or ""
    found = [(m, relation) for relation, pattern in _LIMIT_RE for m in pattern.finditer(t)]
    spans = [(m.start(), m.end()) for m, _ in found]
    taken: list[tuple[int, int]] = []
    out: list[tuple[int, Limit]] = []
    for m, relation in found:
        if any(m.start() < end and start < m.end() for start, end in taken):
            continue
        taken.append((m.start(), m.end()))
        number, unit = m.group(m.lastindex - 1), _limit_unit(m.group(m.lastindex))
        if m.group(0).lower().startswith("within") and unit not in _LIMIT_TIME:
            continue                                     # "within" bounds only a duration
        clause = _CLAUSE_SPLIT_RE.split(t[: m.start()])[-1]
        offset = m.start() - len(clause)
        scan = clause
        for start, end in spans:                         # "not more than 0.1 percent": that "not" is its own limit's
            if start >= offset and end <= m.start():
                scan = scan[: start - offset] + " " * (end - start) + scan[end - offset:]
        if _LIMIT_NEGATOR_RE.search(scan):
            if len(_LIMIT_NEGATOR_RE.findall(scan)) == 1 and _GOVERNING_NEGATION_RE.search(scan):
                relation = _LIMIT_REVERSED[relation]
            else:
                out.append((m.start(), Limit(None)))
                continue
        after = _CLAUSE_SPLIT_RE.split(t[m.end():])[0]
        out.append((m.start(), Limit(relation, _normalise_number(_NUM_WORDS.get(number.lower(), number)), unit,
                                     frozenset(_limit_terms(clause)[-4:]),
                                     frozenset([w for w in _limit_terms(after) if w not in _LIMIT_AFTER_SKIP][:4]),
                                     bool(_AGE_RE.match(t[m.end():])))))
    return [limit for _, limit in sorted(out, key=lambda pair: pair[0])]


def _same_limit_scope(mine: Limit, theirs: Limit) -> bool:
    """The same value and unit bounding the same thing: a shared word before the
    number, and - where both say what it is of or counted from - a shared word after."""
    return (mine.value == theirs.value and mine.unit == theirs.unit and bool(mine.before & theirs.before)
            and not (mine.after and theirs.after and not mine.after & theirs.after))


def compare_limits(claim: str, evidence: str) -> tuple[str, str, str, str] | None:
    """("conflict", why, claim limit, evidence limit) when the claim reverses a
    limit the evidence states; ("blocked", ...) when it states the same limit
    with another boundary (at least vs more than) or reverses an age threshold;
    None when nothing is comparable or the claim's reading is ambiguous."""
    mine, theirs = numeric_limits(claim), numeric_limits(evidence)
    if any(limit.ambiguous for limit in mine):
        return None
    blocked = None
    for c in mine:
        same = [e for e in theirs if not e.ambiguous and _same_limit_scope(c, e)]
        relations = {e.relation for e in same}
        if len(relations) != 1:
            continue                                     # nothing comparable, or the evidence reads two ways
        (relation,) = relations
        if relation == c.relation:
            continue
        shown = (f"{c.relation} {c.value} {c.unit}", f"{relation} {c.value} {c.unit}")
        if c.age or any(e.age for e in same):
            blocked = blocked or ("blocked", f"the answer applies the rule to ages '{shown[0]}' where the evidence "
                                             f"applies it to '{shown[1]}'", *shown)
        elif (c.relation in _LIMIT_UPPER) != (relation in _LIMIT_UPPER):
            return ("conflict", f"the answer bounds {c.value} {c.unit} as '{c.relation}' where the evidence bounds "
                                f"it as '{relation}'", *shown)
        else:
            blocked = blocked or ("blocked", f"the answer's boundary '{c.relation}' {c.value} {c.unit} differs from "
                                             f"the evidence's '{relation}'", *shown)
    return blocked


def measured_quantity_mismatch(claim: str, evidence: str) -> str | None:
    """The claim's number appears in the evidence only as the limit on a
    DIFFERENT stated quantity ("0.1 percent by weight of twine" against "not
    more than 0.1 percent by weight of ethylene glycol")."""
    mine, theirs = numeric_limits(claim), numeric_limits(evidence)
    if any(limit.ambiguous for limit in mine):
        return None
    for c in mine:
        same = [e for e in theirs if not e.ambiguous and e.value == c.value and e.unit == c.unit]
        if c.after and same and all(e.after and not c.after & e.after for e in same):
            return f"the answer's {c.value} {c.unit} is, in the evidence, the limit on a different quantity"
    return None


_DAY_COUNT_RE = re.compile(r"(\d+(?:\.\d+)?)[\s-]*(calendar|business|working)[\s-]+days?\b", re.I)
_TEMPERATURE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°\s*|degrees?\s+)(C|F|Celsius|Fahrenheit)(?![A-Za-z])", re.I)


def _conventions(text: str) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for m in _DAY_COUNT_RE.finditer(text or ""):
        kind = "business" if m.group(2).lower() in ("business", "working") else "calendar"
        out.setdefault(("days", _normalise_number(m.group(1))), set()).add(kind)
    for m in _TEMPERATURE_RE.finditer(text or ""):
        out.setdefault(("degrees", _normalise_number(m.group(1))), set()).add(m.group(2)[0].upper())
    return out


def convention_mismatch(claim: str, evidence: str) -> str | None:
    """The same number counted in another explicitly stated convention:
    calendar vs business (or working) days, °C vs °F. Never converted; an
    unqualified "days" or "degrees" is not a mismatch."""
    mine, theirs = _conventions(claim), _conventions(evidence)
    for (kind, value), conventions in mine.items():
        other = theirs.get((kind, value))
        if other and not conventions & other:
            return (f"the answer states {value} {kind} as {'/'.join(sorted(conventions))} where the evidence states "
                    f"{value} {kind} as {'/'.join(sorted(other))}")
    return None


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
OMISSION_TIME_ANCHOR = "dropped_time_anchor"

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


# A time limit is two things: a period and the event it runs from. "No later than 7 calendar days after
# the sponsor's initial receipt of the information" (21 CFR 312.32(c)(2)) and "no later than 7 calendar
# days" agree on the period and nothing else - the second does not say when the clock starts. Nothing
# compared the event: `numeric_limits` reads bounds, not anchors, so an answer that dropped it was
# credited in full. Recorded acceptance row U-010 is one: "within 30 days" for 21 CFR 830.350(a)'s
# "within 30 days of receipt of FDA's notification", scored correct (100) against a hand rubric of N=1.
_ANCHOR_NUMBER = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|sixty|ninety)"
_ANCHOR_PERIOD = rf"({_ANCHOR_NUMBER})[\s-]+(?:(?:calendar|working|business)[\s-]+)?(day|week|month|year|hour)s?\b"
_ANCHOR_WORDS = r"(?:after|from|of|following|before|prior\s+to|upon|once|since|beginning|starting)"
_LIMIT_LEAD = (r"(?:no\s+later\s+than|not\s+later\s+than|in\s+no\s+case\s+later\s+than|later\s+than|within|"
               r"not\s+more\s+than|no\s+more\s+than|by)")
_ANCHORED_PERIOD_RE = re.compile(rf"\b{_ANCHOR_PERIOD}\s+{_ANCHOR_WORDS}\b", re.I)
_CLAIMED_LIMIT_RE = re.compile(rf"\b{_LIMIT_LEAD}\s+(?:\S+\s+){{0,2}}?{_ANCHOR_PERIOD}(?P<tail>[^.;]*)", re.I)
_TAIL_ANCHOR_RE = re.compile(rf"^\s*(?:\[\d+\]\s*)?{_ANCHOR_WORDS}\b", re.I)
_NUMBER_WORD_VALUES = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                       "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
                       "twenty": "20", "thirty": "30", "sixty": "60", "ninety": "90"}


def _period_key(number: str, unit: str) -> tuple[str, str]:
    return _NUMBER_WORD_VALUES.get(number.lower(), number), unit.lower()


def dropped_time_anchor(claim: str, evidence: str) -> str | None:
    """The claim states a time LIMIT the evidence also states, the evidence runs it from an event, and
    the claim gives no event at all: a description of what was left out, else None.

    Deliberately narrow. Only a limit ("no later than", "within", "not more than", "by" ...) counts on the
    claim side - a period used as a label ("the 7-calendar-day deadline") is not one. Only the SAME
    period counts - a different one is the quantity operator's business. And any anchor the claim does
    give is accepted unread, so a paraphrase ("within 7 days of receiving it") is never second-guessed:
    the finding is only that the event is missing, never that it is worded differently."""
    anchored = {_period_key(m.group(1), m.group(2)) for m in _ANCHORED_PERIOD_RE.finditer(evidence or "")}
    if not anchored:
        return None
    for m in _CLAIMED_LIMIT_RE.finditer(claim or ""):
        number, unit = _period_key(m.group(1), m.group(2))
        if (number, unit) in anchored and not _TAIL_ANCHOR_RE.match(m.group("tail") or ""):
            return (f"the evidence runs the {number}-{unit} period from a stated event, and the answer gives the "
                    f"period without it")
    return None


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

    # -- numeric limits: a matching number agrees only as the same limit on the
    # same quantity. A reversed limit is a conflict; the same number with another
    # boundary, quantity, day count, temperature scale or population is not
    # agreement, and the passage cannot support the claim - but it does not
    # contradict it either.
    limit = compare_limits(claim, evidence)
    if limit is not None and limit[0] == "conflict":
        conflicts.append(note(CONFLICT_LIMIT, limit[1], limit[2], limit[3]))
    else:
        mismatch = (limit[1] if limit else None) or measured_quantity_mismatch(claim, evidence) \
            or convention_mismatch(claim, evidence)
        if mismatch:
            agreed = [name for name in agreed if not name.startswith(f"{CONFLICT_QUANTITY}:")]
            relate(CONFLICT_QUANTITY, "not_the_same_limit", None, None, mismatch)
            if support_blocked is None:
                support_blocked = mismatch

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
    # the event a time limit runs from, dropped -> omission, never a conflict (see dropped_time_anchor)
    anchor = dropped_time_anchor(claim, evidence)
    if anchor is not None:
        omissions.append(note(OMISSION_TIME_ANCHOR, anchor, None, None))

    return OperatorComparison(tuple(conflicts), tuple(omissions), tuple(undetermined), tuple(agreed),
                              relations=tuple(relations), support_blocked=support_blocked, authority=authority,
                              claim_operators=c.to_dict(), evidence_operators=e.to_dict())
