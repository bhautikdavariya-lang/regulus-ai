"""Out-of-scope safety probe: base Qwen3-0.6B vs the SFT v2 adapter, one variable.

    .venv/bin/python scripts/sft2_safety_probe.py [--limit N] [--arm base|sft2_v1]

Diagnostic only, and no benchmark row is touched: the questions live in
artifacts/sft2/safety_probe/questions.json and none appears in the 300 acceptance questions or the
152 SFT v2 training examples (verified before the run).

Both arms go through the SAME construction the acceptance runner uses - load_settings,
configured_generation_config, load_generator, Database.from_env, configured_rag_config,
build_retriever, RagPipeline - so retrieval, the production system prompt, context construction,
decoding and post-processing are identical. The ONLY difference is REGULUS_ADAPTER. Production
max_new_tokens applies: the pipeline's own per-question allowance, ceiling 2048. Nothing is capped.

Writes artifacts/sft2/safety_probe/responses_<arm>.jsonl and metadata_<arm>.json. Existing
acceptance-test artifacts are never written.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "artifacts" / "sft2" / "safety_probe"
ADAPTER = "models/qwen3-0.6b-lora/sft2_v1/adapter"


def build_pipeline():
    """Exactly the acceptance runner's construction, re-reading settings from the environment."""
    from regulus.config import load_settings
    from regulus.rag import RagPipeline
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config

    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    generator = load_generator(settings, local_files_only=True)
    db = Database.from_env()
    db.connect()
    config = configured_rag_config(settings)
    retriever, scope = build_retriever(db, config)
    return settings, config, retriever, generator, RagPipeline(retriever, generator, config, scope_policy=scope)


def record(q: dict, out, seconds: float) -> dict:
    m = out.metadata
    val = m.get("validation") or {}
    return {
        "id": q["id"], "framework": q["framework"], "subtype": q["subtype"],
        "discriminating": q["discriminating"], "question": q["question"], "exists": q["exists"],
        "execution_status": "OK", "seconds": round(seconds, 2),
        "answer": out.answer, "raw_model_output": m.get("raw_model_output"),
        "model_called": out.model_called, "no_context": out.no_context,
        "citations": [{"index": c.index, "label": c.label} for c in out.citations],
        "evidence": [s.result.citation.label for s in out.context.sources],
        "answerability": (m.get("answerability") or {}).get("state"),
        "scope": m.get("scope"), "fallback_type": m.get("fallback_type"),
        "validation_final": (val.get("final") or {}).get("status"),
        "output_tokens": out.output_tokens,
    }


def run_arm(arm: str, questions: list[dict]) -> None:
    if arm == "base":
        os.environ.pop("REGULUS_ADAPTER", None)
    else:
        os.environ["REGULUS_ADAPTER"] = ADAPTER
    from run_diagnostics import reproducibility

    settings, config, retriever, generator, pipeline = build_pipeline()
    adapter = str(settings.model.adapter) if settings.model.adapter else None
    print(f"\n=== arm {arm} | adapter={adapter} ===", flush=True)
    assert (adapter is None) == (arm == "base"), f"arm/adapter mismatch: {arm} {adapter}"

    (OUT / f"metadata_{arm}.json").write_text(json.dumps({
        "arm": arm, "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active_model": {"model_id": settings.model.id, "adapter": adapter,
                         "backend": settings.model.backend},
        "reproducibility": reproducibility(settings, config, retriever, generator.describe()),
        "hardware": {"platform": platform.platform(), "machine": platform.machine(),
                     "python": platform.python_version()},
        "command": "python " + " ".join(sys.argv),
        "protocol": "one stateless RagPipeline.answer call per question; production allowance; no retries",
    }, indent=1, default=str), encoding="utf-8")

    path = OUT / f"responses_{arm}.jsonl"
    t_start = time.perf_counter()
    with path.open("w", encoding="utf-8") as f:
        for n, q in enumerate(questions, start=1):
            t0 = time.perf_counter()
            try:
                row = record(q, pipeline.answer(q["question"]), time.perf_counter() - t0)
            except Exception as exc:
                row = {"id": q["id"], "question": q["question"], "execution_status": "ERROR",
                       "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.perf_counter() - t0, 2)}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  [{n:2}/{len(questions)}] {q['id']:7} {row['seconds']:6.1f}s "
                  f"tok={row.get('output_tokens')} -> {(row.get('answer') or row.get('error') or '')[:90]!r}",
                  flush=True)
    print(f"  arm {arm} done in {(time.perf_counter()-t_start)/60:.1f} min -> {path}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="first N questions only (timing trial)")
    ap.add_argument("--arm", choices=["base", "sft2_v1"], default=None, help="one arm only")
    args = ap.parse_args()
    questions = json.loads((OUT / "questions.json").read_text())["questions"]
    if args.limit:
        questions = questions[: args.limit]
    for arm in ([args.arm] if args.arm else ["base", "sft2_v1"]):
        run_arm(arm, questions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
