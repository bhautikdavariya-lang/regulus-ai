"""Stage 5 aggregation: metric files, failure localisation, the training-plan
artifact and the Markdown report.

Everything here is a pure function of the per-question records written by
the evidence and generation phases, so a report can be regenerated from a
finished run without touching the model or the database.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

from regulus.stage5.dataset import Stage5Example
from regulus.stage5.evidence_eval import EvidenceRecord

LAYER_RETRIEVAL = "retrieval"
LAYER_COVERAGE = "coverage"
LAYER_SELECTION = "selection"
LAYER_GENERATION = "generation"
LAYER_GENERATION_CONTEXT = "generation_context"  # fails with pipeline context, fine with exact evidence only
LAYER_VALIDATION = "validation"
LAYER_DOMAIN = "domain_boundary"
LAYER_NONE = "none"
TRAINING_RELEVANT_LAYERS = (LAYER_GENERATION, LAYER_GENERATION_CONTEXT)

# what a model-side failure in each dataset category would be trained on
CATEGORY_TARGET = {
    "single": "grounded_single_provision", "parent": "grounded_single_provision", "section": "grounded_section_summary",
    "multi": "multi_provision_answers", "range": "multi_provision_answers", "long": "multi_provision_answers",
    "missing": "partial_answers_with_not_found", "nonexistent": "refusal_for_nonexistent",
    "adversarial": "non_fabrication", "refusal": "answer_when_evidence_exists", "citation": "citation_use",
    "general": "grounded_general_answers", "guidance": "grounded_guidance_answers", "domain_boundary": "domain_boundary_refusal",
}
# Stage 6 dataset categories that serve each target
TARGET_CATEGORIES = {
    "grounded_single_provision": ("direct_cfr", "section_paragraph"),
    "grounded_section_summary": ("direct_cfr",),
    "multi_provision_answers": ("multi_provision", "range_provision"),
    "partial_answers_with_not_found": ("partial_provision", "partial_context"),
    "refusal_for_nonexistent": ("abstention", "context_mismatch"),
    "non_fabrication": ("wrong_context", "context_mismatch", "citation_grounding"),
    "answer_when_evidence_exists": ("direct_cfr", "grounded_topic", "section_paragraph"),
    "citation_use": ("citation", "citation_grounding"),
    "grounded_general_answers": ("grounded_topic", "grounded_definition"),
    "grounded_guidance_answers": ("guidance_answer", "fda_guidance"),
    "domain_boundary_refusal": ("abstention",),
}
BASE_SHARES = {
    "direct_cfr": 0.12, "section_paragraph": 0.08, "definition": 0.03, "grounded_definition": 0.05, "grounded_topic": 0.06,
    "citation": 0.03, "citation_grounding": 0.06, "fda_guidance": 0.04, "guidance_answer": 0.05,
    "multi_provision": 0.14, "range_provision": 0.10, "partial_provision": 0.08,
    "abstention": 0.05, "context_mismatch": 0.05, "wrong_context": 0.04, "partial_context": 0.01, "guidance_mismatch": 0.01,
}
MAX_BOOST = 0.08


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 1)


def _by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in records}


# ------------------------------------------------------------- localisation


def localize(ex: Stage5Example, ev: EvidenceRecord | None, full: dict[str, Any] | None, controlled: dict[str, Any] | None) -> dict[str, Any]:
    reasons: list[str] = []
    if ev is None:
        return {"id": ex.id, "layer": "not_run", "reasons": ["no evidence record"]}
    if not ev.retrieval_ok:
        reasons.append("retrieval: " + ("parser named " + str(ev.retrieval["parsed_requirements"]) if not ev.retrieval["parse_ok"] else f"exact recall {ev.retrieval['exact_recall']}, false exact {ev.retrieval['false_exact_for_missing']}"))
        return {"id": ex.id, "layer": LAYER_RETRIEVAL, "reasons": reasons}
    if not ev.coverage_ok:
        reasons.append(f"coverage: state {ev.coverage['state']} vs expected {ev.coverage['expected_state']}, missing {ev.coverage['missing']}")
        return {"id": ex.id, "layer": LAYER_COVERAGE, "reasons": reasons}
    if not ev.selection_ok:
        reasons.append(f"selection: required dropped {ev.selection['required_dropped']}, present {ev.selection['required_present_in_context']}, deterministic {ev.deterministic}")
        return {"id": ex.id, "layer": LAYER_SELECTION, "reasons": reasons}
    if full is None:
        return {"id": ex.id, "layer": "not_run", "reasons": ["generation phase not run"]}
    if ex.domain == "out_of_domain":
        if full.get("domain", {}).get("leak_raw"):
            caught = not full.get("valid_raw", True)
            reasons.append("model answered an out-of-domain question from its own knowledge" + (" (validator caught it)" if caught else " (validator has nothing deterministic to reject)"))
            return {"id": ex.id, "layer": LAYER_DOMAIN, "reasons": reasons, "validator_caught": caught}
        return {"id": ex.id, "layer": LAYER_NONE, "reasons": []}
    if not full.get("generated"):
        # Two deterministic paths refuse without calling the model and both are
        # correct when a refusal was expected: an explicit provision with no
        # exact evidence (refuse_unsupported), and nothing retrieved at all
        # (no_context, which is how a nonexistent docket is handled).
        deterministic_paths = ("refuse_unsupported", "no_context", "refuse_out_of_scope")
        expected_deterministic = ex.expected_behavior == "refuse" and str(full.get("skipped_reason")) in deterministic_paths
        if expected_deterministic:
            return {"id": ex.id, "layer": LAYER_NONE, "reasons": [f"deterministic refusal as expected ({full.get('skipped_reason')})"]}
        reasons.append(f"pipeline did not generate: {full.get('skipped_reason')}")
        return {"id": ex.id, "layer": LAYER_VALIDATION, "reasons": reasons}
    ref, comp, hall = full["refusal"], full["completeness"], full["hallucination"]
    gen_fail = (not full["valid_raw"]) or ref["false_refusal"] or hall["any_raw"] or comp.get("all_addressed_raw") is False
    if ex.expected_behavior == "refuse" and ref["false_answer"]:
        gen_fail = True
        reasons.append("answered although the evidence does not support an answer")
    if gen_fail:
        if not full["valid_raw"]:
            reasons.append("raw answer failed validation: " + ", ".join(full["validation_initial"]["codes"]))
        if ref["false_refusal"]:
            reasons.append("refused although exact evidence was supplied")
        if hall["any_raw"]:
            reasons.append("unsupported content: " + ", ".join(hall["codes_raw"] + hall["fabricated_identifiers_raw"]))
        if comp.get("all_addressed_raw") is False:
            reasons.append(f"addressed {comp['addressed_raw']} of {comp['expected_exact_ids']}")
        c_ok = bool(controlled and controlled.get("generated") and controlled.get("valid_raw") and not controlled["hallucination"]["any_raw"] and controlled["completeness"].get("all_addressed_raw") is not False and not controlled["refusal"]["false_refusal"])
        layer = LAYER_GENERATION_CONTEXT if c_ok else LAYER_GENERATION
        if c_ok:
            reasons.append("the same model answers correctly when given exact evidence only")
        return {"id": ex.id, "layer": layer, "reasons": reasons}
    if comp.get("term_recall_raw") is not None and comp["term_recall_raw"] < 1.0:
        return {"id": ex.id, "layer": LAYER_NONE, "reasons": [f"valid, but expected terms partly absent: {comp['terms_found_raw']} of {comp['terms_expected']}"], "soft": True}
    return {"id": ex.id, "layer": LAYER_NONE, "reasons": []}


# --------------------------------------------------------------- aggregates


def generation_results(full: list[dict], controlled: list[dict], examples: dict[str, Stage5Example]) -> dict[str, Any]:
    def block(records: list[dict]) -> dict[str, Any]:
        gen = [r for r in records if r.get("generated")]
        cats: dict[str, dict[str, int]] = {}
        for r in gen:
            c = cats.setdefault(r["category"], {"generated": 0, "valid_raw": 0, "valid_final": 0, "complete_raw": 0})
            c["generated"] += 1
            c["valid_raw"] += int(bool(r["valid_raw"]))
            c["valid_final"] += int(bool(r["valid_final"]))
            c["complete_raw"] += int(r["completeness"].get("all_addressed_raw") is not False)
        return {
            "questions": len(records), "generated": len(gen), "not_generated": [(r["id"], r.get("skipped_reason")) for r in records if not r.get("generated")],
            "valid_raw": _rate(sum(1 for r in gen if r["valid_raw"]), len(gen)),
            "valid_final": _rate(sum(1 for r in gen if r["valid_final"]), len(gen)),
            "valid_only_after_repair": _rate(sum(1 for r in gen if r["valid_only_after_repair"]), len(gen)),
            "truncated": sum(1 for r in gen if r["tokens"].get("truncated")),
            "mean_generated_tokens": round(statistics.mean(r["tokens"]["generated"] for r in gen if r["tokens"].get("generated") is not None), 1) if gen else None,
            "by_category": cats,
            "status_raw": _count(r["validation_initial"]["status"] for r in gen),
            "status_final": _count(r["validation_final"]["status"] for r in gen),
        }
    fb, cb = _by_id(full), _by_id(controlled)
    localisation = []
    for qid, f in fb.items():
        c = cb.get(qid)
        if not f.get("generated") or not c or not c.get("generated"):
            continue
        localisation.append({"id": qid, "category": f["category"], "full_valid_raw": f["valid_raw"], "controlled_valid_raw": c["valid_raw"],
                             "full_complete_raw": f["completeness"].get("all_addressed_raw"), "controlled_complete_raw": c["completeness"].get("all_addressed_raw"),
                             "full_hallucination_raw": f["hallucination"]["any_raw"], "controlled_hallucination_raw": c["hallucination"]["any_raw"]})
    return {
        "modes": {"full_pipeline_raw": block(full), "controlled_evidence_raw": block(controlled)},
        "note": "valid_final counts answers that passed only after deterministic repair; it is not model quality",
        "localisation": localisation,
        "fails_with_context_but_not_with_exact_only": [l["id"] for l in localisation if not l["full_valid_raw"] and l["controlled_valid_raw"]],
        "fails_even_with_exact_only": [l["id"] for l in localisation if not l["controlled_valid_raw"]],
    }


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


def _claim_block(gen: list[dict], key: str) -> dict[str, Any]:
    all_claims = [dict(c, id=r["id"], category=r["category"]) for r in gen for c in (r.get(key) or {}).get("claims", [])]
    judged = [c for c in all_claims if c["supported"] in ("YES", "NO", "UNCERTAIN")]
    return {
        "claims_total": len(all_claims), "claims_judged": len(judged),
        "supported": sum(1 for c in judged if c["supported"] == "YES"),
        "unsupported": sum(1 for c in judged if c["supported"] == "NO"),
        "uncertain": sum(1 for c in judged if c["supported"] == "UNCERTAIN"),
        "deterministic_statements": sum(1 for c in all_claims if c["supported"] == "N/A"),
        "supported_ratio": _rate(sum(1 for c in judged if c["supported"] == "YES"), len(judged)),
        "questions_with_unsupported_claim": sorted({c["id"] for c in judged if c["supported"] == "NO"}),
        "unsupported_claims": [c for c in judged if c["supported"] == "NO"],
    }


def faithfulness_results(full: list[dict]) -> dict[str, Any]:
    gen = [r for r in full if r.get("generated")]
    all_claims = [dict(c, id=r["id"], category=r["category"]) for r in gen for c in r["faithfulness"]["claims"]]
    judged = [c for c in all_claims if c["supported"] in ("YES", "NO", "UNCERTAIN")]
    by_cat: dict[str, dict[str, int]] = {}
    for c in judged:
        d = by_cat.setdefault(c["category"], {"YES": 0, "NO": 0, "UNCERTAIN": 0})
        d[c["supported"]] += 1
    return {
        "claims_total": len(all_claims), "claims_judged": len(judged),
        "supported": sum(1 for c in judged if c["supported"] == "YES"),
        "unsupported": sum(1 for c in judged if c["supported"] == "NO"),
        "uncertain": sum(1 for c in judged if c["supported"] == "UNCERTAIN"),
        "deterministic_statements": sum(1 for c in all_claims if c["supported"] == "N/A"),
        "supported_ratio": _rate(sum(1 for c in judged if c["supported"] == "YES"), len(judged)),
        "questions_with_unsupported_claim": sorted({c["id"] for c in judged if c["supported"] == "NO"}),
        "by_category": by_cat,
        "unsupported_claims": [c for c in judged if c["supported"] == "NO"],
        "raw_answer": _claim_block(gen, "faithfulness"),
        "final_answer": _claim_block(gen, "faithfulness_final"),
        "note": "raw_answer is the model's own text; final_answer is after deterministic repair and is not a model-quality figure",
        "methodology": (
            "Sentence-level. SUPPORTED: cites an exact source, shares at least 50% of its content words with it and no "
            "deterministic check failed on it. NOT SUPPORTED: a deterministic check failed on the sentence (missing "
            "provision asserted, figure absent from sources, wrong-source citation) or it shares under 25% of its content "
            "words with what it cites. UNCERTAIN: everything between. Refusals and not-found statements are N/A."
        ),
        "limitations": (
            "Word overlap is not entailment: a paraphrase can share words and still misstate the source, and a correct "
            "restatement in different words can score UNCERTAIN. Treat NOT SUPPORTED as reliable and SUPPORTED as unproven."
        ),
    }


def citation_results(full: list[dict]) -> dict[str, Any]:
    gen = [r for r in full if r.get("generated")]
    explicit = [r for r in gen if r["completeness"].get("expected_exact_ids")]
    sat = sum(r["citations"].get("requirements_satisfied", 0) for r in explicit)
    exact_cited = sum(r["citations"].get("requirements_with_exact_cited", 0) for r in explicit)
    uncited = sum(1 for r in gen for p in r["validation_initial"]["problems"] if p["code"] == "uncited_statement")
    return {
        "generated": len(gen),
        "citation_ok": _rate(sum(1 for r in gen if r["citations"]["citation_ok"]), len(gen)),
        "invalid_markers_questions": [r["id"] for r in gen if r["citations"]["invalid"]],
        "requirements_with_exact_source_cited": _rate(exact_cited, sat),
        "mismatch_questions": [r["id"] for r in gen if any(c in r["validation_initial"]["codes"] for c in ("citation_mismatch", "provision_citation_mismatch"))],
        "discovery_cited_questions": [r["id"] for r in gen if "discovery_cited_for_requirement" in r["validation_initial"]["codes"]],
        "irrelevant_markers_total": sum(r["citations"].get("irrelevant_markers", 0) for r in gen),
        "uncited_requirement_statements": uncited,
        "answers_without_any_marker": [r["id"] for r in gen if not r["citations"].get("markers")],
        "listed_citation_roles": _count(c.get("role") for r in gen for c in r["citations"].get("listed", [])),
    }


def hallucination_results(full: list[dict]) -> dict[str, Any]:
    gen = [r for r in full if r.get("generated")]
    codes: dict[str, int] = {}
    for r in gen:
        for c in r["hallucination"]["codes_raw"]:
            if c in ("asserted_missing_provision", "unsupported_figure", "discovery_cited_for_requirement", "citation_mismatch", "provision_citation_mismatch"):
                codes[c] = codes.get(c, 0) + 1
    return {
        "generated": len(gen),
        "any_raw": _rate(sum(1 for r in gen if r["hallucination"]["any_raw"]), len(gen)),
        "any_final": _rate(sum(1 for r in gen if r["hallucination"]["any_final"]), len(gen)),
        "by_code_raw": codes,
        "fabricated_identifiers": [{"id": r["id"], "identifiers": r["hallucination"]["fabricated_identifiers_raw"]} for r in gen if r["hallucination"]["fabricated_identifiers_raw"]],
        "questions_raw": [r["id"] for r in gen if r["hallucination"]["any_raw"]],
        "questions_final": [r["id"] for r in gen if r["hallucination"]["any_final"]],
        "by_category_raw": _count(r["category"] for r in gen if r["hallucination"]["any_raw"]),
    }


def refusal_results(full: list[dict], examples: dict[str, Stage5Example]) -> dict[str, Any]:
    rows = [r for r in full if "refusal" in r]
    expected_refuse = [r for r in rows if examples[r["id"]].expected_behavior == "refuse"]
    expected_answer = [r for r in rows if examples[r["id"]].expected_behavior != "refuse"]
    return {
        "questions": len(rows),
        "correct_refusal": _rate(sum(1 for r in expected_refuse if r["refusal"]["correct_refusal"]), len(expected_refuse)),
        "false_answer": [r["id"] for r in expected_refuse if r["refusal"]["false_answer"]],
        "false_refusal_raw": [r["id"] for r in expected_answer if r["refusal"]["false_refusal"]],
        "false_refusal_final": [r["id"] for r in expected_answer if r["refusal"].get("final_false_refusal")],
        "false_refusal_rate_raw": _rate(sum(1 for r in expected_answer if r["refusal"]["false_refusal"]), len(expected_answer)),
        "deterministic_refusals": [r["id"] for r in rows if r["refusal"].get("deterministic_refusal")],
        "by_expected_behavior": {b: _count(r["refusal"]["raw_class"] for r in rows if examples[r["id"]].expected_behavior == b) for b in ("answer", "partial", "refuse", "general", "guidance")},
    }


def domain_boundary_results(full: list[dict], evidence: dict[str, EvidenceRecord], examples: dict[str, Stage5Example]) -> dict[str, Any]:
    rows = [r for r in full if examples[r["id"]].domain in ("out_of_domain", "mixed")]
    per = []
    for r in rows:
        ev = evidence.get(r["id"])
        tiers = ev.retrieval["tier_counts"] if ev else {}
        leak = r.get("domain", {}).get("leak_raw", False)
        if examples[r["id"]].domain == "out_of_domain":
            attribution = "generation" if leak else "none"
            if leak:
                attribution += " (validator caught)" if not r.get("valid_raw", True) else " (validator gap: no requested provision or figure to check)"
        else:
            attribution = "mixed question handled" if r.get("valid_raw") else "generation"
        per.append({"id": r["id"], "domain": examples[r["id"]].domain, "leak_raw": leak, "leak_final": r.get("domain", {}).get("leak_final", False),
                    "retrieved_tiers": tiers, "raw_class": r["refusal"]["raw_class"], "attribution": attribution, "answer_raw": (r.get("answer_raw") or "")[:200]})
    ood = [p for p in per if p["domain"] == "out_of_domain"]
    return {
        "questions": len(rows),
        "out_of_domain_leak_raw": _rate(sum(1 for p in ood if p["leak_raw"]), len(ood)),
        "out_of_domain_leak_final": _rate(sum(1 for p in ood if p["leak_final"]), len(ood)),
        "attribution": _count(p["attribution"] for p in per),
        "per_question": per,
        "note": "Retrieval always returns something for these questions (discovery tier); the leak is a generation behaviour and the deterministic validator has no identity or figure to reject it with. An intent/domain classifier before generation is the architectural fix, not a keyword rule.",
    }


def latency_results(full: list[dict], evidence: dict[str, EvidenceRecord]) -> dict[str, Any]:
    def stats(values: list[float]) -> dict[str, float | None]:
        return {"n": len(values), "p50": _pct(values, 50), "p95": _pct(values, 95), "max": _pct(values, 100)}
    gen = [r for r in full if r.get("generated")]
    groups = {"all": full, "single_or_general": [r for r in full if r["category"] in ("single", "parent", "general", "guidance", "refusal", "citation", "adversarial", "domain_boundary")],
              "multi_range_long": [r for r in full if r["category"] in ("multi", "range", "long", "section", "missing")]}
    out: dict[str, Any] = {"phases_ms": {}, "by_group_total_ms": {}}
    out["phases_ms"]["planning"] = stats([ev.timings_ms["planning_ms"] for ev in evidence.values()])
    out["phases_ms"]["retrieval"] = stats([ev.timings_ms["retrieval_ms"] for ev in evidence.values()])
    out["phases_ms"]["coverage_selection"] = stats([ev.timings_ms["coverage_selection_ms"] for ev in evidence.values()])
    out["phases_ms"]["generation"] = stats([r["timings_ms"].get("generation_ms", 0.0) for r in gen])
    out["phases_ms"]["validation"] = stats([r["timings_ms"].get("validation_ms", 0.0) for r in gen])
    out["phases_ms"]["end_to_end"] = stats([r["timings_ms"].get("total_ms", 0.0) for r in full if r.get("timings_ms")])
    for name, rows in groups.items():
        out["by_group_total_ms"][name] = stats([r["timings_ms"].get("total_ms", 0.0) for r in rows if r.get("timings_ms")])
    out["tokens_per_second"] = round(statistics.median([r["tokens"]["generated"] / (r["timings_ms"]["generation_ms"] / 1000) for r in gen if r["timings_ms"].get("generation_ms") and r["tokens"].get("generated")]), 2) if gen else None
    return out


def repair_results(full: list[dict]) -> dict[str, Any]:
    gen = [r for r in full if r.get("generated")]
    repaired = [r for r in gen if r.get("repair")]
    return {
        "generated": len(gen), "repaired": len(repaired), "repair_frequency": _rate(len(repaired), len(gen)),
        "valid_before_repair": sum(1 for r in gen if r["valid_raw"]),
        "valid_only_after_repair": sum(1 for r in gen if r["valid_only_after_repair"]),
        "repair_failed": [r["id"] for r in repaired if not r["valid_final"]],
        "by_repair": _count(r["repair"] for r in repaired),
        "note": "valid_only_after_repair answers were produced by the deterministic layer, not by the model",
    }


def failure_analysis(examples: dict[str, Stage5Example], evidence: dict[str, EvidenceRecord], full: list[dict], controlled: list[dict]) -> dict[str, Any]:
    fb, cb = _by_id(full), _by_id(controlled)
    rows = [localize(ex, evidence.get(qid), fb.get(qid), cb.get(qid)) for qid, ex in examples.items()]
    for r in rows:
        r["category"] = examples[r["id"]].category
    return {
        "by_layer": _count(r["layer"] for r in rows),
        "by_layer_and_category": {layer: _count(r["category"] for r in rows if r["layer"] == layer) for layer in {r["layer"] for r in rows}},
        "failures": [r for r in rows if r["layer"] not in (LAYER_NONE, "not_run")],
        "soft": [r for r in rows if r.get("soft")],
        "per_question": rows,
    }


def _correct(r: dict, ex: Stage5Example, stage: str) -> tuple[bool, list[str]]:
    """Conservative composite: deterministic checks + expected terms + the claim heuristic.

    `stage` is "raw" (the model's own text) or "final" (after deterministic
    repair). This is not a human correctness judgment: it can only fail an
    answer for a reason a machine established, so "correct" here means
    "nothing that can be checked is wrong".
    """
    if not r.get("generated"):
        expected_deterministic = ex.expected_behavior == "refuse" and str(r.get("skipped_reason")) in ("refuse_unsupported", "no_context", "refuse_out_of_scope")
        return (bool(expected_deterministic), [] if expected_deterministic else [f"no generation: {r.get('skipped_reason')}"])
    fail: list[str] = []
    val = r["validation_initial"] if stage == "raw" else r["validation_final"]
    if not (val or {}).get("ok"):
        fail.append("validator: " + ",".join((val or {}).get("codes", [])))
    comp, hall, ref = r["completeness"], r["hallucination"], r["refusal"]
    if comp.get("all_addressed_" + stage) is False:
        missing = [i for i in comp["expected_exact_ids"] if i not in comp.get("addressed_" + stage, [])]
        fail.append(f"incomplete: {missing}")
    if hall.get("any_" + stage):
        fail.append("unsupported content")
    if stage == "raw" and (ref.get("false_refusal") or ref.get("false_answer")):
        fail.append("false refusal" if ref.get("false_refusal") else "answered without support")
    if stage == "final" and ref.get("final_false_refusal"):
        fail.append("false refusal")
    recall = comp.get("term_recall_" + stage)
    if recall is not None and recall < 1.0:
        absent = [t for t in comp["terms_expected"] if t not in comp.get("terms_found_" + stage, [])]
        fail.append(f"expected terms missing: {absent}")
    block = (r.get("faithfulness") if stage == "raw" else r.get("faithfulness_final")) or {}
    if (block.get("counts") or {}).get("NO"):
        fail.append("claim not supported by its cited source")
    if r.get("domain", {}).get("leak_" + stage):
        fail.append("out-of-domain content")
    return (not fail, fail)


def correctness_results(full: list[dict], examples: dict[str, Stage5Example]) -> dict[str, Any]:
    rows = []
    for r in full:
        ex = examples[r["id"]]
        raw_ok, raw_why = _correct(r, ex, "raw")
        fin_ok, fin_why = _correct(r, ex, "final")
        rows.append({"id": r["id"], "category": r["category"], "generated": bool(r.get("generated")),
                     "raw_correct": raw_ok, "raw_reasons": raw_why, "final_correct": fin_ok,
                     "final_reasons": fin_why, "repaired": bool(r.get("repair"))})
    gen = [x for x in rows if x["generated"]]
    return {
        "questions": len(rows),
        "raw_correct": _rate(sum(1 for x in rows if x["raw_correct"]), len(rows)),
        "final_correct": _rate(sum(1 for x in rows if x["final_correct"]), len(rows)),
        "raw_correct_generated_only": _rate(sum(1 for x in gen if x["raw_correct"]), len(gen)),
        "final_correct_generated_only": _rate(sum(1 for x in gen if x["final_correct"]), len(gen)),
        "correct_only_after_repair": [x["id"] for x in rows if x["final_correct"] and not x["raw_correct"]],
        "incorrect_after_repair": [x["id"] for x in rows if not x["final_correct"]],
        "definition": ("deterministic validation passed + every requested provision addressed + no unsupported content + "
                       "refusal expectation met + expected terms present + no claim flagged unsupported; a machine cannot "
                       "certify that the remaining wording is right"),
        "per_question": rows,
    }


def behaviour_results(full: list[dict], examples: dict[str, Stage5Example]) -> dict[str, Any]:
    """Accuracy on the question shapes Stage 5 exists to measure."""
    def block(cats: tuple) -> dict[str, Any]:
        rows = [r for r in full if r["category"] in cats]
        gen = [r for r in rows if r.get("generated")]
        return {
            "questions": len(rows), "generated": len(gen),
            "all_provisions_addressed_raw": _rate(sum(1 for r in gen if r["completeness"].get("all_addressed_raw")), len(gen)),
            "all_provisions_addressed_final": _rate(sum(1 for r in gen if r["completeness"].get("all_addressed_final")), len(gen)),
            "valid_raw": _rate(sum(1 for r in gen if r.get("valid_raw")), len(gen)),
            "hallucination_raw": _rate(sum(1 for r in gen if r["hallucination"].get("any_raw")), len(gen)),
            "ids": [r["id"] for r in rows],
        }
    missing = [r for r in full if examples[r["id"]].expected_missing]
    stated = [all(lab in (r.get("answer_final") or "") for lab in examples[r["id"]].expected_missing) for r in missing]
    return {
        "multi_provision": block(("multi",)),
        "range": block(("range", "long")),
        "partial_or_missing": {
            **block(("missing", "nonexistent")),
            "absent_provision_named_in_final_answer": _rate(sum(1 for x in stated if x), len(stated)),
            "invented_content_for_absent_provision_raw": [r["id"] for r in missing if "asserted_missing_provision" in (r.get("validation_initial") or {}).get("codes", [])],
        },
        "adversarial": block(("adversarial",)),
        "general_and_guidance": block(("general", "guidance")),
    }


def stage5_summary(run_id: str, dataset_meta: dict, metrics: dict[str, Any]) -> dict[str, Any]:
    g = metrics["generation_results"]["modes"]["full_pipeline_raw"]
    c = metrics["generation_results"]["modes"]["controlled_evidence_raw"]
    return {
        "run_id": run_id, "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dataset": dataset_meta,
        "questions": metrics["retrieval_results"]["questions"],
        "retrieval_ok": metrics["retrieval_results"]["retrieval_ok"], "requirement_recall": metrics["retrieval_results"]["requirement_recall"],
        "coverage_ok": metrics["coverage_results"]["coverage_ok"], "selection_ok": metrics["selection_results"]["selection_ok"],
        "generation_valid_raw_full": g["valid_raw"], "generation_valid_final_full": g["valid_final"], "generation_valid_raw_controlled": c["valid_raw"],
        "truncated_full": g["truncated"],
        "faithfulness_supported_ratio": metrics["semantic_faithfulness_results"]["supported_ratio"],
        "hallucination_any_raw": metrics["hallucination_results"]["any_raw"], "hallucination_any_final": metrics["hallucination_results"]["any_final"],
        "false_refusal_rate_raw": metrics["refusal_results"]["false_refusal_rate_raw"], "correct_refusal": metrics["refusal_results"]["correct_refusal"],
        "domain_leak_raw": metrics["domain_boundary_results"]["out_of_domain_leak_raw"],
        "latency_p50_total_ms": metrics["latency_results"]["phases_ms"]["end_to_end"]["p50"], "latency_p95_total_ms": metrics["latency_results"]["phases_ms"]["end_to_end"]["p95"],
        "repair_frequency": metrics["repair_results"]["repair_frequency"],
        "answer_correct_raw": metrics["correctness_results"]["raw_correct"],
        "answer_correct_final": metrics["correctness_results"]["final_correct"],
        "faithfulness_supported_ratio_final": metrics["semantic_faithfulness_results"]["final_answer"]["supported_ratio"],
        "multi_provision_complete_raw": metrics["behaviour_results"]["multi_provision"]["all_provisions_addressed_raw"],
        "range_complete_raw": metrics["behaviour_results"]["range"]["all_provisions_addressed_raw"],
        "failures_by_layer": metrics["failure_analysis"]["by_layer"],
    }


# ---------------------------------------------------------- training plan


def training_plan(run_id: str, summary: dict[str, Any], analysis: dict[str, Any], examples: dict[str, Stage5Example], full: list[dict]) -> dict[str, Any]:
    fails = analysis["failures"]
    relevant = [f for f in fails if f["layer"] in TRAINING_RELEVANT_LAYERS]
    arch = [f for f in fails if f["layer"] in (LAYER_RETRIEVAL, LAYER_COVERAGE, LAYER_SELECTION)]
    domain = [f for f in fails if f["layer"] == LAYER_DOMAIN]
    generated = sum(1 for r in full if r.get("generated"))
    targets: dict[str, dict[str, Any]] = {}
    for f in relevant:
        t = CATEGORY_TARGET.get(examples[f["id"]].category, "grounded_single_provision")
        d = targets.setdefault(t, {"target": t, "examples": [], "count": 0, "dataset_categories": list(TARGET_CATEGORIES.get(t, ()))})
        d["examples"].append(f["id"])
        d["count"] += 1
    shares = dict(BASE_SHARES)
    total_rel = max(len(relevant), 1)
    for t, d in targets.items():
        boost = min(MAX_BOOST, 0.25 * d["count"] / total_rel)
        cats = d["dataset_categories"]
        for c in cats:
            shares[c] = shares.get(c, 0.0) + boost / len(cats)
    norm = sum(shares.values())
    shares = {k: round(v / norm, 4) for k, v in shares.items()}
    evidence_ok = all(summary.get(k) is None or summary[k] >= 0.9 for k in ("retrieval_ok", "coverage_ok", "selection_ok"))
    threshold = max(3, int(round(0.15 * generated)))
    proceed = evidence_ok and len(relevant) >= threshold
    if not evidence_ok:
        reason = "retrieval, coverage or selection is below 90% on the evaluation set: fix the architecture before training on its outputs"
    elif len(relevant) < threshold:
        reason = f"only {len(relevant)} model-side failures (threshold {threshold}); training is not justified by this evaluation"
    else:
        reason = f"{len(relevant)} of {generated} generated answers fail for model-side reasons with the evidence architecture working"
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stage5_run": run_id,
        "baseline_metrics": {k: summary[k] for k in ("retrieval_ok", "coverage_ok", "selection_ok", "generation_valid_raw_full", "generation_valid_raw_controlled", "hallucination_any_raw", "false_refusal_rate_raw", "faithfulness_supported_ratio", "domain_leak_raw", "truncated_full")},
        "failure_categories": analysis["by_layer"],
        "training_relevant_failures": relevant,
        "candidate_training_targets": sorted(targets.values(), key=lambda d: -d["count"]),
        "training_relevant_examples_count": len(relevant),
        "do_not_train": {
            "architecture_failures": [f["id"] for f in arch],
            "domain_boundary": [f["id"] for f in domain],
            "reason": "retrieval/coverage/selection failures are code paths, not model behaviour; the domain leak needs an intent check before generation, not weight changes",
        },
        "recommended_composition": shares,
        "composition_rationale": "Stage 6 base shares weighted toward multi-provision, range and partial (not-found) answers in the grounded prompt format, with refusal and non-fabrication categories kept; each model-side failure category adds a bounded boost to the dataset categories that train it.",
        "recommended_validation": {
            "task_validation_set": "held-out validation split of the Stage 6 dataset, stratified by category (16 examples)",
            "checkpoint_metric": "task_score = mean of [validator status valid, every requested provision addressed, no unsupported/fabricated content, refusal correctness]; eval_loss only breaks ties",
            "candidate_rule": "a checkpoint is a candidate only if its task_score is at least the base model's on the same examples",
            "final_comparison": "Stage 5 dataset, base vs trained, controlled evidence and full pipeline, raw and repaired kept separate",
        },
        "recommended_early_stopping": {"metric": "eval_loss", "patience_evals": 3, "note": "stopping on loss bounds the run; selection never uses loss alone"},
        "risks": [
            "Stage 12/13 lesson: lower validation loss did not improve the task and taught over-refusal; every candidate must beat the base on task_score",
            "verbatim-style multi-provision targets could bias the model toward quoting; acceptable for a regulatory system, measured by answer length and repair frequency",
            "CPU training reaches roughly 100 optimizer steps overnight; the effect may be small",
            "the Stage 5 set is 50 questions concentrated on part 820 and part 101; improvements there may not generalise",
        ],
        "proceed": proceed, "proceed_reason": reason,
    }


# ----------------------------------------------------------------- report


def render_report(run_id: str, summary: dict[str, Any], m: dict[str, Any], plan: dict[str, Any], examples: dict[str, Stage5Example]) -> str:
    def pct(v):
        return "n/a" if v is None else f"{100 * v:.0f}%"
    r, c, s = m["retrieval_results"], m["coverage_results"], m["selection_results"]
    g = m["generation_results"]["modes"]
    lines = [f"# Stage 5 Final Report ({run_id})", "", f"Dataset: {summary['dataset']['name']} ({summary['questions']} questions, sha256 {summary['dataset']['sha256'][:16]}...). Base Qwen3-0.6B, greedy decoding, default budget. Generated {summary['generated_at_utc']}.", "",
             "## BASELINE PERFORMANCE", "", "| Layer | Metric | Value |", "|---|---|---|",
             f"| Retrieval | questions with every expected provision retrieved exactly | {pct(r['questions_with_full_exact_recall'])} |",
             f"| Retrieval | requirement recall (provisions) | {pct(r['requirement_recall'])} |",
             f"| Retrieval | multi-provision full recall | {pct(r['multi_provision_full_recall'])} |",
             f"| Retrieval | range full recall | {pct(r['range_full_recall'])} |",
             f"| Retrieval | missing provisions correctly absent | {pct(r['missing_provisions_correctly_absent'])} |",
             f"| Coverage | state and missing labels as expected | {pct(c['coverage_ok'])} |",
             f"| Coverage | incomplete requests detected | {pct(c['incomplete_detected'])} |",
             f"| Selection | required exact evidence preserved in context | {pct(s['required_exact_preserved'])} |",
             f"| Selection | deterministic | {pct(s['deterministic'])} |",
             f"| Generation | full pipeline, raw model text valid | {pct(g['full_pipeline_raw']['valid_raw'])} ({g['full_pipeline_raw']['generated']} generated) |",
             f"| Generation | full pipeline, valid after deterministic repair | {pct(g['full_pipeline_raw']['valid_final'])} |",
             f"| Generation | valid ONLY because of repair | {pct(g['full_pipeline_raw']['valid_only_after_repair'])} |",
             f"| Generation | controlled (exact evidence only), raw valid | {pct(g['controlled_evidence_raw']['valid_raw'])} ({g['controlled_evidence_raw']['generated']} generated) |",
             f"| Generation | truncated (full) | {g['full_pipeline_raw']['truncated']} |",
             f"| Faithfulness (raw) | claims supported (heuristic) | {pct(m['semantic_faithfulness_results']['raw_answer']['supported_ratio'])} of {m['semantic_faithfulness_results']['raw_answer']['claims_judged']} judged; {m['semantic_faithfulness_results']['raw_answer']['unsupported']} not supported |",
             f"| Faithfulness (final) | claims supported after repair (heuristic) | {pct(m['semantic_faithfulness_results']['final_answer']['supported_ratio'])} of {m['semantic_faithfulness_results']['final_answer']['claims_judged']} judged; {m['semantic_faithfulness_results']['final_answer']['unsupported']} not supported |",
             f"| Citations | answers with no invalid or mismatched citation | {pct(m['citation_results']['citation_ok'])} |",
             f"| Citations | satisfied provisions whose exact source was cited | {pct(m['citation_results']['requirements_with_exact_source_cited'])} |",
             f"| Hallucination | raw answers with unsupported content | {pct(m['hallucination_results']['any_raw'])} |",
             f"| Hallucination | after repair | {pct(m['hallucination_results']['any_final'])} |",
             f"| Refusal | correct refusals | {pct(m['refusal_results']['correct_refusal'])}; false refusals raw: {m['refusal_results']['false_refusal_raw']} |",
             f"| Domain boundary | out-of-domain leak (raw) | {pct(m['domain_boundary_results']['out_of_domain_leak_raw'])} |",
             f"| Latency | end-to-end p50 / p95 / max (ms) | {m['latency_results']['phases_ms']['end_to_end']['p50']} / {m['latency_results']['phases_ms']['end_to_end']['p95']} / {m['latency_results']['phases_ms']['end_to_end']['max']} |",
             f"| Latency | generation p50 / p95 (ms) | {m['latency_results']['phases_ms']['generation']['p50']} / {m['latency_results']['phases_ms']['generation']['p95']} |",
             f"| Repair | frequency | {pct(m['repair_results']['repair_frequency'])}; failed repairs: {m['repair_results']['repair_failed']} |",
             f"| Answer correctness | RAW model answer, all machine checks pass | {pct(m['correctness_results']['raw_correct'])} ({m['correctness_results']['questions']} questions) |",
             f"| Answer correctness | FINAL answer after deterministic repair | {pct(m['correctness_results']['final_correct'])}; correct only because of repair: {m['correctness_results']['correct_only_after_repair']} |",
             f"| Multi-provision | every requested provision addressed (raw) | {pct(m['behaviour_results']['multi_provision']['all_provisions_addressed_raw'])} of {m['behaviour_results']['multi_provision']['generated']} |",
             f"| Range | every requested provision addressed (raw) | {pct(m['behaviour_results']['range']['all_provisions_addressed_raw'])} of {m['behaviour_results']['range']['generated']} |",
             f"| Partial / missing | absent provision named in the final answer | {pct(m['behaviour_results']['partial_or_missing']['absent_provision_named_in_final_answer'])}; invented content for it (raw): {m['behaviour_results']['partial_or_missing']['invented_content_for_absent_provision_raw']} |",
             f"| Adversarial | raw answers with unsupported content | {pct(m['behaviour_results']['adversarial']['hallucination_raw'])} of {m['behaviour_results']['adversarial']['generated']} |",
             "", "## WHAT EACH COLUMN MEANS", "",
             "The report never merges these five:", "",
             "1. **Raw model answer** - the text Qwen produced, before anything touched it.",
             "2. **Validator result** - what the deterministic checks said about that raw text.",
             "3. **Repaired answer** - the raw text after the deterministic repair replaced or completed it from verbatim source text.",
             "4. **Semantic correctness of the raw answer** - the machine-checkable composite over the raw text.",
             "5. **Semantic correctness of the final answer** - the same composite over the repaired text; a pass here is a property of the pipeline, not of the model.",
             "",
             f"Answers valid only because of repair: {m['generation_results']['modes']['full_pipeline_raw']['valid_only_after_repair']} of the generated set. "
             f"Answers correct only because of repair: {m['correctness_results']['correct_only_after_repair']}.",
             "", "## FAILURES BY LAYER", "", "| Layer | Questions |", "|---|---|"]
    for layer, n in sorted(m["failure_analysis"]["by_layer"].items()):
        lines.append(f"| {layer} | {n} |")
    lines += ["", "### Failing questions", ""]
    for f in m["failure_analysis"]["failures"]:
        lines.append(f"- **{f['id']}** ({f['category']}, layer `{f['layer']}`): {'; '.join(f['reasons'])}")
    lines += ["", "## KNOWN LIMITATIONS", "",
              "- Faithfulness is heuristic (word overlap plus deterministic checks); SUPPORTED is unproven, NOT SUPPORTED is reliable.",
              "- The dataset is 50 questions concentrated on parts 820 and 101; rates have wide confidence intervals.",
              "- Domain-boundary questions cannot be rejected deterministically when no provision or figure is involved; the validator reports them but cannot fix them.",
              "- Latency is CPU-bound; generation dominates every end-to-end number.",
              "", "## TRAINING-RELEVANT FAILURES", "",
              f"Model-side failures (layers generation / generation_context): {plan['training_relevant_examples_count']}. Architecture failures (not trainable): {len(plan['do_not_train']['architecture_failures'])}. Domain leaks (not trainable here): {len(plan['do_not_train']['domain_boundary'])}.", ""]
    for t in plan["candidate_training_targets"]:
        lines.append(f"- {t['target']}: {t['count']} question(s) {t['examples']} -> dataset categories {t['dataset_categories']}")
    lines += ["", f"**Stage 6 recommendation:** {'PROCEED' if plan['proceed'] else 'DO NOT PROCEED'}. {plan['proceed_reason']}", ""]
    return "\n".join(lines)
