"""Deterministic verification of a requested regulatory identifier against the
verified database.

Stage 12 showed that the language model cannot be trusted to decide whether a
CFR section or a guidance docket exists: asked about the nonexistent
21 CFR 314.999 it re-attributed a real sentence from another section. This
module answers that question from the database instead, and answers it
narrowly.

Three rules keep the layer safe:

  1. It never rewrites an identifier into a different one. 21 CFR 314.999 is
     never "corrected" to 21 CFR 314.99. Normalisation is limited to
     punctuation and spacing ("21 C.F.R. § 314.999" -> "21 CFR 314.999") and
     is asserted by tests.
  2. It distinguishes "verified absent" from "cannot be verified". The corpus
     is Title 21 only, so a Title 40 citation is unverifiable, not absent.
  3. It reports a reason, not just a boolean, so callers can say why they are
     refusing.

The database is read through the existing Stage 5 read-only layer; nothing
here can write. A corpus-backed index is provided so Stage 13 training-data
generation can verify millions of candidates without a query per candidate.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from regulus.retrieval.query import parse_cfr_reference, parse_cfr_references, parse_docket

TITLE_21 = "21"

# identifier kinds
PART = "part"
SECTION = "section"
PARAGRAPH = "paragraph"
DOCKET = "docket"

# verification outcomes
FOUND = "found"
NOT_IN_SNAPSHOT = "not_in_snapshot"
RESERVED = "reserved"
PARAGRAPH_NOT_IN_SECTION = "paragraph_not_in_section"
OUTSIDE_TITLE_21 = "outside_title_21"

_RANGE_RE = re.compile(r"^(\d{1,4})\s*-\s*(\d{1,4})$")


@dataclass(frozen=True)
class RequestedIdentifier:
    """A regulatory identifier named in a question, as written."""

    kind: str
    raw: str
    title: str | None = None
    part: str | None = None
    section: str | None = None
    paragraph: str = ""
    docket: str | None = None

    @property
    def label(self) -> str:
        """Canonical spelling. Never changes any digit of the original."""
        if self.kind == DOCKET:
            return str(self.docket)
        title = self.title or TITLE_21
        if self.kind == PART:
            return f"{title} CFR Part {self.part}"
        return f"{title} CFR {self.section}{self.paragraph}"

    @property
    def source_type(self) -> str:
        return "fda_guidance" if self.kind == DOCKET else "ecfr"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "label": self.label, "source_type": self.source_type}


@dataclass(frozen=True)
class IdentifierVerification:
    """Structured result. `exists` means 'resolves to live content in the
    verified snapshot'; `verifiable` means 'the database can answer at all'."""

    identifier: RequestedIdentifier
    exists: bool
    verifiable: bool
    reason: str
    normalized_identifier: str
    source_type: str
    record: dict[str, Any] = field(default_factory=dict)

    @property
    def verified_absent(self) -> bool:
        """True only when the database authoritatively shows the identifier is
        not live content. This is the single condition that justifies refusing
        on existence grounds."""
        return self.verifiable and not self.exists

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier.to_dict(),
            "exists": self.exists,
            "verifiable": self.verifiable,
            "verified_absent": self.verified_absent,
            "reason": self.reason,
            "normalized_identifier": self.normalized_identifier,
            "source_type": self.source_type,
            "record": dict(self.record),
        }


class IdentifierIndex(Protocol):
    """Existence lookups. Implementations must be read-only."""

    def part_status(self, part: str) -> tuple[bool, bool]: ...  # (exists_in_structure, has_live_records)

    def section_status(self, section: str) -> tuple[bool, bool]: ...

    def paragraph_exists(self, section: str, paragraph: str) -> bool: ...

    def docket_exists(self, docket: str) -> bool: ...

    def section_facts(self, section: str) -> dict[str, Any]: ...


# ----------------------------------------------------------------- parsing


def extract_identifier(question: str) -> RequestedIdentifier | None:
    """The identifier a question asks about, or None when none is named.

    Deliberately conservative: it reuses the Stage 5 parser, so only the forms
    that parser recognises are treated as identifiers. Nothing is invented.
    """
    docket = parse_docket(question or "")
    ref = parse_cfr_reference(question or "")
    if ref is not None:
        kind = PART if ref.section is None else (PARAGRAPH if ref.paragraph_path else SECTION)
        return RequestedIdentifier(
            kind=kind,
            raw=ref.raw,
            title=ref.title,
            part=ref.part,
            section=ref.section,
            paragraph=ref.paragraph_path,
        )
    if docket is not None:
        return RequestedIdentifier(kind=DOCKET, raw=docket, docket=docket)
    return None


def extract_identifiers(question: str) -> tuple[RequestedIdentifier, ...]:
    """Every CFR identifier a question names, in order (Stage 1), plus the docket if any.

    extract_identifier() remains the single-identifier view used by the
    Stage 13 gate; this is the multi-reference view later stages will use.
    """
    out = []
    for ref in parse_cfr_references(question or ""):
        kind = PART if ref.section is None else (PARAGRAPH if ref.paragraph_path else SECTION)
        out.append(RequestedIdentifier(kind=kind, raw=ref.raw, title=ref.title, part=ref.part, section=ref.section, paragraph=ref.paragraph_path))
    docket = parse_docket(question or "")
    if docket is not None:
        out.append(RequestedIdentifier(kind=DOCKET, raw=docket, docket=docket))
    return tuple(out)


# ------------------------------------------------------------ verification


def verify_identifier(identifier: RequestedIdentifier | None, index: IdentifierIndex) -> IdentifierVerification | None:
    """Verify one identifier. Returns None when there is nothing to verify."""
    if identifier is None:
        return None
    label = identifier.label
    if identifier.kind == DOCKET:
        exists = index.docket_exists(str(identifier.docket).upper())
        return IdentifierVerification(
            identifier, exists, True, FOUND if exists else NOT_IN_SNAPSHOT, label, "fda_guidance"
        )
    if (identifier.title or TITLE_21) != TITLE_21:
        # the corpus holds Title 21 only: absence here is not evidence of absence
        return IdentifierVerification(identifier, False, False, OUTSIDE_TITLE_21, label, "ecfr")
    if identifier.kind == PART:
        in_structure, live = index.part_status(str(identifier.part))
        if live:
            return IdentifierVerification(identifier, True, True, FOUND, label, "ecfr")
        reason = RESERVED if in_structure else NOT_IN_SNAPSHOT
        return IdentifierVerification(identifier, False, True, reason, label, "ecfr")
    in_structure, live = index.section_status(str(identifier.section))
    if not live:
        reason = RESERVED if in_structure else NOT_IN_SNAPSHOT
        return IdentifierVerification(identifier, False, True, reason, label, "ecfr")
    facts = index.section_facts(str(identifier.section))
    if identifier.kind == SECTION:
        return IdentifierVerification(identifier, True, True, FOUND, label, "ecfr", facts)
    if index.paragraph_exists(str(identifier.section), identifier.paragraph):
        return IdentifierVerification(identifier, True, True, FOUND, label, "ecfr", facts)
    return IdentifierVerification(identifier, False, True, PARAGRAPH_NOT_IN_SECTION, label, "ecfr", facts)


def verify_question(question: str, index: IdentifierIndex) -> IdentifierVerification | None:
    return verify_identifier(extract_identifier(question), index)


# --------------------------------------------------------------- backends


class CorpusIdentifierIndex:
    """In-memory index over a Stage 11 `Corpus`. Used by dataset generation so
    candidate identifiers are verified without one query each."""

    def __init__(self, corpus) -> None:
        self._corpus = corpus
        self._reserved_parts = corpus.reserved_part_numbers()
        self._live_sections = {n for n, s in corpus.sections.items() if s.records and not s.is_reserved}
        self._live_parts = {s.part for n, s in corpus.sections.items() if n in self._live_sections}
        self._paragraphs: dict[str, set[str]] = {}
        for number in self._live_sections:
            self._paragraphs[number] = {r.paragraph for r in corpus.sections[number].records}
        self._dockets = {d.upper() for d in corpus.all_dockets}

    def part_status(self, part: str) -> tuple[bool, bool]:
        known = part in self._corpus.all_part_numbers or (part.isdigit() and int(part) in self._reserved_parts)
        return known, part in self._live_parts

    def section_status(self, section: str) -> tuple[bool, bool]:
        return section in self._corpus.all_section_numbers, section in self._live_sections

    def paragraph_exists(self, section: str, paragraph: str) -> bool:
        labels = self._paragraphs.get(section, set())
        if paragraph in labels:
            return True
        # a request for "(b)" is satisfied by "(b)(1)" existing
        return any(p.startswith(paragraph) for p in labels if paragraph)

    def docket_exists(self, docket: str) -> bool:
        return docket.upper() in self._dockets

    def section_facts(self, section: str) -> dict[str, Any]:
        sec = self._corpus.sections.get(section)
        if sec is None:
            return {}
        return {
            "heading": sec.heading,
            "part": sec.part,
            "part_title": self._corpus.part_title(sec.part),
            "paragraphs": sorted({r.paragraph for r in sec.records if r.paragraph})[:40],
        }


SQL_PART = """
SELECT (SELECT count(*) FROM cfr_parts WHERE number = %(p)s) AS in_structure,
       (SELECT count(*) FROM cfr_records WHERE part_number = %(p)s AND removed_on IS NULL) AS live
"""
SQL_PART_RANGES = "SELECT number FROM cfr_parts WHERE number LIKE '%%-%%'"
SQL_SECTION = """
SELECT (SELECT count(*) FROM cfr_sections WHERE number = %(s)s) AS in_structure,
       (SELECT count(*) FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL AND NOT is_reserved) AS live
"""
SQL_PARAGRAPH = """
SELECT count(*) AS n FROM cfr_records
WHERE section_number = %(s)s AND removed_on IS NULL
  AND (paragraph_path = %(p)s OR paragraph_path LIKE %(prefix)s)
"""
SQL_DOCKET = "SELECT count(*) AS n FROM fda_guidance WHERE upper(docket_number) = %(d)s"
SQL_SECTION_FACTS = """
SELECT s.heading, s.part_number, p.title AS part_title,
       (SELECT array_agg(DISTINCT r.paragraph_path ORDER BY r.paragraph_path)
        FROM cfr_records r WHERE r.section_number = s.number AND r.removed_on IS NULL AND r.paragraph_path <> '') AS paragraphs
FROM cfr_sections s LEFT JOIN cfr_parts p ON p.number = s.part_number
WHERE s.number = %(s)s
"""


class DatabaseIdentifierIndex:
    """Read-only database lookups with a per-instance cache.

    Every statement is a SELECT with named server-side parameters; the
    connection is the Stage 5 `Database`, which the server holds read-only.
    """

    def __init__(self, db) -> None:
        self.db = db
        self._parts: dict[str, tuple[bool, bool]] = {}
        self._sections: dict[str, tuple[bool, bool]] = {}
        self._paragraphs: dict[tuple[str, str], bool] = {}
        self._dockets: dict[str, bool] = {}
        self._facts: dict[str, dict[str, Any]] = {}
        self._reserved: set[int] | None = None

    def _reserved_parts(self) -> set[int]:
        if self._reserved is None:
            out: set[int] = set()
            for row in self.db.query(SQL_PART_RANGES):
                m = _RANGE_RE.match(str(row["number"]).strip())
                if m:
                    out.update(range(int(m.group(1)), int(m.group(2)) + 1))
            self._reserved = out
        return self._reserved

    def part_status(self, part: str) -> tuple[bool, bool]:
        if part not in self._parts:
            row = self.db.query(SQL_PART, {"p": part})[0]
            in_structure = bool(row["in_structure"]) or (part.isdigit() and int(part) in self._reserved_parts())
            self._parts[part] = (in_structure, bool(row["live"]))
        return self._parts[part]

    def section_status(self, section: str) -> tuple[bool, bool]:
        if section not in self._sections:
            row = self.db.query(SQL_SECTION, {"s": section})[0]
            self._sections[section] = (bool(row["in_structure"]), bool(row["live"]))
        return self._sections[section]

    def paragraph_exists(self, section: str, paragraph: str) -> bool:
        key = (section, paragraph)
        if key not in self._paragraphs:
            row = self.db.query(SQL_PARAGRAPH, {"s": section, "p": paragraph, "prefix": paragraph + "(%"})[0]
            self._paragraphs[key] = bool(row["n"])
        return self._paragraphs[key]

    def docket_exists(self, docket: str) -> bool:
        key = docket.upper()
        if key not in self._dockets:
            self._dockets[key] = bool(self.db.query(SQL_DOCKET, {"d": key})[0]["n"])
        return self._dockets[key]

    def section_facts(self, section: str) -> dict[str, Any]:
        if section not in self._facts:
            rows = self.db.query(SQL_SECTION_FACTS, {"s": section})
            if not rows:
                self._facts[section] = {}
            else:
                r = rows[0]
                self._facts[section] = {
                    "heading": r["heading"],
                    "part": r["part_number"],
                    "part_title": r["part_title"],
                    "paragraphs": list(r["paragraphs"] or [])[:40],
                }
        return self._facts[section]
