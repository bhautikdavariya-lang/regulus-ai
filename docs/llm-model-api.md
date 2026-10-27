# llm-model API (v1)

The Regulus answering service that regulus-backend calls. It answers with the measured application (Qwen3-4B-Instruct-2507
4-bit on MLX, the production pipeline and its default switches) and follows the backend's conventions in
`Regulus-21-API-doc.md`. Code: `src/regulus/api/llm_model.py`; start: `scripts/start_llm_model.sh`.

## Run it on a Mac

1. `python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt` (and the MLX interpreter as for the UI).
2. `cp configs/llm_model.env.example configs/llm_model.env` and fill it in: the API key(s), the shared database URL,
   the MLX interpreter and model snapshot.
3. `scripts/start_llm_model.sh`, then `curl http://127.0.0.1:8100/llm-model/v1/ready`.

Every Mac points `REGULUS_DATABASE_URL` at the one shared PostgreSQL server (a read-only role is enough). To serve other
machines, set `LLM_MODEL_HOST=0.0.0.0` with `LLM_MODEL_TLS_CERT` / `LLM_MODEL_TLS_KEY`, or run behind an HTTPS reverse
proxy with `--behind-proxy`. Plain HTTP beyond loopback is refused: the API key must not cross a network in clear text.
One Mac answers one question at a time (about 40-150 s each); more Macs behind a load balancer answer more at once.

## Endpoints (prefix `/llm-model/v1`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/answer` | API key | idempotent (`X-Idempotency-Key`); body below |
| `POST` | `/answer/stream` | API key | idempotent; NDJSON events `start`, `progress` (no text), then `final` or `error` |
| `GET` | `/health` | public | the process is up |
| `GET` | `/ready` | public | 200 when the model and the database answer, else 503 |
| `GET` | `/info` | API key | model, release (code revision, switches), database snapshot, limits |

Auth: `Authorization: Bearer <secret>`; keys come from `LLM_MODEL_API_KEYS` (`id:secret`, 24+ characters).

### Request

```json
{ "question": "Can we use mica in an eye shadow?",
  "focus": "cosmetics",
  "conversation": [ { "question": "Is mica a color additive?", "anchor": { "cfr": ["73.2496"], "statute": [], "parts": [] } } ] }
```

`question` 1-2000 characters. `focus` is `cosmetics`, `general` or omitted. `conversation` (optional, at most 10, oldest
first) carries the earlier turns, each with the `conversation.anchor` its answer returned: the service keeps no state.

### Response (200)

```json
{ "id": "…", "state": "VERIFIED", "answer": "…",
  "citations": [ { "index": 1, "label": "21 CFR 73.2496(b)", "url": "https://www.ecfr.gov/…", "corpus": "ecfr", "citedInAnswer": true } ],
  "conversation": { "anchor": { "cfr": ["73.2496"], "statute": [], "parts": [] } },
  "evaluation": { "status": "PASS", "score": 92 },
  "model": { "id": "qwen3-4b-2507", "label": "…", "model_revision": "50d4277…" },
  "release": { "revision": "…", "switches": ["A1", "…"] },
  "snapshotDate": "2026-10-20", "focus": "cosmetics", "timingsMs": { "pipeline": 41234.5, "total": 41301.2 } }
```

`state`: `VERIFIED` (validated answer, or a verbatim composed one), `PARTIAL` (part of the evidence did not fit, or only the
provision's text could be given), `NO_SOURCE`, `NOT_COVERED`, `NONEXISTENT_SECTION`, `SECTION_REMOVED` (a former Part
820 section), `ISO_POINTER`, `GATE_FAILURE` (the draft failed validation and was withheld), `OUT_OF_SCOPE` (HTTP 422).

### Errors

`{ "code": "…", "message": "…", "fieldErrors": { … } }` with 400 (invalid JSON), 401, 404, 409 (idempotency key reused
with another body), 411, 413 (over `LLM_MODEL_MAX_BODY_BYTES`, default 64 KB), 415, 422 (schema; out of scope), 429
(`Retry-After`; `LLM_MODEL_RATE_PER_MIN` per key, default 30), 500, 503 (`model_busy` with `Retry-After`, or not ready).
