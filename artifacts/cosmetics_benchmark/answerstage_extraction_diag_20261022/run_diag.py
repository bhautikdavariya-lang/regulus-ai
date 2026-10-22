"""Offline diagnostic: per-part evidence extraction with the production 1.7B MLX model (see PREREGISTRATION.md).

    REGULUS_MLX_PYTHON=... REGULUS_MLX_MODEL_PATH=... python run_diag.py

Reads the 22 Oct run's saved prompt sources; writes outputs.jsonl here. Changes nothing in the application.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
RUN = ROOT / "artifacts/cosmetics_benchmark/cosmetics100_q17_20261022T035901Z"

from regulus.config import load_settings  # noqa: E402
from regulus.model import load_tokenizer  # noqa: E402
from regulus.rag.mlx_generator import MlxGenerator, memory_preflight  # noqa: E402
from regulus.system_identity import configured_generation_config  # noqa: E402

SYSTEM = ("You copy regulatory text. Use only the numbered SOURCES the user gives you. Copy sentences exactly as "
          "written. Never add facts, numbers or requirements that are not in a source.")


def prompt(question: str, sources: list[dict]) -> str:
    src = "\n\n".join(f"[{s['index']}] {s['citation']}\n{s['text']}" for s in sources)
    return (f"QUESTION: {question}\n\nSOURCES:\n{src}\n\n"
            "TASK: Split the question into its separate parts. For each part, write a line starting with PART: that "
            "restates the part, then a line starting with EVIDENCE: that copies, in quotation marks, the one sentence "
            "from a source that answers that part, followed by its source number in brackets. If no source sentence "
            "answers that part, write EVIDENCE: NOT IN SOURCES.")


def main() -> int:
    s = load_settings()
    gen = configured_generation_config(s)
    pre = memory_preflight(1200)
    tok = load_tokenizer(s.model, local_files_only=True)
    m = MlxGenerator(tok, gen, model_id="Qwen/Qwen3-1.7B", model_path=os.environ["REGULUS_MLX_MODEL_PATH"],
                     python=os.environ["REGULUS_MLX_PYTHON"], revision="21457c6f51ed54a7c16e988c0844db973815c137")
    sel = json.loads((HERE / "diag_set.json").read_text())
    qs = {q["ID"]: q for q in json.loads((RUN / "selection.json").read_text())["questions"]}
    out = (HERE / "outputs.jsonl").open("w", encoding="utf-8")
    try:
        for group, ids in sel.items():
            for qid in ids:
                resp = json.loads((RUN / "responses" / f"{qid}.json").read_text())
                p = prompt(qs[qid]["Question (ask verbatim)"], resp["sources"])
                t0 = time.perf_counter()
                r = m.generate([{"role": "system", "content": SYSTEM}, {"role": "user", "content": p}], max_new_tokens=512)
                out.write(json.dumps({"id": qid, "group": group, "output": r.response, "prompt_tokens": r.prompt_tokens,
                                      "generated_tokens": r.generated_tokens, "seconds": round(time.perf_counter() - t0, 2),
                                      "prompt": p}, ensure_ascii=False) + "\n")
                out.flush()
                print(group, qid, r.generated_tokens, flush=True)
    finally:
        out.close()
        m.close()
    (HERE / "run_meta.json").write_text(json.dumps({"preflight": pre, "model": m.describe(), "decoding": str(gen)}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
