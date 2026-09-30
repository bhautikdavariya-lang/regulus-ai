"""Canonical dashboard schemas.

Every artifact family is normalised into these structures before anything
downstream sees it, so the API and the UI never depend on the shape of a
particular file on disk. All are frozen and serialisable.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

# experiment status
CURRENT = "CURRENT"
HISTORICAL = "HISTORICAL"
STALE = "STALE"
INCOMPLETE = "INCOMPLETE"
FAILED = "FAILED"
UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
# What an adapter reports when the artifacts are whole. Freshness is not an
# adapter's business: the registry decides whether a complete run is CURRENT,
# HISTORICAL or STALE, because that needs every other run to be known.
COMPLETE = "COMPLETE"
STATUSES = (COMPLETE, CURRENT, HISTORICAL, STALE, INCOMPLETE, FAILED, UNSUPPORTED_SCHEMA)
COMPLETE_STATUSES = (COMPLETE, CURRENT, HISTORICAL, STALE)

# Sentinel for a run whose artifacts do not say which weights were evaluated.
# It is never guessed from the current configuration: an unrecorded model is
# reported as unrecorded, and comparison must refuse it.
UNRECORDED = "unrecorded"
# Sentinel for a run that legitimately involved no answer model at all, such
# as a retrieval-only evaluation. Distinct from UNRECORDED: here nothing is
# missing, there is simply no model to name.
NOT_APPLICABLE = "not_applicable"
NO_MODEL = (UNRECORDED, NOT_APPLICABLE)

# metric direction
HIGHER_IS_BETTER = "higher_is_better"
LOWER_IS_BETTER = "lower_is_better"
INFORMATIONAL = "informational"
DIRECTIONS = (HIGHER_IS_BETTER, LOWER_IS_BETTER, INFORMATIONAL)

# metric units
RATIO = "ratio"
COUNT = "count"
SECONDS = "seconds"
TOKENS = "tokens"
# A number on a scale the artifact does not define, such as a human
# reviewer's score. It is never rendered as a percentage, because it is not
# a proportion of anything.
SCORE = "score"
UNITS = (RATIO, COUNT, SECONDS, TOKENS, SCORE)

# metric status
OK = "ok"
MISSING = "missing"
INCONSISTENT = "inconsistent"

# experiment kinds
KIND_EVALUATION = "evaluation"
KIND_TRAINING = "training"


def stable_id(kind: str, identifier: str) -> str:
    """Deterministic experiment id from a kind and an artifact path."""
    return hashlib.sha1(f"{kind}:{identifier}".encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ModelIdentity:
    base_model_id: str
    revision: str | None = None
    adapter_id: str | None = None
    adapter_path: str | None = None
    checkpoint: str | None = None
    dtype: str | None = None
    device: str | None = None

    @property
    def checkpoint_unresolved(self) -> bool:
        """An adapter is named but not which of its checkpoints was loaded.

        Every checkpoint of an adapter is a different set of weights, so the
        adapter name alone does not identify what was evaluated.
        """
        return self.base_model_id not in NO_MODEL and bool(self.adapter_id) and not self.checkpoint

    @property
    def recorded(self) -> bool:
        """False when no weights can be named for this run."""
        return self.base_model_id not in NO_MODEL and not self.checkpoint_unresolved

    @property
    def applicable(self) -> bool:
        """False when the run legitimately had no answer model."""
        return self.base_model_id != NOT_APPLICABLE

    @property
    def key(self) -> str:
        """Two evaluations share a key only if they measured the same weights."""
        if self.base_model_id in NO_MODEL:
            # Deliberately not "...+base": an artifact that omits the adapter
            # has not told us there was no adapter.
            return self.base_model_id
        base = f"{self.base_model_id}@{self.revision or 'default'}"
        if self.checkpoint_unresolved:
            # Never "<adapter>@adapter": that would merge every checkpoint of
            # the adapter into one identity. The prefix keeps it from ever
            # equalling a resolved key.
            return f"{UNRECORDED}:{base}+{self.adapter_id}@checkpoint-unresolved"
        if not self.adapter_id:
            return f"{base}+base"
        return f"{base}+{self.adapter_id}@{self.checkpoint}"

    @property
    def label(self) -> str:
        if not self.applicable:
            return "no answer model (retrieval only)"
        if self.checkpoint_unresolved:
            return f"{self.base_model_id} + {self.adapter_id} (checkpoint not recorded, so the weights are unresolved)"
        if not self.recorded:
            return "model not recorded by this artifact"
        if not self.adapter_id:
            return f"{self.base_model_id} (base, no adapter)"
        ckpt = f" / {self.checkpoint}" if self.checkpoint else ""
        return f"{self.base_model_id} + {self.adapter_id}{ckpt}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "key": self.key, "label": self.label,
                "recorded": self.recorded, "applicable": self.applicable,
                "checkpoint_unresolved": self.checkpoint_unresolved}


@dataclass(frozen=True)
class CurrentSystem:
    """What the configuration says the system runs right now.

    Built by `registry.read_current_system` from `regulus.system_identity`.
    `resolved` is False whenever something needed to name the weights or the
    pipeline could not be established; nothing is then CURRENT.
    """

    model: ModelIdentity
    pipeline_fingerprint: dict[str, Any] | None = None
    evaluation_config: dict[str, Any] | None = None
    unresolved: tuple[str, ...] = ()
    source: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return not self.unresolved and self.model.recorded and self.pipeline_fingerprint is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model.to_dict(),
            "pipeline_fingerprint": self.pipeline_fingerprint,
            "evaluation_config": self.evaluation_config,
            "resolved": self.resolved,
            "unresolved": list(self.unresolved),
            "source": self.source,
        }


@dataclass(frozen=True)
class BenchmarkIdentity:
    benchmark_id: str
    version: str | None = None
    path: str | None = None
    sha256: str | None = None
    questions: int | None = None
    categories: tuple[str, ...] = ()
    protected: bool | None = None

    @property
    def key(self) -> str:
        """Content-addressed: two files with the same name but different text differ."""
        return f"{self.benchmark_id}@{(self.sha256 or 'unknown')[:12]}"

    @property
    def label(self) -> str:
        n = f", {self.questions} questions" if self.questions is not None else ""
        return f"{self.benchmark_id}{('/' + self.version) if self.version else ''}{n}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "categories": list(self.categories), "key": self.key, "label": self.label}


@dataclass(frozen=True)
class MetricResult:
    key: str
    display_name: str
    value: float | None
    unit: str = RATIO
    direction: str = INFORMATIONAL
    numerator: int | None = None
    denominator: int | None = None
    definition_key: str | None = None
    source: str | None = None
    status: str = OK
    note: str | None = None
    # What the dashboard itself recomputed this value from, when it did (for
    # example "per-question records"), so a reader can tell a cross-checked
    # number from one copied out of an aggregate. None means not recomputed.
    recomputed_from: str | None = None

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise ValueError(f"unknown unit {self.unit!r}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {self.direction!r}")
        if self.status not in (OK, MISSING, INCONSISTENT):
            raise ValueError(f"unknown metric status {self.status!r}")

    @property
    def sample_note(self) -> str | None:
        if self.numerator is None or self.denominator is None:
            return None
        return f"{self.numerator} / {self.denominator}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "definition_key": self.definition_key or self.key, "sample_note": self.sample_note}


@dataclass(frozen=True)
class QuestionResult:
    """One evaluated question, with everything needed to debug it.

    Fields absent from the source artifact stay None; nothing is invented.
    """

    id: str
    question: str
    category: str | None = None
    expected_behavior: str | None = None
    expected_requirements: tuple[str, ...] = ()
    expected_terms: tuple[str, ...] = ()
    domain: str | None = None
    # plan and evidence
    plan_kind: str | None = None
    detected_requirements: tuple[str, ...] = ()
    requirement_status: dict[str, Any] = field(default_factory=dict)
    coverage_state: str | None = None
    evidence_by_tier: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    selected_evidence: list[dict[str, Any]] = field(default_factory=list)
    # generation
    generated: bool = False
    skipped_reason: str | None = None
    answer_raw: str | None = None
    answer_final: str | None = None
    repair: str | None = None
    validation_raw: dict[str, Any] = field(default_factory=dict)
    validation_final: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    claims_raw: list[dict[str, Any]] = field(default_factory=list)
    claims_final: list[dict[str, Any]] = field(default_factory=list)
    # per-question outcomes
    correct_raw: bool | None = None
    correct_final: bool | None = None
    correct_reasons_raw: tuple[str, ...] = ()
    correct_reasons_final: tuple[str, ...] = ()
    hallucination_raw: bool | None = None
    hallucination_final: bool | None = None
    citation_ok: bool | None = None
    truncated: bool | None = None
    refusal: dict[str, Any] = field(default_factory=dict)
    failure_layer: str | None = None
    failure_reasons: tuple[str, ...] = ()
    # controlled (exact-evidence-only) condition
    controlled_generated: bool | None = None
    controlled_valid_raw: bool | None = None
    controlled_answer_raw: str | None = None
    # cost
    latency_ms: dict[str, float] = field(default_factory=dict)
    tokens: dict[str, Any] = field(default_factory=dict)
    # Artifact detail that has no canonical home. Adapters put the rest of
    # what the record holds here rather than dropping it, so the forensic
    # view can show everything the run actually recorded.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_ms(self) -> float | None:
        return self.latency_ms.get("total_ms")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in ("expected_requirements", "expected_terms", "detected_requirements", "correct_reasons_raw", "correct_reasons_final", "failure_reasons"):
            d[key] = list(d[key])
        d["total_ms"] = self.total_ms
        return d

    def summary_row(self) -> dict[str, Any]:
        """The compact record the question table renders."""
        return {
            "id": self.id, "question": self.question, "category": self.category, "domain": self.domain,
            "expected_behavior": self.expected_behavior, "generated": self.generated, "skipped_reason": self.skipped_reason,
            "correct_raw": self.correct_raw, "correct_final": self.correct_final,
            "validation_raw": (self.validation_raw or {}).get("status"), "validation_final": (self.validation_final or {}).get("status"),
            "repair": self.repair, "hallucination_raw": self.hallucination_raw, "citation_ok": self.citation_ok,
            "truncated": self.truncated, "failure_layer": self.failure_layer,
            "claims_unsupported_raw": sum(1 for c in self.claims_raw if c.get("supported") == "NO"),
            "false_refusal": (self.refusal or {}).get("false_refusal"),
            "total_ms": self.total_ms, "tokens_generated": (self.tokens or {}).get("generated"),
        }


@dataclass(frozen=True)
class Checkpoint:
    name: str
    step: int | None = None
    training_loss: float | None = None
    validation_loss: float | None = None
    created_at: str | None = None
    path: str | None = None
    size_bytes: int | None = None
    is_selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrainingRun:
    training_run_id: str
    name: str
    path: str
    model: ModelIdentity
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    dataset: dict[str, Any] = field(default_factory=dict)
    lora: dict[str, Any] = field(default_factory=dict)
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    curves: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    checkpoints: tuple[Checkpoint, ...] = ()
    resources: dict[str, Any] = field(default_factory=dict)
    losses: dict[str, Any] = field(default_factory=dict)
    # Training-process metrics only. They are never mixed with evaluation
    # metrics: a loss is not an accuracy, and the registry's definitions say so.
    metrics: tuple[MetricResult, ...] = ()
    source_artifacts: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    def metric(self, key: str) -> MetricResult | None:
        return next((m for m in self.metrics if m.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "training_run_id": self.training_run_id, "name": self.name, "path": self.path, "model": self.model.to_dict(),
            "status": self.status, "started_at": self.started_at, "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds, "dataset": self.dataset, "lora": self.lora,
            "hyperparameters": self.hyperparameters, "curves": self.curves,
            "checkpoints": [c.to_dict() for c in self.checkpoints], "resources": self.resources, "losses": self.losses,
            "metrics": [m.to_dict() for m in self.metrics],
            "source_artifacts": list(self.source_artifacts), "problems": list(self.problems),
        }


@dataclass(frozen=True)
class EvaluationRun:
    evaluation_run_id: str
    name: str
    path: str
    schema: str
    model: ModelIdentity
    benchmark: BenchmarkIdentity | None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    configuration: dict[str, Any] = field(default_factory=dict)
    metrics: tuple[MetricResult, ...] = ()
    questions: tuple[QuestionResult, ...] = ()
    failure_summary: dict[str, Any] = field(default_factory=dict)
    # Aggregates that are not single numbers (per-category tables, status
    # counts, repair kinds, latency phases). They are real artifact data and
    # belong in the run, but they are not MetricResults.
    breakdowns: dict[str, Any] = field(default_factory=dict)
    source_artifacts: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    git_revision: str | None = None
    # Which questions were actually evaluated, and whether they are the whole
    # benchmark. `status` says the process completed; `full_benchmark` here
    # says whether the benchmark did (True, False, or None when unknown).
    question_set: dict[str, Any] = field(default_factory=dict)
    # The recorded pipeline fingerprint with a `verified` flag, or None.
    pipeline_fingerprint: dict[str, Any] | None = None

    @property
    def full_benchmark(self) -> bool | None:
        return self.question_set.get("full_benchmark")

    def metric(self, key: str) -> MetricResult | None:
        return next((m for m in self.metrics if m.key == key), None)

    def to_dict(self, include_questions: bool = False) -> dict[str, Any]:
        d = {
            "evaluation_run_id": self.evaluation_run_id, "name": self.name, "path": self.path, "schema": self.schema,
            "model": self.model.to_dict(), "benchmark": self.benchmark.to_dict() if self.benchmark else None,
            "question_set": self.question_set, "pipeline_fingerprint": self.pipeline_fingerprint,
            "status": self.status, "started_at": self.started_at, "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds, "configuration": self.configuration,
            "metrics": [m.to_dict() for m in self.metrics], "failure_summary": self.failure_summary,
            "breakdowns": self.breakdowns,
            "source_artifacts": list(self.source_artifacts), "problems": list(self.problems),
            "git_revision": self.git_revision, "question_count": len(self.questions),
        }
        if include_questions:
            d["questions"] = [q.to_dict() for q in self.questions]
        return d


@dataclass(frozen=True)
class Experiment:
    """An evaluation or training run, with its identity and status resolved."""

    experiment_id: str
    name: str
    kind: str
    status: str
    path: str
    model: ModelIdentity
    benchmark: BenchmarkIdentity | None = None
    evaluation_run_id: str | None = None
    training_run_id: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    git_revision: str | None = None
    configuration: dict[str, Any] = field(default_factory=dict)
    source_artifacts: tuple[str, ...] = ()
    metric_summary: dict[str, Any] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    status_reason: str | None = None
    question_set: dict[str, Any] = field(default_factory=dict)
    pipeline_fingerprint: dict[str, Any] | None = None
    # Machine-readable reason for `status` (regulus.dashboard.freshness codes).
    freshness_code: str | None = None
    # Per-check outcomes behind that decision: model, question_set, pipeline.
    freshness_checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id, "name": self.name, "kind": self.kind, "status": self.status,
            "status_reason": self.status_reason,
            "freshness": {"status": self.status, "code": self.freshness_code, "reason": self.status_reason,
                          "checks": self.freshness_checks},
            "path": self.path, "model": self.model.to_dict(),
            "benchmark": self.benchmark.to_dict() if self.benchmark else None,
            "question_set": self.question_set, "pipeline_fingerprint": self.pipeline_fingerprint,
            "evaluation_run_id": self.evaluation_run_id, "training_run_id": self.training_run_id,
            "created_at": self.created_at, "completed_at": self.completed_at, "git_revision": self.git_revision,
            "configuration": self.configuration, "source_artifacts": list(self.source_artifacts),
            "metric_summary": self.metric_summary, "problems": list(self.problems),
        }
