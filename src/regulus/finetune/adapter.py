"""Loading a saved Stage 12 adapter for inference, and the inference check."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from peft import PeftModel

from regulus.config import GenerationConfig, ModelConfig
from regulus.inference.generate import generate_chat
from regulus.model import load_model
# Reading an adapter's identity loads nothing, so it lives with the rest of the
# system identity code, where the dashboard can use it without peft or torch.
from regulus.system_identity import AdapterError, adapter_identity  # noqa: F401  (re-exported)


def attach_saved_adapter(model, adapter_dir: Path, *, merge: bool = True):
    """Wrap an already-loaded base model with the adapter; merged by default so
    inference speed equals the base model (the adapter files stay the artifact)."""
    adapter_dir = Path(adapter_dir)
    identity = adapter_identity(adapter_dir)
    base = identity.get("base_model_name_or_path")
    model_id = getattr(model.config, "_name_or_path", None) or getattr(model.config, "name_or_path", None)
    if base and model_id and base != model_id:
        raise AdapterError(f"adapter was trained on {base!r}, loaded base model is {model_id!r}")
    peft_model = PeftModel.from_pretrained(model, str(adapter_dir))
    out = peft_model.merge_and_unload() if merge else peft_model
    out.eval()
    return out, identity


def load_adapter_model(model_cfg: ModelConfig, adapter_dir: Path, *, merge: bool = True, local_files_only: bool = False):
    model = load_model(model_cfg, local_files_only=local_files_only)
    return attach_saved_adapter(model, adapter_dir, merge=merge)


def inference_check(model, tokenizer, messages: list[dict[str, str]], gen: GenerationConfig, *, model_id: str, identity: dict[str, Any], out_path: Path | None = None) -> dict[str, Any]:
    """Generate one answer with the adapter model and record the artifact.
    This verifies that generation works, not that the answer is correct."""
    t0 = time.perf_counter()
    result = generate_chat(model, tokenizer, messages, gen)
    artifact = {
        "model_identifier": model_id,
        "adapter_identifier": {k: identity.get(k) for k in ("adapter_name", "adapter_dir", "r", "lora_alpha", "target_modules", "dataset_hash", "best_checkpoint")},
        "system": next((m["content"] for m in messages if m["role"] == "system"), None),
        "question_and_context": messages[-1]["content"],
        "generated_answer": result.response,
        "prompt_tokens": result.prompt_tokens,
        "generated_tokens": result.generated_tokens,
        "seconds": round(time.perf_counter() - t0, 2),
        "generation": {"max_new_tokens": gen.max_new_tokens, "do_sample": gen.do_sample, "enable_thinking": gen.enable_thinking},
        "note": "functional check only: successful generation does not establish factual correctness",
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return artifact
