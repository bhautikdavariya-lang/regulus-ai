"""MLX generation worker for the opt-in `mlx` backend (regulus.rag.mlx_generator).

Runs under the interpreter named by model.mlx_python (an environment with mlx-lm installed, kept apart
from the project environment); nothing in the project imports this file.

The worker never tokenizes or applies a chat template: the caller sends token ids rendered with the
production tokenizer and template, and decodes the ids it gets back. Decoding is greedy (argmax).

Protocol: one JSON object per line on stdin/stdout.
  startup  -> {"op": "ready", "model_path", "load_seconds", "active_memory_mb", "peak_memory_mb", versions}
  request  <- {"op": "generate", "prompt_ids": [...], "max_new_tokens": N, "eos_ids": [...], "check_every": 16}
  chunk    -> {"op": "chunk", "token_ids": [...]}      (every check_every tokens; caller replies)
  reply    <- {"op": "continue"} | {"op": "stop", "reason": "..."}
  final    -> {"op": "done", "token_ids": [...remaining], "finished": bool, "stopped_by_caller": reason|None,
               "prompt_tokens", "generated_tokens", "prefill_seconds", "seconds", "first_token_seconds",
               "peak_memory_mb", "active_memory_mb"}
  request  <- {"op": "shutdown"}
Errors are reported as {"op": "error", "message": "..."} and the worker keeps serving.
"""
from __future__ import annotations

import json
import sys
import time

import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import generate_step

MB = 2**20


def send(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def recv() -> dict:
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return json.loads(line)


def greedy(logprobs: mx.array) -> mx.array:
    return mx.argmax(logprobs, axis=-1)


def main(model_path: str) -> None:
    import importlib.metadata as md

    t0 = time.perf_counter()
    model, _tokenizer = load(model_path)  # the tokenizer is never used for prompts
    mx.eval(model.parameters())
    send({"op": "ready", "model_path": model_path, "load_seconds": round(time.perf_counter() - t0, 3),
          "active_memory_mb": round(mx.get_active_memory() / MB, 1), "peak_memory_mb": round(mx.get_peak_memory() / MB, 1),
          "versions": {p: md.version(p) for p in ("mlx", "mlx-metal", "mlx-lm")}})
    while True:
        try:
            req = recv()
        except EOFError:
            return
        if req.get("op") == "shutdown":
            send({"op": "bye"})
            return
        if req.get("op") != "generate":
            send({"op": "error", "message": f"unknown op {req.get('op')!r}"})
            continue
        try:
            generate(model, req)
        except Exception as exc:  # explicit failure, never a silent fallback
            send({"op": "error", "message": f"{type(exc).__name__}: {exc}"})


def generate(model, req: dict) -> None:
    ids = req["prompt_ids"]
    max_new = int(req["max_new_tokens"])
    eos = set(int(i) for i in req["eos_ids"])
    every = int(req.get("check_every", 16))
    mx.reset_peak_memory()
    start = time.perf_counter()
    first = None
    pending: list[int] = []
    n = 0
    finished = False
    stopped = None
    for token, _ in generate_step(mx.array(ids), model, max_tokens=max_new, sampler=greedy):
        tok = int(token)
        if first is None:
            first = time.perf_counter() - start
        pending.append(tok)
        n += 1
        if tok in eos:
            finished = True
            break
        if n % every == 0 and n < max_new:
            send({"op": "chunk", "token_ids": pending})
            pending = []
            reply = recv()
            if reply.get("op") == "stop":
                stopped = reply.get("reason", "caller")
                break
    send({"op": "done", "token_ids": pending, "finished": finished, "stopped_by_caller": stopped,
          "prompt_tokens": len(ids), "generated_tokens": n, "seconds": round(time.perf_counter() - start, 3),
          "first_token_seconds": None if first is None else round(first, 3),
          "peak_memory_mb": round(mx.get_peak_memory() / MB, 1), "active_memory_mb": round(mx.get_active_memory() / MB, 1)})


if __name__ == "__main__":
    main(sys.argv[1])
