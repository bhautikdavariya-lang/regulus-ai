"""Evidence-supply Phase 1b: is the governing section reachable at greater retrieval depth?

Phase 1 found that 75 of the 126 evidence-supply rows never had the governing section returned by
the retriever at all, at the production `top_k` of 8. That could mean the section is unreachable by
this retriever (a recall problem needing a new retrieval method) or merely below the cut (a depth
problem). The two call for completely different interventions, so this measures which it is.

For each row the retriever is re-run at a series of depths with everything else held constant, and
the governing section's rank in `response.results` is recorded. Retrieval only - no selection, no
prompt, no model. Production config is copied and the copy is modified; production is untouched.

    .venv/bin/python scripts/es_phase1_depth.py [--depths 8,24,48,96]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.config.settings import load_settings  # noqa: E402
from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark  # noqa: E402
from regulus.rag import RagPipeline  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.planning.plan import plan_query  # noqa: E402
from regulus.system_identity import configured_rag_config  # noqa: E402

WORKBOOK = ROOT / "Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx"
SECTION_RE = re.compile(r"(\d{1,4})\.(\d+)")


def section_of(label: str) -> str | None:
    m = SECTION_RE.search(label or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trace", type=Path, default=ROOT / "artifacts/stage_b/phase1_trace.jsonl")
    ap.add_argument("--mode", default="not_retrieved")
    ap.add_argument("--depths", default="8,24,48,96")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_b/phase1_depth.jsonl")
    args = ap.parse_args()

    depths = [int(x) for x in args.depths.split(",")]
    traced = [json.loads(l) for l in args.trace.read_text().splitlines() if l.strip()]
    rows_in = [r for r in traced if r["mode"] == args.mode]
    print(f"probing {len(rows_in)} rows at depths {depths}")

    bench = {q.question_id: q for q in load_acceptance_benchmark(WORKBOOK)}
    settings = load_settings()
    base = configured_rag_config(settings)
    db = Database.from_env()
    db.connect()

    pipelines = {}
    for d in depths:
        cfg = dataclasses.replace(base, top_k=d)
        retriever, scope = build_retriever(db, cfg)
        pipelines[d] = RagPipeline(retriever, None, cfg, scope_policy=scope)

    out = []
    for n, r in enumerate(rows_in, 1):
        q = bench[r["id"]]
        rec = {"id": r["id"], "type": r["type"], "key_sections": r["key_sections"], "by_depth": {}}
        for d, pipe in pipelines.items():
            plan = plan_query(q.question)
            plan2, targets = pipe.reference_lookup_plan(plan)
            response, _ = pipe.retrieve(q.question, plan2, targets)
            secs = [section_of(x.citation.label) for x in response.results]
            corp = [x.corpus for x in response.results]
            ranks = {k: next((i + 1 for i, s in enumerate(secs) if s == k), None) for k in r["key_sections"]}
            best = min([v for v in ranks.values() if v], default=None)
            rec["by_depth"][str(d)] = {
                "n_results": len(response.results),
                "n_ecfr": sum(1 for c in corp if c == "ecfr"),
                "key_ranks": ranks,
                "best_rank": best,
                "found": best is not None,
            }
        rec["first_depth_found"] = next((d for d in depths if rec["by_depth"][str(d)]["found"]), None)
        out.append(rec)
        print(f"  [{n:3}/{len(rows_in)}] {r['id']:8} "
              + "  ".join(f"d{d}:{rec['by_depth'][str(d)]['best_rank'] or '-'}" for d in depths), flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out))

    print("\nfirst depth at which the governing section appears")
    for d, c in Counter(x["first_depth_found"] for x in out).most_common():
        print(f"  {c:4}  {'never' if d is None else f'top_k={d}'}")
    for d in depths:
        found = sum(1 for x in out if x["by_depth"][str(d)]["found"])
        print(f"  cumulative at top_k={d:3}: {found}/{len(out)} ({round(100*found/len(out),1)}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
