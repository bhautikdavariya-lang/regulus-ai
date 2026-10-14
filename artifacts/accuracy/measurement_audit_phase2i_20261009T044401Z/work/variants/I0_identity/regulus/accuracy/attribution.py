"""Verbatim attribution of a claim to the source it is attributed to.

The one measurement this feature adds that the pipeline does not already make,
and the only kind of measurement that may decide substantive correctness here.

A claim is verbatim-attributed to a source when the claim's longest CONTIGUOUS
run of words that appears verbatim in that source covers most of the claim. The
contiguity is the point. Bag-of-words recall was measured over the 299 scored
acceptance rows at 85.5% false passes because word order carries negation,
applicability and attribution and a bag discards all three
(docs/STAGE_A_VALIDATOR_LIMITATION.md). A contiguous run cannot discard them:

    source  "The provisions of this part do not apply to manufacturers of
             components or parts of finished devices"
    answer  "Manufacturers of components are subject to this part"

    bag-of-words recall             ~1.00   -> scored a PASS (phase D1, H4 arm)
    longest contiguous verbatim run  3/8 = 0.38 -> NOT attributed

Normalisation is case, citation markers and punctuation only. No stemming, no
stop-word removal, no synonyms: each of those would re-introduce exactly the
blindness being avoided. Two thresholds are applied and both are reported with
every finding, so a reader can see what was required rather than trusting a
boolean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# A claim counts as verbatim-attributed when one contiguous run of its own words
# appears in the source and that run covers this share of the claim ...
ATTRIBUTION_MIN_COVERAGE = 0.8
# ... and is at least this many words long, so that a short fragment of a long
# sentence can never attribute the sentence.
ATTRIBUTION_MIN_RUN_WORDS = 6

MARK_RE = re.compile(r"(?<![A-Za-z0-9])\[(\d{1,2})\]")
_NON_WORD = re.compile(r"[^a-z0-9]+")

# A leading citation label or framing clause is how a grounded answer introduces
# the provision's own text ("21 CFR 820.10(b)(2) requires that ..."). It is the
# answer's own scaffolding, not a claim about content, so it is removed before
# the run is measured. Nothing inside the claim is removed.
_LEAD_PATTERNS = (
    re.compile(r"^\s*(?:under|pursuant to|according to|as (?:stated|set out) in|per)\s+[^,]{1,70},\s*", re.I),
    re.compile(r"^\s*(?:21\s*)?(?:c\.?f\.?r\.?)?\s*(?:§+\s*)?\d{1,4}\.\d{1,4}[a-z]?(?:\([A-Za-z0-9]{1,4}\))*\s*[:,—-]*\s*", re.I),
    re.compile(r"^\s*(?:21\s*CFR\s*)?part\s+\d{1,4}\s*[:,—-]*\s*", re.I),
    re.compile(r"^\s*(?:it|this|that|the)?\s*(?:provision|section|paragraph|regulation|rule)?\s*"
               r"(?:requires?|states?|provides?|specifies?|mandates?|says?|establishes?)\s+(?:that\s+)?", re.I),
)

ATTRIBUTED_EXACT = "verbatim_from_exact_source"       # the authoritative text of what the claim names
ATTRIBUTED_OTHER = "verbatim_from_other_source"       # verbatim, but not from the provision it names
UNATTRIBUTED = "not_verbatim_in_any_source"


def normalise(text: str) -> str:
    """Case, citation markers and punctuation only. Word order is preserved."""
    return " " + _NON_WORD.sub(" ", MARK_RE.sub(" ", (text or "")).lower()).strip() + " "


def words(text: str) -> list[str]:
    return normalise(text).split()


# Framing that introduces the proposition rather than stating it: "The scope of
# 21 CFR Part 11 is defined in section 11.1(a), which states that <proposition>",
# "This means that <proposition>", "In other words, <proposition>". Removed only
# when what precedes the connector names a provision and carries no obligation of
# its own - "Each manufacturer shall establish procedures, which require ..." keeps
# its main clause.
_FRAMING_RE = re.compile(
    r"^(?P<frame>.{0,160}?),?\s+which\s+(?:states?|requires?|provides?|specifies?|says?|establishes?|mandates?)"
    r"\s+(?:that\s+)?", re.I)
_FRAME_NAMES_RE = re.compile(r"\b(?:section|part|paragraph|regulation|provision|rule|guidance|cfr)\b|\d+\.\d+", re.I)
_FRAME_MODAL_RE = re.compile(r"\b(?:must|shall|should|may|is required|are required)\b", re.I)
_DISCOURSE_LEADS = (
    re.compile(r"^\s*(?:this|that|which)\s+means\s+(?:that\s+)?", re.I),
    re.compile(r"^\s*meaning\s+(?:that\s+)?", re.I),
    re.compile(r"^\s*in\s+other\s+words,?\s*", re.I),
)


def strip_framing(text: str) -> str:
    """The proposition without a framing lead-in (see _FRAMING_RE)."""
    out = text
    for pattern in _DISCOURSE_LEADS:
        out = pattern.sub("", out, count=1)
    m = _FRAMING_RE.match(out)
    if m and _FRAME_NAMES_RE.search(m.group("frame")) and not _FRAME_MODAL_RE.search(m.group("frame")):
        out = out[m.end():]
    return out


def strip_lead(sentence: str) -> str:
    """Remove the answer's own framing of the provision, once per pattern."""
    out = strip_framing(MARK_RE.sub(" ", sentence or ""))
    for pattern in _LEAD_PATTERNS:
        out = pattern.sub("", out, count=1)
    return out.strip()


def longest_run(claim_words: list[str], source_normalised: str) -> tuple[int, str]:
    """Length in words of the longest contiguous run of `claim_words` that appears
    verbatim in `source_normalised`, and the run itself."""
    best, best_text = 0, ""
    n = len(claim_words)
    for i in range(n):
        if n - i <= best:
            break                      # no later start can beat the current best
        j = i + best + 1
        while j <= n:
            candidate = " ".join(claim_words[i:j])
            if f" {candidate} " not in source_normalised:
                break
            best, best_text = j - i, candidate
            j += 1
    return best, best_text


@dataclass(frozen=True)
class Attribution:
    """How one claim relates, by identity, to the evidence supplied for it."""

    grade: str
    source_index: int | None
    run_words: int
    claim_words: int
    coverage: float
    run: str
    detail: str

    @property
    def verbatim(self) -> bool:
        return self.grade in (ATTRIBUTED_EXACT, ATTRIBUTED_OTHER)

    def to_dict(self) -> dict[str, Any]:
        return {"grade": self.grade, "source_index": self.source_index, "run_words": self.run_words,
                "claim_words": self.claim_words, "coverage": round(self.coverage, 3), "run": self.run,
                "detail": self.detail,
                "thresholds": {"min_coverage": ATTRIBUTION_MIN_COVERAGE, "min_run_words": ATTRIBUTION_MIN_RUN_WORDS}}


def attribute(sentence: str, sources, *, authoritative_indices=()) -> Attribution:
    """Attribute one claim to a supplied source by verbatim containment.

    `sources` are PackagedSource objects; `authoritative_indices` are the indices
    whose text IS the provision the claim names (its EXACT source, or its
    parent/child). A run found only outside those indices is still verbatim, but
    it is not the provision's own text and does not establish correctness.
    """
    claim = words(strip_lead(sentence))
    total = len(claim)
    if total == 0:
        return Attribution(UNATTRIBUTED, None, 0, 0, 0.0, "", "the sentence carries no assertable wording")
    scored: list[tuple[float, int, int, str]] = []
    for source in sources:
        run, text = longest_run(claim, normalise(source.text))
        scored.append((run / total, run, source.index, text))
    coverage, run, index, run_text = max(scored, default=(0.0, 0, None, ""), key=lambda r: (r[0], r[1]))
    if coverage < ATTRIBUTION_MIN_COVERAGE or run < ATTRIBUTION_MIN_RUN_WORDS:
        return Attribution(UNATTRIBUTED, index, run, total, coverage, run_text,
                           f"its longest verbatim run in any supplied source is {run}/{total} words "
                           f"({coverage:.0%}); {ATTRIBUTION_MIN_COVERAGE:.0%} over at least "
                           f"{ATTRIBUTION_MIN_RUN_WORDS} words is required to attribute it")
    wanted = set(authoritative_indices)
    if wanted and index not in wanted:
        # prefer an authoritative source that also meets the thresholds
        best = max(((c, r, i, t) for c, r, i, t in scored if i in wanted),
                   default=None, key=lambda r: (r[0], r[1]))
        if best is not None and best[0] >= ATTRIBUTION_MIN_COVERAGE and best[1] >= ATTRIBUTION_MIN_RUN_WORDS:
            coverage, run, index, run_text = best
        else:
            return Attribution(ATTRIBUTED_OTHER, index, run, total, coverage, run_text,
                               f"{coverage:.0%} of it is verbatim in SOURCE {index}, which is not the "
                               f"authoritative text of the provision it names")
    grade = ATTRIBUTED_EXACT if (not wanted or index in wanted) else ATTRIBUTED_OTHER
    return Attribution(grade, index, run, total, coverage, run_text,
                       f"{coverage:.0%} of it ({run} words) is verbatim in SOURCE {index}")
