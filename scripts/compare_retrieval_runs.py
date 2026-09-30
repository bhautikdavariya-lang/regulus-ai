"""Side-by-side comparison of retrieval-evaluation result files on the same
dataset: metrics, per-category rows, per-query first-hit ranks, crowding
fields and negative-control behaviour.

    python scripts/compare_retrieval_runs.py A.json B.json C.json
    python scripts/compare_retrieval_runs.py A.json B.json --queries          # per-query ranks
    python scripts/compare_retrieval_runs.py A.json B.json --ids retrieval-025 --top 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _fmt(v):
    if v is None:
        return "n/a"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    p.add_argument("--queries", action="store_true", help="per-query first-hit rank table")
    p.add_argument("--ids", nargs="+", default=None, help="print top results for these query ids")
    p.add_argument("--top", type=int, default=5)
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    runs = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.runs]
    labels = [r["run"].get("pipeline", Path(f).stem) for r, f in zip(runs, args.runs)]
    if len({r["run"]["dataset"]["sha256"] for r in runs}) > 1:
        print("WARNING: runs use different datasets")
    col = max(12, max(len(l) for l in labels) + 2)

    def row(name, values):
        print(f"{name:<28}" + "".join(f"{_fmt(v):>{col}}" for v in values))

    print(f"{'':<28}" + "".join(f"{l:>{col}}" for l in labels))
    for m in ("recall@1", "recall@3", "recall@5", "recall@10", "mrr", "precision@1", "precision@3", "precision@5"):
        row(m, [r["summary"].get(m) for r in runs])
    row("scored / negatives", [f"{r['summary']['scored']} / {r['summary']['negative_controls']}" for r in runs])
    row("negatives passed", [r["summary"]["negative_controls_passed"] for r in runs])
    row("existence mismatches", [len(r["summary"].get("existence_mismatches", [])) for r in runs])
    row("misses", [len(r["summary"]["misses"]) for r in runs])
    row("avg latency (ms)", [r["summary"]["avg_total_ms"] for r in runs])
    cats = sorted({c for r in runs for c in r["summary"]["by_category"]})
    print("\nby category: recall@1 / recall@10 / precision@5 (negatives passed/total)")
    for c in cats:
        vals = []
        for r in runs:
            b = r["summary"]["by_category"].get(c)
            if not b:
                vals.append("-")
            elif b["scored"]:
                vals.append(f"{_fmt(b['recall@1'])}/{_fmt(b['recall@10'])}/{_fmt(b.get('precision@5'))}")
            else:
                vals.append(f"neg {b['negative_controls_passed']}/{b['negative_controls']}")
        row(c, vals)

    if args.queries or args.ids:
        print()
        by_id = [{q["id"]: q for q in r["results"]} for r in runs]
        for q in runs[0]["results"]:
            if args.ids and q["id"] not in args.ids:
                continue
            ranks = [(t.get(q["id"]) or {}).get("first_hit_rank") for t in by_id]
            negs = [(t.get(q["id"]) or {}).get("negative_control_passed") for t in by_id]
            if q["negative_control"]:
                cell = " | ".join(("neg-ok" if n else "neg-FAIL") if n is not None else "-" for n in negs)
            else:
                cell = " | ".join(f"{r:>3}" if r else "  -" for r in ranks)
            print(f"  {q['id']:<15} {q['category']:<22} {q['query'][:50]:<52} {cell}")
            if args.ids:
                for label, t in zip(labels, by_id):
                    o = t.get(q["id"])
                    if not o:
                        continue
                    rd = o.get("retrieval", {})
                    cw = o.get("crowding", {})
                    print(f"      {label}: mode={rd.get('retrieval_mode')} exact_present={o.get('exact_match_present')} sem_in_final={rd.get('semantic_in_final')} above_target={cw.get('results_above_target')} distractors_above={cw.get('distractors_above_target')} top10 ecfr/guid/sem={cw.get('top10_ecfr')}/{cw.get('top10_guidance')}/{cw.get('top10_semantic')}")
                    for t_ in o["top_results"][: args.top]:
                        print(f"         {t_['rank']:>2}. [{t_['corpus']}] {t_['citation'][:70]} <{t_['method']}{'+sem' if 'semantic' in t_.get('methods', []) and t_['method'] != 'semantic' else ''}> {t_['score']} {t_.get('role') or ''}{' contextual' if t_.get('contextual_only') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
