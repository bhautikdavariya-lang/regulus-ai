"""Full diagnostic trace of one answered question (Stage 4 failure observatory).

`build_trace(out, ...)` turns a RagAnswer into one JSON-serialisable record of
every stage: question, intent/scope, plan, retrieval (queries, parameters, every
candidate in order with method and score), selected context (hashed), prompt
(hashed), model identity, timings, RAW model output, initial validation, repair
input and type, final validation, final answer, citations and sufficiency.

It only reads what the pipeline already produced. It records no secrets:
no database URL, no environment, no credentials, no user identity. Source
texts appear as hashes (the full text is in the verified database); the model
output and the final answer are recorded in full because they are what is
being diagnosed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from regulus.planning import plan_query
from regulus.planning.intent import analyze_question
from regulus.rag.generation import build_grounded_messages
from regulus.rag.prompt import build_messages
from regulus.observability.sufficiency import assess

TRACE_VERSION = 2  # 2: Stage 5 answerability / fallback fields


def sha256(obj: Any) -> str:
    data = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_trace(out, *, question_id: str, generator_info: dict | None = None, config: dict | None = None,
                tokenizer=None) -> dict[str, Any]:
    m = out.metadata
    question = out.question
    plan = plan_query(question)
    analysis = analyze_question(plan)  # diagnostic: computed even when the pipeline mode does not act on it
    package = out.package
    if package is not None and out.model_called:
        messages = build_grounded_messages(package)
    elif out.model_called:
        messages = build_messages(question, out.context.text)
    else:
        messages = None
    context_text = out.context.text
    gen = m.get("generation") or {}
    validation = m.get("validation") or {}
    retrieval = m.get("retrieval") or {}
    suff = assess(question, package, out.coverage, no_context=out.no_context, deterministic_action=m.get("coverage_action"))
    return {
        "trace_version": TRACE_VERSION,
        "question_id": question_id,
        "question": question,
        "question_hash": sha256(question),
        # -- intent / scope (diagnostic analysis; `acted_on` says whether this pipeline mode used it)
        "intent_type": analysis.question_type, "is_yes_no": analysis.is_yes_no,
        "scope": analysis.scope_status, "scope_reason": analysis.scope_reason, "out_of_scope_part": analysis.out_of_scope_part,
        "intent_scope_acted_on": m.get("question_analysis") is not None,
        "answer_shape": m.get("answer_shape"),
        # -- retrieval
        "retrieval_query": {"question_text": question, "requested_provisions": [r.canonical for r in plan.requirements],
                            "docket": plan.docket, "fallback_terms": retrieval.get("fallback_terms", []),
                            "retrieval_mode": retrieval.get("retrieval_mode"), "fallback_used": retrieval.get("fallback_used")},
        "retrieval_parameters": {k: (config or {}).get(k) for k in ("top_k", "corpus", "min_trigram_similarity",
                                                                     "exclude_contextual_only", "context")},
        "retrieval_counts": m.get("retrieval_counts"),
        "retrieved": [{"order": i, "key": r.key, "citation": r.citation.label, "title": r.citation.heading or r.citation.document_title,
                       "corpus": r.corpus, "method": r.retrieval_method, "score": round(r.relevance_score, 4)}
                      for i, r in enumerate(out.retrieved_results, start=1)],
        "candidates": len((m.get("evidence") or {}).get("evidence") or []),
        "coverage": {k: (m.get("coverage") or {}).get(k) for k in ("state", "missing_labels")} if m.get("coverage") else None,
        # -- context
        "selected_context": [{"index": s.index, "key": s.result.key, "citation": s.result.citation.label, "tier": s.tier,
                              "method": s.result.retrieval_method, "chars": len(s.text), "text_sha256": sha256(s.text)}
                             for s in out.context.sources],
        "selection_dropped": len((m.get("selection") or {}).get("dropped") or []),
        "context_hash": sha256(context_text),
        "context_chars": len(context_text),
        "context_token_count": len(tokenizer(context_text)["input_ids"]) if tokenizer is not None else None,
        "evidence_sufficiency": suff,
        # -- prompt
        "prompt_hash": sha256(messages) if messages else None,
        "prompt_token_count": gen.get("prompt_tokens"),
        "max_new_tokens": gen.get("max_new_tokens"),
        # -- model
        "model": {k: (generator_info or {}).get(k) for k in ("model_id", "model_revision", "device", "dtype")},
        "model_called": out.model_called,
        "timings_ms": out.timings_ms,
        "output_token_count": gen.get("generated_tokens"), "finished": gen.get("finished"), "stop_reason": gen.get("stop_reason"),
        # -- the text at every stage
        "raw_model_output": m.get("raw_model_output"),
        "normalization": m.get("normalization"),
        "initial_validation": validation.get("initial"),
        "repair_attempted": m.get("repair_input") is not None,
        "repair_type": validation.get("repair"),
        "repair_input": m.get("repair_input"),
        "repair_output": m.get("repair_output", out.answer if validation.get("repair") else None),
        "final_validation": validation.get("final"),
        "final_answer": out.answer,
        "final_citations": [{"index": c.index, "label": c.label, "role": c.role, "tier": c.tier} for c in out.citations],
        "citation_support": m.get("citation_support"),
        "coverage_action": m.get("coverage_action"),
        # -- Stage 5 answerability gate and safe fallback (None on runs recorded before Stage 5)
        "answerability_state": (m.get("answerability") or {}).get("state"),
        "answerability_reason": (m.get("answerability") or {}).get("reason"),
        "answerability_confidence": (m.get("answerability") or {}).get("confidence"),
        "answerability_signals": (m.get("answerability") or {}).get("signals"),
        "answerability_acted_on": (m.get("answerability") or {}).get("acted_on"),
        "generation_called": m.get("generation_called", out.model_called),
        "generation_blocked": m.get("generation_blocked"),
        "block_reason": m.get("block_reason"),
        "fallback_type": m.get("fallback_type"),
        "fallback_reason": m.get("fallback_reason"),
        "final_output_hash": sha256(out.answer),
    }
