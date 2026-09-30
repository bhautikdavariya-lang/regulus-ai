"""Evaluation datasets, runners and result records.

Imports here are lazy. `regulus.evaluation.runner` reaches the inference
stack and therefore torch, which costs about twenty seconds to import and
several hundred megabytes of memory. Two callers must never pay that:

* the dashboard, whose whole guarantee is that it loads no model - it would
  otherwise drag torch into a process that only reads JSON;
* `regulus.evaluation.acceptance_benchmark`, which is pure standard library
  and reads a workbook.

So the names below resolve on first use (PEP 562) rather than at import.
`from regulus.evaluation import run_evaluation` behaves exactly as before and
pays the cost then; `from regulus.evaluation.acceptance_benchmark import ...`
now costs nothing.
"""

from __future__ import annotations

from typing import Any

# name -> submodule that defines it
_EXPORTS = {
    "CATEGORIES": "regulus.evaluation.dataset",
    "EXPECTED_BEHAVIORS": "regulus.evaluation.dataset",
    "DatasetError": "regulus.evaluation.dataset",
    "EvalDataset": "regulus.evaluation.dataset",
    "EvalExample": "regulus.evaluation.dataset",
    "load_dataset": "regulus.evaluation.dataset",
    "EvaluationRun": "regulus.evaluation.results",
    "QuestionResult": "regulus.evaluation.results",
    "aggregate": "regulus.evaluation.results",
    "load_run": "regulus.evaluation.results",
    "result_filename": "regulus.evaluation.results",
    "save_run": "regulus.evaluation.results",
    "AnswerFn": "regulus.evaluation.runner",
    "build_run_metadata": "regulus.evaluation.runner",
    "run_evaluation": "regulus.evaluation.runner",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value          # resolve once, then it is an ordinary global
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
