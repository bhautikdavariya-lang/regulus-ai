"""Stage 4 failure observatory: trace, diagnose and score the golden diagnostic set.

    python scripts/run_diagnostics.py                          # all of diagnostic_v1.jsonl
    python scripts/run_diagnostics.py --ids UI-04 S5-053       # a few
    python scripts/run_diagnostics.py --repeat 10              # + re-run the first 10 generated questions (determinism)

For every question it runs the configured production pipeline (the default
the answering UI uses: CPU float32, answer_shape as configured, validation
"repair"), then:

* builds the full trace (regulus.observability.trace), including the raw model
  output, the repair input and output, and evidence sufficiency;
* adds two heuristics labelled as such: claim support (word overlap with the
  cited source) and provisions named that are not in the evidence;
* runs the CONTROLLED condition: the same model given only the exact evidence
  of the requested provisions. When the model still fails there, context was
  not the cause;
* diagnoses (regulus.observability.diagnose) against the question's expectation.

Writes artifacts/diagnostics/<label>_<utc>/: traces.jsonl, diagnoses.jsonl,
root_cause_matrix.md, scorecard.json, summary.md. Read-only database; no answer is changed.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from regulus.config import PROJECT_ROOT, load_settings
from regulus.inference.types import GenerationResult
from regulus.observability import build_trace, diagnose
from regulus.observability.taxonomy import FAILURE_CLASSES
from regulus.planning import plan_query
from regulus.rag import RagPipeline, load_qwen_generator
from regulus.rag.generation import build_grounded_messages, build_package
from regulus.rag.validation import validate_answer
from regulus.retrieval import Database, LexicalRetriever
from regulus.stage5.generation_eval import claims, controlled_selection, fabricated_identifiers
from regulus.system_identity import configured_generation_config, configured_rag_config

_GENERIC = {"does", "require", "requires", "required", "what", "which", "under", "must", "shall", "that", "this", "with", "from"}
DATASET = PROJECT_ROOT / "data" / "evaluation" / "datasets" / "diagnostic_v1.jsonl"
OUT_ROOT = PROJECT_ROOT / "artifacts" / "diagnostics"


def heuristics(out, trace: dict) -> None:
    """Claim support and fabricated identifiers for the raw and final text (heuristics, labelled)."""
    pkg = out.package
    if pkg is None or not out.model_called:
        return
    g = out.metadata.get("generation") or {}
    gen = GenerationResult("", "", g.get("prompt_tokens") or 0, g.get("generated_tokens") or 0, 0.0, finished=g.get("finished"))
    raw = (trace.get("raw_model_output") or "").strip()
    raw_report = validate_answer(raw, pkg, gen)
    trace["claims_raw"] = Counter(c["supported"] for c in claims(raw, pkg, raw_report))
    fin_report = validate_answer(out.answer, pkg, gen)
    trace["claims_final"] = Counter(c["supported"] for c in claims(out.answer, pkg, fin_report))
    # an identifier the model names is fabricated only if no supplied source's TEXT mentions it either
    # (sources cross-reference other sections, e.g. "see § 820.7"; the Stage 5 helper knows only source identities)
    texts = " ".join(s.text for s in pkg.sources)
    in_text = lambda label: re.search(r"(?<![\d.])" + re.escape(re.sub(r"^21 CFR |\(.*$", "", label)) + r"(?![\d])", texts) is not None
    trace["fabricated_identifiers_raw"] = [i for i in fabricated_identifiers(raw, pkg) if not in_text(i)]
    # yes/no questions: question terms that no supplied source contains, affirmed by the raw answer
    if trace.get("is_yes_no") and not re.match(r"^\s*(no\b|not\b|the (?:available )?(?:regulatory )?sources? do(?:es)? not)", raw, re.I):
        words = lambda s: set(re.findall(r"[a-z][a-z-]{3,}", (s or "").lower())) - _GENERIC
        in_sources = set().union(*(words(s.text) for s in pkg.sources)) if pkg.sources else set()
        trace["premise_unsupported_terms"] = sorted((words(out.question) - in_sources) & words(raw))
    trace["fabricated_identifiers_final"] = [i for i in fabricated_identifiers(out.answer, pkg) if not in_text(i)]


def controlled(pipeline: RagPipeline, out) -> dict | None:
    """The same model with only the exact evidence of the requested provisions."""
    if out.package is None or out.coverage is None or not out.coverage.satisfied_ids or not out.model_called:
        return None
    plan = plan_query(out.question)
    shape, analysis = pipeline.question_view(plan)
    sel = controlled_selection(out.selection)
    pkg = build_package(plan, out.coverage, sel, budget=pipeline.config.generation_budget, answer_shape=shape, question_analysis=analysis)
    gen = pipeline._generate(build_grounded_messages(pkg), pkg.max_new_tokens)
    report = validate_answer(gen.response.strip(), pkg, gen)
    return {"generated": True, "answer": gen.response.strip(), "validation_initial": report.to_dict(), "sources": len(pkg.sources),
            "generated_tokens": gen.generated_tokens}


def rediagnose(src: Path, items: list[dict], out_dir: Path, settings) -> int:
    """Re-apply the diagnosis rules to saved traces without generating anything."""
    from types import SimpleNamespace

    from regulus.observability.trace import sha256

    by_id = {i["id"]: i for i in items}
    traces = [json.loads(l) for l in (src / "traces.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    db = Database.from_env()
    db.connect()
    pipeline = RagPipeline(LexicalRetriever(db), None, configured_rag_config(settings))
    rows, mismatched = [], []
    with (out_dir / "traces.jsonl").open("w", encoding="utf-8") as tf, (out_dir / "diagnoses.jsonl").open("w", encoding="utf-8") as df:
        for t in traces:
            exp = by_id[t["question_id"]]
            plan = plan_query(t["question"])
            shape, analysis = pipeline.question_view(plan)
            response, registry = pipeline.retrieve(t["question"], plan)
            bundle, coverage, selection = pipeline.build_bundle(response, registry, shape)
            pkg = (build_package(plan, coverage, selection, notes=bundle.notes, budget=pipeline.config.generation_budget,
                                 answer_shape=shape, question_analysis=analysis) if coverage is not None else None)
            if [sha256(s.text) for s in bundle.sources] != [c["text_sha256"] for c in t["selected_context"]]:
                mismatched.append(t["question_id"])  # the evidence is not the one the trace recorded: do not re-diagnose it
                continue
            t["out_of_scope_part"] = analysis.out_of_scope_part if analysis else __import__("regulus.planning.intent", fromlist=["x"]).analyze_question(plan).out_of_scope_part
            fake = SimpleNamespace(package=pkg, model_called=t["model_called"], answer=t["final_answer"], question=t["question"],
                                   metadata={"generation": {"prompt_tokens": t["prompt_token_count"], "generated_tokens": t["output_token_count"],
                                                            "finished": t["finished"]}})
            heuristics(fake, t)
            diag = diagnose(t, exp, t.get("controlled"))
            rows.append({"exp": exp, "trace": t, "diag": diag})
            tf.write(json.dumps(t, ensure_ascii=False, default=dict) + "\n")
            df.write(json.dumps({**diag, "category": exp["category"], "verified_status": exp["verified_status"]}, ensure_ascii=False) + "\n")
    db.close()
    write_reports(rows, out_dir, determinism=[], info={"re-diagnosed from": str(src), "evidence_hash_mismatches": mismatched},
                  config_desc={"answer_shape": pipeline.config.answer_shape, "validation": pipeline.config.validation_behavior})
    print(f"re-diagnosed {len(rows)} traces from {src}; evidence mismatches: {mismatched}")
    return 0


def median(v):
    v = [x for x in v if x is not None]
    return round(statistics.median(v), 1) if v else None


def scorecard(rows: list[dict]) -> dict:
    keyed = [r for r in rows if r["exp"]["expected_behavior"] is not None]
    gen = [r for r in rows if r["trace"]["model_called"]]
    fc = lambda r, code: any(f["failure_class"] == code for f in r["diag"]["failures"])
    n = lambda pool, pred: {"count": sum(1 for r in pool if pred(r)), "of": len(pool)}
    t = lambda r: r["trace"]
    exp_exact = [r for r in keyed if r["exp"]["expected_exact"]]
    oos = [r for r in keyed if r["exp"]["category"].startswith("out_of_scope")]
    return {
        "intent": {"label": "AUTOMATED", "accuracy": "NOT YET MEASURABLE: no verified intent labels exist",
                   "distribution": dict(Counter(t(r)["intent_type"] for r in rows)),
                   "default_fallback_rate": n(rows, lambda r: t(r)["intent_type"] == "explanation")},
        "scope": {"label": "AUTOMATED vs DEVELOPER-KEYED", "keyed_out_of_scope_recognised_by_diagnostic_classifier":
                  n(oos, lambda r: t(r)["scope"] == "out_of_scope"),
                  "keyed_out_of_scope_declined_by_current_pipeline": n(oos, lambda r: not fc(r, "F02"))},
        "retrieval": {"label": "DEVELOPER-KEYED", "expected_provision_retrieved_as_exact": n(exp_exact, lambda r: not fc(r, "F03")),
                      "evidence_sufficiency": dict(Counter(t(r)["evidence_sufficiency"]["state"] for r in rows)),
                      "requested_value_kind_absent_from_evidence": n(rows, lambda r: t(r)["evidence_sufficiency"]["value_kind_in_evidence"] is False),
                      "ranking": "NOT YET MEASURABLE automatically: needs a relevance label per candidate"},
        "generation": {"label": "AUTOMATED", "raw_unsupported_content_F07": n(gen, lambda r: fc(r, "F07")),
                       "raw_qualifier_warnings_F08": n(gen, lambda r: fc(r, "F08")),
                       "answered_despite_insufficient_evidence_F05": n(gen, lambda r: fc(r, "F05")),
                       "raw_claims_supported_heuristic": {k: sum((t(r).get("claims_raw") or {}).get(k, 0) for r in gen) for k in ("YES", "NO", "UNCERTAIN")}},
        "validation": {"label": "AUTOMATED", "raw_answers_rejected": n(gen, lambda r: t(r)["initial_validation"] and not t(r)["initial_validation"]["ok"]),
                       "false_negatives_F11": n(gen, lambda r: fc(r, "F11")),
                       "false_positives_F10": "NOT YET MEASURABLE automatically: needs SME review of rejected answers"},
        "repair": {"label": "AUTOMATED", "repair_rate": n(gen, lambda r: bool(t(r)["repair_type"])),
                   "repair_types": dict(Counter(t(r)["repair_type"] for r in gen if t(r)["repair_type"])),
                   "final_valid_after_repair": n([r for r in gen if t(r)["repair_type"]], lambda r: (t(r)["final_validation"] or {}).get("ok")),
                   "irrelevant_fallback_F13": n(rows, lambda r: fc(r, "F13")), "repair_failure_F12": n(rows, lambda r: fc(r, "F12"))},
        "citations": {"label": "AUTOMATED", "answers_with_a_marker": n(gen, lambda r: "[" in (t(r)["final_answer"] or "")),
                      "citation_attribution_F09": n(gen, lambda r: fc(r, "F09")),
                      "semantic_citation_correctness": "NOT YET MEASURABLE: requires SME review"},
        "final_answer": {"label": "DEVELOPER-KEYED machine checks (not SME)", "pass": n(keyed, lambda r: r["diag"]["final_status"] == "PASS"),
                         "unverified_questions": sum(1 for r in rows if r["exp"]["expected_behavior"] is None),
                         "correctness_grounding_relevance_structure_precision": "NOT YET MEASURABLE: requires SME review"},
        "latency_ms": {"label": "AUTOMATED", "first_token_median": median([t(r)["timings_ms"].get("model_first_token_ms") for r in gen]),
                       "generation_median": median([t(r)["timings_ms"].get("generation_ms") for r in gen]),
                       "total_median": median([t(r)["timings_ms"].get("total_ms") for r in rows])},
    }


def matrix(rows: list[dict]) -> str:
    lines = ["| Question | Category | Final status | Primary failure | Secondary | Root module | Evidence (primary) |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        d = r["diag"]
        p = next((f for f in d["failures"] if f["primary"]), None)
        name = (f"{'(contained) ' if d['final_status'] == 'PASS' else ''}{p['failure_class']} {FAILURE_CLASSES[p['failure_class']].name}"
                f" [{p['confidence']}]") if p else "—"
        ev = ("; ".join(p["evidence"]))[:160].replace("|", "/") if p else ""
        lines.append(f"| {r['exp']['id']} | {r['exp']['category']} | {d['final_status']} | {name} | {', '.join(p['secondary_causes']) if p else '—'} | "
                     f"{p['module'] if p else '—'} | {ev} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--label", default="stage4_baseline")
    ap.add_argument("--repeat", type=int, default=0, help="re-run the first N generated questions to check determinism")
    ap.add_argument("--no-controlled", action="store_true")
    ap.add_argument("--from-traces", default=None, help="re-diagnose a saved run (no generation): rebuilds the evidence from the "
                                                          "database, verifies it against the trace hashes, re-applies the rules")
    args = ap.parse_args()
    items = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.ids:
        items = [i for i in items if i["id"] in args.ids]
    out_dir = OUT_ROOT / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=False)

    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    if args.from_traces:
        return rediagnose(Path(args.from_traces), items, out_dir, settings)
    generator = load_qwen_generator(settings, local_files_only=True)
    db = Database.from_env()
    db.connect()
    config = configured_rag_config(settings)
    pipeline = RagPipeline(LexicalRetriever(db), generator, config)
    info = generator.describe()
    rows = []
    with (out_dir / "traces.jsonl").open("w", encoding="utf-8") as tf, (out_dir / "diagnoses.jsonl").open("w", encoding="utf-8") as df:
        for n, exp in enumerate(items, start=1):
            t0 = time.perf_counter()
            out = pipeline.answer(exp["question"])
            trace = build_trace(out, question_id=exp["id"], generator_info=info, config=config.to_dict(), tokenizer=generator.tokenizer)
            heuristics(out, trace)
            ctrl = None if args.no_controlled else controlled(pipeline, out)
            trace["controlled"] = ctrl
            diag = diagnose(trace, exp, ctrl)
            rows.append({"exp": exp, "trace": trace, "diag": diag})
            tf.write(json.dumps(trace, ensure_ascii=False, default=dict) + "\n")
            df.write(json.dumps({**diag, "category": exp["category"], "verified_status": exp["verified_status"]}, ensure_ascii=False) + "\n")
            tf.flush()
            df.flush()
            print(f"{n:3}/{len(items)} {exp['id']:10} {diag['final_status']:24} primary={diag['primary'] or '-':8} "
                  f"{[f['failure_class'] for f in diag['failures']]} {time.perf_counter() - t0:.1f}s", flush=True)
    determinism = []
    if args.repeat:
        for r in [r for r in rows if r["trace"]["model_called"]][: args.repeat]:
            again = pipeline.answer(r["exp"]["question"])
            determinism.append({"question_id": r["exp"]["id"],
                                "raw_identical": again.metadata.get("raw_model_output") == r["trace"]["raw_model_output"],
                                "final_identical": again.answer == r["trace"]["final_answer"]})
    db.close()
    write_reports(rows, out_dir, determinism, info={"model": info.get("model_id"), "revision": info.get("model_revision"),
                                                    "device": info.get("device"), "dtype": info.get("dtype")},
                  config_desc={"answer_shape": config.answer_shape, "validation": config.validation_behavior})
    return 0


def write_reports(rows, out_dir, determinism, info, config_desc):
    primaries = Counter(r["diag"]["primary"] for r in rows if r["diag"]["primary"])
    by_module = Counter(FAILURE_CLASSES[c].module for c in [r["diag"]["primary"] for r in rows if r["diag"]["primary"]])
    all_records = Counter(f["failure_class"] for r in rows for f in r["diag"]["failures"])
    summary = {"questions": len(rows), "final_status": dict(Counter(r["diag"]["final_status"] for r in rows)),
               "primary_failure_by_class": dict(primaries.most_common()), "primary_failure_by_module": dict(by_module.most_common()),
               "all_failure_records_by_class": dict(all_records.most_common()),
               "severity_of_primary": dict(Counter(f["severity"] for r in rows for f in r["diag"]["failures"] if f["primary"])),
               "primary_by_confidence": dict(Counter(f["confidence"] for r in rows for f in r["diag"]["failures"] if f["primary"])),
               "determinism": determinism, "scorecard": scorecard(rows), "configuration": {**info, **config_desc}}
    (out_dir / "scorecard.json").write_text(json.dumps(summary, indent=1, default=dict), encoding="utf-8")
    (out_dir / "root_cause_matrix.md").write_text("# Root-cause matrix\n\n" + matrix(rows) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("final_status", "primary_failure_by_class", "primary_failure_by_module", "all_failure_records_by_class", "determinism")}, indent=1))
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
