"""Deterministic extraction of every CFR reference in a text (Stage 1).

This module answers one question: *what did the user ask for?* It finds all
CFR references in a question, in the order they appear, normalises them to
one canonical form, expands ranges into explicit provisions and resolves
abbreviated continuations ("820.10(b)(1), (b)(2) and (4)").

It does not consult the database, so "21 CFR 820.999" parses like any other
reference; whether a provision exists is decided by later stages. No model
is involved: everything here is regular expressions and small, testable
rules, so the result is reproducible and fast.

Recognised forms (case-insensitive, whitespace-tolerant):

    21 CFR 820.10(b)(1)      21 C.F.R. § 820.10       21 CFR part 820
    § 820.10(b)(1)           section 820.10(b)        part 820
    820.10(b)(1)             820.10                   (bare; see below)
    820.10(b)(1) through (b)(4)      820.10(b)(1)-(b)(4)      ... to (b)(4)
    820.10(b)(1), (b)(2), and (b)(4)       820.10(b)(1) and (2)
    § 820.10(b)(1) through § 820.10(b)(4)  21 CFR 820.10(b)(1) and 21 CFR 820.10(b)(4)

Bare numbers are the risky form. A dotted number with paragraph tokens
("820.10(b)(1)") is structural enough to accept. A dotted number alone
("820.10") is accepted unless a measurement, currency, version, pH or
standards-clause cue sits next to it ("2.5 mg", "$12.50", "version 3.1",
"pH 6.5", "clause 7.5"); a cue on one end of a "6.5 to 7.5" pair excludes
both ends. The mention records which form matched (`form`), so later stages
can weigh a bare section-only mention more cautiously than an explicit one.

Public surface:
    CfrReference               the normalised reference (frozen)
    scan_references(text)      full result with mentions, ranges and notes
    parse_cfr_references(text) just the ordered, de-duplicated references
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TITLE = "21"

# Upper bound on how many provisions one range may expand to. A range larger
# than this is kept as its two endpoints and noted; nothing is silently lost.
MAX_RANGE_EXPANSION = 50

# how a mention was recognised
FORM_CFR = "cfr"                    # "21 CFR 820.10(b)(1)", "C.F.R. § 820.10", "CFR part 820"
FORM_SYMBOL = "symbol"              # "§ 820.10(b)(1)"
FORM_SECTION_WORD = "section_word"  # "section 820.10(b)"
FORM_PART_WORD = "part_word"        # "part 820"
FORM_BARE = "bare"                  # "820.10(b)(1)", "820.10"
FORM_CONTINUATION = "continuation"  # "(b)(2)" inheriting the previous section
EXPLICIT_FORMS = (FORM_CFR, FORM_SYMBOL, FORM_SECTION_WORD, FORM_PART_WORD, FORM_BARE)

# where a resolved reference came from
ORIGIN_EXPLICIT = "explicit"
ORIGIN_CONTINUATION = "continuation"
ORIGIN_RANGE = "range_expansion"


# ------------------------------------------------------------------ model


@dataclass(frozen=True)
class CfrReference:
    """One normalised CFR reference. `raw` keeps the text it was parsed from."""

    title: str
    part: str
    section: str | None  # full section number, e.g. "820.10"; None for part-level
    paragraph_path: str  # "" or "(b)(1)"
    raw: str

    @property
    def level(self) -> str:
        if self.section is None:
            return "part"
        return "paragraph" if self.paragraph_path else "section"

    @property
    def label(self) -> str:
        if self.section is None:
            return f"{self.title} CFR part {self.part}"
        return f"{self.title} CFR {self.section}{self.paragraph_path}"

    @property
    def canonical(self) -> str:
        """The canonical identifier: equal for every textual form of the same provision."""
        return self.label

    @property
    def key(self) -> tuple[str, str, str | None, str]:
        """Hashable identity used for de-duplication: (title, part, section, paragraph)."""
        return (self.title, self.part, self.section, self.paragraph_path)

    @property
    def paragraph_tokens(self) -> tuple[str, ...]:
        return tuple(_PARA_TOKEN_RE.findall(self.paragraph_path))

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "part": self.part,
            "section": self.section,
            "paragraph_path": self.paragraph_path,
            "level": self.level,
            "canonical": self.canonical,
            "raw": self.raw,
        }


@dataclass(frozen=True)
class Mention:
    """One place in the text where a reference was recognised."""

    index: int
    form: str
    start: int
    end: int
    text: str
    reference: CfrReference

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "form": self.form, "start": self.start, "end": self.end,
                "text": self.text, "canonical": self.reference.canonical}


@dataclass(frozen=True)
class RangeSpan:
    """Two consecutive mentions joined by a range connector, and what became of them."""

    start_mention: int
    end_mention: int
    connector: str
    expanded: bool
    count: int          # references the range stands for (2 when not expanded)
    reason: str         # "expanded" or why it was not

    def to_dict(self) -> dict[str, Any]:
        return {"start_mention": self.start_mention, "end_mention": self.end_mention, "connector": self.connector,
                "expanded": self.expanded, "count": self.count, "reason": self.reason}


@dataclass(frozen=True)
class ResolvedReference:
    """A reference in its final, de-duplicated position, with its provenance."""

    reference: CfrReference
    origin: str          # ORIGIN_EXPLICIT | ORIGIN_CONTINUATION | ORIGIN_RANGE
    mention: int         # index of the mention it came from (the range start for expansions)

    def to_dict(self) -> dict[str, Any]:
        return {"canonical": self.reference.canonical, "origin": self.origin, "mention": self.mention,
                "reference": self.reference.to_dict()}


@dataclass(frozen=True)
class ReferenceScan:
    """Everything the scanner found, for callers and for debugging."""

    text: str                                   # whitespace-normalised input the spans refer to
    mentions: tuple[Mention, ...]
    ranges: tuple[RangeSpan, ...]
    resolved: tuple[ResolvedReference, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def references(self) -> tuple[CfrReference, ...]:
        return tuple(r.reference for r in self.resolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "mentions": [m.to_dict() for m in self.mentions],
            "ranges": [r.to_dict() for r in self.ranges],
            "references": [r.to_dict() for r in self.resolved],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------- patterns

_PARA_TOKEN = r"\(\s*[A-Za-z0-9]{1,4}\s*\)"
_PARAS = rf"(?P<paras>(?:\s*{_PARA_TOKEN})*)"
_SECTION = r"(?P<part>\d{1,4})(?:\.(?P<section>\d{1,4}[a-z]?))?"

# 1) "21 CFR 820.10(b)", "CFR § 820.10", "21 C.F.R. part 820", "21 CFR Part 820"
_CFR_RE = re.compile(
    r"(?:(?P<title>\d{1,2})\s*)?C\.?\s*F\.?\s*R\.?\s*(?:§+\s*)?(?:part\s+)?(?:section\s+)?" + _SECTION + _PARAS,
    re.IGNORECASE,
)
# 2) "§ 820.10(b)(1)" / "§§ 820.10"
_SYMBOL_RE = re.compile(r"§+\s*" + _SECTION + _PARAS)
# 3) "section 820.10(b)"
_SECTION_WORD_RE = re.compile(r"\bsection\s+(?P<part>\d{1,4})\.(?P<section>\d{1,4}[a-z]?)" + _PARAS, re.IGNORECASE)
# 4) "part 820"
_PART_WORD_RE = re.compile(r"\bpart\s+(?P<part>\d{1,4})\b(?!\.\d)", re.IGNORECASE)
# 5) bare "820.10(b)(1)" / "820.10": not glued to other digits, dots, letters or a currency sign
_BARE_RE = re.compile(r"(?<![\w.$€£])(?P<part>\d{1,4})\.(?P<section>\d{1,4}[a-z]?)(?![\d.])" + _PARAS)
# 6) standalone paragraph tokens "(b)(2)" that may continue an earlier reference
_FRAGMENT_RE = re.compile(rf"(?<![\w)])(?P<paras>{_PARA_TOKEN}(?:\s*{_PARA_TOKEN})*)")

_EXPLICIT_PATTERNS = ((FORM_CFR, _CFR_RE), (FORM_SYMBOL, _SYMBOL_RE), (FORM_SECTION_WORD, _SECTION_WORD_RE), (FORM_PART_WORD, _PART_WORD_RE))

_PARA_TOKEN_RE = re.compile(r"\(\s*([A-Za-z0-9]{1,4})\s*\)")

# Cues that mark a bare dotted number as something other than a CFR section.
# Before: "pH 6.5", "version 3.1", "clause 7.5", "Fig. 2.1", "$12.50", "part 2.5".
_BEFORE_CUE_RE = re.compile(
    r"(?:^|[\s(\[])(?:ph|version|ver|v|rev|revision|release|build|clause|step|phase|stage|figure|fig|table|item|"
    r"chapter|iso|iec|astm|ansi|usp|ich|no|number|#|\$|€|£|part|parts)\.?\s*$",
    re.IGNORECASE,
)
# After: "2.5 mg", "4.2%", "1.5 fold", "2.5 hours". Short ambiguous words ("in", "m", "g") are deliberately absent.
_AFTER_CUE_RE = re.compile(
    r"^\s*(?:%|percent|percentage|mg|mcg|µg|ug|kg|ml|mm|cm|km|ppm|ppb|hours?|hrs?|days?|weeks?|months?|years?|"
    r"minutes?|mins?|seconds?|secs?|million|billion|thousand|degrees?|°|fold|times|units?|lbs?|oz|inch|inches)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)

# Text allowed between two mentions of one list/range ("820.10(b)(1), (b)(2), and (b)(4)").
_LIST_GAP_RE = re.compile(r"^(?:[\s,;]*(?:(?:and|or|through|thru|to|&)[\s,;]+)?|\s*[-–—−]\s*)$", re.IGNORECASE)
# Text between two mentions that makes them a range.
_RANGE_GAP_RE = re.compile(r"^\s*(?P<connector>through|thru|to|[-–—−])\s*$", re.IGNORECASE)

_ROMAN_RE = re.compile(r"^(?=[ivxlcdm])m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")
_ROMAN_VALUES = (("m", 1000), ("cm", 900), ("d", 500), ("cd", 400), ("c", 100), ("xc", 90), ("l", 50), ("xl", 40),
                 ("x", 10), ("ix", 9), ("v", 5), ("iv", 4), ("i", 1))


# ------------------------------------------------------------- utilities


def normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def normalise_paragraphs(paras: str | None) -> str:
    if not paras:
        return ""
    return "".join(f"({token})" for token in _PARA_TOKEN_RE.findall(paras))


def _build(m: re.Match, *, title: str | None, raw: str | None = None) -> CfrReference | None:
    part = m.group("part")
    section = m.groupdict().get("section")
    if part is None or part.startswith("0"):
        return None
    full_section = f"{part}.{section}" if section else None
    paras = normalise_paragraphs(m.groupdict().get("paras"))
    if full_section is None and paras:
        return None  # "part 820(b)" is not meaningful
    return CfrReference(title=title or DEFAULT_TITLE, part=part, section=full_section, paragraph_path=paras,
                        raw=(raw if raw is not None else m.group(0)).strip())


def _roman_to_int(s: str) -> int:
    total, i, s = 0, 0, s.lower()
    for sym, val in _ROMAN_VALUES:
        while s.startswith(sym, i):
            total += val
            i += len(sym)
    return total


def _int_to_roman(n: int) -> str:
    out = []
    for sym, val in _ROMAN_VALUES:
        while n >= val:
            out.append(sym)
            n -= val
    return "".join(out)


def token_kind(token: str, depth: int) -> str:
    """Classify a paragraph token by its text and its depth (1-based).

    eCFR nests (a) → (1) → (i) → (A) → (1) → (i), so the depth decides
    whether an ambiguous token such as "(i)" is the letter i or roman one.
    """
    if token.isdigit():
        return "digit"
    expected = ("letter", "digit", "roman")[(depth - 1) % 3]
    upper = token.isupper()
    if expected == "roman" and _ROMAN_RE.match(token.lower()):
        return "roman_upper" if upper else "roman"
    if len(token) == 1 and token.isalpha():
        return "letter_upper" if upper else "letter"
    if _ROMAN_RE.match(token.lower()):
        return "roman_upper" if upper else "roman"
    return "other"


def _token_ordinal(token: str, kind: str) -> int | None:
    if kind == "digit":
        return int(token)
    if kind in ("letter", "letter_upper"):
        return ord(token.lower()) - ord("a") + 1
    if kind in ("roman", "roman_upper"):
        return _roman_to_int(token)
    return None


def _ordinal_token(n: int, kind: str) -> str | None:
    if kind == "digit":
        return str(n)
    if kind in ("letter", "letter_upper"):
        if not 1 <= n <= 26:
            return None
        c = chr(ord("a") + n - 1)
        return c.upper() if kind == "letter_upper" else c
    if kind in ("roman", "roman_upper"):
        r = _int_to_roman(n)
        return r.upper() if kind == "roman_upper" else r
    return None


# ---------------------------------------------------------------- scanning


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(s < end and start < e for s, e in spans)


def _explicit_mentions(text: str) -> list[tuple[int, int, str, CfrReference]]:
    found: list[tuple[int, int, str, CfrReference]] = []
    for form, pattern in _EXPLICIT_PATTERNS:
        for m in pattern.finditer(text):
            ref = _build(m, title=m.groupdict().get("title"))
            if ref is not None:
                found.append((m.start(), m.end(), form, ref))
    # earliest start wins, then the longest match ("21 CFR § 820.10" over "§ 820.10")
    found.sort(key=lambda t: (t[0], -t[1]))
    kept: list[tuple[int, int, str, CfrReference]] = []
    for cand in found:
        if not _overlaps(cand[0], cand[1], [(k[0], k[1]) for k in kept]):
            kept.append(cand)
    return kept


def _bare_mentions(text: str, taken: list[tuple[int, int]]) -> list[tuple[int, int, str, CfrReference]]:
    """Bare dotted numbers, minus those a cue marks as measurements and the like."""
    candidates: list[tuple[int, int, CfrReference, bool]] = []  # (start, end, ref, excluded)
    for m in _BARE_RE.finditer(text):
        if _overlaps(m.start(), m.end(), taken):
            continue
        ref = _build(m, title=None)
        if ref is None:
            continue
        has_paras = bool(ref.paragraph_path)
        before, after = text[: m.start()], text[m.end():]
        excluded = False
        if not has_paras:
            excluded = bool(_BEFORE_CUE_RE.search(before)) or bool(_AFTER_CUE_RE.match(after))
        elif _BEFORE_CUE_RE.search(before) and not before.rstrip().lower().endswith(("part", "parts")):
            excluded = True  # "clause 7.5(a)" is a standards clause; "part 820.30(b)" is loose CFR usage
        candidates.append((m.start(), m.end(), ref, excluded))
    # a measurement range excludes both ends: "pH 6.5 to 7.5", "between 2.5 and 3.5 mg"
    changed = True
    while changed:
        changed = False
        for i in range(len(candidates) - 1):
            a, b = candidates[i], candidates[i + 1]
            if a[3] != b[3] and _LIST_GAP_RE.match(text[a[1]:b[0]]) and text[a[1]:b[0]].strip():
                if not a[2].paragraph_path and not b[2].paragraph_path:
                    candidates[i] = (a[0], a[1], a[2], True)
                    candidates[i + 1] = (b[0], b[1], b[2], True)
                    changed = True
    return [(s, e, FORM_BARE, ref) for s, e, ref, excluded in candidates if not excluded]


def _inherit_path(previous: CfrReference, fragment_tokens: tuple[str, ...]) -> str:
    """Resolve "(2)" after "820.10(b)(1)" to "(b)(2)"; keep "(c)" absolute."""
    prev_tokens = previous.paragraph_tokens
    depth_frag, depth_prev = len(fragment_tokens), len(prev_tokens)
    if 0 < depth_frag < depth_prev:
        position = depth_prev - depth_frag  # 0-based index in prev_tokens where the fragment starts
        if token_kind(fragment_tokens[0], position + 1) == token_kind(prev_tokens[position], position + 1):
            return "".join(f"({t})" for t in prev_tokens[:position] + fragment_tokens)
    return "".join(f"({t})" for t in fragment_tokens)


def _continuation_mentions(text: str, mentions: list[tuple[int, int, str, CfrReference]]) -> list[tuple[int, int, str, CfrReference]]:
    """Paragraph-only fragments that continue the nearest earlier reference."""
    out: list[tuple[int, int, str, CfrReference]] = []
    known = sorted(mentions, key=lambda t: t[0])  # explicit + bare + continuations found so far
    for m in _FRAGMENT_RE.finditer(text):
        if _overlaps(m.start(), m.end(), [(s, e) for s, e, _, _ in known]):
            continue
        previous = None
        for cand in known:
            if cand[1] <= m.start() and (previous is None or cand[1] > previous[1]):
                previous = cand
        if previous is None or previous[3].section is None:
            continue  # nothing to continue, or a part-level reference has no paragraphs
        if not _LIST_GAP_RE.match(text[previous[1]:m.start()]):
            continue  # ordinary words in between: "(a)" is not a citation
        tokens = tuple(_PARA_TOKEN_RE.findall(m.group("paras")))
        ref = CfrReference(title=previous[3].title, part=previous[3].part, section=previous[3].section,
                           paragraph_path=_inherit_path(previous[3], tokens), raw=m.group(0).strip())
        item = (m.start(), m.end(), FORM_CONTINUATION, ref)
        out.append(item)
        known = sorted(known + [item], key=lambda t: t[0])
    return out


def _expand_range(start: CfrReference, end: CfrReference, raw: str) -> tuple[list[CfrReference], str]:
    """Return the provisions strictly between start and end, or [] with a reason."""
    if start.title != end.title or start.section is None or start.section != end.section:
        return [], "section-level or cross-section ranges are not expanded without the database"
    a, b = start.paragraph_tokens, end.paragraph_tokens
    if not a or not b:
        return [], "range endpoints must be paragraphs"
    if len(a) != len(b) or a[:-1] != b[:-1]:
        return [], "range endpoints are at different depths or under different parents"
    depth = len(a)
    kind_a, kind_b = token_kind(a[-1], depth), token_kind(b[-1], depth)
    if kind_a != kind_b or kind_a == "other":
        return [], "range endpoints are not the same kind of paragraph token"
    lo, hi = _token_ordinal(a[-1], kind_a), _token_ordinal(b[-1], kind_b)
    if lo is None or hi is None or hi <= lo:
        return [], "range end does not follow its start"
    if hi - lo + 1 > MAX_RANGE_EXPANSION:
        return [], f"range spans {hi - lo + 1} provisions, above the limit of {MAX_RANGE_EXPANSION}"
    prefix = "".join(f"({t})" for t in a[:-1])
    inner: list[CfrReference] = []
    for n in range(lo + 1, hi):
        tok = _ordinal_token(n, kind_a)
        if tok is None:
            return [], "range cannot be enumerated"
        inner.append(CfrReference(title=start.title, part=start.part, section=start.section,
                                  paragraph_path=f"{prefix}({tok})", raw=raw))
    return inner, "expanded"


def scan_references(text: str) -> ReferenceScan:
    """Find every CFR reference in `text`, in order, with ranges expanded."""
    norm = normalise_text(text)
    if not norm:
        return ReferenceScan(norm, (), (), ())

    explicit = _explicit_mentions(norm)
    bare = _bare_mentions(norm, [(s, e) for s, e, _, _ in explicit])
    base = sorted(explicit + bare, key=lambda t: t[0])
    continuation = _continuation_mentions(norm, base)
    ordered = sorted(base + continuation, key=lambda t: t[0])
    mentions = tuple(Mention(i, form, s, e, norm[s:e], ref) for i, (s, e, form, ref) in enumerate(ordered))

    # ranges between consecutive mentions
    notes: list[str] = []
    ranges: list[RangeSpan] = []
    expansions: dict[int, list[CfrReference]] = {}  # start mention index -> inner references
    for i in range(len(mentions) - 1):
        a, b = mentions[i], mentions[i + 1]
        gap = _RANGE_GAP_RE.match(norm[a.end:b.start])
        if not gap:
            continue
        raw = norm[a.start:b.end]
        inner, reason = _expand_range(a.reference, b.reference, raw)
        expanded = reason == "expanded"
        if expanded:
            expansions[i] = inner
        else:
            notes.append(f"range {a.reference.canonical} {gap.group('connector')} {b.reference.canonical} not expanded: {reason}")
        ranges.append(RangeSpan(i, i + 1, gap.group("connector"), expanded, len(inner) + 2 if expanded else 2, reason))

    # ordered, de-duplicated references with provenance
    resolved: list[ResolvedReference] = []
    seen: set[tuple[str, str, str | None, str]] = set()

    def add(ref: CfrReference, origin: str, mention_index: int) -> None:
        if ref.key in seen:
            notes.append(f"duplicate mention of {ref.canonical} ignored")
            return
        seen.add(ref.key)
        resolved.append(ResolvedReference(ref, origin, mention_index))

    for m in mentions:
        origin = ORIGIN_CONTINUATION if m.form == FORM_CONTINUATION else ORIGIN_EXPLICIT
        add(m.reference, origin, m.index)
        for inner in expansions.get(m.index, ()):
            add(inner, ORIGIN_RANGE, m.index)

    return ReferenceScan(norm, mentions, tuple(ranges), tuple(resolved), tuple(notes))


def parse_cfr_references(text: str) -> tuple[CfrReference, ...]:
    """Every CFR reference in `text`, in textual order, ranges expanded, duplicates removed."""
    return scan_references(text).references
