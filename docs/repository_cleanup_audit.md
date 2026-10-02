# Repository cleanup audit (before the model ladder)

Date: 2026-10-01. Scope: audit and conservative cleanup only. No model was added, downloaded,
configured or tested; no prompt, retrieval, validation, answerability, generation-control,
database, benchmark, key or diagnostic-expectation change was made.

## Repository snapshot

| Item | Value |
| --- | --- |
| Commit audited | `800af07` (Baseline freeze after Stage 8) on `main` |
| Working tree at start | clean (`git status --short` empty) |
| Tracked files | 1,023 |
| `.git` | 13 MB (12.55 MiB loose objects, no packs) |
| Working directory on disk | 4,754,044 KB (≈4.5 GB), almost all gitignored: `models/` 2.4 GB, `.venv/` 955 MB, `.venv-windows-reference/` 930 MB, `data/` 183 MB |
| Tracked content on disk | ≈ `artifacts/` 63 MB, `tests/` 5.5 MB, `src/` 3.8 MB (incl. caches), docs/scripts/audit < 1 MB each |
| Running process at audit time | `scripts/serve_ui.py --port 8000` (pid 10754), left running; it writes `logs/serve_ui.log` |

The cleanup changes nothing under version control: every tracked file's sha256 was recorded
before cleanup and was byte-identical afterwards (1,023/1,023).

## Method

* `git ls-files`, `git status --short --ignored` and `find` for the full inventory, tracked and ignored.
* Usage by reference, not by name. Every `src/regulus` module was searched for imports from
  any other tracked file. Every `scripts/` and `audit/` script was searched for references by
  file name or module name. Configs and datasets were searched in `src`, `scripts`, `tests`,
  `web` and `configs`.
* Duplicates by sha256 over all tracked files.
* Markdown links and backticked repository paths in all tracked `.md` files were resolved
  against the disk.
* Dependencies: each `requirements.txt` entry was matched to actual imports, and all
  third-party imports were checked against `requirements.txt`.
* Integrity: the hashing and database-checksum logic of `scripts/write_baseline_manifest.py`
  was re-run read-only before and after cleanup.

## File classification

### Tracked files (1,023)

| Class | Count | What |
| --- | ---: | --- |
| A — active / required | 258 | `src/` 121, `tests/` 59, `scripts/` 42, `configs/` 8 (all are loaded by `regulus.training.config` / `regulus.finetune.config` / tests), `data/evaluation/` 10 (6 datasets, 2 semantic manifests, 2 `.gitkeep`), `web/` 2, benchmark workbook, `artifacts/baselines/`, `artifacts/benchmark_keys/` 3, `artifacts/dashboard/registry.json`, `artifacts/generation_quality/generation_cache.jsonl` (read by `scripts/generation_experiments.py`), `docs/model_ladder_handoff.md`, README, `pyproject.toml`, `requirements.txt`, `.gitignore`, `.env.example`, the other 3 `.gitkeep` files |
| B — protected historical evidence | 765 | all other `artifacts/` run directories (diagnostics, answer_quality, answer_shape, latency, retrieval_eval, generation_quality, generation_control, stage5_stage6, validation_eval, benchmark_verification, `ASSISTED_REVIEW_NOT_VERIFIED`), Stage 1–8 and 12–14 documentation in `docs/` (36), `audit/` (21), `MODEL_SYSTEM_AUDIT_AND_TEST_REPORT.md`, `data/training/` manifests (9), `models/qwen3-0.6b-lora/stage12_v1`, `stage13_v1`, `stage14_v1` metadata and logs (21) |
| C — archivable | 0 | see "Archive proposals": none was moved |
| D — generated / reproducible | 0 | no tracked file is a disposable generated artifact |
| E — obsolete / unused | 0 | every module and script is referenced, or produced tracked evidence |
| F — uncertain | 0 | |

### Ignored / untracked local files (never in Git)

| Class | Path | Size | Decision |
| --- | --- | ---: | --- |
| A | `models/models--Qwen--Qwen3-0.6B/` (weights + tokenizer of the frozen baseline) | 1.4 GB | keep |
| A | `models/models--BAAI--bge-small-en-v1.5/` (semantic-fallback embedder) | 128 MB | keep |
| A | `data/evaluation/semantic/semantic_expanded_v1/generated/` (the active `semantic_corpus` of the Stage 8 retriever) | 78 MB | keep |
| A | `.venv/` (runtime + editable install) | 955 MB | keep |
| A | `.env` (local DB URL) | < 1 KB | keep |
| B | `models/qwen3-0.6b-lora/stage12_v1/` and `stage13_v1/` adapter, tokenizer and checkpoints | 303 MB + 430 MB | keep: Stage 12/13 training evidence |
| B | `data/evaluation/results/` (32 ignored run results incl. `stage12_v1`, `stage13_v1`, `stage14_v1`) | 9 MB | keep: the only copies of these results |
| B | `data/training/datasets/*.jsonl` (training/validation/test v1, v2, v3, v6) | 87 MB | keep: regenerable but they are the hashed inputs of Stages 12–14 |
| B | `data/evaluation/semantic/generated/` (Stage 8 semantic-experiment corpus) | 8.5 MB | keep |
| B | `logs/` stage logs (`stage2_resume`, `stage3_A_baseline`, `stage3_B_structured`, `stage4_diagnostics`, UI/dashboard logs) | 68 KB | keep: run logs, some cited by stage work; `serve_ui.log` is live |
| D (kept) | `src/regulus.egg-info/` | < 50 KB | keep: editable-install metadata, recreated by `pip install -e .`, no gain from removal |
| **D (removed)** | 21 `__pycache__/` directories (src, scripts, tests) | 7.5 MB | **removed**, see below |
| **D (removed)** | `.pytest_cache/` | 136 KB | **removed**, see below |
| F | `.venv-windows-reference/` (a Windows Python 3.11.9 venv copied from the original machine, `C:\Users\PC-1\...`) | 930 MB | **untouched**: not used on macOS and referenced only by `.gitignore`. Its purpose as a "reference" environment (e.g. reconstructing the Windows Stage 12–14 dependency set) is unclear. Owner decision. |
| F | `models/qwen3-0.6b-lora/smoke_tmp/` (1-step Stage 12 smoke training run, Windows, 2026-09-21) | 176 MB | **untouched**: gitignored and unreferenced, but part of the Stage 12 training lineage and not byte-reproducible on this machine |

## Files removed

Every entry below meets all six criteria. Each is unreferenced, outside any baseline, not needed
by tests (pytest recreates caches on demand), not needed for reproducibility, regenerable by
Python/pytest, and not the only copy of anything (the directories held only `.pyc` files,
which was checked before deletion). All were gitignored, so the removal does not appear in Git.

| File | Reason | Evidence unused | Reproducible? | Safe to delete? |
| --- | --- | --- | --- | --- |
| `scripts/__pycache__/`, `src/regulus/**/__pycache__/` (18), `tests/__pycache__/`, `tests/integration/__pycache__/` (21 dirs, 7.5 MB) | Python bytecode cache | gitignored, never referenced, contained only `*.pyc` | yes, recreated on import | yes |
| `.pytest_cache/` (136 KB) | pytest run cache (last-failed and similar state) | gitignored, not read by any script | yes, recreated by pytest | yes |

These caches come back the next time Python or pytest runs with bytecode writing on. Removing them
cleans out stale bytecode from earlier stages. It is not a lasting size reduction.

## Archive proposals (not carried out)

Moving files was considered and rejected for this task. Moves would be cosmetic, and
references would have to be rewritten inside historical documents:

| Candidate | Why not moved now |
| --- | --- |
| `docs/` into `docs/current/` + `docs/history/` | stage documents cross-reference each other, and scripts write to fixed doc paths (`scripts/generate_metric_docs.py` → `docs/model_dashboard_metrics.md`). A move means editing historical docs. It could be done later as its own reviewed change. |
| `MODEL_SYSTEM_AUDIT_AND_TEST_REPORT.md` (root) into `docs/history/` | historical report. It cites `audit/results/*` with root-relative paths, which stay valid wherever the file lives, but there is no functional benefit. |
| `audit/` into an archive directory | its scripts write to `audit/results/` by fixed path, and the audit report cites those paths |
| Byte-identical files across run directories (137 redundant copies, e.g. `answer_quality/stage3_ab_*` review files, `stage5_stage6/run_*/stage5`) | each run directory is a self-contained evidence snapshot. The identical outputs across repeated runs are themselves evidence of determinism. Removing one copy would leave a run incomplete. |
| Training adapters and checkpoints (≈ 0.9 GB, ignored) | could later move to an external artifact store. Not now: Stage 12/13 evidence. |

## Files explicitly preserved

* Regulatory database (PostgreSQL, accessed read-only). Content checksums unchanged.
* Benchmark `Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx` and key baseline
  `artifacts/benchmark_keys/regulus_acceptance_rev02@c009d5f9c649/baseline.json`. Key status is
  still 300 total, 0 expert verified. `artifacts/ASSISTED_REVIEW_NOT_VERIFIED/` keeps its name and content.
* Diagnostic datasets `diagnostic_v1`, `stage5_v1`, `retrieval_v2`, plus `baseline_v1`,
  `retrieval_v1`, `answer_shape_v1` (all still read by scripts/tests).
* `artifacts/baselines/post_stage8_baseline.json` (sha256 `907f96bf…7a1d`, unchanged).
* Evaluation infrastructure: `scripts/run_diagnostics.py`, `evaluate_*`, `write_baseline_manifest.py`,
  `verify_benchmark_key.py`, `regulus.observability`, `regulus.evaluation`, and the `Generator`/backend
  seam and model-loading/device/dtype configuration needed by the model ladder.
* Stage 12–14 training evidence: tracked metadata, logs including `stage14_v1/*.stalled.log`, the ignored
  adapters/checkpoints, the ignored `data/evaluation/results/stage1{2,3,4}_v1/`, and the training datasets.
* Stage 0–8 and 12–14 documentation, unmodified.
* Scripts not referenced elsewhere, kept because they produced tracked evidence:
  `scripts/evaluate_targeted.py` (Stage 8 `artifacts/generation_control/targeted_*`, including
  `targeted_freeze`), `audit/stage4_live_check.py` and `audit/stage4_token_benchmark.py`
  (`audit/results/stage4_*`).
* `audit/results/analysis.err` (empty, but cited in `MODEL_SYSTEM_AUDIT_AND_TEST_REPORT.md`).

## Dependencies (documented, not changed)

* Every `requirements.txt` entry is imported: torch, transformers, huggingface_hub, accelerate
  (version capture in `finetune/train.py`), safetensors, psycopg, peft, pyyaml, python-dotenv, pytest.
  None is unused.
* Undeclared: `psutil` (installed, 7.2.2). It is a hard import in `scripts/benchmark_latency.py`;
  elsewhere it is guarded by `try/except`. Candidate for a separate dependency change.
* `numpy` and `tokenizers` are imported directly but arrive transitively through torch/transformers.

## Pre-existing reference gaps (not caused by cleanup, not changed)

There are no broken Markdown links. Thirteen backticked paths do not exist on disk:

* `docs/stage0_architecture_blueprint.md`: 12 planned paths (`src/regulus/conversation/state.py`,
  `src/regulus/evidence/*`, `src/regulus/planning/planner.py`, `src/regulus/validation/answer.py`,
  `scripts/evaluate_architecture.py`, `data/evaluation/datasets/architecture_v1.jsonl`, and the related tests).
  This is the Stage 0 design intent, recorded as planned before implementation took a different layout.
* `docs/model_dashboard_architecture.md`: `tests/test_dashboard.py`. The dashboard tests exist as
  `tests/test_dashboard_*.py`.

These are historical statements, so they were not edited.

## Risks / do not touch yet

* `.venv-windows-reference/` and `models/qwen3-0.6b-lora/smoke_tmp/` (class F, above).
* `.gitignore` lists `logs/` and `.DS_Store` twice. This is harmless and left as-is.
* `serve_ui.py` was running during the audit. Stop it before any timed model-ladder run.
* The slow test tier has 3 failures recorded in the baseline manifest. They were not re-run here.

## Verification

| Metric | Before cleanup | After cleanup | Difference |
| --- | ---: | ---: | ---: |
| Test results (default suite) | 1266 passed, 1 skipped, 26 deselected | 1266 passed, 1 skipped, 26 deselected | none |
| Diagnostic results (79 Q, automatic) | DIAG_BEFORE | DIAG_AFTER | DIAG_DIFF |
| Determinism (10 repeats) | 10/10 identical | DET_AFTER | DET_DIFF |
| Benchmark workbook sha256 | `c009d5f9…c4a110` | `c009d5f9…c4a110` | none |
| Benchmark key baseline sha256 | `472d0be1…7b7454` | `472d0be1…7b7454` | none |
| Database | read-only on; `cfr_records` md5 `7b1bb7d8…a9693a9`, `fda_guidance_chunks` md5 `5a2f5e87…d0cf06`; row counts 65341 / 7906 / 250 / 1836 / 68669 | identical | none |
| Diagnostic dataset hashes | diagnostic `f99b1106…`, stage5 `7cf80fda…`, retrieval_v2 `db73c6fa…`, semantic manifest `5b1e8ccf…` | identical | none |
| Model weights sha256 | `f47f7117…96874b` | `f47f7117…96874b` | none |
| Tokenizer sha256 (json / config) | `aeb13307…` / `d5d09f07…` | identical | none |
| Configs (`configs/*.yaml`, 8 files) | recorded | identical | none |
| Baseline manifest sha256 | `907f96bf…7a1d` | `907f96bf…7a1d` | none |
| Protected / tracked files | 1,023 tracked, sha256 recorded | 1,023/1,023 byte-identical | none |
| Repository size on disk | 4,754,044 KB | 4,746,396 KB (before the verification run's output was added) | −7,648 KB (caches) |

DIAG_NOTES
