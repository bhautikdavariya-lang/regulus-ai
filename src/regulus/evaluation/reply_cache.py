"""Reply cache for evaluation runs: a model call seen before gets its recorded reply.

Decoding is greedy (do_sample=False), so the same messages, token limit and model give the same reply. A re-run then
generates only the prompts a change touched - the picker's calls and every unchanged answer are replayed. 300Q
full300c, 29 Oct: 11.8 h, of which the picker 2.8 h and answers 5.2 h.

The key is the messages, the token limit, any other generate() argument, the generator's whole describe() (model id and
revision, quantization, chat template, adapter, generation settings - read at every call, since the UI changes the
settings and the adapter per request) and KEY_VERSION. A generator that samples is never cached. Every GenerationResult
field is stored, so a replayed reply carries the same `finished` / `stop_reason` the validator reads. A damaged line (a
run killed mid-write) is skipped, never fatal. Thread-safe.

The app uses it when REGULUS_REPLY_CACHE names a file (`wrap_from_env`): the prompt holds the evidence text, so a
database, prompt or model change is a new key; retrieval, validation and the evaluator still run for every question.

Replay-only (`ReplayOnlyGenerator`, change-impact testing): no model is loaded. Every call the cache holds is replayed
and everything after it - validation, fallbacks, composers - runs on the code under test; a call it does not hold raises
CacheMiss, so the question is known to need the model (its prompt or token limit changed). The generator's describe()
is kept beside the cache (<cache>.ident.json) so replay-only keys equal the live ones.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from regulus.inference.types import GenerationResult

log = logging.getLogger(__name__)

KEY_VERSION = 2   # 1: section_resolution_eval.CachedGenerator (keyed a "revision" field describe() never had)
_STORED = tuple(f.name for f in dataclasses.fields(GenerationResult))


class CacheMiss(BaseException):
    """A replay-only run met a model call the cache does not hold: this question needs the model. A BaseException, like
    KeyboardInterrupt, on purpose: the pipeline wraps its aids (the picker among them) in `except Exception`, which would
    swallow a miss and answer the question down another path instead of reporting it."""

    def __init__(self, system: str) -> None:
        super().__init__(f"not in the reply cache: {system[:60]!r}")
        self.system = system


def ident_path(path: Path | str) -> Path:
    return Path(f"{path}.ident.json")


def sampling(ident: dict[str, Any]) -> bool:
    """True when the generator samples: its replies are not reproducible and must not be cached."""
    gen = ident.get("generation") or {}
    return bool(gen.get("do_sample")) or (gen.get("temperature") not in (None, 0, 0.0))


class CachedGenerator:
    """Wraps a generator; generate() answers from the cache file when the same call was made before. `fresh` and
    `cached` count the two outcomes."""

    def __init__(self, real, path: Path | str) -> None:
        self.real, self.path = real, Path(path)
        self._lock = threading.Lock()
        self._ident_saved: dict | None = None
        if not self.enabled:
            log.warning("reply cache off: the generator samples (%s)", self.ident().get("generation"))
        self.cache: dict[str, dict] = {}
        self.fresh = self.cached = self.skipped_lines = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    self.cache[rec["key"]] = rec
                except (json.JSONDecodeError, KeyError, TypeError):
                    self.skipped_lines += 1
            if self.skipped_lines:
                log.warning("reply cache %s: %d damaged line(s) skipped", self.path, self.skipped_lines)

    def ident(self) -> dict[str, Any]:
        return (self.real.describe() or {}) if hasattr(self.real, "describe") else {}

    @property
    def enabled(self) -> bool:
        return not sampling(self.ident())

    def key(self, messages, max_new_tokens, kw: dict, ident: dict | None = None) -> str:
        ident = self.ident() if ident is None else ident
        blob = json.dumps([KEY_VERSION, messages, max_new_tokens, sorted(kw.items()), ident],
                          sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def generate(self, messages, max_new_tokens=None, on_text=None, **kw) -> GenerationResult:
        call = {"max_new_tokens": max_new_tokens, **({"on_text": on_text} if on_text is not None else {}), **kw}
        ident = self.ident()
        if sampling(ident):
            self.fresh += 1
            return self.real.generate(messages, **call)
        key = self.key(messages, max_new_tokens, kw, ident)
        with self._lock:
            rec = self.cache.get(key)
        if rec is None:
            res = self.real.generate(messages, **call)
            rec = {"key": key, **{f: getattr(res, f) for f in _STORED}}
            with self._lock:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
                self.cache[key] = rec
                self.fresh += 1
                if self._ident_saved != ident:   # replay-only runs key their calls with this same describe()
                    ident_path(self.path).write_text(json.dumps(ident, sort_keys=True, default=str), encoding="utf-8")
                    self._ident_saved = ident
            return res
        with self._lock:
            self.cached += 1
        if on_text is not None and rec.get("response"):
            on_text(rec["response"])   # a streaming caller still sees the text once
        return GenerationResult(**{f: rec[f] for f in _STORED if f in rec})

    def counts(self) -> dict[str, int]:
        return {"fresh": self.fresh, "cached": self.cached}

    def __getattr__(self, name):
        return getattr(self.real, name)


class ReplayOnlyGenerator:
    """Stands in for the model in a replay-only run: describe() is the recorded model's, generate() raises CacheMiss
    (the CachedGenerator around it answers every call it holds before this is reached)."""

    retrieval_only = False

    def __init__(self, cache_path: Path | str) -> None:
        p = ident_path(cache_path)
        if not p.is_file():
            raise FileNotFoundError(f"{p}: no model identity recorded beside the cache - run live with this cache first")
        self.ident = json.loads(p.read_text(encoding="utf-8"))

    def describe(self) -> dict[str, Any]:
        return dict(self.ident)

    def generate(self, messages, max_new_tokens=None, on_text=None, **kw) -> GenerationResult:
        raise CacheMiss((messages[0].get("content") if messages else "") or "")

    def close(self) -> None:
        pass


def wrap_from_env(real, env: str = "REGULUS_REPLY_CACHE"):
    """`real` wrapped in a CachedGenerator when the environment variable names a cache file, else `real` itself."""
    path = (os.environ.get(env) or "").strip()
    if not path or path.lower() in ("0", "off", "none"):
        return real
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return CachedGenerator(real, path)
