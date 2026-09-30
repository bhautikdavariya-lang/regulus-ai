"""What a Stage 5 run evaluated, recorded in its own manifest.

Everything here is read from the objects the run actually uses: the loaded
generator for the weights and decoding, the `RagConfig` for the pipeline. The
configuration sections and their normalisation come from
`regulus.system_identity`, the same code the dashboard uses to describe the
currently configured system, so the two fingerprints are computed identically.

Manifest schema version 2 adds, beside the version 1 keys it keeps unchanged:

    schema_version        2
    started_at            UTC ISO-8601 of the first invocation (null when a
                          version 1 manifest is resumed: that time is unknown)
    completed_at          UTC ISO-8601 when the report phase finished
    invocations           one entry per invocation of the runner
    question_set          identity of the requested question ids
    evaluation_config     the evaluation-relevant configuration
    pipeline_fingerprint  its fingerprint (regulus.dashboard.fingerprint)
    model                 the resolved weights, written when the model loads
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from regulus.system_identity import (  # noqa: F401  (re-exported for Stage 5 callers)
    CHECKPOINT_RE,
    decoding_config,
    pipeline_config,
    resolve_adapter,
)
from regulus.system_identity import evaluation_config as _evaluation_config

MANIFEST_SCHEMA_VERSION = 2


def utc_now() -> str:
    """The one timestamp format this package writes: timezone-aware UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evaluation_config(config: Any, generator: Any | None) -> dict[str, Any]:
    """The evaluation configuration of this run; decoding from the loaded
    generator's own GenerationConfig, or absent before a model is loaded."""
    return _evaluation_config(config, getattr(generator, "gen", None) if generator is not None else None)


def model_block(generator: Any) -> dict[str, Any]:
    """The resolved weights, read from the generator the run just loaded.

    `system_identity` is attached by `regulus.rag.load_qwen_generator`: the
    configured base model id (the generator's own `model_id` includes the
    adapter) and the identity of the adapter merged into it, if any.
    """
    described = generator.describe() or {}
    attached = getattr(generator, "system_identity", None) or {}
    adapter = attached.get("adapter")
    resolved = resolve_adapter(adapter)
    return {
        "id": attached.get("base_model_id") or described.get("model_id"),
        "revision": described.get("model_revision"),
        "adapter_dir": (adapter or {}).get("adapter_dir"),
        "adapter_name": resolved.get("adapter_name"),
        "checkpoint": resolved.get("checkpoint"),
        "checkpoint_source": resolved.get("checkpoint_source"),
        "adapter_base_model": (adapter or {}).get("base_model_name_or_path"),
        "adapter_dataset_hash": (adapter or {}).get("dataset_hash"),
        "dtype": described.get("dtype"),
        "device": described.get("device"),
        "resolved_from": "the loaded model (QwenGenerator.describe)",
    }
