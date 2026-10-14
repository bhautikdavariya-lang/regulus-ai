"""Tokenizer tests. These need the model files in the cache (run
scripts/download_model.py once); they are skipped otherwise. No model weights
are loaded here."""

import pytest

from regulus.model import ModelLoadError, load_tokenizer


@pytest.fixture(scope="module")
def tokenizer(settings):
    try:
        return load_tokenizer(settings.model, local_files_only=True)
    except ModelLoadError as exc:
        pytest.skip(f"tokenizer not in local cache: {exc}")


def test_tokenizer_roundtrip(tokenizer):
    text = "The FDA regulates food, drugs, and medical devices."
    ids = tokenizer(text)["input_ids"]
    assert len(ids) > 0
    assert tokenizer.decode(ids, skip_special_tokens=True) == text


def test_tokenizer_has_eos(tokenizer):
    assert tokenizer.eos_token_id is not None


def test_chat_template_supports_thinking_switch(tokenizer):
    messages = [{"role": "user", "content": "hello"}]
    with_think = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=True
    )
    no_think = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    assert "<|im_start|>assistant" in with_think
    # Qwen3 injects an empty think block when thinking is disabled
    assert "<think>" in no_think and "</think>" in no_think
    assert with_think != no_think
