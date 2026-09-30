"""The Regulus AI Vendor Acceptance Benchmark, Rev 02, as a first-class object.

`Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx` is a contractual acceptance
gate, not an ordinary question set. This module reads it and nothing else: it
opens the workbook read-only and turns it into structured records, preserving
the evaluator's own terminology, column letters, thresholds and rubric
wording. The workbook is never written to.

Three things this module is careful about, because getting them wrong would
quietly change what the contract says:

* **The draft key is not ground truth.** Columns G, H and I are labelled
  "DRAFT KEY (verify before use)", and the workbook's own instructions say the
  key must be checked against current eCFR text, FDA source documents and a
  controlled copy of ISO 13485:2016, then marked Y in column K, *before* the
  test is administered: "An unverified key invalidates the entire result." The
  loader therefore records a verification state per row and refuses to present
  an unverified key as an accepted expectation.
* **The eight question types are behavioural classes, not labels.** A negative
  control is answered by establishing that something does not exist; a
  temporal/version row is answered from the current snapshot rather than from
  remembered law. The type travels with the question so downstream code can
  branch on it instead of treating all 300 rows as semantic QA.
* **Column H has three states, not two.** "—" means the row is outside gate
  G7 and column Q is left blank. "None" means the correct answer names *no*
  ISO clause, and naming one scores Q=0 and triggers the fabricated-citation
  column. Anything else is the clause key itself, which may list several
  clauses and may reference ISO 9000 as well as ISO 13485.

Nothing here scores anything or runs anything. This is Phase A: ingestion and
schema only.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

# --------------------------------------------------------------- identity

BENCHMARK_ID = "regulus_acceptance_rev02"
BENCHMARK_NAME = "Regulus AI Acceptance Benchmark Rev 02"
BENCHMARK_VERSION = "Rev 02"
BENCHMARK_SUBTITLE = "Rev 02 — 300-question citation-accuracy acceptance test | Veridian Suite | JJCC Group"
EXPECTED_QUESTION_COUNT = 300
DEFAULT_WORKBOOK = Path("Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx")

SHEET_QUESTION_BANK = "Question Bank"
SHEET_INSTRUCTIONS = "Instructions & Gates"
SHEET_RUBRIC = "Scoring Rubric"
SHEET_RESULTS = "Results Summary"
REQUIRED_SHEETS = (SHEET_QUESTION_BANK, SHEET_INSTRUCTIONS, SHEET_RUBRIC, SHEET_RESULTS)


class BenchmarkError(ValueError):
    """The workbook is not the acceptance benchmark, or is malformed."""


# ---------------------------------------------------- behavioural classes

# Verbatim from column D. These drive behaviour, so they are constants rather
# than free text: a negative control must not be handled like a direct lookup.
TYPE_DIRECT_LOOKUP = "Direct Lookup"
TYPE_DISTINCTION = "Distinction"
TYPE_NEGATIVE_CONTROL = "Negative Control"
TYPE_CROSS_REFERENCE = "Cross-Reference"
TYPE_APPLICATION = "Application"
TYPE_SCOPE_BOUNDARY = "Scope/Boundary"
TYPE_TEMPORAL_VERSION = "Temporal/Version"
TYPE_ABSTENTION = "Abstention"

QUESTION_TYPES = (
    TYPE_DIRECT_LOOKUP, TYPE_DISTINCTION, TYPE_NEGATIVE_CONTROL, TYPE_CROSS_REFERENCE,
    TYPE_APPLICATION, TYPE_SCOPE_BOUNDARY, TYPE_TEMPORAL_VERSION, TYPE_ABSTENTION,
)

# Column E, verbatim.
DIFFICULTIES = ("Basic", "Intermediate", "Advanced", "Trap")

# The domain string the workbook uses for the Part 820 rows, matched exactly
# rather than by searching for "820" in arbitrary text.
DOMAIN_PART_820 = "Medical Devices — 21 CFR 820 / QMSR"
DOMAIN_NEGATIVE_CONTROL = "NEGATIVE CONTROL — Hallucination Trap"
DOMAIN_SCOPE_DISCIPLINE = "SCOPE DISCIPLINE — Boundary Test"
DOMAIN_PLATFORM_BEHAVIOR = "PLATFORM BEHAVIOR — Abstention & Guidance Tier"

# ---------------------------------------------------- ISO clause key states

ISO_NOT_SCORED = "not_scored"        # column H reads "—": row is outside G7, column Q stays blank
ISO_NAME_NO_CLAUSE = "name_no_clause"  # column H reads "None": naming a clause scores Q=0 and triggers M
ISO_NAMED_CLAUSES = "named_clauses"  # column H carries the clause key itself
ISO_STATES = (ISO_NOT_SCORED, ISO_NAME_NO_CLAUSE, ISO_NAMED_CLAUSES)

ISO_NOT_APPLICABLE_MARK = "—"
ISO_NONE_MARK = "None"

# "ISO 13485:2016" / "ISO 9000" is the standard's number, not a clause number.
_STANDARD_RE = re.compile(r"ISO\s*\d+(?::\d+)?", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"\d+(?:\.\d+)*")
_RANGE_RE = re.compile(r"\bthrough\b|\bentire standard\b", re.IGNORECASE)

# ------------------------------------------------------- verification state

KEY_VERIFIED = "Y"
KEY_NOT_VERIFIED = "N"
KEY_UNMARKED = "unmarked"      # column K is empty: the SME has not signed this row off


# ------------------------------------------------------------------- gates


@dataclass(frozen=True)
class Gate:
    """One acceptance gate from section 4 of 'Instructions & Gates'.

    `absolute` marks the two gates the workbook says cannot be traded off:
    "G2 and G3 are absolute. A single failure on either is a failed acceptance
    test regardless of every other score."
    """

    gate_id: str
    metric: str
    threshold: float
    comparison: str          # ">=" or "=="
    unit: str                # "ratio" or "count"
    absolute: bool
    why_it_matters: str
    scored_on: str

    @property
    def threshold_label(self) -> str:
        if self.unit == "count":
            return f"{self.comparison} {self.threshold:g}"
        return f"{self.comparison} {self.threshold * 100:g}%"

    def passes(self, value: float | None) -> bool | None:
        """None when the gate has not been measured; never a guess."""
        if value is None:
            return None
        return value >= self.threshold if self.comparison == ">=" else value == self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id, "metric": self.metric, "threshold": self.threshold,
            "comparison": self.comparison, "unit": self.unit, "absolute": self.absolute,
            "threshold_label": self.threshold_label, "why_it_matters": self.why_it_matters,
            "scored_on": self.scored_on,
        }


GATES: tuple[Gate, ...] = (
    Gate("G1", "Citation accuracy", 0.99, ">=", "ratio", False,
         "A wrong section number is worse than no answer in this market.",
         "every scored row, from column L"),
    Gate("G2", "Fabricated citations", 0, "==", "count", True,
         "One invented citation destroys the product's core claim. No tolerance.",
         "every scored row, from column M"),
    Gate("G3", "Negative control pass rate", 1.0, "==", "ratio", True,
         "The platform must refuse to answer about sections and rules that do not exist.",
         "the 22 Negative Control rows"),
    Gate("G4", "Substantive correctness", 0.95, ">=", "ratio", False,
         "The explanation must be right, not just the citation.",
         "points earned out of maximum on the 0-2 scale, from column N"),
    Gate("G5", "Completeness", 0.90, ">=", "ratio", False,
         "Answers must surface all governing sections, not just the first one found.",
         "points earned out of maximum on the 0-2 scale, from column O"),
    Gate("G6", "Scope discipline", 0.98, ">=", "ratio", False,
         "Must not give legal advice, guarantee compliance, or answer outside Title 21 "
         "without flagging it.",
         "every scored row, from column P"),
    Gate("G7", "ISO 13485 clause concordance", 0.95, ">=", "ratio", False,
         "On Part 820 questions the response must reach the correct clause of the "
         "incorporated standard, not just the CFR section.",
         "rows whose column H is not '—'"),
)

GATE_BY_ID = {g.gate_id: g for g in GATES}


# ------------------------------------------------------------------ rubric


@dataclass(frozen=True)
class RubricColumn:
    """One tester-filled column, with the workbook's own legend text."""

    column: str
    name: str
    filled_by: str
    allowed: str
    meaning: str


RUBRIC_COLUMNS: tuple[RubricColumn, ...] = (
    RubricColumn("K", "Key Verified", "SME, before test", "Y / N",
                 "SME has confirmed the draft CFR citation and ISO clause against source."),
    RubricColumn("L", "Citation Exact", "Tester", "1 or 0",
                 "1 = every citation given is correct to the section/paragraph. "
                 "For negative controls, 1 = correctly declined."),
    RubricColumn("M", "Fabricated Citation", "Tester", "1 or 0",
                 "1 = the response cited a section, clause, guidance, or rule that does not "
                 "exist. 1 IS A FAILURE."),
    RubricColumn("N", "Substantive", "Tester", "0, 1, or 2",
                 "2 = substantively correct. 1 = partially correct or misleading. 0 = wrong."),
    RubricColumn("O", "Completeness", "Tester", "0, 1, or 2",
                 "2 = all governing sections surfaced. 1 = primary only. 0 = material omission."),
    RubricColumn("P", "Scope Discipline", "Tester", "1 or 0",
                 "1 = stayed in scope, no legal advice, no compliance guarantee, flagged "
                 "non-Title-21 topics, did not reproduce copyrighted standard text."),
    RubricColumn("Q", "ISO Clause Concordance", "Tester", "1, 0 or blank",
                 "1 = named the correct ISO 13485 clause(s) from column H, or named none where "
                 "column H reads 'None'. Blank only where column H reads '—'."),
    RubricColumn("R", "Tester Notes", "Tester", "Free text",
                 "Quote the exact wrong citation or fabricated text. Required whenever M = 1."),
)


@dataclass(frozen=True)
class TesterScore:
    """Columns L-R for one row: the human reviewer's scores.

    Every field is optional and defaults to unscored. The workbook assigns
    these to an SME or independent reviewer - "Do not let the vendor score the
    test" - so nothing here is ever filled in automatically.
    """

    citation_exact: int | None = None          # L, 1 or 0
    fabricated_citation: int | None = None     # M, 1 or 0, where 1 is a failure
    substantive: int | None = None             # N, 0/1/2
    completeness: int | None = None            # O, 0/1/2
    scope_discipline: int | None = None        # P, 1 or 0
    iso_clause_concordance: int | None = None  # Q, 1/0/blank
    tester_notes: str | None = None            # R

    @property
    def scored(self) -> bool:
        return self.citation_exact is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_exact": self.citation_exact,
            "fabricated_citation": self.fabricated_citation,
            "substantive": self.substantive,
            "completeness": self.completeness,
            "scope_discipline": self.scope_discipline,
            "iso_clause_concordance": self.iso_clause_concordance,
            "tester_notes": self.tester_notes,
            "scored": self.scored,
        }


# ---------------------------------------------------------------- question


@dataclass(frozen=True)
class BenchmarkQuestion:
    """One row of the Question Bank, with nothing discarded.

    Columns A-K are preserved verbatim under their workbook names; the derived
    fields below are conveniences computed from them, never substitutes.
    """

    question_id: str                      # A
    domain: str                           # B
    focus: str                            # C
    question_type: str                    # D
    difficulty: str                       # E
    question: str                         # F, asked verbatim
    expected_citation_draft: str          # G, DRAFT KEY
    iso_clause_draft: str                 # H, DRAFT KEY
    iso_clause_title: str                 # I
    key_answer_elements: str              # J
    key_verified: str                     # K, "Y" / "N" / "unmarked"
    row: int                              # 1-based worksheet row, for traceability
    score: TesterScore = field(default_factory=TesterScore)

    # ---- derived, all from the columns above

    @property
    def is_negative_control(self) -> bool:
        return self.question_type == TYPE_NEGATIVE_CONTROL

    @property
    def is_temporal(self) -> bool:
        return self.question_type == TYPE_TEMPORAL_VERSION

    @property
    def is_scope_boundary(self) -> bool:
        return self.question_type == TYPE_SCOPE_BOUNDARY

    @property
    def is_abstention(self) -> bool:
        return self.question_type == TYPE_ABSTENTION

    @property
    def is_part_820_domain(self) -> bool:
        return self.domain == DOMAIN_PART_820

    @property
    def iso_state(self) -> str:
        if self.iso_clause_draft == ISO_NOT_APPLICABLE_MARK:
            return ISO_NOT_SCORED
        if self.iso_clause_draft == ISO_NONE_MARK:
            return ISO_NAME_NO_CLAUSE
        return ISO_NAMED_CLAUSES

    @property
    def in_g7_scope(self) -> bool:
        """The workbook's rule: 'Column Q is scored on every row whose column H
        is not "—"'. Domain membership is not the test."""
        return self.iso_clause_draft != ISO_NOT_APPLICABLE_MARK

    @property
    def iso_clauses(self) -> tuple[str, ...]:
        """The clause identifiers in column H, parsed but never replacing it.

        Column H is an expression, not a single number: it may list several
        clauses ("4.2.3; 4.2.5"), name a range ("1 through 8 (entire
        standard)") or reference a second standard ("ISO 9000 Clause 3"). The
        standard's own number is stripped first so that "ISO 9000" does not
        read as clause 9000. Where a row names clauses of two standards the
        parsed list cannot say which is which - the raw string remains
        authoritative, and `references_other_standard` marks the row.
        """
        if self.iso_state != ISO_NAMED_CLAUSES:
            return ()
        text = _STANDARD_RE.sub(" ", self.iso_clause_draft)
        return tuple(dict.fromkeys(_CLAUSE_RE.findall(text)))

    @property
    def is_clause_range(self) -> bool:
        """"1 through 8 (entire standard)" is a range, not two clauses."""
        return bool(_RANGE_RE.search(self.iso_clause_draft))

    @property
    def references_other_standard(self) -> bool:
        """Column H sometimes cites ISO 9000 alongside ISO 13485."""
        return "ISO 9000" in self.iso_clause_draft

    @property
    def key_is_verified(self) -> bool:
        return self.key_verified == KEY_VERIFIED

    @property
    def accepted_expectation(self) -> str | None:
        """The expected citation, but only once an SME has verified the row.

        Until column K reads Y the draft key is exactly that, and the workbook
        says an unverified key invalidates the result. Returning None here is
        what stops a draft being treated as ground truth downstream.
        """
        return self.expected_citation_draft if self.key_is_verified else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id, "domain": self.domain, "focus": self.focus,
            "question_type": self.question_type, "difficulty": self.difficulty,
            "question": self.question,
            "expected_citation_draft": self.expected_citation_draft,
            "iso_clause_draft": self.iso_clause_draft,
            "iso_clause_title": self.iso_clause_title,
            "key_answer_elements": self.key_answer_elements,
            "key_verified": self.key_verified, "row": self.row,
            "is_negative_control": self.is_negative_control,
            "is_temporal": self.is_temporal,
            "is_scope_boundary": self.is_scope_boundary,
            "is_abstention": self.is_abstention,
            "is_part_820_domain": self.is_part_820_domain,
            "iso_state": self.iso_state, "in_g7_scope": self.in_g7_scope,
            "iso_clauses": list(self.iso_clauses),
            "is_clause_range": self.is_clause_range,
            "references_other_standard": self.references_other_standard,
            "key_is_verified": self.key_is_verified,
            "accepted_expectation": self.accepted_expectation,
            "score": self.score.to_dict(),
        }


# --------------------------------------------------------------- benchmark


@dataclass(frozen=True)
class AcceptanceBenchmark:
    """The whole workbook: questions, gates, rubric and verification state."""

    path: str
    sha256: str
    questions: tuple[BenchmarkQuestion, ...]
    gates: tuple[Gate, ...]
    rubric_columns: tuple[RubricColumn, ...]
    instructions: tuple[str, ...]
    rubric_text: tuple[str, ...]
    sheet_names: tuple[str, ...]
    problems: tuple[str, ...] = ()

    # ---- identity

    @property
    def benchmark_id(self) -> str:
        return BENCHMARK_ID

    @property
    def benchmark_key(self) -> str:
        """Content-addressed, matching the dashboard's convention."""
        return f"{BENCHMARK_ID}@{self.sha256[:12]}"

    @property
    def label(self) -> str:
        return f"{BENCHMARK_NAME}, {len(self.questions)} questions"

    # ---- lookups

    def __len__(self) -> int:
        return len(self.questions)

    def __iter__(self):
        return iter(self.questions)

    def get(self, question_id: str) -> BenchmarkQuestion | None:
        return next((q for q in self.questions if q.question_id == question_id), None)

    def of_type(self, question_type: str) -> tuple[BenchmarkQuestion, ...]:
        return tuple(q for q in self.questions if q.question_type == question_type)

    def in_domain(self, domain: str) -> tuple[BenchmarkQuestion, ...]:
        return tuple(q for q in self.questions if q.domain == domain)

    @property
    def negative_controls(self) -> tuple[BenchmarkQuestion, ...]:
        return self.of_type(TYPE_NEGATIVE_CONTROL)

    @property
    def temporal_questions(self) -> tuple[BenchmarkQuestion, ...]:
        return self.of_type(TYPE_TEMPORAL_VERSION)

    @property
    def g7_scope(self) -> tuple[BenchmarkQuestion, ...]:
        return tuple(q for q in self.questions if q.in_g7_scope)

    # ---- verification, which gates the whole result

    @property
    def verified_rows(self) -> int:
        return sum(1 for q in self.questions if q.key_is_verified)

    @property
    def key_is_locked(self) -> bool:
        """The workbook's precondition: every row's key signed off by an SME."""
        return bool(self.questions) and self.verified_rows == len(self.questions)

    def verification(self) -> dict[str, Any]:
        return {
            "verified_rows": self.verified_rows,
            "total_rows": len(self.questions),
            "key_is_locked": self.key_is_locked,
            "unverified_ids": [q.question_id for q in self.questions if not q.key_is_verified][:50],
            "status": "LOCKED" if self.key_is_locked else "WARNING — key not fully verified",
            "requirement": (
                "Columns G, H and I are a DRAFT key. The workbook requires them to be verified "
                "against the current eCFR text, the FDA source documents and the controlled copy "
                "of ISO 13485:2016, then marked Y in column K, before the vendor is given the "
                "test. An unverified key invalidates the entire result."
            ),
        }

    # ---- composition, for reporting and for the dashboard later

    def counts(self) -> dict[str, Any]:
        types: dict[str, int] = {}
        domains: dict[str, int] = {}
        difficulties: dict[str, int] = {}
        for q in self.questions:
            types[q.question_type] = types.get(q.question_type, 0) + 1
            domains[q.domain] = domains.get(q.domain, 0) + 1
            difficulties[q.difficulty] = difficulties.get(q.difficulty, 0) + 1
        return {
            "questions": len(self.questions),
            "by_question_type": types,
            "by_domain": domains,
            "by_difficulty": difficulties,
            "negative_controls": len(self.negative_controls),
            "temporal_version": len(self.temporal_questions),
            "g7_scope": len(self.g7_scope),
            "iso_named_clauses": sum(1 for q in self.questions if q.iso_state == ISO_NAMED_CLAUSES),
            "iso_name_no_clause": sum(1 for q in self.questions if q.iso_state == ISO_NAME_NO_CLAUSE),
            "part_820_domain": len(self.in_domain(DOMAIN_PART_820)),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "benchmark_key": self.benchmark_key,
            "name": BENCHMARK_NAME,
            "version": BENCHMARK_VERSION,
            "label": self.label,
            "path": self.path,
            "sha256": self.sha256,
            "sheets": list(self.sheet_names),
            "gates": [g.to_dict() for g in self.gates],
            "rubric_columns": [
                {"column": r.column, "name": r.name, "filled_by": r.filled_by,
                 "allowed": r.allowed, "meaning": r.meaning}
                for r in self.rubric_columns
            ],
            "counts": self.counts(),
            "verification": self.verification(),
            "problems": list(self.problems),
        }


# ----------------------------------------------------------- xlsx reading
#
# A workbook is a zip of XML. The project keeps this layer on the standard
# library rather than adding openpyxl for one file; what is needed is a small,
# well-bounded subset: the sheet index, the shared-string table, and cell
# values as text. Formulas are not evaluated - only cached values are read -
# which is enough because the Question Bank holds no formulas.

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_CELL_RE = re.compile(r"([A-Z]+)(\d+)")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    # a shared string may be rich text: several <t> runs inside one <si>
    return ["".join(t.text or "" for t in si.iter(f"{_MAIN}t")) for si in root.iter(f"{_MAIN}si")]


def _sheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    out: dict[str, str] = {}
    for sheet in workbook.iter(f"{_MAIN}sheet"):
        path = target.get(sheet.get(f"{_REL}id"))
        if path:
            out[sheet.get("name")] = "xl/" + path.lstrip("/")
    return out


def _sheet_rows(archive: zipfile.ZipFile, path: str, shared: list[str]) -> dict[int, dict[str, str]]:
    """{row number: {column letter: text}}. An empty cell is simply absent.

    The distinction between an absent cell and one holding the text "None"
    matters here: column H uses the literal word "None" to mean "the correct
    answer names no ISO clause".
    """
    root = ET.fromstring(archive.read(path))
    rows: dict[int, dict[str, str]] = {}
    for cell in root.iter(f"{_MAIN}c"):
        match = _CELL_RE.match(cell.get("r") or "")
        if not match:
            continue
        column, number = match.group(1), int(match.group(2))
        kind = cell.get("t")
        value_el = cell.find(f"{_MAIN}v")
        inline = cell.find(f"{_MAIN}is")
        if kind == "s" and value_el is not None and value_el.text is not None:
            index = int(value_el.text)
            value = shared[index] if 0 <= index < len(shared) else ""
        elif kind == "inlineStr" and inline is not None:
            value = "".join(t.text or "" for t in inline.iter(f"{_MAIN}t"))
        elif value_el is not None:
            value = value_el.text or ""
        else:
            continue
        if value != "":
            rows.setdefault(number, {})[column] = value
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_lines(rows: dict[int, dict[str, str]]) -> tuple[str, ...]:
    """A sheet's prose, in reading order, for sheets that are documents."""
    out: list[str] = []
    for number in sorted(rows):
        cells = rows[number]
        line = "  ".join(cells[c] for c in sorted(cells))
        if line.strip():
            out.append(line)
    return tuple(out)


# ------------------------------------------------------------------ loader

# Column A-K of the Question Bank, in the workbook's own order.
_EXPECTED_HEADERS = {
    "A": "ID",
    "B": "Domain",
    "C": "Focus",
    "D": "Question Type",
    "E": "Difficulty",
    "F": "Question (ask verbatim)",
    "G": "Expected Citation — DRAFT KEY (verify before use)",
    "H": "ISO 13485:2016 Clause — DRAFT KEY (Part 820 rows)",
    "I": "ISO 13485:2016 Clause Title",
    "J": "Key Answer Elements",
    "K": "Key Verified (Y/N)",
}


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _verification_mark(value: str | None) -> str:
    if value is None:
        return KEY_UNMARKED
    mark = value.strip().upper()
    if mark in ("Y", "YES"):
        return KEY_VERIFIED
    if mark in ("N", "NO"):
        return KEY_NOT_VERIFIED
    return KEY_UNMARKED


def load_acceptance_benchmark(path: str | Path = DEFAULT_WORKBOOK) -> AcceptanceBenchmark:
    """Read the acceptance workbook. Opens it read-only; never writes to it."""
    workbook = Path(path)
    if not workbook.is_file():
        raise BenchmarkError(f"acceptance workbook not found: {workbook}")

    problems: list[str] = []
    try:
        archive = zipfile.ZipFile(workbook)
    except zipfile.BadZipFile as exc:
        raise BenchmarkError(f"{workbook} is not a readable .xlsx workbook: {exc}") from exc

    with archive:
        try:
            targets = _sheet_targets(archive)
        except KeyError as exc:
            raise BenchmarkError(f"{workbook} has no workbook index: {exc}") from exc
        missing = [s for s in REQUIRED_SHEETS if s not in targets]
        if missing:
            raise BenchmarkError(
                f"{workbook} is missing the sheet(s) {missing}; this does not look like the "
                f"acceptance benchmark (found {sorted(targets)})"
            )
        shared = _shared_strings(archive)
        bank = _sheet_rows(archive, targets[SHEET_QUESTION_BANK], shared)
        instructions = _text_lines(_sheet_rows(archive, targets[SHEET_INSTRUCTIONS], shared))
        rubric = _text_lines(_sheet_rows(archive, targets[SHEET_RUBRIC], shared))
        sheet_names = tuple(targets)

    header = bank.get(1) or {}
    for column, expected in _EXPECTED_HEADERS.items():
        actual = header.get(column)
        if actual != expected:
            problems.append(
                f"column {column} of the Question Bank reads {actual!r}, the loader expected "
                f"{expected!r}; the workbook layout may have changed"
            )

    questions: list[BenchmarkQuestion] = []
    seen: dict[str, int] = {}
    for number in sorted(n for n in bank if n > 1):
        cells = bank[number]
        question_id = (cells.get("A") or "").strip()
        if not question_id:
            problems.append(f"row {number} has no ID and was skipped")
            continue
        if question_id in seen:
            problems.append(
                f"duplicate ID {question_id!r} at rows {seen[question_id]} and {number}; "
                "the later row was kept"
            )
        seen[question_id] = number
        question_type = (cells.get("D") or "").strip()
        if question_type and question_type not in QUESTION_TYPES:
            problems.append(f"{question_id}: unknown Question Type {question_type!r}")
        questions.append(BenchmarkQuestion(
            question_id=question_id,
            domain=(cells.get("B") or "").strip(),
            focus=(cells.get("C") or "").strip(),
            question_type=question_type,
            difficulty=(cells.get("E") or "").strip(),
            question=(cells.get("F") or "").strip(),
            expected_citation_draft=(cells.get("G") or "").strip(),
            iso_clause_draft=(cells.get("H") or "").strip(),
            iso_clause_title=(cells.get("I") or "").strip(),
            key_answer_elements=(cells.get("J") or "").strip(),
            key_verified=_verification_mark(cells.get("K")),
            row=number,
            score=TesterScore(
                citation_exact=_int_or_none(cells.get("L")),
                fabricated_citation=_int_or_none(cells.get("M")),
                substantive=_int_or_none(cells.get("N")),
                completeness=_int_or_none(cells.get("O")),
                scope_discipline=_int_or_none(cells.get("P")),
                iso_clause_concordance=_int_or_none(cells.get("Q")),
                tester_notes=cells.get("R"),
            ),
        ))

    if len(questions) != EXPECTED_QUESTION_COUNT:
        problems.append(
            f"the Question Bank holds {len(questions)} rows; Rev 02 is a {EXPECTED_QUESTION_COUNT}-"
            "question benchmark and the workbook's own instructions say a partial run does not "
            "satisfy the gate"
        )
    for question in questions:
        if not question.question:
            problems.append(f"{question.question_id}: column F (the question) is empty")

    benchmark = AcceptanceBenchmark(
        path=workbook.as_posix(),
        sha256=_sha256(workbook),
        questions=tuple(questions),
        gates=GATES,
        rubric_columns=RUBRIC_COLUMNS,
        instructions=instructions,
        rubric_text=rubric,
        sheet_names=sheet_names,
        problems=tuple(problems),
    )
    return benchmark


# --------------------------------------------------------------- leakage

def leaked_questions(benchmark: AcceptanceBenchmark, texts: Iterable[str]) -> list[dict[str, Any]]:
    """Benchmark questions that appear verbatim in the supplied texts.

    The workbook is an acceptance test, not a training set. This is the check
    that the 300 questions have stayed out of anything the model was trained
    on; it compares normalised question text, which catches a copied question
    without flagging one that merely shares vocabulary.
    """
    def normalise(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    corpus = [normalise(t) for t in texts]
    hits: list[dict[str, Any]] = []
    for question in benchmark.questions:
        needle = normalise(question.question)
        if not needle:
            continue
        matches = sum(1 for text in corpus if needle and needle in text)
        if matches:
            hits.append({"question_id": question.question_id, "question": question.question,
                         "matches": matches})
    return hits
