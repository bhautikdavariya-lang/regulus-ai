"""AnswerShape: what kind of answer a question asks for (Stage 12).

The QueryPlan says *which* provisions a question names. The AnswerShape says
*how* the answer should be organised: a synthesized overview, a focused
answer about one provision, an enumeration of every item, a comparison, or a
direct statement of what something is. It is derived from the plan, never
from the evidence, and it is deterministic: regular expressions over the
question with the CFR identifiers masked out, combined with the plan's
structure (how many provisions, at what level, whether a range was
expanded). No model is called.

Wording is never read alone. "What does ... require" is a synthesis cue for
one section but not for four named paragraphs; "all" counts only when it is
bound to a requirement noun ("all requirements", "every subsection"), so
"Does 820.10 apply to all manufacturers?" is not an enumeration request.

Modes
    synthesis    a coherent overview; related evidence combined, subordinate
                 requirements grouped under their parent
    focused      the requested provision (or topic inside one) and nothing else
    enumeration  every requested item, each kept distinct
    comparison   the requested sides, organised around their differences
    direct       a direct statement of what something is

Scopes
    part | section | subsection | multiple | topic | document
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from regulus.planning.plan import KIND_RANGE, KIND_UNKNOWN, QueryPlan

MODE_SYNTHESIS = "synthesis"
MODE_FOCUSED = "focused"
MODE_ENUMERATION = "enumeration"
MODE_COMPARISON = "comparison"
MODE_DIRECT = "direct"
MODES = (MODE_SYNTHESIS, MODE_FOCUSED, MODE_ENUMERATION, MODE_COMPARISON, MODE_DIRECT)

SCOPE_PART = "part"
SCOPE_SECTION = "section"
SCOPE_SUBSECTION = "subsection"
SCOPE_MULTIPLE = "multiple"
SCOPE_TOPIC = "topic"
SCOPE_DOCUMENT = "document"
SCOPES = (SCOPE_PART, SCOPE_SECTION, SCOPE_SUBSECTION, SCOPE_MULTIPLE, SCOPE_TOPIC, SCOPE_DOCUMENT)

# signals (recorded on the shape so a classification can always be explained)
SIG_COMPARISON = "comparison_wording"
SIG_LIST_VERB = "list_verb"
SIG_QUANTIFIER = "quantifier_on_requirements"
SIG_DETAIL = "exhaustive_wording"
SIG_OVERVIEW = "overview_wording"
SIG_DEFINITION = "definition_wording"
SIG_MULTIPLE = "several_named_provisions"
SIG_RANGE = "expanded_range"
SIG_PARAGRAPH = "paragraph_level_reference"
SIG_TOPIC_FOCUS = "topic_inside_provision"
SIG_DOCKET = "guidance_document"
SIG_COMPARISON_ONE_SIDE = "comparison_wording_single_target"

_REQUIREMENT_NOUN = (
    r"(?:requirements?|provisions?|subsections?|sub-sections?|paragraphs?|obligations?|conditions?|elements?|"
    r"items?|clauses?|rules?|duties|components?|parts?|sections?|points?)"
)
_COMPARISON_RE = re.compile(
    r"\b(compare[sd]?|comparing|comparison|contrast(?:s|ed|ing)?|differ(?:s|ence|ences)?|distinguish(?:es)?|"
    r"versus|vs\.?|similarit(?:y|ies)|how\s+(?:is|are|does|do)\s+\S+(?:\s+\S+){0,6}\s+(?:related|different)\s+(?:to|from))\b",
    re.IGNORECASE,
)
_LIST_RE = re.compile(
    r"\b(list|lists|listing|enumerate|enumerating|itemi[sz]e|tabulate|break\s+(?:it\s+|them\s+)?down|breakdown|"
    r"walk\s+(?:me\s+)?through\s+(?:each|every|all)|go\s+through\s+(?:each|every|all))\b",
    re.IGNORECASE,
)
# LV1: "list" that asks for an enumeration - an instruction ("List the ...", "can you list"), or followed by what to
# enumerate ("list all", "list each requirement", "list the conditions")
_ENUMERATING_LIST_RE = re.compile(
    rf"(?:^|[.?!]\s+|\b(?:please|you|can|could|would|just)\s+)list\b|\blist(?:s|ing)?\s+(?:out\s+)?(?:(?:all|each|every|the|"
    rf"its|their|any|which|what)\s+)+(?:\w+\s+){{0,2}}{_REQUIREMENT_NOUN}\b|\blist(?:s|ing)?\s+(?:out\s+)?(?:all|each|every)\b",
    re.IGNORECASE)


def _lv1() -> bool:
    from regulus.rag.validator_switches import enabled

    return enabled("LV1")


_QUANTIFIER_RE = re.compile(
    rf"\b(all|every|each)\b(?:\s+(?:of\s+)?(?:the|its|their|these|those|this|that|applicable|individual|specific|separate|listed|"
    rf"regulatory|listed)){{0,3}}\s+{_REQUIREMENT_NOUN}\b|\b(?:all|each|every\s+one)\s+of\s+(?:them|these|those|its|the)\b",
    re.IGNORECASE,
)
_DETAIL_RE = re.compile(
    r"\b(in\s+full|exhaustive(?:ly)?|one\s+by\s+one|item\s+by\s+item|(?:sub)?section[- ]by[- ](?:sub)?section|"
    r"paragraph[- ]by[- ]paragraph|(?:complete|full|entire)\s+(?:list|breakdown|set|enumeration)|in\s+detail|"
    r"every\s+single|without\s+omitting)\b",
    re.IGNORECASE,
)
_OVERVIEW_RE = re.compile(
    r"\b(summari[sz]e[sd]?|summary|overview|in\s+brief|briefly|brief|generally|in\s+general|high[- ]level|"
    r"main\s+points?|gist|in\s+short|at\s+a\s+glance)\b",
    re.IGNORECASE,
)
_DEFINITION_RE = re.compile(
    r"^\s*(?:what\s+is|what's|what\s+are|define|definition\s+of|meaning\s+of|what\s+is\s+meant\s+by)\b"
    r"|\bwhat\s+does\s+.{1,60}\s+mean\b|\bwhat\s+is\s+meant\s+by\b",
    re.IGNORECASE,
)
# "What are the requirements ..." starts like a definition question but is not one
_REQUIREMENTS_QUESTION_RE = re.compile(rf"^\s*what\s+are\s+(?:the\s+)?(?:\w+\s+)?{_REQUIREMENT_NOUN}\b", re.IGNORECASE)

# Words that never make a question topical: interrogatives, function words,
# regulatory boilerplate (all from the retrieval query analyser), shape cues,
# and generic subjects that every provision shares.
_SHAPE_WORDS = {
    "list", "lists", "listing", "enumerate", "itemize", "itemise", "compare", "compared", "comparing", "comparison",
    "contrast", "differ", "differs", "different", "difference", "differences", "versus", "vs", "summarize",
    "summarise", "summary", "overview", "brief", "briefly", "detail", "detailed", "full", "complete", "entire",
    "exhaustive", "exhaustively", "each", "every", "all", "breakdown", "use", "used", "uses", "apply", "applies", "break", "down", "walk", "through", "go",
    "outline", "describe", "explain", "discuss", "tell", "show", "give", "provide", "state", "set", "sets", "lay",
    "lays", "impose", "imposes", "contain", "contains", "include", "includes", "entail", "entails", "involve",
    "involves", "cover", "covers", "say", "says", "said", "require", "requires", "required", "requirement",
    "requirements", "provision", "provisions", "subsection", "subsections", "paragraph", "paragraphs", "obligation",
    "obligations", "item", "items", "element", "elements", "point", "points", "rule", "rules", "section", "sections",
    "part", "parts", "manufacturer", "manufacturers", "device", "devices", "medical", "company", "companies", "firm",
    "firms", "establishment", "establishments", "under", "per", "pursuant", "mean", "means", "meant", "definition",
    "define", "similarity", "similarities", "distinguish", "related", "relate", "relates", "high", "level", "gist",
    "short", "main", "key", "important", "ecfr", "c.f.r", "cfr", "21", "title", "regulation", "regulations",
    # Stage 8: question verbs of "what does X ...?" name no topic ("What does 21 CFR 830.20 address?" had focus "address")
    "address", "addresses", "addressed", "concern", "concerns", "govern", "governs", "regulate", "regulates",
    "establish", "establishes", "specify", "specifies", "prescribe", "prescribes", "mandate", "mandates",
    "stipulate", "stipulates", "deal", "deals", "talk", "talks", "about", "cover", "covered",
}
_WORD_RE = re.compile(r"[a-z][a-z'-]{2,}")


@dataclass(frozen=True)
class AnswerShape:
    mode: str
    scope: str
    exhaustive: bool
    requested_units: tuple[str, ...] = ()   # canonical labels, in question order
    focus_terms: tuple[str, ...] = ()        # topical restriction inside a named provision
    signals: tuple[str, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown answer mode {self.mode!r}")
        if self.scope not in SCOPES:
            raise ValueError(f"unknown answer scope {self.scope!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scope": self.scope,
            "exhaustive": self.exhaustive,
            "requested_units": list(self.requested_units),
            "focus_terms": list(self.focus_terms),
            "signals": list(self.signals),
            "rationale": self.rationale,
        }


def _masked(plan: QueryPlan) -> str:
    """The question with every CFR mention blanked, so identifiers are never read as wording."""
    text = plan.scan.text or plan.normalized_question or plan.question or ""
    for m in sorted(plan.scan.mentions, key=lambda m: m.start, reverse=True):
        text = text[: m.start] + " " + text[m.end:]
    return re.sub(r"\s+", " ", text).strip()


def _topic_terms(masked: str) -> tuple[str, ...]:
    from regulus.retrieval.query import _STOP_TERMS  # the retrieval analyser's own stop list

    out: list[str] = []
    for w in _WORD_RE.findall(masked.lower()):
        w = w.strip("'-")
        if len(w) < 3 or w in _STOP_TERMS or w in _SHAPE_WORDS or w in out:
            continue
        out.append(w)
    return tuple(out)


def _level_scope(level: str) -> str:
    return {"part": SCOPE_PART, "section": SCOPE_SECTION}.get(level, SCOPE_SUBSECTION)


def analyze_shape(plan: QueryPlan) -> AnswerShape:
    """The answer shape for a plan. Deterministic; no database, no model."""
    masked = _masked(plan)
    signals: list[str] = []
    comparison = bool(_COMPARISON_RE.search(masked))
    list_verb = bool(_LIST_RE.search(masked))
    if list_verb and _lv1() and not _ENUMERATING_LIST_RE.search(masked) and not any(
            m.group(1).lower() not in ("list", "lists", "listing") for m in _LIST_RE.finditer(masked)):
        # LV1: "petitioning to list a new colorant", "amend a listing" - in Parts 70-82 to list is to approve a color
        # additive; it asks for no enumeration unless it is an instruction or names what to enumerate
        list_verb = False
    quantifier = bool(_QUANTIFIER_RE.search(masked))
    detail = bool(_DETAIL_RE.search(masked))
    overview = bool(_OVERVIEW_RE.search(masked))
    definition = bool(_DEFINITION_RE.search(masked)) and not _REQUIREMENTS_QUESTION_RE.search(masked)
    for flag, name in ((comparison, SIG_COMPARISON), (list_verb, SIG_LIST_VERB), (quantifier, SIG_QUANTIFIER),
                       (detail, SIG_DETAIL), (overview, SIG_OVERVIEW), (definition, SIG_DEFINITION)):
        if flag:
            signals.append(name)
    # "an overview of all requirements" asks for coverage, not a list; an explicit
    # list verb or exhaustive wording outranks the overview word
    exhaustive_request = list_verb or detail or (quantifier and not overview)

    reqs = plan.requirements
    units = tuple(r.canonical for r in reqs)

    def shape(mode: str, scope: str, exhaustive: bool, why: str, focus: tuple[str, ...] = ()) -> AnswerShape:
        return AnswerShape(mode, scope, exhaustive, units, focus, tuple(signals), why)

    if plan.kind == KIND_UNKNOWN:
        return shape(MODE_SYNTHESIS, SCOPE_TOPIC, False, "empty question")

    if len(reqs) >= 2:
        signals.append(SIG_MULTIPLE)
        if plan.kind == KIND_RANGE:
            signals.append(SIG_RANGE)
        if comparison:
            return shape(MODE_COMPARISON, SCOPE_MULTIPLE, False, f"comparison wording over {len(reqs)} named provisions")
        return shape(MODE_ENUMERATION, SCOPE_MULTIPLE, True,
                     f"{len(reqs)} named provisions{' (an expanded range)' if plan.kind == KIND_RANGE else ''}: each one is requested")

    if len(reqs) == 1:
        req = reqs[0]
        scope = _level_scope(req.level)
        if comparison:
            # one side named, the other implicit ("how does (c) differ from the rest?"): answer the named one
            signals.append(SIG_COMPARISON_ONE_SIDE)
        if exhaustive_request:
            return shape(MODE_ENUMERATION, scope, True, f"explicit request for every item of {req.canonical}")
        if req.level == "paragraph":
            signals.append(SIG_PARAGRAPH)
            return shape(MODE_FOCUSED, scope, False, f"a single paragraph-level provision ({req.canonical})")
        focus = _topic_terms(masked)
        if focus:
            signals.append(SIG_TOPIC_FOCUS)
            return shape(MODE_FOCUSED, scope, False, f"{req.canonical}, restricted to: {', '.join(focus)}", focus)
        if req.level == "part" and definition:
            return shape(MODE_DIRECT, scope, False, f"what {req.canonical} is")
        return shape(MODE_SYNTHESIS, scope, False, f"an overview of {req.canonical}")

    # no CFR provision named
    scope = SCOPE_DOCUMENT if (plan.docket or plan.guidance_requested) else SCOPE_TOPIC
    if scope == SCOPE_DOCUMENT:
        signals.append(SIG_DOCKET)
    if comparison:
        return shape(MODE_COMPARISON, scope, False, "comparison wording")
    if exhaustive_request:
        return shape(MODE_ENUMERATION, scope, True, "explicit request for every item")
    if definition and len(_topic_terms(masked)) <= 4:
        return shape(MODE_DIRECT, scope, False, "a definition or direct-fact question")
    return shape(MODE_SYNTHESIS, scope, False, "a general question: synthesize the relevant material")
