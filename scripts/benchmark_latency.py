"""Latency baseline: the configured answering pipeline, stage by stage.

    python scripts/benchmark_latency.py
    python scripts/benchmark_latency.py --ids S5-001 S5-012 --label quick
    python scripts/benchmark_latency.py --ids all --with-answer-shape --device mps --dtype float16 --label mps_fp16

Loads the configured model exactly as the answering UI does (same settings,
greedy decoding, thinking off), then runs existing Stage 5 questions through
`RagPipeline.answer()` with the production configuration (validation
"repair"). Nothing about the answer is changed; this only reads the timings
the pipeline and `generate_chat()` now record, and samples CPU and memory
while it runs.

Reported per question and summarised (median / p90 / mean):
    plan, retrieval (incl. plan), context (coverage + selection), package,
    prompt render, model tokenize, model first token (prefill + first step),
    model decode, detokenize, validation (+ repair), citations, diagnostics
    payload, total; prompt tokens, generated tokens, overall and decode-only
    tokens/second, sources in context, context characters; process CPU %,
    RSS, system memory pressure and swap.

The first question after loading is reported separately (cold) and excluded
from the warm statistics. Output: artifacts/latency/<label>_<utc>/.
The database is read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import platform
import statistics
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import psutil

from regulus.config import PROJECT_ROOT, load_settings
from regulus.rag.generation import build_grounded_messages
from regulus.rag.prompt import build_messages
from regulus.rag import RagPipeline, load_qwen_generator
from regulus.retrieval import Database, LexicalRetriever
from regulus.system_identity import configured_generation_config, configured_rag_config

DATASET = PROJECT_ROOT / "data" / "evaluation" / "datasets" / "stage5_v1.jsonl"
SHAPE_DATASET = PROJECT_ROOT / "data" / "evaluation" / "datasets" / "answer_shape_v1.jsonl"
OUT_ROOT = PROJECT_ROOT / "artifacts" / "latency"
# one or more of every path the pipeline has: single, parent, section, multi,
# range, partial, not found (no model call), general, guidance, out of domain, long
DEFAULT_IDS = ("S5-001", "S5-004", "S5-006", "S5-011", "S5-012", "S5-013", "S5-022", "S5-024", "S5-033",
               "S5-042", "S5-043", "S5-060", "S5-070", "S5-080", "S5-100")
STAGES = ("plan_ms", "retrieval_ms", "context_ms", "package_ms", "prompt_ms", "model_prepare_ms", "model_first_token_ms",
          "model_decode_ms", "model_detokenize_ms", "generation_ms", "validation_ms", "citations_ms", "metadata_ms", "total_ms")


_GPU_UTIL_RE = re.compile(r'"Device Utilization %"=(\d+)')


def gpu_utilization() -> int | None:
    """Apple GPU utilisation % from the IOAccelerator registry (no sudo needed); None if unreadable."""
    try:
        out = subprocess.run(["ioreg", "-r", "-c", "IOAccelerator", "-d", "1"], capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return None
    m = _GPU_UTIL_RE.search(out)
    return int(m.group(1)) if m else None


def mps_memory_mb() -> dict:
    import torch

    if not torch.backends.mps.is_available():
        return {}
    return {"mps_allocated_mb": round(torch.mps.current_allocated_memory() / 2**20),
            "mps_driver_mb": round(torch.mps.driver_allocated_memory() / 2**20)}


class Sampler:
    """Samples this process's CPU % and RSS, system memory and swap, and Apple GPU utilisation."""

    def __init__(self, interval: float = 0.5) -> None:
        self.proc = psutil.Process()
        self.interval = interval
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        self.proc.cpu_percent(None)
        psutil.cpu_percent(None)
        while not self._stop.wait(self.interval):
            vm, sw = psutil.virtual_memory(), psutil.swap_memory()
            self.samples.append({"t": time.perf_counter(), "proc_cpu": self.proc.cpu_percent(None),
                                 "sys_cpu": psutil.cpu_percent(None), "rss_mb": self.proc.memory_info().rss / 2**20,
                                 "mem_available_mb": vm.available / 2**20, "swap_used_mb": sw.used / 2**20,
                                 "gpu_util": gpu_utilization()})

    def start(self) -> "Sampler":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def window(self, t0: float, t1: float) -> dict:
        s = [x for x in self.samples if t0 <= x["t"] <= t1]
        if not s:
            return {}
        return {"proc_cpu_mean": round(statistics.mean(x["proc_cpu"] for x in s), 1),
                "sys_cpu_mean": round(statistics.mean(x["sys_cpu"] for x in s), 1),
                "rss_mb_max": round(max(x["rss_mb"] for x in s)), "mem_available_mb_min": round(min(x["mem_available_mb"] for x in s)),
                "swap_used_mb_max": round(max(x["swap_used_mb"] for x in s)),
                "gpu_util_mean": (round(statistics.mean(g), 1) if (g := [x["gpu_util"] for x in s if x["gpu_util"] is not None]) else None),
                "gpu_util_max": max(g) if g else None}


def stats(values: list[float]) -> dict:
    v = sorted(x for x in values if x is not None)
    if not v:
        return {}
    p90 = v[min(len(v) - 1, round(0.9 * (len(v) - 1)))]
    return {"n": len(v), "median": round(statistics.median(v), 1), "p90": round(p90, 1), "mean": round(statistics.mean(v), 1),
            "min": round(v[0], 1), "max": round(v[-1], 1)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ids", nargs="*", default=list(DEFAULT_IDS))
    p.add_argument("--label", default="baseline")
    p.add_argument("--with-answer-shape", action="store_true", help="also run data/evaluation/datasets/answer_shape_v1.jsonl")
    p.add_argument("--device", choices=("auto", "cpu", "mps"), default=None, help="override model.device")
    p.add_argument("--dtype", choices=("auto", "float32", "float16", "bfloat16"), default=None, help="override model.dtype")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    items = {json.loads(l)["id"]: json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()}
    questions = list(items.values()) if args.ids == ["all"] else [items[i] for i in args.ids]
    if args.with_answer_shape:
        questions += [{**q, "category": q["dimension"]} for q in
                      (json.loads(l) for l in SHAPE_DATASET.read_text(encoding="utf-8").splitlines() if l.strip())]
    out_dir = OUT_ROOT / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=False)
    sampler = Sampler().start()

    settings = load_settings()
    if args.device or args.dtype:
        settings.model = replace(settings.model, device=args.device or settings.model.device, dtype=args.dtype or settings.model.dtype)
        settings.model.validate()
    settings.generation = configured_generation_config(settings)
    t_load = time.perf_counter()
    generator = load_qwen_generator(settings, local_files_only=True)
    load_s = time.perf_counter() - t_load
    model = generator.model
    params = sum(p.numel() for p in model.parameters())
    param_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
    db = Database.from_env()
    db.connect()
    pipeline = RagPipeline(LexicalRetriever(db), generator, configured_rag_config(settings))

    vm = psutil.virtual_memory()
    env = {
        "model_id": generator.model_id, "parameters": params, "weights_mb_in_memory": round(param_bytes / 2**20),
        "device": str(model.device), "dtype": str(model.dtype).replace("torch.", ""),
        "context_window_tokens": getattr(model.config, "max_position_embeddings", None),
        "torch_threads": __import__("torch").get_num_threads(),
        "mps_available": __import__("torch").backends.mps.is_available(),
        "machine": platform.machine(), "processor": platform.processor(), "cpu_logical": psutil.cpu_count(),
        "cpu_physical": psutil.cpu_count(logical=False), "ram_total_mb": round(vm.total / 2**20),
        "model_load_s": round(load_s, 2), "configured_device": settings.model.device, "configured_dtype": settings.model.dtype,
        "generation": {k: getattr(settings.generation, k) for k in ("do_sample", "temperature", "top_p", "top_k", "enable_thinking",
                                                                   "repetition_penalty", "no_repeat_ngram_size")},
        "mps_after_load": mps_memory_mb(), "answer_length": settings.answer_length.__dict__ if hasattr(settings.answer_length, "__dict__") else None,
    }
    print(json.dumps(env, indent=1), flush=True)
    (out_dir / "environment.json").write_text(json.dumps(env, indent=1, default=str), encoding="utf-8")

    rows = []
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as fh:
        for n, q in enumerate(questions):
            t0 = time.perf_counter()
            out = pipeline.answer(q["question"])
            t1 = time.perf_counter()
            g = out.metadata.get("generation") or {}
            messages = build_grounded_messages(out.package) if out.package is not None else build_messages(q["question"], out.context.text)
            v = out.metadata.get("validation") or {}
            row = {
                "id": q["id"], "category": q["category"], "cold": n == 0, "model_called": out.model_called,
                "wall_ms": round((t1 - t0) * 1000, 2), "timings_ms": out.timings_ms,
                "retrieval_sql_ms": out.metadata.get("retrieval_timings_ms"),
                "prompt_tokens": out.input_tokens, "generated_tokens": out.output_tokens,
                "allowance": g.get("max_new_tokens"), "finished": g.get("finished"),
                "tokens_per_second": g.get("tokens_per_second"), "decode_tokens_per_second": g.get("decode_tokens_per_second"),
                "source_count": len(out.context.sources), "context_chars": len(out.context.text),
                "prompt_chars": g.get("prompt_chars"), "answer_chars": len(out.answer),
                "resources": {**sampler.window(t0, t1), **mps_memory_mb()},
                # everything the equivalence check compares (scripts/compare_inference_runs.py)
                "question": q["question"],
                "prompt_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode("utf-8")).hexdigest(),
                "answer": out.answer,
                "citations": [c.to_dict() for c in out.citations],
                "sources": [{"index": s.index, "citation": s.result.citation.label, "key": s.result.key, "tier": s.tier}
                            for s in out.context.sources],
                "validation_initial": v.get("initial"), "validation_final": v.get("final"), "repair": v.get("repair"),
                "coverage_action": out.metadata.get("coverage_action"),
                "citation_support": out.metadata.get("citation_support"),
            }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            rows.append(row)
            t = out.timings_ms
            print(f"{q['id']:7} {q['category']:15} total {t['total_ms'] / 1000:6.1f}s  retrieval {t['retrieval_ms']:7.1f}ms  "
                  f"first-token {t.get('model_first_token_ms', 0) / 1000:5.1f}s  decode {t.get('model_decode_ms', 0) / 1000:6.1f}s  "
                  f"tokens {out.input_tokens}->{out.output_tokens}  {row['decode_tokens_per_second']} tok/s", flush=True)
    sampler.stop()
    db.close()

    warm = [r for r in rows if not r["cold"]]
    gen_rows = [r for r in warm if r["model_called"]]
    summary = {
        "environment": env,
        "questions": len(rows), "warm_questions": len(warm), "warm_with_model_call": len(gen_rows),
        "cold_first_question": rows[0] if rows else None,
        "stage_ms_warm_model_called": {k: stats([r["timings_ms"].get(k) for r in gen_rows]) for k in STAGES},
        "stage_ms_warm_no_model": {k: stats([r["timings_ms"].get(k) for r in warm if not r["model_called"]]) for k in STAGES},
        "prompt_tokens": stats([r["prompt_tokens"] for r in gen_rows]),
        "generated_tokens": stats([r["generated_tokens"] for r in gen_rows]),
        "tokens_per_second_overall": stats([r["tokens_per_second"] for r in gen_rows]),
        "tokens_per_second_decode": stats([r["decode_tokens_per_second"] for r in gen_rows]),
        "prefill_tokens_per_second": stats([r["prompt_tokens"] / (r["timings_ms"]["model_first_token_ms"] / 1000)
                                            for r in gen_rows if r["timings_ms"].get("model_first_token_ms")]),
        "sources": stats([r["source_count"] for r in gen_rows]), "context_chars": stats([r["context_chars"] for r in gen_rows]),
        "proc_cpu_mean": stats([r["resources"].get("proc_cpu_mean") for r in gen_rows]),
        "rss_mb_max": max((r["resources"].get("rss_mb_max", 0) for r in rows), default=None),
        "swap_used_mb_max": max((r["resources"].get("swap_used_mb_max", 0) for r in rows), default=None),
        "mem_available_mb_min": min((r["resources"].get("mem_available_mb_min", 10**9) for r in rows), default=None),
        "gpu_util_mean": stats([r["resources"].get("gpu_util_mean") for r in gen_rows]),
        "mps_driver_mb_max": max((r["resources"].get("mps_driver_mb", 0) for r in rows), default=None),
        "total_generation_s": round(sum(r["timings_ms"].get("generation_ms", 0) for r in rows) / 1000, 1),
        "total_wall_s": round(sum(r["wall_ms"] for r in rows) / 1000, 1),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"\nwrote {out_dir}")
    print(json.dumps({k: summary[k] for k in ("stage_ms_warm_model_called", "tokens_per_second_decode", "generated_tokens", "prompt_tokens")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
