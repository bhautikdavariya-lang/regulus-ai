"""Run facts for the workbook builder, from the holdout run's own records. python run_facts.py <run_dir> <out.json>"""
import json, sys
from datetime import datetime, timedelta
from pathlib import Path

run = Path(sys.argv[1])
prov = json.loads((run / "run_provenance.json").read_text())
rows = [json.loads(l) for l in (run / "answers.jsonl").read_text().splitlines() if l.strip()]
start = datetime.strptime(prov["started_local"][:19], "%Y-%m-%d %H:%M:%S")
wall = sum(r.get("seconds") or 0 for r in rows)
end = datetime.fromtimestamp((run / "answers.jsonl").stat().st_mtime)
model = (rows[0].get("model") or {}) if rows else {}
rev = model.get("model_revision") or prov["profile"].get("REGULUS_MLX_REVISION")
facts = {
    "run_id": "holdout100_20261022",
    "run_window": f"{start:%Y-%m-%d %H:%M} → {end:%H:%M} IST (local)",
    "wall_seconds": round((end - start).total_seconds(), 3),
    "timeout_s": None,
    "bank_file": "Regulus_QBank_Cosmetics_REV01.xlsx",
    "base_model_short": "Qwen3-4B-Instruct-2507 (MLX 4-bit)",
    "base_model_cell": f"mlx-community/Qwen3-4B-Instruct-2507-4bit (rev {str(rev)[:8]})",
    "embedding_model_cell": "BAAI/bge-small-en-v1.5 (dense section candidates for promotion)",
    "baseline_label": "1.7B, 22 Oct (different 100 questions)",
    "new_label": "4B-2507 holdout, 22 Oct",
    "comparison_note": "Not the same questions as the earlier runs: this is the frozen holdout (100 of the 177 questions never used in development).",
    "model_config_lines": [
        ["Base language model", f"Qwen3-4B-Instruct-2507, MLX 4-bit (mlx-community/Qwen3-4B-Instruct-2507-4bit revision {rev}); no adapter; thinking off."],
        ["Provider / runtime", "Local MLX worker on the Apple GPU through scripts/run_cosmetics_eval.py (the production RagPipeline without the web UI). No external API."],
        ["Decoding", f"Greedy; repetition penalty {prov['profile'].get('REGULUS_REPETITION_PENALTY', '1.0')}; the pipeline's adaptive token allowance."],
        ["Retrieval / index", "Lexical PostgreSQL retrieval over the read-only database (eCFR snapshot 2026-09-03, 65,408 rows after the 22 Oct source-text repair) plus FDA guidance; section promotion with the LLM picker over lexical + dense candidates; FD&C Act statute corpus (govinfo USCODE-2024, 528 paragraphs); deterministic color-listing composer; answer style apply."],
        ["Deployment scope", prov["profile"].get("REGULUS_DEPLOYMENT_SCOPE", "")],
        ["Evaluator", "Question-bank rubric against the verified key, scored blind by two independent AI scorers (a plain and a skeptical lens) with a third adjudicating where they disagreed on PASS; the recorded verdict is the stricter scorer's. AI-assisted, not SME-signed. The Regulus live evaluator was not run in this offline runner (its columns are blank)."],
    ],
    "metadata_lines": [
        ["Holdout", "100 questions drawn (seed 20261022) from the 177 bank questions never used in development; frozen before any result (selection.json sha256 " + prov["selection_sha256"][:12] + "…)."],
        ["Code", f"git {prov['git_head'][:7]} + uncommitted working tree (diff sha256 {prov['uncommitted_diff_sha256'][:12]}…); per-file sha256 in run_provenance.json."],
        ["Database", json.dumps(prov.get("db_fingerprint_after_repair_step2", {}).get("ecfr", {}))],
        ["Run directory", "artifacts/cosmetics_benchmark/holdout100_20261022/ (answers.jsonl, run.log, run_provenance.json, wb_run/)"],
    ],
}
Path(sys.argv[2]).write_text(json.dumps(facts, indent=1, ensure_ascii=False))
print(json.dumps({k: facts[k] for k in ("run_window", "wall_seconds", "base_model_cell")}))
