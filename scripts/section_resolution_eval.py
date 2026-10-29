"""Section-resolution benchmark (regulus.evaluation.section_resolution).

    python scripts/section_resolution_eval.py build --bank BANK.json --dev-ids DEV.json --sealed-ids SEALED.json \
        [--gen GEN_DIR --verify VERIFY_DIR] [--out data/evaluation/datasets/section_resolution_v1.jsonl]
    python scripts/section_resolution_eval.py run --split dev|synthetic|sealed [--unseal] [--mode production|candidates] \
        [--promotion picker|lexical|resolver] [--mlx] --out RUN_DIR [--ids IDS.json]
    python scripts/section_resolution_eval.py compare RUN_A RUN_B [--metric hit|primary|cover]

The database is only read: every statement that is not SELECT/WITH is refused, and the regulatory tables' write
counters are recorded before and after a run. The sealed split (bank questions never run) is scored only with
--unseal. --mlx loads the configured MLX model (REGULUS_MLX_* profile) for the picker; nothing else is generated.
A run is resumable: rows already in RUN_DIR/rows.jsonl are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.evaluation import section_resolution as SR  # noqa: E402

DEFAULT_DATASET = ROOT / "data" / "evaluation" / "datasets" / "section_resolution_v1.jsonl"
STATUTE_STORE = ROOT / "data" / "processed" / "statute_fdca" / "rows.jsonl"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _statute_maps() -> tuple[dict[str, str], set[str]]:
    rows = [json.loads(line) for line in STATUTE_STORE.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["usc_section"].lower(): r["fdca_section"] for r in rows}, {r["fdca_section"] for r in rows}


def _in_scope(statute: set[str]):
    from regulus.retrieval.section_index import COSMETIC_PARTS

    return lambda s: bool(s) and (s in statute or ("." in s and s.split(".")[0] in COSMETIC_PARTS))


def cmd_build(a) -> None:
    usc, statute = _statute_maps()
    in_scope = _in_scope(statute)
    bank = json.loads(Path(a.bank).read_text())
    rows = SR.bank_rows(bank, json.loads(Path(a.dev_ids).read_text()), json.loads(Path(a.sealed_ids).read_text()), usc, in_scope)
    stats = {}
    if a.gen:
        reinstate = json.loads(Path(a.overrides).read_text())["reinstate"] if a.overrides else ()
        syn, stats = SR.synthetic_rows(Path(a.gen), Path(a.verify), in_scope, reinstate)
        rows += syn
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    from collections import Counter

    print(json.dumps({"rows": len(rows), "splits": Counter(r["split"] for r in rows), "synthetic": stats,
                      "no_primary": [r["id"] for r in rows if not r["primary"]], "sha256": _sha(out)}, indent=1, default=str))


def _read_only(db_cls) -> None:
    query = db_cls.query

    def guarded(self, sql, params=None, *args, **kw):
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if head not in ("SELECT", "WITH"):
            raise RuntimeError(f"read-only harness: refused a {head} statement")
        return query(self, sql, params, *args, **kw)

    db_cls.query = guarded


def _mlx_generator():
    from regulus.config import load_settings
    from regulus.model import load_tokenizer
    from regulus.rag.mlx_generator import MlxGenerator
    from regulus.rag.mlx_models import SUPPORTED_MLX_MODELS, identify_mlx_model
    from regulus.system_identity import configured_generation_config

    s = load_settings()
    path = Path(os.environ["REGULUS_MLX_MODEL_PATH"])
    key = identify_mlx_model(json.loads((path / "config.json").read_text()))
    return MlxGenerator(load_tokenizer(s.model, local_files_only=True), configured_generation_config(s),
                        model_id=SUPPORTED_MLX_MODELS[key]["model_id"], model_path=path, python=os.environ["REGULUS_MLX_PYTHON"],
                        revision=os.environ.get("REGULUS_MLX_REVISION"))


# the reply cache lives in the package (regulus.evaluation.reply_cache); imported here for the harnesses that use it
from regulus.evaluation.reply_cache import CachedGenerator  # noqa: E402,F401


PICKER_CACHE = Path.home() / "regulus_eval_runs" / "section_resolution_20261023" / "picker_cache.jsonl"


def cmd_run(a) -> None:
    from regulus.evaluation import retrieval_baseline as RB
    from regulus.retrieval.db import Database

    dataset = Path(a.dataset)
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if a.split == "sealed" and not a.unseal:
        sys.exit("the sealed split is scored only with --unseal (once, for the final honest test)")
    rows = [r for r in rows if r["split"] == a.split]
    if a.ids:
        keep = set(json.loads(Path(a.ids).read_text()))
        rows = [r for r in rows if r["id"] in keep]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["id"] for line in (out / "rows.jsonl").read_text().splitlines() if line.strip()} \
        if (out / "rows.jsonl").exists() else set()
    _read_only(Database)
    db = Database.from_env()
    db.connect()
    fp0 = RB.database_fingerprint(db)
    pipe, _ = RB.production_pipeline(db)
    if a.promotion:
        pipe.config = replace(pipe.config, section_promotion=a.promotion)
    if a.mlx:
        pipe.generator = CachedGenerator(_mlx_generator(), Path(a.cache))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(["git", "diff", "HEAD"], cwd=ROOT, capture_output=True).stdout
    prov = {"dataset": str(dataset), "dataset_sha256": _sha(dataset), "split": a.split, "mode": a.mode,
            "promotion": pipe.config.section_promotion, "mlx": bool(a.mlx), "git_head": head,
            "uncommitted_diff_sha256": hashlib.sha256(diff).hexdigest(), "rows": len(rows),
            "env": {k: v for k, v in os.environ.items() if k.startswith("REGULUS_") and "URL" not in k and "PASS" not in k},
            "db_fingerprint_before": fp0}
    t0 = time.perf_counter()
    with (out / "rows.jsonl").open("a", encoding="utf-8") as f:
        for n, r in enumerate([r for r in rows if r["id"] not in done], 1):
            res = SR.resolve_row(pipe, r["question"], mode=a.mode)
            f.write(json.dumps(SR.score_row(r, res), ensure_ascii=False, default=str) + "\n")
            f.flush()
            if n % 25 == 0:
                print(f"{n} rows, {time.perf_counter() - t0:.0f} s", flush=True)
    scored = [json.loads(line) for line in (out / "rows.jsonl").read_text().splitlines() if line.strip()]
    prov["db_fingerprint_after"] = RB.database_fingerprint(db)
    prov["db_unchanged"] = prov["db_fingerprint_before"] == prov["db_fingerprint_after"]
    prov["seconds"] = round(time.perf_counter() - t0, 1)
    if a.mlx:
        prov["picker_calls"] = {"fresh": pipe.generator.fresh, "cached": pipe.generator.cached, "cache": str(a.cache)}
    summary = SR.summarize(rows, scored)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    (out / "provenance.json").write_text(json.dumps(prov, indent=1, default=str))
    for k, v in summary.items():
        if k.startswith(("all:", "corpus:", "names_part:")):
            print(f"{k:28s} n={v['n']:4d} hit={v['hit']:>8s} primary={v['primary']:>8s} cover={v['cover']:>8s} "
                  f"cand@1={v['cand@1']:>8s} cand@any={v['cand@any']:>8s} act@1={v['act@1']:>7s} act@3={v['act@3']:>7s} promoted/q={v['mean_promoted']}")
    print("db unchanged:", prov["db_unchanged"])


def cmd_compare(a) -> None:
    load = lambda d: [json.loads(line) for line in (Path(d) / "rows.jsonl").read_text().splitlines() if line.strip()]
    print(json.dumps(SR.compare(load(a.a), load(a.b), a.metric), indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--bank", required=True)
    b.add_argument("--dev-ids", required=True)
    b.add_argument("--sealed-ids", required=True)
    b.add_argument("--gen")
    b.add_argument("--verify")
    b.add_argument("--overrides", help="JSON {reinstate: [qid, ...], reason}")
    b.add_argument("--out", default=str(DEFAULT_DATASET))
    r = sub.add_parser("run")
    r.add_argument("--dataset", default=str(DEFAULT_DATASET))
    r.add_argument("--split", required=True, choices=["dev", "synthetic", "sealed"])
    r.add_argument("--unseal", action="store_true")
    r.add_argument("--mode", default="production", choices=["production", "candidates"])
    r.add_argument("--promotion", choices=["picker", "lexical", "resolver"])
    r.add_argument("--mlx", action="store_true")
    r.add_argument("--cache", default=str(PICKER_CACHE), help="greedy reply cache for --mlx")
    r.add_argument("--ids")
    r.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--metric", default="hit", choices=["hit", "primary", "cover"])
    a = p.parse_args()
    {"build": cmd_build, "run": cmd_run, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
