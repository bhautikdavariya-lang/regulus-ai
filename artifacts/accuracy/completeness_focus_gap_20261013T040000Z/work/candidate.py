"""Prototype of the two candidate changes, patched in at runtime so every measurement runs them
WITHOUT touching src/. `patched()` applies both; `patched(focus=False)` / `patched(anchor=False)` one.

1. focus gap: a requirement group is demanded only if, besides being on topic as today, it carries at
   least one of the question's DISTINGUISHING topic words - the ones present in some but not all of
   the provision's obligation-bearing groups. With none, today's rule applies unchanged.
2. time anchor: a claim stating a time LIMIT ("no later than 7 calendar days") whose aligned evidence
   states the same period with an anchor ("... after the sponsor's initial receipt of the information")
   and which gives no anchor of its own drops a condition of that limit: an omission, so the claim is
   at most partially supported. It can only downgrade.
"""
from __future__ import annotations
import contextlib, re, sys
from dataclasses import replace
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

_NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|sixty|ninety)"
_PERIOD = rf"({_NUM})[\s-]+(?:(?:calendar|working|business)[\s-]+)?(day|week|month|year|hour)s?\b"
_ANCHOR_WORDS = r"(?:after|from|of|following|before|prior\s+to|upon|once|since|beginning|starting)"
_LIMIT_LEAD = r"(?:no\s+later\s+than|not\s+later\s+than|in\s+no\s+case\s+later\s+than|later\s+than|within|not\s+more\s+than|no\s+more\s+than|by)"
_EVIDENCE_RE = re.compile(rf"\b{_PERIOD}\s+{_ANCHOR_WORDS}\b", re.I)
_CLAIM_LIMIT_RE = re.compile(rf"\b{_LIMIT_LEAD}\s+(?:\S+\s+){{0,2}}?{_PERIOD}(?P<tail>[^.;]*)", re.I)
_TAIL_ANCHOR_RE = re.compile(rf"^\s*(?:\[\d+\]\s*)?{_ANCHOR_WORDS}\b", re.I)


def _norm(num, unit):
    words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
             "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30",
             "sixty": "60", "ninety": "90"}
    return (words.get(num.lower(), num), unit.lower())


def dropped_time_anchor(claim: str, evidence: str) -> str | None:
    anchored = {_norm(m.group(1), m.group(2)) for m in _EVIDENCE_RE.finditer(evidence or "")}
    if not anchored:
        return None
    for m in _CLAIM_LIMIT_RE.finditer(claim or ""):
        period = _norm(m.group(1), m.group(2))
        if period in anchored and not _TAIL_ANCHOR_RE.match(m.group("tail") or ""):
            return (f"the evidence runs the {period[0]}-{period[1]} period from a stated event, and the answer gives "
                    f"the period without it")
    return None


def _focus_rule():
    from harness import explain_focus_gap

    def run(package, intent, answering, claims, passages):
        return explain_focus_gap(package, intent, answering, claims, passages, rule="distinguishing")[0]
    return run


@contextlib.contextmanager
def patched(*, focus: bool = True, anchor: bool = True):
    from regulus.accuracy import evaluator as E, operators as OP
    orig_gap, orig_compare = E._focus_gap, OP.compare

    def compare(claim, evidence, *, authority=OP.BINDING):
        c = orig_compare(claim, evidence, authority=authority)
        detail = dropped_time_anchor(claim, evidence)
        if detail is None:
            return c
        om = {"operator": "dropped_time_anchor", "detail": detail, "claim": None, "evidence": None}
        return replace(c, omissions=tuple(c.omissions) + (om,))

    if focus:
        E._focus_gap = _focus_rule()
    if anchor:
        OP.compare = compare
    try:
        yield
    finally:
        E._focus_gap, OP.compare = orig_gap, orig_compare
