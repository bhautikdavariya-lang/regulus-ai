"""Parse official U.S. Code text (govinfo USCODE HTML rendered to text) into paragraph rows.

Input is one file per section as written by the govinfo fetcher: a `SOURCE:` and `LABEL: FDCA 605 = 21 U.S.C. 364a`
header, the page banner, the `§364a. Heading` line, the section text with one designated paragraph per line, then the
source credit `(June 25, 1938, ...)` and the editorial/statutory notes, which are not law and are dropped.

Paragraph designators follow the U.S. Code outline: (a) subsection, (1) paragraph, (A) subparagraph, (i) clause,
(I) subclause. A line may open with several designators, "(h)(1) The term ...". "(i)" and similar letters are both a
subsection letter and a roman numeral; it is read as a clause only when the line sits under a subparagraph (A) or
when the previous subsection letter is not the one before it ("(h)" -> "(i)" is a subsection).

Nothing is invented: every row's text is a line of the source, and the path is read from the designators.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_DESIG = re.compile(r"^\((?P<d>[A-Za-z]{1,6}|\d{1,3})\)")
_ROMAN_LOWER = re.compile(r"^(?=[ivxl]+$)m{0}(xl|l?x{0,3})(ix|iv|v?i{0,3})$")
_ROMAN_UPPER = re.compile(r"^(?=[IVXL]+$)(XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_HEADING = re.compile(r"^§\s*(?P<usc>\d+[a-z]*(?:-\d+)?)\.\s*(?P<heading>.+)$")
_LABEL = re.compile(r"^LABEL:\s*FDCA\s+(?P<fdca>\d+[A-Za-z]*(?:-\d+)?)\s*=\s*21 U\.S\.C\.\s*(?P<usc>\S+)")
_SOURCE = re.compile(r"^SOURCE:\s*(?P<url>\S+)")
_CREDIT = re.compile(r"^\((?:June 25, 1938|Pub\. L\.)")
_END_MARKERS = ("Editorial Notes", "Statutory Notes and Related Subsidiaries", "Executive Documents")


@dataclass(frozen=True)
class StatuteRow:
    fdca_section: str          # "605"
    usc_section: str           # "364a"
    paragraph_path: str        # "(b)(1)", "" for undesignated lead text
    ordinal: int
    heading: str               # section heading, "Adverse events"
    paragraph_heading: str     # the designated line's own caption when it has no text ("Submission of reports")
    body_text: str
    source_url: str
    top_caption: str = ""      # the caption of the row's top-level subsection ("(b) Submission of reports" -> that text)

    @property
    def label(self) -> str:
        return f"FD&C Act § {self.fdca_section}{self.paragraph_path} [21 U.S.C. {self.usc_section}{self.paragraph_path}]"

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.body_text.encode("utf-8")).hexdigest()


_ROMANS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii",
           "xviii", "xix", "xx", "xxi", "xxii", "xxiii", "xxiv", "xxv"]


def _is_letter(d: str) -> bool:
    """(a) ... (z), (aa), (bbb): one letter, possibly repeated."""
    return len(set(d)) == 1


def _next_letter(d: str) -> str:
    return d[0] * len(d) if d[0] == "z" else chr(ord(d[0]) + 1) * len(d)


def _kind(d: str, path: list[tuple[int, str]], ahead: list[str], last: dict[int, str] | None = None) -> int:
    """Outline level of designator d: 1 (a), 2 (1), 3 (A), 4 (i), 5 (I). `ahead` = the first designators of the
    following lines, used only when d is both a subsection letter and a roman numeral ("(i)", "(v)", "(x)")."""
    if d.isdigit():
        return 2
    levels = [lv for lv, _ in path]
    if d.islower():
        roman, letter = bool(_ROMAN_LOWER.match(d)), _is_letter(d)
        if roman and letter:
            # what came just before decides first: "(hh)" -> "(ii)" is the next subsection, "(i)" -> "(ii)" the next clause
            last = last or {}
            prev_roman = _ROMANS[_ROMANS.index(d) - 1] if d in _ROMANS[1:] else None
            follows_letter = bool(last.get(1)) and _is_letter(last[1]) and _next_letter(last[1]) == d
            follows_roman = (prev_roman is not None and last.get(4) == prev_roman) or (d == "i" and 3 in levels)
            if follows_letter != follows_roman:
                return 1 if follows_letter else 4
            nxt_roman = _ROMANS[_ROMANS.index(d) + 1] if d in _ROMANS[:-1] else None
            nxt_letter = _next_letter(d)
            for a in ahead:
                if a == nxt_roman:
                    return 4
                if a == nxt_letter:
                    return 1
            return 4 if 3 in levels else 1
        return 4 if roman else 1
    if _ROMAN_UPPER.match(d) and 4 in levels:
        return 5
    return 3


def parse_section(text: str) -> list[StatuteRow]:
    fdca = usc = url = heading = None
    rows: list[StatuteRow] = []
    path: list[tuple[int, str]] = []
    started = False
    pending_caption: dict[str, str] = {}
    last: dict[int, str] = {}
    lines = [raw.strip() for raw in text.splitlines() if raw.strip()]
    firsts = [m.group("d") if (m := _DESIG.match(line)) else None for line in lines]
    for i, line in enumerate(lines):
        if m := _SOURCE.match(line):
            url = m.group("url"); continue
        if m := _LABEL.match(line):
            fdca, usc = m.group("fdca"), m.group("usc"); continue
        if not started:
            if m := _HEADING.match(line):
                heading = m.group("heading").strip().rstrip(".")
                started = True
            continue
        if _CREDIT.match(line) or line in _END_MARKERS:
            break
        desigs = []
        rest = line
        while m := _DESIG.match(rest):
            desigs.append(m.group("d")); rest = rest[m.end():].lstrip()
        if desigs:
            ahead = [f for f in firsts[i + 1:] if f]
            for d in desigs:
                lv = _kind(d, path, ahead, last)
                path = [p for p in path if p[0] < lv] + [(lv, d)]
                last[lv] = d
                for deeper in [k for k in last if k > lv]:
                    del last[deeper]
        p = "".join(f"({d})" for _, d in path)
        # a designated line with a short caption and no sentence is a heading of what follows ("(b) Submission of reports")
        # list items ending ", or" / ", and" / "or" are text, not captions (code review: 201(bb)(1) was lost)
        if (desigs and rest and not re.search(r"[.;:—-]$|[.;:]\s", rest) and len(rest) < 120 and not rest.endswith(",")
                and not re.search(r"(?:,|\b(?:or|and))$", rest)):
            pending_caption[p] = rest
            continue
        caption = pending_caption.get(p, "")
        top = f"({path[0][1]})" if path else ""
        rows.append(StatuteRow(fdca_section=fdca or "", usc_section=usc or "", paragraph_path=p if desigs or path else "",
                               ordinal=len(rows), heading=heading or "", paragraph_heading=caption,
                               body_text=line, source_url=url or "", top_caption=pending_caption.get(top, "")))
    if not (fdca and usc and heading):
        raise ValueError("not a fetched U.S. Code section file (missing LABEL, SOURCE or § heading line)")
    return rows


def parse_file(path: str | Path) -> list[StatuteRow]:
    return parse_section(Path(path).read_text(encoding="utf-8"))
