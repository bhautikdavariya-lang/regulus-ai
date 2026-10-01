"""Write a machine-readable baseline manifest for one verified system state (no model is loaded).

    python scripts/write_baseline_manifest.py --run <diagnostic run dir> --name post_stage8 [--tests "1266 passed, 1 skipped"]

Records what a later run must match to be comparable (the model ladder): code commit, model
identity and weight/tokenizer hashes, database content hashes, benchmark/dataset hashes, prompt and
pipeline configuration, decoding, device/dtype, test count and the run's results. Read-only: the
database is queried through the read-only connection; nothing protected is modified.

Output: artifacts/baselines/<name>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.config import load_settings  # noqa: E402
from regulus.retrieval import Database  # noqa: E402

PROTECTED_FILES = {
    "benchmark_workbook": "Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx",
    "benchmark_key_baseline": "artifacts/benchmark_keys/regulus_acceptance_rev02@c009d5f9c649/baseline.json",
    "diagnostic_set": "data/evaluation/datasets/diagnostic_v1.jsonl",
    "stage5_set": "data/evaluation/datasets/stage5_v1.jsonl",
    "retrieval_set": "data/evaluation/datasets/retrieval_v2.jsonl",
    "semantic_manifest": "data/evaluation/semantic/semantic_expanded_v1/manifest.yaml",
}
DB_TABLES = ("cfr_records", "cfr_sections", "cfr_parts", "fda_guidance", "fda_guidance_chunks")


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip() or None
    except Exception:
        return None


def first(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out.setdefault(r["question_id"], r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--tests", default=None, help="the test-suite result line, as run")
    args = ap.parse_args()
    run = Path(args.run).resolve()
    score = json.loads((run / "scorecard.json").read_text(encoding="utf-8"))
    repro = score.get("reproducibility") or {}
    diags = first(run / "diagnoses.jsonl")
    reviews = first(run / "manual_review.jsonl") if (run / "manual_review.jsonl").exists() else {}
    reviewed = Counter((reviews.get(q) or {}).get("reviewed_status", d["final_status"]).split(" ")[0] for q, d in diags.items())

    settings = load_settings()
    snap = sorted(Path(settings.model.cache_dir).glob(f"models--{settings.model.id.replace('/', '--')}/snapshots/*"))
    snap = snap[0] if snap else None
    db = Database.from_env()
    db.connect()
    database = {
        "read_only": db.query("SHOW default_transaction_read_only")[0]["default_transaction_read_only"],
        "row_counts": {t: db.query(f"SELECT count(*) AS n FROM {t}")[0]["n"] for t in DB_TABLES},
        "cfr_records_content_md5": db.query(
            "SELECT md5(string_agg(md5(coalesce(body_text,''))||coalesce(section_number,'')||coalesce(paragraph_path,''), ',' ORDER BY id)) AS h "
            "FROM cfr_records")[0]["h"],
        "fda_guidance_chunks_content_md5": db.query(
            "SELECT md5(string_agg(md5(coalesce(body_text,'')), ',' ORDER BY id)) AS h FROM fda_guidance_chunks")[0]["h"],
    }
    db.close()
    manifest = {
        "manifest": args.name,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code": {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain"))},
        "model": {
            "model_id": repro.get("model_id"), "model_revision": repro.get("model_revision"),
            "weights_sha256": repro.get("weights_sha256"),
            "tokenizer_json_sha256": sha256(snap / "tokenizer.json") if snap else None,
            "tokenizer_config_sha256": sha256(snap / "tokenizer_config.json") if snap else None,
            "device": repro.get("device"), "dtype": repro.get("dtype"), "decoding": repro.get("decoding"),
            "backend": settings.model.backend,
        },
        "prompt": {"system_prompt_sha256": repro.get("system_prompt_sha256")},
        "pipeline_config": repro.get("pipeline_config"),
        "retriever": repro.get("retriever"),
        "database": database,
        "protected_files_sha256": {k: sha256(ROOT / v) for k, v in PROTECTED_FILES.items()},
        "tests": args.tests,
        "diagnostic_run": {
            "path": str(run.relative_to(ROOT)),
            "questions": len(diags),
            "automatic_status": score.get("final_status"),
            "reviewed_status": dict(reviewed),
            "outcomes_automatic": score.get("outcomes"),
            "determinism": {"identical": sum(1 for d in score.get("determinism") or [] if d["raw_identical"] and d["final_identical"]),
                            "repeats": len(score.get("determinism") or [])},
            "run_git_commit": repro.get("git_commit"), "run_git_dirty": repro.get("git_dirty"),
        },
    }
    out = ROOT / "artifacts/baselines" / f"{args.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("code", "model", "database")}, indent=1, default=str))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
