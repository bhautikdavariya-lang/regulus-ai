"""Stage 5 answerability gate and safe fallback. In-memory eCFR table and
scripted generators: no PostgreSQL, no model. Scenarios are general patterns
(a kind of value, a provision level, a question form), never a benchmark
question, topic or number rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.observability import build_trace, diagnose
from regulus.rag import RagConfig, RagPipeline
from regulus.rag import answerability as A
from regulus.rag.evidence_values import evidence_has_value, requested_value_kind, value_request_is_whole_question
from regulus.rag.fallback import FB_UNVALIDATED, FB_VALUE_NOT_ESTABLISHED, FB_VERBATIM_PROVISION
from regulus.retrieval import LexicalRetriever
from tests.test_answer_shape import TABLE, TEXT
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, guidance_row, row

GOOD = "21 CFR 820.10(b)(2) requires documented traceability procedures under part 821, if applicable [1]."
PART_803 = [row("803.10", "", 0, text="Generally."),
            row("803.10", "(a)", 1, text="(a) If you are a device user facility, you must submit reports as follows.")]
INVENTED_TEMPERATURE = "The provision requires storage at 20°C to 25°C [1]."
# a loop INSIDE one sentence (Stage 8): the 4-gram test rejects it and repetition trimming cannot rescue it;
# a whole sentence repeated is now trimmed to its first occurrence instead (tests/test_stage8_generation_control.py)
LOOP = "Labels must carry the name " + "of the product and the name " * 12 + "of the product."


def run(question, response=GOOD, table=None, events=None, **cfg):
    g = ScriptedGenerator(response)
    p = RagPipeline(LexicalRetriever(TableDatabase(table if table is not None else TABLE + PART_803)), g, RagConfig(**cfg))
    out = p.answer(question, on_event=(lambda k, d: events.append((k, d))) if events is not None else None)
    return out, g, p


def gate(out):
    return out.metadata["answerability"]


def exp(**kw):
    base = {"id": "T", "category": "direct_requirement", "expected_behavior": "answer", "expected_exact": [], "expected_terms": [],
            "expected_points": [], "forbidden_value_kind": None, "source_reference": "test", "verified_status": "test"}
    base.update(kw)
    return base


# ------------------------------------------------------------ requested value kinds


@pytest.mark.parametrize("question, kind, whole", [
    ("What exact storage temperature range does 21 CFR 820.10 require?", "temperature", True),
    ("By what date must a manufacturer comply with 21 CFR 820.10(b)(1)?", "date", True),
    ("What penalty amount does 21 CFR 820.10(b)(3) specify?", "money", True),
    ("Which FDA form number must be used under 21 CFR 820.10(b)(4)?", "form_number", True),
    ("How often must the review be repeated — every six months?", "duration_or_frequency", True),
    ("How long must records be retained and how must they be made available?", "duration_or_frequency", False),
])
def test_requested_value_kind_and_whole_question(question, kind, whole):
    assert requested_value_kind(question) == kind
    assert value_request_is_whole_question(question, kind) is whole


@pytest.mark.parametrize("question", [
    "What are the time/temperature control requirements for food?",     # mentions the word, asks for requirements
    "In what form must the identifier appear on the label?",               # "form" is not a form number
    "What does 21 CFR 820.10(b)(2) require?",
])
def test_mentioning_a_value_word_is_not_asking_for_a_value(question):
    assert requested_value_kind(question) is None


def test_evidence_value_detection_is_by_kind_not_by_topic():
    assert evidence_has_value("temperature", ["Store between 2 °C and 8 °C."])
    assert not evidence_has_value("temperature", ["Store under appropriate conditions of temperature and humidity."])
    assert evidence_has_value("money", ["a fee of $4,000"]) and not evidence_has_value("money", ["a fee"])


# ------------------------------------------------------------ states


def test_answerable_explicit_provision_is_generated():
    out, g, _ = run("What does 21 CFR 820.10(b)(2) require?")
    assert gate(out)["state"] == A.ANSWERABLE and gate(out)["confidence"] == A.PROVEN
    assert len(g.calls) == 1 and out.model_called and not out.metadata["generation_blocked"]
    assert out.metadata["generation_called"] is True and out.metadata["fallback_type"] is None


def test_requested_value_absent_blocks_generation_and_quotes_the_identified_provision():
    out, g, _ = run("What penalty amount does 21 CFR 820.10(b)(3) specify for late complaint notification?", "$10,000 [1].")
    d = gate(out)
    assert d["state"] == A.INSUFFICIENT_EVIDENCE and d["blocking_conditions"] == ["requested_value_absent"]
    assert g.calls == [] and not out.model_called and out.metadata["generation_blocked"]
    assert out.metadata["fallback_type"] == FB_VALUE_NOT_ESTABLISHED and "$" not in out.answer
    assert "does not establish the amount" in out.answer and TEXT["(b)(3)"][:40] in out.answer
    assert [c.label for c in out.citations] == ["21 CFR 820.10(b)(3)"]  # the quoted provision is cited
    assert out.metadata["coverage_action"] == "blocked_insufficient_evidence" and d["evidence_ids"]


def test_temperature_regression_through_the_general_mechanism():
    """The Stage 4 incident pattern: a value the evidence does not contain. Blocked by the value-kind
    rule; the model is never asked, so it cannot invent the figure; nothing unrelated is quoted."""
    q = "What exact storage temperature range does 21 CFR Part 820 require for all finished devices?"
    out, g, _ = run(q, INVENTED_TEMPERATURE)
    assert gate(out)["state"] == A.INSUFFICIENT_EVIDENCE and g.calls == []
    assert "°" not in out.answer and "verified text of the requested provision" not in out.answer
    assert "does not establish the specific temperature or temperature range" in out.answer
    assert not any(t[:30] in out.answer for t in TEXT.values())  # part-level: no passage is quoted as the answer
    assert "Sources consulted" in out.answer and out.citations == []


def test_the_same_question_is_answered_when_the_evidence_contains_the_value():
    table = [row("820.10", p, n, text=t + (" Store between 15 °C and 25 °C." if p == "(b)(1)" else "")) for n, (p, t) in enumerate(TEXT.items())]
    out, g, _ = run("What exact storage temperature range does 21 CFR 820.10 require?", "Between 15 °C and 25 °C [1].", table=table)
    assert gate(out)["state"] == A.ANSWERABLE and len(g.calls) == 1  # decided by the evidence, not the topic


def test_value_missing_from_one_part_of_a_multi_part_question_is_partial():
    q = "How long must records under 21 CFR 820.10(b)(2) be retained and how must they be made available?"
    out, g, _ = run(q, GOOD)
    d = gate(out)
    assert d["state"] == A.PARTIALLY_ANSWERABLE and len(g.calls) == 1 and not out.metadata["generation_blocked"]
    assert out.answer.rstrip().endswith(d["limitation"]) and "time period or frequency" in d["limitation"]


def test_partial_coverage_is_partial_and_states_the_missing_provision():
    out, g, _ = run("What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?")
    assert gate(out)["state"] == A.PARTIALLY_ANSWERABLE and len(g.calls) == 1
    assert out.metadata["coverage_action"] == "answer_partial" and "820.999" in out.answer


def test_requested_provision_not_found_keeps_the_existing_refusal():
    out, g, _ = run("What does 21 CFR 820.999 require?")
    assert gate(out)["state"] == A.INSUFFICIENT_EVIDENCE and g.calls == []
    assert out.metadata["coverage_action"] == "refuse_unsupported" and out.metadata["fallback_type"] == "provision_not_found"


def test_no_evidence_blocks():
    out, g, _ = run("What is the capital of France?")
    assert gate(out)["state"] == A.INSUFFICIENT_EVIDENCE and g.calls == [] and out.metadata["fallback_type"] == "no_evidence"


@pytest.mark.parametrize("mode", ["adaptive", "structured", "off"])
def test_out_of_scope_is_declined_in_every_answer_shape_mode(mode):
    out, g, _ = run("What does the EU Medical Device Regulation require for UDI?", "The EU MDR requires a UDI [1].", answer_shape=mode)
    assert gate(out)["state"] == A.OUT_OF_SCOPE and g.calls == [] and out.metadata["coverage_action"] == "refuse_out_of_scope"


@pytest.mark.parametrize("question", ["What does paragraph (b) require?", "What does this section require for complaints?"])
def test_unidentified_provision_is_ambiguous(question):
    out, g, _ = run(question)
    assert gate(out)["state"] == A.AMBIGUOUS and g.calls == [] and "name the provision" in out.answer


def test_citation_lookup_naming_only_the_referenced_provision_is_wrong_provision():
    q = "Cite the provision that requires manufacturers to notify FDA of complaints meeting part 803 criteria."
    out, g, _ = run(q, "21 CFR 803.10(a) [1].")
    d = gate(out)
    assert d["state"] == A.WRONG_PROVISION and d["signals"]["reference_targets"] == ["21 CFR part 803"] and g.calls == []
    assert "user facility" not in out.answer  # the referenced provision's text is not presented as the answer


def test_citation_lookup_with_a_named_container_is_not_blocked():
    out, g, _ = run("Which provision of 21 CFR 820.10 refers to part 806?")
    assert gate(out)["state"] != A.WRONG_PROVISION and len(g.calls) == 1  # 820.10 is what is asked about


def test_determination_request_is_unsupported():
    out, g, _ = run("Is my device compliant with 21 CFR 820.10?")
    assert gate(out)["state"] == A.UNSUPPORTED_REQUEST and g.calls == []


def test_general_question_is_unknown_and_generated():
    table = TABLE + [row("801.1", "", 0, text="Labeling applies.", rank=0.5)]
    db = TableDatabase(table, full_text=[row("801.1", "", 0, text="Labeling applies.", rank=0.5)])
    g = ScriptedGenerator("Labeling applies [1].")
    out = RagPipeline(LexicalRetriever(db), g, RagConfig()).answer("What must a drug label carry?")
    assert gate(out)["state"] == A.UNKNOWN and len(g.calls) == 1


def test_gate_off_restores_stage4_behaviour_and_still_records_the_decision():
    out, g, _ = run("What exact storage temperature range does 21 CFR Part 820 require?", INVENTED_TEMPERATURE, answerability="off")
    assert len(g.calls) == 1 and gate(out)["state"] == A.INSUFFICIENT_EVIDENCE and gate(out)["acted_on"] is False
    assert out.metadata["generation_blocked"] is False


def test_every_decision_carries_reason_signals_confidence_and_evidence():
    for q in ("What does 21 CFR 820.10(b)(2) require?", "What penalty amount does 21 CFR 820.10(b)(3) specify?",
              "What does 21 CFR 820.999 require?", "Is my device compliant with 21 CFR 820.10?"):
        d = gate(run(q)[0])
        assert d["state"] in A.STATES and d["reason"] and d["signals"] and d["confidence"] in (A.PROVEN, A.PROBABLE, A.UNDETERMINED)
        assert d["blocked"] == (d["state"] in A.BLOCKING) and (not d["blocked"] or d["blocking_conditions"])


def test_decisions_are_deterministic():
    q = "What exact storage temperature range does 21 CFR Part 820 require?"
    a, b = run(q)[0], run(q)[0]
    assert gate(a) == gate(b) and a.answer == b.answer


# ------------------------------------------------------------ safe fallback


def test_failed_generation_on_a_part_level_request_quotes_nothing():
    out, g, _ = run("What does 21 CFR Part 820 require?", LOOP)
    assert len(g.calls) == 1 and out.metadata["validation"]["repair"] == FB_UNVALIDATED
    assert "verified text of the requested provision" not in out.answer
    assert not any(t[:30] in out.answer for t in TEXT.values()) and out.citations == []


def test_failed_generation_on_an_identified_provision_still_quotes_it():
    out, g, _ = run("What does 21 CFR 820.10(b)(2) require?", LOOP)
    assert out.metadata["validation"]["repair"] == "extractive_replacement" and TEXT["(b)(2)"][:40] in out.answer


def test_a_repair_that_stays_ungrounded_falls_back_safely(monkeypatch):
    g = ScriptedGenerator("21 CFR 820.10(b)(2) requires a fee of $500 [1].")
    p = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), g, RagConfig())
    monkeypatch.setattr(p, "repair_answer", lambda text, package, report, **kw: ("", "broken_repair"))
    out = p.answer("What does 21 CFR 820.10(b)(2) require?")
    m = out.metadata
    assert m["validation"]["repair"] == "broken_repair+failed_repair_fallback" and m["fallback_type"] == FB_VERBATIM_PROVISION
    assert out.answer.startswith("The generated answer could not be validated") and TEXT["(b)(2)"][:40] in out.answer
    assert m["raw_model_output"] == g.response and m["repair_input"] == g.response and m["repair_output"] == ""
    assert "still failed validation" in m["fallback_reason"] and out.validation.ok


def test_fallback_wording_never_claims_the_regulation_lacks_something():
    for q in ("What exact storage temperature range does 21 CFR Part 820 require?", "Which FDA form number must be used under 21 CFR 820.10(b)(4)?"):
        text = run(q)[0].answer.lower()
        assert "does not establish" in text and "the regulation does not contain" not in text and "does not require" not in text


# ------------------------------------------------------------ trace, streaming, safety


def test_trace_records_the_gate_and_no_secrets():
    out, _, p = run("What penalty amount does 21 CFR 820.10(b)(3) specify?")
    t = build_trace(out, question_id="T", config=p.config.to_dict())
    assert t["answerability_state"] == A.INSUFFICIENT_EVIDENCE and t["generation_blocked"] is True and t["generation_called"] is False
    assert t["fallback_type"] == FB_VALUE_NOT_ESTABLISHED and t["block_reason"] and t["answerability_confidence"] == A.PROVEN
    blob = json.dumps(t, default=str).lower()
    for secret in ("postgresql://", "password", "regulus_database_url", "hf_token", "api_key", "@"):
        assert secret not in blob


def test_diagnosis_treats_a_gate_decline_as_declined_and_flags_blocks_that_miss_the_key():
    out, _, p = run("Which FDA form number must be used under 21 CFR 820.10(b)(4)?")
    t = build_trace(out, question_id="T", config=p.config.to_dict())
    assert diagnose(t, exp(expected_terms=["advisory"]))["final_status"] == "PASS"   # the quoted provision meets the key
    d = diagnose(t, exp(expected_terms=["a term the fallback lacks"]))
    assert d["final_status"] == "NEEDS_REVIEW" and any(f["failure_class"] == "F21" for f in d["failures"])


def test_streaming_a_blocked_question_emits_context_and_no_generation():
    events = []
    out, g, _ = run("What penalty amount does 21 CFR 820.10(b)(3) specify?", events=events)
    kinds = [k for k, _ in events]
    assert kinds == ["context"] and g.calls == [] and out.answer


def test_streaming_an_answerable_question_is_unchanged():
    events = []
    out, _, _ = run("What does 21 CFR 820.10(b)(2) require?", events=events)
    assert [k for k, _ in events][:2] == ["context", "generation_started"] and "generation_finished" in [k for k, _ in events]


def test_gate_code_has_no_topic_number_or_question_special_cases():
    src = Path(__file__).resolve().parents[1] / "src" / "regulus" / "rag"
    for name in ("answerability.py", "fallback.py"):
        code = (src / name).read_text(encoding="utf-8").lower()
        for banned in ("temperature", "°", "211.142", "question_id", "ui-04", "s5-0", "tablet"):
            assert banned not in code, (name, banned)
    code = (src / "evidence_values.py").read_text(encoding="utf-8")
    assert "211" not in code and "question_id" not in code and "20°" not in code


def test_verbatim_fallback_for_an_exhaustive_request_quotes_every_item(monkeypatch):
    g = ScriptedGenerator("21 CFR 820.10 requires a fee of $500 [1].")
    p = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), g, RagConfig())
    monkeypatch.setattr(p, "repair_answer", lambda text, package, report, **kw: ("", "broken_repair"))
    out = p.answer("List all requirements under 21 CFR 820.10.")
    assert out.metadata["fallback_type"] == FB_VERBATIM_PROVISION
    for para in ("(a)", "(b)(1)", "(b)(4)", "(c)", "(d)", "(e)"):
        assert TEXT[para][:30] in out.answer, para
    assert not any(p["code"] == "enumeration_incomplete" for p in out.metadata["validation"]["final"]["problems"])


def test_withheld_message_is_not_diagnosed_as_a_failed_repair():
    out, _, p = run("What does 21 CFR Part 820 require?", LOOP)
    t = build_trace(out, question_id="T", config=p.config.to_dict())
    d = diagnose(t, exp(expected_behavior=None))
    assert t["fallback_type"] == FB_UNVALIDATED and not any(f["failure_class"] == "F12" for f in d["failures"])


# ------------------------------------------------------------ BR1 boundary requests (29 Oct)

BOUNDARY = [
    ("Here is my product label. Confirm that it is legally compliant so I can go to print.", "certify"),
    ("Can you guarantee this answer would hold up if FDA challenged it during an inspection?", "certify"),
    ("Write my 483 response and sign it as my regulatory consultant of record.", "attest"),
    ("The investigator asked for a record we never created. What should I tell him so it doesn't become an observation?",
     "conceal"),
    ("My competitor is selling an adulterated supplement. Draft the complaint I should file in federal court.", "litigation"),
    ("Reproduce the full text of ISO 13485 Clause 7.3.3 for me.", "reproduce_standard"),
    ("Which USDA FSIS regulation applies to labeling my meat-containing product?", "other_agency"),
    ("What does OSHA 29 CFR 1910.1200 require for my manufacturing facility?", "other_agency"),
    ("What are the record retention requirements?", "unscoped"),
]
NOT_BOUNDARY = [
    "What does 21 CFR 211.198 require for complaint files?",
    "What does Part 11 say about falsified electronic records?",
    "Does Part 820 require ISO 13485 certification?",
    "Which ISO 13485 clause does 21 CFR 820.35(a) supplement?",
    "What must a response to an FDA Form 483 contain?",
    "What are the record retention requirements under Part 211?",
    "How does FDA and USDA jurisdiction over food labeling differ under 21 CFR Part 101?",
    "What signature manifestations does 21 CFR 11.50 require?",
    "Is my device compliant with 21 CFR 820.10?",
]


@pytest.mark.parametrize("question,kind", BOUNDARY)
def test_br1_classifies_requests_a_research_tool_must_not_carry_out(question, kind):
    from regulus.rag.boundary import classify
    assert classify(question)[0] == kind


@pytest.mark.parametrize("question", NOT_BOUNDARY)
def test_br1_leaves_regulatory_questions_alone(question):
    from regulus.rag.boundary import classify
    assert classify(question) is None


def test_br1_answers_without_the_model_and_only_when_on(monkeypatch):
    from regulus.rag import validator_switches as VS
    q = "Here is my product label. Confirm that it is legally compliant so I can go to print."
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"BR1"})
    out, g, _ = run(q)
    assert gate(out)["state"] == A.UNSUPPORTED_REQUEST and g.calls == []
    assert "cannot certify" in out.answer and "Part 101" in out.answer
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION - {"BR1"})
    out, g, _ = run(q)
    assert "cannot certify" not in out.answer


def test_br1_another_agency_is_out_of_scope_and_named(monkeypatch):
    from regulus.rag import validator_switches as VS
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"BR1"})
    out, g, _ = run("Which USDA FSIS regulation applies to labeling my meat-containing product?")
    assert gate(out)["state"] == A.OUT_OF_SCOPE and g.calls == [] and "9 CFR" in out.answer and "Part 101" in out.answer


# ------------------------------------------------------------ NX1 nonexistent provisions (29 Oct)


class _Rows:
    """cfr_records rows by section; parts with live sections."""

    def __init__(self, rows, parts=()):
        self.rows, self.parts = rows, set(parts)

    def query(self, sql, params):
        if "part_number" in sql:
            return [{"ok": 1}] if params["p"] in self.parts else []
        return [dict(paragraph_path=p, body_text=t, snapshot_date="2026-09-03", is_reserved=res, removed_on=None)
                for s, p, t, res in self.rows if s == params["s"]]


K_ROWS = [("101.9", "(k)", "A food labeled under this section shall be deemed misbranded if", False)] + \
         [("101.9", f"(k)({n})", f"claim {n}", False) for n in (2, 1, 4, 3)]


def test_nx1_a_paragraph_past_the_last_is_said_not_to_exist_with_the_premise_term():
    from regulus.rag.nonexistence import statement
    text = statement(_Rows(K_ROWS), "What does 21 CFR 101.9(k)(5) say about mandatory QR code placement?",
                     ["21 CFR 101.9(k)(5)"])
    assert "101.9(k)(1) through 101.9(k)(4) and no 101.9(k)(5)" in text and "does not mention “QR code”" in text


def test_nx1_makes_no_claim_where_a_data_gap_could_be_the_cause():
    from regulus.rag.nonexistence import statement
    gap = [r for r in K_ROWS if r[1] != "(k)(3)"]
    assert statement(_Rows(gap), "q", ["21 CFR 101.9(k)(3)"]) is None            # inside the sequence
    assert statement(_Rows(gap), "q", ["21 CFR 101.9(k)(5)"]) is None            # the sequence has a gap
    assert statement(_Rows(K_ROWS), "q", ["21 CFR 101.9(m)(1)"]) is None         # the parent is missing too
    reserved = [("820.5", "", "[Reserved]", True)]
    assert statement(_Rows(reserved, parts={"820"}), "q", ["21 CFR 820.5"]) is None
    assert statement(_Rows([], parts=()), "q", ["21 CFR 999.1"]) is None          # a part not in the corpus
    assert statement(_Rows([], parts={"820"}), "q", ["21 CFR 820.30"]) is None   # a former QSR section (QM1)


def test_nx1_a_section_its_part_does_not_have():
    from regulus.rag.nonexistence import statement
    assert statement(_Rows([], parts={"111"}), "q", ["21 CFR 111.900"]).startswith("21 CFR Part 111 has no section 111.900")
