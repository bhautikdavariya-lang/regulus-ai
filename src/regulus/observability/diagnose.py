"""Failure classification from a trace (Stage 4 failure observatory).

`diagnose(trace, expectation, controlled)` proposes FailureRecords. Every rule
states the trace evidence it used. Rules only fire on facts the trace
establishes; anything else is left for review:

* "proven": decided by deterministic facts (validation codes, coverage, the
  presence of a value in the evidence, a keyed expectation);
* "probable": decided by a heuristic (claim word overlap, fallback relevance);
* a question that fails a keyed expectation with no rule explaining why gets
  UNKNOWN / needs_review, never an invented cause.

The PRIMARY failure is the earliest pipeline module among proven/probable
records: where the answer first became wrong. Severity describes the effect
on the FINAL answer: a failure that validation caught and repair contained
is "minor"; one that reaches the user is "major" or "critical".
"""

from __future__ import annotations

import re
from typing import Any

from regulus.evaluation.grounding_eval import ANSWER, REFUSAL, classify_answer
from regulus.observability.sufficiency import INSUFFICIENT, NOT_FOUND, VALUE_KINDS
from regulus.observability.taxonomy import CONFIDENCE, FAILURE_CLASSES, FailureRecord, module_rank

UNSUPPORTED_CODES = {"unsupported_figure", "asserted_missing_provision", "discovery_cited_for_requirement"}
CITATION_CODES = {"citation_mismatch", "provision_citation_mismatch", "synthesis_citation_gap", "invalid_citation"}
QUALIFIER_CODES = {"qualifier_dropped", "qualifier_misapplied", "applicability_dropped"}
STRUCTURE_CODES = {"evidence_by_evidence", "prompt_echo", "repeated_statement"}
FALLBACK_REPAIRS = {"extractive_replacement", "safe_message", "unvalidated_answer_withheld"}
WITHHELD = {"safe_message", "unvalidated_answer_withheld"}  # the answer was replaced and nothing was quoted
FALLBACK_PREFIX = "The generated answer could not be validated"
_WORD = re.compile(r"[a-z][a-z-]{3,}")
_STOP = {"what", "does", "which", "require", "requires", "required", "requirement", "requirements", "must", "shall", "under",
         "that", "this", "with", "from", "part", "section", "about", "exact", "specific", "their", "there", "these", "those",
         "have", "when", "where", "into", "such", "each", "every", "other", "manufacturer", "manufacturers", "apply", "applies",
         # Stage 5: instruction words say what to do with a provision, not what it is about
         "list", "explain", "describe", "summarize", "summarise", "through", "cite", "compare", "walk", "tell"}


def _codes(v: dict | None) -> set[str]:
    return set((v or {}).get("codes") or [])


def _ok(v: dict | None) -> bool | None:
    return None if v is None else bool(v.get("ok", v.get("status") == "valid"))


def _declined(trace: dict) -> bool:
    if not trace["model_called"] and trace.get("coverage_action") in ("refuse_unsupported", "refuse_out_of_scope", None):
        return True
    if not trace["model_called"] and (trace.get("generation_blocked") or str(trace.get("coverage_action") or "").startswith("blocked_")):
        return True  # Stage 5: the answerability gate declined before generation
    return classify_answer(trace["final_answer"]) != ANSWER


def _topic_words(question: str, out_of_scope_part: str | None = None) -> set[str]:
    """The question's topical words, without numbers, provisions and any declined out-of-scope clause."""
    if out_of_scope_part:
        question = question.replace(out_of_scope_part, " ")
    q = re.sub(r"\b\d+(?:\.\d+)?(?:\([a-z0-9]+\))*", " ", question.lower())
    return set(_WORD.findall(q)) - _STOP


def _value_in(kind: str, text: str) -> bool:
    return bool(next(v for k, _, v in VALUE_KINDS if k == kind).search(text or ""))


def diagnose(trace: dict[str, Any], exp: dict[str, Any], controlled: dict[str, Any] | None = None) -> dict[str, Any]:
    qid = trace["question_id"]
    recs: list[FailureRecord] = []
    raw = trace.get("raw_model_output") or ""
    final = trace.get("final_answer") or ""
    iv, fv = trace.get("initial_validation"), trace.get("final_validation")
    icodes, fcodes = _codes(iv), _codes(fv)
    suff = trace["evidence_sufficiency"]
    behavior = exp.get("expected_behavior")
    keyed = behavior is not None
    declined = _declined(trace)
    fallback = trace.get("repair_type") in FALLBACK_REPAIRS or bool(trace.get("fallback_type")) or final.startswith(FALLBACK_PREFIX)
    blocked = bool(trace.get("generation_blocked")) and not trace["model_called"]

    def add(code, severity, confidence, evidence, notes=""):
        if any(r.failure_class == code for r in recs):
            return  # one record per class per question; the first rule to establish it keeps its evidence
        recs.append(FailureRecord(qid, code, severity, confidence, evidence if isinstance(evidence, list) else [evidence], notes=notes))

    # -- scope
    if behavior == "refuse" and exp.get("category", "").startswith("out_of_scope") and not declined:
        acted = trace.get("intent_scope_acted_on")
        add("F02", "critical", "proven", [f"expected to decline ({exp['source_reference']}); final answer supplies content",
                                          f"diagnostic scope = {trace['scope']}; the pipeline mode {'acted on' if acted else 'did not use'} a scope decision"])
    # -- retrieval: a keyed provision that was not retrieved as exact evidence
    missing_keyed = [lab for lab in exp.get("expected_exact") or [] if lab in ((trace.get("coverage") or {}).get("missing_labels") or [])]
    if missing_keyed:
        add("F03", "major", "proven", f"expected provision(s) with no exact evidence: {', '.join(missing_keyed)}")
    # -- sufficiency: the evidence cannot support the requested claim, and the model answered anyway
    kind = suff.get("requested_value_kind")
    if trace["model_called"] and suff["state"] in (INSUFFICIENT, NOT_FOUND) and classify_answer(raw) == ANSWER:
        ev = [f"evidence sufficiency = {suff['state']}: {'; '.join(suff['reasons'])}"]
        conf = "proven" if kind else "probable"
        if kind and _value_in(kind, raw):
            ev.append(f"the raw answer states a {kind.replace('_', ' ')} anyway")
        add("F05", "major", conf, ev + ["no stage detected the insufficiency before or after generation"])
    # -- generation
    if icodes & UNSUPPORTED_CODES:
        add("F07", "major", "proven", f"initial validation: {', '.join(sorted(icodes & UNSUPPORTED_CODES))}")
    elif trace.get("fabricated_identifiers_raw"):
        add("F07", "major", "proven", f"raw answer names provisions not in the evidence: {trace['fabricated_identifiers_raw']}")
    elif exp.get("forbidden_value_kind") and _value_in(exp["forbidden_value_kind"], raw):
        add("F07", "major", "proven", f"raw answer states a {exp['forbidden_value_kind']}; the database has none for this provision ({exp['verified_status']})")
    elif trace.get("premise_unsupported_terms"):
        add("F07", "major", "probable", f"yes/no question: the raw answer affirms terms no supplied source contains: {trace['premise_unsupported_terms']}")
    elif (trace.get("claims_raw") or {}).get("NO"):
        # word overlap is not entailment: a reason to look, never a verdict on its own
        add("F07", "major", "needs_review", f"{trace['claims_raw']['NO']} raw claim(s) share almost no words with the source they cite (heuristic)")
    if icodes & QUALIFIER_CODES:
        add("F08", "major", "probable", f"initial validation: {', '.join(sorted(icodes & QUALIFIER_CODES))} (warnings)")
    if icodes & CITATION_CODES:
        add("F09", "major", "proven", f"initial validation: {', '.join(sorted(icodes & CITATION_CODES))}")
    if icodes & STRUCTURE_CODES or (trace.get("normalization") or {}).get("markers_moved"):
        add("F14", "minor", "proven", f"structure: {', '.join(sorted(icodes & STRUCTURE_CODES)) or 'citation markers written at line starts'}")
    if "truncated" in icodes or "degenerate_output" in icodes:
        add("F18", "major", "proven", f"initial validation: {', '.join(sorted(icodes & {'truncated', 'degenerate_output'}))}")
    # -- completeness against the keyed expectation (raw answer)
    missing_terms = [t for t in exp.get("expected_terms") or [] if t.lower() not in final.lower()]
    missing_points = [p for p in exp.get("expected_points") or [] if not any(a.lower() in final.lower() for a in p)]
    if keyed and behavior != "refuse" and not declined and (missing_terms or missing_points):
        add("F15", "major", "proven", [f"final answer lacks expected term(s): {missing_terms}" if missing_terms else "",
                                       f"final answer lacks {len(missing_points)} expected point(s)" if missing_points else ""])
    # -- validation false negative: validation passed a raw answer that fails a keyed or proven check
    raw_bad = any(r.failure_class in ("F02", "F05", "F07") and r.confidence != "needs_review" for r in recs) or (keyed and behavior == "refuse" and classify_answer(raw) == ANSWER)
    if iv is not None and iv.get("ok") and raw_bad:
        add("F11", "major", "proven", "initial validation passed a raw answer that the records above show is wrong")
    # a quoting fallback: Stage 4 extractive replacement, or the Stage 5 verbatim-provision fallback (a safe message quotes nothing)
    quoting_fallback = trace.get("repair_type") == "extractive_replacement" or trace.get("fallback_type") == "verbatim_requested_provision"
    if quoting_fallback and fv is not None and fv.get("ok") and trace["model_called"]:
        topic = _topic_words(trace["question"], trace.get("out_of_scope_part"))
        quoted = set(_WORD.findall(final.lower()))
        if topic and not topic & quoted:
            add("F11", "major", "probable", f"final validation passed a fallback that shares none of the question's topic words {sorted(topic)[:6]}")
    # -- repair / fallback
    # "truncated" describes the generation, not the repaired text: it stays in the final report even when repair
    # replaced the text, so it is not evidence that repair failed (F18 records the truncation itself)
    final_errors = final_errors_of(fv)
    # Stage 5: the withheld-answer message makes no claim, so its validation is not evidence of a failed repair
    # (whether withholding was right is judged by F13 below)
    if trace.get("repair_type") and final_errors and trace.get("fallback_type") != "unvalidated_answer_withheld":
        add("F12", "major", "proven", f"repair '{trace['repair_type']}' ran and final validation still fails: {sorted(final_errors)}")
    if quoting_fallback and trace["model_called"]:
        topic = _topic_words(trace["question"], trace.get("out_of_scope_part"))
        quoted = set(_WORD.findall(final.lower()))
        if topic and not topic & quoted:
            add("F13", "major", "probable", [f"fallback '{trace.get('repair_type')}' quotes text sharing none of the question's topic words {sorted(topic)[:6]}"])
            # presented as "the requested provision" while the request was a whole part or section:
            # the label is technically true and practically misleading
            broad = any(re.search(r"part \d+$|^\S+ CFR \d+\.\d+$", p) for p in (trace.get("retrieval_query") or {}).get("requested_provisions", []))
            if "verified text of the requested provision" in final and broad:
                add("F20", "major", "proven", "unrelated quoted text is presented as 'the verified text of the requested provision(s)'")
    if keyed and behavior == "refuse" and not declined and not any(r.failure_class == "F02" for r in recs):
        add("F13", "critical", "proven", f"expected a decline ({exp['source_reference']}); the final answer supplies content")
    if keyed and behavior not in ("refuse", None) and (trace.get("repair_type") in WITHHELD or trace.get("fallback_type") == "unvalidated_answer_withheld"):
        add("F13", "major", "proven", "the safe message replaced the answer: an answerable question received no answer "
                                      f"(raw failed: {sorted(icodes & (UNSUPPORTED_CODES | {'degenerate_output', 'empty_output'}))})")
        if "degenerate_output" in icodes:
            add("F18", "major", "proven", "the raw generation was degenerate (repetition), which forced the safe message")
    if keyed and behavior not in ("refuse", None) and blocked:
        # Stage 5: the gate declined a question keyed to be answered. When its fallback still carries everything the
        # key checks (e.g. the verbatim provision, and no forbidden value) the decline is consistent with the key;
        # otherwise a person must judge whether the block was right
        if missing_terms or missing_points:
            add("F21", "major", "needs_review", [f"generation blocked ({trace.get('answerability_state')}: {trace.get('block_reason')}); "
                                                 f"the question is keyed '{behavior}' and the fallback lacks {missing_terms or 'expected points'}"])
    if keyed and behavior not in ("refuse", None) and declined and trace["model_called"] and not fallback:
        add("UNKNOWN", "major", "needs_review", "declined although an answer was expected: a false refusal or a sound decline; review")
    if exp.get("forbidden_value_kind") and _value_in(exp["forbidden_value_kind"], final):
        add("F07", "critical", "proven", f"the FINAL answer states a {exp['forbidden_value_kind']} the database does not contain")
    # -- model capability: the same model, exact evidence only, still produces unsupported content
    # (only when the evidence is sufficient: with insufficient evidence the controlled run proves nothing about the model)
    if controlled and controlled.get("generated") and suff["state"] == "EVIDENCE_SUFFICIENT" and any(r.failure_class in ("F07", "F09") for r in recs):
        c_codes = set(((controlled.get("validation_initial") or {}).get("codes")) or [])
        if c_codes & (UNSUPPORTED_CODES | CITATION_CODES):
            add("F16", "major", "probable", f"with exact evidence only, the model still fails: {sorted(c_codes & (UNSUPPORTED_CODES | CITATION_CODES))}")

    # severity: failures contained by validation + repair do not reach the user
    contained_codes = {"F07", "F09", "F08", "F18"}
    final_ok = fv is None or not final_errors_of(fv)
    irrelevant_fallback = any(r.failure_class == "F13" for r in recs)
    for r in recs:
        if r.failure_class in contained_codes and not r.evidence[0].startswith("the FINAL") and final_ok and trace.get("repair_type") \
                and not irrelevant_fallback and not (keyed and behavior == "refuse" and not declined):
            r.severity = "minor"
            r.notes = (r.notes + " contained: validation caught it and repair corrected the text").strip()
        r.evidence = [e for e in r.evidence if e]

    # final status against the keyed expectation (or the machine-provable failures when unkeyed)
    reaching = [r for r in recs if r.severity in ("critical", "major") and r.confidence in ("proven", "probable")]
    review = [r for r in recs if r.severity in ("critical", "major") and r.confidence == "needs_review"]
    if keyed:
        status = "FAIL" if reaching else ("NEEDS_REVIEW" if review or any(r.failure_class == "UNKNOWN" for r in recs) else "PASS")
    else:
        status = "UNVERIFIED" + ("_WITH_FAILURES" if reaching else "_NEEDS_REVIEW" if review else "")
    decided = [r for r in recs if r.confidence in ("proven", "probable") and r.failure_class != "UNKNOWN"]
    pool = decided or [r for r in recs if r.confidence == "needs_review"]
    if pool:
        primary = min(pool, key=lambda r: (module_rank(r.failure_class), CONFIDENCE.index(r.confidence), r.failure_class))
        primary.primary = True
        primary.secondary_causes = sorted({r.failure_class for r in pool if r is not primary})
    elif status == "FAIL":
        recs.append(FailureRecord(qid, "UNKNOWN", "major", "needs_review", ["fails its keyed expectation; no rule establishes why"], primary=True))
    return {"question_id": qid, "final_status": status, "failures": [r.to_dict() for r in recs],
            "primary": next((r.failure_class for r in recs if r.primary), None)}


def final_errors_of(fv: dict | None) -> set[str]:
    return {p["code"] for p in (fv or {}).get("problems", []) if p.get("severity") == "error"} - {"truncated"}


def describe_classes() -> list[dict[str, str]]:
    return [{"code": c.code, "name": c.name, "module": c.module, "definition": c.definition} for c in FAILURE_CLASSES.values()]
