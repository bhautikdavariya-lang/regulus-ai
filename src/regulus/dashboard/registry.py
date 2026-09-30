"""Experiment discovery, identity and freshness.

The registry walks a configured set of artifact roots, offers every candidate
to each adapter in turn, and turns what is claimed into `Experiment` records
with a resolved status. Nothing is hard-coded to a particular run: adding a
run directory makes it appear, and removing one makes it disappear.

It writes exactly one file, `artifacts/dashboard/registry.json`, which holds
the names and pins a person has set plus a cache of the last scan. The
artifacts themselves are never touched.

Freshness is decided here rather than in an adapter, because deciding
whether a run is current needs every other run to be known. The rule that
matters most: a historical result is never presented as the current model's
performance, and a run whose model identity was never recorded can never be
called current at all.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import freshness as F
from .adapters import legacy, stage5, training
from .schemas import (
    CURRENT,
    KIND_EVALUATION,
    KIND_TRAINING,
    CurrentSystem,
    EvaluationRun,
    Experiment,
    ModelIdentity,
    TrainingRun,
    stable_id,
)

STORE = Path("artifacts") / "dashboard" / "registry.json"
STORE_VERSION = 1


@dataclass(frozen=True)
class Root:
    """One place to look, and the shape of the candidates inside it."""

    path: str
    pattern: str
    is_file: bool
    label: str


DEFAULT_ROOTS: tuple[Root, ...] = (
    Root("artifacts", "*/*/*", False, "Stage 5 evaluation runs"),
    Root("models/qwen3-0.6b-lora", "*", False, "LoRA training runs"),
    Root("data/evaluation/results", "**/*.json", True, "legacy evaluation results"),
)

# Order matters only in that the first adapter to claim a candidate wins;
# the three detectors are disjoint in practice.
ADAPTERS = (
    ("stage5", stage5, KIND_EVALUATION),
    ("legacy", legacy, KIND_EVALUATION),
    ("training", training, KIND_TRAINING),
)

# The headline numbers each kind of run shows in a list, in this order. A key
# that a run does not have is simply skipped.
SUMMARY_KEYS = (
    "correctness_final", "correctness_raw", "valid_raw", "recall_at_1", "mrr",
    "manual_score_mean", "completion_rate", "final_eval_loss", "base_eval_loss",
    "total_steps", "e2e_latency_p50",
)


@dataclass
class Discovery:
    experiments: list[Experiment] = field(default_factory=list)
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    scanned: int = 0
    seconds: float = 0.0
    scanned_at: str | None = None


# --------------------------------------------------------------- current model


def read_current_system(root: Path) -> CurrentSystem:
    """The system configured to run right now, resolved from the configuration.

    One source: `regulus.system_identity`, which reads `configs/model.yaml`
    through the project's settings loader, so REGULUS_* overrides (model id,
    adapter, cache directory, answer length) apply exactly as they do for the
    answering pipeline and for Stage 5. It loads no model. Anything that cannot
    be established (revision, adapter checkpoint) is listed in `unresolved`,
    and then nothing can be CURRENT.
    """
    root = Path(root)
    config = root / "configs" / "model.yaml"
    if not config.is_file():
        return CurrentSystem(model=ModelIdentity(base_model_id="unknown"),
                             unresolved=(f"{config.as_posix()} could not be read",),
                             source={"config_file": config.as_posix()})
    try:
        from regulus.config import PROJECT_ROOT
        from regulus.system_identity import configured_system

        system = configured_system(config, use_dotenv=root.resolve() == PROJECT_ROOT.resolve())
    except Exception as exc:  # an invalid configuration is reported, never guessed around
        return CurrentSystem(model=ModelIdentity(base_model_id="unknown"),
                             unresolved=(f"the configuration could not be resolved: {type(exc).__name__}: {exc}",),
                             source={"config_file": config.as_posix()})
    m = system.model
    identity = ModelIdentity(
        base_model_id=m["id"], revision=m["revision"], adapter_id=m["adapter_name"],
        adapter_path=m["adapter_dir"], checkpoint=m["checkpoint"], dtype=m["dtype"], device=m["device"],
    )
    return CurrentSystem(
        model=identity,
        pipeline_fingerprint=system.pipeline_fingerprint,
        evaluation_config=system.evaluation_config,
        unresolved=system.unresolved,
        source={**system.source, "checkpoint_source": m["checkpoint_source"],
                "device_configured": m["device_configured"], "dtype_configured": m["dtype_configured"]},
    )


def read_current_model(root: Path) -> tuple[ModelIdentity, str]:
    """The configured model and a one-line description of where it came from."""
    current = read_current_system(root)
    if current.source.get("config_file") and not current.source.get("loader"):
        return current.model, "; ".join(current.unresolved)
    adapter = (f"adapter {current.model.adapter_id} ({current.model.checkpoint or 'checkpoint unresolved'})"
               if current.model.adapter_id else "no adapter configured; the answering pipeline runs the base model")
    return current.model, f"configs/model.yaml via regulus.config.load_settings ({adapter})"


# ------------------------------------------------------------------ discovery


def _candidates(root: Path, roots: Iterable[Root]) -> list[tuple[Root, Path]]:
    out: list[tuple[Root, Path]] = []
    for spec in roots:
        base = root / spec.path
        if not base.is_dir():
            continue
        for candidate in sorted(base.glob(spec.pattern)):
            if spec.is_file and not candidate.is_file():
                continue
            if not spec.is_file and not candidate.is_dir():
                continue
            # never scan the registry's own output
            if STORE.parent.name in candidate.parts and candidate.parts[0] == "artifacts":
                continue
            out.append((spec, candidate))
    return out


def _metric_summary(metrics: Iterable[Any]) -> dict[str, Any]:
    by_key = {m.key: m for m in metrics}
    summary: dict[str, Any] = {}
    for key in SUMMARY_KEYS:
        m = by_key.get(key)
        if m is None or m.value is None:
            continue
        summary[key] = {
            "display_name": m.display_name, "value": m.value, "unit": m.unit,
            "direction": m.direction, "numerator": m.numerator, "denominator": m.denominator,
            "status": m.status,
        }
    return summary


def _experiment(kind: str, name: str, path: Path, root: Path, run: EvaluationRun | TrainingRun) -> Experiment:
    relative = path.relative_to(root).as_posix() if _under(path, root) else path.as_posix()
    is_evaluation = isinstance(run, EvaluationRun)
    return Experiment(
        experiment_id=stable_id(kind, relative),
        name=run.name,
        kind=kind,
        status=run.status,
        path=relative,
        model=run.model,
        benchmark=run.benchmark if is_evaluation else None,
        evaluation_run_id=run.evaluation_run_id if is_evaluation else None,
        training_run_id=None if is_evaluation else run.training_run_id,
        created_at=run.started_at,
        completed_at=run.completed_at,
        git_revision=getattr(run, "git_revision", None),
        configuration=run.configuration if is_evaluation else run.hyperparameters,
        source_artifacts=run.source_artifacts,
        metric_summary=_metric_summary(run.metrics),
        problems=run.problems,
        status_reason=None,
        question_set=dict(run.question_set) if is_evaluation else {},
        pipeline_fingerprint=run.pipeline_fingerprint if is_evaluation else None,
    )


def discover(root: Path, roots: Iterable[Root] = DEFAULT_ROOTS) -> tuple[Discovery, dict[str, Any]]:
    """Scan the roots. Returns the discovery and the loaded runs by id."""
    started = time.perf_counter()
    result = Discovery()
    loaded: dict[str, Any] = {}
    claimed: list[Path] = []

    for spec, candidate in _candidates(root, roots):
        result.scanned += 1
        if any(_under(candidate, done) and candidate != done for done in claimed):
            continue  # inside something an adapter already claimed
        for adapter_name, adapter, kind in ADAPTERS:
            try:
                if not adapter.detect(candidate):
                    continue
            except Exception as exc:  # a detector must never break a scan
                result.errors.append({"path": candidate.as_posix(), "adapter": adapter_name,
                                      "stage": "detect", "error": f"{type(exc).__name__}: {exc}"})
                continue
            try:
                run = adapter.load(candidate, root=root)
            except Exception as exc:
                result.errors.append({"path": candidate.as_posix(), "adapter": adapter_name,
                                      "stage": "load", "error": f"{type(exc).__name__}: {exc}"})
                claimed.append(candidate)
                break
            experiment = _experiment(kind, adapter_name, candidate, root, run)
            result.experiments.append(experiment)
            loaded[experiment.experiment_id] = run
            claimed.append(candidate)
            break
        else:
            result.unsupported.append({
                "path": candidate.relative_to(root).as_posix() if _under(candidate, root) else candidate.as_posix(),
                "root": spec.path, "label": spec.label,
                "reason": "no adapter recognised this artifact",
            })

    result.seconds = round(time.perf_counter() - started, 3)
    result.scanned_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result, loaded


# ----------------------------------------------------------------- freshness


def same_weights(candidate: ModelIdentity, current: ModelIdentity, pinned_model: str | None = None) -> tuple[bool, str | None]:
    """Do these two identities name the same weights?

    Base model, revision, adapter and checkpoint must all be equal; a revision
    missing on either side is not a match. `pinned_model` is accepted for
    older callers and ignored: which model is current comes from the
    configuration alone.
    """
    if not candidate.recorded or not current.recorded:
        return False, None
    code, reason = F._model_check(candidate, current)
    return code == "match", reason


def resolve_freshness(experiments: list[Experiment], current: CurrentSystem, pinned_model: str | None = None) -> list[Experiment]:
    """Turn each adapter's COMPLETE into CURRENT, STALE or HISTORICAL.

    The rules live in `regulus.dashboard.freshness`; see its module docstring.
    `pinned_model` is accepted for older callers and ignored.
    """
    return F.resolve(experiments, current)


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ registry


class Registry:
    """The dashboard's view of every experiment on disk."""

    def __init__(self, root: Path, roots: Iterable[Root] = DEFAULT_ROOTS, store: Path | None = None) -> None:
        self.root = Path(root)
        self.roots = tuple(roots)
        self.store_path = Path(store) if store else self.root / STORE
        self._state = self._read_store()
        self._discovery = Discovery()
        self._runs: dict[str, Any] = {}
        self._experiments: list[Experiment] = []
        self.refresh()

    # ---- persistence (the one file the dashboard writes)

    def _read_store(self) -> dict[str, Any]:
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {
            "version": data.get("version", STORE_VERSION),
            "current_model": data.get("current_model"),
            "names": dict(data.get("names") or {}),
            "pinned": list(data.get("pinned") or []),
            # Empty by default, and deliberately so: the project defines no
            # quality thresholds, and deciding here that 70% is "good" would be
            # a judgment the artifacts do not support. Set an entry per metric
            # key - {"correctness_final": {"good": 0.9, "attention": 0.75}} -
            # and only then does the health page colour that metric.
            "thresholds": dict(data.get("thresholds") or {}),
        }

    def _write_store(self) -> None:
        payload = {
            **self._state,
            "version": STORE_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_scan": {
                "at": self._discovery.scanned_at, "seconds": self._discovery.seconds,
                "experiments": len(self._experiments), "unsupported": len(self._discovery.unsupported),
                "errors": len(self._discovery.errors),
            },
            "experiments": [
                {"experiment_id": e.experiment_id, "name": e.name, "kind": e.kind,
                 "path": e.path, "status": e.status, "model_key": e.model.key,
                 "benchmark_key": e.benchmark.key if e.benchmark else None,
                 "completed_at": e.completed_at}
                for e in self._experiments
            ],
        }
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ---- scanning

    def refresh(self) -> None:
        self._discovery, self._runs = discover(self.root, self.roots)
        self._current = read_current_system(self.root)
        resolved = resolve_freshness(self._discovery.experiments, self._current)
        names = self._state.get("names") or {}
        self._experiments = [
            _renamed(e, names[e.experiment_id]) if e.experiment_id in names else e
            for e in sorted(resolved, key=lambda e: (e.kind, -_epoch(e.completed_at), e.name))
        ]
        self._write_store()

    # ---- reads

    @property
    def experiments(self) -> tuple[Experiment, ...]:
        return tuple(self._experiments)

    def experiment(self, experiment_id: str) -> Experiment | None:
        return next((e for e in self._experiments if e.experiment_id == experiment_id), None)

    def run(self, experiment_id: str) -> Any | None:
        return self._runs.get(experiment_id)

    def evaluation(self, experiment_id: str) -> EvaluationRun | None:
        run = self._runs.get(experiment_id)
        return run if isinstance(run, EvaluationRun) else None

    def training(self, experiment_id: str) -> TrainingRun | None:
        run = self._runs.get(experiment_id)
        return run if isinstance(run, TrainingRun) else None

    @property
    def current_system(self) -> CurrentSystem:
        """The configured system as resolved at the last refresh (the one the
        statuses were decided against)."""
        return self._current

    def current_model(self) -> dict[str, Any]:
        """The canonical current system, and which evaluations measure it."""
        current = self._current
        identity = current.model
        _, source = read_current_model(self.root)
        pinned = self._state.get("current_model")
        evaluations = [
            e for e in self._experiments
            if e.kind == KIND_EVALUATION and e.status == CURRENT
        ]
        return {
            "model": identity.to_dict(),
            "source": source,
            "system": current.to_dict(),
            "resolved": current.resolved,
            "unresolved": list(current.unresolved),
            "pipeline_fingerprint": current.pipeline_fingerprint,
            "pinned_model_key": pinned,
            "pinned_model_note": (
                f"A pinned model key ({pinned}) is stored, but it is ignored: the current system comes from the "
                "configuration alone." if pinned else None
            ),
            "effective_model_key": identity.key,
            "current_evaluations": [
                {"experiment_id": e.experiment_id, "name": e.name,
                 "benchmark": e.benchmark.to_dict() if e.benchmark else None,
                 "completed_at": e.completed_at, "metric_summary": e.metric_summary}
                for e in evaluations
            ],
            "has_current_evaluation": bool(evaluations),
            "note": (
                "No evaluation of the current model exists. Every result below was measured on "
                "something else, and none of them describes what the system does today."
                if not evaluations else None
            ),
        }

    def diagnostics(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for e in self._experiments:
            by_status[e.status] = by_status.get(e.status, 0) + 1
        return {
            "roots": [{"path": r.path, "pattern": r.pattern, "label": r.label,
                       "exists": (self.root / r.path).is_dir()} for r in self.roots],
            "scanned_candidates": self._discovery.scanned,
            "scanned_at": self._discovery.scanned_at,
            "scan_seconds": self._discovery.seconds,
            "experiments": len(self._experiments),
            "by_status": by_status,
            "by_kind": {k: sum(1 for e in self._experiments if e.kind == k) for k in (KIND_EVALUATION, KIND_TRAINING)},
            "by_schema": _count(getattr(self._runs.get(e.experiment_id), "schema", "training")
                                for e in self._experiments),
            "unsupported": self._discovery.unsupported,
            "errors": self._discovery.errors,
            "store": {"path": self.store_path.as_posix(), "exists": self.store_path.is_file(),
                      "names": len(self._state.get("names") or {}), "pinned": self._state.get("pinned") or []},
            "problems": [
                {"experiment_id": e.experiment_id, "name": e.name, "problems": list(e.problems)}
                for e in self._experiments if e.problems
            ],
        }

    # ---- the small amount of state a person can set

    def rename(self, experiment_id: str, name: str | None) -> None:
        names = self._state.setdefault("names", {})
        if name:
            names[experiment_id] = name
        else:
            names.pop(experiment_id, None)
        self.refresh()

    def set_pinned_model(self, model_key: str | None) -> None:
        self._state["current_model"] = model_key or None
        self.refresh()

    def pin(self, experiment_id: str, pinned: bool = True) -> None:
        current = set(self._state.get("pinned") or [])
        current.add(experiment_id) if pinned else current.discard(experiment_id)
        self._state["pinned"] = sorted(current)
        self._write_store()

    @property
    def pinned(self) -> tuple[str, ...]:
        return tuple(self._state.get("pinned") or [])

    @property
    def thresholds(self) -> dict[str, Any]:
        """Per-metric quality thresholds, if anyone has configured any."""
        return dict(self._state.get("thresholds") or {})

    def set_threshold(self, metric_key: str, good: float | None, attention: float | None = None) -> None:
        thresholds = dict(self._state.get("thresholds") or {})
        if good is None:
            thresholds.pop(metric_key, None)
        else:
            thresholds[metric_key] = {"good": good, "attention": attention}
        self._state["thresholds"] = thresholds
        self._write_store()


def _renamed(experiment: Experiment, name: str) -> Experiment:
    return replace(experiment, name=name)


def _epoch(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    for form in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(timestamp, form).timestamp()
        except ValueError:
            continue
    return 0.0


def _count(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value)
        out[key] = out.get(key, 0) + 1
    return out
