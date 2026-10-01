"""Local web UI for testing the Regulus RAG pipeline by hand.

Runs entirely on this machine: it needs the read-only PostgreSQL database and
the local Qwen weights, so it cannot be a hosted page. Standard library only,
no new dependencies.

    python scripts/serve_ui.py
    python scripts/serve_ui.py --port 8000 --adapter models/qwen3-0.6b-lora/stage13_v1/adapter

Then open http://127.0.0.1:8000 in a browser.

What it exposes, per question: the generated answer, the authoritative
citations, every retrieved source with its score and retrieval method, the
grounding gate's decision, and the timings. Adapter and gate can be switched
from the page without restarting, so base / Stage 12 / Stage 13 and gate
on / off can be compared on the same question.

The database is opened read-only through the Stage 5 layer; nothing here
writes anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from regulus.config import PROJECT_ROOT, load_settings
from regulus.evaluation.runner import sanitize_error

WEB_DIR = PROJECT_ROOT / "web"
ADAPTER_ROOT = PROJECT_ROOT / "models" / "qwen3-0.6b-lora"

# one inference at a time: the model is not safe to share across threads and
# this machine cannot run two anyway
_LOCK = threading.Lock()


class Engine:
    """Holds the loaded model and database, and answers one question at a time."""

    def __init__(self, settings, offline: bool) -> None:
        from regulus.model import load_model, load_tokenizer
        from regulus.retrieval import Database

        self.settings = settings
        print("Loading tokenizer and model ...", flush=True)
        t0 = time.perf_counter()
        self.tokenizer = load_tokenizer(settings.model, local_files_only=offline)
        self.base_model = load_model(settings.model, local_files_only=offline)
        # The default selection ("") is the configured model: the base model,
        # or the adapter configured in configs/model.yaml / REGULUS_ADAPTER.
        self.default_info: dict = {}
        if settings.model.adapter is not None:
            from regulus.finetune import attach_saved_adapter

            print(f"Merging configured adapter {settings.model.adapter} ...", flush=True)
            self.base_model, self.default_info = attach_saved_adapter(self.base_model, settings.model.adapter, merge=True)
        print(f"Model ready in {time.perf_counter() - t0:.1f}s on {self.base_model.device} ({self.base_model.dtype})", flush=True)
        self.db = Database.from_env()
        self.db.connect()
        status = self.db.status()
        print(f"Database {status['database']} read-only={status['default_transaction_read_only']}", flush=True)
        self.snapshot = self.db.query("SELECT max(snapshot_date)::text AS d FROM cfr_records WHERE removed_on IS NULL")[0]["d"]
        self._models: dict[str, object] = {"": self.base_model}
        self._adapter_info: dict[str, dict] = {"": self.default_info}

    # -- adapters ---------------------------------------------------------

    def available_adapters(self) -> list[dict]:
        default = (f"Configured: {self.default_info.get('adapter_name')} adapter" if self.default_info
                   else "Base Qwen3-0.6B (no adapter)")
        out = [{"id": "", "label": default}]
        if ADAPTER_ROOT.is_dir():
            for d in sorted(ADAPTER_ROOT.iterdir()):
                # smoke_tmp holds a one-step throwaway adapter; never offer it
                if d.name.startswith("smoke"):
                    continue
                cfg = d / "adapter" / "adapter_config.json"
                if cfg.is_file():
                    out.append({"id": d.name, "label": f"{d.name} adapter"})
        return out

    def model_for(self, adapter_id: str):
        """Load and cache a merged adapter model. Each costs ~2.4 GB, so only
        the ones actually asked for are kept."""
        if adapter_id in self._models:
            return self._models[adapter_id], self._adapter_info[adapter_id]
        from regulus.finetune import load_adapter_model

        path = ADAPTER_ROOT / adapter_id / "adapter"
        print(f"Loading adapter {adapter_id} ...", flush=True)
        model, info = load_adapter_model(self.settings.model, path, merge=True, local_files_only=True)
        self._models[adapter_id] = model
        self._adapter_info[adapter_id] = info
        return model, info

    # -- answering --------------------------------------------------------

    def ask(self, question: str, *, adapter: str = "", grounding: bool = False,
            top_k: int = 8, max_new_tokens: int | None = None, on_event=None) -> dict:
        """Answer one question. `on_event` (streaming) is passed to the pipeline
        unchanged; the returned dict is the same with or without it."""
        from dataclasses import replace
        from regulus.rag import QwenGenerator, RagPipeline
        from regulus.retrieval import LexicalRetriever
        from regulus.system_identity import configured_generation_config, configured_rag_config

        t_setup = time.perf_counter()
        model, adapter_info = self.model_for(adapter)
        # The configured pipeline (the same definition the dashboard and Stage 5
        # use), with the page's two controls applied on top. The page's token
        # control is the hard safety ceiling, not a target length; the pipeline
        # still sets each question's allowance from plan, coverage and evidence.
        config = configured_rag_config(self.settings)
        if getattr(self, "answer_shape", None):
            config = replace(config, answer_shape=self.answer_shape)
        budget = config.generation_budget
        if max_new_tokens:
            budget = replace(budget, hard_max_tokens=max_new_tokens)
        gen = replace(configured_generation_config(self.settings), max_new_tokens=budget.hard_max_tokens)
        gate = None
        if grounding:
            from regulus.grounding import DatabaseIdentifierIndex, GroundingConfig, GroundingGate

            gate = GroundingGate(DatabaseIdentifierIndex(self.db), GroundingConfig(enabled=True), snapshot_date=self.snapshot)
        # Stage 7: the answering pipeline's retriever (semantic fallback) and scope policy, built once
        if getattr(self, "_retrieval", None) is None:
            from regulus.retrieval.factory import build_retriever

            self._retrieval = build_retriever(self.db, config, lexical=LexicalRetriever(self.db))
        retriever, scope = self._retrieval
        pipeline = RagPipeline(
            retriever,
            QwenGenerator(model, self.tokenizer, gen, self.settings.model.id),
            replace(config, top_k=top_k, generation_budget=budget),
            grounding=gate,
            scope_policy=scope,
        )
        setup_ms = round((time.perf_counter() - t_setup) * 1000, 2)
        t_answer = time.perf_counter()
        out = pipeline.answer(question, on_event=on_event)
        answer_ms = round((time.perf_counter() - t_answer) * 1000, 2)
        t_build = time.perf_counter()
        g = out.metadata.get("grounding")
        result = {
            "question": out.question,
            "answer": out.answer,
            "model_called": out.model_called,
            "no_context": out.no_context,
            "citations": [
                {"index": c.index, "label": c.label, "corpus": c.corpus, "url": c.url, "cited_in_answer": c.cited_in_answer,
                 "tier": c.tier, "requirement_ids": list(c.requirement_ids), "role": c.role}
                for c in out.citations
            ],
            "sources": [
                {
                    "index": s.index,
                    "citation": s.result.citation.label,
                    "corpus": s.result.corpus,
                    "heading": s.result.citation.heading or s.result.citation.document_title,
                    "method": s.result.retrieval_method,
                    "score": round(s.result.relevance_score, 3),
                    "url": s.result.source_url,
                    "text": s.text,
                    "truncated": s.truncated,
                    # Stage 3 provenance (None/empty on the legacy path)
                    "tier": s.tier,
                    "requirement_ids": list(s.requirement_ids),
                    "protected": s.protected,
                    "selection_reason": s.selection_reason,
                }
                for s in out.context.sources
            ],
            "dropped_sources": out.context.dropped,
            "notes": list(out.context.notes),
            "grounding": g,
            "retrieval": out.metadata.get("retrieval", {}),
            "query_type": out.metadata.get("query_type"),
            # Stage 1-3 diagnostics for the raw JSON panel
            "plan": out.metadata.get("plan"),
            "evidence": out.metadata.get("evidence"),
            "coverage": out.metadata.get("coverage"),
            "coverage_action": out.metadata.get("coverage_action"),
            "selection": out.metadata.get("selection"),
            # Stage 12
            "answer_shape": out.metadata.get("answer_shape"),
            # answer-quality Stage 3 ("structured" only)
            "question_analysis": out.metadata.get("question_analysis"),
            "quality_flags": out.metadata.get("quality_flags"),
            "normalization": out.metadata.get("normalization"),
            # Stage 4
            "generation": out.metadata.get("generation"),
            "validation": out.metadata.get("validation"),
            "citation_support": out.metadata.get("citation_support"),
            # Stage 5 answerability gate and safe fallback (diagnostics panel only)
            **{k: out.metadata.get(k) for k in ("answerability", "generation_called", "generation_blocked", "block_reason",
                                                "fallback_type", "fallback_reason", "scope_policy", "semantic_fallback",
                                                "reference_lookup")},
            "timings_ms": out.timings_ms,
            "input_tokens": out.input_tokens,
            "output_tokens": out.output_tokens,
            "adapter": {"id": adapter, "name": adapter_info.get("adapter_name"), "r": adapter_info.get("r"), "dataset_hash": adapter_info.get("dataset_hash")},
            "snapshot_date": self.snapshot,
        }
        # latency baseline: server-side stages around the pipeline
        result["server_timings_ms"] = {"engine_setup_ms": setup_ms, "pipeline_answer_ms": answer_ms,
                                       "response_build_ms": round((time.perf_counter() - t_build) * 1000, 2)}
        return result


class Handler(BaseHTTPRequestHandler):
    engine: Engine = None  # set on the class before serving

    def log_message(self, fmt, *args):  # quieter console
        if "api/ask" in (args[0] if args else ""):
            print(f"  {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = WEB_DIR / "index.html"
            if not page.is_file():
                self._json(500, {"error": "web/index.html is missing"})
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/config":
            self._json(200, {
                "adapters": self.engine.available_adapters(),
                "model_id": self.engine.settings.model.id,
                "device": str(self.engine.base_model.device),
                "dtype": str(self.engine.base_model.dtype).replace("torch.", ""),
                "snapshot_date": self.engine.snapshot,
                "defaults": {"top_k": 8, "max_new_tokens": self.engine.settings.answer_length.max_new_tokens},
                "answer_length": {
                    "policy": self.engine.settings.answer_length.policy,
                    "ceiling": self.engine.settings.answer_length.max_new_tokens,
                    "note": ("the ceiling is a safety limit against a model that never stops, not a target "
                             "length; the pipeline sets each question's allowance from its evidence"),
                },
            })
            return
        self._json(404, {"error": "not found"})

    @staticmethod
    def _ask_kwargs(body: dict) -> dict:
        return {
            "adapter": str(body.get("adapter") or ""),
            "grounding": bool(body.get("grounding")),
            "top_k": max(1, min(int(body.get("top_k") or 8), 20)),
            "max_new_tokens": (max(64, min(int(body["max_new_tokens"]), 4096)) if body.get("max_new_tokens") else None),
        }

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/ask/stream":
            self._ask_stream()
            return
        if path != "/api/ask":
            self._json(404, {"error": "not found"})
            return
        t_request = time.perf_counter()
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            question = (body.get("question") or "").strip()
            if not question:
                self._json(400, {"error": "question must not be empty"})
                return
            t0 = time.perf_counter()
            parse_ms = round((t0 - t_request) * 1000, 2)
            with _LOCK:
                lock_wait_ms = round((time.perf_counter() - t0) * 1000, 2)
                result = self.engine.ask(question, **self._ask_kwargs(body))
            result["wall_seconds"] = round(time.perf_counter() - t0, 1)
            result["server_timings_ms"].update({"request_parse_ms": parse_ms, "lock_wait_ms": lock_wait_ms})
            t_send = time.perf_counter()
            self._json(200, result)
            # serialisation + socket write cannot be reported inside the body it produces: logged instead
            print(f"  timing: serialize+send {round((time.perf_counter() - t_send) * 1000, 2)} ms, "
                  f"request total {round((time.perf_counter() - t_request) * 1000, 2)} ms", flush=True)
        except Exception as exc:  # never leak a path or a stack trace to the page
            traceback.print_exc()
            self._json(500, {"error": sanitize_error(exc)})

    # -- streaming ----------------------------------------------------------

    def _ask_stream(self) -> None:
        """POST /api/ask/stream: the same answer as /api/ask, as newline-delimited JSON events.

        One event per line, flushed as it happens:
            {"type": "start"}
            {"type": "context", "sources": [...], "no_context": bool}   sources selected for the model
            {"type": "generation_started", "max_new_tokens": n}
            {"type": "delta", "text": "..."}                            DRAFT text of the one generation
            {"type": "generation_finished", "generated_tokens": n, "finished": bool}
            {"type": "final", "result": {...}}                          the validated answer: exactly what
                                                                        /api/ask returns, plus "stream" stats
            {"type": "error", "error": "..."}                           instead of "final" when it fails
        The stream always ends with exactly one "final" or "error" event. Drafts are
        never final: validation and repair run after generation, as they always did,
        and may change the text. A client that disconnects stops the generation.
        """
        t_request = time.perf_counter()
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            question = (body.get("question") or "").strip()
            kwargs = self._ask_kwargs(body)
        except Exception as exc:
            self._json(400, {"error": sanitize_error(exc)})
            return
        if not question:
            self._json(400, {"error": "question must not be empty"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()  # HTTP/1.0 response without Content-Length: the body ends when the connection closes

        stats = {"deltas": 0, "first_delta_ms": None, "delta_chars": 0}

        def send(event: dict) -> None:
            try:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as exc:
                raise ClientDisconnected() from exc

        def on_event(kind: str, data: dict) -> None:
            if kind == "delta":
                stats["deltas"] += 1
                stats["delta_chars"] += len(data.get("text", ""))
                if stats["first_delta_ms"] is None:
                    stats["first_delta_ms"] = round((time.perf_counter() - t_request) * 1000, 2)
            send({"type": kind, **data})

        try:
            send({"type": "start"})
            t0 = time.perf_counter()
            with _LOCK:
                lock_wait_ms = round((time.perf_counter() - t0) * 1000, 2)
                result = self.engine.ask(question, on_event=on_event, **kwargs)
            result["wall_seconds"] = round(time.perf_counter() - t0, 1)
            result.setdefault("server_timings_ms", {}).update({"lock_wait_ms": lock_wait_ms})
            result["stream"] = {**stats, "final_ms": round((time.perf_counter() - t_request) * 1000, 2)}
            send({"type": "final", "result": result})
            print(f"  stream: {stats['deltas']} deltas, first at {stats['first_delta_ms']} ms, "
                  f"final at {result['stream']['final_ms']} ms", flush=True)
        except ClientDisconnected:
            print(f"  stream: client disconnected after {stats['deltas']} deltas; generation stopped", flush=True)
        except Exception as exc:  # never leak a path or a stack trace to the page
            traceback.print_exc()
            try:
                send({"type": "error", "error": sanitize_error(exc)})
            except ClientDisconnected:
                pass


class ClientDisconnected(Exception):
    """The streaming client went away; raised out of the generation to stop it."""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1", help="loopback by default; this UI has no authentication")
    p.add_argument("--offline", action="store_true", help="fail instead of downloading the model")
    p.add_argument("--device", choices=("auto", "cpu", "mps"), default=None,
                   help="override model.device (configs/model.yaml / REGULUS_DEVICE); mps = Apple GPU, opt-in")
    p.add_argument("--dtype", choices=("auto", "float32", "float16", "bfloat16"), default=None,
                   help="override model.dtype (configs/model.yaml / REGULUS_DTYPE)")
    p.add_argument("--answer-shape", choices=("off", "adaptive", "structured"), default=None,
                   help="override RagConfig.answer_shape; 'structured' = answer-quality Stage 3 (default: as configured)")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    settings = load_settings()
    if args.device or args.dtype:
        from dataclasses import replace as _replace

        settings.model = _replace(settings.model, device=args.device or settings.model.device,
                                  dtype=args.dtype or settings.model.dtype)
        settings.model.validate()
    Handler.engine = Engine(settings, offline=args.offline)
    Handler.engine.answer_shape = args.answer_shape
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print()
    print(f"  Regulus test UI:  http://{args.host}:{args.port}")
    print("  Ctrl+C to stop. Answers take 30-90 s on this CPU.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping ...")
    finally:
        Handler.engine.db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
