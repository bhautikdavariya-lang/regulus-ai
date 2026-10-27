"""Start the llm-model API (regulus.api.llm_model) with the application's model and database.

    scripts/start_llm_model.sh      (reads configs/llm_model.env; see configs/llm_model.env.example)
or
    LLM_MODEL_API_KEYS=backend:<secret> REGULUS_DATABASE_URL=... REGULUS_MLX_PYTHON=... REGULUS_MLX_MODEL_PATH=... \
        python scripts/serve_llm_model.py --host 0.0.0.0 --port 8100 --tls-cert cert.pem --tls-key key.pem

The engine is the UI's (scripts/serve_ui.py Engine): the same model checks, pipeline and switches, so the API answers
exactly as the measured application does. Every machine-specific value - the model, its interpreter, the database, the
keys - comes from the environment. A non-loopback address needs TLS (--tls-cert / --tls-key) or, behind an HTTPS
reverse proxy on a private network, --behind-proxy: the API key must never cross a network in clear text.
"""
from __future__ import annotations

import argparse
import ssl
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regulus.api.llm_model import PREFIX, ApiConfig, Service, make_handler, release_info  # noqa: E402
from regulus.config import load_settings  # noqa: E402
from serve_ui import Engine, is_loopback, serve_until_stopped  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--tls-cert", default=None, help="PEM certificate: serve HTTPS directly")
    p.add_argument("--tls-key", default=None, help="PEM private key for --tls-cert")
    p.add_argument("--behind-proxy", action="store_true",
                   help="allow plain HTTP on a non-loopback address: only behind an HTTPS reverse proxy on a private network")
    p.add_argument("--offline", action="store_true", help="fail instead of downloading the tokenizer")
    p.add_argument("--no-evaluation", action="store_true", help="do not run the live evaluator (answers are unchanged)")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    try:
        config = ApiConfig.from_env()
    except ValueError as exc:
        raise SystemExit(f"llm-model cannot start: {exc}") from None
    tls = bool(args.tls_cert and args.tls_key)
    if not is_loopback(args.host) and not tls and not args.behind_proxy:
        raise SystemExit("llm-model refuses plain HTTP on a non-loopback address: pass --tls-cert and --tls-key, or "
                         "--behind-proxy when an HTTPS reverse proxy on a private network terminates TLS")
    engine = Engine(load_settings(), offline=args.offline)
    engine.accuracy = not args.no_evaluation
    service = Service(engine, config, release_info())
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    scheme = "https" if tls else "http"
    print(f"\n  llm-model {service.release.get('revision') or ''}: {scheme}://{args.host}:{args.port}{PREFIX}/health"
          f"  ({len(config.keys)} API key(s); Ctrl+C to stop)\n", flush=True)
    serve_until_stopped(server, lambda: engine.db.close())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
