"""Point a citation marker at the source that states, word for word, what it is attached to.

The model numbers its citations by SOURCE, but with a provision split into
paragraph-level sources it was measured to cite by PARAGRAPH instead: "the
nature and details of the complaint [5]" for 21 CFR 820.35(a)(5), which is
SOURCE 7 - SOURCE 5 is (a)(3), the UDI. Or one marker at the end of three
quoted paragraphs, so the 211.25(c) sentence carried 211.25(a)'s number. The
words are right and verbatim; only the number is wrong, and the reader is sent
to the wrong paragraph.

The repair is decided by identity alone, never by similarity:

    the text a marker is attached to - the list item or sentence ending at it -
    ends in a run of at least MIN_WORDS words that is MIN_SHARE of that text and
    appears verbatim (case, punctuation and spacing aside) in exactly ONE
    supplied source, and in none of the sources the marker cites.

Then, and only then, the marker group is replaced by that source's number. A
marker whose cited source contains the text, a paraphrase, a run found in two
sources, or a marker naming a source that does not exist is left exactly as it
is for validation and the evaluator to judge. Nothing is added or removed but
the number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

MIN_WORDS = 5          # a shorter run ("the name of the device") is not distinctive enough to move a citation
MIN_SHARE = 0.6        # the run must be most of what the marker is attached to, not a coincidental tail

_MARK_GROUP_RE = re.compile(r"(?:[ \t]*\[\d{1,3}\])+")
_MARK_RE = re.compile(r"\[(\d{1,3})\]")
# where the text a marker is attached to begins: a previous marker group (handled
# by the caller), a line break, or a sentence end followed by a new sentence or item
_PIECE_BREAK_RE = re.compile(r"\n+|(?<=[.!?;:])\s+(?=[A-Z(\-•*])")
_WORD_RE = re.compile(r"[a-z0-9§]+(?:[.'\-][a-z0-9]+)*")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


@dataclass(frozen=True)
class Repoint:
    """One marker group moved: from the cited numbers to the source that states the text."""

    old: tuple[int, ...]
    new: int
    text: str

    def to_dict(self) -> dict:
        return {"from": list(self.old), "to": self.new, "text": self.text}


def repoint_citations(answer: str, sources: Iterable[tuple[int, str]]) -> tuple[str, list[Repoint]]:
    """(answer with misnumbered markers corrected, the corrections made)."""
    texts = {int(i): " " + " ".join(_words(t)) + " " for i, t in sources}
    if not answer or len(texts) < 2:
        return answer, []
    out, changes, cursor, previous_end = [], [], 0, 0
    for m in _MARK_GROUP_RE.finditer(answer):
        cited = tuple(int(n) for n in _MARK_RE.findall(m.group(0)))
        piece = _PIECE_BREAK_RE.split(answer[previous_end:m.start()])[-1]
        previous_end = m.end()
        target = _target(piece, cited, texts)
        if target is None:
            continue
        out.append(answer[cursor:m.start()])
        out.append(re.match(r"[ \t]*", m.group(0)).group(0) + f"[{target}]")
        cursor = m.end()
        changes.append(Repoint(cited, target, " ".join(piece.split())[:160]))
    out.append(answer[cursor:])
    return "".join(out), changes


def _target(piece: str, cited: tuple[int, ...], texts: dict[int, str]) -> int | None:
    if not cited or any(n not in texts for n in cited):
        return None                                   # a nonexistent source is validation's finding, not ours
    words = _words(piece)
    if len(words) < MIN_WORDS:
        return None
    for k in range(len(words), MIN_WORDS - 1, -1):    # the longest run ending at the marker that some source states
        run = " " + " ".join(words[-k:]) + " "
        holders = [i for i, t in texts.items() if run in t]
        if not holders:
            continue
        if k < MIN_SHARE * len(words) or any(n in holders for n in cited) or len(holders) != 1:
            return None
        return holders[0]
    return None
