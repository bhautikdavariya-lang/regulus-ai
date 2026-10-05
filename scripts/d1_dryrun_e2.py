"""D1-E2 pre-registration: evidence composition for arms 3 and 4, with NO model call.

    .venv/bin/python scripts/d1_dryrun_e2.py --arm 3
    .venv/bin/python scripts/d1_dryrun_e2.py --arm 4

The pipeline is run end to end with a stub generator, so the whole production selection path executes
- coverage, select_evidence, the Stage 6 `required_only` narrowing, and Stage 8 `consolidate_evidence`
- and the recorded composition is what the real arm will put in front of the model. This is the
mistake the arm 2 pre-registration made: it called select_evidence directly, skipped required_only and
consolidate_evidence, and overstated source counts (predicted 9 for M-013, measured 6).

The benchmark key is read only AFTER composition, to measure presence, rank and paragraph coverage.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


class StubResult:
    response = ""
    generated_tokens = 0
    prompt_tokens = 0
    finished = True
    stop_reason = "stub"
    seconds = 0.0
    first_token_seconds = 0.0
    tokens_per_second = 0.0
    decode_tokens_per_second = None


class StubGenerator:
    """Runs the pipeline's retrieval, selection and prompt assembly, then returns nothing."""

    def __init__(self, inner):
        self.inner = inner
        self.model, self.tokenizer = inner.model, inner.tokenizer

    def generate(self, messages, max_new_tokens=None, on_text=None):
        return StubResult()

    def describe(self):
        return self.inner.describe()

    def __getattr__(self, name):
        return getattr(self.inner, name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["0", "2", "3", "4"])
    ap.add_argument("--set", default=str(ROOT / "artifacts/diagnostics/model_probe/probe_set.json"))
    ap.add_argument("--ids", default=None, help="comma-separated subset")
    ap.add_argument("--out", default=str(ROOT / "artifacts/diagnostics/d1_experiment"))
    args = ap.parse_args()

    import d1_experiment as D

    patches = []
    if args.arm == "2":
        patches.append(D.install_k1()); patches.append(D.install_ceiling())
    if args.arm == "3":
        patches.append(D.install_ceiling_for(D.PART_HARD_MAX_RESULTS, D.PART_HARD_MAX_CHARS, "breadth"))
    if args.arm == "4":
        patches.append(D.install_full_sections())
        patches.append(D.install_section_contiguous_order())
        patches.append(D.install_ceiling_for(D.FULL_HARD_MAX_RESULTS, D.PART_HARD_MAX_CHARS, "depth"))
    for p in patches:
        print(p)

    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_generation_config, configured_rag_config

    probe = json.loads(Path(args.set).read_text(encoding="utf-8"))
    if args.ids:
        want = [x.strip() for x in args.ids.split(",") if x.strip()]
        by = {it["id"]: it for it in probe}
        probe = [by[x] for x in want]
    bench = {q.question_id: q for q in load_acceptance_benchmark()}
    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    base = load_generator(settings, local_files_only=True)
    db = Database.from_env(); db.connect()
    cfg = configured_rag_config(settings)
    retriever, scope = build_retriever(db, cfg)
    pipe = RagPipeline(retriever, StubGenerator(base), cfg, scope_policy=scope)

    rows = []
    for i, item in enumerate(probe, start=1):
        qid = item["id"]; q = bench[qid]
        plan = plan_query(q.question)
        part_level = bool(plan.requirements) and all(r.reference.section is None for r in plan.requirements)
        t0 = time.perf_counter()
        outp = pipe.answer(q.question)
        srcs = list(outp.context.sources)
        secs = [s.result.metadata.get("section") for s in srcs]
        keyed = item.get("key_sections") or []            # measurement only, after composition
        rank = next((n for n, s in enumerate(secs, start=1) if s in keyed), None)
        paras = {}
        for ks in keyed:
            total = db.query("select count(*) n from cfr_records where section_number=%s", (ks,))
            paras[ks] = {"paragraphs_in_prompt": sum(1 for s in secs if s == ks),
                         "paragraphs_in_section": int(total[0]["n"]) if total else 0}
        rows.append({
            "arm": args.arm, "id": qid, "type": q.question_type, "part_level_plan": part_level,
            "keyed_sections": keyed, "keyed_present": bool(rank), "keyed_rank": rank,
            "n_sources": len(srcs), "n_distinct_sections": len({s for s in secs if s}),
            "evidence_chars": sum(len(s.text) for s in srcs),
            "keyed_paragraph_coverage": paras, "sections": secs,
            "seconds": round(time.perf_counter() - t0, 2),
        })
        print(f"{i:3}/{len(probe)} arm{args.arm} {qid:8} part_level={str(part_level):5} "
              f"src={len(srcs):4} distinct_secs={rows[-1]['n_distinct_sections']:3} "
              f"chars={rows[-1]['evidence_chars']:6} keyed_rank={str(rank):5} "
              f"keyed_paras={sum(v['paragraphs_in_prompt'] for v in paras.values()):3}"
              f"/{sum(v['paragraphs_in_section'] for v in paras.values()):3}", flush=True)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / f"dryrun_arm{args.arm}.json").write_text(
        json.dumps({"arm": args.arm, "patches": patches, "rows": rows}, indent=1, default=str), encoding="utf-8")
    print("wrote", out / f"dryrun_arm{args.arm}.json")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
