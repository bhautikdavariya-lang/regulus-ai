"""Stage 4 failure observatory: taxonomy, sufficiency, traces, raw-output
preservation and diagnosis. In-memory eCFR table and scripted generators:
no PostgreSQL, no model. The scenarios are generic patterns, not benchmark
questions: nothing here depends on a particular regulation or number.
"""

from __future__ import annotations

import json

import pytest

from regulus.observability import FAILURE_CLASSES, FailureRecord, build_trace, diagnose
from regulus.observability.sufficiency import (
    INSUFFICIENT,
    NOT_FOUND,
    PARTIAL,
    SUFFICIENT,
    UNKNOWN,
    assess,
    evidence_has_value,
    requested_value_kind,
)
from regulus.rag import RagConfig, RagPipeline
from regulus.retrieval import LexicalRetriever
from tests.test_answer_shape import TABLE
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, guidance_row, row

GOOD = "21 CFR 820.10(b)(2) requires documented traceability procedures under part 821, if applicable [1]."


def answer(question, response, db=None, **cfg):
    g = ScriptedGenerator(response)
    p = RagPipeline(LexicalRetriever(db or TableDatabase(TABLE)), g, RagConfig(**cfg))
    return p.answer(question), p


def trace_of(question, response, qid="T", **cfg):
    out, p = answer(question, response, **cfg)
    return build_trace(out, question_id=qid, generator_info={"model_id": "scripted"}, config=p.config.to_dict()), out


def exp(**kw):
    base = {"id": "T", "category": "direct_requirement", "expected_behavior": "answer", "expected_exact": [], "expected_terms": [],
            "expected_points": [], "forbidden_value_kind": None, "source_reference": "test", "verified_status": "test"}
    base.update(kw)
    return base


# ------------------------------------------------------------ taxonomy


def test_taxonomy_has_every_class_and_an_explicit_unknown():
    assert [f"F{i:02d}" for i in range(1, 22)] + ["UNKNOWN"] == list(FAILURE_CLASSES)  # F21 added in Stage 5
    assert all(c.definition and c.module for c in FAILURE_CLASSES.values())


def test_a_failure_record_must_carry_evidence_and_a_known_class():
    with pytest.raises(ValueError):
        FailureRecord("Q", "F07", "major", "proven", [])
    with pytest.raises(ValueError):
        FailureRecord("Q", "F99", "major", "proven", ["x"])
    r = FailureRecord("Q", "F03", "major", "proven", ["missing"])
    assert r.module == "retrieval" and r.to_dict()["name"] == "Retrieval miss"


# ------------------------------------------------------------ evidence sufficiency


@pytest.mark.parametrize("question, kind", [
    ("What exact storage temperature range does part X require?", "temperature"),
    ("By what date must a manufacturer comply?", "date"),
    ("How often must a supplier be re-verified?", "duration_or_frequency"),
    ("What penalty amount applies?", "money"),
    ("Which FDA form must be used?", "form_number"),
    ("How many samples are required?", "count"),
    ("What does 21 CFR 820.10 require?", None),
])
def test_requested_value_kinds_are_general(question, kind):
    assert requested_value_kind(question) == kind


def test_value_kinds_are_recognised_in_evidence():
    assert evidence_has_value("temperature", ["store at 25 °C"]) and not evidence_has_value("temperature", ["appropriate conditions of temperature"])
    assert evidence_has_value("duration_or_frequency", ["within 30 days"]) and evidence_has_value("money", ["$1,000"])


def test_sufficiency_states():
    out, _ = answer("What does 21 CFR 820.10(b)(2) require?", GOOD)
    assert assess(out.question, out.package, out.coverage, no_context=False)["state"] == SUFFICIENT
    out, _ = answer("What exact temperature range does 21 CFR 820.10(b)(2) require?", GOOD)
    s = assess(out.question, out.package, out.coverage, no_context=False)
    assert s["state"] == INSUFFICIENT and s["requested_value_kind"] == "temperature" and s["value_kind_in_evidence"] is False
    out, _ = answer("What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?", GOOD)
    assert assess(out.question, out.package, out.coverage, no_context=False)["state"] == PARTIAL
    out, _ = answer("What does 21 CFR 820.999 require?", GOOD)
    assert assess(out.question, out.package, out.coverage, no_context=out.no_context)["state"] == NOT_FOUND
    db = TableDatabase(TABLE, full_text=[row("801.1", "", 0, text="Labeling applies.", rank=0.5)])
    out, _ = answer("What labeling rules apply?", GOOD, db=db)
    assert assess(out.question, out.package, out.coverage, no_context=out.no_context)["state"] == UNKNOWN


# ------------------------------------------------------------ raw output preservation


def test_raw_output_survives_repair_in_production_mode():
    bad = "21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [9]."
    out, _ = answer("What does 21 CFR 820.10(b)(2) require?", bad)
    m = out.metadata
    assert m["validation"]["repair"] == "invalid_citations_removed"
    assert m["raw_model_output"] == bad and "[9]" not in out.answer   # raw kept, final repaired
    assert m["repair_input"] == bad


def test_no_raw_output_is_invented_when_the_model_is_not_called():
    out, _ = answer("What does 21 CFR 820.999 require?", GOOD)
    assert not out.model_called and out.metadata["raw_model_output"] is None and out.metadata["repair_input"] is None


def test_diagnostics_do_not_change_the_answer():
    # the same question and text with the pipeline alone: identical final answer and citations
    out, _ = answer("What does 21 CFR 820.10(b)(2) require?", GOOD)
    t, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    assert t["final_answer"] == out.answer and t["final_output_hash"] == build_trace(out, question_id="x")["final_output_hash"]


# ------------------------------------------------------------ trace


REQUIRED = ("question_id", "question", "question_hash", "intent_type", "scope", "retrieval_query", "retrieval_parameters",
            "retrieved", "selected_context", "context_hash", "evidence_sufficiency", "prompt_hash", "prompt_token_count",
            "model", "timings_ms", "output_token_count", "raw_model_output", "initial_validation", "repair_attempted",
            "repair_type", "repair_input", "repair_output", "final_validation", "final_answer", "final_citations",
            "citation_support", "coverage_action", "final_output_hash")


def test_trace_has_every_stage_and_is_json_serialisable():
    t, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    assert all(k in t for k in REQUIRED)
    json.dumps(t, default=dict)
    assert t["retrieved"] and all("method" in r and "score" in r for r in t["retrieved"])
    assert t["selected_context"][0]["text_sha256"] and t["prompt_hash"]


def test_trace_is_deterministic():
    a, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    b, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    drop = lambda t: {k: v for k, v in t.items() if k != "timings_ms"}
    assert drop(a) == drop(b)


def test_trace_leaks_no_secrets_or_source_texts():
    t, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    blob = json.dumps(t, default=dict).lower()
    for secret in ("postgresql://", "password", "regulus_database_url", "hf_token", "api_key", "@localhost"):
        assert secret not in blob
    assert "820.10(b)(2) body text" not in blob  # source text is hashed, not copied (fixture text)


# ------------------------------------------------------------ diagnosis patterns


def test_pattern_insufficient_evidence_fabricated_value_irrelevant_fallback():
    """A value the evidence cannot supply is invented, validation catches it, and
    the fallback quotes unrelated text as 'the requested provision'. The Stage 4 pattern, reproduced
    with the Stage 5 gate off (tests/test_answerability.py shows the gate preventing it)."""
    q = "What exact storage temperature range does 21 CFR 820.10 require?"
    t, _ = trace_of(q, "21 CFR 820.10 requires storage at 20°C to 25°C [1].", answerability="off")
    assert t["evidence_sufficiency"]["state"] == INSUFFICIENT
    assert "20°C" in t["raw_model_output"] and t["repair_type"] == "extractive_replacement"
    d = diagnose(t, exp(expected_exact=["21 CFR 820.10"], forbidden_value_kind="temperature"))
    codes = [f["failure_class"] for f in d["failures"]]
    assert d["primary"] == "F05" and {"F05", "F07", "F13", "F20"} <= set(codes) and d["final_status"] == "FAIL"


def test_pattern_contained_generation_failure_is_minor():
    bad = "21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [9]."
    t, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", bad)
    d = diagnose(t, exp(expected_exact=["21 CFR 820.10(b)(2)"]))
    f09 = next(f for f in d["failures"] if f["failure_class"] == "F09")
    assert f09["severity"] == "minor" and "contained" in f09["notes"] and d["final_status"] == "PASS"


def test_pattern_out_of_scope_answered():
    db = TableDatabase(TABLE, or_ecfr=[row("801.1", "", 0, text="Labeling.", rank=0.1)], or_guidance=[guidance_row(0, rank=0.1)])
    out, p = answer("What does the EU Medical Device Regulation require for UDI?", "The EU MDR requires a UDI [1].", db=db,
                    answerability="off")  # the Stage 4 pattern; with the gate on it is declined (test_answerability.py)
    t = build_trace(out, question_id="T", config=p.config.to_dict())
    d = diagnose(t, exp(category="out_of_scope_framework", expected_behavior="refuse"))
    assert d["primary"] == "F02" and d["final_status"] == "FAIL"


def test_pattern_keyed_provision_not_retrieved():
    t, _ = trace_of("What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?", GOOD)
    d = diagnose(t, exp(expected_exact=["21 CFR 820.999"]))
    assert any(f["failure_class"] == "F03" for f in d["failures"])


def test_unkeyed_questions_are_never_marked_pass():
    t, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    d = diagnose(t, exp(expected_behavior=None))
    assert d["final_status"].startswith("UNVERIFIED")


def test_a_failure_nothing_explains_becomes_unknown():
    t, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    d = diagnose(t, exp(expected_terms=["a term the answer does not contain"]))
    assert d["final_status"] == "FAIL" and d["primary"] == "F15"
    # a keyed failure with no rule behind it is UNKNOWN / needs_review, never a guessed class
    t2, _ = trace_of("What does 21 CFR 820.10(b)(2) require?", GOOD)
    t2["final_answer"] = "The provision is discussed elsewhere."   # a decline-free answer that fails no deterministic rule
    d2 = diagnose(t2, exp(expected_points=[["nonexistent point"]]))
    assert d2["primary"] == "F15"
    t3 = dict(t2, final_answer=GOOD)
    d3 = diagnose(t3, exp(expected_behavior="partial"))
    assert d3["final_status"] == "PASS"
