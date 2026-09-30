"""Stage 11: instruction-tuning dataset preparation from the read-only
regulatory database. No model is involved; answers are built from verbatim
database text and deterministic templates."""

from regulus.training.config import CATEGORIES, TrainingConfig, TrainingConfigError, load_training_config
from regulus.training.models import ContextItem, ExampleError, TrainingExample, read_jsonl, to_messages, write_jsonl
from regulus.training.pipeline import PipelineError, PrepareResult, build_examples, dataset_paths, manifest_path, prepare_dataset
from regulus.training.validate import ValidationReport, validate_dataset

__all__ = [
    "CATEGORIES",
    "ContextItem",
    "ExampleError",
    "PipelineError",
    "PrepareResult",
    "TrainingConfig",
    "TrainingConfigError",
    "TrainingExample",
    "ValidationReport",
    "build_examples",
    "dataset_paths",
    "load_training_config",
    "manifest_path",
    "prepare_dataset",
    "read_jsonl",
    "to_messages",
    "validate_dataset",
    "write_jsonl",
]
