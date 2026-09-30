"""Citation builders. Input is a plain row mapping from SQL; output is a
Citation. No database access and no invented values: anything not present in
the row stays None."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from regulus.retrieval.models import Citation


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return _str(value)


def build_ecfr_citation(row: Mapping[str, Any]) -> Citation:
    """21 CFR 820.10(b)(1) from title, section_number and paragraph_path."""
    title = _str(row.get("title")) or "21"
    section = _str(row.get("section_number"))
    paragraph = _str(row.get("paragraph_path")) or None
    part = _str(row.get("part_number"))
    if section:
        label = f"{title} CFR {section}{paragraph or ''}"
    elif part:
        label = f"{title} CFR part {part}"
    else:
        label = f"{title} CFR"
    return Citation(
        corpus="ecfr",
        label=label,
        url=_str(row.get("ecfr_permalink")),
        title=title,
        part=part,
        section=section,
        paragraph=paragraph,
        heading=_str(row.get("section_heading")),
    )


def build_guidance_citation(row: Mapping[str, Any]) -> Citation:
    """Document-level citation: title, status, issued date, docket, URL."""
    doc_title = _str(row.get("title"))
    status = _str(row.get("status"))
    issued = _date(row.get("issued_on"))
    docket = _str(row.get("docket_number"))
    parts = [f"FDA Guidance: {doc_title}" if doc_title else "FDA Guidance"]
    qualifiers = [q for q in (status, issued, f"Docket {docket}" if docket else None) if q]
    if qualifiers:
        parts.append(f"({', '.join(qualifiers)})")
    return Citation(
        corpus="fda_guidance",
        label=" ".join(parts),
        url=_str(row.get("source_url")),
        document_title=doc_title,
        docket_number=docket,
        status=status,
        issued_on=issued,
        center=_str(row.get("center")),
    )
