"""Choosing WHICH evidence passage a claim is compared against. Nothing else.

This module answers one question - *of the sentences in the authoritative
evidence, which one is this claim about?* - and it is forbidden from answering
any other. In particular it never decides whether a claim is correct. The
measurement that forces that separation, taken with the repository's own
embedder (BAAI/bge-small-en-v1.5):

    evidence "shall establish and maintain procedures"
      vs "may establish procedures"              cos 0.974   <- the WRONG claim
      vs "must create and maintain documented …" cos 0.959   <- the RIGHT claim

The wrong modal scores higher than the correct paraphrase, so similarity ranks
a contradiction above a faithful restatement. As a *ranking* signal that is
harmless - both sentences are about the same requirement, which is all this
module claims - and as a *correctness* signal it is worse than useless. The
verdict is decided by `regulus.accuracy.operators` on the pair this module
returns.

Two aligners, one interface:

    LexicalAligner    always available, zero cost: content-term overlap plus the
                      longest contiguous verbatim run, over evidence sentences.
    SemanticAligner   wraps an existing embedder (regulus.retrieval.semantic
                      TransformersEmbedder) and ranks by cosine. Used only when
                      an embedder is supplied; the evaluator works without one.

A `SemanticAligner` is constructed around an embedder the caller already owns,
so no model is loaded per question and none is loaded at all unless the caller
chose to. Embeddings of evidence are cached by passage text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from regulus.accuracy.attribution import longest_run, normalise, strip_lead
from regulus.evaluation.grounding_eval import split_sentences

# Below this share of the claim's content terms, no evidence sentence is "about"
# the claim at all and the claim is reported unaligned rather than compared
# against the least-bad passage. It is an ALIGNMENT floor, never a verdict.
MIN_ALIGNMENT_OVERLAP = 0.25
# How many candidates the verdict stage may examine per claim.
TOP_K = 3

_WORD_RE = re.compile(r"[a-z][a-z'-]{2,}")
# Terms carried by nearly every regulatory sentence; they say nothing about
# which passage a claim is about. Not used for any verdict.
_STOP = frozenset(
    "the and for with that this these those from into under upon such any all are was were have has had its their "
    "there where when what which must shall will would could should may can not required require requires requirement "
    "requirements provision provisions section sections paragraph paragraphs part parts chapter title cfr ecfr iso "
    "clause subclause accordance applicable specified stated states state include includes including means also each "
    "other than only more most very being been does your you they them then".split())


def content_terms(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(normalise(text))) - _STOP


@dataclass(frozen=True)
class Passage:
    """One sentence of one evidence source, with its provenance."""

    source_index: int
    citation: str
    tier: str
    text: str
    heading: str | None = None      # the source's own section/document title, when it has one
    authority: str = "binding_regulation"   # regulus.accuracy.operators.BINDING / GUIDANCE, from the corpus
    seq: int = 0                    # position of this sentence within its source, for adjacent-sentence windows

    def to_dict(self) -> dict[str, Any]:
        return {"source_index": self.source_index, "citation": self.citation, "tier": self.tier,
                "heading": self.heading, "authority": self.authority, "text": self.text[:300]}


@dataclass(frozen=True)
class Alignment:
    passage: Passage
    overlap: float          # share of the claim's content terms present in the passage
    verbatim_run: int       # longest contiguous verbatim run, in words
    claim_words: int
    similarity: float | None = None   # cosine, when a semantic aligner was used
    method: str = "lexical"

    @property
    def verbatim_coverage(self) -> float:
        return self.verbatim_run / self.claim_words if self.claim_words else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"passage": self.passage.to_dict(), "overlap": round(self.overlap, 3),
                "verbatim_run": self.verbatim_run, "claim_words": self.claim_words,
                "verbatim_coverage": round(self.verbatim_coverage, 3),
                "similarity": None if self.similarity is None else round(float(self.similarity), 4),
                "method": self.method}


def passages(sources: Sequence[Any], *, min_words: int = 4) -> list[Passage]:
    """Every evidence source split into sentences, each keeping its source."""
    from regulus.accuracy.operators import authority_of

    out: list[Passage] = []
    for source in sources:
        heading = getattr(source, "heading", None)
        tier = getattr(source, "tier", "exact")
        authority = authority_of(getattr(source, "corpus", None))
        seq = 0
        for sentence in split_sentences(source.text or ""):
            if len(normalise(sentence).split()) >= min_words:
                out.append(Passage(source.index, source.citation, tier, sentence.strip(), heading, authority, seq))
                seq += 1
        if not any(p.source_index == source.index for p in out) and (source.text or "").strip():
            out.append(Passage(source.index, source.citation, tier, (source.text or "").strip(), heading, authority, 0))
    return out


class Aligner(Protocol):
    method: str

    def prepare(self, claims: Sequence[str], candidates: Sequence[Passage]) -> None: ...

    def align(self, claim: str, candidates: Sequence[Passage], *, top_k: int = TOP_K) -> list[Alignment]: ...


def _score(claim: str, passage: Passage) -> tuple[float, int, int]:
    """Overlap, longest verbatim run and claim length, all measured on the claim's
    assertable body.

    `strip_lead` removes the answer's own scaffolding - the citation label or
    framing clause a grounded answer opens with ("21 CFR 820.10(b)(2): ...",
    "Under 820.30(a), ..."). Leaving it in would both inflate the denominator and
    break the contiguous run at the very first word, so a claim quoting its
    provision word for word would be reported as a paraphrase.
    """
    body = strip_lead(claim)
    terms = content_terms(body)
    words = normalise(body).split()
    overlap = len(terms & content_terms(passage.text)) / len(terms) if terms else 0.0
    run, _ = longest_run(words, normalise(passage.text))
    return overlap, run, len(words)


def adjacent_windows(anchors: Sequence[Passage], candidates: Sequence[Passage]) -> list[Passage]:
    """Two consecutive sentences of the SAME source joined, around each anchor:
    a claim may restate a rule its source states over two sentences. Never
    across sources, never more than two sentences."""
    by_pos = {(p.source_index, p.seq): p for p in candidates}
    out: dict[tuple[int, int], Passage] = {}
    for a in anchors:
        for first in (a.seq - 1, a.seq):
            one, two = by_pos.get((a.source_index, first)), by_pos.get((a.source_index, first + 1))
            if one is not None and two is not None and (a.source_index, first) not in out:
                out[(a.source_index, first)] = Passage(one.source_index, one.citation, one.tier, f"{one.text} {two.text}",
                                                       one.heading, one.authority, one.seq)
    return list(out.values())


class LexicalAligner:
    """Ranks by content-term overlap, then by the longest verbatim run."""

    method = "lexical"

    def prepare(self, claims: Sequence[str], candidates: Sequence[Passage]) -> None:
        """Nothing to precompute."""

    def align(self, claim: str, candidates: Sequence[Passage], *, top_k: int = TOP_K) -> list[Alignment]:
        scored: list[Alignment] = []
        for passage in candidates:
            overlap, run, n = _score(claim, passage)
            if overlap < MIN_ALIGNMENT_OVERLAP:
                continue
            scored.append(Alignment(passage, overlap, run, n, method=self.method))
        scored.sort(key=lambda a: (a.overlap, a.verbatim_run), reverse=True)
        return scored[:top_k]


class SemanticAligner:
    """Ranks by cosine against an embedder the caller already owns.

    The lexical floor still applies: a passage that shares almost none of the
    claim's content terms is not about the claim, whatever its cosine. Cosine
    reorders what survives the floor and adds candidates the floor admits but
    overlap ranks poorly - a concise paraphrase of a long provision.
    """

    method = "semantic"

    def __init__(self, embedder, *, floor: float = MIN_ALIGNMENT_OVERLAP) -> None:
        self._embedder = embedder
        self._floor = floor
        self._cache: dict[str, Any] = {}

    def _vectors(self, texts: Sequence[str]):
        import numpy as np

        # Length-sorted so each internal batch pads to a similar length: padded
        # positions are masked, so the vectors are the same; only the wasted
        # attention over padding goes away. The embedder itself is shared with
        # retrieval and is deliberately not modified.
        missing = sorted((t for t in dict.fromkeys(texts) if t not in self._cache), key=len)
        if missing:
            for text, vector in zip(missing, self._embedder.embed_batch(missing)):
                self._cache[text] = vector
        return np.stack([self._cache[t] for t in texts])

    def prepare(self, claims: Sequence[str], candidates: Sequence[Passage]) -> None:
        """Embed every claim and every passage some claim could align to, in ONE call.

        Without this each claim triggers its own forward pass, which measured at
        650 ms for a 24-claim answer. Only passages that clear the lexical floor
        for at least one claim are embedded: the rest can never be returned by
        `align`, so embedding them would be cost with no effect. Verdicts are
        unaffected - the same texts are embedded by the same pinned model; only
        how many forward passes it takes changes.
        """
        needed = [p.text for p in candidates
                  if any(_score(claim, p)[0] >= self._floor for claim in claims)]
        if claims or needed:
            self._vectors([*claims, *needed])

    def align(self, claim: str, candidates: Sequence[Passage], *, top_k: int = TOP_K) -> list[Alignment]:
        from regulus.retrieval.semantic import cosine_similarity

        kept = [(p, *_score(claim, p)) for p in candidates]
        kept = [row for row in kept if row[1] >= self._floor]
        if not kept:
            return []
        matrix = self._vectors([row[0].text for row in kept])
        query = self._vectors([claim])[0]
        sims = cosine_similarity(query, matrix, normalized=True)
        out = [Alignment(p, overlap, run, n, similarity=float(sim), method=self.method)
               for (p, overlap, run, n), sim in zip(kept, sims)]
        out.sort(key=lambda a: (a.similarity, a.overlap, a.verbatim_run), reverse=True)
        return out[:top_k]
