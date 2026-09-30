"""Pipeline logging and resource checks shared by the Stage 5 / Stage 6 runners.

The log file is the operator's view of an unattended run: every line is
timestamped, tagged phases ([STAGE 5], [TRAINING], ...) are written verbatim,
and failures land as [ERROR] with the traceback followed by [STOPPED].
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Hard floor: below this the model cannot be loaded at all on this machine.
# Measured: the base model's resident set is about 2.4 GB and Windows trims the
# working sets of idle applications to make room, so runs succeed well below
# 2.4 GB "available". Between the floor and COMFORTABLE_RAM_GB the run proceeds
# but is logged as slow-risk: paging, not failure, is the expected cost.
MIN_AVAILABLE_RAM_GB = 1.0
COMFORTABLE_RAM_GB = 3.0
OTHER_MODEL_PROCESS_RSS_GB = 1.2  # another Python process above this is assumed to hold a model


class ResourceError(RuntimeError):
    pass


class PipelineLog:
    def __init__(self, path: Path, echo: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self._fh = self.path.open("a", encoding="utf-8")

    def _write(self, line: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = f"{stamp} {line}"
        self._fh.write(text + "\n")
        self._fh.flush()
        if self.echo:
            try:
                print(text, flush=True)
            except UnicodeEncodeError:
                print(text.encode("ascii", "replace").decode("ascii"), flush=True)

    def info(self, message: str) -> None:
        self._write(message)

    def tag(self, name: str, message: str = "") -> None:
        self._write(f"[{name}] {message}".rstrip())

    def error(self, exc: BaseException, context: str = "") -> None:
        self._write(f"[ERROR] {context}{': ' if context else ''}{type(exc).__name__}: {exc}")
        for line in traceback.format_exception(type(exc), exc, exc.__traceback__):
            for sub in line.rstrip("\n").splitlines():
                self._fh.write(f"    {sub}\n")
        self._fh.flush()
        self._write("[STOPPED]")

    def __call__(self, message: str) -> None:  # usable as the finetune `log` callable
        self.info(message)

    def close(self) -> None:
        self._fh.close()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def resource_report() -> dict[str, Any]:
    """Available RAM and other Python processes that look like they hold a model."""
    try:
        import psutil
    except ImportError:  # pragma: no cover
        return {"available_ram_gb": None, "other_model_processes": [], "psutil": False}
    vm = psutil.virtual_memory()
    me = os.getpid()
    others: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.pid == me or not p.info["name"] or "python" not in p.info["name"].lower():
                continue
            rss = p.memory_info().rss / 1e9
            if rss >= OTHER_MODEL_PROCESS_RSS_GB:
                others.append({"pid": p.pid, "rss_gb": round(rss, 2), "cmdline": " ".join(p.info["cmdline"] or [])[-80:]})
        except Exception:  # process vanished or access denied
            continue
    return {"available_ram_gb": round(vm.available / 1e9, 2), "total_ram_gb": round(vm.total / 1e9, 2), "other_model_processes": others, "psutil": True}


def ensure_resources(log: PipelineLog | None = None, *, min_available_gb: float = MIN_AVAILABLE_RAM_GB, allow_other_models: bool = False) -> dict[str, Any]:
    """Fail before a model load or a training run that could not fit."""
    rep = resource_report()
    if log:
        log.info(f"Resources: available RAM {rep.get('available_ram_gb')} GB of {rep.get('total_ram_gb')} GB; other model-sized Python processes: {len(rep.get('other_model_processes', []))}")
    avail = rep.get("available_ram_gb")
    if avail is not None and avail < min_available_gb:
        raise ResourceError(f"only {avail} GB RAM available; at least {min_available_gb} GB is needed to load the model at all")
    if avail is not None and avail < COMFORTABLE_RAM_GB and log:
        log.info(f"WARNING: {avail} GB available is below the comfortable {COMFORTABLE_RAM_GB} GB. The run will proceed but generation will page; closing editors or browser windows would speed it up.")
    if rep.get("other_model_processes") and not allow_other_models:
        listing = ", ".join(f"pid {o['pid']} ({o['rss_gb']} GB)" for o in rep["other_model_processes"])
        raise ResourceError(f"another model-sized Python process is running ({listing}); stop it first (for example the UI server) so two models never share this machine")
    return rep
