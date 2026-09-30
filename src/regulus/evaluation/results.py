"""Result records, aggregation and JSON persistence for evaluation runs.

File naming convention (documented in README):
    data/evaluation/results/<pipeline>_<YYYYmmdd>_<HHMMSS>_<run_id>.json
e.g. baseline_20260915_153012_a1b2c3d4.json
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from regulus.config import PROJECT_ROOT
from regulus.evaluation.dataset import CATEGORIES, EvalExample

DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "evaluation" / "results"
SCHEMA_VERSION = 1
MANUAL_SCORES = {0: "incorrect", 1: "partially correct", 2: "correct"}


class ResultsError(ValueError):
    """Raised when a results file cannot be read or is malformed."""


@dataclass
class QuestionResult:
    question_id: str
    category: str
    question: str
    reference_answer: str
    evaluation_notes: str
    expected_behavior: str
    status: str  # "completed" | "failed"
    model_answer: str | None = None
    error: str | None = None
    generation_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens_per_second: float | None = None
    # Manual quality assessment; left unset by the runner on purpose.
    quality_score: int | None = None
    manual_evaluation: dict[str, Any] | None = None
    # Pipeline diagnostics (e.g. RAG: retrieved sources, context, citations).
    # None for the raw-model baseline.
    diagnostics: dict[str, Any] | None = None
    citations: list[dict[str, Any]] | None = None

    @classmethod
    def from_example(cls, ex: EvalExample, **kwargs: Any) -> "QuestionResult":
        return cls(
            question_id=ex.id,
            category=ex.category,
            question=ex.question,
            reference_answer=ex.reference_answer,
            evaluation_notes=ex.evaluation_notes,
            expected_behavior=ex.expected_behavior,
            **kwargs,
        )


@dataclass
class EvaluationRun:
    run: dict[str, Any]
    results: list[QuestionResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run": self.run,
            "summary": self.summary,
            "results": [asdict(r) for r in self.results],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationRun":
        try:
            results = [QuestionResult(**r) for r in data["results"]]
            return cls(
                run=data["run"],
                results=results,
                summary=data.get("summary", {}),
                schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            )
        except (KeyError, TypeError) as exc:
            raise ResultsError(f"malformed results file: {exc}") from exc


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 3) if values else None


def aggregate(results: list[QuestionResult]) -> dict[str, Any]:
    """Objective, transparent statistics. No answer-quality guessing."""
    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status == "failed"]

    by_category: dict[str, dict[str, int]] = {}
    for key in CATEGORIES:
        rows = [r for r in results if r.category == key]
        if rows:
            by_category[key] = {
                "total": len(rows),
                "completed": sum(1 for r in rows if r.status == "completed"),
                "failed": sum(1 for r in rows if r.status == "failed"),
            }

    scored = [r for r in results if r.quality_score is not None]
    manual: dict[str, Any] = {"scored": len(scored), "unscored": len(results) - len(scored)}
    if scored:
        manual["mean_score"] = _avg([r.quality_score for r in scored])
        manual["by_category"] = {
            key: _avg([r.quality_score for r in scored if r.category == key])
            for key in by_category
            if any(r.category == key for r in scored)
        }

    return {
        "total": len(results),
        "completed": len(completed),
        "failed": len(failed),
        "failed_ids": [r.question_id for r in failed],
        "avg_generation_seconds": _avg([r.generation_seconds for r in completed]),
        "total_generation_seconds": round(sum(r.generation_seconds or 0 for r in completed), 3),
        "avg_input_tokens": _avg([r.input_tokens for r in completed]),
        "avg_output_tokens": _avg([r.output_tokens for r in completed]),
        "avg_tokens_per_second": _avg([r.tokens_per_second for r in completed]),
        "by_category": by_category,
        "manual_evaluation": manual,
    }


def result_filename(pipeline: str, run_id: str, when: datetime) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pipeline) or "run"
    return f"{safe}_{when.strftime('%Y%m%d_%H%M%S')}_{run_id}.json"


def save_run(run: EvaluationRun, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(run.to_dict(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def load_run(path: str | Path) -> EvaluationRun:
    path = Path(path)
    if not path.is_file():
        raise ResultsError(f"results file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResultsError(f"results file is not valid JSON: {path} ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise ResultsError(f"results file must contain a JSON object: {path}")
    return EvaluationRun.from_dict(data)


def latest_result(results_dir: Path = DEFAULT_RESULTS_DIR) -> Path | None:
    files = sorted(results_dir.glob("*.json"))
    return files[-1] if files else None
