"""Evidence-supply Phase 1: trace where the governing provision is lost, per row.

Replays the production retrieval path - `plan_query` -> `RagPipeline.retrieve` ->
`build_bundle` -> `build_package` - for a given set of benchmark questions and records, at each
stage, whether the benchmark's governing section is still present. No generation: the model is
never loaded, so a 126-row trace costs seconds, not hours.

The stages, and the failure mode each one isolates:

    corpus          does the section exist in the snapshot at all, and how many paragraphs has it
    retrieved       is it among `response.results` (what the retriever returned), and at what rank
    selected        is it among `bundle.sources` (what survived ranking, budget and consolidation)
    prompt          is it in the text the model is actually given, and with how many paragraphs

A row's failure mode is the first stage at which the section disappears. That is the whole point:
"evidence supply failed" is not one mechanism, and a fix aimed at the wrong stage cannot work.

Read-only. Production is imported and called, never modified; nothing is written outside
`artifacts/stage_b/`.

    .venv/bin/python scripts/es_phase1_trace.py --ids-from artifacts/stage_a/attribution_rows.jsonl
    .venv/bin/python scripts/es_phase1_trace.py --ids S-001,M-004
"""

from __future__ import annotations

import argparse
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
from regulus.rag.generation import build_grounded_messages, build_package  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.factory import build_retriever  # noqa: E402
from regulus.planning.plan import plan_query  # noqa: E402

WORKBOOK = ROOT / "Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx"
SECTION_RE = re.compile(r"(\d{1,4})\.(\d+)")


def configured():
    """The acceptance run's own configuration, via the same helper the runner uses."""
    from regulus.system_identity import configured_rag_config
    settings = load_settings()
    return settings, configured_rag_config(settings)


def section_of(label: str) -> str | None:
    m = SECTION_RE.search(label or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def corpus_facts(db: Database, sections: list[str]) -> dict:
    out = {}
    with db.connect() as conn, conn.cursor() as cur:
        for s in sections:
            cur.execute(
                "SELECT count(*) AS n, bool_or(is_reserved) AS reserved,"
                "       count(*) FILTER (WHERE ordinal = 0) AS ord0"
                "  FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL",
                {"s": s})
            row = cur.fetchone()
            out[s] = {"paragraphs": row["n"], "reserved": bool(row["reserved"]), "has_ordinal_0": row["ord0"] > 0}
    return out


def trace(pipeline: RagPipeline, question: str, keys: list[str]) -> dict:
    plan = plan_query(question)
    plan2, reference_targets = pipeline.reference_lookup_plan(plan)
    shape, analysis = pipeline.question_view(plan2)
    response, registry = pipeline.retrieve(question, plan2, reference_targets)
    bundle, coverage, selection = pipeline.build_bundle(response, registry, shape)
    package = (build_package(plan2, coverage, selection, notes=bundle.notes,
                             budget=pipeline.config.generation_budget, answer_shape=shape,
                             question_analysis=analysis)
               if coverage is not None and selection is not None else None)
    prompt = ""
    if package is not None:
        try:
            prompt = "\n".join(m["content"] for m in build_grounded_messages(package))
        except Exception as exc:                      # a package the prompt builder rejects
            prompt = f"<<prompt build failed: {exc}>>"

    retrieved = [r.citation.label for r in response.results]
    retrieved_secs = [section_of(x) for x in retrieved]
    selected = [s.result.citation.label for s in bundle.sources]
    selected_secs = [section_of(x) for x in selected]

    def rank_of(sec: str, seq: list[str | None]) -> int | None:
        return next((i + 1 for i, x in enumerate(seq) if x == sec), None)

    per_key = {}
    for k in keys:
        in_prompt = bool(re.search(r"\b" + re.escape(k) + r"\b", prompt))
        # how many distinct paragraphs of the key section reached the prompt
        paras_selected = sum(1 for x in selected_secs if x == k)
        per_key[k] = {
            "retrieved_rank": rank_of(k, retrieved_secs),
            "selected_rank": rank_of(k, selected_secs),
            "paragraphs_selected": paras_selected,
            "named_in_prompt": in_prompt,
        }

    # was the plan a whole-part request? that is what routes to ECFR_EXACT_PART
    part_level = [r.reference.canonical for r in plan2.requirements if r.reference.section is None]
    return {
        "plan_requirements": [r.reference.canonical for r in plan2.requirements],
        "part_level_requirements": part_level,
        "is_part_level": bool(part_level),
        "reference_targets": list(reference_targets),
        "n_retrieved": len(retrieved),
        "n_selected": len(selected),
        "retrieved_sections": retrieved_secs,
        "selected_labels": selected,
        "selected_sections": selected_secs,
        "corpora": sorted({r.corpus for r in response.results}),
        "selected_corpora": sorted({s.result.corpus for s in bundle.sources}),
        "coverage_state": getattr(coverage, "state", None),
        "satisfied_ids": list(getattr(package, "satisfied_ids", ()) or ()) if package else [],
        "evidence_chars": sum(len(s.result.text or "") for s in bundle.sources),
        "prompt_chars": len(prompt),
        "per_key": per_key,
    }


def classify(row: dict) -> tuple[str, str]:
    """First stage at which every governing section is gone -> the failure mode."""
    keys = row["key_sections"]
    if not keys:
        return "no_governing_section", "the question names no provision to supply"
    facts, per = row["corpus"], row["trace"]["per_key"]

    live = [k for k in keys if facts[k]["paragraphs"] > 0 and not facts[k]["reserved"]]
    if not live:
        reserved = [k for k in keys if facts[k]["reserved"]]
        if reserved:
            return "corpus_reserved_only", f"every governing section is reserved in the snapshot: {','.join(reserved)}"
        return "corpus_gap", f"no live rows in the snapshot for {','.join(keys)}"

    if any(per[k]["named_in_prompt"] and per[k]["paragraphs_selected"] >= 1 for k in live):
        reached = [k for k in live if per[k]["paragraphs_selected"] >= 1]
        if all(per[k]["paragraphs_selected"] == 1 and facts[k]["paragraphs"] > 1 for k in reached):
            worst = max(facts[k]["paragraphs"] for k in reached)
            return "supplied_first_paragraph_only", \
                f"{','.join(reached)} reached the prompt with 1 of up to {worst} paragraphs"
        return "supplied", f"{','.join(reached)} reached the prompt with its paragraphs"

    if any(per[k]["selected_rank"] for k in live):
        return "selected_not_in_prompt", "the section survived selection but is not named in the prompt"
    if any(per[k]["retrieved_rank"] for k in live):
        ranks = {k: per[k]["retrieved_rank"] for k in live if per[k]["retrieved_rank"]}
        return "dropped_in_selection", f"retrieved at rank {ranks} and cut before the prompt"
    return "not_retrieved", f"the retriever never returned {','.join(live)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", default=None, help="comma-separated question ids")
    ap.add_argument("--ids-from", type=Path, default=ROOT / "artifacts/stage_a/attribution_rows.jsonl")
    ap.add_argument("--category", default="EVIDENCE_SUPPLY")
    ap.add_argument("--dataset", type=Path, default=ROOT / "artifacts/stage_a/dataset.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_b/phase1_trace.jsonl")
    args = ap.parse_args()

    data = {json.loads(l)["id"]: json.loads(l) for l in args.dataset.read_text().splitlines() if l.strip()}
    if args.ids:
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    else:
        ids = [json.loads(l)["id"] for l in args.ids_from.read_text().splitlines()
               if l.strip() and json.loads(l)["category"] == args.category]
    print(f"tracing {len(ids)} rows")

    bench = {q.question_id: q for q in load_acceptance_benchmark(WORKBOOK)}
    settings, config = configured()
    db = Database.from_env()
    db.connect()
    retriever, scope = build_retriever(db, config)
    pipeline = RagPipeline(retriever, None, config, scope_policy=scope)

    rows = []
    for n, qid in enumerate(ids, 1):
        d = data[qid]
        keys = [s.strip() for s in re.split(r"[;,]", d["rev_key_sections"] or "") if s.strip()]
        row = {"id": qid, "type": d["type"], "domain": d["domain"], "key_citation_draft": d["key_citation_draft"],
               "key_sections": keys, "result": d["result"], "N": d["N"], "L": d["L"]}
        row["corpus"] = corpus_facts(db, keys)
        try:
            row["trace"] = trace(pipeline, d["question"], keys)
            row["error"] = None
        except Exception as exc:
            row["trace"] = {"per_key": {k: {"retrieved_rank": None, "selected_rank": None,
                                            "paragraphs_selected": 0, "named_in_prompt": False} for k in keys}}
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["mode"], row["mode_detail"] = classify(row)
        rows.append(row)
        print(f"  [{n:3}/{len(ids)}] {qid:8} {row['mode']:32} {row['mode_detail'][:70]}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print("\nMODES")
    for m, n in Counter(r["mode"] for r in rows).most_common():
        print(f"  {n:4}  {m}")
    print(f"\nerrors: {sum(1 for r in rows if r['error'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
