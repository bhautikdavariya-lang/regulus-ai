"""Stage 5 evaluation dataset: questions with explicit, checkable expectations.

Each record states what the question asks for (requirements, as canonical
labels), which of those should have exact evidence in the snapshot, which
are known to be missing, what the correct behaviour is, and a few terms a
correct answer contains. Expectations were fixed by hand against the
database before the run and the file is protected: it is listed among the
benchmark files that training data must exclude.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from regulus.config import PROJECT_ROOT

DEFAULT_STAGE5_DATASET = PROJECT_ROOT / "data" / "evaluation" / "datasets" / "stage5_v1.jsonl"

BEHAVIORS = ("answer", "partial", "refuse", "general", "guidance")
DOMAINS = ("regulatory", "out_of_domain", "mixed")
CATEGORIES = ("single", "parent", "section", "multi", "range", "missing", "nonexistent", "adversarial",
              "general", "guidance", "domain_boundary", "citation", "long", "refusal")


class Stage5DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Stage5Example:
    id: str
    category: str
    question: str
    expected_requirements: tuple[str, ...]
    expected_exact: tuple[str, ...]
    expected_missing: tuple[str, ...]
    expected_behavior: str
    expected_terms: tuple[str, ...]
    domain: str
    notes: str = ""

    @property
    def explicit(self) -> bool:
        return bool(self.expected_requirements)

    @property
    def generates(self) -> bool:
        """Whether the pipeline is expected to call the model at all."""
        return not (self.expected_behavior == "refuse" and self.expected_requirements and not self.expected_exact)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Stage5Dataset:
    name: str
    path: Path
    sha256: str
    examples: tuple[Stage5Example, ...]

    def __len__(self) -> int:
        return len(self.examples)

    def by_category(self) -> dict[str, list[Stage5Example]]:
        out: dict[str, list[Stage5Example]] = {}
        for e in self.examples:
            out.setdefault(e.category, []).append(e)
        return out


def _tuple(record: dict, key: str, line_no: int) -> tuple[str, ...]:
    value = record.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise Stage5DatasetError(f"line {line_no}: {key} must be a list of strings")
    return tuple(value)


def validate_record(record: object, line_no: int) -> Stage5Example:
    if not isinstance(record, dict):
        raise Stage5DatasetError(f"line {line_no}: record must be an object")
    for key in ("id", "category", "question", "expected_behavior", "domain"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise Stage5DatasetError(f"line {line_no}: {key} is required")
    if record["category"] not in CATEGORIES:
        raise Stage5DatasetError(f"line {line_no}: unknown category {record['category']!r}")
    if record["expected_behavior"] not in BEHAVIORS:
        raise Stage5DatasetError(f"line {line_no}: unknown expected_behavior {record['expected_behavior']!r}")
    if record["domain"] not in DOMAINS:
        raise Stage5DatasetError(f"line {line_no}: unknown domain {record['domain']!r}")
    ex = Stage5Example(
        id=record["id"],
        category=record["category"],
        question=record["question"],
        expected_requirements=_tuple(record, "expected_requirements", line_no),
        expected_exact=_tuple(record, "expected_exact", line_no),
        expected_missing=_tuple(record, "expected_missing", line_no),
        expected_behavior=record["expected_behavior"],
        expected_terms=_tuple(record, "expected_terms", line_no),
        domain=record["domain"],
        notes=str(record.get("notes", "")),
    )
    if set(ex.expected_exact) - set(ex.expected_requirements) or set(ex.expected_missing) - set(ex.expected_requirements):
        raise Stage5DatasetError(f"line {line_no}: expected_exact and expected_missing must be subsets of expected_requirements")
    if set(ex.expected_exact) & set(ex.expected_missing):
        raise Stage5DatasetError(f"line {line_no}: a requirement cannot be both exact and missing")
    if ex.expected_behavior == "partial" and not (ex.expected_exact and ex.expected_missing):
        raise Stage5DatasetError(f"line {line_no}: 'partial' needs both exact and missing requirements")
    return ex


def load_stage5_dataset(path: str | Path | None = None) -> Stage5Dataset:
    p = Path(path) if path else DEFAULT_STAGE5_DATASET
    if not p.is_file():
        raise Stage5DatasetError(f"dataset not found: {p}")
    raw = p.read_bytes()
    examples: list[Stage5Example] = []
    seen: set[str] = set()
    for line_no, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Stage5DatasetError(f"line {line_no}: invalid JSON ({exc.msg})") from exc
        ex = validate_record(record, line_no)
        if ex.id in seen:
            raise Stage5DatasetError(f"line {line_no}: duplicate id {ex.id}")
        seen.add(ex.id)
        examples.append(ex)
    if not examples:
        raise Stage5DatasetError(f"{p} contains no records")
    return Stage5Dataset(name=p.stem, path=p, sha256=hashlib.sha256(raw).hexdigest(), examples=tuple(examples))
