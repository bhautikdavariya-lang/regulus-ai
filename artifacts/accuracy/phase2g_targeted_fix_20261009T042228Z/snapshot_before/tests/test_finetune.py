"""Stage 12 unit tests: configuration, dataset identity, chat rendering and
tokenisation, LoRA attachment, adapter save/reload, generation and safety.

No GPU, no database and no 0.6B weights: LoRA/checkpoint/inference tests use
a two-layer random Qwen3 built from its config; the rendering tests use the
real tokenizer from the local cache (skipped if it is not downloaded).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import torch

from regulus.config import GenerationConfig, ModelConfig
from regulus.finetune import (
    AdapterError,
    DatasetIdentityError,
    FinetuneConfigError,
    LoraSettings,
    LoraTargetError,
    adapter_identity,
    attach_lora,
    attach_saved_adapter,
    collate,
    inference_check,
    load_finetune_config,
    render_example,
    tokenize_examples,
    verify_dataset,
    verify_target_modules,
)
from regulus.finetune.config import DatasetConfig
from regulus.finetune.data import IGNORE_INDEX, eval_subset, protected_hashes, sha256_file
from regulus.model import load_tokenizer
from regulus.model.loader import ModelLoadError
from regulus.training import ContextItem, TrainingExample, to_messages, write_jsonl

TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def tiny_model():
    """Fresh per test: attach_lora wraps the model's modules in place."""
    from transformers import AutoModelForCausalLM, Qwen3Config

    torch.manual_seed(0)
    cfg = Qwen3Config(vocab_size=512, hidden_size=64, intermediate_size=128, num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=256, tie_word_embeddings=True)
    model = AutoModelForCausalLM.from_config(cfg)
    model.eval()
    return model


@pytest.fixture(scope="module")
def tokenizer(settings):
    try:
        return load_tokenizer(settings.model, local_files_only=True)
    except ModelLoadError:
        pytest.skip("Qwen3 tokenizer not in the local cache")


def _example(i: int = 0) -> TrainingExample:
    ctx = [ContextItem("ecfr", "21 CFR 820.10(a)", f"Document a quality management system number {i}.", url="https://www.ecfr.gov/x", section="820.10", paragraph="(a)", heading="Requirements.", source_key=f"ecfr:820.10:(a):{i}")]
    return TrainingExample("regulatory_qa", "section_paragraph", f"What does 21 CFR 820.10(a) require (variant {i})?", ctx, f"21 CFR 820.10(a) [1] provides: Document a quality management system number {i}.", ["21 CFR 820.10(a)"], True, "gen", f"ecfr:820.10:{i}")


def _write_dataset(tmp_path: Path, counts=(3, 2, 2), tamper: bool = False):
    paths = {s: tmp_path / f"{n}_v1.jsonl" for s, n in (("train", "training"), ("validation", "validation"), ("test", "test"))}
    files = {}
    combined = hashlib.sha256()
    k = 0
    for split, n in zip(("train", "validation", "test"), counts):
        rows = []
        for _ in range(n):
            ex = _example(k)
            ex.split = split
            rows.append(ex)
            k += 1
        write_jsonl(rows, paths[split])
        digest = sha256_file(paths[split])
        combined.update(digest.encode("ascii"))
        files[split] = {"path": paths[split].name, "examples": n, "sha256": digest}
    manifest = tmp_path / "manifest_v1.json"
    manifest.write_text(json.dumps({"dataset_version": "v1", "files": files, "dataset_sha256": combined.hexdigest(), "config": {"seed": 42}, "database": {"snapshot": {"ecfr_snapshot_date": "2026-09-03"}}}), encoding="utf-8")
    if tamper:
        paths["train"].write_text(paths["train"].read_text(encoding="utf-8").replace("variant 0", "variant X"), encoding="utf-8")
    return DatasetConfig(train=paths["train"], validation=paths["validation"], test=paths["test"], manifest=manifest, expected_hash=combined.hexdigest(), expected_counts={"train": counts[0], "validation": counts[1], "test": counts[2]})


# ------------------------------------------------------------- configuration


def test_config_loads_with_required_fields_and_overrides():
    cfg = load_finetune_config()
    assert cfg.model_name == "Qwen3-0.6B" and cfg.model.id == "Qwen/Qwen3-0.6B"
    assert cfg.dataset.expected_counts == {"train": 7566, "validation": 962, "test": 917}
    assert cfg.dataset.expected_hash == "bee32e320fc5c5072b040efc5b5a1caf707bce09c96affd05586a0f039e77a54"
    assert cfg.lora.r == 16 and cfg.lora.alpha == 32 and cfg.lora.dropout == 0.05 and set(cfg.lora.target_modules) == set(TARGETS)
    assert cfg.training.seed == 42 and cfg.dataset.seed == 42 and cfg.training.max_seq_length == 1280
    assert cfg.output_dir != cfg.smoke_dir and cfg.output_dir.name == "stage12_v1"
    d = cfg.to_dict()
    assert d["stage"] == 12 and d["training"]["learning_rate"] == 2e-4 and "protected" in d["dataset"]
    over = load_finetune_config(max_steps=3, eval_subset=5, output_dir="models/tmp_x")
    assert over.training.max_steps == 3 and over.dataset.eval_subset == 5 and over.output_dir.name == "tmp_x"


def test_invalid_config_fails_clearly(tmp_path):
    with pytest.raises(FinetuneConfigError, match="override"):
        load_finetune_config(bogus=1)
    with pytest.raises(FinetuneConfigError):
        load_finetune_config(max_steps=0)
    bad = tmp_path / "bad.yaml"
    bad.write_text("model: {name: x}\ndataset: {}\n", encoding="utf-8")
    with pytest.raises(FinetuneConfigError, match="section"):
        load_finetune_config(bad)
    with pytest.raises(FinetuneConfigError, match="not found"):
        load_finetune_config(tmp_path / "missing.yaml")


# ------------------------------------------------------------------ dataset


def test_stage11_dataset_paths_resolve_and_match_manifest():
    cfg = load_finetune_config()
    if not cfg.dataset.train.is_file():
        pytest.skip("Stage 11 dataset not generated")
    identity = verify_dataset(cfg.dataset)
    assert identity["dataset_sha256"] == cfg.dataset.expected_hash
    assert {k: v["examples"] for k, v in identity["files"].items()} == cfg.dataset.expected_counts
    assert identity["database_snapshot"] == "2026-09-03"


def test_dataset_identity_check_rejects_tampering_and_wrong_counts(tmp_path):
    good = _write_dataset(tmp_path / "good")
    identity = verify_dataset(good)
    assert identity["files"]["train"]["examples"] == 3 and identity["dataset_sha256"] == good.expected_hash
    bad = _write_dataset(tmp_path / "bad", tamper=True)
    with pytest.raises(DatasetIdentityError, match="sha256"):
        verify_dataset(bad)
    wrong = DatasetConfig(**{**good.__dict__, "expected_counts": {"train": 99, "validation": 2, "test": 2}})
    with pytest.raises(DatasetIdentityError, match="expected 99"):
        verify_dataset(wrong)
    wrong_hash = DatasetConfig(**{**good.__dict__, "expected_hash": "0" * 64})
    with pytest.raises(DatasetIdentityError, match="hash"):
        verify_dataset(wrong_hash)


def test_eval_subset_is_deterministic():
    exs = [_example(i) for i in range(20)]
    a = [e.id for e in eval_subset(exs, 5, 42)]
    assert a == [e.id for e in eval_subset(exs, 5, 42)] and len(set(a)) == 5
    assert a != [e.id for e in eval_subset(exs, 5, 7)]


# ------------------------------------------------------------- tokenisation


def test_to_messages_and_rendering_mask_the_prompt(tokenizer):
    ex = _example(1)
    messages = to_messages(ex)
    assert [m["role"] for m in messages] == ["system", "user", "assistant"] and messages[2]["content"] == ex.answer
    input_ids, labels = render_example(ex, tokenizer)
    assert len(input_ids) == len(labels) > 20
    n_prompt = sum(1 for l in labels if l == IGNORE_INDEX)
    assert 0 < n_prompt < len(labels)
    learned = tokenizer.decode([l for l in labels if l != IGNORE_INDEX])
    assert learned.startswith(ex.answer) and learned.rstrip().endswith("<|im_end|>")
    assert [l for l in labels if l != IGNORE_INDEX] == input_ids[n_prompt:]
    assert tokenizer.decode(input_ids[:n_prompt]).rstrip().endswith("</think>")  # generation prompt ends right before the answer


def test_tokenize_examples_reports_lengths_skips_or_truncates(tokenizer):
    exs = [_example(i) for i in range(3)]
    ds = tokenize_examples(exs, tokenizer, 4096)
    assert len(ds) == 3 and ds.stats["skipped_over_length"] == 0 and ds.stats["truncated"] == 0
    assert ds.stats["max_token_length_observed"] >= ds.stats["median_token_length"] > 0 and ds.stats["answer_tokens_mean"] > 0
    small = ds.stats["max_token_length_observed"] - 1
    skipped = tokenize_examples(exs, tokenizer, small, "skip")
    assert skipped.stats["skipped_over_length"] >= 1 and len(skipped) + skipped.stats["skipped_over_length"] == 3
    trunc = tokenize_examples(exs, tokenizer, small, "truncate")
    assert trunc.stats["truncated"] >= 1 and all(len(r["input_ids"]) <= small for r in trunc.rows)
    item = ds[0]
    assert set(item) == {"input_ids", "attention_mask", "labels"} and item["attention_mask"].sum() == len(ds.rows[0]["input_ids"])
    batch = collate([ds[0], ds[1]], tokenizer.pad_token_id)
    width = batch["input_ids"].shape[1]
    assert batch["labels"].shape == (2, width) and (batch["attention_mask"].sum(dim=1) == torch.tensor([len(ds.rows[0]["input_ids"]), len(ds.rows[1]["input_ids"])])).all()
    assert (batch["labels"][batch["attention_mask"] == 0] == IGNORE_INDEX).all()


# ------------------------------------------------------------------- LoRA


def test_target_modules_are_verified_and_lora_attaches(tiny_model):
    counts = verify_target_modules(tiny_model, TARGETS)
    assert counts == {t: 2 for t in TARGETS}
    with pytest.raises(LoraTargetError, match="not found"):
        verify_target_modules(tiny_model, ("q_proj", "made_up_proj"))
    peft_model, info = attach_lora(tiny_model, LoraSettings(r=4, alpha=8, dropout=0.0, target_modules=TARGETS))
    assert info["trainable_parameters"] > 0 and info["trainable_parameters"] < info["total_parameters"]
    assert info["base_parameters_frozen"] is True and info["target_module_counts"] == counts
    assert all(p.requires_grad == ("lora_" in n) for n, p in peft_model.named_parameters())
    # one optimisation step changes only LoRA weights
    ids = torch.randint(0, 512, (1, 16))
    before = {n: p.detach().clone() for n, p in peft_model.named_parameters() if "lora_B" in n}
    loss = peft_model(input_ids=ids, labels=ids).loss
    loss.backward()
    torch.optim.SGD([p for p in peft_model.parameters() if p.requires_grad], lr=0.5).step()
    assert any(not torch.equal(before[n], p.detach()) for n, p in peft_model.named_parameters() if n in before)


def test_adapter_saves_reloads_and_generates(tiny_model, tmp_path):
    from transformers import AutoModelForCausalLM

    peft_model, _ = attach_lora(tiny_model, LoraSettings(r=4, alpha=8, dropout=0.0, target_modules=TARGETS))
    with torch.no_grad():
        for n, p in peft_model.named_parameters():
            if "lora_B" in n:
                p.add_(0.05)
    out = tmp_path / "run" / "adapter"
    peft_model.save_pretrained(str(out))
    assert (out / "adapter_config.json").is_file() and any(p.name.startswith("adapter_model.") for p in out.iterdir())
    (tmp_path / "run" / "metadata.json").write_text(json.dumps({"stage": 12, "dataset": {"hash": "abc"}, "best_checkpoint": "checkpoint-1", "timestamp": "t"}), encoding="utf-8")
    ident = adapter_identity(out)
    assert ident["r"] == 4 and ident["lora_alpha"] == 8 and ident["stage"] == 12 and ident["dataset_hash"] == "abc" and ident["adapter_name"] == "run"
    torch.manual_seed(0)  # same seed as the fixture -> identical base weights
    fresh = AutoModelForCausalLM.from_config(tiny_model.config)
    fresh.eval()
    fresh.config._name_or_path = ident["base_model_name_or_path"] or ""
    merged, ident2 = attach_saved_adapter(fresh, out, merge=True)
    assert ident2["adapter_dir"] == out.as_posix() and not any("lora_" in n for n, _ in merged.named_parameters())
    ids = torch.randint(0, 512, (1, 8))
    with torch.no_grad():
        ref = peft_model(input_ids=ids).logits
        got = merged(input_ids=ids).logits
    assert torch.allclose(ref, got, atol=1e-4)
    generated = merged.generate(input_ids=ids, max_new_tokens=4, do_sample=False, pad_token_id=0)
    assert generated.shape[1] == 12
    with pytest.raises(AdapterError):
        adapter_identity(tmp_path / "nowhere")


def test_attach_refuses_mismatched_base_model(tiny_model, tmp_path):
    peft_model, _ = attach_lora(tiny_model, LoraSettings(r=2, alpha=4, dropout=0.0, target_modules=("q_proj",)))
    out = tmp_path / "adapter"
    peft_model.save_pretrained(str(out))
    cfg = json.loads((out / "adapter_config.json").read_text(encoding="utf-8"))
    cfg["base_model_name_or_path"] = "Some/OtherModel"
    (out / "adapter_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    other = type(tiny_model)(tiny_model.config)
    other.config._name_or_path = "Qwen/Qwen3-0.6B"
    with pytest.raises(AdapterError, match="trained on"):
        attach_saved_adapter(other, out)


def test_inference_check_writes_artifact(tiny_model, tokenizer, tmp_path, monkeypatch):
    from regulus.finetune import adapter as adapter_mod
    from regulus.inference.generate import GenerationResult

    monkeypatch.setattr(adapter_mod, "generate_chat", lambda *a, **k: GenerationResult("q", "an answer [1]", 30, 4, 0.5))
    ex = _example(2)
    art = inference_check(tiny_model, tokenizer, to_messages(ex)[:-1], GenerationConfig(max_new_tokens=8, do_sample=False), model_id="Qwen/Qwen3-0.6B", identity={"adapter_name": "stage12_v1", "r": 16}, out_path=tmp_path / "inference_check.json")
    saved = json.loads((tmp_path / "inference_check.json").read_text(encoding="utf-8"))
    assert saved["generated_answer"] == "an answer [1]" and saved["model_identifier"] == "Qwen/Qwen3-0.6B" and saved["adapter_identifier"]["adapter_name"] == "stage12_v1"
    assert ex.question in saved["question_and_context"] and "SOURCE 1" in saved["question_and_context"] and "correctness" in saved["note"]


# ------------------------------------------------------------------- safety


def test_protected_evaluation_datasets_are_only_hashed_never_written(tmp_path):
    p = tmp_path / "baseline_v1.jsonl"
    p.write_text('{"id": "x"}\n', encoding="utf-8")
    before = p.stat().st_mtime_ns
    hashes = protected_hashes((p, tmp_path / "missing.jsonl"))
    assert set(hashes) == {"baseline_v1.jsonl"} and len(hashes["baseline_v1.jsonl"]) == 64
    assert p.stat().st_mtime_ns == before and p.read_text(encoding="utf-8") == '{"id": "x"}\n'


def test_finetune_modules_do_not_import_the_database_layer():
    import sys

    import regulus.finetune.train  # noqa: F401  (importing must not start training or touch the database)

    assert "regulus.retrieval.db" not in {m for m in sys.modules if m.startswith("regulus.finetune")}
    src = Path(__file__).resolve().parents[1] / "src" / "regulus" / "finetune"
    for py in src.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "regulus.retrieval" not in text and "psycopg" not in text, py.name
