"""Opt-in `mlx` backend: generation in a separate worker process under the MLX runtime (Apple Silicon).

Selected only by model.backend = "mlx" (configs/model.yaml or REGULUS_MODEL_BACKEND); the default stays the
in-process transformers backend. Measured on the 8 GB M2 (Qwen3-1.7B, Qwen's MLX 4-bit build): about 0.9 GB
of MLX memory, where the same model in bf16 on MPS drove macOS to critical memory pressure.

What stays in this process, unchanged: the chat template and tokenizer (model.id / model.cache_dir, thinking
off), the token budget, the sentence-repetition stop (regulus.inference.repetition_text, checked every 16
tokens exactly as RepetitionStop does) and decoding of the returned ids. The worker (scripts/mlx_worker.py,
run by model.mlx_python) only runs forward passes on the token ids it is sent and decodes greedily. A worker
that fails to start, dies, reports an error or stops answering raises MlxWorkerError: there is no fallback to
another model.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from regulus.inference.repetition_text import repeated_sentence
from regulus.inference.types import GenerationResult, Message

WORKER_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "mlx_worker.py"
CHECK_EVERY = 16            # as regulus.inference.repetition.CHECK_EVERY
STARTUP_TIMEOUT = 300.0
GENERATION_TIMEOUT = 600.0  # longest silence tolerated between two messages from the worker


class MlxWorkerError(RuntimeError):
    """The MLX worker could not start, failed, or stopped answering."""


class MemoryPreflightError(RuntimeError):
    """Not enough memory is available to start the MLX worker safely."""


def available_memory_mb() -> tuple[float | None, int | None]:
    """(available MB = free + inactive + speculative pages, macOS memory-pressure level), None when unknown."""
    def run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return ""
    out = run(["vm_stat"])
    page = re.search(r"page size of (\d+) bytes", out)
    pages = [re.search(rf"{name}:\s+(\d+)", out) for name in ("Pages free", "Pages inactive", "Pages speculative")]
    available = (sum(int(m.group(1)) for m in pages) * int(page.group(1)) / 2**20
                 if page and all(pages) else None)
    level = run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip()
    return available, (int(level) if level.isdigit() else None)


def memory_preflight(min_available_mb: int, measure=available_memory_mb) -> dict[str, Any]:
    """Refuse to start the worker under critical memory pressure or with too little memory available.
    min_available_mb = 0 disables the check. Memory that cannot be measured is a refusal, not a pass."""
    if min_available_mb == 0:
        return {"checked": False}
    available, level = measure()
    if available is None or level is None:
        raise MemoryPreflightError("memory preflight: available memory or pressure level could not be measured")
    if level >= 4:
        raise MemoryPreflightError(f"memory preflight: macOS memory pressure is critical (level {level})")
    if available < min_available_mb:
        raise MemoryPreflightError(f"memory preflight: {available:.0f} MB available, at least {min_available_mb} MB "
                                   "required (model.mlx_min_available_mb)")
    return {"checked": True, "available_mb": round(available), "pressure_level": level}


class MlxGenerator:
    """The Generator interface of regulus.rag.generator.QwenGenerator, served by an MLX worker process."""

    def __init__(self, tokenizer, gen, *, model_id: str, model_path: str | Path, python: str | Path,
                 revision: str | None = None, worker_script: str | Path = WORKER_SCRIPT,
                 startup_timeout: float = STARTUP_TIMEOUT, timeout: float = GENERATION_TIMEOUT,
                 stop_repetition: bool = True) -> None:
        self.tokenizer = tokenizer
        self.gen = gen
        self.model_id = model_id
        self.model_path = Path(model_path)
        self.revision = revision
        self.timeout = timeout
        self.stop_repetition = stop_repetition
        self.last_worker_stats: dict[str, Any] | None = None
        cfg = json.loads((self.model_path / "config.json").read_text(encoding="utf-8"))
        self.quantization = cfg.get("quantization")
        eos = cfg.get("eos_token_id")
        eos_ids = list(eos) if isinstance(eos, list) else [eos]
        self.eos_ids = sorted({int(i) for i in eos_ids + [tokenizer.eos_token_id] if i is not None})
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        try:
            self.proc = subprocess.Popen([str(python), "-B", "-I", str(worker_script), str(self.model_path)],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, env=env)
        except OSError as exc:
            raise MlxWorkerError(f"could not start the MLX worker with {python}: {exc}") from exc
        self._lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.ready = self._read(startup_timeout)
        if self.ready.get("op") != "ready":
            self.close()
            raise MlxWorkerError(f"the MLX worker did not start: {self.ready}")

    # ------------------------------------------------------------------ worker protocol
    def _pump(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _read(self, timeout: float) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.close(kill=True)
            raise MlxWorkerError(f"the MLX worker sent nothing for {timeout:.0f} s") from None
        if line is None:
            raise MlxWorkerError(f"the MLX worker exited (exit code {self.proc.poll()})")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise MlxWorkerError(f"the MLX worker sent an unreadable line: {line[:200]!r}") from exc

    def _send(self, obj: dict[str, Any]) -> None:
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise MlxWorkerError(f"the MLX worker is not accepting input (exit code {self.proc.poll()})") from exc

    # ------------------------------------------------------------------ Generator interface
    def generate(self, messages: list[Message], max_new_tokens: int | None = None, on_text=None) -> GenerationResult:
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("messages must end with a user turn")
        t_prepare = time.perf_counter()
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                  enable_thinking=False)
        prompt_ids = list(self.tokenizer(text)["input_ids"])
        budget = int(max_new_tokens if max_new_tokens is not None else self.gen.max_new_tokens)
        start = time.perf_counter()
        self._send({"op": "generate", "prompt_ids": prompt_ids, "max_new_tokens": budget, "eos_ids": self.eos_ids,
                    "check_every": CHECK_EVERY})
        ids: list[int] = []
        stop_reason = None
        failure: BaseException | None = None
        while True:
            msg = self._read(self.timeout)
            if msg.get("op") == "error":
                raise MlxWorkerError(f"the MLX worker failed: {msg.get('message')}")
            ids.extend(int(i) for i in msg.get("token_ids", []))
            if msg.get("op") == "done":
                break
            if msg.get("op") != "chunk":
                raise MlxWorkerError(f"unexpected message from the MLX worker: {msg}")
            if failure is not None:            # the caller already gave up: drain to "done"
                self._send({"op": "stop", "reason": "caller"})
                continue
            draft = self.tokenizer.decode(ids, skip_special_tokens=True)
            try:
                if on_text is not None:
                    on_text(draft)
            except BaseException as exc:      # e.g. the client disconnected: stop the worker, then re-raise
                failure = exc
                self._send({"op": "stop", "reason": "caller"})
                continue
            if self.stop_repetition and repeated_sentence(draft):
                stop_reason = "repetition"
                self._send({"op": "stop", "reason": "repetition"})
            else:
                self._send({"op": "continue"})
        if failure is not None:
            raise failure
        elapsed = time.perf_counter() - start
        t_detok = time.perf_counter()
        response = self.tokenizer.decode(ids, skip_special_tokens=True).strip()
        detok = time.perf_counter() - t_detok
        self.last_worker_stats = {k: msg.get(k) for k in ("prompt_tokens", "generated_tokens", "seconds",
                                                           "first_token_seconds", "peak_memory_mb", "active_memory_mb")}
        return GenerationResult(prompt=messages[-1]["content"], response=response, prompt_tokens=len(prompt_ids),
                                generated_tokens=len(ids), seconds=elapsed,
                                finished=(ids[-1] in self.eos_ids) if ids else None,
                                prepare_seconds=start - t_prepare, first_token_seconds=msg.get("first_token_seconds"),
                                detokenize_seconds=detok, stop_reason=stop_reason)

    def describe(self) -> dict[str, Any]:
        q = self.quantization
        return {"model_id": self.model_id, "model_revision": self.revision, "backend": "mlx", "device": "mlx-gpu",
                "dtype": f"mlx-{q['bits']}bit-g{q['group_size']}" if q else "mlx-unquantized",
                "quantization": q, "mlx_model_path": str(self.model_path),
                "runtime_versions": self.ready.get("versions"),
                "generation": {"max_new_tokens": self.gen.max_new_tokens, "do_sample": False, "temperature": None,
                               "top_p": None, "top_k": None, "enable_thinking": False}}

    def close(self, kill: bool = False) -> None:
        if self.proc.poll() is not None:
            return
        if not kill:
            try:
                self._send({"op": "shutdown"})
                self.proc.wait(timeout=10)
                return
            except Exception:
                pass
        self.proc.kill()
        self.proc.wait()


def load_mlx_generator(settings, *, local_files_only: bool = False, measure=available_memory_mb) -> MlxGenerator:
    """The `mlx` backend for model.backend == "mlx": memory preflight, then the production tokenizer, then the worker."""
    from regulus.model import load_tokenizer

    m = settings.model
    preflight = memory_preflight(m.mlx_min_available_mb, measure)
    tokenizer = load_tokenizer(m, local_files_only=local_files_only)
    generator = MlxGenerator(tokenizer, settings.generation, model_id=m.id, model_path=m.mlx_model_path,
                             python=m.mlx_python, revision=m.mlx_revision)
    generator.preflight = preflight
    return generator
