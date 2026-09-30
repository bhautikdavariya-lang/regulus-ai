"""Evaluation dataset loading and schema validation (JSONL).

One JSON object per line with the fields of EvalExample. The dataset name is
the file stem (e.g. ``baseline_v1``) and a SHA-256 of the file content is
recorded with every run so results can always be traced to the exact
benchmark that produced them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from regulus.config import PROJECT_ROOT

DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "evaluation" / "datasets"
DEFAULT_DATASET_PATH = DEFAULT_DATASET_DIR / "baseline_v1.jsonl"

CATEGORIES = {
    "general_knowledge": "General knowledge",
    "regulatory_concepts": "Regulatory concepts",
    "fda_ecfr": "FDA/eCFR-oriented",
    "reasoning": "Reasoning",
    "hallucination": "Unknown/hallucination",
}
EXPECTED_BEHAVIORS = {"answer", "acknowledge_uncertainty"}
REQUIRED_FIELDS = ("id", "category", "question", "reference_answer", "evaluation_notes", "expected_behavior")


class DatasetError(ValueError):
    """Raised for a missing, malformed or schema-invalid dataset."""


@dataclass(frozen=True)
class EvalExample:
    id: str
    category: str
    question: str
    reference_answer: str
    evaluation_notes: str
    expected_behavior: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EvalDataset:
    name: str
    path: Path
    sha256: str
    examples: list[EvalExample]

    def __len__(self) -> int:
        return len(self.examples)

    def __iter__(self):
        return iter(self.examples)

    def relative_path(self) -> str:
        try:
            return self.path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return self.path.name


def validate_record(record: object, line_no: int) -> EvalExample:
    """Validate one parsed JSON record and convert it to an EvalExample."""
    if not isinstance(record, dict):
        raise DatasetError(f"line {line_no}: expected a JSON object, got {type(record).__name__}")
    missing = [f for f in REQUIRED_FIELDS if f not in record]
    if missing:
        raise DatasetError(f"line {line_no}: missing required field(s): {', '.join(missing)}")
    for name in REQUIRED_FIELDS:
        value = record[name]
        if not isinstance(value, str) or not value.strip():
            raise DatasetError(f"line {line_no}: field {name!r} must be a non-empty string")
    if record["category"] not in CATEGORIES:
        raise DatasetError(
            f"line {line_no}: unknown category {record['category']!r}; expected one of {sorted(CATEGORIES)}"
        )
    if record["expected_behavior"] not in EXPECTED_BEHAVIORS:
        raise DatasetError(
            f"line {line_no}: unknown expected_behavior {record['expected_behavior']!r}; "
            f"expected one of {sorted(EXPECTED_BEHAVIORS)}"
        )
    extra = set(record) - set(REQUIRED_FIELDS)
    if extra:
        raise DatasetError(f"line {line_no}: unexpected field(s): {', '.join(sorted(extra))}")
    return EvalExample(**{f: record[f].strip() for f in REQUIRED_FIELDS})


def parse_jsonl(text: str) -> list[EvalExample]:
    examples: list[EvalExample] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"line {line_no}: invalid JSON ({exc.msg})") from exc
        example = validate_record(record, line_no)
        if example.id in seen:
            raise DatasetError(f"line {line_no}: duplicate id {example.id!r}")
        seen.add(example.id)
        examples.append(example)
    if not examples:
        raise DatasetError("dataset contains no examples")
    return examples


def load_dataset(path: str | Path | None = None) -> EvalDataset:
    path = Path(path) if path else DEFAULT_DATASET_PATH
    if not path.is_file():
        raise DatasetError(f"dataset file not found: {path}")
    raw = path.read_bytes()
    examples = parse_jsonl(raw.decode("utf-8"))
    return EvalDataset(
        name=path.stem,
        path=path.resolve(),
        sha256=hashlib.sha256(raw).hexdigest(),
        examples=examples,
    )
