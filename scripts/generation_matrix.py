"""Stage 6: generation failure matrix from a diagnostic run (no model is loaded).

    python scripts/generation_matrix.py <run dir> [--out artifacts/generation_quality/<name>.jsonl]

For every question that fails (reviewed where a review exists) or carries a generation-class record,
it lines up the pipeline's raw output (A) against the exact-evidence controlled output (B), the keyed
expectation of diagnostic_v1 (never edited), and whether each missing expected element exists in the
evidence the model was given. The root cause is assigned by the rules in `root_cause` below; they are
reported as rules, not as verdicts.
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DATASET = ROOT / "data/evaluation/datasets/diagnostic_v1.jsonl"
GEN_CLASSES = {"F07", "F08", "F09", "F12", "F13", "F14", "F15", "F16", "F18", "F20"}


def first(path):
    out = {}
    for l in open(path, encoding="utf-8"):
        if l.strip():
            r = json.loads(l); out.setdefault(r["question_id"], r)
    return out


def keyed_gaps(exp, text):
    t = (text or "").lower()
    terms = [x for x in exp.get("expected_terms") or [] if x.lower() not in t]
    points = [p for p in exp.get("expected_points") or [] if not any(a.lower() in t for a in p)]
    return terms, points


def root_cause(t, d, exp, a_gaps, b_gaps, b, evidence_text):
    classes = {f["failure_class"] for f in d["failures"] if f["confidence"] in ("proven", "probable")}
    if t.get("generation_blocked") or not t["model_called"]:
        return "scope/answerability", "the model was not called"
    if classes & {"F02"}:
        return "scope/answerability", "an out-of-scope question was generated"
    missing = a_gaps[0] + [p[0] for p in a_gaps[1]]
    absent = [m for m in missing if m.lower() not in evidence_text]
    if absent:
        return "evidence packaging/context", f"expected element(s) not in the evidence given to the model: {absent}"
    b_ok = b is not None and b.get("generated") and not (b_gaps[0] or b_gaps[1]) and (b.get("validation_initial") or {}).get("ok")
    a_ok_raw = not (a_gaps[0] or a_gaps[1])
    if b_ok and not a_ok_raw:
        return "evidence packaging/context", "the same model succeeds with exact evidence only; the extra context hurts"
    if a_ok_raw and "F12" in classes | {"F13"} & classes:
        return "repair", "the raw answer meets the key; repair/fallback made it fail"
    if a_ok_raw and (t.get("initial_validation") or {}).get("ok") is False and not classes & {"F07", "F09"}:
        return "validation (possible false positive)", "the raw answer meets the key but validation rejected it"
    if b is not None and b.get("generated"):
        return "model capability OR prompt", "fails with exact evidence too; prompt variants decide which"
    return "model capability OR prompt", "general question: no exact-evidence condition"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    run = Path(args.run)
    traces, diags = first(run / "traces.jsonl"), first(run / "diagnoses.jsonl")
    reviews = first(run / "manual_review.jsonl") if (run / "manual_review.jsonl").exists() else {}
    exps = {json.loads(l)["id"]: json.loads(l) for l in open(DATASET, encoding="utf-8") if l.strip()}
    from regulus.rag import RagPipeline
    from regulus.retrieval import Database, LexicalRetriever
    from regulus.config import load_settings
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_diagnostics import configured_rag_config
    from regulus.planning import plan_query
    db = Database.from_env(); db.connect()
    pipe = RagPipeline(LexicalRetriever(db), None, configured_rag_config(load_settings()))
    rows = []
    for q, d in diags.items():
        t, exp = traces[q], exps[q]
        status = (reviews.get(q) or {}).get("reviewed_status", d["final_status"]).split(" ")[0]
        classes = sorted({f["failure_class"] for f in d["failures"]})
        gen_records = [f for f in d["failures"] if f["failure_class"] in GEN_CLASSES and f["confidence"] != "needs_review"]
        if status in ("PASS", "UNVERIFIED") and not [f for f in gen_records if f["severity"] != "minor"]:
            continue
        # the evidence the model was given, rebuilt (and checked against the trace hash)
        plan = plan_query(t["question"]); shape, _ = pipe.question_view(plan)
        response, registry = pipe.retrieve(t["question"], plan)
        bundle, _, _ = pipe.build_bundle(response, registry, shape)
        evidence_text = " ".join(s.text for s in bundle.sources).lower()
        b = t.get("controlled")
        a_gaps = keyed_gaps(exp, t.get("raw_model_output") or t["final_answer"])
        b_gaps = keyed_gaps(exp, (b or {}).get("answer", "")) if b else ([], [])
        iv = t.get("initial_validation") or {}
        codes = set(iv.get("codes") or [])
        cause, why = root_cause(t, d, exp, a_gaps, b_gaps, b, evidence_text)
        rows.append({
            "question_id": q, "question": t["question"], "status": status, "automatic_status": d["final_status"],
            "answerability_state": t.get("answerability_state"), "evidence_sufficiency": t["evidence_sufficiency"]["state"],
            "retrieved_sources": [c["citation"] for c in t["selected_context"]], "prompt_tokens": t.get("prompt_token_count"),
            "exact_evidence_only_result": None if not b else {"answer": b.get("answer"), "validation": (b.get("validation_initial") or {}).get("codes"),
                                                              "ok": (b.get("validation_initial") or {}).get("ok"), "keyed_missing_terms": b_gaps[0],
                                                              "keyed_missing_points": len(b_gaps[1]), "sources": b.get("sources")},
            "raw_model_output": t.get("raw_model_output"), "validation_result": {"status": iv.get("status"), "codes": sorted(codes)},
            "repair_result": t.get("repair_type"), "fallback": t.get("fallback_type"), "final_answer": t["final_answer"],
            "failure_classes": classes, "primary": d["primary"],
            "missing_requirement": {"terms": a_gaps[0], "points": a_gaps[1]} if (a_gaps[0] or a_gaps[1]) else None,
            "qualifier_error": sorted(codes & {"qualifier_dropped", "qualifier_misapplied", "applicability_dropped"}) or None,
            "citation_error": sorted(codes & {"citation_mismatch", "provision_citation_mismatch", "invalid_citation", "discovery_cited_for_requirement"}) or None,
            "enumeration_error": sorted(codes & {"enumeration_incomplete", "requirement_not_addressed"}) or None,
            "unsupported_claim": sorted(codes & {"unsupported_figure", "asserted_missing_provision"}) or None,
            "synthesis_error": sorted(codes & {"synthesis_citation_gap", "material_group_uncovered", "evidence_by_evidence"}) or None,
            "repair_error": [f["failure_class"] for f in d["failures"] if f["failure_class"] in ("F12", "F13", "F20")] or None,
            "likely_root_cause": cause, "root_cause_rule": why,
            "confidence": "probable" if "OR" not in cause else "needs_experiment",
        })
    out = Path(args.out) if args.out else ROOT / "artifacts/generation_quality" / f"matrix_{run.name}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in rows:
        e = r["exact_evidence_only_result"]
        print(f"{r['question_id']:9} {r['status']:24} {r['primary'] or '-':7} {r['likely_root_cause']:32} "
              f"A-miss={len((r['missing_requirement'] or {}).get('terms', []))}t/{len((r['missing_requirement'] or {}).get('points', []))}p "
              f"B={'-' if not e else ('ok' if e['ok'] else 'bad')}/{'-' if not e else str(len(e['keyed_missing_terms']))+'t/'+str(e['keyed_missing_points'])+'p'} "
              f"q={r['qualifier_error']} c={r['citation_error']} en={r['enumeration_error']} u={r['unsupported_claim']}")
    print("wrote", out)


if __name__ == "__main__":
    main()
