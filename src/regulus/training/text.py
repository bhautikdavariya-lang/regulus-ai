"""Deterministic text helpers for question/answer construction. No model, no
database, no randomness: the same input always yields the same output."""

from __future__ import annotations

import hashlib
import re

_WS_RE = re.compile(r"\s+")
_LABEL_RE = re.compile(r"^\(\s*[A-Za-z0-9]{1,4}\s*\)\s*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“])")
_IDENTIFIER_RE = re.compile(r"[A-Za-z]*\d[\w.\-()]*")
_FOOTNOTE_RE = re.compile(r"[a-z]\d{1,3}(?![\w.\-])")
_WORD_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
_TABLE_NOISE_RE = re.compile(r"[│┃|]{2,}|\.{6,}|_{5,}")

# A paragraph "lead-in" is the italic caption eCFR paragraphs often open with:
#   "(c) Design and development. Manufacturers of class II ..."
# It is short, has no verb-like connective, and is followed by a sentence.
_LEADIN_RE = re.compile(r"^(?P<lead>[A-Z][A-Za-z0-9 ,'’\-/()]{1,90}?)\.\s+(?=[A-Z(\"“])")
_LEADIN_STOP_STARTS = (
    "each ", "the ", "a ", "an ", "no ", "this ", "these ", "all ", "any ", "if ", "for ", "when ", "where ",
    "in ", "such ", "upon ", "except ", "under ", "before ", "after ", "at ", "on ", "as ", "it ", "there ",
    "you ", "we ", "fda ", "manufacturers ", "sponsors ", "applicants ", "persons ", "records ", "within ",
)
_LEADIN_STOP_WORDS = (" shall ", " must ", " may ", " means ", " is ", " are ", " will ", " should ", " includes ", " has ", " have ", " does ", " do ")


def clean(text: str | None) -> str:
    """Collapse whitespace (including non-breaking spaces) to single spaces."""
    return _WS_RE.sub(" ", (text or "").replace("\u00a0", " ")).strip()


def strip_label(text: str) -> str:
    """Remove the leading paragraph label(s): '(b)(1) text' -> 'text'."""
    out = clean(text)
    for _ in range(3):
        stripped = _LABEL_RE.sub("", out, count=1)
        if stripped == out:
            break
        out = stripped
    return out


def leadin(text: str) -> tuple[str | None, str]:
    """Split an eCFR paragraph into (lead-in caption, remainder).

    Returns (None, text) when the paragraph has no recognisable caption.
    """
    body = strip_label(text)
    m = _LEADIN_RE.match(body)
    if not m:
        return None, body
    lead = m.group("lead").strip()
    low = lead.lower() + " "
    if len(lead.split()) > 8 or low.startswith(_LEADIN_STOP_STARTS) or any(w in low for w in _LEADIN_STOP_WORDS):
        return None, body
    rest = body[m.end():].strip()
    if not rest:
        return None, body
    return lead, rest


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(clean(text)) if s.strip()]


def first_sentence(text: str, max_chars: int = 400) -> str | None:
    for s in sentences(text):
        if 20 <= len(s) <= max_chars:
            return s
        return None
    return None


def heading_topic(heading: str | None) -> str | None:
    """'Responsibilities of quality control unit.' -> 'responsibilities of quality control unit'.
    Question-style headings ('What records must I keep?') make no usable topic."""
    h = clean(heading).rstrip(".").strip()
    if not h or "?" in h or len(h) > 140:
        return None
    if h.isupper():
        h = h.lower()
    return h[0].lower() + h[1:] if len(h) > 1 and not h[:2].isupper() else h


def is_clean_paragraph(text: str, min_chars: int, max_chars: int) -> bool:
    """Whole, citable prose: within bounds, ends a sentence, not a list intro,
    not a reserved stub, no table remnants."""
    t = clean(text)
    if not (min_chars <= len(t) <= max_chars):
        return False
    if "[reserved]" in t.lower() or _TABLE_NOISE_RE.search(t):
        return False
    if t.endswith((":", ";", ",", "—", "-", "and", "or")):
        return False
    body = strip_label(t)
    return bool(body) and body[-1] in ".)\"”" and any(c.isalpha() for c in body)


def is_list_intro(text: str) -> bool:
    return clean(text).endswith(":")


def normalise_question(text: str) -> str:
    """Lower-case word form used for duplicate detection and benchmark exclusion."""
    return " ".join(_WORD_RE.findall(clean(text).lower()))


def identifiers(text: str) -> frozenset[str]:
    """Tokens that carry a number: '820.10', 'part 11' -> '11', 'FDA-2016-D-2565', '510(k)'."""
    return frozenset(t.lower().strip(".") for t in _IDENTIFIER_RE.findall(clean(text)))


def has_footnote_artifact(text: str) -> bool:
    """'drugs2' / 'technology12': a footnote number glued to a word by PDF extraction."""
    return bool(_FOOTNOTE_RE.search(text))


def word_set(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(clean(text).lower()))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def stable_hash(*parts: str) -> str:
    """SHA-256 over the parts joined with a separator that cannot occur in them."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def pick(options: list[str] | tuple[str, ...], *key: str) -> str:
    """Deterministically choose one option from a key (used for template variety)."""
    if not options:
        raise ValueError("no options")
    return options[int(stable_hash(*key)[:8], 16) % len(options)]


def quote(text: str) -> str:
    return '"' + clean(text).replace('"', "'") + '"'


def strip_trailing_period(text: str) -> str:
    return clean(text).rstrip(".").strip()


def find_sentence_with(text: str, needle: str, min_chars: int = 40, max_chars: int = 500) -> str | None:
    """First sentence of `text` containing `needle`, if it is a clean sentence."""
    for s in sentences(text):
        if needle in s and min_chars <= len(s) <= max_chars and "http" not in s and not _TABLE_NOISE_RE.search(s):
            return s
    return None
