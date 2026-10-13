"""Read-only API and page server for the model evaluation dashboard.

    python scripts/serve_dashboard.py
    python scripts/serve_dashboard.py --port 8050 --host 127.0.0.1

Then open http://127.0.0.1:8050 in a browser.

This process **never loads a model and never connects to the database**, so
it can run beside the answering UI, or beside a training job, without
competing for memory. It reads evaluation and training artifacts from disk
and serves them as the canonical dashboard schemas; the browser never parses
an artifact.

The only file anything here writes is `artifacts/dashboard/registry.json`,
which holds the names and pins a person sets plus a cache of the last scan.
Evaluation artifacts, benchmarks, adapters, weights and the regulatory
database are all untouched.

It is a separate application from `scripts/serve_ui.py`: different port,
different page, no shared state.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from regulus.dashboard import metrics as M  # noqa: E402
from regulus.dashboard.compare import compare  # noqa: E402
from regulus.dashboard.health import current_health, current_history, experiment_analysis  # noqa: E402
from regulus.dashboard.observatory import (  # noqa: E402
    MAX_COMPARE,
    compare_runs,
    evaluation_history,
    iter_evaluation_pairs,
    question_detail,
    question_list,
)
from regulus.dashboard.acceptance_view import payload as acceptance_payload  # noqa: E402
from regulus.dashboard.benchmark_review import review_status  # noqa: E402
from regulus.dashboard.registry import DEFAULT_ROOTS, Registry  # noqa: E402
from regulus.dashboard.schemas import KIND_EVALUATION, KIND_TRAINING  # noqa: E402

WEB_DIR = ROOT / "web"
PAGE = "dashboard.html"

_LOCK = threading.Lock()


class State:
    """The registry, rebuilt on demand. Guarded by a lock so a refresh never
    races a request that is halfway through reading it."""

    def __init__(self, root: Path, store: Path | None = None) -> None:
        # `store` relocates the registry's one writable file (names, pins,
        # thresholds); tests pass a temporary path so they never rewrite the
        # user's artifacts/dashboard/registry.json.
        self.root = root
        with _LOCK:
            self.registry = Registry(root, store=store)

    def refresh(self) -> dict:
        with _LOCK:
            self.registry.refresh()
            return self.registry.diagnostics()

    def fingerprint(self) -> str:
        """A cheap signature of what is on disk, so the page can notice that
        a new run appeared without the server rescanning everything."""
        parts: list[str] = []
        for spec in DEFAULT_ROOTS:
            base = self.root / spec.path
            if not base.is_dir():
                continue
            for candidate in sorted(base.glob(spec.pattern)):
                try:
                    parts.append(f"{candidate.name}:{int(candidate.stat().st_mtime)}")
                except OSError:
                    continue
        return str(hash("|".join(parts)))


STATE: State | None = None


# ---------------------------------------------------------------- payloads


def _experiments(kind: str | None = None) -> list[dict]:
    assert STATE is not None
    pinned = set(STATE.registry.pinned)
    return [
        {**e.to_dict(), "pinned": e.experiment_id in pinned}
        for e in STATE.registry.experiments
        if kind is None or e.kind == kind
    ]


def _models() -> dict:
    """The model registry: every set of weights any run measured or produced,
    and the runs that used it. This is where an evaluation of an adapter
    joins up with the training run that produced that adapter."""
    assert STATE is not None
    registry = STATE.registry
    models: dict[str, dict] = {}
    for experiment in registry.experiments:
        entry = models.setdefault(experiment.model.key, {
            "model": experiment.model.to_dict(),
            "evaluations": [], "training_runs": [], "produced_by": None,
        })
        row = {
            "experiment_id": experiment.experiment_id, "name": experiment.name,
            "status": experiment.status, "completed_at": experiment.completed_at,
            "benchmark": experiment.benchmark.to_dict() if experiment.benchmark else None,
            "metric_summary": experiment.metric_summary,
        }
        if experiment.kind == KIND_EVALUATION:
            entry["evaluations"].append(row)
        else:
            entry["training_runs"].append(row)

    # traceability: an adapter named by an evaluation is the directory name of
    # the training run that produced it
    training_by_adapter = {
        e.model.adapter_id: e for e in registry.experiments
        if e.kind == KIND_TRAINING and e.model.adapter_id
    }
    for key, entry in models.items():
        adapter = entry["model"].get("adapter_id")
        source = training_by_adapter.get(adapter)
        if source is not None and entry["evaluations"]:
            run = registry.training(source.experiment_id)
            entry["produced_by"] = {
                "experiment_id": source.experiment_id, "name": source.name,
                "status": source.status, "completed_at": source.completed_at,
                "dataset": run.dataset if run else {},
                "losses": run.losses if run else {},
                "note": (
                    "This adapter came from that training run. The training numbers describe the "
                    "training process; the evaluation numbers describe the answers. They are not the "
                    "same kind of measurement and are never differenced against each other."
                ),
            }
    return {
        "current_model_key": registry.current_model()["effective_model_key"],
        "models": [dict(v, key=k) for k, v in sorted(models.items())],
        "count": len(models),
    }


def _question_payload(run, question_id: str) -> dict | None:
    """The question record plus its forensic structure (regulus.dashboard.observatory)."""
    return question_detail(run, question_id)


def _one(query: dict, name: str) -> str | None:
    values = [v for v in query.get(name, []) if v != ""]
    if len(values) > 1:
        raise ValueError(f"parameter {name!r} was given more than once")
    return values[0] if values else None


# ------------------------------------------------------------------ routing


def _json_response(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, status: int, message: str, **extra) -> None:
    _json_response(handler, {"error": message, **extra}, status)


class Handler(BaseHTTPRequestHandler):
    server_version = "RegulusDashboard/1.0"

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        if "GET /api" not in (fmt % args):
            sys.stderr.write("  %s\n" % (fmt % args))

    # ---- GET

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            self._route(path, query)
        except BrokenPipeError:
            pass
        except Exception:
            traceback.print_exc()
            _error(self, 500, "the dashboard failed to build this response; see the server console")

    def _route(self, path: str, query: dict) -> None:
        assert STATE is not None
        registry = STATE.registry

        if path in ("/", "/index.html", f"/{PAGE}"):
            return self._page()
        if path == "/api/system/health":
            return _json_response(self, {
                "ok": True, "root": str(STATE.root), "page": PAGE,
                "fingerprint": STATE.fingerprint(),
                "loads_model": False, "connects_to_database": False,
                "writes": [str(registry.store_path.relative_to(STATE.root))
                           if registry.store_path.is_relative_to(STATE.root) else str(registry.store_path)],
                **{k: registry.diagnostics()[k] for k in ("scanned_at", "experiments", "by_status")},
            })
        if path == "/api/system/current-model":
            return _json_response(self, registry.current_model())
        if path == "/api/system/diagnostics":
            return _json_response(self, registry.diagnostics())
        if path == "/api/metrics/definitions":
            return _json_response(self, M.definitions_payload())
        if path == "/api/models":
            return _json_response(self, _models())

        # The model health views. Everything is derived from the registry and
        # the adapters; the browser parses no artifact and computes no metric.
        if path == "/api/benchmark-review/status":
            return _json_response(self, review_status(STATE.root))
        # The controlled acceptance evaluation and its provenance. Separate from
        # /api/model-health/current on purpose: that endpoint answers "has the
        # CONFIGURED system been evaluated?", this one answers "which acceptance
        # run is the authoritative benchmark result, and what produced it?".
        # Neither may stand in for the other, and this payload always carries
        # is_current so the page cannot present one as the other.
        if path == "/api/acceptance/current":
            return _json_response(self, acceptance_payload(registry))

        if path == "/api/model-health/current":
            return _json_response(self, current_health(registry, registry.thresholds))
        if path == "/api/model-health/current/history":
            return _json_response(self, current_history(registry))
        if path == "/api/model-health/current/metrics":
            payload = current_health(registry, registry.thresholds)
            return _json_response(self, {"state": payload["state"], "sections": payload["sections"],
                                         "coverage": payload.get("coverage")})
        if path == "/api/model-health/current/failures":
            payload = current_health(registry, registry.thresholds)
            return _json_response(self, {"state": payload["state"], "attention": payload.get("attention"),
                                         "failure_breakdown": payload.get("failure_breakdown")})

        if path == "/api/evaluation/experiments":
            return _json_response(self, {"experiments": _experiments(KIND_EVALUATION)})
        if path == "/api/training/runs":
            return _json_response(self, {"experiments": _experiments(KIND_TRAINING)})
        if path == "/api/experiments":
            return _json_response(self, {"experiments": _experiments()})

        if path == "/api/evaluation/history":
            return _json_response(self, evaluation_history(registry))

        if path == "/api/evaluation/compare":
            try:
                raw = _one(query, "ids") or ""
            except ValueError as exc:
                return _error(self, 400, str(exc))
            ids = [i.strip() for i in raw.split(",") if i.strip()]
            if not 2 <= len(ids) <= MAX_COMPARE:
                return _error(self, 400, f"compare needs 2 to {MAX_COMPARE} experiment ids, as ids=a,b[,c...]")
            if len(set(ids)) != len(ids):
                return _error(self, 400, "the same experiment id was given twice")
            try:
                pairs = iter_evaluation_pairs(registry, ids)
            except LookupError as exc:
                return _error(self, 404, str(exc))
            table = compare_runs(pairs)
            # Two runs keep the original pairwise payload (left/right/metrics/...)
            # beside the table, so existing consumers are unaffected.
            payload = compare(pairs[0][1], pairs[1][1]) if len(pairs) == 2 else {
                "comparable": all(c["comparable"] for c in table["runs"])}
            return _json_response(self, {**payload, "table": table})

        # The model-analysis view of one evaluation: the same blocks as the
        # current-model page, from that evaluation's own records, with the
        # freshness engine's verdict on whether it is the current model's.
        match = re.fullmatch(r"/api/evaluation/experiments/([^/]+)/analysis", path)
        if match:
            payload = experiment_analysis(registry, match.group(1), registry.thresholds)
            if payload is None:
                return _error(self, 404, f"no evaluation experiment {match.group(1)}")
            return _json_response(self, payload)

        match = re.fullmatch(r"/api/evaluation/experiments/([^/]+)(?:/(metrics|questions))?", path)
        if match:
            experiment_id, section = match.group(1), match.group(2)
            experiment = registry.experiment(experiment_id)
            run = registry.evaluation(experiment_id)
            if experiment is None or run is None:
                return _error(self, 404, f"no evaluation experiment {experiment_id}")
            if section == "metrics":
                return _json_response(self, {
                    "experiment": experiment.to_dict(),
                    "metrics": [m.to_dict() for m in run.metrics],
                    "breakdowns": run.breakdowns,
                })
            if section == "questions":
                try:
                    listing = question_list(run, filter_key=_one(query, "filter"), layer=_one(query, "layer"),
                                            category=_one(query, "category"), search=_one(query, "q"))
                except ValueError as exc:
                    return _error(self, 400, str(exc))
                return _json_response(self, {
                    "experiment_id": experiment_id,
                    "experiment": experiment.to_dict(),
                    **listing,
                    "failure_summary": run.failure_summary,
                })
            return _json_response(self, {
                "experiment": experiment.to_dict(),
                "run": run.to_dict(),
            })

        match = re.fullmatch(r"/api/evaluation/experiments/([^/]+)/questions/([^/]+)", path)
        if match:
            experiment_id, question_id = match.group(1), unquote(match.group(2))
            run = registry.evaluation(experiment_id)
            if run is None:
                return _error(self, 404, f"no evaluation experiment {experiment_id}")
            payload = _question_payload(run, question_id)
            if payload is None:
                return _error(self, 404, f"experiment {experiment_id} has no question {question_id}")
            return _json_response(self, {
                "experiment": registry.experiment(experiment_id).to_dict(),
                "question": payload,
            })

        match = re.fullmatch(r"/api/training/runs/([^/]+)(?:/(metrics|checkpoints))?", path)
        if match:
            experiment_id, section = match.group(1), match.group(2)
            experiment = registry.experiment(experiment_id)
            run = registry.training(experiment_id)
            if experiment is None or run is None:
                return _error(self, 404, f"no training run {experiment_id}")
            if section == "metrics":
                return _json_response(self, {
                    "experiment": experiment.to_dict(),
                    "metrics": [m.to_dict() for m in run.metrics],
                    "curves": run.curves,
                    "losses": run.losses,
                })
            if section == "checkpoints":
                return _json_response(self, {
                    "experiment_id": experiment_id,
                    "checkpoints": [c.to_dict() for c in run.checkpoints],
                    "selected": run.losses.get("best_checkpoint"),
                })
            return _json_response(self, {"experiment": experiment.to_dict(), "run": run.to_dict()})

        return _error(self, 404, f"no such endpoint: {path}")

    # ---- POST

    def do_POST(self) -> None:  # noqa: N802
        assert STATE is not None
        path = urlparse(self.path).path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return _error(self, 400, "the request body is not valid JSON")

        if path == "/api/refresh":
            return _json_response(self, {"refreshed": True, "diagnostics": STATE.refresh()})
        if path == "/api/registry/name":
            experiment_id, name = body.get("experiment_id"), body.get("name")
            if not experiment_id:
                return _error(self, 400, "experiment_id is required")
            STATE.registry.rename(experiment_id, name)
            return _json_response(self, {"ok": True, "experiments": _experiments()})
        if path == "/api/registry/pin":
            experiment_id = body.get("experiment_id")
            if not experiment_id:
                return _error(self, 400, "experiment_id is required")
            STATE.registry.pin(experiment_id, bool(body.get("pinned", True)))
            return _json_response(self, {"ok": True, "pinned": list(STATE.registry.pinned)})
        if path == "/api/registry/current-model":
            STATE.registry.set_pinned_model(body.get("model_key"))
            return _json_response(self, {"ok": True, "current_model": STATE.registry.current_model()})
        if path == "/api/registry/threshold":
            key = body.get("metric_key")
            if not key:
                return _error(self, 400, "metric_key is required")
            STATE.registry.set_threshold(key, body.get("good"), body.get("attention"))
            return _json_response(self, {"ok": True, "thresholds": STATE.registry.thresholds})
        return _error(self, 404, f"no such endpoint: {path}")

    # ---- the page

    def _page(self) -> None:
        page = WEB_DIR / PAGE
        if not page.is_file():
            return _error(self, 500, f"{page} is missing")
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    global STATE
    parser = argparse.ArgumentParser(description="Read-only dashboard for evaluation and training artifacts")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--root", default=str(ROOT), help="project root to scan")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    print(f"Scanning {root} ...")
    STATE = State(root)
    diagnostics = STATE.registry.diagnostics()
    print(f"  {diagnostics['experiments']} experiments  {diagnostics['by_status']}")
    if diagnostics["unsupported"]:
        print(f"  {len(diagnostics['unsupported'])} artifact(s) no adapter understands (see Diagnostics)")
    if diagnostics["errors"]:
        print(f"  {len(diagnostics['errors'])} artifact(s) failed to load (see Diagnostics)")
    current = STATE.registry.current_model()
    print(f"  current model: {current['effective_model_key']}"
          f"{'' if current['has_current_evaluation'] else '  (no evaluation of it exists)'}")
    print(f"\nNo model is loaded and no database connection is opened.")
    print(f"Open http://{args.host}:{args.port}\n")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
