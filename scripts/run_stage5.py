"""Stage 5: comprehensive baseline evaluation (standalone entry point).

    python scripts/run_stage5.py --check                      # validate environment only
    python scripts/run_stage5.py                              # full Stage 5 into a new run directory
    python scripts/run_stage5.py --run-dir artifacts/stage5_stage6/<run_id>   # resume / reuse
    python scripts/run_stage5.py --skip-generation --limit 5  # evidence phases only, fast smoke

Read-only against the database. The configured model (configs/model.yaml,
REGULUS_ADAPTER) unless --adapter replaces the adapter (used by
Stage 6 for the trained comparison). One model process at a time: the run
refuses to start while another model-sized Python process (the UI server) is
alive.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from regulus.automation import PipelineLog, ResourceError, ensure_resources, new_run_id, resource_report
from regulus.config import PROJECT_ROOT, load_settings

ARTIFACTS = PROJECT_ROOT / "artifacts" / "stage5_stage6"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", default=None, help="run directory (default: artifacts/stage5_stage6/<new run id>)")
    p.add_argument("--run-id", default=None, help="run id used in reports (default: directory name)")
    p.add_argument("--dataset", default=None, help="Stage 5 dataset JSONL (default: data/evaluation/datasets/stage5_v1.jsonl)")
    p.add_argument("--ids", nargs="+", default=None, help="only these question ids")
    p.add_argument("--limit", type=int, default=None, help="only the first N questions")
    p.add_argument("--skip-generation", action="store_true", help="evidence phases and report only (no model)")
    p.add_argument("--no-controlled", action="store_true", help="skip the exact-evidence-only generation mode")
    p.add_argument("--adapter", default=None, help="LoRA adapter directory to merge into the base model (Stage 6 comparison)")
    p.add_argument("--allow-download", action="store_true", help="allow Hugging Face downloads (default: local files only)")
    p.add_argument("--check", action="store_true", help="validate environment (database, dataset, model cache, resources) and exit")
    p.add_argument("--answer-shape", choices=("off", "adaptive", "structured"), default=None,
                   help="override RagConfig.answer_shape (default: as configured); 'structured' = answer-quality Stage 3")
    return p.parse_args()


def check_environment() -> int:
    from regulus.model import load_tokenizer
    from regulus.retrieval import Database
    from regulus.stage5 import load_stage5_dataset

    ok = True
    settings = load_settings()
    print(f"model: {settings.model.id} (cache {settings.model.cache_dir})")
    try:
        load_tokenizer(settings.model, local_files_only=True)
        print("model cache: tokenizer found locally")
    except Exception as exc:
        ok = False
        print(f"model cache: FAIL ({exc})")
    try:
        db = Database.from_env()
        db.connect()
        st = db.status()
        ro = str(st.get("default_transaction_read_only", "")).lower() in ("on", "true", "1")
        n = db.query("SELECT count(*) AS n FROM cfr_records WHERE removed_on IS NULL")[0]["n"]
        db.close()
        print(f"database: {st.get('database')} read-only={st.get('default_transaction_read_only')} live eCFR rows={n}")
        ok = ok and ro
    except Exception as exc:
        ok = False
        print(f"database: FAIL ({exc})")
    try:
        ds = load_stage5_dataset()
        print(f"dataset: {ds.name} {len(ds)} questions sha256={ds.sha256[:16]}")
    except Exception as exc:
        ok = False
        print(f"dataset: FAIL ({exc})")
    rep = resource_report()
    print(f"resources: available RAM {rep.get('available_ram_gb')} GB; other model-sized Python processes: {rep.get('other_model_processes')}")
    if rep.get("other_model_processes"):
        print("WARNING: stop the other model process (for example scripts/serve_ui.py) before running Stage 5 or Stage 6")
    print("ENVIRONMENT OK" if ok else "ENVIRONMENT PROBLEMS FOUND")
    return 0 if ok else 1


def make_generator_factory(adapter: str | None, offline: bool):
    """The configured model (configs/model.yaml + REGULUS_*), or the configured
    base model with `--adapter` in place of any configured adapter."""

    def factory():
        from regulus.rag import load_qwen_generator
        from regulus.system_identity import configured_generation_config

        settings = load_settings()
        if adapter:
            settings.model.adapter = Path(adapter)
        # decoding exactly as the answering pipeline runs it (greedy, thinking off)
        settings.generation = configured_generation_config(settings)
        # load_qwen_generator merges the adapter and attaches `system_identity`,
        # which regulus.stage5.identity records in run_manifest.json
        return load_qwen_generator(settings, local_files_only=offline)

    return factory


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if args.check:
        return check_environment()
    from regulus.stage5 import Stage5Error, run_stage5

    run_dir = Path(args.run_dir) if args.run_dir else ARTIFACTS / new_run_id()
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or run_dir.name
    log = PipelineLog(run_dir / "pipeline.log")
    log.tag("START", f"stage5 run_dir={run_dir}")
    config = None
    if args.answer_shape:
        from dataclasses import replace

        from regulus.system_identity import evaluation_rag_config

        config = replace(evaluation_rag_config(load_settings()), answer_shape=args.answer_shape)
        log.info(f"answer_shape override: {args.answer_shape}")
    try:
        result = run_stage5(
            run_dir, run_id=run_id, log=log,
            generator_factory=None if args.skip_generation else make_generator_factory(args.adapter, not args.allow_download),
            dataset_path=Path(args.dataset) if args.dataset else None, ids=args.ids, limit=args.limit,
            skip_generation=args.skip_generation, controlled=not args.no_controlled, config=config,
        )
    except (Stage5Error, ResourceError) as exc:
        log.error(exc, "stage 5")
        return 1
    except Exception as exc:  # noqa: BLE001 - the log must show why an unattended run stopped
        log.error(exc, "stage 5")
        return 1
    log.tag("DONE", f"reports in {run_dir / 'stage5'}; Stage 6 recommended: {result['plan']['proceed']}")
    print(f"\nStage 5 report: {run_dir / 'stage5' / 'STAGE5_FINAL_REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
