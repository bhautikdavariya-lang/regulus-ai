# Deploying the UI with a remote GPU inference server

This guide is for operators deploying Regulus with model inference on a separate GPU server. The code
supports the split described here, and it is tested with a fake inference server. **No cloud deployment
has been performed or verified.** The networking, authentication and storage requirements below must be
checked in the real environment before any user is given access.

## Responsibilities

| Component | Runs | Holds |
|---|---|---|
| GPU inference server | an OpenAI-compatible chat-completions server (vLLM, TGI, llama.cpp or similar) serving the model | the model weights. **No user data is stored there by Regulus.** |
| Application host | `scripts/serve_ui.py`: the UI, the request lifecycle, retrieval from the regulatory database, validation, the accuracy evaluator, chat history and measurement records | `data/chat/` and `data/ui_measurements/` |
| Offline evaluation | `scripts/evaluate_ui_session.py`, on the application host or a workstation with a copy of `data/` | result files inside each session directory |

Restarting or replacing the GPU server fails only the requests in flight. Each one is recorded as a
`pipeline_error` with a `remote inference failed (<category>)` message. It never touches measurement
history, which lives only on the application host.

## Configuration

Inference is selected exactly as for the acceptance runner (`regulus.rag.remote_generator`):

| Setting | Meaning |
|---|---|
| `model.backend` in `configs/model.yaml`, or `REGULUS_MODEL_BACKEND` | `transformers` (default: in-process, the model is loaded on this host) or `openai_compatible` (the GPU server) |
| `model.endpoint`, or `REGULUS_MODEL_ENDPOINT` | the server's OpenAI-compatible base URL, ending before `/chat/completions` |
| `REGULUS_MODEL_API_KEY` | optional bearer token for the inference server. Read from the environment only, sent only as an `Authorization` header, never logged or recorded |
| `model.id` | the model id requested from the server; it must match an id the server serves |
| `serve_ui.py --backend openai_compatible` | overrides `model.backend` for this run |
| `serve_ui.py --inference-timeout SECONDS` | how long to wait for the inference server (default 600) |

In `openai_compatible` mode the UI loads **no tokenizer and no weights** (tested), and a locally configured
adapter is refused at start, because adapters merge locally and cannot apply to a remote model. At start
the UI asks the server which models it serves (`GET {endpoint}/models`) and logs whether the configured
id is listed. It never logs the endpoint itself.

Prefer passing the endpoint through the environment or the config file rather than on the command line,
where it would be visible in process listings.

## Network boundary

- **The UI server has no authentication.** Its chat-history endpoints return every stored conversation.
  It binds to loopback (`127.0.0.1`) by default, and **refuses** a non-loopback `--host` unless
  `--allow-remote-clients` is also given (fail-closed; tested). Pass that flag only when the server sits
  behind both of these:
  - a private network that untrusted clients cannot reach;
  - an authenticated HTTPS reverse proxy that is the only way in.

  Binding to `0.0.0.0` is never secure on its own.
- **Application host to GPU server:** keep this traffic on a private network. Use HTTPS, or a private link,
  if the network is not trusted. The UI warns at start when the endpoint is plain HTTP to a non-loopback
  host. Do not expose the inference server publicly; if it must be reachable beyond the private network,
  require `REGULUS_MODEL_API_KEY`.
- **Database:** the regulatory PostgreSQL database stays reachable from the application host only, opened
  read-only, as today.

## Persistent storage (required)

`data/` on the application host must be on a **persistent volume** that survives process restarts,
reboots, redeployments and replacement of the VM or container. A container's writable layer, an ephemeral
instance disk or an autoscaled worker's local disk is not enough: measurement history and chat history
would be lost with it.

- **One server process writes its own session directory.** Several processes, or several hosts, never
  write the same session: each start creates a new uniquely named session, so they cannot collide. Several
  hosts need their own persistent volumes, or one shared persistent filesystem, plus a collection step
  before offline evaluation.
- **Permissions:** session files are created `0700`/`0600`. Make sure the volume's own permissions and
  ownership restrict it to the service account.
- **Backups:** back up the volume to private storage. Never to a public bucket, a log pipeline or git
  (`data/chat/` and `data/ui_measurements/` are git-ignored).
- **Retention and deletion:** nothing expires automatically. Decide a retention period and delete session
  directories accordingly (see `docs/measurement_record.md`).

## Operator checklist

**Before the first deployment**
- [ ] `data/` is on a persistent volume, owned by the service account, not world-readable
- [ ] The UI is reachable only through an authenticated HTTPS reverse proxy on a private network; `--allow-remote-clients` is used only in that setup
- [ ] The inference server is on a private network (HTTPS, or a trusted link); `REGULUS_MODEL_API_KEY` is set if it is reachable more widely
- [ ] The startup log says `Inference: remote ...` and that the configured model is served
- [ ] The startup log says `Measurement records: ON -> ...` (or `OFF` deliberately)
- [ ] Disk-space monitoring and an alert on the `data/` volume
- [ ] Log collection alerts on `measurement event=write_failed` and `event=partial_line_terminated`
- [ ] The process manager stops the server with SIGTERM (systemd and Docker default), so sessions close cleanly
- [ ] Backups of `data/` are configured and a restore has been tried
- [ ] A retention period is decided and documented

**Before running several application workers or hosts**
- [ ] Each worker has a persistent volume, or one shared persistent filesystem
- [ ] A collection step brings session directories together for offline evaluation
- [ ] `GET /api/config` → `measurement` is checked per worker

## Known gaps

| Gap | Severity |
|---|---|
| No built-in authentication. It relies on the proxy and the network boundary above. | High until those are in place |
| A remote server reports no weights revision. Records carry the model id, the served-model list and a hashed endpoint, but cannot prove which weights answered. | Medium |
| Durability depends on the volume honouring `fsync`. A non-persistent or misbehaving volume can lose recent records. | Medium |
| Offline evaluation still differs from live: lexical by default (`--offline-aligner semantic` uses the live embedder), and the identifier index is not replayed, although its lookups are now recorded. | Medium |
| No alerting is built in. Failures are visible in logs and `/api/config`; alerting must be configured on the platform. | Medium |
| Requests in flight when the server stops are not recorded. They were never delivered. | Low |
