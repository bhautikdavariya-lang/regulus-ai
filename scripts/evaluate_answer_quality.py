"""Answer-quality evaluation (Stage 3) over Stage 5 runs: no model is loaded.

    python scripts/evaluate_answer_quality.py --run A=artifacts/stage5_stage6/run_X --label stage3_A
    python scripts/evaluate_answer_quality.py --run A=<run A dir> --run B=<run B dir> --label stage3_ab

Stage 5 already generates and machine-checks every answer (validation, repair,
completeness, refusal, hallucination, claim support, citations). This script
reads those records instead of generating again, and adds what Stage 3 needs:

* the prompt the model was given, rebuilt deterministically from the question
  with the run's own configuration, and checked against what the run recorded
  (prompt SHA-256 when recorded, else the prompt's character count);
* the question analysis (type, yes/no, scope) and the deterministic quality flags;
* one Markdown review page per question for an SME, and an index;
* with two runs, a per-question comparison (answer diff, validation, repair,
  citations, flags, tokens, latency) and a table of dimensions.

Every dimension is reported separately and labelled by how it is measured:
AUTOMATIC (deterministic checks), BENCHMARK-KEYED (against the hand-fixed
expectations in stage5_v1.jsonl: expected behaviour and terms, fixed by the
developer, NOT an SME-locked key), or SME REVIEW PENDING. Nothing is combined
into a score. Output: artifacts/answer_quality/<label>/. Read-only database.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from regulus.config import PROJECT_ROOT, load_settings
from regulus.planning import plan_query
from regulus.planning.intent import analyze_question
from regulus.rag import RagPipeline
from regulus.rag.answer_quality import quality_flags
from regulus.rag.generation import build_grounded_messages, build_package
from regulus.retrieval import Database, LexicalRetriever
from regulus.system_identity import evaluation_rag_config

OUT_ROOT = PROJECT_ROOT / "artifacts" / "answer_quality"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.is_file() else []


def load_run(run_dir: Path) -> dict:
    stage = run_dir / "stage5" if (run_dir / "stage5").is_dir() else run_dir
    manifest = json.loads((stage / "run_manifest.json").read_text(encoding="utf-8"))
    correctness = json.loads((stage / "correctness_results.json").read_text(encoding="utf-8"))
    return {
        "dir": stage, "manifest": manifest,
        "full": {r["id"]: r for r in jsonl(stage / "generation_full.jsonl")},
        "correct": {r["id"]: r for r in correctness.get("per_question", [])},
        "answer_shape": ((manifest.get("evaluation_config") or {}).get("prompt") or {}).get("answer_shape") or "adaptive",
    }


def rebuild(pipe: RagPipeline, question: str):
    plan = plan_query(question)
    shape, analysis = pipe.question_view(plan)  # exactly what the pipeline decided
    response, registry = pipe.retrieve(question, plan)
    bundle, coverage, selection = pipe.build_bundle(response, registry, shape)
    if coverage is None or selection is None:
        return None, plan
    package = build_package(plan, coverage, selection, notes=bundle.notes, budget=pipe.config.generation_budget,
                            answer_shape=shape, question_analysis=analysis)
    return package, plan


def evaluate_run(label: str, run: dict, questions: dict[str, dict], db) -> list[dict]:
    config = replace(evaluation_rag_config(load_settings()), answer_shape=run["answer_shape"])
    pipe = RagPipeline(LexicalRetriever(db), None, config)
    rows = []
    for qid, rec in run["full"].items():
        q = questions[qid]
        package, plan = rebuild(pipe, q["question"])
        analysis = analyze_question(plan)
        prompt = build_grounded_messages(package) if package is not None and rec.get("generated") else None
        sha = hashlib.sha256(json.dumps(prompt, ensure_ascii=False).encode("utf-8")).hexdigest() if prompt else None
        if rec.get("prompt_sha256"):
            prompt_check = "sha256 equal" if sha == rec["prompt_sha256"] else "SHA256 DIFFERS"
        elif prompt:
            prompt_check = "chars equal" if len(prompt[1]["content"]) == rec.get("prompt_chars") else "CHARS DIFFER"
        else:
            prompt_check = "no model call"
        flags_final = rec.get("quality_flags")
        if flags_final is None:  # runs made before Stage 3: compute the same flags from the recorded answer
            flags_final = quality_flags(rec.get("answer_final") or "", package, analysis, rec.get("validation_final"),
                                        coverage_action=rec.get("coverage_action"), model_called=bool(rec.get("generated")),
                                        question=q["question"])
        corr = run["correct"].get(qid, {})
        tokens = rec.get("tokens") or {}
        rows.append({
            "run": label, "question_id": qid, "question": q["question"], "category": q["category"],
            "expected_behavior": q["expected_behavior"], "expected_terms": q["expected_terms"],
            "prompt_hash": sha, "prompt_check": prompt_check,
            "prompt_chars": len(prompt[1]["content"]) if prompt else None,
            "question_type": analysis.question_type, "is_yes_no": analysis.is_yes_no, "scope_status": analysis.scope_status,
            "model": (run["manifest"].get("model") or {}).get("key") if isinstance(run["manifest"].get("model"), dict) else None,
            "answer_shape_setting": run["answer_shape"],
            "sources": [{"index": s.index, "citation": s.citation, "tier": s.tier} for s in (package.sources if package else ())],
            "source_texts": {s.index: s.text for s in (package.sources if package else ())},
            "answer_raw": rec.get("answer_raw"), "answer": rec.get("answer_final"),
            "citations": [c.get("label") for c in (rec.get("citations") or {}).get("listed", [])],
            "initial_validation": {k: (rec.get("validation_initial") or {}).get(k) for k in ("status", "codes")},
            "final_validation": {k: (rec.get("validation_final") or {}).get(k) for k in ("status", "codes")},
            "repair": rec.get("repair"), "coverage_action": rec.get("coverage_action"),
            "generated_tokens": tokens.get("generated"), "prompt_tokens": tokens.get("prompt_tokens"),
            "answer_length_words": len((rec.get("answer_final") or "").split()),
            "latency_ms": {k: (rec.get("timings_ms") or {}).get(k) for k in ("model_first_token_ms", "generation_ms", "total_ms")},
            "quality_flags": flags_final,
            "normalization": rec.get("normalization"),
            # Stage 5 machine checks, per dimension (no composite)
            "benchmark_keyed_correct_raw": corr.get("raw_correct"), "benchmark_keyed_correct_final": corr.get("final_correct"),
            "correct_reasons_final": corr.get("final_reasons"),
            "all_addressed_final": (rec.get("completeness") or {}).get("all_addressed_final"),
            "term_recall_final": (rec.get("completeness") or {}).get("term_recall_final"),
            "claims_final": (rec.get("faithfulness_final") or {}).get("counts"),
            "citation_ok": (rec.get("citations") or {}).get("citation_ok"),
            "hallucination_final": (rec.get("hallucination") or {}).get("any_final"),
            "refusal": rec.get("refusal"),
            "domain_leak_final": (rec.get("domain") or {}).get("leak_final"),
        })
    return rows


# ------------------------------------------------------------------ dimensions


def dimensions(rows: list[dict]) -> dict:
    gen = [r for r in rows if r["generated_tokens"]]
    n = lambda pred, pool: f"{sum(1 for r in pool if pred(r))}/{len(pool)}"
    flag = lambda name: lambda r: any(f["flag"] == name for f in (r["quality_flags"] or []))
    ref_expected = [r for r in rows if r["expected_behavior"] == "refuse"]
    answer_expected = [r for r in rows if r["expected_behavior"] != "refuse"]
    def outcome(r):  # how an expected refusal was handled, without collapsing the classes
        if (r["refusal"] or {}).get("deterministic_refusal") or (r["generated_tokens"] is None and r["coverage_action"] != "answer"):
            return "deterministic"
        return (r["refusal"] or {}).get("final_class") or "answer"
    refused = lambda r: outcome(r) in ("deterministic", "refusal")
    return {
        "Correctness [BENCHMARK-KEYED, machine composite, not SME]": {
            "all machine checks pass, final answer": n(lambda r: r["benchmark_keyed_correct_final"], rows),
            "all machine checks pass, raw model answer": n(lambda r: r["benchmark_keyed_correct_raw"], rows),
            "semantic correctness": "NOT MEASURABLE YET: requires SME review"},
        "Grounding [AUTOMATIC, heuristic]": {
            "answers with a claim flagged NOT supported (final)": n(lambda r: (r["claims_final"] or {}).get("NO", 0) > 0, gen),
            "unsupported content (hallucination checks, final)": n(lambda r: r["hallucination_final"], gen)},
        "Citation support [AUTOMATIC]": {
            "citation checks pass (raw)": n(lambda r: r["citation_ok"], gen),
            "citation_mismatch flag (final)": n(flag("citation_mismatch"), gen),
            "missing_citation flag (final)": n(flag("missing_citation"), gen)},
        "Completeness [BENCHMARK-KEYED]": {
            "every expected provision addressed (final)": n(lambda r: r["all_addressed_final"] is not False, answer_expected),
            "all expected terms present (final)": n(lambda r: r["term_recall_final"] in (None, 1.0), answer_expected)},
        "Relevance [AUTOMATIC signal only]": {
            "excessive_length flag": n(flag("excessive_length"), gen), "scope_expansion in validation": n(
                lambda r: "scope_expansion" in (r["final_validation"]["codes"] or []), gen),
            "judgement": "NOT MEASURABLE YET: requires SME review"},
        "Structure [AUTOMATIC signal only]": {
            "weak_structure flag": n(flag("weak_structure"), gen), "missing_direct_answer flag": n(flag("missing_direct_answer"), gen),
            "question_echo flag": n(flag("question_echo"), gen),
            "citation markers moved onto their sentence": n(lambda r: (r["normalization"] or {}).get("markers_moved", 0) > 0, gen),
            "judgement": "NOT MEASURABLE YET: requires SME review"},
        "Regulatory precision [AUTOMATIC signal only]": {
            "missing_condition flag": n(flag("missing_condition"), gen), "missing_exception flag": n(flag("missing_exception"), gen),
            "judgement": "NOT MEASURABLE YET: requires SME review"},
        "Refusal / scope [BENCHMARK-KEYED]": {
            "declined when a refusal was expected: deterministic or refusal class (final)": n(refused, ref_expected),
            "expected refusals by outcome (deterministic / refusal / hedged / answer)": {
                k: [r["question_id"] for r in ref_expected if outcome(r) == k] for k in ("deterministic", "refusal", "hedged", "answer")},
            "answered when an answer was expected (final)": n(lambda r: not refused(r), answer_expected),
            "out-of-domain content in the final answer": n(lambda r: r["domain_leak_final"], rows),
            "scope_mismatch flag": n(flag("scope_mismatch"), rows),
            "unsupported_claim flag (premise repeated)": n(flag("unsupported_claim"), gen)},
        "Hallucination [AUTOMATIC]": {
            "possible_hallucination flag": n(flag("possible_hallucination"), gen),
            "unsupported content (final)": n(lambda r: r["hallucination_final"], gen)},
        "Performance [AUTOMATIC]": {
            "median prompt tokens": _median([r["prompt_tokens"] for r in gen]),
            "median generated tokens": _median([r["generated_tokens"] for r in gen]),
            "median first token ms": _median([r["latency_ms"]["model_first_token_ms"] for r in gen]),
            "median generation ms": _median([r["latency_ms"]["generation_ms"] for r in gen]),
            "median total ms": _median([r["latency_ms"]["total_ms"] for r in rows]),
            "model calls": len(gen)},
    }


def _median(values):
    v = sorted(x for x in values if x is not None)
    return None if not v else (v[len(v) // 2] if len(v) % 2 else round((v[len(v) // 2 - 1] + v[len(v) // 2]) / 2, 1))


# ------------------------------------------------------------------ review pages


def review_page(r: dict) -> str:
    lines = [f"# {r['question_id']}: {r['question']}", "",
             f"*Run {r['run']} · answer_shape `{r['answer_shape_setting']}` · question type **{r['question_type']}**"
             f"{' (yes/no)' if r['is_yes_no'] else ''} · scope {r['scope_status']} · expected behaviour (developer-fixed, "
             f"not SME): {r['expected_behavior']}*", "",
             "## Generated answer (final, after validation and any repair)", "", r["answer"] or "(none)", ""]
    if r["answer_raw"] and r["answer_raw"] != r["answer"]:
        lines += ["## Raw model answer (before repair)", "", r["answer_raw"], ""]
    lines += ["## Citations listed", ""] + [f"- {c}" for c in r["citations"] or ["(none)"]] + [""]
    lines += ["## Validation", "",
              f"- initial: {r['initial_validation']['status']} {r['initial_validation']['codes']}",
              f"- repair: {r['repair']}", f"- final: {r['final_validation']['status']} {r['final_validation']['codes']}",
              f"- coverage action: {r['coverage_action']}", ""]
    lines += ["## Review flags (signals, not verdicts)", ""] + (
        [f"- **{f['flag']}**: {f['detail']}" for f in r["quality_flags"]] or ["- none"]) + [""]
    lines += ["## Retrieved evidence given to the model", ""]
    for s in r["sources"]:
        text = r["source_texts"].get(s["index"]) or r["source_texts"].get(str(s["index"])) or ""
        lines += [f"**[{s['index']}] {s['citation']}** ({s['tier']})", "", f"> {text[:1200]}", ""]
    lines += ["## SME review (to fill in)", "", "- Correct? yes / no / partly:", "- Grounded in the evidence above?",
              "- Conditions and exceptions preserved?", "- Structure clear?", "- Notes:", ""]
    return "\n".join(lines)


def compare(a: list[dict], b: list[dict]) -> tuple[list[dict], str]:
    bi = {r["question_id"]: r for r in b}
    changes, out = [], []
    for ra in a:
        rb = bi.get(ra["question_id"])
        if rb is None:
            continue
        fields = {k: (ra[k], rb[k]) for k in ("answer", "citations", "initial_validation", "final_validation", "repair",
                                               "coverage_action", "generated_tokens") if ra[k] != rb[k]}
        fa, fb = {f["flag"] for f in ra["quality_flags"] or []}, {f["flag"] for f in rb["quality_flags"] or []}
        if fa != fb:
            fields["quality_flags"] = (sorted(fa), sorted(fb))
        if not fields:
            continue
        changes.append({"question_id": ra["question_id"], "fields": sorted(fields)})
        out += [f"## {ra['question_id']} ({ra['question_type']}): {ra['question']}", "",
                f"Sources (same retrieval): {', '.join(s['citation'] for s in ra['sources']) or 'none'}", "",
                f"| | A | B |", "|---|---|---|",
                f"| initial validation | {ra['initial_validation']['status']} | {rb['initial_validation']['status']} |",
                f"| repair | {ra['repair']} | {rb['repair']} |",
                f"| final validation | {ra['final_validation']['status']} | {rb['final_validation']['status']} |",
                f"| coverage action | {ra['coverage_action']} | {rb['coverage_action']} |",
                f"| machine checks pass (final) | {ra['benchmark_keyed_correct_final']} | {rb['benchmark_keyed_correct_final']} |",
                f"| citations | {len(ra['citations'])} | {len(rb['citations'])} |",
                f"| generated tokens | {ra['generated_tokens']} | {rb['generated_tokens']} |",
                f"| total ms | {ra['latency_ms']['total_ms']} | {rb['latency_ms']['total_ms']} |",
                f"| flags | {', '.join(sorted(fa)) or '-'} | {', '.join(sorted(fb)) or '-'} |", ""]
        if "answer" in fields:
            out += ["```diff", "\n".join(difflib.unified_diff((ra["answer"] or "").splitlines(), (rb["answer"] or "").splitlines(),
                                                             "A", "B", lineterm="", n=2)), "```", ""]
    return changes, "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", action="append", required=True, help="LABEL=<stage5 run dir>; give A and optionally B")
    p.add_argument("--label", default="answer_quality")
    args = p.parse_args()
    runs = {lab: load_run(Path(d)) for lab, d in (x.split("=", 1) for x in args.run)}
    questions = {json.loads(l)["id"]: json.loads(l) for l in (PROJECT_ROOT / "data" / "evaluation" / "datasets" /
                                                             "stage5_v1.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    out_dir = OUT_ROOT / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=False)
    db = Database.from_env()
    db.connect()
    results = {lab: evaluate_run(lab, run, questions, db) for lab, run in runs.items()}
    db.close()
    summary = {"runs": {lab: {"dir": str(run["dir"]), "answer_shape": run["answer_shape"],
                              "prompt_checks": sorted({r["prompt_check"] for r in results[lab]})} for lab, run in runs.items()},
               "dimensions": {lab: dimensions(rows) for lab, rows in results.items()}}
    for lab, rows in results.items():
        (out_dir / f"results_{lab}.jsonl").write_text("".join(json.dumps({k: v for k, v in r.items() if k != "source_texts"},
                                                                          ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        review = out_dir / f"review_{lab}"
        review.mkdir()
        for r in rows:
            (review / f"{r['question_id']}.md").write_text(review_page(r), encoding="utf-8")
        (review / "INDEX.md").write_text("# SME review pages\n\n" + "\n".join(
            f"- [{r['question_id']}]({r['question_id']}.md) {r['question_type']} · flags: "
            f"{', '.join(f['flag'] for f in r['quality_flags']) or 'none'} · {r['question'][:90]}" for r in rows) + "\n", encoding="utf-8")
    if len(results) == 2:
        (la, a), (lb, b) = results.items()
        changes, md = compare(a, b)
        summary["changed_questions"] = changes
        (out_dir / f"compare_{la}_vs_{lb}.md").write_text(f"# {la} vs {lb}: {len(changes)} questions differ\n\n" + md, encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False)[:6000])
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
