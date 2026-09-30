from pathlib import Path

import pytest

from regulus.config import DEFAULT_CONFIG_PATH, PROJECT_ROOT, ConfigError, ModelConfig, load_settings


def test_default_config_file_exists():
    assert DEFAULT_CONFIG_PATH.is_file()
    assert (PROJECT_ROOT / "requirements.txt").is_file()


def test_load_settings_from_yaml(settings):
    assert settings.model.id == "Qwen/Qwen3-0.6B"
    assert settings.model.cache_dir == (PROJECT_ROOT / "models").resolve()
    assert settings.model.cache_dir.is_absolute()
    assert settings.model.device == "auto"
    assert settings.model.dtype == "auto"
    assert settings.generation.max_new_tokens > 0


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("REGULUS_MODEL_ID", "Qwen/Qwen3-1.7B")
    monkeypatch.setenv("REGULUS_MODEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("REGULUS_DEVICE", "CPU")
    monkeypatch.setenv("REGULUS_DTYPE", "bfloat16")
    s = load_settings(use_dotenv=False)
    assert s.model.id == "Qwen/Qwen3-1.7B"
    assert s.model.cache_dir == tmp_path
    assert s.model.device == "cpu"
    assert s.model.dtype == "bfloat16"


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "nope.yaml", use_dotenv=False)


@pytest.mark.parametrize("model_id", ["Qwen/Qwen3-0.6B", "meta-llama/Llama-3.2-1B", "org/name_v1.0"])
def test_valid_model_ids(model_id):
    ModelConfig(id=model_id).validate()


@pytest.mark.parametrize("model_id", ["", "Qwen3-0.6B", "a/b/c", "/x", "org/", "org name/model"])
def test_invalid_model_ids(model_id):
    with pytest.raises(ConfigError):
        ModelConfig(id=model_id).validate()


@pytest.mark.parametrize("field,value", [("device", "gpu"), ("device", "cuda:x"), ("dtype", "int8")])
def test_invalid_device_or_dtype(field, value):
    with pytest.raises(ConfigError):
        ModelConfig(**{field: value}).validate()


def test_relative_cache_dir_resolves_to_project_root(tmp_path, monkeypatch):
    cfg = tmp_path / "m.yaml"
    cfg.write_text("model:\n  id: Qwen/Qwen3-0.6B\n  cache_dir: models\n", encoding="utf-8")
    monkeypatch.delenv("REGULUS_MODEL_CACHE_DIR", raising=False)
    s = load_settings(cfg, use_dotenv=False)
    assert s.model.cache_dir == Path(PROJECT_ROOT / "models").resolve()


def test_mps_is_a_valid_device_and_the_default_is_unchanged(monkeypatch):
    ModelConfig(device="mps", dtype="float16").validate()
    monkeypatch.delenv("REGULUS_DEVICE", raising=False)
    monkeypatch.delenv("REGULUS_DTYPE", raising=False)
    s = load_settings(use_dotenv=False)
    assert (s.model.device, s.model.dtype) == ("auto", "auto")


def test_device_env_override_accepts_mps(monkeypatch):
    monkeypatch.setenv("REGULUS_DEVICE", "mps")
    monkeypatch.setenv("REGULUS_DTYPE", "float16")
    s = load_settings(use_dotenv=False)
    assert (s.model.device, s.model.dtype) == ("mps", "float16")
