"""Unsupported-premise check (experimental, 2026-10-20): OFF unless a PremiseCheck is passed to RagPipeline.

A question can assume something about the regulation that is not so: "the requirements of 21 CFR Part 1250
Subpart Q" (Part 1250 has no Subpart Q), "which section of 21 CFR Part 211 requires a Chief Quality Officer to sign
every batch record" (no provision of Part 211 mentions one). Measured on the benchmark's negative controls, the model
answers such questions from whatever the part says. The check decides from the verified database, never from the
retrieved context or from similarity, and only for two forms whose premise names something checkable:

  * subpart       "Part N Subpart X": the subpart must exist in cfr_subparts for that part;
  * named thing   "which/what section of Part N requires X", "cite the section of Part N that requires X": every
                  specific thing X names - a Title-Cased term, a hyphenated compound, a standard identifier
                  ("ISO 13485"), a quoted phrase - must occur somewhere in Part N.

Ordinary wording is never checked ("a QA department to review batch records" names nothing specific), so a valid
question that is merely phrased differently from the regulation passes. When the premise is unsupported the answer
says what the database does not contain; it states nothing about what the regulation requires.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

_TITLE = r"(?:21\s*C\.?\s*F\.?\s*R\.?\s*)?"
SUBPART_RE = re.compile(rf"\b{_TITLE}part\s+(?P<part>\d{{1,4}})\s*,?\s+subpart\s+(?P<subpart>[A-Z]{{1,2}})\b", re.I)
ASSERTED_RE = re.compile(
    rf"\b(?:which|what)\s+(?:section|provision|paragraph)\s+of\s+{_TITLE}part\s+(?P<p1>\d{{1,4}})\s+"
    r"(?:requires?|mandates?|establish(?:es)?)\s+(?P<x1>[^?]+)"
    rf"|\bcite\s+the\s+(?:section|provision|paragraph)\s+of\s+{_TITLE}part\s+(?P<p2>\d{{1,4}})\s+that\s+"
    r"(?:requires?|mandates?|establish(?:es)?)\s+(?P<x2>[^?]+)", re.I)
_QUOTED_RE = re.compile(r"(?<![A-Za-z])[\"'‘“]([^\"'’”]{3,60})[\"'’”](?![A-Za-z])")
_TITLE_CASE_RE = re.compile(r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}))+\b")
_STANDARD_RE = re.compile(r"\b(?:ISO|IEC|ASTM|ANSI|AAMI)\s*\d{3,6}(?:-\d+)?\b")
_HYPHENATED_RE = re.compile(r"\b[a-z]+-[a-z]+\b")
NAMED_MAX = 4

SUBPARTS = "SELECT designation, title FROM cfr_subparts WHERE part_number = %(part)s ORDER BY sort_order"
PART_EXISTS = "SELECT count(*) AS n FROM cfr_records WHERE part_number = %(part)s AND removed_on IS NULL"
PHRASE_IN_PART = """
SELECT count(*) AS n FROM cfr_records
WHERE part_number = %(part)s AND removed_on IS NULL
  AND (body_text ~* %(pattern)s OR coalesce(section_heading, '') ~* %(pattern)s)
"""
SNAPSHOT = "SELECT max(snapshot_date) AS d FROM cfr_records WHERE removed_on IS NULL"

KIND_SUBPART = "subpart_not_found"
KIND_NAMED = "named_thing_not_in_part"


@dataclass(frozen=True)
class PremiseDecision:
    unsupported: bool
    kind: str | None = None
    part: str | None = None
    missing: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()
    answer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def named_things(asserted: str) -> list[str]:
    """The specific things an asserted requirement names; ordinary words are never among them."""
    found: list[str] = []
    for pattern in (_QUOTED_RE, _STANDARD_RE, _TITLE_CASE_RE, _HYPHENATED_RE):
        for m in pattern.finditer(asserted):
            text = (m.group(1) if pattern is _QUOTED_RE else m.group(0)).strip()
            if text and not any(text.lower() in f.lower() for f in found):
                found.append(text)
    return found[:NAMED_MAX]


def phrase_pattern(text: str) -> str:
    """Whole-word, case-insensitive POSIX pattern; spaces and hyphens are interchangeable ("third-party")."""
    words = re.findall(r"[A-Za-z0-9]+", text)
    return r"\m" + r"[\s\-]+".join(re.escape(w) for w in words) + r"\M"


@dataclass
class PremiseCheck:
    db: Any
    _snapshot: str | None = field(default=None, init=False)

    def snapshot(self) -> str:
        if self._snapshot is None:
            d = self.db.query(SNAPSHOT)[0]["d"]
            self._snapshot = d.isoformat() if hasattr(d, "isoformat") else str(d)
        return self._snapshot

    def decide(self, question: str) -> PremiseDecision:
        m = SUBPART_RE.search(question or "")
        if m:
            return self._subpart(m.group("part"), m.group("subpart").upper())
        m = ASSERTED_RE.search(question or "")
        if m:
            part = m.group("p1") or m.group("p2")
            things = named_things((m.group("x1") or m.group("x2") or "").strip())
            if things:
                return self._named(part, things)
        return PremiseDecision(False)

    def _part_exists(self, part: str) -> bool:
        return bool(self.db.query(PART_EXISTS, {"part": part})[0]["n"])

    def _subpart(self, part: str, subpart: str) -> PremiseDecision:
        if not self._part_exists(part):
            return PremiseDecision(False)   # a missing part is the grounding and coverage path's to report
        rows = self.db.query(SUBPARTS, {"part": part})
        if any(r["designation"].upper() == subpart for r in rows):
            return PremiseDecision(False, checked=(f"Subpart {subpart}",), part=part)
        listed = "; ".join(f"Subpart {r['designation']} ({r['title']})" for r in rows[:12])
        answer = (f"The available eCFR data (snapshot {self.snapshot()}) has no Subpart {subpart} in 21 CFR part {part}, "
                  "so no requirements of such a subpart can be stated.")
        if listed:
            answer += f" 21 CFR part {part} has these subparts: {listed}."
        return PremiseDecision(True, KIND_SUBPART, part, (f"Subpart {subpart}",), (f"Subpart {subpart}",), answer)

    def _named(self, part: str, things: list[str]) -> PremiseDecision:
        if not self._part_exists(part):
            return PremiseDecision(False)
        missing = tuple(t for t in things if not self.db.query(PHRASE_IN_PART, {"part": part, "pattern": phrase_pattern(t)})[0]["n"])
        if not missing:
            return PremiseDecision(False, part=part, checked=tuple(things))
        quoted = ", ".join(f'"{t}"' for t in missing)
        answer = (f"No provision of 21 CFR part {part} in the available eCFR data (snapshot {self.snapshot()}) mentions "
                  f"{quoted}, so the requirement the question describes is not found in that part.")
        return PremiseDecision(True, KIND_NAMED, part, missing, tuple(things), answer)
