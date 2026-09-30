"""Phase B: turning the benchmark's draft key into an accepted expectation.

The workbook's columns G, H and I are labelled "DRAFT KEY (verify before
use)", and its own instructions say the key must be checked against current
eCFR text, the FDA source documents and a controlled copy of ISO 13485:2016
before the test is administered, because "An unverified key invalidates the
entire result."

This module performs the part of that check a machine can perform, and is
deliberately explicit about the part it cannot.

    draft expectation  ──findings per dimension──▶  accepted expectation
      (never altered)        (recorded, auditable)     (only if verified)

Three rules it holds to:

* **Existence is not verification.** A row is not verified because the
  database happens to contain the cited section. Seven dimensions are checked
  separately, and two of them - whether the substance of the answer is right,
  and whether it names every governing provision - are judgments this module
  refuses to make. They are reported as REQUIRES_SME, and a row carrying one
  can never reach VERIFIED on its own.
* **Nothing is silently repaired.** Where a draft expectation is contradicted
  by the sources, the outcome is a recorded contradiction with its evidence -
  never a corrected key. The workbook stays byte-identical; the finding goes
  in a separate artifact.
* **Only verified rows may later score.** `accepted_expectation` is None until
  a row is verified, so an unverified row cannot contribute to an acceptance
  gate by accident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from regulus.evaluation.acceptance_benchmark import (
    ISO_NAME_NO_CLAUSE,
    ISO_NAMED_CLAUSES,
    AcceptanceBenchmark,
    BenchmarkQuestion,
)
from regulus.retrieval.references import CfrReference, parse_cfr_references

# ------------------------------------------------------------- dimensions

DIM_CITATION = "citation"
DIM_PARAGRAPH = "provision_paragraph"
DIM_TEMPORAL = "temporal_status"
DIM_ISO = "iso_clause"
DIM_NEGATIVE_CONTROL = "negative_control"
DIM_SUBSTANTIVE = "substantive_elements"
DIM_COMPLETENESS = "completeness"

DIMENSIONS = (
    DIM_CITATION, DIM_PARAGRAPH, DIM_TEMPORAL, DIM_ISO,
    DIM_NEGATIVE_CONTROL, DIM_SUBSTANTIVE, DIM_COMPLETENESS,
)

# Dimensions no machine decides. They need the provision text read against the
# expected answer elements by someone qualified to say whether it is right.
SME_ONLY = (DIM_SUBSTANTIVE, DIM_COMPLETENESS)

# ---------------------------------------------------------------- statuses

CONFIRMED = "CONFIRMED"
CONTRADICTED = "CONTRADICTED"
UNVERIFIABLE = "UNVERIFIABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
REQUIRES_SME = "REQUIRES_SME"
FINDING_STATUSES = (CONFIRMED, CONTRADICTED, UNVERIFIABLE, NOT_APPLICABLE, REQUIRES_SME)

STATUS_VERIFIED = "VERIFIED"
STATUS_CONTRADICTED = "CONTRADICTED"
STATUS_AWAITING_SME = "AWAITING_SME"
STATUS_UNVERIFIABLE = "UNVERIFIABLE"
ROW_STATUSES = (STATUS_VERIFIED, STATUS_CONTRADICTED, STATUS_AWAITING_SME, STATUS_UNVERIFIABLE)

# How column G declares something other than a plain citation.
_NEGATIVE_MARKERS = ("NO SUCH", "DOES NOT EXIST", "NOT A REAL", "NO SUCH REQUIREMENT")
_TEMPORAL_MARKERS = ("TEMPORAL TRAP", "[RESERVED]", "IS RESERVED")
_SCOPE_MARKERS = ("MUST DECLINE", "OUT OF SCOPE", "NOT A TITLE 21", "OUTSIDE TITLE 21")

# The declaration a negative-control key opens with. They are not
# interchangeable: "NO SUCH SECTION" asserts a section is absent, while
# "FALSE PREMISE" and "REPEALED PROVISION" are about provisions that do
# exist - reserved, or simply not containing the claimed requirement.
DECLARE_NO_SECTION = "NO SUCH SECTION"
DECLARE_NO_SUBPART = "NO SUCH SUBPART"
DECLARE_NO_CLAUSE = "NO SUCH CLAUSE"
DECLARE_FALSE_PREMISE = "FALSE PREMISE"
DECLARE_REPEALED = "REPEALED PROVISION"
# "NO SUCH REQUIREMENT / LIMIT / PROGRAM / GUIDANCE" all assert the absence of
# something inside or beyond a provision, which a section lookup cannot settle.
DECLARE_NO_REQUIREMENT = "NO SUCH REQUIREMENT-LIKE THING"

_DECLARATION_PREFIXES = (
    (DECLARE_NO_SECTION, ("NO SUCH SECTION",)),
    (DECLARE_NO_SUBPART, ("NO SUCH SUBPART",)),
    (DECLARE_NO_CLAUSE, ("NO SUCH CLAUSE",)),
    (DECLARE_FALSE_PREMISE, ("FALSE PREMISE",)),
    (DECLARE_REPEALED, ("REPEALED PROVISION",)),
    (DECLARE_NO_REQUIREMENT, ("NO SUCH REQUIREMENT", "NO SUCH LIMIT", "NO SUCH PROGRAM",
                              "NO SUCH GUIDANCE", "NO SUCH PROVISION")),
)

# Where a temporal key stops naming reserved provisions and starts naming the
# provision that now carries the requirement.
_ROUTING_MARKERS = ("now specified at", "now at", "reaches the manufacturer through",
                    "routes through", "now carried by", "is now", "requirements now",
                    "now reside", "handled under", "through 21 CFR")


def declaration_of(text: str) -> str | None:
    """The kind of absence a negative-control key is asserting, if any."""
    head = (text or "").split("—")[0].strip().upper()
    for name, prefixes in _DECLARATION_PREFIXES:
        if any(head.startswith(p) for p in prefixes):
            return name
    return None


def _routing_split(text: str) -> int:
    """Character offset where routing language begins, or -1."""
    lowered = (text or "").lower()
    offsets = [lowered.find(m) for m in _ROUTING_MARKERS if lowered.find(m) != -1]
    return min(offsets) if offsets else -1


KEY_PLAIN_CITATION = "plain_citation"
KEY_NEGATIVE_DECLARATION = "negative_declaration"
KEY_TEMPORAL_DECLARATION = "temporal_declaration"
KEY_SCOPE_DECLARATION = "scope_declaration"


def classify_draft_key(text: str) -> str:
    """What column G is actually saying, which is not always a citation."""
    upper = (text or "").upper()
    if any(m in upper for m in _NEGATIVE_MARKERS):
        return KEY_NEGATIVE_DECLARATION
    if any(m in upper for m in _TEMPORAL_MARKERS):
        return KEY_TEMPORAL_DECLARATION
    if any(m in upper for m in _SCOPE_MARKERS):
        return KEY_SCOPE_DECLARATION
    return KEY_PLAIN_CITATION


# ------------------------------------------------------------------ sources


class VerificationSources(Protocol):
    """Read-only lookups verification needs. Implementations must not write."""

    def section_state(self, section: str) -> dict[str, Any]:
        """{'exists': bool, 'live': bool, 'reserved': bool, 'covered_by': str|None}"""

    def paragraph_exists(self, section: str, paragraph: str) -> bool: ...

    def crosswalk(self, section: str) -> list[dict[str, Any]]:
        """Approved CFR-section -> ISO clause rows, with resolution_status."""

    def iso_clause_exists(self, clause: str) -> bool: ...

    def provision_text(self, section: str, paragraph_path: str = "") -> list[dict[str, Any]]:
        """The eCFR text of a provision, for a reviewer to read."""

    def search_part(self, part: str, terms: list[str], limit: int = 8) -> list[dict[str, Any]]:
        """Provisions of a part mentioning the given terms."""

    def describe(self) -> dict[str, Any]:
        """What was consulted, for the audit trail."""


_RANGE_SECTION_RE = re.compile(r"^(\d+)\.(\d+)-\1\.(\d+)$")


class DatabaseSources:
    """The read-only PostgreSQL snapshot and the approved ISO crosswalk.

    Reserved provisions are the awkward case. The snapshot stores a reserved
    span as one record whose section number is a range, "820.20-820.30", so a
    question about 820.30 finds nothing by exact match. This resolves a
    section against those ranges before concluding it does not exist, which is
    the difference between "reserved" and "never existed" - a distinction the
    benchmark's temporal rows exist to test.
    """

    def __init__(self, db) -> None:
        self.db = db
        self._sections: dict[str, dict[str, Any]] = {}
        self._crosswalk: dict[str, list[dict[str, Any]]] = {}
        self._clauses: set[str] | None = None
        self._ranges: list[tuple[str, str, int, int]] | None = None

    # ---- reserved ranges

    def _reserved_ranges(self) -> list[tuple[str, str, int, int]]:
        if self._ranges is None:
            out = []
            for row in self.db.query(
                "SELECT DISTINCT part_number, section_number FROM cfr_records WHERE is_reserved IS TRUE"
            ):
                match = _RANGE_SECTION_RE.match(str(row["section_number"]).strip())
                if match:
                    out.append((str(row["part_number"]), str(row["section_number"]),
                                int(match.group(2)), int(match.group(3))))
            self._ranges = out
        return self._ranges

    def _covering_range(self, section: str) -> str | None:
        if "." not in section:
            return None
        part, _, tail = section.partition(".")
        if not tail.isdigit():
            return None
        number = int(tail)
        for range_part, label, low, high in self._reserved_ranges():
            if range_part == part and low <= number <= high:
                return label
        return None

    def section_state(self, section: str) -> dict[str, Any]:
        if section not in self._sections:
            rows = self.db.query(
                """SELECT count(*) AS n,
                          count(*) FILTER (WHERE removed_on IS NULL) AS live,
                          bool_or(is_reserved) AS reserved
                   FROM cfr_records WHERE section_number = %(s)s""",
                {"s": section},
            )
            row = rows[0] if rows else {"n": 0, "live": 0, "reserved": False}
            covered = None if int(row["n"] or 0) else self._covering_range(section)
            self._sections[section] = {
                "exists": bool(int(row["n"] or 0)) or covered is not None,
                "live": bool(int(row["live"] or 0)) and not bool(row["reserved"]),
                "reserved": bool(row["reserved"]) or covered is not None,
                "covered_by": covered,
            }
        return self._sections[section]

    def paragraph_exists(self, section: str, paragraph: str) -> bool:
        rows = self.db.query(
            """SELECT count(*) AS n FROM cfr_records
               WHERE section_number = %(s)s AND removed_on IS NULL
                 AND (paragraph_path = %(p)s OR paragraph_path LIKE %(prefix)s)""",
            {"s": section, "p": paragraph, "prefix": paragraph + "(%"},
        )
        return bool(int(rows[0]["n"] or 0)) if rows else False

    def crosswalk(self, section: str) -> list[dict[str, Any]]:
        if section not in self._crosswalk:
            self._crosswalk[section] = [
                {"clause": str(r["clause"]), "clause_title": r["clause_title"],
                 "resolution_status": r["resolution_status"],
                 "resolved_section": r["cfr_section_resolved"],
                 "standard": r["standard_id"], "edition": r["edition"]}
                for r in self.db.query(
                    """SELECT clause, clause_title, resolution_status, cfr_section_resolved,
                              standard_id, edition
                       FROM usable_crosswalk WHERE cfr_section = %(s)s ORDER BY ordinal""",
                    {"s": section},
                )
            ]
        return self._crosswalk[section]

    def iso_clause_exists(self, clause: str) -> bool:
        if self._clauses is None:
            self._clauses = {str(r["clause"]) for r in self.db.query("SELECT DISTINCT clause FROM iso_clauses")}
        return clause in self._clauses

    def provision_text(self, section: str, paragraph_path: str = "") -> list[dict[str, Any]]:
        """The eCFR text of a provision.

        The CFR is a US Government work and is quoted here so a reviewer can
        judge substance without leaving the tool. ISO text is never returned
        by anything in this module - only clause identifiers.
        """
        sql = """SELECT section_number, paragraph_path, section_heading, body_text, effective_date::text
                 FROM cfr_records
                 WHERE section_number = %(s)s AND removed_on IS NULL"""
        params: dict[str, Any] = {"s": section}
        if paragraph_path:
            sql += " AND (paragraph_path = %(p)s OR paragraph_path LIKE %(prefix)s)"
            params.update({"p": paragraph_path, "prefix": paragraph_path + "(%"})
        sql += " ORDER BY path_ordinal, ordinal LIMIT 40"
        return [
            {"section": r["section_number"], "paragraph_path": r["paragraph_path"] or "",
             "heading": r["section_heading"], "text": r["body_text"],
             "effective_date": r["effective_date"]}
            for r in self.db.query(sql, params)
        ]

    def search_part(self, part: str, terms: list[str], limit: int = 8) -> list[dict[str, Any]]:
        """Provisions of one part whose text mentions any of `terms`.

        Used for absence claims: a reviewer asked to accept "no such
        requirement" should see what the part *does* say on the subject rather
        than be asked to prove a negative from memory. It is evidence, never a
        conclusion - nothing here decides that an absence is real.
        """
        if not terms:
            return []
        clauses, params = [], {"part": part}
        for i, term in enumerate(terms[:6]):
            key = f"t{i}"
            clauses.append(f"body_text ILIKE %({key})s")
            params[key] = f"%{term}%"
        rows = self.db.query(
            f"""SELECT section_number, paragraph_path, left(body_text, 320) AS snippet
                FROM cfr_records
                WHERE part_number = %(part)s AND removed_on IS NULL AND ({' OR '.join(clauses)})
                ORDER BY section_number, path_ordinal LIMIT {int(limit)}""",
            params,
        )
        return [{"section": r["section_number"], "paragraph_path": r["paragraph_path"] or "",
                 "snippet": r["snippet"]} for r in rows]

    def describe(self) -> dict[str, Any]:
        snapshot = self.db.query(
            "SELECT max(snapshot_date)::text AS d, count(*) AS n FROM cfr_records WHERE removed_on IS NULL")[0]
        standards = self.db.query(
            "SELECT DISTINCT standard_id, edition FROM iso_clauses ORDER BY 1, 2")
        crosswalk = self.db.query("SELECT count(*) AS n, count(DISTINCT cfr_section) AS s FROM usable_crosswalk")[0]
        return {
            "ecfr_snapshot_date": snapshot["d"],
            "ecfr_live_records": int(snapshot["n"]),
            "iso_clause_index": [f"{r['standard_id']}:{r['edition']}" for r in standards],
            "iso_clause_text_available": False,
            "crosswalk_rows": int(crosswalk["n"]),
            "crosswalk_sections": int(crosswalk["s"]),
            "note": (
                "ISO clause numbers and titles come from the approved crosswalk held in the "
                "database. The standard's text is not stored and is not consulted; clause "
                "identity is all that is verified."
            ),
        }


# ------------------------------------------------------------------ records


@dataclass(frozen=True)
class Finding:
    dimension: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "status": self.status,
                "detail": self.detail, "evidence": self.evidence}


@dataclass(frozen=True)
class RowVerification:
    """One row's verification record, for the auditable artifact."""

    benchmark_id: str
    question_id: str
    verification_status: str
    verification_source: str
    verified_citation: str | None
    verified_answer_elements: str | None
    verified_iso_clause: str | None
    verification_notes: str
    verifier: str | None
    verification_timestamp: str
    findings: tuple[Finding, ...]
    # the draft is carried alongside, never replaced
    expected_citation_draft: str = ""
    expected_iso_clause_draft: str = ""

    @property
    def key_verified(self) -> bool:
        return self.verification_status == STATUS_VERIFIED

    @property
    def accepted_expectation(self) -> str | None:
        """Only a verified row offers an expectation to score against."""
        return self.verified_citation if self.key_verified else None

    def finding(self, dimension: str) -> Finding | None:
        return next((f for f in self.findings if f.dimension == dimension), None)

    @property
    def contradictions(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status == CONTRADICTED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "question_id": self.question_id,
            "verification_status": self.verification_status,
            "verification_source": self.verification_source,
            "verified_citation": self.verified_citation,
            "verified_answer_elements": self.verified_answer_elements,
            "verified_ISO_clause": self.verified_iso_clause,
            "verification_notes": self.verification_notes,
            "verifier": self.verifier,
            "verification_timestamp": self.verification_timestamp,
            "key_verified": self.key_verified,
            "accepted_expectation": self.accepted_expectation,
            "expected_citation_draft": self.expected_citation_draft,
            "expected_ISO_clause_draft": self.expected_iso_clause_draft,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class VerificationArtifact:
    benchmark_id: str
    benchmark_key: str
    workbook_sha256: str
    workbook_path: str
    generated_at: str
    sources: dict[str, Any]
    rows: tuple[RowVerification, ...]
    verifier: str | None = None

    def row(self, question_id: str) -> RowVerification | None:
        return next((r for r in self.rows if r.question_id == question_id), None)

    @property
    def contradicted(self) -> tuple[RowVerification, ...]:
        return tuple(r for r in self.rows if r.verification_status == STATUS_CONTRADICTED)

    @property
    def verified(self) -> tuple[RowVerification, ...]:
        return tuple(r for r in self.rows if r.key_verified)

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for r in self.rows:
            by_status[r.verification_status] = by_status.get(r.verification_status, 0) + 1
        by_dimension: dict[str, dict[str, int]] = {}
        for r in self.rows:
            for f in r.findings:
                bucket = by_dimension.setdefault(f.dimension, {})
                bucket[f.status] = bucket.get(f.status, 0) + 1
        return {
            "rows": len(self.rows),
            "by_status": by_status,
            "by_dimension": by_dimension,
            "verified_rows": len(self.verified),
            "contradicted_rows": len(self.contradicted),
            "contradicted_ids": [r.question_id for r in self.contradicted],
            "key_is_locked": bool(self.rows) and len(self.verified) == len(self.rows),
            "scoring_status": (
                "READY" if self.rows and len(self.verified) == len(self.rows)
                else "BLOCKED — the key is not fully verified, and the workbook states that an "
                     "unverified key invalidates the entire result"
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "benchmark_key": self.benchmark_key,
            "workbook_sha256": self.workbook_sha256,
            "workbook_path": self.workbook_path,
            "generated_at": self.generated_at,
            "verifier": self.verifier,
            "sources": self.sources,
            "summary": self.summary(),
            "rows": [r.to_dict() for r in self.rows],
        }


# ------------------------------------------------------------------ checks


def _positive_references(question: BenchmarkQuestion, kind: str) -> tuple[CfrReference, ...]:
    """The provisions the key asserts *are* the answer.

    A negative-control or temporal key names two different sorts of provision:
    the ones it declares absent or reserved, and the one that now carries the
    requirement ("...is [Reserved]; complaint record content is now specified
    at 21 CFR 820.35(a)"). Splitting on the routing language is what keeps a
    reserved provision from being checked as though the key claimed it was
    live - an earlier version of this module dropped only the first reference
    and wrongly flagged keys that listed several reserved sections.
    """
    text = question.expected_citation_draft
    refs = parse_cfr_references(text)
    if kind not in (KEY_NEGATIVE_DECLARATION, KEY_TEMPORAL_DECLARATION):
        return refs
    split = _routing_split(text)
    if split == -1:
        return ()
    return tuple(r for r in refs if text.find(r.raw) >= split)


def _subject_references(question: BenchmarkQuestion, kind: str) -> tuple[CfrReference, ...]:
    """The provisions a negative-control or temporal row is *about*."""
    text = question.expected_citation_draft
    refs = parse_cfr_references(text)
    if kind not in (KEY_NEGATIVE_DECLARATION, KEY_TEMPORAL_DECLARATION):
        return ()
    split = _routing_split(text)
    if split == -1:
        return refs
    return tuple(r for r in refs if text.find(r.raw) < split)


def _check_citation(question, kind, sources) -> Finding:
    refs = _positive_references(question, kind)
    if not refs:
        if kind == KEY_PLAIN_CITATION:
            return Finding(DIM_CITATION, UNVERIFIABLE,
                           "no CFR reference could be parsed from the draft key",
                           {"draft": question.expected_citation_draft})
        return Finding(DIM_CITATION, NOT_APPLICABLE,
                       f"the draft key is a {kind.replace('_', ' ')}, not a citation to verify",
                       {"draft": question.expected_citation_draft})
    checked, missing = [], []
    for ref in refs:
        if ref.section is None:
            continue
        state = sources.section_state(ref.section)
        checked.append({"citation": ref.canonical, "section": ref.section, **state})
        if not state["live"]:
            missing.append(ref.canonical)
    if not checked:
        return Finding(DIM_CITATION, UNVERIFIABLE, "the draft key names a part, not a section",
                       {"draft": question.expected_citation_draft})
    if missing:
        return Finding(DIM_CITATION, CONTRADICTED,
                       "the draft key cites a provision that is not live in the current snapshot: "
                       + ", ".join(missing),
                       {"sections": checked})
    return Finding(DIM_CITATION, CONFIRMED,
                   "every cited section is present and live in the current snapshot",
                   {"sections": checked})


def _check_paragraph(question, kind, sources) -> Finding:
    refs = [r for r in _positive_references(question, kind) if r.section and r.paragraph_path]
    if not refs:
        return Finding(DIM_PARAGRAPH, NOT_APPLICABLE,
                       "the draft key asserts no paragraph-level requirement", {})
    checked, missing = [], []
    for ref in refs:
        ok = sources.paragraph_exists(ref.section, ref.paragraph_path)
        checked.append({"citation": ref.canonical, "exists": ok})
        if not ok:
            missing.append(ref.canonical)
    if missing:
        return Finding(DIM_PARAGRAPH, CONTRADICTED,
                       "the draft key cites a paragraph that is not in the snapshot: " + ", ".join(missing),
                       {"paragraphs": checked})
    return Finding(DIM_PARAGRAPH, CONFIRMED, "every cited paragraph exists", {"paragraphs": checked})


def _check_temporal(question, kind, sources) -> Finding:
    if not question.is_temporal and kind != KEY_TEMPORAL_DECLARATION:
        return Finding(DIM_TEMPORAL, NOT_APPLICABLE, "not a temporal/version row", {})
    subjects = [r for r in _subject_references(question, KEY_TEMPORAL_DECLARATION) if r.section]
    if not subjects:
        return Finding(DIM_TEMPORAL, UNVERIFIABLE,
                       "the row is temporal but no subject provision could be parsed from the draft key",
                       {"draft": question.expected_citation_draft})
    checked, live, unresolved = [], [], []
    for subject in subjects:
        state = sources.section_state(subject.section)
        statuses = sorted({r["resolution_status"] for r in sources.crosswalk(subject.section)})
        reserved = state["reserved"] or bool({"removed", "range_reserved"} & set(statuses))
        checked.append({"citation": subject.canonical, **state, "crosswalk_status": statuses,
                        "reserved": reserved})
        if state["live"]:
            live.append(subject.canonical)
        elif not reserved:
            unresolved.append(subject.canonical)
    evidence = {"subjects": checked}
    if live:
        return Finding(DIM_TEMPORAL, CONTRADICTED,
                       "the draft key treats these as reserved, but the snapshot has them live: "
                       + ", ".join(live), evidence)
    if unresolved:
        return Finding(DIM_TEMPORAL, UNVERIFIABLE,
                       "absent from the snapshot, which does not by itself distinguish a reserved "
                       "provision from one that never existed: " + ", ".join(unresolved), evidence)
    return Finding(DIM_TEMPORAL, CONFIRMED,
                   "every provision the draft key calls reserved is reserved or removed in the "
                   "current snapshot", evidence)


def _check_negative_control(question, kind, sources) -> Finding:
    if not question.is_negative_control:
        return Finding(DIM_NEGATIVE_CONTROL, NOT_APPLICABLE, "not a negative-control row", {})
    declaration = declaration_of(question.expected_citation_draft)
    subjects = [r for r in _subject_references(question, KEY_NEGATIVE_DECLARATION) if r.section]
    draft = question.expected_citation_draft
    evidence: dict[str, Any] = {"declaration": declaration, "draft": draft}

    # A reserved provision exists. Only an outright "NO SUCH SECTION" claims a
    # section is absent; a false premise or a repealed provision is about one
    # that is there.
    if declaration in (DECLARE_FALSE_PREMISE, DECLARE_REPEALED):
        if not subjects:
            return Finding(DIM_NEGATIVE_CONTROL, REQUIRES_SME,
                           f"a {declaration.lower()} about no named section: whether the premise is "
                           "false is a judgment about the provision's content", evidence)
        checked = [{"citation": r.canonical, **sources.section_state(r.section)} for r in subjects]
        evidence["sections"] = checked
        reserved = [c for c in checked if c["reserved"]]
        if reserved and all(not c["live"] for c in checked):
            return Finding(DIM_NEGATIVE_CONTROL, CONFIRMED,
                           "the provisions this false premise rests on are reserved in the current "
                           "snapshot, so the premise cannot hold", evidence)
        return Finding(DIM_NEGATIVE_CONTROL, REQUIRES_SME,
                       "the named provisions are live; whether they carry the requirement the "
                       "question assumes is a judgment about their content", evidence)

    if declaration == DECLARE_NO_CLAUSE:
        clauses = re.findall(r"Clause\s+(\d+(?:\.\d+)*)", question.question or "")
        present = [c for c in clauses if sources.iso_clause_exists(c)]
        evidence["clauses_in_question"] = clauses
        if not clauses:
            return Finding(DIM_NEGATIVE_CONTROL, UNVERIFIABLE,
                           "no ISO clause number could be read from the question", evidence)
        if present:
            return Finding(DIM_NEGATIVE_CONTROL, CONTRADICTED,
                           "the draft key says the clause does not exist, but the clause index "
                           "contains " + ", ".join(present), evidence)
        return Finding(DIM_NEGATIVE_CONTROL, CONFIRMED,
                       "the clause is absent from the ISO clause index, as the draft key states",
                       evidence)

    if declaration in (DECLARE_NO_REQUIREMENT, DECLARE_NO_SUBPART) or declaration is None:
        return Finding(DIM_NEGATIVE_CONTROL, REQUIRES_SME,
                       f"the key declares {(declaration or 'an absence').lower()}, which is not a "
                       "section-existence claim: establishing it needs the provision text, the "
                       "guidance corpus or the subpart structure read by a reviewer", evidence)

    # DECLARE_NO_SECTION
    if not subjects:
        return Finding(DIM_NEGATIVE_CONTROL, UNVERIFIABLE,
                       "the key declares no such section but names none this module can parse", evidence)
    checked = [{"citation": r.canonical, **sources.section_state(r.section)} for r in subjects]
    evidence["sections"] = checked
    present = [c["citation"] for c in checked if c["exists"]]
    if present:
        return Finding(DIM_NEGATIVE_CONTROL, CONTRADICTED,
                       "the draft key says these do not exist, but the snapshot contains them: "
                       + ", ".join(present), evidence)
    return Finding(DIM_NEGATIVE_CONTROL, CONFIRMED,
                   "absent from the snapshot, as the draft key states", evidence)


def _check_iso(question, sources) -> Finding:
    if not question.in_g7_scope:
        return Finding(DIM_ISO, NOT_APPLICABLE, "column H reads '—': the row is outside gate G7", {})

    sections = [r.section for r in parse_cfr_references(question.expected_citation_draft) if r.section]
    approved: list[dict[str, Any]] = []
    for section in dict.fromkeys(sections):
        approved.extend(sources.crosswalk(section))
    approved_clauses = {r["clause"] for r in approved}
    evidence = {"sections": sections, "approved_clauses": sorted(approved_clauses),
                "crosswalk": approved[:12]}

    if question.iso_state == ISO_NAME_NO_CLAUSE:
        # The crosswalk maps a *section* to clauses; column H 'None' is about
        # this *question's* answer. A section-level mapping therefore cannot
        # contradict it, and saying it did was this module's own error.
        return Finding(DIM_ISO, REQUIRES_SME,
                       "the draft key says the correct answer for this question names no ISO clause. "
                       "The crosswalk maps sections, not questions, so it cannot settle this; a "
                       "reviewer must confirm the answer genuinely reaches no clause",
                       evidence)

    drafted = question.iso_clauses
    if not drafted:
        return Finding(DIM_ISO, UNVERIFIABLE,
                       "column H carries no clause number this module can parse",
                       {"draft": question.iso_clause_draft})
    if question.is_clause_range:
        return Finding(DIM_ISO, UNVERIFIABLE,
                       "column H names a range of clauses rather than specific ones, which cannot be "
                       "matched clause by clause against the crosswalk",
                       {**evidence, "draft": question.iso_clause_draft})
    # The index covers clauses 1-8; a clause numbered 0.x belongs to the
    # standard's introduction, which the index does not carry, so its absence
    # says nothing about the draft key.
    outside = [c for c in drafted if c.split(".")[0] == "0"]
    unknown = [c for c in drafted if c not in outside and not sources.iso_clause_exists(c)]
    if outside and not unknown:
        return Finding(DIM_ISO, UNVERIFIABLE,
                       "the draft names clause(s) " + ", ".join(outside) + ", which lie outside the "
                       "numbering the clause index carries (it begins at clause 1)",
                       {**evidence, "drafted": list(drafted)})
    if unknown:
        return Finding(DIM_ISO, CONTRADICTED,
                       "the draft ISO key names a clause that is not in the clause index: "
                       + ", ".join(unknown),
                       {**evidence, "drafted": list(drafted)})
    if not approved_clauses:
        return Finding(DIM_ISO, UNVERIFIABLE,
                       "the approved crosswalk holds no mapping for the sections in this row, so the "
                       "draft clause cannot be confirmed against it",
                       {**evidence, "drafted": list(drafted)})
    missing = [c for c in drafted if c not in approved_clauses]
    if missing:
        # The crosswalk is an internal approved mapping at section granularity;
        # the workbook's authority is the controlled copy of ISO 13485:2016,
        # which is not held here. A disagreement between the two is a conflict
        # for the SME to settle, not a proven defect in the draft key - the
        # crosswalk may simply be coarser or incomplete.
        return Finding(DIM_ISO, REQUIRES_SME,
                       "the draft key and the approved crosswalk disagree: the draft names "
                       + ", ".join(missing)
                       + " and the crosswalk maps these sections to "
                       + (", ".join(sorted(approved_clauses)) or "no clause")
                       + ". Both clause numbers exist in the standard, so the controlled copy of "
                         "ISO 13485:2016 has to settle which mapping is right",
                       {**evidence, "drafted": list(drafted), "disputed": missing})
    return Finding(DIM_ISO, CONFIRMED,
                   "every drafted clause is in the approved crosswalk for these sections",
                   {**evidence, "drafted": list(drafted)})


def _sme_findings(question: BenchmarkQuestion) -> list[Finding]:
    return [
        Finding(DIM_SUBSTANTIVE, REQUIRES_SME,
                "whether the provision actually requires what column J says is a judgment about the "
                "text, not a lookup; it needs a qualified reviewer",
                {"key_answer_elements": question.key_answer_elements}),
        Finding(DIM_COMPLETENESS, REQUIRES_SME,
                "whether the key names every governing provision the question reaches cannot be "
                "established from the draft key alone",
                {"draft": question.expected_citation_draft}),
    ]


# ------------------------------------------------------------------ runner


def verify_question(question: BenchmarkQuestion, sources: VerificationSources) -> list[Finding]:
    """Every dimension's finding for one row."""
    kind = classify_draft_key(question.expected_citation_draft)
    return [
        _check_citation(question, kind, sources),
        _check_paragraph(question, kind, sources),
        _check_temporal(question, kind, sources),
        _check_negative_control(question, kind, sources),
        _check_iso(question, sources),
        *_sme_findings(question),
    ]


def _row_status(findings: Iterable[Finding]) -> str:
    findings = list(findings)
    if any(f.status == CONTRADICTED for f in findings):
        return STATUS_CONTRADICTED
    if any(f.status == REQUIRES_SME for f in findings):
        return STATUS_AWAITING_SME
    if any(f.status == UNVERIFIABLE for f in findings):
        return STATUS_UNVERIFIABLE
    return STATUS_VERIFIED


def verify_benchmark(
    benchmark: AcceptanceBenchmark,
    sources: VerificationSources,
    verifier: str | None = None,
) -> VerificationArtifact:
    """Verify every row. Reads only; the workbook is never written to.

    `verifier` names the person accountable for the human dimensions. Left
    None - as it is for an unattended run - no row can reach VERIFIED, because
    two dimensions always come back REQUIRES_SME.
    """
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    description = sources.describe()
    source_label = (
        f"eCFR snapshot {description.get('ecfr_snapshot_date')}; "
        f"approved ISO crosswalk ({description.get('crosswalk_rows')} rows); "
        f"clause index {', '.join(description.get('iso_clause_index') or []) or 'none'}"
    )

    rows: list[RowVerification] = []
    for question in benchmark.questions:
        findings = verify_question(question, sources)
        status = _row_status(findings)
        notes = "; ".join(
            f"{f.dimension}: {f.detail}" for f in findings
            if f.status in (CONTRADICTED, UNVERIFIABLE)
        ) or "no contradiction found by the automated checks"
        iso_finding = next((f for f in findings if f.dimension == DIM_ISO), None)
        rows.append(RowVerification(
            benchmark_id=benchmark.benchmark_id,
            question_id=question.question_id,
            verification_status=status,
            verification_source=source_label,
            # only a verified row carries an accepted expectation, so these stay
            # None until a human has signed the row off
            verified_citation=question.expected_citation_draft if status == STATUS_VERIFIED else None,
            verified_answer_elements=question.key_answer_elements if status == STATUS_VERIFIED else None,
            verified_iso_clause=(question.iso_clause_draft
                                 if status == STATUS_VERIFIED and question.in_g7_scope else None),
            verification_notes=notes,
            verifier=verifier,
            verification_timestamp=timestamp,
            findings=tuple(findings),
            expected_citation_draft=question.expected_citation_draft,
            expected_iso_clause_draft=question.iso_clause_draft,
        ))

    return VerificationArtifact(
        benchmark_id=benchmark.benchmark_id,
        benchmark_key=benchmark.benchmark_key,
        workbook_sha256=benchmark.sha256,
        workbook_path=benchmark.path,
        generated_at=timestamp,
        sources=description,
        rows=tuple(rows),
        verifier=verifier,
    )
