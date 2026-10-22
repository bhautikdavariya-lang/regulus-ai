"""Answer cosmetics-bank questions through the production pipeline with the MLX model, offline (no UI, no scoring).

    set -a; source ~/regulus_eval_runs/q17_feasibility/qwen3_4b_2507_mlx_4bit.env; set +a
    .venv/bin/python scripts/run_cosmetics_eval.py --selection artifacts/cosmetics_benchmark/holdout100_20261022/selection.json \
        --out artifacts/cosmetics_benchmark/holdout100_20261022/answers.jsonl

--selection: a selection.json (summary.selected_ids) or a .json list of {"id": ...}; --bank: the question bank workbook.
The output file is appended to and questions already in it are skipped, so an interrupted run resumes with the same
command. Each line: id, question asked, delivered answer, fallback type, promotion, sources, validation, timings.
The database is opened read-only by the caller's configuration; nothing is written to it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def read_bank(path: Path, sheet: str = "Questions") -> dict[str, dict]:
    """The bank's Questions sheet with the standard library (no openpyxl), keyed by ID."""
    z = zipfile.ZipFile(path)
    ss = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
          for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid = [s for s in wb.find("m:sheets", NS) if s.get("name") == sheet][0].get(f"{{{NS['r']}}}id")
    target = [r for r in rels if r.get("Id") == rid][0].get("Target").lstrip("/")
    target = target if target.startswith("xl/") else "xl/" + target
    rows = []
    for row in ET.fromstring(z.read(target)).iter(f"{{{NS['m']}}}row"):
        vals = {}
        for c in row.findall("m:c", NS):
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            idx = 0
            for ch in col:
                idx = idx * 26 + ord(ch) - 64
            v = c.find("m:v", NS)
            vals[idx - 1] = (ss[int(v.text)] if c.get("t") == "s" else (v.text if v is not None else None))
        rows.append([vals.get(i) for i in range(max(vals) + 1)] if vals else [])
    hdr = rows[0]
    return {r[0]: dict(zip(hdr, r + [None] * (len(hdr) - len(r)))) for r in rows[1:] if r and r[0]}


def _replay(pipe, question: str, recorded) -> None:
    """Make the pipeline's promoter return the promotion an earlier run recorded for this question (or none)."""
    from regulus.rag.section_promotion import Promotion

    promoter = pipe.section_promoter()
    if promoter is None:
        return

    def resolve(q, parts=None, named_only=False):
        if not recorded or recorded.get("error"):
            return None
        if recorded.get("statute"):
            from dataclasses import replace as _replace

            lex = promoter.index.question_lexemes(promoter.db, q)
            named = dict(promoter.named_statute(q, lex))
            pr = promoter._statute_promotion([(s, named.get(s, "")) for s in recorded["statute"]], lex, "replay", time.perf_counter())
            if recorded.get("sections"):   # a co-promotion: the regulation(s) as well
                pr = _replace(pr, sections=tuple(recorded["sections"]), companions=tuple(recorded.get("companions") or ()))
            return pr
        return Promotion(sections=tuple(recorded.get("sections") or ()), companions=tuple(recorded.get("companions") or ()),
                         method="replay") if recorded.get("sections") else None

    promoter.resolve = resolve


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bank", default=str(ROOT / "Regulus_QBank_Cosmetics_REV01.xlsx"))
    ap.add_argument("--replay-promotions", help="answers.jsonl of an earlier run: reuse its section promotions, so a "
                                                "model comparison measures the answers only")
    a = ap.parse_args()
    sel = json.loads(Path(a.selection).read_text(encoding="utf-8"))
    ids = sel["summary"]["selected_ids"] if isinstance(sel, dict) else [x["id"] for x in sel]
    bank = read_bank(Path(a.bank))
    # a selection may carry its own question texts (e.g. rows of the 300-question acceptance benchmark)
    if isinstance(sel, dict):
        for q in sel.get("questions") or []:
            qid, text = q.get("ID") or q.get("question_id"), q.get("Question (ask verbatim)") or q.get("question")
            if qid and text:
                bank.setdefault(qid, {"Question (ask verbatim)": text})
    out = Path(a.out)
    # answered questions are skipped; a question that failed (e.g. a database timeout) is retried by re-running
    done = ({r["id"] for r in (json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip())
             if not r.get("error")} if out.exists() else set())
    todo = [i for i in ids if i not in done]
    print(f"{len(ids)} selected, {len(done)} already answered, {len(todo)} to go", flush=True)
    if not todo:
        return 0

    from regulus.config import load_settings
    from regulus.evaluation import retrieval_baseline as RB
    from regulus.model import load_tokenizer
    from regulus.rag.mlx_generator import MlxGenerator, memory_preflight
    from regulus.retrieval import Database
    from regulus.system_identity import configured_generation_config

    s = load_settings()
    print("memory", memory_preflight(s.model.mlx_min_available_mb), flush=True)
    tok = load_tokenizer(s.model, local_files_only=True)
    from regulus.rag.mlx_models import EXPECTED_BITS, SUPPORTED_MLX_MODELS, identify_mlx_model, opens_reasoning

    path = Path(os.environ["REGULUS_MLX_MODEL_PATH"])
    cfg = json.loads((path / "config.json").read_text())
    key = identify_mlx_model(cfg)
    if key is None or (cfg.get("quantization") or {}).get("bits") != EXPECTED_BITS:
        raise SystemExit(f"{path} is not a supported model ({', '.join(SUPPORTED_MLX_MODELS)}) quantized to {EXPECTED_BITS} bits")
    gen = MlxGenerator(tok, configured_generation_config(s), model_id=SUPPORTED_MLX_MODELS[key]["model_id"], model_path=path,
                       python=os.environ["REGULUS_MLX_PYTHON"], revision=os.environ.get("REGULUS_MLX_REVISION"))
    if opens_reasoning(gen.generation_prefix()):
        from regulus.rag.mlx_models import THINKING_MLX_MODELS, thinking_allowed

        if not (thinking_allowed() and key in THINKING_MLX_MODELS):
            gen.close()
            raise SystemExit(f"{path}: the chat template opens a reasoning block - a thinking model needs REGULUS_ALLOW_THINKING=1")
        gen.model_id = THINKING_MLX_MODELS[key]["model_id"]
    db = Database.from_env()
    db.connect()
    t_all = time.perf_counter()
    try:
        pipe, _ = RB.production_pipeline(db)
        pipe.generator = gen
        replay = {}
        if a.replay_promotions:
            for line in Path(a.replay_promotions).read_text(encoding="utf-8").splitlines():
                rec = json.loads(line) if line.strip() else {}
                if rec.get("id") and not rec.get("error"):
                    replay[rec["id"]] = rec.get("promotion")
        with out.open("a", encoding="utf-8") as f:
            for n, qid in enumerate(todo, 1):
                q = bank[qid]["Question (ask verbatim)"]
                t0 = time.perf_counter()
                if a.replay_promotions:
                    _replay(pipe, q, replay.get(qid))
                try:
                    r = pipe.answer(q)
                except Exception as exc:  # noqa: BLE001 - one failed question must not end the run
                    f.write(json.dumps({"id": qid, "asked": q, "error": f"{type(exc).__name__}: {exc}"[:500]}) + "\n")
                    f.flush()
                    print(f"[{n}/{len(todo)}] {qid} ERROR {type(exc).__name__} (re-run the command to retry)", flush=True)
                    continue
                md = r.metadata
                f.write(json.dumps({
                    "id": qid, "asked": q, "answer": r.answer, "fallback_type": md.get("fallback_type"),
                    "promotion": md.get("section_promotion"),
                    "sources": [[x.result.citation.label, x.tier, len(x.text or "")] for x in r.context.sources],
                    "validation": md.get("validation"), "generation": md.get("generation"),
                    "raw": md.get("raw_model_output"), "seconds": round(time.perf_counter() - t0, 1),
                    "model": gen.describe(),
                }, ensure_ascii=False, default=str) + "\n")
                f.flush()
                left = (time.perf_counter() - t_all) / n * (len(todo) - n)
                print(f"[{n}/{len(todo)}] {qid} {md.get('fallback_type') or 'answer'} {time.perf_counter() - t0:.0f}s"
                      f"  ~{left / 60:.0f} min left", flush=True)
    finally:
        db.close()
        gen.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
