"""Retrieval-only baseline over a frozen gold set (regulus.evaluation.retrieval_baseline). No model, no external API.

    python scripts/retrieval_baseline.py build-dataset                 # writes data/evaluation/datasets/retrieval_baseline_v1.jsonl
    python scripts/retrieval_baseline.py run                           # one baseline run -> data/evaluation/results/<run>/
    python scripts/retrieval_baseline.py run --ids S-007 D-016         # a subset
    python scripts/retrieval_baseline.py compare <run_a> <run_b>       # determinism: identical records apart from timings

`run` executes the production answering pipeline (scripts/serve_ui.py's default request: configured_rag_config,
the factory retriever with scope policy and semantic fallback, top_k 8, grounding off) with a generator stub, so
the model is never loaded. It reads the database only, inside the server-enforced read-only session of
regulus.retrieval.db, and records the database's identity and write counters before and after.

Outputs (data/evaluation/results/ is gitignored): per_question.jsonl, summary.json, provenance.json, REPORT.md.
Gold keys are developer-keyed or draft, NOT SME-verified; REPORT.md says so and lists the open key questions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402

RESULTS_DIR = ROOT / "data" / "evaluation" / "results"
CODE_GLOBS = ("src/regulus/**/*.py", "scripts/serve_ui.py", "scripts/retrieval_baseline.py", "configs/model.yaml",
              "data/evaluation/semantic/semantic_expanded_v1/manifest.yaml")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def code_identity() -> dict:
    """SHA-256 of every file the run depends on (the working tree, committed or not), and git HEAD."""
    files = sorted({p for g in CODE_GLOBS for p in ROOT.glob(g) if p.is_file() and "__pycache__" not in p.parts})
    per_file = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    combined = hashlib.sha256("\n".join(f"{k} {v}" for k, v in per_file.items()).encode()).hexdigest()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"git_head": head, "files": len(per_file), "combined_sha256": combined, "per_file_sha256": per_file}


def cmd_build_dataset(args) -> int:
    out = Path(args.out)
    if out.exists():
        print(f"refusing to overwrite {out}; the gold set is frozen (write a new version instead)", file=sys.stderr)
        return 2
    rows = RB.build_dataset()
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    kinds = {"retrieval_v2": sum(r["source"] == RB.SOURCE_V2 for r in rows),
             "benchmark": sum(r["source"] == RB.SOURCE_BENCHMARK for r in rows),
             "negative_controls": sum(r["is_negative_control"] for r in rows),
             "no_cfr_key": sum(r["key_status"] == RB.KEY_NONE for r in rows),
             "audit_failure_cases": sum(r["audit_failure_case"] for r in rows),
             "sme_verified": sum(bool(r["sme_verified"]) for r in rows)}
    print(f"wrote {out} rows={len(rows)} sha256={sha} {kinds}")
    return 0


def cmd_run(args) -> int:
    from regulus.retrieval.db import Database

    rows = RB.load_dataset(Path(args.dataset))
    if args.ids:
        wanted = set(args.ids)
        rows = [r for r in rows if r["id"] in wanted]
        missing = wanted - {r["id"] for r in rows}
        if missing:
            print(f"unknown ids: {sorted(missing)}", file=sys.stderr)
            return 2
    run_id = f"retrieval_baseline_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    out_dir = Path(args.out_dir) if args.out_dir else RESULTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=False)   # never overwrite an earlier run

    db = Database.from_env()
    db.connect()
    try:
        started = _now()
        fp_before = RB.database_fingerprint(db)
        pipe, generator = RB.production_pipeline(db, semantic=args.semantic, general_evidence_order=args.general_evidence_order,
                                                 min_trigram_similarity=args.min_trigram_similarity)
        lookup = RB.CorpusLookup(db)
        records = []
        with (out_dir / "per_question.jsonl").open("w", encoding="utf-8") as f:
            for n, row in enumerate(rows, start=1):
                rec = RB.run_question(pipe, generator, lookup, row)
                records.append(rec)
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                if n % 25 == 0 or n == len(rows):
                    print(f"  {n}/{len(rows)}", flush=True)
        fp_after = RB.database_fingerprint(db)
        finished = _now()
    finally:
        db.close()

    summary = RB.summarise(records)
    summary["canonical_sha256"] = RB.canonical_sha256(records)
    summary["generation_requests_answered_by_stub"] = generator.calls
    db_unchanged = (fp_before["corpus_identity"]["ecfr"] == fp_after["corpus_identity"]["ecfr"]
                    and fp_before["corpus_identity"]["guidance"] == fp_after["corpus_identity"]["guidance"]
                    and fp_before["row_counts"] == fp_after["row_counts"]
                    and fp_before["write_counters"] == fp_after["write_counters"])
    config = pipe.config   # what actually ran, the experimental switch included
    import psycopg
    import torch
    import transformers
    provenance = {
        "run_id": run_id, "started_utc": started, "finished_utc": finished,
        "dataset": {"path": str(Path(args.dataset).resolve().relative_to(ROOT)) if Path(args.dataset).resolve().is_relative_to(ROOT) else args.dataset,
                    "sha256": hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest(), "rows_run": len(rows),
                    "ids_filter": args.ids or None},
        "pipeline": {"semantic_mode": args.semantic, "top_k": 8, "grounding": "off", "generator": generator.describe(),
                     "general_evidence_order": config.context.general_evidence_order,
                     "min_trigram_similarity": config.min_trigram_similarity,
                     "rag_config": config.to_dict()},
        "code": code_identity(),
        "database_before": fp_before, "database_after": fp_after, "database_unchanged": db_unchanged,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "torch": torch.__version__, "transformers": transformers.__version__, "psycopg": psycopg.__version__},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=1, default=str), encoding="utf-8")
    (out_dir / "REPORT.md").write_text(render_report(summary, provenance), encoding="utf-8")
    m = summary["metrics"]
    for g in ("identifier", "plain_language"):
        s = m[g]["section_level"]
        if s.get("n"):
            print(f"{g:15s} n={s['n']:3d} candidates={s['any_in_candidates']['count']:3d} context={s['any_in_context']['count']:3d} "
                  f"reaches_prompt={s['any_reaches_prompt']['count']:3d}")
    print(f"database_unchanged={db_unchanged} canonical_sha256={summary['canonical_sha256']} errors={len(summary['errors'])}")
    print(f"out: {out_dir}")
    return 0


def cmd_compare(args) -> int:
    a, b = Path(args.run_a), Path(args.run_b)

    def load(d: Path):
        return [json.loads(l) for l in (d / "per_question.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ra, rb = load(a), load(b)
    ha, hb = RB.canonical_sha256(ra), RB.canonical_sha256(rb)
    da = {r["id"]: json.dumps({k: v for k, v in r.items() if k not in RB.VOLATILE_KEYS}, sort_keys=True, default=str) for r in ra}
    db_ = {r["id"]: json.dumps({k: v for k, v in r.items() if k not in RB.VOLATILE_KEYS}, sort_keys=True, default=str) for r in rb}
    differing = sorted(i for i in set(da) | set(db_) if da.get(i) != db_.get(i))
    print(f"A {ha}\nB {hb}\nidentical={ha == hb} records A={len(ra)} B={len(rb)} differing_ids={differing[:40]}")
    return 0 if ha == hb else 1


# ---------------------------------------------------------------- report

def _pct(x) -> str:
    return f"{x['count']} ({x['rate'] * 100:.1f}%)" if isinstance(x, dict) and "count" in x else "-"


def render_report(summary: dict, prov: dict) -> str:
    m = summary["metrics"]
    L = [f"# Retrieval baseline - {prov['run_id']}", "",
         "Retrieval only: the production pipeline with a generator stub (no model, no external API). "
         "**Gold keys are developer-keyed or draft and NOT SME-verified** "
         f"({summary['sme_verified_rows']} of {summary['dataset_rows']} rows verified): every figure below is a measurement "
         "against those keys, not an accuracy result.", "",
         f"- git HEAD `{prov['code']['git_head'][:12]}` + working tree, code sha256 `{prov['code']['combined_sha256'][:16]}` "
         f"({prov['code']['files']} files)",
         f"- dataset `{prov['dataset']['path']}` sha256 `{prov['dataset']['sha256'][:16]}`, rows run {prov['dataset']['rows_run']}",
         f"- eCFR identity `{prov['database_before']['corpus_identity']['ecfr'].get('sha256', '')[:16]}`, guidance "
         f"`{prov['database_before']['corpus_identity']['guidance'].get('sha256', '')[:16]}`; database unchanged during run: "
         f"**{prov['database_unchanged']}**",
         f"- semantic fallback: {prov['pipeline']['semantic_mode']}; top_k {prov['pipeline']['top_k']}; grounding off; "
         f"general_evidence_order: **{prov['pipeline'].get('general_evidence_order', 'tier')}**; "
         f"min_trigram_similarity: **{prov['pipeline'].get('min_trigram_similarity', 0.4)}**",
         f"- canonical record sha256 `{summary['canonical_sha256']}` (timings excluded)",
         f"- generation requests answered by the stub: {summary['generation_requests_answered_by_stub']}; errors: {len(summary['errors'])}",
         "", "## Question-level baseline (section level: any row of an expected section counts)", "",
         "| Group | n | in candidates | candidate rank <= 8 | in top_k | in context | reaches prompt | retrieved, not in context | median context chars | guidance share |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for g in ("identifier", "identifier/retrieval_v2", "identifier/benchmark_rev02",
              "plain_language", "plain_language/retrieval_v2", "plain_language/benchmark_rev02"):
        s = m[g]["section_level"]
        if not s.get("n"):
            L.append(f"| {g} | 0 | | | | | | | | |")
            continue
        b = s["context_budget"]
        L.append(f"| {g} | {s['n']} | {_pct(s['any_in_candidates'])} | {_pct(s['recall_at_candidate_rank'][8])} | "
                 f"{_pct(s['any_in_topk'])} | {_pct(s['any_in_context'])} | {_pct(s['any_reaches_prompt'])} | "
                 f"{_pct(s['retrieved_but_not_in_context'])} | {b['total_chars_median']} | {b['guidance_share_of_context_chars']} |")
    L += ["", "## Target-level stages (one expected section = one count)", "",
          "| Group | targets | " + " | ".join(RB.STAGES) + " | drop reasons |", "|---|---|" + "---|" * len(RB.STAGES) + "---|"]
    for g in ("identifier", "plain_language"):
        t = m[g]["targets_section_level"]
        L.append(f"| {g} | {t['targets']} | " + " | ".join(str(t['stages'][s]) for s in RB.STAGES) + f" | {t['drop_reasons']} |")
    L += ["", "Provision level (paragraph targets such as 812.3(m) must match the paragraph):", "",
          "| Group | n | in candidates | in context | reaches prompt |", "|---|---|---|---|---|"]
    for g in ("identifier", "plain_language"):
        s = m[g]["provision_level"]
        if s.get("n"):
            L.append(f"| {g} | {s['n']} | {_pct(s['any_in_candidates'])} | {_pct(s['any_in_context'])} | {_pct(s['any_reaches_prompt'])} |")
    L += ["", "## The audit's eight failure cases", "", "| id | key status | target | exists | cand. rank | top_k rank | stage | drop reasons | context chars (guidance) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for c in summary["audit_failure_cases"]:
        if c.get("error"):
            L.append(f"| {c['id']} | error: {c['error']} | | | | | | | |")
            continue
        for label, targets, status in (("key", c["targets"], c["key_status"]), ("alt", c["alternative"], c["alternative_key_status"])):
            for t in targets:
                L.append(f"| {c['id']} ({label}) | {status} | {t['target']} [{t['level']}] | {t['exists_in_db']} | {t['candidate_rank']} | "
                         f"{t['topk_rank']} | {t['stage']} | {', '.join(t['drop_reasons'])} | {c['context_chars']} ({c['guidance_chars']}) |")
    nc = summary["negative_controls"]
    L += ["", "## Negative controls", "",
          f"retrieval_v2 negatives passing retrieval_eval's rule (no exact_cfr result in top_k): "
          f"{nc['retrieval_v2_rule_passed']}/{nc['retrieval_v2_total']}; excluding structural parent rows: "
          f"{nc['retrieval_v2_rule_passed_excluding_parent_rows']}/{nc['retrieval_v2_total']}. Benchmark controls (answer-level "
          f"behaviour; shown descriptively): gate blocked {nc['benchmark_gate_blocked']}/{nc['benchmark_total']}, model would be "
          f"called {nc['benchmark_model_would_be_called']}/{nc['benchmark_total']}. 'Pre-generation fallback' is the pipeline's "
          "own answer when it blocks before the model; when the model would be called, nothing after generation is recorded "
          "(the stub's empty text would make it meaningless).", "",
          "| id | named identifiers (exists in DB) | exact_cfr in top_k (excl. parent rows) | gate | blocked | model called | pre-generation fallback |",
          "|---|---|---|---|---|---|---|"]
    for o in nc["rows"]:
        if o.get("error"):
            L.append(f"| {o['id']} | error: {o['error']} | | | | | |")
            continue
        named = "; ".join(f"{n['target']} ({n.get('exists')})" for n in o["named_identifiers"]) or "-"
        L.append(f"| {o['id']} | {named} | {o['exact_cfr_in_topk']} ({o['exact_cfr_in_topk_excluding_parent_rows']}) | "
                 f"{o['gate_state']} | {o['gate_blocked']} | {o['model_would_be_called']} | {o['pre_generation_fallback'] or '-'} |")
    u = summary["unresolved_gold_keys"]
    L += ["", "## Unresolved gold-key questions (need an SME)", ""]
    for k, items in u.items():
        L.append(f"- **{k}** ({len(items)}): " + (", ".join(i["id"] for i in items) if items else "none"))
    L += ["", f"Rows by kind: {summary['rows_by_kind']}", ""]
    if summary["errors"]:
        L += ["## Errors", ""] + [f"- {e['id']}: {e['error']}" for e in summary["errors"]] + [""]
    return "\n".join(L)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-dataset", help="write the frozen gold set (refuses to overwrite)")
    b.add_argument("--out", default=str(RB.DEFAULT_DATASET))
    r = sub.add_parser("run", help="one retrieval-only baseline run")
    r.add_argument("--dataset", default=str(RB.DEFAULT_DATASET))
    r.add_argument("--out-dir", default=None, help="must not exist (default: data/evaluation/results/<run_id>)")
    r.add_argument("--semantic", choices=("production", "off"), default="production",
                   help="production = the configured semantic fallback; off = lexical only (diagnostic)")
    r.add_argument("--ids", nargs="*", default=None)
    r.add_argument("--general-evidence-order", choices=("tier", "binding_first"), default=None,
                   help="Phase 2 experiment switch (ContextPolicy.general_evidence_order); default: as configured (tier)")
    r.add_argument("--min-trigram-similarity", type=float, default=None,
                   help="Phase 4 experiment: override RagConfig.min_trigram_similarity for this run (default: as configured, 0.4)")
    c = sub.add_parser("compare", help="determinism check between two runs")
    c.add_argument("run_a")
    c.add_argument("run_b")
    cb = sub.add_parser("compare-baseline", help="per-question comparison and the Phase 2 acceptance criteria")
    cb.add_argument("baseline")
    cb.add_argument("candidate")
    args = p.parse_args()
    return {"build-dataset": cmd_build_dataset, "run": cmd_run, "compare": cmd_compare,
            "compare-baseline": cmd_compare_baseline}[args.cmd](args)


def cmd_compare_baseline(args) -> int:
    def load(d: str):
        return [json.loads(l) for l in (Path(d) / "per_question.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    out = RB.compare_to_baseline(load(args.baseline), load(args.candidate))
    target = Path(args.candidate) / "comparison_to_baseline.json"
    if target.exists():
        print(f"refusing to overwrite {target}", file=sys.stderr)
        return 2
    out["baseline_run"], out["candidate_run"] = Path(args.baseline).name, Path(args.candidate).name
    target.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    for name, c in out["criteria"].items():
        shown = {k: v for k, v in c.items() if k not in ("base", "new", "limit_violations", "gating_changes")}
        extra = (f" violations={len(c['limit_violations'])} gating_changes={len(c['gating_changes'])}"
                 if "limit_violations" in c else "")
        print(f"{'PASS' if c['passed'] else 'FAIL'}  {name}: {shown}{extra}")
    print(f"all_passed={out['all_passed']} recovered={out['recovered']}")
    print(f"not_recovered={out['not_recovered']}")
    print(f"plain_lost={out['plain_lost']} identifier_lost={out['identifier_lost']} gained_outside_targets={out['plain_gained_outside_targets']}")
    print(f"records identical by class: {out['by_class']}")
    print(f"written: {target}")
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
