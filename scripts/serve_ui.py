"""Local web UI for testing the Regulus RAG pipeline by hand.

Runs entirely on this machine: it needs the read-only PostgreSQL database and
the application's one model, Qwen3-1.7B 4-bit, run by the MLX worker, so it
cannot be a hosted page. Standard library only, no new dependencies.

    REGULUS_MLX_PYTHON=<python with mlx-lm> REGULUS_MLX_MODEL_PATH=<Qwen3-1.7B-MLX-4bit snapshot> \
        python scripts/serve_ui.py --port 8000

Then open http://127.0.0.1:8000 in a browser.

What it exposes, per question: the generated answer, the authoritative
citations, every retrieved source with its score and retrieval method, the
grounding gate's decision, the timings, and the live answer-accuracy
assessment. Adapter and gate can be switched from the page without restarting,
so base / Stage 12 / Stage 13 and gate on / off can be compared on the same
question.

The accuracy assessment (regulus.accuracy) is an OBSERVER and is deliberately
wired in here rather than in the pipeline: it runs after `pipeline.answer()`
has returned, reads only what the RagAnswer already carries, and cannot reach
the answer. `src/regulus/rag/` is untouched by the feature, so with
`--no-accuracy` (or `{"accuracy": false}` in the request) the answer, its
citations and its evidence are the same objects they would be without it.
Verify with `python scripts/accuracy_regression.py`.

The database is opened read-only through the Stage 5 layer. The server writes
only local, git-ignored files: chat history (data/chat/) and, unless
--no-measure, one measurement record per answered question
(data/ui_measurements/<session>/, regulus.traceability.ui_session; see
docs/measurement_record.md). Measurement, like the assessment, is an observer:
it is written after the answer has been sent and cannot change it.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import signal
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from regulus.accuracy import RUBRIC_ID as ACCURACY_RUBRIC_ID
from regulus.config import PROJECT_ROOT, load_settings
from regulus.conversations import (CANCELLED, ERROR, OK, ConversationNotFound, ConversationStore, InvalidInput)
from regulus.evaluation.runner import sanitize_error
from regulus.traceability.ui_session import DELIVERED, NOT_DELIVERED, UISession, code_revision, default_root

WEB_DIR = PROJECT_ROOT / "web"
ADAPTER_ROOT = PROJECT_ROOT / "models" / "qwen3-0.6b-lora"

# The application answers with ONE model: Qwen3-1.7B quantized to 4 bits, run by the MLX worker
# (regulus.rag.mlx_generator). There is no selector and no fallback: the worker's interpreter and model directory
# come from model.mlx_python / model.mlx_model_path (REGULUS_MLX_PYTHON / REGULUS_MLX_MODEL_PATH), every check runs
# before the server listens, and a failed check stops the server with what to fix. Nothing else is ever loaded in
# its place: no in-process Qwen3-0.6B, no adapter, no remote server. A request may name the model; any other name
# is refused rather than answered by this one.
MODEL_MLX = "qwen3-1.7b"
MLX_MODEL_ID = "Qwen/Qwen3-1.7B"
MLX_LABEL = "Qwen3-1.7B (MLX 4-bit)"
# config.json values that identify Qwen3-1.7B (Qwen3-0.6B is 1024 wide; Qwen3-4B is 2560 wide with 36 layers),
# and the quantization the application is validated with
MLX_EXPECTED_CONFIG = {"model_type": "qwen3", "hidden_size": 2048, "num_hidden_layers": 28, "intermediate_size": 6144}
MLX_EXPECTED_BITS = 4


def check_model(model: str | None) -> None:
    """A request may name the model it expects; anything but this server's one model is refused."""
    if model not in (None, "", MODEL_MLX):
        raise ValueError(f"unknown model {model!r}: this server answers with {MLX_LABEL} ({MODEL_MLX!r}) only")


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()

# one inference at a time: the model is not safe to share across threads and
# this machine cannot run two anyway
_LOCK = threading.Lock()
_CONVERSATION_PATH = re.compile(r"/api/conversations/([A-Za-z0-9-]{1,64})")


class Engine:
    """Holds the loaded model and database, and answers one question at a time."""

    def __init__(self, settings, offline: bool) -> None:
        from regulus.retrieval import Database

        self.settings = settings
        self._init_inference(offline)
        self.db = Database.from_env()
        self.db.connect()
        status = self.db.status()
        print(f"Database {status['database']} read-only={status['default_transaction_read_only']}", flush=True)
        self.snapshot = self.db.query("SELECT max(snapshot_date)::text AS d FROM cfr_records WHERE removed_on IS NULL")[0]["d"]
        self._adapter_records: dict[str, dict] = {}
        # The accuracy evaluator's optional existence check reuses the Stage 13
        # identifier index (read-only, one indexed lookup per unaccounted-for
        # section). Default on; --no-accuracy turns the whole feature off.
        self.accuracy = True
        # "semantic" reuses the pinned bge-small encoder already in this
        # repository to choose WHICH evidence passage each claim is compared
        # against; it never decides correctness. "lexical" needs no model at all.
        self.accuracy_alignment = "semantic"
        self._identifier_index = None
        self._aligner = None

    def _init_inference(self, offline: bool) -> None:
        """Start the application's one model, Qwen3-1.7B 4-bit in the MLX worker, or stop with what to fix.

        Checked in order, each before anything is loaded that a failure would waste: no remote backend and no
        adapter configured; the worker's interpreter and model directory exist; the directory's config.json is
        Qwen3-1.7B quantized to 4 bits; its tokenizer.json is byte-identical to the tokenizer loaded here
        (prompts are tokenized in this process); the memory preflight; the worker starts. There is no fallback:
        any failure raises SystemExit and the server does not start."""
        from regulus.model import load_tokenizer
        from regulus.rag.mlx_generator import MlxGenerator, memory_preflight
        from regulus.system_identity import configured_generation_config

        m = self.settings.model

        def refuse(problem: str):
            raise SystemExit(f"{MLX_LABEL} cannot start: {problem}. The application answers with this model only "
                             f"and never substitutes another.")

        if m.backend == "openai_compatible":
            refuse("model.backend is 'openai_compatible' (REGULUS_MODEL_BACKEND), which would answer with the remote "
                   "server's model; unset it")
        if m.adapter is not None:
            refuse("model.adapter is set (configs/model.yaml or REGULUS_ADAPTER), but adapters are Qwen3-0.6B LoRA "
                   "weights; unset it (REGULUS_ADAPTER=none)")
        if m.mlx_python is None or m.mlx_model_path is None:
            refuse("the MLX worker is not configured; set REGULUS_MLX_PYTHON (a Python with mlx-lm installed) and "
                   "REGULUS_MLX_MODEL_PATH (the Qwen3-1.7B-MLX-4bit snapshot directory)")
        path = Path(m.mlx_model_path)
        if not Path(m.mlx_python).is_file():
            refuse(f"REGULUS_MLX_PYTHON does not name a file ({m.mlx_python})")
        if not (path / "config.json").is_file() or not (path / "tokenizer.json").is_file():
            refuse("REGULUS_MLX_MODEL_PATH has no config.json and tokenizer.json")
        cfg = json.loads((path / "config.json").read_text(encoding="utf-8"))
        wrong = {k: cfg.get(k) for k, v in MLX_EXPECTED_CONFIG.items() if cfg.get(k) != v}
        bits = (cfg.get("quantization") or {}).get("bits")
        if wrong or bits != MLX_EXPECTED_BITS:
            refuse(f"REGULUS_MLX_MODEL_PATH is not Qwen3-1.7B quantized to {MLX_EXPECTED_BITS} bits "
                   f"(config.json: {wrong or ''}{'' if bits == MLX_EXPECTED_BITS else f' quantization bits {bits}'})")
        self.tokenizer = load_tokenizer(m, local_files_only=offline)
        mine = self._tokenizer_file()
        if mine is None or _sha256(mine) != _sha256(path / "tokenizer.json"):
            refuse(f"the tokenizer loaded from {m.id} (REGULUS_MODEL_ID / REGULUS_MODEL_CACHE_DIR) is not "
                   f"byte-identical to the MLX model's tokenizer.json")
        self._tokenizer_sha256 = _sha256(mine)
        # an HF cache snapshot directory is named by its commit; an explicit REGULUS_MLX_REVISION wins
        revision = m.mlx_revision or (path.name if path.parent.name == "snapshots" else None)
        try:
            memory_preflight(m.mlx_min_available_mb)
            print(f"Starting {MLX_LABEL} in the MLX worker ...", flush=True)
            t0 = time.perf_counter()
            self._mlx = MlxGenerator(self.tokenizer, configured_generation_config(self.settings), model_id=MLX_MODEL_ID,
                                     model_path=path, python=m.mlx_python, revision=revision)
        except Exception as exc:  # noqa: BLE001 - every start-up failure stops the server, explained
            refuse(f"{type(exc).__name__}: {exc}")
        d = self._mlx.describe()
        print(f"Answering model: {d['model_id']} {d['dtype']} revision {d['model_revision'] or 'not recorded'}, "
              f"MLX worker {d.get('runtime_versions')}, tokenizer.json sha256 {self._tokenizer_sha256[:12]}, "
              f"ready in {time.perf_counter() - t0:.1f}s", flush=True)

    def adapter_record(self, adapter_id: str) -> dict | None:
        """What a measurement record keeps about the adapter a request used: its name and training metadata,
        and the SHA-256 of its weights file, computed once. None for the base model and for remote inference
        (no adapter is applied on this host). Never the local path."""
        if getattr(self, "remote", None) is not None:
            return None
        cache = self.__dict__.setdefault("_adapter_records", {})
        if adapter_id in cache:
            return cache[adapter_id]
        directory = (ADAPTER_ROOT / adapter_id / "adapter") if adapter_id else self.settings.model.adapter
        if not directory:
            cache[adapter_id] = None
            return None
        try:
            from regulus.system_identity import adapter_identity

            ident = adapter_identity(Path(directory))
            weights = sorted(Path(directory).glob("adapter_model.*"))
            digest = None
            if weights:
                import hashlib

                h = hashlib.sha256()
                with weights[0].open("rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                digest = h.hexdigest()
            record = {"id": adapter_id, **{k: ident.get(k) for k in ("adapter_name", "base_model_name_or_path", "peft_type",
                                                                       "r", "lora_alpha", "stage", "dataset_hash")},
                      "weights_file": weights[0].name if weights else None, "weights_sha256": digest}
        except Exception as exc:  # noqa: BLE001
            record = {"id": adapter_id, "unavailable": type(exc).__name__}
        cache[adapter_id] = record
        return record

    def aligner(self):
        """The claim-to-evidence aligner, built once per process.

        The embedder is ~33M parameters and about 300 MB resident, loaded on
        first use and then shared by every question. It is a separate model from
        the answering model and is never asked to generate anything.
        """
        if self._aligner is None:
            from regulus.accuracy.alignment import LexicalAligner, SemanticAligner

            if self.accuracy_alignment != "semantic":
                self._aligner = LexicalAligner()
            else:
                try:
                    from regulus.retrieval.semantic import TransformersEmbedder, load_manifest

                    t0 = time.perf_counter()
                    embedder = TransformersEmbedder(load_manifest().embedding,
                                                    cache_dir=self.settings.model.cache_dir, local_files_only=True)
                    self._aligner = SemanticAligner(embedder)
                    print(f"Accuracy aligner: {embedder.describe()['model_id']} in "
                          f"{time.perf_counter() - t0:.1f}s", flush=True)
                except Exception as exc:  # no index, no weights, anything: fall back, never fail answering
                    print(f"Accuracy aligner: semantic alignment unavailable ({type(exc).__name__}: {exc}); "
                          f"using lexical alignment", flush=True)
                    self._aligner = LexicalAligner()
        return self._aligner

    def identifier_index(self):
        if self._identifier_index is None:
            from regulus.grounding import DatabaseIdentifierIndex

            self._identifier_index = DatabaseIdentifierIndex(self.db)
        return self._identifier_index

    # -- adapters ---------------------------------------------------------

    def available_adapters(self) -> list[dict]:
        """Adapters are Qwen3-0.6B LoRA weights and never apply to the application's model."""
        return [{"id": "", "label": "No adapter"}]

    # -- the one model --------------------------------------------------------

    def active_model(self) -> str:
        return MODEL_MLX

    def available_models(self) -> list[dict]:
        """The one model this server answers with (/api/config keeps the list shape for its readers)."""
        return [{"id": MODEL_MLX, "label": MLX_LABEL, "available": True}]

    def _tokenizer_file(self) -> Path | None:
        from regulus.system_identity import cached_revision

        m = self.settings.model
        try:
            revision, _ = cached_revision(m.id, Path(m.cache_dir))
        except Exception:  # noqa: BLE001
            return None
        path = Path(m.cache_dir) / f"models--{m.id.replace('/', '--')}" / "snapshots" / str(revision) / "tokenizer.json"
        return path if revision and path.is_file() else None

    def model_identity(self) -> dict:
        """What answers, as the start-up log, /api/config, every response and every measurement record name it.
        Never the local paths."""
        d = self._mlx.describe()
        return {"backend": "mlx", "model_id": d.get("model_id"), "model_revision": d.get("model_revision"),
                "device": d.get("device"), "dtype": d.get("dtype"), "quantization": d.get("quantization"),
                "runtime_versions": d.get("runtime_versions"), "adapter": None,
                "decoding": d.get("generation"),   # what the worker does (greedy), not the configured sampling
                "tokenizer": {"loaded_from": self.settings.model.id,
                              "tokenizer_json_sha256": getattr(self, "_tokenizer_sha256", None),
                              "identical_to_mlx_model": True}}

    # -- answering --------------------------------------------------------

    def ask(self, question: str, *, turn=None, **kwargs) -> dict:
        """Answer one question (see _ask). `turn` (regulus.traceability.ui_session.Turn), when the server
        measures, is handed the finished answer and its assessment, or told that the request failed or was
        cancelled; it never changes the result, and it writes nothing itself until the Handler knows whether
        the answer was delivered."""
        try:
            return self._ask(question, turn=turn, **kwargs)
        except Exception as exc:
            if turn is not None:
                turn.failed(exc, cancelled=isinstance(exc, ClientDisconnected), error=safe_error(exc))
            raise

    def _ask(self, question: str, *, adapter: str = "", grounding: bool = False,
             top_k: int = 8, max_new_tokens: int | None = None, on_event=None,
             accuracy: bool | None = None, turn=None, model: str | None = None) -> dict:
        """Answer one question. `on_event` (streaming) is passed to the pipeline
        unchanged; the returned dict is the same with or without it."""
        from dataclasses import replace
        from regulus.rag import RagPipeline
        from regulus.retrieval import LexicalRetriever
        from regulus.system_identity import configured_generation_config, configured_rag_config

        t_setup = time.perf_counter()
        check_model(model)
        if adapter:
            raise ValueError(f"adapters are Qwen3-0.6B LoRA weights and do not apply to {MLX_LABEL}")
        adapter_info: dict = {}
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
        self._mlx.gen = gen   # the configured decoding settings; the worker decodes greedily, thinking off
        pipeline = RagPipeline(
            retriever,
            self._mlx,
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
            "model": {"id": MODEL_MLX, "label": MLX_LABEL,
                      **{k: v for k, v in self.model_identity().items() if k in ("backend", "model_id", "model_revision", "dtype")}},
            "snapshot_date": self.snapshot,
            # the exact evidence placed in the prompt, with its fingerprint (regulus.traceability)
            "evidence_snapshot": out.evidence_snapshot.to_dict() if out.evidence_snapshot is not None else None,
        }
        # latency baseline: server-side stages around the pipeline
        result["server_timings_ms"] = {"engine_setup_ms": setup_ms, "pipeline_answer_ms": answer_ms,
                                       "response_build_ms": round((time.perf_counter() - t_build) * 1000, 2)}
        # ---- answer accuracy: strictly after the final answer, strictly read-only.
        # `out` is not consulted again below and `result["answer"]` is already set:
        # whatever happens here, the answer has been delivered. evaluate_safely
        # never raises.
        if self.accuracy if accuracy is None else accuracy:
            t_acc = time.perf_counter()
            lookups: list = []
            result["accuracy"] = self.accuracy_payload(out, lookups=lookups)
            result["server_timings_ms"]["accuracy_ms"] = round((time.perf_counter() - t_acc) * 1000, 2)
        else:
            lookups = None
        if turn is not None:   # staged only: the record is written once delivery is known (Handler)
            acc = result.get("accuracy")
            turn.answered(out, evaluation={k: v for k, v in acc.items() if k != "question_review"} if acc else None,
                          review=acc.get("question_review") if acc else None,
                          live=self.live_context(out, acc, lookups, adapter))
        return result

    def live_context(self, out, accuracy, lookups, adapter: str) -> dict:
        """What the live answer path knew that a measurement record should keep. Values the path did not
        produce are recorded as None, never guessed. Never raises: the answer is already final here."""
        try:
            return self._live_context(out, accuracy, lookups, adapter)
        except Exception as exc:  # noqa: BLE001
            return {"unavailable": type(exc).__name__}

    def _live_context(self, out, accuracy, lookups, adapter: str) -> dict:
        checked = (accuracy or {}).get("checked") or {}
        embedder = getattr(getattr(self, "_aligner", None), "_embedder", None) if accuracy else None
        try:
            embedder_identity = embedder.describe() if embedder is not None and hasattr(embedder, "describe") else None
        except Exception as exc:  # noqa: BLE001
            embedder_identity = {"unavailable": type(exc).__name__}
        return {
            "aligner_used": checked.get("aligner"),          # actual method, after any semantic->lexical fallback
            "embedder": embedder_identity,
            # every identifier-index lookup the live evaluator made, with its answer (None: accuracy was off)
            "identifier_lookups": lookups,
            "grounding": out.metadata.get("grounding"),       # the grounding gate's decision; None when off
            "adapter": self.adapter_record(adapter),
            "inference_backend": "mlx",
        }

    def accuracy_payload(self, out, *, lookups: list | None = None) -> dict:
        """The assessment as the page receives it: the evaluator's own dict, plus
        the per-question status read from it (regulus.accuracy.review). Kept inside
        the one `accuracy` object, so the response with the feature on still
        differs from the response with it off by that key alone."""
        from regulus.accuracy.review import question_review

        payload = self.assess(out, lookups=lookups).to_dict()
        payload["question_review"] = question_review(payload, question=out.question)
        return payload

    def assess(self, out, *, lookups: list | None = None):
        """The live accuracy assessment of a finished RagAnswer.

        Every argument comes off the RagAnswer; nothing is retrieved, generated
        or recomputed, and no model is called.
        """
        from regulus.accuracy import evaluate_safely

        analysis = out.metadata.get("question_analysis") or {}
        return evaluate_safely(
            out.question,
            out.answer,
            package=out.package,
            evidence=out.evidence_snapshot,   # the exact evidence the prompt carried (None: not captured)
            citations=out.citations,
            validation=out.validation,
            coverage=out.coverage,
            model_called=out.model_called,
            fallback_type=out.metadata.get("fallback_type"),
            scope_status=analysis.get("scope_status"),
            answerability=out.metadata.get("answerability"),
            repair=out.metadata.get("validation"),   # what post-processing removed, for completeness
            identifier_index=(self.identifier_index() if lookups is None
                              else _RecordingIndex(self.identifier_index(), lookups)),
            aligner=self.aligner(),
        )


class Handler(BaseHTTPRequestHandler):
    engine: Engine = None  # set on the class before serving
    # Chat history (regulus.conversations): None when the store could not be opened, in which case
    # answering works exactly as before and only the history endpoints report it unavailable.
    store: ConversationStore | None = None
    # Measurement records (regulus.traceability.ui_session): None when --no-measure or when the session could
    # not be opened, in which case answering, streaming and chat history work exactly as before.
    measure: UISession | None = None

    def _turn(self, question: str, endpoint: str, kwargs: dict, conversation: tuple[str, str] | None = None):
        """A measurement turn for this request, or None. Never raises."""
        if self.measure is None:
            return None
        try:
            return self.measure.turn(question, endpoint=endpoint, request=kwargs,
                                     conversation_id=conversation[0] if conversation else None,
                                     turn_id=conversation[1] if conversation else None)
        except Exception as exc:  # noqa: BLE001 - measurement never touches the answer
            print(f"  measurement: turn not opened ({type(exc).__name__})", flush=True)
            return None

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
            identity = self.engine.model_identity()
            self._json(200, {
                "adapters": self.engine.available_adapters(),
                "models": self.engine.available_models(),
                "active_model": self.engine.active_model(),
                "model_id": identity["model_id"],
                "model_revision": identity["model_revision"],
                "device": identity["device"],
                "dtype": identity["dtype"],
                "inference_backend": "mlx",
                # ids and counters only: whether records are being written, and the last failure category
                "measurement": self.measure.status() if self.measure is not None else {"enabled": False},
                "snapshot_date": self.engine.snapshot,
                "defaults": {"top_k": 8, "max_new_tokens": self.engine.settings.answer_length.max_new_tokens},
                "accuracy": {"enabled": self.engine.accuracy, "rubric_id": ACCURACY_RUBRIC_ID,
                             "alignment": self.engine.accuracy_alignment,
                             "note": ("an evidence-based assessment of this one answer; not the 300-question "
                                      "acceptance-test score")},
                "conversations": {
                    "enabled": self.store is not None,
                    "context": ("each question is answered on its own: earlier messages are kept as history "
                                "but are never sent to the model or used as evidence"),
                },
                "answer_length": {
                    "policy": self.engine.settings.answer_length.policy,
                    "ceiling": self.engine.settings.answer_length.max_new_tokens,
                    "note": ("the ceiling is a safety limit against a model that never stops, not a target "
                             "length; the pipeline sets each question's allowance from its evidence"),
                },
            })
            return
        if path == "/api/conversations":
            if self._history_available():
                self._json(200, {"conversations": self.store.list_conversations()})
            return
        match = _CONVERSATION_PATH.fullmatch(path)
        if match:
            if self._history_available():
                try:
                    conv = self.store.get_conversation(match.group(1))
                    # records stored before the delivery boundary existed may still carry draft text
                    conv["messages"] = [{**m, "result": browser_safe(m.get("result"))} for m in conv.get("messages") or ()]
                    self._json(200, {"conversation": conv})
                except ConversationNotFound:
                    self._json(404, {"error": "conversation not found"})
                except InvalidInput as exc:
                    self._json(400, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})

    # -- conversations ------------------------------------------------------

    def _history_available(self) -> bool:
        if self.store is None:
            self._json(503, {"error": "conversation history is unavailable on this server"})
            return False
        return True

    def _record_turn(self, conversation: tuple[str, str], status: str, content: str, result: dict | None) -> dict:
        """Record how a conversation turn ended. Never raises: a failed save is reported to the page
        (saved: false) rather than hiding the answer that was delivered."""
        cid, tid = conversation
        t0 = time.perf_counter()
        try:
            self.store.record_answer(cid, tid, status, content, result)
            saved = True
        except Exception as exc:  # the answer stands even if history could not record it
            traceback.print_exc()
            print(f"  chat: turn {tid[:8]} NOT recorded ({type(exc).__name__})", flush=True)
            saved = False
        print(f"  chat: conversation {cid[:8]} turn {tid[:8]} {status} recorded={saved} "
              f"in {round((time.perf_counter() - t0) * 1000, 2)} ms", flush=True)
        return {"id": cid, "turn_id": tid, "saved": saved}

    @staticmethod
    def _ask_kwargs(body: dict) -> dict:
        out = {
            "adapter": str(body.get("adapter") or ""),
            "grounding": bool(body.get("grounding")),
            "top_k": max(1, min(int(body.get("top_k") or 8), 20)),
            "max_new_tokens": (max(64, min(int(body["max_new_tokens"]), 4096)) if body.get("max_new_tokens") else None),
        }
        # Passed on only when the request actually asks, so that a request that
        # says nothing about accuracy calls ask() exactly as it was called before
        # the feature existed. The regression harness sends false for Run A.
        if "accuracy" in body:
            out["accuracy"] = bool(body["accuracy"])
        if "model" in body:   # a client may name the model it expects; any other than the one served is refused
            out["model"] = str(body.get("model") or "")
            check_model(out["model"])
        return out

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/ask/stream":
            self._ask_stream()
            return
        if path == "/api/conversations":
            if self._history_available():
                self._json(201, {"conversation": self.store.create_conversation()})
            return
        if path != "/api/ask":
            self._json(404, {"error": "not found"})
            return
        t_request = time.perf_counter()
        turn = None
        answering = False
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            question = (body.get("question") or "").strip()
            if not question:
                self._json(400, {"error": "question must not be empty"})
                return
            kwargs = self._ask_kwargs(body)
            turn = self._turn(question, "/api/ask", kwargs)
            t0 = time.perf_counter()
            parse_ms = round((t0 - t_request) * 1000, 2)
            answering = True
            with _LOCK:
                lock_wait_ms = round((time.perf_counter() - t0) * 1000, 2)
                result = browser_safe(self.engine.ask(question, **kwargs, **({"turn": turn} if turn is not None else {})))
            result["wall_seconds"] = round(time.perf_counter() - t0, 1)
            result["server_timings_ms"].update({"request_parse_ms": parse_ms, "lock_wait_ms": lock_wait_ms})
            t_send = time.perf_counter()
            self._json(200, result)
            if turn is not None:
                turn.finish(DELIVERED)
            # serialisation + socket write cannot be reported inside the body it produces: logged instead
            print(f"  timing: serialize+send {round((time.perf_counter() - t_send) * 1000, 2)} ms, "
                  f"request total {round((time.perf_counter() - t_request) * 1000, 2)} ms", flush=True)
        except Exception as exc:  # never leak a path or a stack trace to the page
            traceback.print_exc()
            if turn is not None:
                turn.finish(NOT_DELIVERED)      # a no-op when ask() already recorded the failure
            self._json(500, {"error": page_error(exc, draft_possible=answering)})

    # -- streaming ----------------------------------------------------------

    def _ask_stream(self) -> None:
        """POST /api/ask/stream: the same answer as /api/ask, as newline-delimited JSON events.

        One event per line, flushed as it happens:
            {"type": "start"}
            {"type": "context", "sources": [...], "no_context": bool}   sources selected for the model
            {"type": "generation_started", "max_new_tokens": n}
            {"type": "progress", "elapsed_ms": n}                       the model is generating; no text, at
                                                                        most one per PROGRESS_INTERVAL_S
            {"type": "generation_finished", "generated_tokens": n, "finished": bool}
            {"type": "final", "result": {...}}                          the validated answer: exactly what
                                                                        /api/ask returns, plus "stream" stats
            {"type": "error", "error": "..."}                           instead of "final" when it fails
        The stream always ends with exactly one "final" or "error" event. No draft text is
        sent: the model's text reaches only the pipeline, whose validation and repair decide
        what is delivered (STREAM_EVENTS, browser_safe). A client that disconnects is noticed
        at the next progress write, which stops the generation.
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
        # A conversation turn: the question is recorded before anything is generated, and a turn that
        # was already answered is replayed rather than generated - and stored - a second time. A
        # request without conversation fields takes exactly the path it always did.
        conversation = None
        if body.get("conversation_id") is not None or body.get("turn_id") is not None:
            if not self._history_available():
                return
            cid, tid = body.get("conversation_id"), body.get("turn_id")
            try:
                self.store.add_user_message(cid, tid, question)
                stored = self.store.answer_for(cid, tid)
            except ConversationNotFound:
                self._json(404, {"error": "conversation not found"})
                return
            except InvalidInput as exc:
                self._json(400, {"error": str(exc)})
                return
            conversation = (cid, tid)

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()  # HTTP/1.0 response without Content-Length: the body ends when the connection closes

        stats = {"progress_events": 0, "first_progress_ms": None}
        deltas = {"n": 0, "last_progress": None}      # server-side only: never sent to the page
        began = {"generation": False}
        turn = None

        def send(event: dict) -> None:
            try:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as exc:
                raise ClientDisconnected() from exc

        def on_event(kind: str, data: dict) -> None:
            if kind == "delta":                       # draft text: counted, never forwarded
                deltas["n"] += 1
                now = time.perf_counter()
                if deltas["last_progress"] is not None and now - deltas["last_progress"] < PROGRESS_INTERVAL_S:
                    return
                deltas["last_progress"] = now
                elapsed_ms = round((now - t_request) * 1000, 2)
                stats["progress_events"] += 1
                if stats["first_progress_ms"] is None:
                    stats["first_progress_ms"] = elapsed_ms
                send({"type": "progress", "elapsed_ms": elapsed_ms})
                return
            if kind == "generation_started":
                began["generation"] = True
            if kind in STREAM_EVENTS:                 # any other pipeline event is not the page's to see
                send({"type": kind, **data})

        try:
            send({"type": "start"})
            if conversation is not None and stored is not None and stored["status"] == OK:
                replay = browser_safe(dict(stored["result"] or {"answer": stored["content"]}))
                replay["conversation"] = {"id": conversation[0], "turn_id": conversation[1], "saved": True,
                                          "replayed": True}
                send({"type": "final", "result": replay})
                print(f"  chat: turn {conversation[1][:8]} already answered; replayed the stored answer", flush=True)
                return
            turn = self._turn(question, "/api/ask/stream", kwargs, conversation)   # never for a replayed turn
            t0 = time.perf_counter()
            with _LOCK:
                lock_wait_ms = round((time.perf_counter() - t0) * 1000, 2)
                result = browser_safe(self.engine.ask(question, on_event=on_event, **kwargs,
                                                      **({"turn": turn} if turn is not None else {})))
            result["wall_seconds"] = round(time.perf_counter() - t0, 1)
            result.setdefault("server_timings_ms", {}).update({"lock_wait_ms": lock_wait_ms})
            result["stream"] = {**stats, "final_ms": round((time.perf_counter() - t_request) * 1000, 2)}
            if conversation is not None:
                result["conversation"] = self._record_turn(conversation, OK, result.get("answer") or "", result)
            send({"type": "final", "result": result})
            if turn is not None:
                turn.finish(DELIVERED)
            print(f"  stream: {deltas['n']} deltas, {stats['progress_events']} progress events, first at "
                  f"{stats['first_progress_ms']} ms, final at {result['stream']['final_ms']} ms", flush=True)
        except ClientDisconnected:
            print(f"  stream: client disconnected after {deltas['n']} deltas; generation stopped", flush=True)
            if turn is not None:
                turn.finish(NOT_DELIVERED)
            if conversation is not None:
                self._record_turn(conversation, CANCELLED, "Stopped before the answer was complete.", None)
        except Exception as exc:  # never leak a path, a stack trace or draft text to the page
            traceback.print_exc()
            message = page_error(exc, draft_possible=began["generation"])
            if turn is not None:
                turn.finish(NOT_DELIVERED)
            if conversation is not None:
                self._record_turn(conversation, ERROR, "Request failed: " + message, None)
            try:
                send({"type": "error", "error": message})
            except ClientDisconnected:
                pass


class _RecordingIndex:
    """The live identifier index, unchanged, recording every lookup and its answer for the measurement record."""

    def __init__(self, inner, lookups: list) -> None:
        self._inner, self._lookups = inner, lookups

    def _call(self, kind: str, ident, fn):
        try:
            exists, live = fn(ident)
        except Exception as exc:
            self._lookups.append({"kind": kind, "id": str(ident), "error": type(exc).__name__})
            raise
        self._lookups.append({"kind": kind, "id": str(ident), "exists": bool(exists), "live": bool(live)})
        return exists, live

    def section_status(self, section):
        return self._call("section", section, self._inner.section_status)

    def part_status(self, part):
        return self._call("part", part, self._inner.part_status)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def safe_error(exc: BaseException) -> str:
    """Error text for the page, the chat history and measurement records: sanitize_error (paths removed),
    then the configured inference endpoint and API key removed wherever they appear."""
    import os

    text = sanitize_error(exc)
    endpoint = getattr(getattr(Handler.engine, "settings", None), "model", None)
    for secret in ((getattr(endpoint, "endpoint", None) or ""), os.environ.get("REGULUS_MODEL_API_KEY") or ""):
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


# ---- the delivery boundary: the page receives the finished answer and nothing of a draft.
# The model's text streams only inside the server (to the pipeline's listener, which is how a client
# disconnect stops generation); a page sees content-free progress events, then the validated result.
# Every route that sends or stores an answer goes through browser_safe().
STREAM_EVENTS = frozenset({"start", "context", "generation_started", "generation_finished", "final", "error"})
PROGRESS_INTERVAL_S = 0.5   # at most one progress event per interval: their count does not track the draft's length
_DRAFT_KEYS = ("raw_model_output", "repair_input", "repair_output")
_PROBLEM_KEYS = ("code", "severity", "requirement_id", "citation")


def browser_safe(result):
    """A copy of an answer result without draft text. The INITIAL validation report describes the draft,
    so its problems keep their codes but not the sentences and details that quote it; a re-pointed
    citation keeps its numbers but not its words; the raw draft and repair texts are dropped. The final
    report describes the delivered answer and is kept. `result` itself is not changed."""
    if not isinstance(result, dict):
        return result
    out = {k: v for k, v in result.items() if k not in _DRAFT_KEYS}
    validation = out.get("validation")
    if isinstance(validation, dict) and isinstance(validation.get("initial"), dict):
        initial = dict(validation["initial"])
        initial["problems"] = [{k: p.get(k) for k in _PROBLEM_KEYS}
                               for p in initial.get("problems") or () if isinstance(p, dict)]
        out["validation"] = {**validation, "initial": initial}
    generation = out.get("generation")
    if isinstance(generation, dict) and generation.get("citations_repointed"):
        out["generation"] = {**generation, "citations_repointed": [
            {k: c.get(k) for k in ("from", "to")} for c in generation["citations_repointed"] if isinstance(c, dict)]}
    return out


def page_error(exc: BaseException, *, draft_possible: bool) -> str:
    """Error text for the page and the chat history. Once the model may have produced text, an
    exception's message could quote it, so only the exception's type is given; the full message stays
    in the server log (and the local measurement record). A remote InferenceError's message is a
    category by construction (regulus.rag.remote_generator), never model text, so it is kept."""
    from regulus.rag.remote_generator import InferenceError

    if draft_possible and not isinstance(exc, InferenceError):
        return f"{type(exc).__name__} while answering (details are in the server log)"
    return safe_error(exc)


_LOOPBACK = {"localhost"}


def is_loopback(host: str) -> bool:
    if host in _LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_bind(host: str, allow_remote_clients: bool) -> None:
    """Fail closed: this server has no authentication, and its chat-history endpoints return every stored
    conversation. It binds beyond loopback only when the operator says it is behind a private network and an
    authenticated HTTPS reverse proxy (--allow-remote-clients)."""
    if is_loopback(host):
        return
    if not allow_remote_clients:
        raise SystemExit(f"refusing to listen on a non-loopback address: this server has no authentication and "
                         f"exposes chat history. Put it behind a private network and an authenticated HTTPS "
                         f"reverse proxy, then pass --allow-remote-clients.")
    print("WARNING: listening beyond loopback with NO built-in authentication: only safe behind a private network "
          "and an authenticated HTTPS reverse proxy", flush=True)


def serve_until_stopped(server, cleanup, *, signals=(signal.SIGTERM,)) -> None:
    """Serve until Ctrl-C or SIGTERM, then run `cleanup` (close the measurement session, the database).

    The SIGTERM handler does no work itself: it asks serve_forever to return, from another thread (calling
    shutdown() from the serving thread would deadlock), and the cleanup runs in the normal `finally`. Requests
    still in flight when the process exits are not recorded: they were never delivered. SIGKILL, host failure
    and power loss run no cleanup at all; the session is then left "open" (see ui_session)."""
    def stop(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    previous = {}
    for sig in signals:
        try:
            previous[sig] = signal.signal(sig, stop)
        except (ValueError, OSError):        # not the main thread, or unsupported on this platform
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping ...")
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        cleanup()


def measurement_run(settings, engine) -> dict:
    """What every measurement record of this server session carries about the session (no secrets: the
    model id and revision, decoding, a hash of the pipeline configuration, the code revision, the rubric).
    Per-request choices (adapter, top_k, token ceiling, grounding) are in each record's origin.request."""
    import hashlib
    from dataclasses import replace

    from regulus.accuracy.rubric import RUBRIC_VERSION
    from regulus.rag.generation import GROUNDED_SYSTEM_PROMPT
    from regulus.system_identity import (configured_generation_config, configured_rag_config, decoding_config,
                                         pipeline_config)
    from regulus.traceability.measurement import sha256_json

    config = configured_rag_config(settings)
    if getattr(engine, "answer_shape", None):
        config = replace(config, answer_shape=engine.answer_shape)
    return {
        "source": "ui",
        "model": engine.model_identity(),
        # the regulatory database as this server saw it at start (max snapshot_date of live eCFR rows)
        "database": {"snapshot_date": getattr(engine, "snapshot", None), "observed": "at server start"},
        "generation_config": json.loads(json.dumps(decoding_config(configured_generation_config(settings)), default=str)),
        "system_prompt_sha256": hashlib.sha256(GROUNDED_SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "pipeline_config_sha256": sha256_json(json.loads(json.dumps(pipeline_config(config), default=str))),
        "code_revision": code_revision(PROJECT_ROOT),
        "evaluator": {"rubric_id": ACCURACY_RUBRIC_ID, "rubric_version": RUBRIC_VERSION, "evaluator_version": None,
                      "accuracy_enabled": bool(engine.accuracy), "aligner_configured": engine.accuracy_alignment,
                      "identifier_index": "database"},
    }


class ClientDisconnected(Exception):
    """The streaming client went away; raised out of the generation to stop it."""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1", help="loopback by default; this UI has no authentication")
    p.add_argument("--allow-remote-clients", action="store_true",
                   help="allow a non-loopback --host. Only behind a private network AND an authenticated HTTPS "
                        "reverse proxy: this server has no authentication and serves chat history")
    p.add_argument("--offline", action="store_true", help="fail instead of downloading the tokenizer")
    p.add_argument("--no-accuracy", action="store_true",
                   help="do not assess answer accuracy; the answer, citations and evidence are unchanged either way")
    p.add_argument("--accuracy-alignment", choices=("semantic", "lexical"), default="semantic",
                   help="how the accuracy evaluator picks which evidence passage a claim is compared against "
                        "(semantic reuses the pinned bge-small encoder; it never decides correctness)")
    p.add_argument("--no-measure", action="store_true",
                   help="do not write measurement records (default: one per answered question, under "
                        "data/ui_measurements/ or $REGULUS_UI_MEASUREMENTS; local files, git-ignored)")
    p.add_argument("--measure-dir", default=None, help="where measurement sessions are written (default as above)")
    p.add_argument("--answer-shape", choices=("off", "adaptive", "structured"), default=None,
                   help="override RagConfig.answer_shape; 'structured' = answer-quality Stage 3 (default: as configured)")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    check_bind(args.host, args.allow_remote_clients)
    settings = load_settings()
    Handler.engine = Engine(settings, offline=args.offline)
    try:
        Handler.store = ConversationStore()
        print(f"Conversation history: {Handler.store.path}", flush=True)
    except Exception as exc:  # answering must not depend on history
        print(f"Conversation history unavailable ({type(exc).__name__}: {exc}); answering is unaffected", flush=True)
    Handler.engine.answer_shape = args.answer_shape
    Handler.engine.accuracy = not args.no_accuracy
    Handler.engine.accuracy_alignment = args.accuracy_alignment
    if args.no_measure:
        print("Measurement records: OFF (--no-measure)", flush=True)
    else:
        try:
            Handler.measure = UISession(Path(args.measure_dir) if args.measure_dir else default_root(PROJECT_ROOT),
                                        measurement_run(settings, Handler.engine))
            print(f"Measurement records: ON -> {Handler.measure.dir} (local only; --no-measure to turn off)", flush=True)
        except Exception as exc:  # answering must not depend on measurement
            print(f"Measurement records unavailable ({type(exc).__name__}: {exc}); answering is unaffected", flush=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print()
    print(f"  Regulus test UI:  http://{args.host}:{args.port}")
    print("  Ctrl+C to stop. Answers take 30-90 s on this CPU.")
    print()
    def cleanup():
        if Handler.measure is not None:
            Handler.measure.close()
        Handler.engine.db.close()

    serve_until_stopped(server, cleanup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
