"""Generator backed by an OpenAI-compatible chat-completions server (Stage 7 backend seam).

Covers remote inference and quantized models alike: vLLM, TGI, llama.cpp's server and MLX-LM's
server all expose `POST {endpoint}/chat/completions`. The answering pipeline does not change: it
calls `generate(messages, max_new_tokens, on_text)` exactly as it calls the in-process generator,
and gets a GenerationResult with the same fields (text, token counts when the server reports
them, finished flag, first-token time when streaming).

Decoding is greedy (temperature 0) and thinking stays off, as in the in-process pipeline. The API
key, if the server needs one, comes from REGULUS_MODEL_API_KEY and is never recorded. Standard
library only.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any
from urllib.parse import urlparse

from regulus.inference.types import GenerationResult


class OpenAICompatibleGenerator:
    def __init__(self, endpoint: str, model: str, *, timeout: float = 600.0, api_key_env: str = "REGULUS_MODEL_API_KEY") -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model_id = model
        self.timeout = timeout
        self._api_key_env = api_key_env
        self.tokenizer = None  # token counts come from the server's usage report

    def _request(self, body: dict[str, Any]):
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(self._api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(f"{self.endpoint}/chat/completions", data=json.dumps(body).encode("utf-8"), headers=headers)
        return urllib.request.urlopen(req, timeout=self.timeout)

    def generate(self, messages, max_new_tokens: int | None = None, on_text=None) -> GenerationResult:
        body: dict[str, Any] = {"model": self.model_id, "messages": list(messages), "temperature": 0,
                                "stream": on_text is not None}
        if max_new_tokens:
            body["max_tokens"] = int(max_new_tokens)
        if on_text is not None:
            body["stream_options"] = {"include_usage": True}
        start = time.perf_counter()
        first = None
        text, finish, usage = "", None, {}
        with self._request(body) as resp:
            if on_text is None:
                data = json.loads(resp.read().decode("utf-8"))
                choice = (data.get("choices") or [{}])[0]
                text = (choice.get("message") or {}).get("content") or ""
                finish, usage = choice.get("finish_reason"), data.get("usage") or {}
            else:
                for raw in resp:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    event = json.loads(payload)
                    usage = event.get("usage") or usage
                    for choice in event.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content") or ""
                        if delta:
                            if first is None:
                                first = time.perf_counter() - start
                            text += delta
                            on_text(delta)
                        finish = choice.get("finish_reason") or finish
        seconds = time.perf_counter() - start
        last = messages[-1]["content"] if messages else ""
        return GenerationResult(
            prompt=last, response=text.strip(),
            prompt_tokens=int(usage.get("prompt_tokens") or 0), generated_tokens=int(usage.get("completion_tokens") or 0),
            seconds=seconds, finished=(None if finish is None else finish == "stop"), first_token_seconds=first,
        )

    def describe(self) -> dict[str, Any]:
        host = urlparse(self.endpoint)
        return {"model_id": self.model_id, "model_revision": None, "backend": "openai_compatible",
                "endpoint_host": f"{host.scheme}://{host.hostname}{':' + str(host.port) if host.port else ''}",
                "device": "remote", "dtype": None,
                "generation": {"do_sample": False, "temperature": 0, "enable_thinking": False}}


def load_generator(settings, *, local_files_only: bool = False):
    """The configured Generator: in-process transformers (default) or an OpenAI-compatible server."""
    if settings.model.backend == "openai_compatible":
        return OpenAICompatibleGenerator(settings.model.endpoint, settings.model.id)
    from regulus.rag.generator import load_qwen_generator

    return load_qwen_generator(settings, local_files_only=local_files_only)


# ------------------------------------------------------------------ the UI's guarded remote generator
#
# The answering UI (scripts/serve_ui.py) reaches the GPU server through OpenAICompatibleGenerator, wrapped
# here so that (a) a failure becomes an InferenceError whose message names only a category - never the
# endpoint URL, a header or the server's text, which the UI returns to the page, logs and records - and
# (b) a response that carries neither text nor a finish reason (an empty or malformed body) is a failure,
# not an empty draft for the pipeline to "repair" into an answer. The acceptance runner keeps using
# load_generator unchanged.

INFERENCE_FAILURES = ("timeout", "connection", "http_status", "invalid_response", "other")


class InferenceError(RuntimeError):
    """Remote inference failed. `category` is one of INFERENCE_FAILURES; the message carries nothing else."""

    def __init__(self, category: str, detail: str = "") -> None:
        self.category = category
        super().__init__(f"remote inference failed ({category}{': ' + detail if detail else ''})")


def _category(exc: BaseException) -> tuple[str, str]:
    import socket
    import urllib.error

    if isinstance(exc, urllib.error.HTTPError):
        return "http_status", f"HTTP {exc.code}"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout", ""
    if isinstance(exc, urllib.error.URLError):
        return ("timeout", "") if isinstance(exc.reason, (socket.timeout, TimeoutError)) else ("connection", "")
    if isinstance(exc, (ConnectionError, OSError)):
        return "connection", ""
    if isinstance(exc, (ValueError, KeyError, TypeError, AttributeError, IndexError, UnicodeDecodeError)):
        return "invalid_response", ""
    return "other", type(exc).__name__


class GuardedRemoteGenerator:
    """OpenAICompatibleGenerator for the UI: categorised, redacted failures; malformed responses rejected.

    `passthrough` exceptions (the UI's client-disconnect signal, raised from inside `on_text`) propagate
    unchanged, so a cancelled stream is still a cancellation and not an inference failure."""

    def __init__(self, inner: OpenAICompatibleGenerator, *, passthrough: tuple[type[BaseException], ...] = ()) -> None:
        self.inner = inner
        self.passthrough = passthrough
        self.model_id = inner.model_id
        self.tokenizer = None

    def generate(self, messages, max_new_tokens: int | None = None, on_text=None) -> GenerationResult:
        try:
            result = self.inner.generate(messages, max_new_tokens=max_new_tokens, on_text=on_text)
        except self.passthrough:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised as a category, without the original text
            category, detail = _category(exc)
            raise InferenceError(category, detail) from None
        if not result.response and result.finished is None:
            raise InferenceError("invalid_response", "no text and no finish reason")
        return result

    def describe(self) -> dict[str, Any]:
        """Identity safe to record: the endpoint is hashed, never written out (it may be a private address)."""
        import hashlib

        parsed = urlparse(self.inner.endpoint)
        return {"backend": "openai_compatible", "model_id": self.inner.model_id, "model_revision": None,
                "model_revision_source": "unknown: an OpenAI-compatible server does not report a weights revision",
                "endpoint_scheme": parsed.scheme or None,
                "endpoint_sha256": hashlib.sha256(self.inner.endpoint.encode("utf-8")).hexdigest(),
                "endpoint_is_loopback": (parsed.hostname or "") in ("127.0.0.1", "::1", "localhost"),
                "timeout_seconds": self.inner.timeout, "api_key_configured": bool(os.environ.get(self.inner._api_key_env)),
                "generation": {"do_sample": False, "temperature": 0, "enable_thinking": False}}

    def served_models(self, timeout: float = 10.0) -> dict[str, Any]:
        """GET {endpoint}/models: which model ids the server says it serves. Best effort, never raises."""
        headers = {}
        key = os.environ.get(self.inner._api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            req = urllib.request.Request(f"{self.inner.endpoint}/models", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            ids = [m.get("id") for m in data.get("data") or [] if isinstance(m, dict)]
            roots = sorted({m.get("root") for m in data.get("data") or [] if isinstance(m, dict) and m.get("root")})
            return {"checked": True, "served_ids": ids, "roots": roots,
                    "configured_id_served": self.inner.model_id in ids}
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "category": _category(exc)[0]}
