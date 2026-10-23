"""What a question asks for, as the accuracy evaluator needs to know it.

Phase 1 had no representation of the question at all: `question` reached the
evaluator and was used only to spot an answer that echoed it. So nothing could
tell "this sentence is true" from "this sentence answers the question", and
acceptance row D-001 - an answer made of twenty verbatim quotations of
21 CFR 211.100-211.132 given to a question about the SCOPE of Part 211 - passed
substantive correctness.

`QuestionIntent` records, deterministically and with no model:

    provisions   the CFR provisions the question names (regulus.planning.plan_query,
                 the pipeline's own parser - not a second one)
    parts        the parts those provisions belong to
    topic        the question's subject terms: what it is ABOUT once the question
                 words, generic regulatory vocabulary, the named provisions and the
                 product domain are removed ("scope", "personnel qualification
                 training", "children safeguards")
    domains      the Title 21 subchapters the question's product words imply
                 ("drug" -> C/D, "device" -> H, "cosmetic" -> G ...)
    elements     the separate things the answer must cover: the clauses of a
                 compound question ("which facilities must register, AND how often
                 must registration be renewed"), the items of a distinction
                 ("process, sanitation and allergen preventive controls"), or an
                 explicit "requirements and exceptions"
    kind         direct_lookup | scope | explanation | distinction |
                 cross_reference | application | temporal | negative_control |
                 list | exception | other

Why topic terms are allowed here when word overlap is prohibited elsewhere:
docs/STAGE_A_VALIDATOR_LIMITATION.md measured that a bag of words "measures
TOPICALITY, and topicality is exactly what every answer in this corpus has". It
was refuted as a measure of CORRECTNESS, which is what it was being used for.
Here it is used for exactly what it does measure - whether a passage is about
the question's subject - and correctness is still decided only by the
regulatory operators.

`regulus.planning.intent.analyze_question` is recorded alongside but not relied
on: it was built to steer generation, and on the validation questions it calls
the D-001 scope question and both distinction questions "procedure". The
planning package is not modified.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------ term handling

_WORD_RE = re.compile(r"[a-z][a-z'-]{2,}")

# Question words, generic regulatory vocabulary and connective words. A topic
# term must say what the question is ABOUT, so anything every regulatory
# question could contain is excluded.
_GENERIC = frozenset("""
what which who whom whose why how when where whether does did do is are was were be been being the a an and or of for
to in on at by with from into under over about this that these those there their its it as any all each every some
than then also such other same more most very much many can could would will shall should must may might need needs
require requires required requirement requirements apply applies applied applicable application regulation regulations
regulatory rule rules section sections provision provisions paragraph paragraphs part parts subpart subparts chapter
title cfr ecfr fda agency federal code according specific specified general current currently describe explain list
summarize summarise walk me tell give state states stated say says mean means set forth contain contains include
includes including impose imposes create creates add adds under per additional particular certain kind kinds type
types often long much many firm firms our you your they them use used using must applicable between differ differs
difference differences distinguish through has have not based given uses around built good practice practices cgmp
subject obligation obligations responsible assign assigned following manufacture manufacturer manufacturers
manufacturing
""".split())

# Product-domain words map to Title 21 subchapters. They are not topic terms -
# "drug" appears in every Part 211 sentence and says nothing about which part
# of Part 211 the question is about - they are checked separately.
_DOMAIN_WORDS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"\banimal\s+(?:food|feed)s?\b|\bmedicated\s+feeds?\b|\bveterinary\b|\banimal\s+drugs?\b", re.I),
     frozenset("E")),
    (re.compile(r"\bdietary\s+supplements?\b|\binfant\s+formula\b|\bfood(?!\s+and\s+drug)\b|\bfoods\b|\ballergens?\b", re.I),
     frozenset("AB")),
    (re.compile(r"\bdrugs?\b|\bdrug\s+products?\b|\bpharmaceuticals?\b|\bnational\s+drug\s+code\b", re.I),
     frozenset("CD")),
    (re.compile(r"\bbiologic(?:al)?s?\b|\bblood\b|\bvaccines?\b|\bplasma\b|\bbiologics?\s+license\b", re.I),
     frozenset("F")),
    (re.compile(r"\bcosmetics?\b", re.I), frozenset("G")),
    (re.compile(r"\bdevices?\b|\bmedical\s+devices?\b|\bIDE\b|\b510\(k\)", re.I), frozenset("H")),
    (re.compile(r"\btobacco\b|\bcigarettes?\b|\bcigars?\b|\bsmokeless\b|\be-?cigarettes?\b", re.I), frozenset("K")),
)
_DOMAIN_TERMS = frozenset("""drug drugs product products device devices medical food foods dietary supplement supplements
cosmetic cosmetics biologic biologics biological blood vaccine vaccines plasma tobacco animal feed feeds pharmaceutical
""".split())

# Title 21's own structure: subchapter by part number. Fixed by the CFR, so
# derived here rather than looked up.
_SUBCHAPTERS = ((1, 99, "A"), (100, 199, "B"), (200, 299, "C"), (300, 499, "D"), (500, 599, "E"), (600, 699, "F"),
                (700, 799, "G"), (800, 899, "H"), (900, 999, "I"), (1000, 1099, "J"), (1100, 1199, "K"),
                (1200, 1499, "L"))
SUBCHAPTER_NAMES = {"A": "general", "B": "food and dietary supplements", "C": "drugs (general)",
                    "D": "drugs for human use", "E": "animal drugs, feeds and related products",
                    "F": "biologics", "G": "cosmetics", "H": "medical devices", "I": "mammography",
                    "J": "radiological health", "K": "tobacco products", "L": "other acts"}

_SUFFIXES = ("izations", "ization", "ational", "ations", "ation", "ments", "ment", "ities", "ity", "ings", "ing",
             "ions", "ion", "ies", "ied", "ers", "er", "ed", "es", "s")


def stem(word: str) -> str:
    """A small, symmetric suffix stripper. Applied identically to the question,
    the claim and the evidence, so it only has to be consistent with itself."""
    w = word.lower().strip("'-")
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            w = w[: -len(suffix)]
            break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def same_term(a: str, b: str) -> bool:
    """Two stems name the same term when one is a prefix of the other and they
    differ by little ("qualifi" / "qualific"). "person" / "personnel" do not."""
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long.startswith(short) and len(short) / len(long) >= 0.75


def terms(text: str, *, drop: frozenset[str] = frozenset(), keep: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """Content-term stems of `text`, in order, without generic or domain words -
    except those whose stem is in `keep` (the term a definitional question asks about)."""
    out: list[str] = []
    masked = re.sub(r"\d+[a-z]?(?:\.\d+[a-z]?)?(?:\([^)]{1,4}\))*", " ", (text or "").lower())
    for w in _WORD_RE.findall(masked):
        if (w in _GENERIC or w in _DOMAIN_TERMS or w in drop) and stem(w) not in keep:
            continue
        s = stem(w)
        # "register" and "registration" are one term; counting both would make
        # a passage look twice as on-topic as it is
        if len(s) >= 3 and not any(same_term(s, o) for o in out):
            out.append(s)
    return tuple(out)


def matched(wanted, have) -> tuple[str, ...]:
    """Which of `wanted` appear in `have` (both stems)."""
    have = tuple(have)
    return tuple(t for t in wanted if any(same_term(t, h) for h in have))


def subchapter(part: str | int | None) -> str | None:
    try:
        n = int(str(part))
    except (TypeError, ValueError):
        return None
    return next((name for lo, hi, name in _SUBCHAPTERS if lo <= n <= hi), None)


def part_of(citation: str | None) -> str | None:
    """The PART of a CFR citation: 111 in "21 CFR 111.30" and "21 CFR part 111".

    Anchored after "CFR" on purpose. The first number in a citation is the
    TITLE (21), and reading it as the part put every source in subchapter A
    (general provisions), which conflicts with nothing - so no domain check
    could ever fire.
    """
    m = re.search(r"\bCFR\s+(?:part\s+)?(\d{1,4})(?:\.\d+[a-z]?)?\b", citation or "", re.I)
    return m.group(1) if m else None


# ------------------------------------------------------------ intent

DIRECT = "direct_lookup"
SCOPE = "scope"
EXPLANATION = "explanation"
DISTINCTION = "distinction"
CROSS_REFERENCE = "cross_reference"
APPLICATION = "application"
TEMPORAL = "temporal"
NEGATIVE_CONTROL = "negative_control"
LIST = "list"
EXCEPTION = "exception"
OTHER = "other"

_DISTINCTION_RE = re.compile(
    r"\bdifference(?:s)?\s+between\s+(?P<items>.+?)(?:\?|$|\s+under\b)"
    r"|\bhow\s+(?:does|do|is|are)\s+(?P<a>.+?)\s+differ(?:s)?\s+from\s+(?P<b>.+?)(?:\?|$)"
    r"|\bdistinguish(?:es)?\s+(?:between\s+)?(?P<items2>.+?)(?:\?|$)", re.I)
_CROSS_RE = re.compile(r"\brelate[sd]?\s+to\b|\binteract\b|\bincorporat|\bcross-?referenc|\brout(?:e|es|ed|ing)\b"
                       r"|\bin\s+relation\s+to\b|\bhow\s+does\s+.+\s+(?:work|fit)\s+with\b", re.I)
_SCOPE_RE = re.compile(r"\bscope\b|\bwho\s+is\s+subject\b|\bto\s+(?:whom|which\s+\w+)\s+does\s+.+\s+apply\b"
                       r"|\bwhich\s+\w+\s+(?:are|is)\s+(?:subject|covered)\b", re.I)
_APPLICATION_RE = re.compile(r"^\s*(?:a|an|our|my|we|suppose|if)\b.+[.]\s+\S", re.I)
_TEMPORAL_RE = re.compile(r"\b(?:still\s+appl|current(?:ly)?\s+part|superseded|reserved|former|old|previous|"
                          r"quality\s+system\s+regulation|QSR|before\s+20\d\d|after\s+20\d\d|as\s+of\b|"
                          r"effective\s+date|transition)", re.I)
_LIST_RE = re.compile(r"\b(?:list|enumerate|which\s+\w+\s+are|what\s+are\s+the)\b", re.I)
_EXCEPTION_RE = re.compile(r"\bexception|\bexempt|\bexclu|\bunless\b|\bdoes\s+not\s+apply\b", re.I)
# a compound question: a second wh-clause joined by "and"
_COMPOUND_RE = re.compile(r",?\s+and\s+(?=(?:how|what|when|which|who|whom|whether|where|does|do|is|are|must|can)\b)",
                          re.I)


@dataclass(frozen=True)
class Element:
    """One thing the answer must cover."""

    label: str
    terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "terms": list(self.terms)}


@dataclass(frozen=True)
class QuestionIntent:
    question: str
    kind: str
    provisions: tuple[str, ...] = ()                 # canonical labels ("21 CFR 820.10", "21 CFR part 211")
    sections: tuple[str, ...] = ()                   # "820.10"
    parts: tuple[str, ...] = ()                      # "820"
    topic: tuple[str, ...] = ()                      # stems
    domains: frozenset[str] = frozenset()            # subchapter letters
    elements: tuple[Element, ...] = ()
    signals: tuple[str, ...] = ()
    planner_type: str | None = None                  # regulus.planning.intent, recorded only
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def names_section(self) -> bool:
        return bool(self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "provisions": list(self.provisions), "sections": list(self.sections),
                "parts": list(self.parts), "topic": list(self.topic),
                "domains": sorted(self.domains), "domain_names": [SUBCHAPTER_NAMES[d] for d in sorted(self.domains)],
                "elements": [e.to_dict() for e in self.elements], "signals": list(self.signals),
                "planner_type": self.planner_type}


def _distinction_items(question: str) -> list[str]:
    m = _DISTINCTION_RE.search(question)
    if not m:
        return []
    if m.group("a"):
        parts = [m.group("a").strip(), m.group("b").strip()]
    else:
        items = m.group("items") or m.group("items2") or ""
        parts = [p.strip() for p in re.split(r",\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+", items) if p.strip()]
    if len(parts) >= 2:
        # "a process preventive control, a sanitation preventive control, and an
        # allergen preventive control": the shared head noun is not what tells
        # the items apart, the modifier is. The items are returned as WORDS (not
        # stems), so stemming them again downstream is idempotent.
        shared = set.intersection(*(set(terms(p)) for p in parts))
        out = []
        for p in parts:
            kept = [w for w in _WORD_RE.findall(p.lower()) if terms(w) and terms(w)[0] not in shared]
            out.append(" ".join(kept) or p)
        return out
    return parts


_ASKS = re.compile(r"\?\s*$|^\s*(?:can|may|must|do|does|did|is|are|was|were|should|could|would|will|what|which|how|"
                   r"when|where|who|whom|whose|whether|why|list|name|explain|describe)\b", re.I)


def asked_part(question: str) -> str:
    """A scenario question's asked part: from the statement just before its first question to the end.

    "We're a 12-person contract filler formulating a tinted hand cream. Our supplier offers D&C Brown No. 1. Can we
    use it, is there a use limit, and does it need certification?" asks about D&C Brown No. 1: the firm's size and
    role are facts the answer may apply, not things each statement must cover. Read whole, the question made correct
    answers 'only partly address the question' and left 'We're a 12-person contract filler ...' unaddressed: 35 of the
    37 holdout answers the blind scorers passed were shown as FAIL (23 Oct 2026). The statement right before the
    question stays - it is what "it" and "these" refer to, and what "Which provisions could apply?" applies to. A
    question that is one sentence, or that asks from its first sentence, is returned as it is."""
    from regulus.evaluation.grounding_eval import split_sentences

    context, asked = split_scenario(question)
    return f"{context} {asked}".strip() if context else asked


def split_scenario(question: str) -> tuple[str, str]:
    """(context, asked): the statement just before a question's first question sentence, and the sentences from that
    one on. ("", question) for a question that asks from its first sentence or has no question sentence."""
    from regulus.evaluation.grounding_eval import split_sentences

    sentences = [s for s in split_sentences((question or "").strip()) if s.strip()]
    first = next((i for i, s in enumerate(sentences) if _ASKS.search(s)), None)
    if first is None or first == 0:
        return "", question
    return sentences[first - 1], " ".join(sentences[first:])


def analyze(question: str, *, plan=None) -> QuestionIntent:
    """The evaluator's reading of the question. Deterministic; no model."""
    from regulus.planning import plan_query
    from regulus.retrieval.references import parse_cfr_references

    plan = plan if plan is not None else plan_query(question)
    signals: list[str] = []
    provisions = tuple(dict.fromkeys(r.canonical for r in plan.requirements))
    refs = [r.reference for r in plan.requirements] + list(parse_cfr_references(question))
    sections = tuple(dict.fromkeys(r.section for r in refs if r.section))
    parts = tuple(dict.fromkeys(str(r.part) for r in refs if r.part))

    domains: set[str] = set()
    for pattern, letters in _DOMAIN_WORDS:
        if pattern.search(question):
            domains |= set(letters)
            signals.append(f"domain:{''.join(sorted(letters))}")
    for part in parts:           # a named part fixes its own domain
        sc = subchapter(part)
        if sc:
            domains.add(sc)

    context, asked = split_scenario(question)
    if context:
        signals.append("scenario")
    # the topic: what is asked and the statement it rests on; the elements to cover: what is asked
    topic = terms(f"{context} {asked}".strip())
    # A definitional question about one term ("What does FDA stand for?") is
    # ABOUT that term, whatever its vocabulary: "FDA", "Act" or "drug" are
    # generic in any other question but are the whole subject here, and the
    # frame ("stand for", "mean") is not. The same reading retrieval uses.
    from regulus.retrieval.query import definition_term

    defined = definition_term(question) if not plan.requirements else None
    if defined is not None:
        topic = tuple(dict.fromkeys(stem(w) for w in re.findall(r"[a-z][a-z'-]+", defined.lower())))
        signals.append("definition_term")
    planner_type = None
    try:
        from regulus.planning.intent import analyze_question

        planner_type = analyze_question(plan).question_type
    except Exception:
        pass

    # ---- kind, most specific first. Temporal outranks the rest: a question
    # framed on a superseded regulation is a temporal question whatever its
    # surface form ("what is the difference between a DMR and a DHF under the
    # current Part 820" is a distinction built on a false premise).
    items = _distinction_items(question)
    if _TEMPORAL_RE.search(question):
        kind = TEMPORAL
    elif items:
        kind = DISTINCTION
    elif _APPLICATION_RE.search(question):
        kind = APPLICATION
    elif _CROSS_RE.search(question) or len(set(parts)) >= 2:
        kind = CROSS_REFERENCE
    elif _SCOPE_RE.search(question):
        kind = SCOPE
    elif _EXCEPTION_RE.search(question):
        kind = EXCEPTION
    elif re.search(r"\b(?:why|explain|walk\s+me\s+through|how\s+(?:does|do|is|are|must|should))\b", question, re.I):
        kind = EXPLANATION
    elif _LIST_RE.search(question):
        kind = LIST
    else:
        kind = DIRECT
    signals.append(f"kind:{kind}")

    # ---- elements
    elements: list[Element] = []
    if items:
        elements = [Element(item.strip(), terms(item)) for item in items if terms(item)]
    else:
        clauses = [c for c in _COMPOUND_RE.split(asked) if c.strip()]
        if len(clauses) >= 2:
            elements = [Element(c.strip(" ?,"), terms(c)) for c in clauses if terms(c)]
        if re.search(r"\brequirements?\s+and\s+(?:the\s+)?(?:exceptions?|exemptions?)\b", question, re.I):
            elements.append(Element("exceptions", ("except", "exempt")))
    if defined is not None:
        elements = [Element(f"the term {defined}", topic)] if topic else []
    elif len(elements) < 2:
        elements = [Element("the question's subject", topic)] if topic else []
    return QuestionIntent(question=question, kind=kind, provisions=provisions, sections=sections, parts=parts,
                          topic=topic, domains=frozenset(domains), elements=tuple(elements),
                          signals=tuple(signals), planner_type=planner_type)


def topic_coverage(wanted: tuple[str, ...], text: str) -> tuple[tuple[str, ...], float]:
    """Which wanted stems a text carries, and what share of them."""
    have = terms(text)
    hit = matched(wanted, have)
    return hit, (len(hit) / len(wanted)) if wanted else 0.0


def required_hits(n: int) -> int:
    """How many of n topic terms make a passage ABOUT the topic: half, rounded up."""
    return max(1, math.ceil(n / 2))
