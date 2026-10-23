"""Repetition detection on text (torch-free; used by generation, validation and the pipeline).

Sentences are compared NORMALISED: citation markers ("[7]", "SOURCE 7"), case, whitespace and
trailing punctuation are removed, so one sentence repeated with an incrementing citation number
is recognised as the same sentence (the 21 CFR 830.20 loop, Stage 8 repetition fix).
"""

from __future__ import annotations

import re
from collections import Counter

from regulus.evaluation.grounding_eval import _ABBREVIATIONS, split_sentences

SENTENCE_REPEATS = 3        # the validator's threshold (rag.validation._DEGENERATE_SENTENCE_REPEATS)
MIN_SENTENCE_CHARS = 20     # the validator's minimum sentence length

_MARKS = re.compile(r"\[\s*\d{1,3}\s*\]|\*{0,2}\bsources?\s+\d{1,3}\b\*{0,2}", re.I)


def _ends_on_abbreviation(piece: str) -> bool:
    """True when a split piece ends on an abbreviation or initial ("FD&C Green No.", "the U.S.", "J."), whose period
    does not end the sentence: the same rule as split_sentences."""
    words = piece.rstrip().split()
    last = words[-1].rstrip(".").lower() if words else ""
    return last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha())


def _merge_abbreviations(pieces: list[str]) -> list[str]:
    """`pieces` alternate sentence, separator, sentence, ... (re.split with one capturing group). A sentence that
    ends on an abbreviation is joined with its separator and the next sentence when the separator is inline
    (not a line break), so "The use of FD&C Green No. 3 in a blush" stays one sentence."""
    out = list(pieces)
    i = 0
    while i + 2 < len(out):
        if "\n" not in out[i + 1] and _ends_on_abbreviation(out[i]) and not re.search(r"\[\s*\d", out[i + 1]):
            out[i:i + 3] = [out[i] + out[i + 1] + out[i + 2]]
            continue
        i += 2
    return out


def normalise_sentence(sentence: str) -> str:
    s = _MARKS.sub(" ", sentence or "").lower()
    s = re.sub(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+", "", s)  # a list bullet is not part of the sentence
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(" .;:,")


def repeated_sentence(text: str) -> tuple[str, int] | None:
    sentences = [normalise_sentence(s) for s in split_sentences(text)]
    sentences = [s for s in sentences if len(s) >= MIN_SENTENCE_CHARS]
    if not sentences:
        return None
    top, n = Counter(sentences).most_common(1)[0]
    return (top, n) if n >= SENTENCE_REPEATS else None


def trim_repetition(text: str) -> tuple[str, int]:
    """(text up to the end of the first occurrence of any sentence that is later repeated, number of
    repeated sentences removed). Unchanged text and 0 when nothing repeats."""
    pieces = _merge_abbreviations(re.split(r"(?<=[.!?])(\s+(?:\[\s*\d{1,3}\s*\]\s*)*)", text or ""))
    # pieces alternate: sentence, separator (which may carry a trailing citation marker), sentence, ...
    seen: set[str] = set()
    kept: list[str] = []
    removed = 0
    for i in range(0, len(pieces), 2):
        sentence = pieces[i]
        sep = pieces[i + 1] if i + 1 < len(pieces) else ""
        key = normalise_sentence(sentence)
        if len(key) >= MIN_SENTENCE_CHARS and key in seen:
            removed = sum(1 for j in range(i, len(pieces), 2) if normalise_sentence(pieces[j]))
            break
        if len(key) >= MIN_SENTENCE_CHARS:
            seen.add(key)
        kept.append(sentence + sep)
    return ("".join(kept).rstrip(), removed) if removed else (text, 0)



def _flat(text: str) -> str:
    """Text for a verbatim-passage test: no citation markers or quotation marks, lower case, single spaces."""
    s = re.sub(r"[\"'“”‘’]", "", _MARKS.sub(" ", text or "")).lower()
    return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", s)).strip()


def _quoted_runs(parts: list[str], drop: set[int], sources: list[str]) -> set[int]:
    """The repeated sentences that must stay because dropping them would cut a passage a source states verbatim: a
    run of repeats on one line, read together with the kept sentence it adjoins on that line, is source text (the
    740.17 caution quoted in full twice lost its middle three sentences the second time; holdout failure fix G)."""
    flat_sources = [_flat(s) for s in sources if s]
    keep: set[int] = set()
    i = 0
    while i < len(parts):
        if i not in drop:
            i += 2
            continue
        j = i
        while j + 2 < len(parts) and j + 2 in drop and "\n" not in parts[j + 1]:
            j += 2
        run = " ".join(parts[k] for k in range(i, j + 1, 2))
        before = parts[i - 2] if i >= 2 and i - 2 not in drop and "\n" not in parts[i - 1] else ""
        after = parts[j + 2] if j + 2 < len(parts) and j + 2 not in drop and "\n" not in parts[j + 1] else ""
        joined = [_flat(x) for x in ((before + " " + run) if before else "", (run + " " + after) if after else "") if x]
        if any(len(x) >= 2 * MIN_SENTENCE_CHARS and any(x in s for s in flat_sources) for x in joined):
            keep.update(range(i, j + 1, 2))
        i = j + 2
    return keep


def drop_duplicate_sentences(text: str, sources: list[str] | None = None) -> tuple[str, int]:
    """Remove every later copy of a sentence or list item that is IDENTICAL to an earlier one once citation
    markers, list bullets, case and spacing are ignored (>= 20 characters). Nothing is lost: the first copy
    stays. Near-identical sentences are NOT touched: measured in Stage 8, their overlap does not separate
    restatements (0.84) from distinct requirements worded alike (0.83). With `sources` (the supplied source texts),
    a copy that is part of a passage quoted verbatim from a source is kept, so no quotation loses sentences."""
    parts = _merge_abbreviations(re.split(r"((?<=[.!?])[ \t]+(?:\[\s*\d{1,3}\s*\][ \t]*)*|\n+)", text or ""))
    seen: set[str] = set()
    drop: set[int] = set()
    for i in range(0, len(parts), 2):
        key = normalise_sentence(parts[i])
        if len(key) >= MIN_SENTENCE_CHARS and key in seen:
            drop.add(i)
        elif len(key) >= MIN_SENTENCE_CHARS:
            seen.add(key)
    if drop and sources:
        drop -= _quoted_runs(parts, drop, sources)
    if not drop:
        return text, 0
    out: list[str] = []
    for i, part in enumerate(parts):
        if i in drop or (i % 2 == 1 and i - 1 in drop):   # a dropped sentence takes its following separator along
            continue
        out.append(part)
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip(), len(drop)
