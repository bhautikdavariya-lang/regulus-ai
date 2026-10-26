"""A yes/no question that asserts a figure the provision does not state (fix FP1, 26 Oct 2026).

"Our consultant says advisory committee members are paid $150 per member per day under 70.19. Correct?", "Does
70.25(a)(4) require a 24-month expiry date?", "If we don't answer within 30 days the petition is denied, correct?" - 113
of the question bank's 277 false-premise follow-ups assert a figure, and in most of them the provision states no such
figure (70.19(l) says "$75.00"; 70.25(a)(4) "if stability data require it"; 71.4 "180 days"). Qwen3-4B accepted such
premises (701.11-Q1-F4: "at least 1/4 inch tall" answered as a requirement).

The check is mechanical: every figure the question asserts (an amount with its unit - money, a period, a percentage, a
concentration, a length, a weight) is looked for, by value and unit, in ALL the text supplied for the identified
provision(s). Only when one is absent is the answer composed: "No. <figure> does not appear in the text of <provision>",
then the provision's paragraphs that state figures of the same kind (or, failing that, share most subject words with the
question), verbatim and cited. When every asserted figure is present - "$3,000 for a cosmetics-only petition", a real
figure misapplied - nothing is composed: the model answers. Switched by "FP1" in regulus.rag.validator_switches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
                 "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45,
                 "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "one hundred": 100,
                 "one hundred eighty": 180, "one hundred and eighty": 180}
_FRACTION_WORDS = {"one-half": 0.5, "one half": 0.5, "one-quarter": 0.25, "one-fourth": 0.25, "one fourth": 0.25,
                   "one-eighth": 0.125, "one-sixteenth": 0.0625, "three-fourths": 0.75, "one-third": 1 / 3}
# unit words -> unit kind
_UNITS = [
    (r"(?:calendar\s+|business\s+|working\s+)?days?", "day"), (r"hours?|hrs?", "hour"), (r"weeks?", "week"),
    (r"months?", "month"), (r"years?|yrs?", "year"), (r"minutes?", "minute"),
    (r"percent|per\s*cent|%", "percent"), (r"ppm|parts\s+per\s+million", "ppm"), (r"ppb|parts\s+per\s+billion", "ppb"),
    (r"inch(?:es)?|in\.", "inch"), (r"mm|millimet(?:er|re)s?", "mm"), (r"cm|centimet(?:er|re)s?", "cm"),
    (r"mg/kg", "mg/kg"), (r"mg|milligrams?", "mg"), (r"g|grams?", "g"), (r"kg|kilograms?", "kg"),
    (r"pounds?|lbs?", "pound"), (r"ounces?|oz", "ounce"), (r"fl\.?\s*oz", "floz"), (r"ml|milliliters?", "ml"),
    (r"°\s*[CF]|degrees?", "degree"),
]
_UNIT_RE = "|".join(f"(?:{u})" for u, _ in _UNITS)
_NUM = r"\d+(?:,\d{3})*(?:\.\d+)?(?:/\d+)?"
_WORDNUM = "|".join(sorted((re.escape(w) for w in list(_WORD_NUMBERS) + list(_FRACTION_WORDS)), key=len, reverse=True))
_MONEY = re.compile(r"\$\s?(" + _NUM + r")")
_AMOUNT = re.compile(r"(?<![\w.§])(" + _NUM + r"|" + _WORDNUM + r")(?:\s|-)?(?:of\s+an?\s+)?(" + _UNIT_RE + r")(?![a-z])", re.I)
# a question that puts a claim up for confirmation: yes/no form or a tag
_YES_NO = re.compile(r"^\s*(?:is|are|does|do|did|can|could|must|may|will|would|should|has|have)\b", re.I)
_TAG = re.compile(r"(?:,\s*|\s)(?:right|correct|true|isn't\s+it|is\s+that\s+(?:right|correct|true))\s*\?\s*$|"
                  r"\b(?:says?|claims?|told\s+us|insists?)\b[^?]*\?\s*$", re.I)
# a figure is a claim about the regulation only when its sentence attributes it to a requirement: "requires a 24-month
# expiry", "within 30 days", "paid at $150 ... under 70.19", "a 5% limit". A figure of the user's own facts ("can we use it
# at 2% in a lotion?", "our bar contains 0.25% TBS") is not checked - answering "No" to it would be wrong
_CLAIM_WORDS = re.compile(r"\b(?:requires?|required|must|has\s+to|have\s+to|needs?\s+to|shall|mandat\w*|caps?|capped|"
                          r"limits?|limited|sets?|gives?|allows?|allowed|permits?|permitted|deadlines?|within|at\s+least|"
                          r"no\s+more\s+than|not\s+more\s+than|minimum|maximum|up\s+to|exactly|fees?|deposits?|paid|pay|"
                          r"costs?|charges?|period|threshold|tall|high|wide|large|retain|retention|kept|keep|expir\w*|"
                          r"wait|valid|lasts?|every|each)\b", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!;])\s+")
# a paragraph that states a rule (not background): preferred when no paragraph states a figure of the asserted kind
_OPERATIVE = re.compile(r"\b(?:shall|must|may\s+not|is\s+prohibited|are\s+prohibited|deemed|required|requires|"
                        r"exempt|is\s+adulterated|is\s+misbranded|not\s+to\s+exceed|no\s+more\s+than|within)\b", re.I)
QUOTE_CHARS = 1600
# the answer's first sentence: what the check found (written by the pipeline; its figure is the question's, quoted)
PREMISE_SENTENCE_RE = re.compile(r"No\. The figure[s]? [^\n]*? (?:does|do) not appear in the text of [^\n]*? supplied for this "
                                 r"answer\.")


@dataclass(frozen=True)
class Figure:
    value: float
    unit: str        # "money", "day", "percent", ...
    text: str        # as the question wrote it


def _value(raw: str) -> float | None:
    raw = raw.strip().lower()
    if raw in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[raw])
    if raw in _FRACTION_WORDS:
        return float(_FRACTION_WORDS[raw])
    raw = raw.replace(",", "")
    try:
        if "/" in raw:
            a, b = raw.split("/", 1)
            return float(a) / float(b)
        return float(raw)
    except (ValueError, ZeroDivisionError):
        return None


def _unit(raw: str) -> str:
    for pattern, kind in _UNITS:
        if re.fullmatch(pattern, raw.strip(), re.I):
            return kind
    return raw.lower()


def figures(text: str) -> list[Figure]:
    """Every amount with a unit in `text`, and every dollar amount."""
    out: list[Figure] = []
    for m in _MONEY.finditer(text or ""):
        v = _value(m.group(1))
        if v is not None:
            out.append(Figure(v, "money", m.group(0)))
    for m in _AMOUNT.finditer(text or ""):
        v = _value(m.group(1))
        if v is not None:
            out.append(Figure(v, _unit(m.group(2)), m.group(0)))
    return out


def puts_premise(question: str) -> bool:
    """The question asks to confirm a claim: yes/no form, a tag ("..., correct?") or a reported claim ("our consultant
    says ...?")."""
    q = (question or "").strip()
    return q.endswith("?") and bool(_YES_NO.search(q) or _TAG.search(q))


def claimed_figures(question: str) -> list[Figure]:
    """The figures the question attributes to a requirement (see _CLAIM_WORDS), sentence by sentence."""
    out: list[Figure] = []
    for sent in _SENTENCE_SPLIT.split(question or ""):
        if _CLAIM_WORDS.search(sent):
            out += [f for f in figures(sent) if f not in out]
    return out


def absent_figures(question: str, supplied: list[str]) -> list[Figure]:
    """The figures the question attributes to a requirement that no supplied text states, by value and unit."""
    have = {(round(f.value, 6), f.unit) for t in supplied for f in figures(t)}
    out = []
    for f in claimed_figures(question):
        if (round(f.value, 6), f.unit) not in have and f not in out:
            out.append(f)
    return out


def compose(package, question: str, provisions: list[str], *, limit: int = 3) -> str | None:
    """The answer to a confirmation question asserting a figure the identified provision(s) do not state, or None."""
    from regulus.rag.conversation import subject_words
    from regulus.rag.generation import _verbatim, whole_sentences
    from regulus.retrieval.evidence import TIER_EXACT, TIER_SUPPORTING

    if package is None or not provisions or not puts_premise(question):
        return None
    pool = [s for s in package.sources if not s.is_docket and (
        (s.tier == TIER_EXACT and s.requirement_ids) or (s.tier == TIER_SUPPORTING and s.corpus == "usc"))]
    if not pool:
        return None
    # every supplied text counts, not only the identified provision's: a figure stated anywhere is left to the model
    missing = absent_figures(question, [s.text or "" for s in package.sources])
    if not missing:
        return None
    kinds = {f.unit for f in missing}
    asked = subject_words(question)
    scored = []
    for s in pool:
        body = whole_sentences(s.text or "")
        if not body:
            continue
        same_kind = sum(1 for f in figures(body) if f.unit in kinds)
        overlap = len(asked & subject_words(body))
        if same_kind or overlap:
            # a paragraph that states figures of the asserted kind first, then one that states a rule, then overlap
            scored.append((-min(same_kind, 1), -int(bool(_OPERATIVE.search(body))), -overlap, s.index, s, body))
    if not scored:
        return None
    ranked = sorted(scored, key=lambda x: x[:4])
    kept, used = [], 0
    for row in ranked:
        if len(kept) >= limit or (kept and used + len(row[5]) > QUOTE_CHARS):
            break
        kept.append(row)
        used += len(row[5])
    shown = ", ".join(f'"{f.text.strip()}"' for f in missing)
    plural = len(missing) > 1
    names = " and ".join(provisions[:2]) + (" and the other provisions" if len(provisions) > 2 else "")
    lines = [f"No. The figure{'s' if plural else ''} {shown} {'do' if plural else 'does'} not appear in the text of "
             f"{names} supplied for this answer. What {'they say' if len(provisions) > 1 else 'it says'} on this point, verbatim:"]
    for *_, s, body in sorted(kept, key=lambda x: x[3]):
        kind = "FD&C Act, verbatim" if s.corpus == "usc" else "eCFR, binding, verbatim"
        lines.append(f"{s.citation} ({kind}): {_verbatim(body, s.index)}")
    return "\n".join(lines)
