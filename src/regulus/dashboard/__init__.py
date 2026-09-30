"""Model evaluation, experiment tracking and failure analysis dashboard.

Read-only. This package discovers evaluation and training artifacts,
normalises them into canonical schemas, and serves them. It never writes to
the regulatory database, never loads a model, and never modifies an existing
artifact. The only file it writes is its own registry.
"""

from .metrics import (
    MetricDefinition,
    UnknownMetricError,
    all_definitions,
    definition,
    definitions_payload,
    has_definition,
    make_metric,
    ratio_metric,
)
from .schemas import (
    BenchmarkIdentity,
    Checkpoint,
    EvaluationRun,
    Experiment,
    MetricResult,
    ModelIdentity,
    QuestionResult,
    TrainingRun,
    stable_id,
)

__all__ = [
    "BenchmarkIdentity", "Checkpoint", "EvaluationRun", "Experiment",
    "MetricDefinition", "MetricResult", "ModelIdentity", "QuestionResult",
    "TrainingRun", "UnknownMetricError", "all_definitions", "definition",
    "definitions_payload", "has_definition", "make_metric", "ratio_metric",
    "stable_id",
]
