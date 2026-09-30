"""Deterministic, bounded context construction from RetrievalResult objects.

Format (one block per source, boundaries explicit):

    SOURCE 1
    Corpus: eCFR
    Citation: 21 CFR 820.10(b)
    URL: https://www.ecfr.gov/...
    Text:
    (b) Applicable regulatory requirements. ...

    SOURCE 2
    Corpus: FDA Guidance
    ...

Budget policy (see docs/lexical_rag.md): at most `max_results` sources,
at most `max_chars_per_result` characters each (beginning kept, truncation
marked), at most `max_total_chars` overall. Sources that do not fit are
dropped, never silently squeezed. Nothing here touches the database.

Stage 3: `build_context()` is the legacy renderer for a plain result list.
`render_selection()` renders the output of the evidence selector
(regulus.rag.selection), which decides what goes in; this module only
formats. The policy carries the soft budget above plus hard ceilings that
bound required evidence (see ContextPolicy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from regulus.retrieval.models import RetrievalResult

CORPUS_LABEL = {"ecfr": "eCFR", "fda_guidance": "FDA Guidance"}
TRUNCATION_MARK = " [... truncated]"


@dataclass(frozen=True)
class ContextPolicy:
    """Limits chosen for Qwen3-0.6B on a CPU-only 8 GB machine.

    3,600 characters is roughly 900 tokens of source text, which keeps the
    prompt (system + sources + question) near 1,100 tokens: bounded prefill
    time on CPU and a context small enough for a 0.6B model to actually use.
    1,200 characters per source fits a whole eCFR paragraph (avg 218 chars,
    max 3,388) and most of a guidance chunk (median 1,459 chars). Up to 8
    sources are allowed because eCFR paragraphs are short and an exact
    section lookup returns several of them; the character budget, not the
    count, is normally the binding limit (three guidance chunks fill it).
    """

    max_results: int = 8
    max_chars_per_result: int = 1200
    max_total_chars: int = 3600
    # Stage 3 ceilings. The three limits above are the soft budget for optional
    # evidence. Required evidence (exact rows of requested provisions) is kept
    # in full up to required_max_chars_per_result each (longer than any eCFR
    # paragraph, max 3,388 chars) and may exceed the soft budget up to these
    # hard ceilings, which exist only to keep the prompt bounded on this CPU.
    hard_max_results: int = 24
    hard_max_total_chars: int = 9000
    required_max_chars_per_result: int = 4000

    def __post_init__(self) -> None:
        if self.max_results <= 0 or self.max_chars_per_result <= 0 or self.max_total_chars <= 0:
            raise ValueError("context limits must be positive")
        if self.required_max_chars_per_result <= 0:
            raise ValueError("required_max_chars_per_result must be positive")
        # a hard ceiling can never sit below the soft budget it bounds
        object.__setattr__(self, "hard_max_results", max(self.hard_max_results, self.max_results))
        object.__setattr__(self, "hard_max_total_chars", max(self.hard_max_total_chars, self.max_total_chars))

    def to_dict(self) -> dict[str, int]:
        return {
            "max_results": self.max_results,
            "max_chars_per_result": self.max_chars_per_result,
            "max_total_chars": self.max_total_chars,
            "hard_max_results": self.hard_max_results,
            "hard_max_total_chars": self.hard_max_total_chars,
            "required_max_chars_per_result": self.required_max_chars_per_result,
        }


@dataclass(frozen=True)
class ContextSource:
    """One source as it appears in the context, with its authoritative citation."""

    index: int  # 1-based number used in the prompt and by the model ([1], [2] ...)
    result: RetrievalResult
    text: str  # the (possibly truncated) text placed in the context
    truncated: bool
    # Stage 3 provenance (None/empty on the legacy build_context path)
    tier: str | None = None
    requirement_ids: tuple[str, ...] = ()
    protected: bool = False
    selection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "corpus": self.result.corpus,
            "citation": self.result.citation.label,
            "url": self.result.source_url,
            "retrieval_method": self.result.retrieval_method,
            "relevance_score": round(self.result.relevance_score, 4),
            "key": self.result.key,
            "chars": len(self.text),
            "truncated": self.truncated,
            "tier": self.tier,
            "requirement_ids": list(self.requirement_ids),
            "protected": self.protected,
            "selection_reason": self.selection_reason,
        }


@dataclass(frozen=True)
class ContextBundle:
    text: str
    sources: tuple[ContextSource, ...]
    dropped: int  # results that did not fit the budget
    notes: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.sources

    def to_dict(self) -> dict[str, Any]:
        return {"chars": len(self.text), "sources": [s.to_dict() for s in self.sources], "dropped": self.dropped, "notes": list(self.notes)}


def _clean(text: str) -> str:
    """Normalise whitespace so identical results always render identically."""
    return " ".join((text or "").split())


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = max(limit - len(TRUNCATION_MARK), 0)
    return text[:cut].rstrip() + TRUNCATION_MARK, True


def render_source(source: ContextSource) -> str:
    r = source.result
    lines = [
        f"SOURCE {source.index}",
        f"Corpus: {CORPUS_LABEL.get(r.corpus, r.corpus)}",
        f"Citation: {r.citation.label}",
    ]
    if r.corpus == "ecfr" and r.citation.heading:
        lines.append(f"Heading: {r.citation.heading}")
    lines.append(f"URL: {r.source_url or 'not available'}")
    lines.append("Text:")
    lines.append(source.text)
    return "\n".join(lines)


def build_context(
    results: list[RetrievalResult],
    policy: ContextPolicy | None = None,
    notes: list[str] | None = None,
) -> ContextBundle:
    """Turn ordered retrieval results into a bounded, delimited context."""
    policy = policy or ContextPolicy()
    sources: list[ContextSource] = []
    blocks: list[str] = []
    used = 0
    dropped = 0
    for r in results:
        if len(sources) >= policy.max_results:
            dropped += 1
            continue
        text, truncated = _truncate(_clean(r.text), policy.max_chars_per_result)
        candidate = ContextSource(index=len(sources) + 1, result=r, text=text, truncated=truncated)
        block = render_source(candidate)
        # +2 for the blank line between blocks
        if used + len(block) + (2 if blocks else 0) > policy.max_total_chars:
            remaining = policy.max_total_chars - used - (2 if blocks else 0)
            # try to fit a shortened version of this source, if a useful amount remains
            header_len = len(block) - len(text)
            if remaining - header_len >= 200:
                text, truncated = _truncate(text, remaining - header_len)
                candidate = ContextSource(index=candidate.index, result=r, text=text, truncated=True)
                block = render_source(candidate)
            else:
                dropped += 1
                continue
        sources.append(candidate)
        blocks.append(block)
        used += len(block) + (2 if len(blocks) > 1 else 0)
    note_lines = tuple(_clean(n) for n in (notes or []) if n and n.strip())
    text = "\n\n".join(blocks)
    if note_lines:
        text = (text + "\n\n" if text else "") + "\n".join(f"NOTE: {n}" for n in note_lines)
    return ContextBundle(text=text, sources=tuple(sources), dropped=dropped, notes=note_lines)


def render_selection(selection, notes: list[str] | None = None) -> ContextBundle:
    """Render a Stage 3 Selection (regulus.rag.selection) into a ContextBundle.

    Selection already decided membership, order, text and truncation; this
    only formats. `dropped` counts everything the selector left out.
    """
    sources = tuple(
        ContextSource(
            index=item.index,
            result=item.evidence.result,
            text=item.text,
            truncated=item.truncated,
            tier=item.evidence.tier,
            requirement_ids=item.requirement_ids,
            protected=item.protected,
            selection_reason=item.reason,
        )
        for item in selection.selected
    )
    blocks = [render_source(src) for src in sources]
    note_lines = tuple(_clean(n) for n in (notes or []) if n and n.strip())
    text = "\n\n".join(blocks)
    if note_lines:
        text = (text + "\n\n" if text else "") + "\n".join(f"NOTE: {n}" for n in note_lines)
    return ContextBundle(text=text, sources=sources, dropped=len(selection.dropped), notes=note_lines)
