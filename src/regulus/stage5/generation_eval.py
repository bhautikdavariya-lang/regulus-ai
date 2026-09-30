"""Stage 5 generation phases: the model on controlled evidence, the full
pipeline raw, and the full pipeline after deterministic repair.

Two generations per question at most (greedy decoding, so a third run for
"repaired" would reproduce the second): the repaired answer is derived from
the raw one with the pipeline's own repair function. Every record keeps the
raw text, the repaired text and both validation reports, so "valid after
repair" is never confused with "generated correctly".

Claim-level faithfulness is heuristic and labelled as such: a sentence is
SUPPORTED when it cites an exact source and shares most of its content
words with it and no deterministic check failed on it; NOT SUPPORTED when
a deterministic check failed on it or it shares almost nothing with what
it cites; UNCERTAIN otherwise. Refusals and not-found statements are
deterministic and counted separately.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from regulus.evaluation.grounding_eval import REFUSAL, classify_answer, split_sentences
from regulus.inference.types import GenerationResult
from regulus.planning import plan_query
from regulus.planning.intent import analyze_question
from regulus.planning.plan import QueryPlan
from regulus.rag.coverage import STATE_INCOMPLETE, CoverageReport
from regulus.rag.generation import GenerationPackage, build_grounded_messages, build_package
from regulus.rag.pipeline import RagPipeline
from regulus.rag.prompt import coverage_note, unresolved_provisions_statement
from regulus.rag.selection import SelectedEvidence, Selection
from regulus.rag.validation import (
    ASSERTED_MISSING_PROVISION,
    CITATION_MISMATCH,
    DISCOVERY_CITED_FOR_REQUIREMENT,
    MARK_RE,
    PROVISION_CITATION_MISMATCH,
    UNSUPPORTED_FIGURE,
    ValidationReport,
    _content_words,
    _is_negated,
    _mention_patterns,
    _mentions,
    attach_trailing_markers,
    validate_answer,
)
from regulus.retrieval.evidence import TIER_EXACT
from regulus.retrieval.references import parse_cfr_references
from regulus.stage5.dataset import Stage5Example
from regulus.stage5.evidence_eval import EvidenceOutcome

MODE_FULL = "full"
MODE_CONTROLLED = "controlled"
HALLUCINATION_CODES = (ASSERTED_MISSING_PROVISION, UNSUPPORTED_FIGURE, DISCOVERY_CITED_FOR_REQUIREMENT, CITATION_MISMATCH, PROVISION_CITATION_MISMATCH)
SUPPORTED_OVERLAP = 0.5
UNSUPPORTED_OVERLAP = 0.25


# ------------------------------------------------------------- analysis


def fabricated_identifiers(answer: str, package: GenerationPackage) -> list[str]:
    """CFR labels in the answer that are neither a supplied source nor a requested provision
    (nor a parent/child of one). Statements that say a provision was not found are excluded."""
    known: set[tuple[str, str | None, str]] = set()
    for s in package.sources:
        f = s.citation_fields or {}
        if s.corpus == "ecfr" and f.get("section"):
            known.add((str(f.get("title") or "21"), f["section"], f.get("paragraph") or ""))
    for _, label in package.requirements:
        for ref in parse_cfr_references(label):
            known.add((ref.title, ref.section, ref.paragraph_path))
    out: list[str] = []
    for sentence in split_sentences(attach_trailing_markers(answer or "")):
        if _is_negated(sentence):
            continue
        for ref in parse_cfr_references(sentence):
            if ref.section is None:
                continue
            ident = (ref.title, ref.section, ref.paragraph_path)
            related = any(
                k[0] == ident[0] and k[1] == ident[1] and (k[2] == ident[2] or not k[2] or not ident[2] or k[2].startswith(ident[2] + "(") or ident[2].startswith(k[2] + "("))
                for k in known
            )
            if not related and ref.canonical not in out:
                out.append(ref.canonical)
    return out


def claims(answer: str, package: GenerationPackage, report: ValidationReport) -> list[dict[str, Any]]:
    """Claim-level representation of an answer (see module docstring)."""
    by_index = {s.index: s for s in package.sources}
    patterns = _mention_patterns(package)
    flagged = {p.sentence for p in report.problems if p.severity == "error" and p.sentence}
    out: list[dict[str, Any]] = []
    for sentence in split_sentences(attach_trailing_markers(answer or "")):
        marks = [int(m) for m in MARK_RE.findall(sentence) if int(m) in by_index]
        provisions = [rid for rid in package.requirement_labels if _mentions(sentence, patterns.get(rid, []))]
        lower = sentence.lower()
        if classify_answer(sentence) == REFUSAL and not marks and not provisions:
            ctype, supported, overlap = "refusal", "N/A", None
        elif provisions and _is_negated(sentence):
            ctype, supported, overlap = "not_found", "N/A", None
        else:
            ctype = "provision_statement" if provisions or any(by_index[i].tier == TIER_EXACT for i in marks) else "general_statement"
            words = _content_words(MARK_RE.sub("", sentence))
            targets = [by_index[i] for i in marks] or [s for rid in provisions for s in package.exact_sources_for(rid)]
            overlap = max((len(words & _content_words(s.text)) / len(words) for s in targets), default=None) if words else None
            if sentence in flagged:
                supported = "NO"
            elif overlap is None:
                supported = "UNCERTAIN"
            elif overlap >= SUPPORTED_OVERLAP and marks:
                supported = "YES"
            elif overlap < UNSUPPORTED_OVERLAP:
                supported = "NO"
            else:
                supported = "UNCERTAIN"
        out.append({
            "claim": sentence[:300], "type": ctype, "provisions": provisions, "cited": marks,
            "cited_tiers": [by_index[i].tier for i in marks], "overlap": round(overlap, 3) if overlap is not None else None,
            "supported": supported,
        })
    return out


def _tokens_for(report: ValidationReport | None, generation: dict[str, Any]) -> dict[str, Any]:
    return {"cap": generation.get("max_new_tokens"), "generated": generation.get("generated_tokens"), "finished": generation.get("finished"),
            "prompt_tokens": generation.get("prompt_tokens"), "truncated": bool(report.truncated) if report else None}


def _refusal_block(ex: Stage5Example, raw: str, final: str, coverage_action: str | None) -> dict[str, Any]:
    raw_class = classify_answer(raw) if raw else REFUSAL
    final_class = classify_answer(final) if final else REFUSAL
    # "refuse_out_of_scope": answer-quality Stage 3 declines a named non-U.S. framework without the model
    # "blocked_*": the Stage 5 answerability gate declined before generation
    deterministic_refusal = coverage_action in ("refuse_unsupported", "refuse_out_of_scope") or str(coverage_action or "").startswith("blocked_")
    refused_raw = raw_class == REFUSAL or deterministic_refusal
    expected_refuse = ex.expected_behavior == "refuse"
    return {
        "raw_class": raw_class, "final_class": final_class, "expected": ex.expected_behavior,
        "deterministic_refusal": deterministic_refusal,
        "correct_refusal": expected_refuse and refused_raw,
        "false_refusal": (not expected_refuse) and refused_raw,
        "false_answer": expected_refuse and not refused_raw,
        "final_false_refusal": (not expected_refuse) and (final_class == REFUSAL and not deterministic_refusal),
    }


def _completeness(ex: Stage5Example, package: GenerationPackage, initial: ValidationReport | None, final: ValidationReport | None, raw: str, final_text: str) -> dict[str, Any]:
    labels = package.requirement_labels
    expected_ids = [rid for rid, lab in package.requirements if lab in ex.expected_exact]
    addressed_raw = [rid for rid in (initial.addressed if initial else ()) if rid in expected_ids]
    addressed_final = [rid for rid in (final.addressed if final else ()) if rid in expected_ids]
    terms = [t for t in ex.expected_terms]
    found_raw = [t for t in terms if t.lower() in (raw or "").lower()]
    found_final = [t for t in terms if t.lower() in (final_text or "").lower()]
    return {
        "expected_exact_ids": expected_ids, "expected_exact_labels": [labels[r] for r in expected_ids],
        "addressed_raw": addressed_raw, "addressed_final": addressed_final,
        "all_addressed_raw": len(addressed_raw) == len(expected_ids), "all_addressed_final": len(addressed_final) == len(expected_ids),
        "terms_expected": terms, "terms_found_raw": found_raw, "terms_found_final": found_final,
        "term_recall_raw": (len(found_raw) / len(terms)) if terms else None, "term_recall_final": (len(found_final) / len(terms)) if terms else None,
    }


def _hallucination(package: GenerationPackage, initial: ValidationReport | None, final: ValidationReport | None, raw: str, final_text: str) -> dict[str, Any]:
    codes_raw = list(initial.codes()) if initial else []
    codes_final = list(final.codes()) if final else []
    fab_raw = fabricated_identifiers(raw, package)
    fab_final = fabricated_identifiers(final_text, package)
    flags = {c: (c in codes_raw) for c in HALLUCINATION_CODES}
    return {
        "fabricated_identifiers_raw": fab_raw, "fabricated_identifiers_final": fab_final,
        "codes_raw": codes_raw, "codes_final": codes_final, "flags_raw": flags,
        "any_raw": bool(fab_raw) or any(flags.values()),
        "any_final": bool(fab_final) or any(c in codes_final for c in HALLUCINATION_CODES),
    }


def _citations(out_citations: list, support: dict[str, Any] | None, initial: ValidationReport | None, package: GenerationPackage) -> dict[str, Any]:
    support = support or {}
    by_tier = support.get("by_tier", {})
    exact_cited_for = support.get("exact_source_cited_for", {})
    return {
        "listed": [c.to_dict() if hasattr(c, "to_dict") else c for c in out_citations],
        "markers": support.get("markers", []),
        "invalid": list(initial.invalid_citations) if initial else [],
        "by_tier": by_tier,
        "exact_source_cited_for": exact_cited_for,
        "requirements_with_exact_cited": sum(1 for v in exact_cited_for.values() if v),
        "requirements_satisfied": len(package.satisfied_ids),
        "irrelevant_markers": by_tier.get("supporting", 0) + by_tier.get("discovery", 0),
        "citation_ok": not (initial and initial.invalid_citations) and not any(c in (initial.codes() if initial else ()) for c in (CITATION_MISMATCH, PROVISION_CITATION_MISMATCH, DISCOVERY_CITED_FOR_REQUIREMENT)),
    }


def selected_evidence_ids(package: GenerationPackage) -> list[str]:
    """Evidence ids of the sources placed in this answer's prompt, in prompt
    order, so selected_ids[i] is the source the model cites as [i + 1]."""
    return [s.evidence_id for s in sorted(package.sources, key=lambda s: s.index)]


# ------------------------------------------------------------- execution


def controlled_selection(selection: Selection) -> Selection:
    """Only the required (protected) evidence, re-indexed 1..n: the 'perfect evidence' condition."""
    kept = [s for s in selection.selected if s.protected]
    items = tuple(SelectedEvidence(i, s.evidence, s.text, s.truncated, True, s.reason, s.chars) for i, s in enumerate(kept, start=1))
    return Selection(items, (), selection.policy, sum(s.chars for s in items), {**selection.diagnostics, "controlled": True, "optional_count": 0})
# (the pipeline's Stage 6 exact-evidence context is regulus.rag.selection.required_only: the same evidence, same order)


def run_controlled(ex: Stage5Example, pipeline: RagPipeline, outcome: EvidenceOutcome) -> dict[str, Any]:
    """The model with exact evidence only. Skipped when there is none to give."""
    plan: QueryPlan = outcome.retrieval.plan
    coverage: CoverageReport = outcome.coverage
    if not coverage.satisfied_ids:
        return {"id": ex.id, "category": ex.category, "mode": MODE_CONTROLLED, "generated": False, "skipped_reason": "no exact evidence to control for"}
    sel = controlled_selection(outcome.selection)
    notes = [coverage_note(coverage.missing_labels)] if coverage.state == STATE_INCOMPLETE else []
    package = build_package(plan, coverage, sel, notes=notes, budget=pipeline.config.generation_budget, answer_shape=pipeline.shape_for(plan))
    t0 = time.perf_counter()
    gen = pipeline._generate(build_grounded_messages(package), package.max_new_tokens)
    gen_ms = round((time.perf_counter() - t0) * 1000, 2)
    raw = gen.response.strip()
    t1 = time.perf_counter()
    initial = validate_answer(raw, package, gen)
    repaired, repair = pipeline.repair_answer(raw, package, initial) if not initial.ok else (raw, None)
    final = validate_answer(repaired, package, gen) if repair else initial
    val_ms = round((time.perf_counter() - t1) * 1000, 2)
    generation = {"max_new_tokens": package.max_new_tokens, "generated_tokens": gen.generated_tokens, "finished": gen.finished, "prompt_tokens": gen.prompt_tokens}
    return _record(ex, MODE_CONTROLLED, package, raw, repaired, repair, initial, final, generation, None, {"generation_ms": gen_ms, "validation_ms": val_ms, "total_ms": gen_ms + val_ms}, None, [], None)


def run_full(ex: Stage5Example, pipeline: RagPipeline) -> dict[str, Any]:
    """The full pipeline: raw model text (validation only) and its deterministic repair."""
    t0 = time.perf_counter()
    out = pipeline.answer(ex.question)
    wall = round(time.perf_counter() - t0, 2)
    package = out.package
    coverage_action = out.metadata.get("coverage_action")
    stage3 = {k: out.metadata.get(k) for k in ("question_analysis", "quality_flags", "normalization") if out.metadata.get(k) is not None}
    if not out.model_called or package is None:
        return {**stage3,
            "id": ex.id, "category": ex.category, "expected_behavior": ex.expected_behavior, "domain": ex.domain, "mode": MODE_FULL,
            "generated": False, "skipped_reason": coverage_action or ("no_context" if out.no_context else "not_generated"),
            "coverage_action": coverage_action, "selected_ids": None,  # no model call, so no evidence was given to one
            "answer_raw": out.answer, "answer_final": out.answer, "repair": None,
            "validation_initial": None, "validation_final": None, "tokens": {}, "timings_ms": out.timings_ms, "wall_s": wall,
            "refusal": _refusal_block(ex, "", out.answer, coverage_action),
            "completeness": {"expected_exact_ids": [], "all_addressed_raw": None, "all_addressed_final": None, "term_recall_final": None},
            "hallucination": {"any_raw": False, "any_final": False, "fabricated_identifiers_raw": [], "codes_raw": []},
            "citations": {"listed": [c.to_dict() for c in out.citations], "citation_ok": True, "markers": [], "by_tier": {}},
            "faithfulness": {"claims": [], "counts": {}},
            "domain": {"leak_raw": False, "leak_final": False},
        }
    initial = out.validation  # validation_behavior="annotate": the raw report
    raw = out.answer
    suffix = unresolved_provisions_statement(out.coverage.missing_labels) if out.coverage is not None and out.coverage.state == STATE_INCOMPLETE else None
    if suffix and raw.endswith(suffix):
        raw = raw[: -len(suffix)].rstrip()
    # Stage 5: a PARTIALLY_ANSWERABLE limitation the pipeline appended is not model text either
    gate = out.metadata.get("answerability") or {}
    limitation = gate.get("limitation") if gate.get("acted_on") else None
    if limitation and raw.endswith(limitation):
        raw = raw[: -len(limitation)].rstrip()
    else:
        limitation = None
    generation = out.metadata.get("generation") or {}
    gen_result = GenerationResult("", raw, generation.get("prompt_tokens") or 0, generation.get("generated_tokens") or 0, 0.0, finished=generation.get("finished"))
    t1 = time.perf_counter()
    if initial is None:
        initial = validate_answer(raw, package, gen_result)
    fallback = None
    if initial.ok:
        repaired, repair, final = raw, None, initial
    else:  # the pipeline's own repair and Stage 5 failed-repair fallback (one implementation)
        plan = plan_query(ex.question)
        shape, analysis = pipeline.question_view(plan)
        r = pipeline.repair_with_fallback(raw, package, initial, gen_result, question=ex.question, plan=plan, shape=shape,
                                          analysis=analysis if analysis is not None else analyze_question(plan),
                                          sources=out.context.sources)
        repaired, repair, final, fallback = r["text"], r["repair"], r["final"], r["fallback_type"]
    if limitation:
        repaired = repaired.rstrip() + "\n" + limitation
    if suffix and not all(f"{label}: not found" in repaired for label in out.coverage.missing_labels):
        repaired = repaired + " " + suffix
    val_ms = round((time.perf_counter() - t1) * 1000, 2)
    timings = dict(out.timings_ms)
    timings["validation_ms"] = round(timings.get("validation_ms", 0.0) + val_ms, 2)
    record = _record(ex, MODE_FULL, package, raw, repaired, repair, initial, final, generation, coverage_action, timings, wall, out.citations, out.metadata.get("citation_support"))
    # answer-quality Stage 3: what the model was given (exact prompt identity) and the structured-mode extras
    record["fallback_type"] = fallback
    record["answerability"] = gate or None
    record["prompt_sha256"] = hashlib.sha256(json.dumps(build_grounded_messages(package), ensure_ascii=False).encode("utf-8")).hexdigest()
    record.update(stage3)
    return record


def _record(ex, mode, package, raw, final_text, repair, initial, final, generation, coverage_action, timings, wall, out_citations, support) -> dict[str, Any]:
    leak_raw = ex.domain == "out_of_domain" and classify_answer(raw) != REFUSAL
    leak_final = ex.domain == "out_of_domain" and classify_answer(final_text) != REFUSAL
    cl = claims(raw, package, initial)
    counts = {k: sum(1 for c in cl if c["supported"] == k) for k in ("YES", "NO", "UNCERTAIN", "N/A")}
    judged = counts["YES"] + counts["NO"] + counts["UNCERTAIN"]
    cl_final = claims(final_text, package, final) if final_text != raw else cl
    counts_final = {k: sum(1 for c in cl_final if c["supported"] == k) for k in ("YES", "NO", "UNCERTAIN", "N/A")}
    judged_final = counts_final["YES"] + counts_final["NO"] + counts_final["UNCERTAIN"]
    return {
        "id": ex.id, "category": ex.category, "expected_behavior": ex.expected_behavior, "domain": ex.domain, "mode": mode,
        "generated": True, "skipped_reason": None, "coverage_action": coverage_action,
        "selected_ids": selected_evidence_ids(package),
        "answer_raw": raw, "answer_final": final_text, "repair": repair,
        "validation_initial": initial.to_dict(), "validation_final": final.to_dict(),
        "valid_raw": initial.ok, "valid_final": final.ok, "valid_only_after_repair": (not initial.ok) and final.ok,
        "tokens": _tokens_for(initial, generation), "timings_ms": timings, "wall_s": wall,
        "refusal": _refusal_block(ex, raw, final_text, coverage_action),
        "completeness": _completeness(ex, package, initial, final, raw, final_text),
        "hallucination": _hallucination(package, initial, final, raw, final_text),
        "citations": _citations(out_citations, support, initial, package),
        "faithfulness": {"claims": cl, "counts": counts, "supported_ratio": round(counts["YES"] / judged, 3) if judged else None},
        "faithfulness_final": {"claims": cl_final, "counts": counts_final, "supported_ratio": round(counts_final["YES"] / judged_final, 3) if judged_final else None},
        "domain": {"leak_raw": leak_raw, "leak_final": leak_final},
        "shape": package.shape, "prompt_chars": len(build_grounded_messages(package)[1]["content"]),
        # Stage 12 (absent when answer_shape="off")
        **({"answer_shape": package.answer_shape.to_dict(),
            "evidence_plan": {"mode": package.answer_plan.mode, "lead_in": list(package.answer_plan.lead_in),
                              "groups": [g.to_dict() for g in package.answer_plan.groups],
                              "context": list(package.answer_plan.context), "related": list(package.answer_plan.related)}}
           if package.answer_plan is not None else {}),
    }
