"""The opt-in `mlx` backend (regulus.rag.mlx_generator): selection, worker protocol, failures, memory preflight.

No MLX is needed: a fake worker (plain Python, run by this interpreter) speaks the protocol of
scripts/mlx_worker.py, and a character-level fake tokenizer stands in for the Qwen tokenizer.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import regulus.model as MODEL
from regulus.config import PROJECT_ROOT, ConfigError, load_settings
from regulus.config.settings import ModelConfig
from regulus.rag import mlx_generator as MG
from regulus.rag import remote_generator as RG

EOS = 1_000_000

FAKE_WORKER = r'''
import json, sys, time
cfg = json.load(open(sys.argv[-1] + "/config.json"))
mode, reply = cfg["fake_mode"], cfg.get("fake_reply", "")
log = open(cfg["fake_log"], "a")
def send(o): sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
if mode == "crash_on_start": sys.exit(3)
send({"op": "ready", "versions": {"mlx": "fake"}, "load_seconds": 0.0})
for line in sys.stdin:
    req = json.loads(line)
    log.write(json.dumps({"got": req.get("op"), "max_new_tokens": req.get("max_new_tokens"),
                          "n_prompt": len(req.get("prompt_ids", []))}) + "\n"); log.flush()
    if req["op"] == "shutdown": send({"op": "bye"}); break
    if mode == "error": send({"op": "error", "message": "boom"}); continue
    if mode == "hang": time.sleep(60); continue
    every, out, n = req["check_every"], [], 0
    stream = [ord(c) for c in reply] + ([] if mode == "repeat" else [req["eos_ids"][0]])
    stopped = None
    while n < req["max_new_tokens"]:
        tok = stream[n % len(stream)]
        out.append(tok); n += 1
        if tok in req["eos_ids"]: break
        if n % every == 0 and n < req["max_new_tokens"]:
            send({"op": "chunk", "token_ids": out}); out = []
            r = json.loads(sys.stdin.readline())
            log.write(json.dumps({"reply": r["op"], "reason": r.get("reason")}) + "\n"); log.flush()
            if r["op"] == "stop": stopped = r.get("reason"); break
    send({"op": "done", "token_ids": out, "finished": out[-1:] == [req["eos_ids"][0]], "stopped_by_caller": stopped,
          "prompt_tokens": len(req["prompt_ids"]), "generated_tokens": n, "seconds": 0.01, "first_token_seconds": 0.001,
          "peak_memory_mb": 1.0, "active_memory_mb": 1.0})
'''


class CharTokenizer:
    """Characters are token ids; EOS is special (dropped by skip_special_tokens)."""
    eos_token_id = EOS

    def __init__(self):
        self.template_calls = []

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=None):
        self.template_calls.append({"enable_thinking": enable_thinking, "add_generation_prompt": add_generation_prompt})
        return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"

    def __call__(self, text, **kw):
        return {"input_ids": [ord(c) for c in text]}

    def decode(self, ids, skip_special_tokens=True):
        return "".join(chr(i) for i in ids if not (skip_special_tokens and i == EOS))


class Gen:
    max_new_tokens = 64


def model_dir(tmp_path, mode, reply="The FDA regulates devices. [1]"):
    d = tmp_path / "model"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps({"eos_token_id": [EOS], "quantization": {"bits": 4, "group_size": 128},
                                               "fake_mode": mode, "fake_reply": reply,
                                               "fake_log": str(tmp_path / "worker_log.jsonl")}))
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER)
    return d, script


def worker_log(tmp_path):
    p = tmp_path / "worker_log.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def make(tmp_path, mode, reply="The FDA regulates devices. [1]", **kw):
    d, script = model_dir(tmp_path, mode, reply)
    return MG.MlxGenerator(CharTokenizer(), Gen(), model_id="Qwen/Qwen3-1.7B", model_path=d, python=sys.executable,
                           revision="rev-abc", worker_script=script, **kw)


MSGS = [{"role": "system", "content": "rules"}, {"role": "user", "content": "Which agency regulates devices?"}]


# ------------------------------------------------------------------ selection and configuration

def _clear_model_env(monkeypatch):
    for k in ("MODEL_ID", "MODEL_BACKEND", "MODEL_ENDPOINT", "MODEL_CACHE_DIR", "MLX_PYTHON", "MLX_MODEL_PATH",
              "MLX_REVISION", "MLX_MIN_AVAILABLE_MB", "ADAPTER", "DEVICE", "DTYPE"):
        monkeypatch.delenv("REGULUS_" + k, raising=False)


def test_default_model_and_backend_are_unchanged(monkeypatch):
    _clear_model_env(monkeypatch)
    s = load_settings(use_dotenv=False)
    assert (s.model.id, s.model.backend) == ("Qwen/Qwen3-0.6B", "transformers")
    assert s.model.mlx_python is None and s.model.mlx_model_path is None


def test_mlx_backend_needs_its_interpreter_and_model_directory(tmp_path):
    with pytest.raises(ConfigError, match="mlx_python"):
        ModelConfig(backend="mlx").validate()
    ModelConfig(backend="mlx", mlx_python=tmp_path / "python", mlx_model_path=tmp_path).validate()
    with pytest.raises(ConfigError):
        ModelConfig(mlx_min_available_mb=-1).validate()


def test_the_environment_selects_the_mlx_backend_explicitly(monkeypatch, tmp_path):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("REGULUS_MODEL_BACKEND", "mlx")
    monkeypatch.setenv("REGULUS_MODEL_ID", "Qwen/Qwen3-1.7B")
    monkeypatch.setenv("REGULUS_MLX_PYTHON", str(tmp_path / "py"))
    monkeypatch.setenv("REGULUS_MLX_MODEL_PATH", str(tmp_path / "m"))
    monkeypatch.setenv("REGULUS_MLX_REVISION", "21457c6f51ed")
    monkeypatch.setenv("REGULUS_MLX_MIN_AVAILABLE_MB", "1500")
    m = load_settings(use_dotenv=False).model
    assert (m.backend, m.id, m.mlx_revision, m.mlx_min_available_mb) == ("mlx", "Qwen/Qwen3-1.7B", "21457c6f51ed", 1500)
    assert m.mlx_python == tmp_path / "py" and m.mlx_model_path == tmp_path / "m"


def test_load_generator_dispatches_to_mlx_and_refuses_an_adapter(monkeypatch, tmp_path):
    s = load_settings(use_dotenv=False)
    s.model = replace(s.model, backend="mlx", mlx_python=tmp_path, mlx_model_path=tmp_path, adapter=None)
    sentinel = object()
    monkeypatch.setattr(MG, "load_mlx_generator", lambda settings, local_files_only=False: sentinel)
    assert RG.load_generator(s) is sentinel
    s.model = replace(s.model, adapter=tmp_path)
    with pytest.raises(ValueError, match="adapter"):
        RG.load_generator(s)


def test_the_transformers_default_never_reaches_the_mlx_backend(monkeypatch):
    s = load_settings(use_dotenv=False)
    s.model = replace(s.model, backend="transformers")
    monkeypatch.setattr(MG, "load_mlx_generator", lambda *a, **k: pytest.fail("mlx backend used for transformers"))
    import regulus.rag.generator as GEN
    monkeypatch.setattr(GEN, "load_qwen_generator", lambda settings, local_files_only=False: "transformers-generator")
    assert RG.load_generator(s) == "transformers-generator"


# ------------------------------------------------------------------ generation through the worker

def test_generation_round_trip_uses_the_production_template_with_thinking_off(tmp_path):
    g = make(tmp_path, "echo")
    try:
        r = g.generate(MSGS, max_new_tokens=200)
        assert r.response == "The FDA regulates devices. [1]"
        assert r.finished is True and r.stop_reason is None
        assert r.generated_tokens == len("The FDA regulates devices. [1]") + 1      # + EOS, as transformers counts it
        assert r.prompt_tokens == len(CharTokenizer().apply_chat_template(MSGS))
        assert g.tokenizer.template_calls == [{"enable_thinking": False, "add_generation_prompt": True}]
        sent = [e for e in worker_log(tmp_path) if e.get("got") == "generate"]
        assert sent[0]["max_new_tokens"] == 200                                     # the pipeline's budget is passed on
        d = g.describe()
        assert (d["backend"], d["model_id"], d["model_revision"], d["dtype"]) == ("mlx", "Qwen/Qwen3-1.7B", "rev-abc",
                                                                                 "mlx-4bit-g128")
        assert d["generation"]["enable_thinking"] is False and d["generation"]["do_sample"] is False
    finally:
        g.close()


def test_a_thinking_models_reasoning_is_never_returned(tmp_path):
    g = make(tmp_path, "echo", reply="weigh (a) against (b)</think>\n\n21 CFR 71.2")
    g._thinking = True
    try:
        r = g.generate(MSGS, max_new_tokens=16)
        assert r.response == "21 CFR 71.2" and r.stop_reason is None
        assert len([e for e in worker_log(tmp_path) if e.get("got") == "generate"]) == 1
    finally:
        g.close()


def test_a_zero_reasoning_budget_closes_the_block_and_answers_in_one_pass(tmp_path):
    g = make(tmp_path, "echo", reply="21 CFR 71.2")
    g._thinking = True
    try:
        r = g.generate(MSGS, max_new_tokens=16, think_budget=0)
        assert r.response == "21 CFR 71.2" and r.stop_reason is None and r.finished is True
        sent = [e for e in worker_log(tmp_path) if e.get("got") == "generate"]
        assert len(sent) == 1 and sent[0]["max_new_tokens"] == 16
        assert sent[0]["n_prompt"] == len(CharTokenizer().apply_chat_template(MSGS)) + len("\n</think>\n\n")
    finally:
        g.close()


def test_the_configured_budget_applies_when_none_is_given_and_the_cap_is_unfinished(tmp_path):
    g = make(tmp_path, "repeat", reply="abcdefghij")              # never emits EOS, never repeats a sentence
    try:
        r = g.generate(MSGS)
        assert r.generated_tokens == Gen.max_new_tokens and r.finished is False and r.stop_reason is None
    finally:
        g.close()


def test_a_sentence_loop_is_stopped_by_the_production_repetition_rule(tmp_path):
    g = make(tmp_path, "repeat", reply="Records must be kept for two years. [3] ")
    try:
        r = g.generate(MSGS, max_new_tokens=2000)
        assert r.stop_reason == "repetition" and r.finished is False
        assert r.generated_tokens < 2000
        assert {"reply": "stop", "reason": "repetition"} in worker_log(tmp_path)
    finally:
        g.close()


def test_drafts_go_only_to_on_text_and_a_failing_callback_stops_the_worker(tmp_path):
    g = make(tmp_path, "repeat", reply="abcdefghij")

    class Disconnected(Exception):
        pass

    def on_text(draft):
        raise Disconnected(draft)

    try:
        with pytest.raises(Disconnected):
            g.generate(MSGS, max_new_tokens=500, on_text=on_text)
        assert {"reply": "stop", "reason": "caller"} in worker_log(tmp_path)
        assert g.generate(MSGS, max_new_tokens=5).generated_tokens == 5          # the protocol is still in step
    finally:
        g.close()


# ------------------------------------------------------------------ failures are explicit, never a fallback

def test_a_worker_that_does_not_start_is_an_explicit_error(tmp_path):
    with pytest.raises(MG.MlxWorkerError, match="exited"):
        make(tmp_path, "crash_on_start")


def test_a_missing_worker_interpreter_is_an_explicit_error(tmp_path):
    d, script = model_dir(tmp_path, "echo")
    with pytest.raises(MG.MlxWorkerError, match="could not start"):
        MG.MlxGenerator(CharTokenizer(), Gen(), model_id="m/x", model_path=d, python=tmp_path / "no-python",
                        worker_script=script)


def test_a_worker_error_is_raised_not_replaced(tmp_path):
    g = make(tmp_path, "error")
    try:
        with pytest.raises(MG.MlxWorkerError, match="boom"):
            g.generate(MSGS)
    finally:
        g.close()


def test_a_silent_worker_times_out_and_is_killed(tmp_path):
    g = make(tmp_path, "hang", timeout=1.0)
    with pytest.raises(MG.MlxWorkerError, match="sent nothing"):
        g.generate(MSGS)
    assert g.proc.poll() is not None


# ------------------------------------------------------------------ memory preflight

@pytest.mark.parametrize("measured, message", [((900.0, 1), "900 MB available"), ((9000.0, 4), "critical"),
                                               ((None, 1), "could not be measured"), ((9000.0, None), "could not be measured")])
def test_the_memory_preflight_refuses(measured, message):
    with pytest.raises(MG.MemoryPreflightError, match=message):
        MG.memory_preflight(2000, measure=lambda: measured)


def test_the_memory_preflight_passes_with_room_and_can_be_disabled():
    assert MG.memory_preflight(2000, measure=lambda: (3000.0, 2)) == {"checked": True, "available_mb": 3000, "pressure_level": 2}
    assert MG.memory_preflight(0, measure=lambda: pytest.fail("measured although disabled")) == {"checked": False}


def test_a_refused_preflight_starts_no_worker_and_loads_no_tokenizer(monkeypatch, tmp_path):
    s = load_settings(use_dotenv=False)
    s.model = replace(s.model, backend="mlx", mlx_python=tmp_path, mlx_model_path=tmp_path, mlx_min_available_mb=4000)
    monkeypatch.setattr(MODEL, "load_tokenizer", lambda *a, **k: pytest.fail("tokenizer loaded after a refusal"))
    monkeypatch.setattr(MG, "MlxGenerator", lambda *a, **k: pytest.fail("worker started after a refusal"))
    with pytest.raises(MG.MemoryPreflightError):
        MG.load_mlx_generator(s, measure=lambda: (1000.0, 1))


# ------------------------------------------------------------------ the answering UI: this backend or nothing

def test_the_answering_ui_stops_on_an_unusable_worker_instead_of_loading_another_model(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("serve_ui_mlx_test", PROJECT_ROOT / "scripts" / "serve_ui.py")
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    monkeypatch.setattr(MODEL, "load_model", lambda *a, **k: pytest.fail("a transformers model was loaded"))
    monkeypatch.setattr(MODEL, "load_tokenizer", lambda *a, **k: pytest.fail("a tokenizer was loaded"))
    e = object.__new__(ui.Engine)
    s = load_settings(use_dotenv=False)
    s.model = replace(s.model, backend="mlx", mlx_python=tmp_path, mlx_model_path=tmp_path, adapter=None)
    e.settings = s
    with pytest.raises(SystemExit, match="REGULUS_MLX_PYTHON does not name a file"):   # tmp_path is a directory
        ui.Engine._init_inference(e, offline=True)


def test_the_worker_script_exists_where_the_backend_looks_for_it():
    assert MG.WORKER_SCRIPT == Path(PROJECT_ROOT) / "scripts" / "mlx_worker.py" and MG.WORKER_SCRIPT.is_file()
