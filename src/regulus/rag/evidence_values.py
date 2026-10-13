"""Requested kinds of value: what a question asks for, and whether evidence contains one.

A question can ask for a *kind of value* (a temperature, a date, a time period
or frequency, an amount of money, a percentage, a form number, a count) rather
than for an explanation. If no supplied source contains any value of that
kind, the evidence cannot establish the answer, whatever the topic.

The test is about kinds, never about topics or particular numbers. It fires
only when the question ASKS for the value ("what temperature range", "how
often", "which FDA form number"); a question that merely mentions the word
("time/temperature control", "in what form must a UDI appear") is not asking
for a value. Measured against the 300 benchmark questions before adoption;
see docs/answerability_gate_stage5.md.

Limitations: it cannot tell whether a source that contains *some* value of the
kind contains *the* value asked for; it covers the kinds listed and nothing
else (no general numeric limits, no named-requirement detection).
"""

from __future__ import annotations

import re

_NUM_WORDS = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|sixty|ninety)"

# (kind, question asks for it, evidence contains one, how to name it to a reader)
VALUE_KINDS: tuple[tuple[str, re.Pattern[str], re.Pattern[str], str], ...] = (
    ("temperature",
     re.compile(r"\b(?:what|which)\s+(?:exact\s+|specific\s+|maximum\s+|minimum\s+)?(?:storage\s+|holding\s+)?temperatures?"
                r"(?:\s+(?:range|limits?))?\b(?!\s+(?:control|controls|monitoring|requirements?))"
                r"|\bat\s+what\s+temperature\b|\bhow\s+(?:hot|cold|warm)\b", re.I),
     re.compile(r"-?\d+(?:\.\d+)?\s*°\s*[CF]?|\b\d+(?:\.\d+)?\s*degrees?\b", re.I),
     "specific temperature or temperature range"),
    # A regulatory "deadline" is normally a PERIOD ("no later than 7 calendar days after the
    # sponsor's initial receipt of the information"), not a calendar date, so either kind of value
    # establishes it. Before this entry existed, "deadline" fell to the "date" kind below, whose
    # evidence pattern matches only calendar dates: asked for the reporting deadline of 21 CFR
    # 312.32(c)(2), the gate withheld a correct answer although (c)(2) was in front of the model.
    # It stays ahead of "date" and narrower than it: "by what date", "compliance date" and
    # "effective date" are still calendar dates and are unaffected.
    ("deadline",
     re.compile(r"\bdeadlines?\b", re.I),
     re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b"
                r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:19|20)\d{2}\b"
                r"|\b(?:\d+|" + _NUM_WORDS + r")[\s-]+(?:calendar\s+|working\s+|business\s+)?(?:days?|weeks?|months?|years?|hours?)\b", re.I),
     "date or time period"),
    ("date",
     re.compile(r"\b(?:by|on)\s+what\s+date\b|\b(?:what|which)\s+date\b|\bcompliance\s+date\b|\beffective\s+date\b"
                r"|\bwhen\s+did\b", re.I),
     re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b"
                r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:19|20)\d{2}\b", re.I),
     "date"),
    ("duration_or_frequency",
     re.compile(r"\bhow\s+(?:long|often|soon|frequently)\b|\bwithin\s+how\s+many\b|\bhow\s+many\s+(?:days|weeks|months|years|hours)\b"
                r"|\bevery\s+(?:\d+|" + _NUM_WORDS + r")\s+(?:days|weeks|months|years)\b", re.I),
     re.compile(r"\b(?:\d+|" + _NUM_WORDS + r")[\s-]+(?:calendar\s+|working\s+|business\s+)?(?:days?|weeks?|months?|years?|hours?)\b"
                r"|\b(?:annually|monthly|weekly|daily|quarterly|yearly|biennially)\b", re.I),
     "time period or frequency"),
    ("money",
     re.compile(r"\b(?:penalty|fine|fee|user\s+fee|dollar)\s+amounts?\b|\bhow\s+much\s+(?:is|are|does|will|must)\b.{0,40}\b(?:fee|fine|penalty|cost)"
                r"|\$", re.I),
     re.compile(r"\$\s?\d|\b\d[\d,]*\s*dollars\b", re.I),
     "amount"),
    ("percentage",
     re.compile(r"\bwhat\s+percent(?:age)?\b|\bhow\s+many\s+percent\b", re.I),
     re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent)\b", re.I),
     "percentage"),
    ("form_number",
     re.compile(r"\bform\s+(?:number|no\.?)\b|\b(?:which|what)\s+FDA\s+form\b|\bForm\s+FDA\b", re.I),
     re.compile(r"\bForm\s+(?:FDA\s+)?\d{3,5}[A-Z]?\b|\bFDA\s+Form\s+\d", re.I),
     "form number"),
    ("count",
     re.compile(r"\bhow\s+many\b(?!\s+(?:days|weeks|months|years|hours|percent))", re.I),
     re.compile(r"\b\d+\b|\b" + _NUM_WORDS + r"\b", re.I),
     "number"),
)
_CLAUSES = re.compile(r"\?|;|,\s*and\s+|\s+and\s+(?=(?:what|who|when|where|how|which|why|is|are|does|do|must)\b)|\s+[—–-]\s+", re.I)


def requested_value_kind(question: str) -> str | None:
    """The kind of value the question asks for, or None."""
    for kind, asks, _, _ in VALUE_KINDS:
        if asks.search(question or ""):
            return kind
    return None


# Wordings that ask WITHIN WHAT TIME something must happen without using any of the words above.
# They are deliberately NOT in VALUE_KINDS: that tuple drives the answerability gate, which
# WITHHOLDS an answer when the evidence holds no value of the kind asked for, and widening what
# the gate withholds on is a different and riskier change than widening what selection prefers.
_PERIOD_SYNONYMS = re.compile(r"\btime[\s-]*frames?\b|\btime[\s-]+limits?\b|\btime[\s-]+periods?\b"
                              r"|\btimelines?\b|\bhow\s+(?:quickly|rapidly|promptly)\b", re.I)


def selection_value_kind(question: str) -> str | None:
    """The kind of value a question asks for, for RANKING evidence rather than gating it.

    The same kinds the answerability gate uses, plus the period wordings it does not act on:
    "timeframes", "time limits", "time periods", "timeline", "how quickly". Asked for the IND
    safety reporting *timeframes* of 21 CFR 312.32, selection scored (c)(2) - the 7-calendar-day
    rule - on one shared word and the (c)(1) family on three, so the paragraph that answered the
    question lost the hard ceiling to paragraphs that did not.

    Ranking can only reorder a competition that the ceilings already force, so a wrong answer
    here costs a less relevant paragraph; a wrong answer in the gate costs a withheld answer.
    """
    kind = requested_value_kind(question)
    if kind is None and _PERIOD_SYNONYMS.search(question or ""):
        return "duration_or_frequency"
    return kind


def value_request_is_whole_question(question: str, kind: str) -> bool:
    """False when the value is asked in one clause of a multi-part question
    ("How long must records be retained and how must they be made available?"),
    so the other parts may still be answerable."""
    asks = next(a for k, a, _, _ in VALUE_KINDS if k == kind)
    clauses = [c.strip() for c in _CLAUSES.split(question or "") if c and len(c.split()) >= 3]
    other = [c for c in clauses if not asks.search(c)]
    # a trailing premise check ("— is it quarterly?", "every six months?") is part of the same request
    substantive = [c for c in other if len(c.split()) >= 4 and not re.match(r"^\s*(?:is|are)\s+it\b", c, re.I)]
    return not substantive


def evidence_has_value(kind: str, texts: list[str]) -> bool:
    pattern = next(v for k, _, v, _ in VALUE_KINDS if k == kind)
    return any(pattern.search(t or "") for t in texts)


def value_kind_label(kind: str) -> str:
    return next(label for k, _, _, label in VALUE_KINDS if k == kind)


def with_article(label: str) -> str:
    return ("an " if label[:1].lower() in "aeiou" else "a ") + label
