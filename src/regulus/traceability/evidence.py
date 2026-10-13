"""Exact evidence capture, fingerprint and replay.

What "exact evidence" means here
--------------------------------
The passages that were placed in the model's prompt for one answer, after all
retrieval, ranking, selection, filtering, truncation and the evidence ceiling:
`GenerationPackage.sources[*].text`, which `regulus.rag.generation.render_source`
writes into the prompt verbatim. Not the retrieved results, not the database
text, not the citation list. A truncated source is captured as truncated.

The snapshot is taken from the same frozen package object the prompt was
rendered from, and - when the model was called - checked against the prompt
that was actually sent: every captured text must appear in the prompt's
SOURCES block, in order (`prompt_verified`). `prompt_sha256` is the hash of
that SOURCES block as sent.

Fingerprint
-----------
SHA-256 over a canonical JSON list, in prompt order, of each item's identity,
citation, heading, tier and EXACT TEXT. Reordering, editing, adding or removing
an item changes it. It is recomputed on every load; a snapshot whose items do
not hash to its recorded fingerprint is rejected (`EvidenceIntegrityError`).

Provenance
----------
EXACT                 a snapshot captured at generation and verified on load
LEGACY_RECONSTRUCTED  evidence rebuilt afterwards (e.g. from labels in an old
                      artifact); NOT what the model saw, and never labelled EXACT
MISSING               no evidence record exists for the answer
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

EVIDENCE_SCHEMA = "regulus_evidence_snapshot_v1"

EXACT = "exact"
LEGACY_RECONSTRUCTED = "legacy_reconstructed"
MISSING = "missing"
PROVENANCES = (EXACT, LEGACY_RECONSTRUCTED, MISSING)

CAPTURE_PACKAGE = "generation_package"   # the Stage 4 package the grounded prompt is rendered from
CAPTURE_CONTEXT = "context_bundle"       # the legacy path: ContextBundle rendered by build_context

_SOURCE_TYPE = {"ecfr": "ecfr", "fda_guidance": "guidance"}


class EvidenceIntegrityError(ValueError):
    """A stored snapshot does not hash to its recorded fingerprint."""


@dataclass(frozen=True)
class EvidenceItem:
    """One source exactly as it was placed in the prompt."""

    order: int                      # 0-based position in the prompt's SOURCES block
    index: int                      # the number the model saw ("SOURCE 3", cited as [3])
    evidence_id: str
    source_type: str                # "ecfr" | "guidance" | the corpus name otherwise
    corpus: str                     # the raw corpus value ("ecfr", "fda_guidance")
    citation: str                   # the label shown to the model
    heading: str | None             # the heading shown to the model (None when none was shown)
    text: str                       # the exact text in the prompt, truncation included
    truncated: bool
    tier: str | None = None
    requirement_ids: tuple[str, ...] = ()
    protected: bool = False
    key: str = ""
    url: str | None = None
    is_docket: bool = False
    document: str | None = None     # guidance document title; None for eCFR
    part: str | None = None
    section: str | None = None
    paragraph: str | None = None
    citation_fields: dict[str, Any] = field(default_factory=dict)

    def hashed(self) -> dict[str, Any]:
        """The fields the fingerprint covers. Text is always among them."""
        return {"order": self.order, "index": self.index, "evidence_id": self.evidence_id,
                "source_type": self.source_type, "citation": self.citation, "heading": self.heading,
                "tier": self.tier, "truncated": self.truncated, "text": self.text}

    def to_dict(self) -> dict[str, Any]:
        return {"order": self.order, "index": self.index, "evidence_id": self.evidence_id,
                "source_type": self.source_type, "corpus": self.corpus, "citation": self.citation,
                "document": self.document, "part": self.part, "section": self.section, "paragraph": self.paragraph,
                "heading": self.heading, "tier": self.tier, "requirement_ids": list(self.requirement_ids),
                "protected": self.protected, "key": self.key, "url": self.url, "is_docket": self.is_docket,
                "truncated": self.truncated, "chars": len(self.text), "text": self.text,
                "citation_fields": dict(self.citation_fields)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvidenceItem:
        return cls(order=int(d["order"]), index=int(d["index"]), evidence_id=str(d["evidence_id"]),
                   source_type=d["source_type"], corpus=d.get("corpus") or d["source_type"], citation=d["citation"],
                   heading=d.get("heading"), text=d["text"], truncated=bool(d.get("truncated")), tier=d.get("tier"),
                   requirement_ids=tuple(d.get("requirement_ids") or ()), protected=bool(d.get("protected")),
                   key=d.get("key") or "", url=d.get("url"), is_docket=bool(d.get("is_docket")),
                   document=d.get("document"), part=d.get("part"), section=d.get("section"),
                   paragraph=d.get("paragraph"), citation_fields=dict(d.get("citation_fields") or {}))


def fingerprint(items: Iterable[EvidenceItem]) -> str:
    """SHA-256 of the ordered items, text included. Deterministic across runs and platforms."""
    payload = [EVIDENCE_SCHEMA] + [item.hashed() for item in items]
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


@dataclass(frozen=True)
class EvidenceSnapshot:
    """The evidence package of one answer: immutable once captured."""

    items: tuple[EvidenceItem, ...]
    fingerprint: str
    capture_point: str
    model_called: bool
    prompt_sha256: str | None = None      # SHA-256 of the SOURCES block of the prompt actually sent
    prompt_verified: bool | None = None   # every item's text found in that block, in order (None: no prompt)
    # The non-evidence context the evaluator also needs to replay without the live package.
    question: str = ""
    requirements: tuple[tuple[str, str], ...] = ()
    satisfied_ids: tuple[str, ...] = ()
    missing_labels: tuple[str, ...] = ()
    coverage_explicit: bool = False
    schema: str = EVIDENCE_SCHEMA

    # -- the package/coverage interface the evaluator reads -------------------

    @property
    def sources(self) -> tuple[EvidenceItem, ...]:
        return self.items

    @property
    def requirement_labels(self) -> dict[str, str]:
        return dict(self.requirements)

    @property
    def explicit(self) -> bool:
        return self.coverage_explicit

    answer_plan = None
    question_analysis = None

    def verify(self) -> EvidenceSnapshot:
        actual = fingerprint(self.items)
        if actual != self.fingerprint:
            raise EvidenceIntegrityError(f"evidence fingerprint mismatch: recorded {self.fingerprint[:12]}..., "
                                         f"items hash to {actual[:12]}...")
        if [i.order for i in self.items] != list(range(len(self.items))):
            raise EvidenceIntegrityError("evidence order is not contiguous")
        return self

    def summary(self) -> dict[str, Any]:
        """What an assessment reports about the evidence it used (no text)."""
        return {"fingerprint": self.fingerprint, "items": len(self.items),
                "guidance_items": sum(1 for i in self.items if i.source_type == "guidance"),
                "capture_point": self.capture_point, "model_called": self.model_called,
                "prompt_sha256": self.prompt_sha256, "prompt_verified": self.prompt_verified, "schema": self.schema}

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "fingerprint": self.fingerprint, "capture_point": self.capture_point,
                "model_called": self.model_called, "prompt_sha256": self.prompt_sha256,
                "prompt_verified": self.prompt_verified, "question": self.question,
                "requirements": [{"id": i, "canonical": c} for i, c in self.requirements],
                "satisfied_ids": list(self.satisfied_ids), "missing_labels": list(self.missing_labels),
                "coverage_explicit": self.coverage_explicit, "items": [i.to_dict() for i in self.items]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvidenceSnapshot:
        if d.get("schema") != EVIDENCE_SCHEMA:
            raise EvidenceIntegrityError(f"unknown evidence schema {d.get('schema')!r}")
        snap = cls(items=tuple(EvidenceItem.from_dict(i) for i in d.get("items") or ()),
                   fingerprint=d["fingerprint"], capture_point=d["capture_point"],
                   model_called=bool(d.get("model_called")), prompt_sha256=d.get("prompt_sha256"),
                   prompt_verified=d.get("prompt_verified"), question=d.get("question") or "",
                   requirements=tuple((r["id"], r["canonical"]) for r in d.get("requirements") or ()),
                   satisfied_ids=tuple(d.get("satisfied_ids") or ()),
                   missing_labels=tuple(d.get("missing_labels") or ()),
                   coverage_explicit=bool(d.get("coverage_explicit")), schema=d["schema"])
        return snap.verify()


def load(record: EvidenceSnapshot | dict[str, Any] | str) -> EvidenceSnapshot:
    """A verified snapshot from a snapshot, its dict or its JSON. Raises on tampering."""
    if isinstance(record, EvidenceSnapshot):
        return record.verify()
    if isinstance(record, str):
        record = json.loads(record)
    return EvidenceSnapshot.from_dict(record)


# --------------------------------------------------------------- capture


def _item(order: int, source: Any) -> EvidenceItem:
    """From a PackagedSource (the grounded path) or a ContextSource (the legacy path)."""
    result = getattr(source, "result", None)
    if result is not None:                       # ContextSource: heading shown for eCFR only
        corpus, citation = result.corpus, result.citation.label
        fields = result.citation.to_dict()
        heading = result.citation.heading if corpus == "ecfr" else None
        evidence_id, key, url = result.key, result.key, result.source_url
        is_docket = False
    else:                                        # PackagedSource
        corpus, citation = source.corpus, source.citation
        fields = dict(getattr(source, "citation_fields", None) or {})
        heading = source.heading
        evidence_id, key, url = source.evidence_id, source.key, source.url
        is_docket = bool(getattr(source, "is_docket", False))
    source_type = _SOURCE_TYPE.get(corpus, corpus)
    return EvidenceItem(order=order, index=int(source.index), evidence_id=str(evidence_id), source_type=source_type,
                        corpus=corpus, citation=citation, heading=heading, text=source.text,
                        truncated=bool(source.truncated), tier=getattr(source, "tier", None),
                        requirement_ids=tuple(getattr(source, "requirement_ids", ()) or ()),
                        protected=bool(getattr(source, "protected", False)), key=str(key or ""), url=url,
                        is_docket=is_docket,
                        document=fields.get("document_title") if source_type == "guidance" else None,
                        part=fields.get("part"), section=fields.get("section"), paragraph=fields.get("paragraph"),
                        citation_fields=fields)


def _in_order(texts: Sequence[str], block: str) -> bool:
    at = 0
    for text in texts:
        found = block.find(text, at)
        if found < 0:
            return False
        at = found + len(text)
    return True


def capture(sources: Sequence[Any], *, capture_point: str, prompt_sources: str | None = None,
            model_called: bool = False, question: str = "", requirements: Sequence[tuple[str, str]] = (),
            satisfied_ids: Sequence[str] = (), missing_labels: Sequence[str] = (),
            coverage_explicit: bool = False) -> EvidenceSnapshot:
    """Snapshot the sources in prompt order. `prompt_sources` is the SOURCES block
    of the prompt actually sent (None when no model was called)."""
    items = tuple(_item(order, s) for order, s in enumerate(sources))
    verified = _in_order([i.text for i in items], prompt_sources) if prompt_sources is not None else None
    return EvidenceSnapshot(items=items, fingerprint=fingerprint(items), capture_point=capture_point,
                            model_called=model_called, prompt_sha256=_sha256(prompt_sources), prompt_verified=verified,
                            question=question, requirements=tuple((str(i), str(c)) for i, c in requirements),
                            satisfied_ids=tuple(satisfied_ids), missing_labels=tuple(missing_labels),
                            coverage_explicit=bool(coverage_explicit))


def sources_block(prompt: str | None, opener: str, closer: str) -> str | None:
    """The SOURCES section of a rendered user message, exactly as sent."""
    if prompt is None:
        return None
    start = prompt.find(opener)
    end = prompt.find(closer, start + len(opener)) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    return prompt[start + len(opener):end]


def capture_safely(*args, **kwargs) -> EvidenceSnapshot | None:
    """`capture` for the answering path: a capture failure must never affect the
    answer. None then means the evidence was NOT captured (provenance MISSING),
    which an evaluator reports as such rather than reconstructing."""
    try:
        return capture(*args, **kwargs)
    except Exception:  # noqa: BLE001 - capture is an observer of the answer
        return None
