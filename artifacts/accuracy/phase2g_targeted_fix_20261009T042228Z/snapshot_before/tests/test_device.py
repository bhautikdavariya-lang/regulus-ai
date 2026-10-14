import pytest
import torch

from regulus.model import environment_info, resolve_device, resolve_dtype


def test_auto_device_matches_torch():
    dev = resolve_device("auto")
    expected = "cuda" if torch.cuda.is_available() else "cpu"
    assert dev.type == expected


def test_explicit_cpu():
    assert resolve_device("cpu").type == "cpu"


def test_cuda_request_without_cuda_raises():
    if torch.cuda.is_available():
        pytest.skip("CUDA is available on this machine")
    with pytest.raises(RuntimeError, match="CUDA is not available"):
        resolve_device("cuda")


def test_auto_dtype_on_cpu_is_float32():
    assert resolve_dtype("auto", torch.device("cpu")) is torch.float32


@pytest.mark.parametrize(
    "name,expected",
    [("float32", torch.float32), ("float16", torch.float16), ("bfloat16", torch.bfloat16)],
)
def test_explicit_dtype(name, expected):
    assert resolve_dtype(name, torch.device("cpu")) is expected


def test_unknown_dtype_raises():
    with pytest.raises(ValueError):
        resolve_dtype("int4", torch.device("cpu"))


def test_environment_info_keys():
    info = environment_info()
    for key in ("python", "torch", "cuda_available", "cuda_version", "cpu_threads", "gpu_name"):
        assert key in info
    assert isinstance(info["cuda_available"], bool)
    if info["cuda_available"]:
        assert info["gpu_name"]


# ---- opt-in Apple GPU (MPS): never chosen by "auto", explicit when asked for


def test_auto_never_selects_mps(monkeypatch):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert resolve_device("auto").type in ("cuda", "cpu")


def test_explicit_mps_when_available(monkeypatch):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert resolve_device("mps").type == "mps"


def test_mps_request_without_mps_raises_instead_of_falling_back(monkeypatch):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="MPS\\) is not available"):
        resolve_device("mps")


def test_auto_dtype_on_mps_is_float32_float16_only_when_asked():
    assert resolve_dtype("auto", torch.device("mps")) is torch.float32
    assert resolve_dtype("float16", torch.device("mps")) is torch.float16


def test_environment_info_reports_mps():
    assert "mps_available" in environment_info()
