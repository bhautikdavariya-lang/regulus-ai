"""Source selection: read the regulatory content the generators need from the
read-only database into plain in-memory structures.

Only SELECT statements, all constant apart from named limit/flag parameters.
Database ids are used in memory to join hierarchy rows and are never written
to the dataset. The connection is the Stage 5 `Database` (server-enforced
read-only); nothing here can write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from regulus.retrieval.citations import build_ecfr_citation, build_guidance_citation
from regulus.retrieval.db import Database
from regulus.training.config import TrainingConfig


class SourceError(RuntimeError):
    """Raised when the database is not in the expected read-only state or a
    required table is empty."""


# ------------------------------------------------------------------ models


@dataclass(frozen=True)
class Record:
    """One live cfr_records row (a verbatim eCFR paragraph)."""

    section: str
    paragraph: str  # "" or "(b)(1)"
    path_ordinal: int
    ordinal: int
    heading: str | None
    text: str
    url: str | None
    part: str
    subchapter: str | None
    is_reserved: bool = False

    @property
    def key(self) -> str:
        return f"ecfr:{self.section}:{self.paragraph}:{self.path_ordinal}"

    @property
    def citation(self) -> str:
        return build_ecfr_citation({"title": "21", "section_number": self.section, "paragraph_path": self.paragraph, "part_number": self.part}).label

    @property
    def top_level(self) -> bool:
        return self.paragraph.count("(") == 1 and self.path_ordinal == 0


@dataclass
class Section:
    number: str
    heading: str | None
    part: str
    subpart_id: str | None
    is_reserved: bool
    sort_order: int
    records: list[Record] = field(default_factory=list)

    @property
    def citation(self) -> str:
        return f"21 CFR {self.number}"

    @property
    def url(self) -> str | None:
        return self.records[0].url if self.records else None


@dataclass
class Subpart:
    id: str
    part: str
    designation: str
    title: str | None
    sort_order: int
    sections: list[str] = field(default_factory=list)


@dataclass
class Part:
    number: str
    title: str | None
    subchapter: str | None
    url: str | None
    is_reserved: bool
    sections: list[str] = field(default_factory=list)
    subparts: list[str] = field(default_factory=list)  # subpart ids in order


@dataclass(frozen=True)
class Subchapter:
    code: str
    title: str | None
    part_range: str | None


@dataclass(frozen=True)
class Definition:
    term: str
    record: Record


@dataclass(frozen=True)
class CrossRef:
    from_record: Record
    raw_text: str
    to_record: Record


@dataclass(frozen=True)
class GuidanceChunk:
    ordinal: int
    text: str


@dataclass
class GuidanceDoc:
    title: str
    docket: str | None
    status: str | None
    center: str | None
    sector: str | None
    issued_on: str | None
    url: str
    anchor_part: str | None
    anchor_section: str | None
    disclaimer: str | None
    retrievable: bool
    intro_chunks: list[GuidanceChunk] = field(default_factory=list)
    recommendation_chunks: list[GuidanceChunk] = field(default_factory=list)
    anchor_chunks: list[GuidanceChunk] = field(default_factory=list)
    anchors: list[tuple[str, str | None]] = field(default_factory=list)

    @property
    def citation(self) -> str:
        return build_guidance_citation(
            {"title": self.title, "status": self.status, "issued_on": self.issued_on, "docket_number": self.docket, "source_url": self.url, "center": self.center}
        ).label

    def chunk_key(self, chunk: GuidanceChunk) -> str:
        return f"fda_guidance:{self.url}#{chunk.ordinal}"


@dataclass
class Corpus:
    snapshot: dict[str, Any]
    subchapters: dict[str, Subchapter]
    parts: dict[str, Part]
    subparts: dict[str, Subpart]
    sections: dict[str, Section]
    definitions: list[Definition]
    cross_refs: list[CrossRef]
    guidance: list[GuidanceDoc]
    all_part_numbers: set[str]  # every cfr_parts.number including reserved ranges such as "83-98"
    all_section_numbers: set[str]  # every cfr_sections.number including reserved
    all_dockets: set[str]  # every docket on any guidance row, retrievable or not

    @property
    def snapshot_date(self) -> str | None:
        return self.snapshot.get("ecfr_snapshot_date")

    def part_title(self, part: str) -> str | None:
        p = self.parts.get(part)
        return p.title if p else None

    def subpart_of(self, section: Section) -> Subpart | None:
        return self.subparts.get(section.subpart_id) if section.subpart_id else None

    def subchapter_of_part(self, part: str) -> Subchapter | None:
        p = self.parts.get(part)
        return self.subchapters.get(p.subchapter) if p and p.subchapter else None

    def record(self, key: str) -> Record | None:
        try:
            _, section, paragraph, path_ordinal = key.split(":", 3)
        except ValueError:
            return None
        sec = self.sections.get(section)
        if not sec:
            return None
        for r in sec.records:
            if r.paragraph == paragraph and str(r.path_ordinal) == path_ordinal:
                return r
        return None

    def reserved_part_numbers(self) -> set[int]:
        """Numbers covered by reserved ranges such as '83-98' (reserved, not nonexistent)."""
        out: set[int] = set()
        for n in self.all_part_numbers:
            if "-" in n:
                a, b = n.split("-", 1)
                if a.strip().isdigit() and b.strip().isdigit():
                    out.update(range(int(a), int(b) + 1))
        return out


# --------------------------------------------------------------------- SQL

SQL_SUBCHAPTERS = "SELECT code, title, part_range FROM cfr_subchapters ORDER BY sort_order, code"
SQL_PARTS = "SELECT number, title, subchapter_code, ecfr_permalink, is_reserved FROM cfr_parts ORDER BY number"
SQL_SUBPARTS = "SELECT id::text AS id, part_number, designation, title, sort_order FROM cfr_subparts ORDER BY part_number, sort_order, designation"
SQL_SECTIONS = "SELECT number, heading, part_number, subpart_id::text AS subpart_id, is_reserved, sort_order FROM cfr_sections ORDER BY part_number, sort_order, number"
SQL_RECORDS = """
SELECT section_number, paragraph_path, path_ordinal, ordinal, section_heading, body_text, ecfr_permalink,
       part_number, subchapter_code, is_reserved
FROM cfr_records
WHERE removed_on IS NULL
ORDER BY section_number, ordinal
"""
SQL_DEFINITIONS = """
SELECT d.term, r.section_number, r.paragraph_path, r.path_ordinal
FROM cfr_definitions d
JOIN cfr_records r ON r.id = d.record_id
WHERE coalesce(d.term, '') <> '' AND r.removed_on IS NULL
ORDER BY r.section_number, r.ordinal, d.term
"""
SQL_CROSS_REFS = """
SELECT a.section_number AS from_section, a.paragraph_path AS from_paragraph, a.path_ordinal AS from_path_ordinal,
       x.raw_text, b.section_number AS to_section, b.paragraph_path AS to_paragraph, b.path_ordinal AS to_path_ordinal
FROM cfr_cross_references x
JOIN cfr_records a ON a.id = x.from_record_id
JOIN cfr_records b ON b.id = x.to_record_id
WHERE x.resolvable AND a.removed_on IS NULL AND b.removed_on IS NULL AND a.section_number <> b.section_number
ORDER BY a.section_number, a.ordinal, b.section_number, b.ordinal, x.raw_text
"""
SQL_GUIDANCE_DOCS = """
SELECT title, docket_number, status, center, sector, issued_on, source_url, anchor_part, anchor_section, disclaimer_text, retrievable
FROM fda_guidance
WHERE (%(retrievable)s::boolean IS NULL OR retrievable = %(retrievable)s)
ORDER BY source_url
"""
SQL_ALL_DOCKETS = "SELECT DISTINCT docket_number FROM fda_guidance WHERE docket_number IS NOT NULL ORDER BY docket_number"
SQL_GUIDANCE_ANCHORS = """
SELECT g.source_url, a.part, a.section
FROM fda_guidance_anchors a
JOIN fda_guidance g ON g.id = a.guidance_id
WHERE (%(retrievable)s::boolean IS NULL OR g.retrievable = %(retrievable)s)
ORDER BY g.source_url, a.part, a.section
"""
SQL_GUIDANCE_INTRO_CHUNKS = """
SELECT g.source_url, c.ordinal, c.body_text
FROM fda_guidance_chunks c
JOIN fda_guidance g ON g.id = c.guidance_id
WHERE (%(retrievable)s::boolean IS NULL OR g.retrievable = %(retrievable)s)
  AND c.ordinal < %(max_ordinal)s
ORDER BY g.source_url, c.ordinal
"""
# Chunks that contain an explicit "FDA recommends" sentence, at most per_document per guidance.
SQL_GUIDANCE_RECOMMENDATION_CHUNKS = r"""
SELECT source_url, ordinal, body_text FROM (
    SELECT g.source_url, c.ordinal, c.body_text,
           ROW_NUMBER() OVER (PARTITION BY c.guidance_id ORDER BY c.ordinal) AS rn
    FROM fda_guidance_chunks c
    JOIN fda_guidance g ON g.id = c.guidance_id
    WHERE (%(retrievable)s::boolean IS NULL OR g.retrievable = %(retrievable)s)
      AND c.body_text ~ '\mFDA recommends\M'
) ranked
WHERE rn <= %(per_document)s
ORDER BY source_url, ordinal
"""
# Chunks that cite the document's own anchor section explicitly ("§ 807.92", "21 CFR 807.92").
SQL_GUIDANCE_ANCHOR_CHUNKS = r"""
SELECT source_url, ordinal, body_text FROM (
    SELECT g.source_url, c.ordinal, c.body_text,
           ROW_NUMBER() OVER (PARTITION BY c.guidance_id ORDER BY c.ordinal) AS rn
    FROM fda_guidance_chunks c
    JOIN fda_guidance g ON g.id = c.guidance_id
    WHERE (%(retrievable)s::boolean IS NULL OR g.retrievable = %(retrievable)s)
      AND g.anchor_section IS NOT NULL
      AND c.body_text ~ ('(§|21 CFR|[Ss]ection|[Pp]art)\s*' || replace(g.anchor_section, '.', '\.') || '\M')
) ranked
WHERE rn <= %(per_document)s
ORDER BY source_url, ordinal
"""
SQL_SNAPSHOT = """
SELECT (SELECT max(snapshot_date)::text FROM cfr_records WHERE removed_on IS NULL) AS ecfr_snapshot_date,
       (SELECT count(*) FROM cfr_records WHERE removed_on IS NULL) AS ecfr_live_records,
       (SELECT count(*) FROM cfr_sections) AS ecfr_sections,
       (SELECT count(*) FROM cfr_parts) AS ecfr_parts,
       (SELECT count(*) FROM fda_guidance) AS guidance_documents,
       (SELECT count(*) FROM fda_guidance WHERE retrievable) AS guidance_retrievable_documents,
       (SELECT count(*) FROM fda_guidance_chunks) AS guidance_chunks,
       (SELECT max(retrieved_at)::date::text FROM fda_guidance) AS guidance_last_retrieved,
       (SELECT count(*) FROM cfr_definitions WHERE coalesce(term, '') <> '') AS named_definitions,
       (SELECT count(*) FROM cfr_cross_references WHERE resolvable) AS resolvable_cross_references
"""

INTRO_CHUNK_ORDINALS = 4
RECOMMENDATION_CHUNKS_PER_DOCUMENT = 3
ANCHOR_CHUNKS_PER_DOCUMENT = 2


def _s(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _d(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return _s(value)


def assert_read_only(db: Database) -> dict[str, Any]:
    """SHOW default_transaction_read_only must be 'on' before anything runs."""
    status = db.status()
    if status.get("default_transaction_read_only") != "on" or status.get("transaction_read_only") != "on":
        raise SourceError("database session is not read-only; refusing to run")
    return {k: status[k] for k in ("server_version", "database", "transaction_read_only", "default_transaction_read_only")}


def load_corpus(db: Database, config: TrainingConfig) -> Corpus:
    """Read everything the generators need. Deterministic order everywhere."""
    assert_read_only(db)
    snapshot = {k: (int(v) if isinstance(v, int) else v) for k, v in db.query(SQL_SNAPSHOT)[0].items()}

    subchapters = {r["code"]: Subchapter(r["code"], _s(r["title"]), _s(r["part_range"])) for r in db.query(SQL_SUBCHAPTERS)}
    parts: dict[str, Part] = {}
    all_part_numbers: set[str] = set()
    for r in db.query(SQL_PARTS):
        all_part_numbers.add(r["number"])
        parts[r["number"]] = Part(r["number"], _s(r["title"]), _s(r["subchapter_code"]), _s(r["ecfr_permalink"]), bool(r["is_reserved"]))
    subparts: dict[str, Subpart] = {}
    for r in db.query(SQL_SUBPARTS):
        sp = Subpart(r["id"], r["part_number"], _s(r["designation"]) or "", _s(r["title"]), int(r["sort_order"] or 0))
        subparts[sp.id] = sp
        if sp.part in parts:
            parts[sp.part].subparts.append(sp.id)
    sections: dict[str, Section] = {}
    all_section_numbers: set[str] = set()
    if config.use_ecfr:
        for r in db.query(SQL_SECTIONS):
            all_section_numbers.add(r["number"])
            sec = Section(r["number"], _s(r["heading"]), r["part_number"], _s(r["subpart_id"]), bool(r["is_reserved"]), int(r["sort_order"] or 0))
            sections[sec.number] = sec
            if sec.part in parts:
                parts[sec.part].sections.append(sec.number)
            if sec.subpart_id in subparts:
                subparts[sec.subpart_id].sections.append(sec.number)
        for r in db.query(SQL_RECORDS):
            rec = Record(
                r["section_number"], r["paragraph_path"] or "", int(r["path_ordinal"] or 0), int(r["ordinal"] or 0), _s(r["section_heading"]),
                r["body_text"] or "", _s(r["ecfr_permalink"]), r["part_number"], _s(r["subchapter_code"]), bool(r["is_reserved"]),
            )
            sec = sections.get(rec.section)
            if sec is None:  # a record whose section row is missing: keep it citable anyway
                sec = Section(rec.section, rec.heading, rec.part, None, rec.is_reserved, 0)
                sections[rec.section] = sec
                all_section_numbers.add(rec.section)
            sec.records.append(rec)
    else:
        for r in db.query(SQL_SECTIONS):
            all_section_numbers.add(r["number"])

    def rec_at(section: str, paragraph: str, path_ordinal: int) -> Record | None:
        sec = sections.get(section)
        if not sec:
            return None
        for rec in sec.records:
            if rec.paragraph == (paragraph or "") and rec.path_ordinal == int(path_ordinal or 0):
                return rec
        return None

    definitions: list[Definition] = []
    cross_refs: list[CrossRef] = []
    if config.use_ecfr:
        for r in db.query(SQL_DEFINITIONS):
            rec = rec_at(r["section_number"], r["paragraph_path"], r["path_ordinal"])
            if rec is not None:
                definitions.append(Definition(str(r["term"]).strip(), rec))
        for r in db.query(SQL_CROSS_REFS):
            a = rec_at(r["from_section"], r["from_paragraph"], r["from_path_ordinal"])
            b = rec_at(r["to_section"], r["to_paragraph"], r["to_path_ordinal"])
            if a is not None and b is not None and _s(r["raw_text"]):
                cross_refs.append(CrossRef(a, str(r["raw_text"]).strip(), b))

    all_dockets = {r["docket_number"].strip().upper() for r in db.query(SQL_ALL_DOCKETS) if r["docket_number"]}
    guidance: list[GuidanceDoc] = []
    if config.use_guidance:
        flag = {"retrievable": True if config.retrievable_guidance_only else None}
        by_url: dict[str, GuidanceDoc] = {}
        for r in db.query(SQL_GUIDANCE_DOCS, flag):
            doc = GuidanceDoc(
                _s(r["title"]) or "", _s(r["docket_number"]), _s(r["status"]), _s(r["center"]), _s(r["sector"]), _d(r["issued_on"]),
                r["source_url"], _s(r["anchor_part"]), _s(r["anchor_section"]), _s(r["disclaimer_text"]), bool(r["retrievable"]),
            )
            if doc.title:
                by_url[doc.url] = doc
        for r in db.query(SQL_GUIDANCE_ANCHORS, flag):
            doc = by_url.get(r["source_url"])
            if doc:
                doc.anchors.append((str(r["part"]), _s(r["section"])))
        for stmt, attr, params in (
            (SQL_GUIDANCE_INTRO_CHUNKS, "intro_chunks", {"max_ordinal": INTRO_CHUNK_ORDINALS}),
            (SQL_GUIDANCE_RECOMMENDATION_CHUNKS, "recommendation_chunks", {"per_document": RECOMMENDATION_CHUNKS_PER_DOCUMENT}),
            (SQL_GUIDANCE_ANCHOR_CHUNKS, "anchor_chunks", {"per_document": ANCHOR_CHUNKS_PER_DOCUMENT}),
        ):
            for r in db.query(stmt, {**flag, **params}):
                doc = by_url.get(r["source_url"])
                if doc:
                    getattr(doc, attr).append(GuidanceChunk(int(r["ordinal"]), r["body_text"] or ""))
        guidance = [by_url[u] for u in sorted(by_url)]

    if config.use_ecfr and not sections:
        raise SourceError("no eCFR sections were loaded")
    if config.use_guidance and not guidance:
        raise SourceError("no guidance documents were loaded")
    return Corpus(snapshot, subchapters, parts, subparts, sections, definitions, cross_refs, guidance, all_part_numbers, all_section_numbers, all_dockets)


def source_counts(corpus: Corpus) -> dict[str, int]:
    return {
        "subchapters": len(corpus.subchapters),
        "parts": len(corpus.parts),
        "subparts": len(corpus.subparts),
        "sections": len(corpus.sections),
        "records": sum(len(s.records) for s in corpus.sections.values()),
        "definitions": len(corpus.definitions),
        "cross_references": len(corpus.cross_refs),
        "guidance_documents": len(corpus.guidance),
        "guidance_intro_chunks": sum(len(g.intro_chunks) for g in corpus.guidance),
        "guidance_recommendation_chunks": sum(len(g.recommendation_chunks) for g in corpus.guidance),
        "guidance_anchor_chunks": sum(len(g.anchor_chunks) for g in corpus.guidance),
    }
