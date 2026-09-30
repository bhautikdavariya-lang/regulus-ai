"""Training example schema (JSONL) and conversion to chat messages.

One line per example:

    {
      "id": "example_3f9a...",           # deterministic (sha256 of category, generator, sources, question)
      "type": "regulatory_qa" | "abstention",
      "category": "direct_cfr" | ...,    # see regulus.training.config.CATEGORIES
      "question": "...",
      "context": [ {source_type, citation, text, url, ...provenance} ],
      "answer": "...",
      "citations": ["21 CFR 820.10(a)"],
      "grounded": true,
      "provenance": {"source_keys": [...], "group": "ecfr:820.10", "generator": "...", "snapshot_date": "2026-09-03"},
      "split": "train" | "validation" | "test"
    }

Context entries carry regulatory provenance only (citation, part, subpart,
section, paragraph, heading, document title, docket, status, issue date,
URL). No database ids, no credentials, no vectors.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from regulus.training.config import CATEGORIES
from regulus.training.text import stable_hash

EXAMPLE_TYPES = ("regulatory_qa", "abstention")
SOURCE_TYPES = ("ecfr", "fda_guidance", "ecfr_hierarchy")
SPLITS = ("train", "validation", "test")
SCHEMA_VERSION = 1
REQUIRED_FIELDS = ("id", "type", "category", "question", "context", "answer", "citations", "grounded", "provenance")


class ExampleError(ValueError):
    """Raised for a malformed training example."""


@dataclass(frozen=True)
class ContextItem:
    source_type: str
    citation: str
    text: str
    url: str | None = None
    # eCFR provenance
    part: str | None = None
    part_title: str | None = None
    subpart: str | None = None
    section: str | None = None
    paragraph: str | None = None
    heading: str | None = None
    # guidance provenance
    document_title: str | None = None
    docket_number: str | None = None
    status: str | None = None
    issued_on: str | None = None
    center: str | None = None
    # natural, non-secret identity of the row (same form as RetrievalResult.key)
    source_key: str = ""

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ExampleError(f"unknown source_type {self.source_type!r}")
        if not self.citation.strip() or not self.text.strip():
            raise ExampleError("context citation and text must be non-empty")
        if not self.source_key:
            raise ExampleError("context source_key must be set")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TrainingExample:
    type: str
    category: str
    question: str
    context: list[ContextItem]
    answer: str
    citations: list[str]
    grounded: bool
    generator: str
    group: str  # split-grouping key (source section / guidance document / negative identifier)
    snapshot_date: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    split: str | None = None
    id: str = ""

    def __post_init__(self) -> None:
        if self.type not in EXAMPLE_TYPES:
            raise ExampleError(f"unknown type {self.type!r}")
        if self.category not in CATEGORIES:
            raise ExampleError(f"unknown category {self.category!r}")
        if not self.question.strip() or not self.answer.strip():
            raise ExampleError("question and answer must be non-empty")
        if self.grounded and not self.context:
            raise ExampleError("a grounded example needs at least one context item")
        if self.grounded and not self.citations:
            raise ExampleError("a grounded example needs at least one citation")
        if not self.group:
            raise ExampleError("group must be set")
        if not self.id:
            self.id = make_id(self.category, self.generator, self.source_keys, self.question)

    @property
    def source_keys(self) -> list[str]:
        return [c.source_key for c in self.context]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "category": self.category,
            "question": self.question,
            "context": [c.to_dict() for c in self.context],
            "answer": self.answer,
            "citations": list(self.citations),
            "grounded": self.grounded,
            "provenance": {
                "source_keys": self.source_keys,
                "group": self.group,
                "generator": self.generator,
                "snapshot_date": self.snapshot_date,
                **({"extra": dict(self.extra)} if self.extra else {}),
            },
        }
        if self.split:
            d["split"] = self.split
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrainingExample":
        if not isinstance(data, dict):
            raise ExampleError("example must be a JSON object")
        missing = [f for f in REQUIRED_FIELDS if f not in data]
        if missing:
            raise ExampleError(f"missing field(s): {', '.join(missing)}")
        prov = data["provenance"]
        if not isinstance(prov, dict) or "group" not in prov or "generator" not in prov:
            raise ExampleError("provenance must contain group and generator")
        try:
            ctx = [ContextItem(**c) for c in data["context"]]
        except TypeError as exc:
            raise ExampleError(f"bad context item: {exc}") from exc
        ex = cls(
            type=data["type"],
            category=data["category"],
            question=data["question"],
            context=ctx,
            answer=data["answer"],
            citations=list(data["citations"]),
            grounded=bool(data["grounded"]),
            generator=prov["generator"],
            group=prov["group"],
            snapshot_date=prov.get("snapshot_date"),
            extra=dict(prov.get("extra", {})),
            split=data.get("split"),
            id=data["id"],
        )
        return ex


def make_id(category: str, generator: str, source_keys: Iterable[str], question: str) -> str:
    return "example_" + stable_hash(category, generator, "|".join(source_keys), question)[:16]


# ------------------------------------------------------------------ JSONL


def write_jsonl(examples: Iterable[TrainingExample], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for ex in examples:
            fh.write(json.dumps(ex.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    return n


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExampleError(f"{path.name} line {line_no}: invalid JSON ({exc.msg})") from exc


def read_jsonl(path: Path) -> list[TrainingExample]:
    out = []
    for line_no, record in iter_jsonl(path):
        try:
            out.append(TrainingExample.from_dict(record))
        except ExampleError as exc:
            raise ExampleError(f"{path.name} line {line_no}: {exc}") from exc
    return out


# ------------------------------------------------------- chat conversion


def render_context(context: list[ContextItem]) -> str:
    """Same SOURCE block layout as regulus.rag.context so a fine-tuned model
    sees at training time exactly what the RAG pipeline shows at inference."""
    label = {"ecfr": "eCFR", "fda_guidance": "FDA Guidance", "ecfr_hierarchy": "eCFR"}
    blocks = []
    for i, c in enumerate(context, start=1):
        lines = [f"SOURCE {i}", f"Corpus: {label[c.source_type]}", f"Citation: {c.citation}"]
        if c.source_type != "fda_guidance" and c.heading:
            lines.append(f"Heading: {c.heading}")
        lines.append(f"URL: {c.url or 'not available'}")
        lines.append("Text:")
        lines.append(c.text)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def to_messages(example: TrainingExample) -> list[dict[str, str]]:
    """system / user / assistant turns using the Stage 6 RAG prompt, so the
    dataset can be fed directly to a chat-format SFT trainer later."""
    from regulus.rag.prompt import build_messages

    messages = build_messages(example.question, render_context(example.context))
    return [*messages, {"role": "assistant", "content": example.answer}]
