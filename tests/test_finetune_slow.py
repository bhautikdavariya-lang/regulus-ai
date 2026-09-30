"""Stage 12 slow tests: the real Qwen3-0.6B base model with the saved
stage12_v1 adapter. Excluded by default; run with `pytest -m slow`.
Skipped when the adapter has not been trained yet."""

from __future__ import annotations

import json

import pytest

from regulus.config import GenerationConfig
from regulus.finetune import DEFAULT_ADAPTER_DIR, adapter_identity, load_adapter_model
from regulus.finetune.data import verify_dataset
from regulus.finetune.config import load_finetune_config
from regulus.inference.generate import generate_chat
from regulus.model import load_tokenizer
from regulus.rag.prompt import build_messages

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def cfg():
    return load_finetune_config()


def test_saved_adapter_reloads_and_generates_through_the_rag_prompt(cfg):
    adapter = cfg.output_dir / "adapter"
    if not (adapter / "adapter_config.json").is_file():
        pytest.skip("stage12_v1 adapter not trained yet")
    ident = adapter_identity(adapter)
    assert ident["base_model_name_or_path"] == cfg.model.id and ident["r"] == cfg.lora.r
    meta = json.loads((cfg.output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["stage"] == 12 and meta["dataset"]["hash"] == cfg.dataset.expected_hash
    tokenizer = load_tokenizer(cfg.model, local_files_only=True)
    model, _ = load_adapter_model(cfg.model, adapter, merge=True, local_files_only=True)
    messages = build_messages("What does 21 CFR 820.10 cover?", "SOURCE 1\nCorpus: eCFR\nCitation: 21 CFR 820.10\nURL: not available\nText:\nA manufacturer subject to this part as described by § 820.1(a) must document a quality management system.")
    result = generate_chat(model, tokenizer, messages, GenerationConfig(max_new_tokens=32, do_sample=False, enable_thinking=False))
    assert result.generated_tokens > 0 and result.response.strip()
    assert DEFAULT_ADAPTER_DIR == adapter


def test_training_did_not_touch_protected_files(cfg):
    summary_path = cfg.output_dir / "training_summary.json"
    if not summary_path.is_file():
        pytest.skip("stage12_v1 not trained yet")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    from regulus.finetune.data import protected_hashes

    assert protected_hashes(cfg.dataset.protected) == summary["protected_files_sha256"]
    assert verify_dataset(cfg.dataset)["dataset_sha256"] == summary["dataset_identity"]["dataset_sha256"]
