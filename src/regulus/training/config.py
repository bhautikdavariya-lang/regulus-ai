"""Training-data configuration (configs/training.yaml + CLI overrides).

Mirrors the style of regulus.config.settings: a YAML file with dataclass
defaults, validated once. No secrets live here; the database URL still comes
from REGULUS_DATABASE_URL through regulus.retrieval.db.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from regulus.config import PROJECT_ROOT

DEFAULT_TRAINING_CONFIG_PATH = PROJECT_ROOT / "configs" / "training.yaml"

# Stage 11 categories, then the Stage 13 grounding categories. A category with
# no share in the config is never generated, so configs/training.yaml (which
# lists only the first nine) still reproduces the v1 dataset byte for byte.
STAGE11_CATEGORIES = (
    "direct_cfr",
    "section_paragraph",
    "definition",
    "relationship",
    "fda_guidance",
    "cfr_vs_guidance",
    "citation",
    "multi_context",
    "abstention",
)
STAGE13_CATEGORIES = (
    "context_mismatch",
    "wrong_context",
    "partial_context",
    "guidance_mismatch",
    "citation_grounding",
)
# Stage 14 answer-side categories, added to counter the Stage 13 over-refusal
STAGE14_CATEGORIES = (
    "grounded_definition",
    "grounded_topic",
    "guidance_answer",
)
# Stage 6 answer-side categories in the Stage 4 generation contract: several
# requested provisions, ranges, and a requested provision proven absent.
# Adding them leaves v1-v3 byte-identical: a category with no share is never
# generated and contributes nothing to the split files.
STAGE6_CATEGORIES = (
    "multi_provision",
    "range_provision",
    "partial_provision",
)
CATEGORIES = STAGE11_CATEGORIES + STAGE13_CATEGORIES + STAGE14_CATEGORIES + STAGE6_CATEGORIES

# categories whose answers must refuse; used by validation and by the metrics
ABSTENTION_CATEGORIES = ("abstention", "context_mismatch", "wrong_context", "partial_context", "guidance_mismatch")

DEFAULT_CATEGORY_SHARES = {
    "direct_cfr": 0.25,
    "section_paragraph": 0.20,
    "definition": 0.10,
    "relationship": 0.10,
    "fda_guidance": 0.15,
    "cfr_vs_guidance": 0.05,
    "citation": 0.05,
    "multi_context": 0.05,
    "abstention": 0.05,
}

DEFAULT_BENCHMARKS = (
    "data/evaluation/datasets/baseline_v1.jsonl",
    "data/evaluation/datasets/retrieval_v1.jsonl",
    "data/evaluation/datasets/retrieval_v2.jsonl",
    "data/evaluation/datasets/stage5_v1.jsonl",
)


class TrainingConfigError(ValueError):
    """Raised for a missing or invalid training configuration."""


@dataclass(frozen=True)
class QualityConfig:
    allow_unverified_sources: bool = False
    min_paragraph_chars: int = 60
    max_paragraph_chars: int = 1500
    max_context_chars: int = 3600
    near_duplicate_jaccard: float = 0.9
    benchmark_jaccard: float = 0.75
    benchmark_jaccard_same_identifiers: float = 0.5
    max_paragraph_examples_per_section: int = 2
    max_definition_examples_per_section: int = 12
    max_guidance_examples_per_document: int = 3
    # Stage 14 generator behaviour. Both default to the v2 behaviour so that
    # configs/training_v2.yaml still reproduces the Stage 13 dataset exactly;
    # configs/training_v3.yaml opts in.
    varied_refusal_openings: bool = False
    guidance_context_negatives: bool = False
    # Stage 6: also drop every example whose split group (section / part) is
    # named by a benchmark question, not just questions that look alike.
    # Defaults to off so v1-v3 reproduce; configs/training_v6.yaml opts in.
    exclude_benchmark_groups: bool = False


@dataclass(frozen=True)
class TrainingConfig:
    version: str = "v1"
    target_examples: int = 10000
    seed: int = 42
    train_ratio: float = 0.8
    validation_ratio: float = 0.1
    test_ratio: float = 0.1
    output_dir: Path = PROJECT_ROOT / "data" / "training" / "datasets"
    use_ecfr: bool = True
    use_guidance: bool = True
    retrievable_guidance_only: bool = True
    quality: QualityConfig = field(default_factory=QualityConfig)
    category_shares: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CATEGORY_SHARES))
    benchmarks: tuple[Path, ...] = field(default_factory=lambda: tuple(PROJECT_ROOT / b for b in DEFAULT_BENCHMARKS))
    source: Path | None = None

    def __post_init__(self) -> None:
        if self.target_examples <= 0:
            raise TrainingConfigError("target_examples must be positive")
        ratios = (self.train_ratio, self.validation_ratio, self.test_ratio)
        if any(r < 0 for r in ratios) or abs(sum(ratios) - 1.0) > 1e-6:
            raise TrainingConfigError("train/validation/test ratios must be >= 0 and sum to 1")
        unknown = set(self.category_shares) - set(CATEGORIES)
        if unknown:
            raise TrainingConfigError(f"unknown categories in config: {sorted(unknown)}")
        if any(v < 0 for v in self.category_shares.values()):
            raise TrainingConfigError("category shares must be >= 0")
        if not self.use_ecfr and not self.use_guidance:
            raise TrainingConfigError("at least one of use_ecfr / use_guidance must be true")
        if self.quality.allow_unverified_sources:
            raise TrainingConfigError("allow_unverified_sources=true is not supported: every example must trace to a database row")

    def category_targets(self) -> dict[str, int]:
        """Absolute per-category caps derived from target_examples and the shares."""
        return {c: int(round(self.target_examples * self.category_shares.get(c, 0.0))) for c in CATEGORIES}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "target_examples": self.target_examples,
            "seed": self.seed,
            "train_ratio": self.train_ratio,
            "validation_ratio": self.validation_ratio,
            "test_ratio": self.test_ratio,
            "output_dir": _rel(self.output_dir),
            "use_ecfr": self.use_ecfr,
            "use_guidance": self.use_guidance,
            "retrievable_guidance_only": self.retrievable_guidance_only,
            "quality": self.quality.__dict__.copy(),
            "category_shares": dict(self.category_shares),
            "benchmarks": [_rel(b) for b in self.benchmarks],
            "source": _rel(self.source) if self.source else None,
        }


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _resolve(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_training_config(path: str | Path | None = None, **overrides: Any) -> TrainingConfig:
    """Load configs/training.yaml; keyword overrides (target_examples, seed, ...)
    take precedence over the file. Unknown override names raise."""
    path = Path(path) if path else DEFAULT_TRAINING_CONFIG_PATH
    if not path.is_file():
        raise TrainingConfigError(f"training config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TrainingConfigError(f"{path} must contain a mapping at top level")
    ds = data.get("dataset", {}) or {}
    src = data.get("sources", {}) or {}
    q = data.get("quality", {}) or {}
    cats = data.get("categories", None)
    benches = data.get("benchmarks", None)

    quality_defaults = QualityConfig()
    quality = QualityConfig(**{k: type(getattr(quality_defaults, k))(q.get(k, getattr(quality_defaults, k))) for k in quality_defaults.__dict__})

    values: dict[str, Any] = {
        "version": str(ds.get("version", "v1")),
        "target_examples": int(ds.get("target_examples", 10000)),
        "seed": int(ds.get("seed", 42)),
        "train_ratio": float(ds.get("train_ratio", 0.8)),
        "validation_ratio": float(ds.get("validation_ratio", 0.1)),
        "test_ratio": float(ds.get("test_ratio", 0.1)),
        "output_dir": _resolve(ds.get("output_dir", "data/training/datasets")),
        "use_ecfr": bool(src.get("use_ecfr", True)),
        "use_guidance": bool(src.get("use_guidance", True)),
        "retrievable_guidance_only": bool(src.get("retrievable_guidance_only", True)),
        "quality": quality,
        "category_shares": {str(k): float(v) for k, v in (cats or DEFAULT_CATEGORY_SHARES).items()},
        "benchmarks": tuple(_resolve(b) for b in (benches if benches is not None else DEFAULT_BENCHMARKS)),
        "source": path,
    }
    unknown = set(overrides) - set(values)
    if unknown:
        raise TrainingConfigError(f"unknown override(s): {sorted(unknown)}")
    for key, value in overrides.items():
        if value is None:
            continue
        values[key] = _resolve(value) if key == "output_dir" else value
    return TrainingConfig(**values)
