"""NX1 (29 Oct 2026): a requested provision that does not exist is said not to exist, from the database.

"The available eCFR data does not contain 21 CFR 101.9(k)(5)" reads as a gap in the data, and the false premise behind
the question stands (300Q NC-014: "What does 21 CFR 101.9(k)(5) say about mandatory QR code placement?" - 101.9(k) ends
at (k)(4)). The corpus holds every live section of Title 21 (28 Oct check: 0 of 312 key sections missing that exist), so
the database can settle it - but only where a data defect cannot be mistaken for absence:

  * a section with any row at all (reserved or removed included), or a former Quality System regulation section, is
    never called nonexistent;
  * "Part N has no section N.x" only when Part N has live sections;
  * a paragraph only when its parent exists and the requested designator comes after the parent's last subparagraph,
    the existing ones running without a gap from the first ((a), (b), (c) ... or (1), (2), (3) ...); roman designators
    are left alone.

A term of the question's premise (an acronym phrase such as "QR code", or a quoted phrase) that the section's text never
uses is named as absent. None when nothing can be established, and the caller keeps its own wording.
"""
from __future__ import annotations

import re

_LABEL = re.compile(r"(?:21\s+CFR\s+)?(?P<sec>\d+\.\d+[a-z]?)(?P<path>(?:\([A-Za-z0-9]+\))*)")
_COMPONENT = re.compile(r"\(([A-Za-z0-9]+)\)")
_ACRONYM_TERM = re.compile(r"\b([A-Z]{2,5}(?:\s+[a-z]{3,})?)\b")
_QUOTED = re.compile(r"['\"‘“]([A-Za-z][A-Za-z -]{2,40})['\"’”]")
_NOT_TERMS = {"CFR", "FDA", "USC", "ISO", "FD", "OTC", "USDA", "EPA", "GMP", "CGMP", "QMSR", "QSR", "HACCP"}


def _seq_value(c: str) -> int | None:
    """Position of a designator in its sequence: a=1, b=2 ... or 1, 2 ...; None for i, v, x (letter or roman numeral?),
    capitals and anything else - no claim is made where the sequence could be misread."""
    if c.isdigit():
        return int(c)
    if len(c) == 1 and c.islower() and c not in "ivx":
        return ord(c) - 96
    return None


def _sequence_ok(designators: list[str]) -> int | None:
    """The last position when the designators run 1..n without a gap, else None."""
    vals = [_seq_value(c) for c in designators]
    if not vals or any(v is None for v in vals):
        return None
    vals = sorted(set(vals))
    return vals[-1] if vals == list(range(1, len(vals) + 1)) else None


def _premise_terms(question: str) -> list[str]:
    terms = [m.group(1) for m in _QUOTED.finditer(question or "")]
    terms += [m.group(1) for m in _ACRONYM_TERM.finditer(question or "") if m.group(1).split()[0] not in _NOT_TERMS]
    return list(dict.fromkeys(t.strip() for t in terms if t.strip()))


def statement(db, question: str, labels) -> str | None:
    out: list[str] = []
    sections: dict[str, str] = {}
    for label in labels:
        m = _LABEL.search(label or "")
        if not m:
            return None
        sec, path = m.group("sec"), m.group("path") or ""
        rows = db.query("SELECT paragraph_path, body_text, snapshot_date, is_reserved, removed_on FROM cfr_records "
                        "WHERE section_number = %(s)s", {"s": sec})
        live = [r for r in rows if r["removed_on"] is None and not r["is_reserved"]]
        if not rows:
            part = sec.split(".")[0]
            if part == "820":
                from regulus.rag.qmsr import reference

                if sec in reference()["former_sections"]:
                    return None   # a former Quality System regulation section: removed, not nonexistent (QM1 answers it)
            if not db.query("SELECT 1 AS ok FROM cfr_records WHERE part_number = %(p)s AND removed_on IS NULL AND NOT "
                            "is_reserved LIMIT 1", {"p": part}):
                return None
            out.append(f"21 CFR Part {part} has no section {sec}")
            continue
        if not live or not path:
            return None   # reserved or removed: what it was is another answer; a whole live section is not missing
        comps = _COMPONENT.findall(path)
        parent = "".join(f"({c})" for c in comps[:-1])
        paths = [r["paragraph_path"] or "" for r in live]
        if parent and parent not in paths:
            return None   # the parent is missing too: settled only one level at a time
        children = [_COMPONENT.findall(p)[len(comps) - 1] for p in paths
                    if p.startswith(parent) and len(_COMPONENT.findall(p)) == len(comps)]
        children = sorted(dict.fromkeys(children), key=lambda c: (_seq_value(c) is None, _seq_value(c) or 0, c))
        want = _seq_value(comps[-1])
        if want is None:
            return None
        if not children:
            if not parent:
                return None
            out.append(f"21 CFR {sec}{parent} has no subparagraphs, so there is no {sec}{path}")
        else:
            last = _sequence_ok(children)
            if last is None or want <= last:
                return None
            out.append(f"21 CFR {sec}{parent} has paragraphs {sec}{parent}({children[0]}) through "
                       f"{sec}{parent}({children[-1]}) and no {sec}{path}")
        sections[sec] = " ".join(r["body_text"] or "" for r in live).lower()
        snap = next((r["snapshot_date"] for r in live if r["snapshot_date"]), None)
        if snap is not None:
            out[-1] += f" (eCFR text as of {snap.isoformat() if hasattr(snap, 'isoformat') else snap})"
    if not out:
        return None
    text = "; ".join(out) + ". The provision the question asks about does not exist, so there is nothing in it to state."
    absent = [t for t in _premise_terms(question) if sections and all(t.lower() not in body for body in sections.values())]
    if absent:
        where = " or ".join(f"21 CFR {s}" for s in sections)
        text += " " + " ".join(f"{where} does not mention “{t}”." for t in absent)
    return text
