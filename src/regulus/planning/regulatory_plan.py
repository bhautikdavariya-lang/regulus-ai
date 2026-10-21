"""Stage A of the experimental advanced retrieval (2026-10-21): a deterministic, regulatory-aware question plan.

No model call. The plan says what the question asks and what a source must contain to address each part; it guides
retrieval and evidence coverage and is never a source of legal conclusions.

    references     every CFR reference, with the title an explicitly named agency gives it ("FAA Part 107" -> 14)
    agencies       agencies the question names; non_fda when it is about another agency's rules
    subparts       (part, subpart) the question names
    question_type  regulus.planning.intent (definition, requirement, procedure, applicability, exception, ...)
    elements       what must be addressed: each question clause ("ask"), each side of a comparison, each specific
                   thing named (Title-Cased term, hyphenated compound, standard identifier, quoted phrase). Every
                   element carries match keys: its own content words, plus subject words from the question's
                   statements for an ask that has none of its own ("how must the petition be submitted").
    quantities     numbers with units ("500 mg/kg", "30 days"); dates and years
    temporal       "historical" when the question asks about former requirements; the corpus is one snapshot
    alternatives   readings the question leaves open (a bare part number next to another agency's name elsewhere)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from regulus.retrieval.query import content_terms, definitional_terms
from regulus.retrieval.references import agencies_named, resolved_titles

KEY_PREFIX = 6                  # a key matches any word that starts with it ("submitted" ~ "submission")
MAX_ELEMENTS = 5
SUBJECT_KEYS = 4                # subject words a statement contributes to each ask
_NOT_KEYS = {"ourselves", "yourself", "yourselves", "themselves", "someone", "anyone", "something", "anything",
             "thing", "things", "way", "ways", "lot", "use", "uses", "used", "using", "set", "get", "make", "made",
             "new", "small", "line", "want", "define", "defined", "defines", "definition", "definitions", "sets",
             "apply", "applies", "applied"}
_ASK_SPLIT_RE = re.compile(r",?\s+and\s+(?=(?:what|which|how|when|who|whom|whether|where|why|can|must|may|does|do|is|are)\b)"
                           r"|;\s*(?=(?:what|which|how|when|who|can|must|may|does|is)\b)", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.?!])\s+(?=[A-Z])")
_QUESTION_START_RE = re.compile(r"^(?:what|which|how|when|who|whom|whether|where|why|can|could|must|may|does|do|did|is|are|"
                                r"will|would|should|shall|explain|describe|compare|list|summari[sz]e|cite|walk)\b", re.I)
_COMPARISON_RE = re.compile(r"\b(?:difference|differences|distinguish|compare|comparison)\s+(?:between|among)?\s*(?P<sides>.+?)(?:\?|$)", re.I)
_QUANTITY_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mg/kg|µg|ug|mg|kg|g|ppm|ppb|percent|%|days?|hours?|weeks?|months?|years?|"
                          r"calendar days?|business days?|°\s*[CF])(?![A-Za-z])", re.I)
_DATE_RE = re.compile(r"\b(?:(?:19|20)\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|"
                      r"December)\s+\d{1,2}(?:,\s*(?:19|20)\d{2})?)\b")
_HISTORICAL_RE = re.compile(r"\b(?:previous(?:ly)?|former(?:ly)?|used to|prior to|before (?:19|20)\d{2}|historic(?:al)?|"
                            r"superseded|old (?:rule|regulation|requirement)s?|quality system regulation|QSR)\b", re.I)
_SUBPART_RE = re.compile(r"\bpart\s+(\d{1,4})\s*,?\s+subpart\s+([A-Z]{1,2})\b", re.I)
_NAMED_RE = (re.compile(r"(?<![A-Za-z])[\"'‘“]([^\"'’”]{3,60})[\"'’”](?![A-Za-z])"),
             re.compile(r"\b(?:ISO|IEC|ASTM|ANSI|AAMI)\s*\d{3,6}(?:-\d+)?\b"),
             re.compile(r"(?<!^)(?<![.?!]\s)\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}))+\b"),
             re.compile(r"\b[a-z]+-[a-z]+\b"))


def keys_of(text: str) -> tuple[str, ...]:
    """Prefix keys of the content words of `text` (hyphenated words split; numbers and section numbers dropped)."""
    out: list[str] = []
    for term in content_terms(text or ""):
        for part in term.strip('"').split("-"):
            part = part.strip(".()'").lower()
            if len(part) < 3 or part.replace(".", "").isdigit() or part in _NOT_KEYS:
                continue
            key = part[:KEY_PREFIX]
            if key not in out:
                out.append(key)
    return tuple(out)


def keys_present(keys: tuple[str, ...], text: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return tuple(k for k in keys if any(w.startswith(k) for w in words))


@dataclass(frozen=True)
class PlanElement:
    id: str
    kind: str                       # ask | comparison_side | named_thing
    text: str
    keys: tuple[str, ...]           # the element's own keys
    subject_keys: tuple[str, ...] = ()  # subject keys carried from the question's statements

    def covered_by(self, text: str, context: str = "") -> bool:
        """Whether a passage (its text, and its heading/part title as context) addresses this element: at least half
        of the element's own keys, two when it has two or more, and - when subject keys were carried - one of them."""
        if not self.keys:
            return False
        if self.kind == "named_thing":
            words = re.findall(r"[a-z0-9]+", self.text.lower())
            pattern = r"\b" + r"[\s\-]+".join(re.escape(w) for w in words) + r"\b"
            return bool(re.search(pattern, f"{text} {context}".lower()))
        need = min(len(self.keys), max(2, -(-len(self.keys) // 2)))
        own = keys_present(self.keys, text)
        if len(own) < need:
            return False
        return not self.subject_keys or bool(keys_present(self.subject_keys, f"{text} {context}"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegulatoryPlan:
    question: str
    references: tuple[str, ...] = ()
    agencies: tuple[str, ...] = ()
    non_fda: bool = False
    subparts: tuple[tuple[str, str], ...] = ()
    question_type: str | None = None
    is_yes_no: bool = False
    elements: tuple[PlanElement, ...] = ()
    defined_terms: tuple[str, ...] = ()
    quantities: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    temporal: str = "current"
    alternatives: tuple[str, ...] = ()

    @property
    def names_provision(self) -> bool:
        return bool(self.references)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["elements"] = [e.to_dict() for e in self.elements]
        return d


def _asks_and_statements(question: str) -> tuple[list[str], list[str]]:
    asks, statements = [], []
    for sentence in _SENTENCE_RE.split((question or "").strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        if sentence.endswith("?") or _QUESTION_START_RE.match(sentence):
            for part in _ASK_SPLIT_RE.split(sentence):
                part = re.sub(r"^(?:and|or)\s+", "", part.strip(" ?,;."), flags=re.I)
                if part:
                    asks.append(part)
        else:
            statements.append(sentence)
    return asks, statements


def _named_things(question: str) -> list[str]:
    found: list[str] = []
    for i, pattern in enumerate(_NAMED_RE):
        for m in pattern.finditer(question):
            text = (m.group(1) if i == 0 else m.group(0)).strip()
            low = text.lower()
            if (text and low not in ("fda", "cfr") and not re.search(r"\b(?:part|subpart|section|cfr)\b", low)
                    and not any(low in f.lower() for f in found)):
                found.append(text)
    return found


def build_regulatory_plan(question: str) -> RegulatoryPlan:
    from regulus.planning import plan_query
    from regulus.planning.intent import analyze_question

    question = (question or "").strip()
    refs = resolved_titles(question)
    references = tuple(dict.fromkeys(f"{title} CFR {ref.canonical.split(' CFR ', 1)[-1]}" for ref, title in refs))
    agencies = agencies_named(question)
    non_fda = any(title != "21" for _, title in refs) or (not refs and bool(agencies)
                                                          and all(t != "21" for _, t in agencies))
    alternatives = []
    if any(title == "21" for _, title in refs) and any(t != "21" for _, t in agencies):
        alternatives.append("a reference without a title in a question that also names another agency")
    analysis = analyze_question(plan_query(question))
    asks, statements = _asks_and_statements(question)
    subject = tuple(k for s in statements for k in keys_of(s))[:SUBJECT_KEYS * 2]
    elements: list[PlanElement] = []
    for n, ask in enumerate(asks or [question], start=1):
        own = keys_of(ask)
        carried = tuple(k for k in subject if k not in own)[:SUBJECT_KEYS] if (statements and len(own) < 4) else ()
        elements.append(PlanElement(f"ask{n}", "ask", ask, own, carried))
    m = _COMPARISON_RE.search(question)
    if m:
        for n, side in enumerate(re.split(r",\s*(?:and\s+)?|\s+and\s+|\s+vs\.?\s+|\s+versus\s+", m.group("sides")), start=1):
            side = re.sub(r"^(?:a|an|the)\s+", "", side.strip(" ?.,"), flags=re.I)
            if keys_of(side):
                elements.append(PlanElement(f"side{n}", "comparison_side", side, keys_of(side)))
    for n, thing in enumerate(_named_things(question), start=1):
        if keys_of(thing):
            elements.append(PlanElement(f"named{n}", "named_thing", thing, keys_of(thing)))
    return RegulatoryPlan(
        question=question, references=references, agencies=tuple(a for a, _ in agencies), non_fda=non_fda,
        subparts=tuple((p, s.upper()) for p, s in _SUBPART_RE.findall(question)),
        question_type=analysis.question_type, is_yes_no=analysis.is_yes_no, elements=tuple(elements[:MAX_ELEMENTS]),
        defined_terms=tuple(sorted(t for t, w in definitional_terms(question).items() if w >= 3)), quantities=tuple(m.group(0) for m in _QUANTITY_RE.finditer(question)),
        dates=tuple(m.group(0) for m in _DATE_RE.finditer(question)),
        temporal="historical" if _HISTORICAL_RE.search(question) else "current", alternatives=tuple(alternatives))
