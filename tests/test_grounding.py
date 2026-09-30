"""Stage 13 tests: identifier verification, the grounding gate, the new
training categories and the grounding metrics. No model, no database, no GPU.
"""

from __future__ import annotations

import json

import pytest

from regulus.evaluation.grounding_eval import ANSWER, HEDGED, REFUSAL, classify_answer, evaluate_grounding, is_refusal
from regulus.grounding import (
    REASON_ABSENT,
    REASON_CONTEXT_MISMATCH,
    REASON_PARAGRAPH_ABSENT,
    REASON_RESERVED,
    CorpusIdentifierIndex,
    GroundingConfig,
    GroundingGate,
    RequestedIdentifier,
    extract_identifier,
    match_results,
    refusal_text,
    verify_identifier,
    verify_question,
)
from regulus.grounding.identifiers import (
    DOCKET,
    NOT_IN_SNAPSHOT,
    OUTSIDE_TITLE_21,
    PARAGRAPH,
    PART,
    SECTION,
)
from regulus.retrieval.models import METHOD_FULL_TEXT
from regulus.training.grounding_examples import STAGE13_GENERATORS
from tests.test_retrieval_lexical import ecfr_row, guidance_row
from tests.test_training_data import make_corpus


# --------------------------------------------------------------- fake index


class FakeIndex:
    """Small hand-built index: Part 11 live, Part 83-98 reserved, Part 1400 absent."""

    def __init__(self) -> None:
        self.live_sections = {"11.1": {"", "(a)", "(b)"}, "11.10": {"", "(a)", "(b)"}, "820.10": {"(a)", "(b)", "(b)(1)"}}
        self.structure_sections = set(self.live_sections) | {"11.99"}  # 11.99 exists but is reserved
        self.live_parts = {"11", "820"}
        self.structure_parts = self.live_parts | {"90"}  # inside a reserved range
        self.dockets = {"FDA-2003-D-0143"}

    def part_status(self, part):
        return part in self.structure_parts, part in self.live_parts

    def section_status(self, section):
        return section in self.structure_sections, section in self.live_sections

    def paragraph_exists(self, section, paragraph):
        labels = self.live_sections.get(section, set())
        return paragraph in labels or any(p.startswith(paragraph) for p in labels if paragraph)

    def docket_exists(self, docket):
        return docket.upper() in self.dockets

    def section_facts(self, section):
        return {"heading": "Scope.", "part": section.split(".")[0], "paragraphs": sorted(p for p in self.live_sections.get(section, set()) if p)}


@pytest.fixture
def index():
    return FakeIndex()


# ------------------------------------------------------------- extraction


def test_extract_identifier_recognises_the_supported_forms():
    assert extract_identifier("What does 21 CFR 314.999 require?") == RequestedIdentifier(SECTION, "21 CFR 314.999", "21", "314", "314.999", "")
    assert extract_identifier("Explain 21 CFR 820.10(b)(1)").kind == PARAGRAPH
    assert extract_identifier("What does 21 CFR Part 1400 cover?").kind == PART
    assert extract_identifier("Summarize FDA-2023-D-99999").kind == DOCKET
    assert extract_identifier("§ 807.81").section == "807.81"


def test_extract_identifier_returns_none_when_no_identifier_is_named():
    for q in ("What is a 510(k) submission?", "What is 21 CFR?", "What is the Federal Register?", "", "What does CFR stand for?"):
        assert extract_identifier(q) is None, q


def test_labels_never_alter_the_requested_digits():
    ident = extract_identifier("21 C.F.R. § 314.999")
    assert ident.label == "21 CFR 314.999"  # punctuation normalised, digits untouched
    assert "314.99 " not in ident.label and ident.section == "314.999"
    assert extract_identifier("21 CFR Part 1400").label == "21 CFR Part 1400"


# ----------------------------------------------------------- verification


def test_verify_existing_identifiers(index):
    for q in ("What does 21 CFR 11.1 cover?", "What does 21 CFR Part 11 cover?", "Explain 21 CFR 820.10(b)(1)"):
        v = verify_question(q, index)
        assert v.exists and v.verifiable and not v.verified_absent, q


def test_verify_absent_identifiers(index):
    v = verify_question("What does 21 CFR 314.999 require?", index)
    assert v.verified_absent and v.reason == NOT_IN_SNAPSHOT and v.source_type == "ecfr"
    assert verify_question("What does 21 CFR Part 1400 say?", index).verified_absent
    assert verify_question("Summarize FDA-2023-D-99999", index).verified_absent


def test_reserved_is_distinguished_from_absent(index):
    assert verify_question("What does 21 CFR 11.99 require?", index).reason == "reserved"
    assert verify_question("What does 21 CFR Part 90 cover?", index).reason == "reserved"
    assert verify_question("What does 21 CFR Part 1400 cover?", index).reason == NOT_IN_SNAPSHOT


def test_paragraph_absent_from_a_real_section(index):
    v = verify_question("What does 21 CFR 820.10(z) require?", index)
    assert v.verified_absent and v.reason == "paragraph_not_in_section"
    assert v.record["paragraphs"] == ["(a)", "(b)", "(b)(1)"]
    assert verify_question("What does 21 CFR 820.10(b) require?", index).exists  # parent of (b)(1)


def test_other_titles_are_unverifiable_not_absent(index):
    v = verify_question("What does 40 CFR 261.3 require?", index)
    assert v.reason == OUTSIDE_TITLE_21 and not v.exists and not v.verifiable and not v.verified_absent


def test_verify_identifier_handles_nothing_to_verify(index):
    assert verify_identifier(None, index) is None
    assert verify_question("What is a medical device?", index) is None


def test_corpus_index_matches_the_corpus():
    corpus = make_corpus()
    idx = CorpusIdentifierIndex(corpus)
    assert idx.section_status("820.10") == (True, True)
    assert idx.section_status("820.999x")[1] is False  # reserved section
    assert idx.part_status("11") == (True, True)
    assert idx.part_status("90") == (True, False)  # inside the reserved 83-98 range
    assert idx.part_status("1400") == (False, False)
    assert idx.docket_exists("FDA-2003-D-0143") and not idx.docket_exists("FDA-2023-D-99999")
    assert idx.paragraph_exists("820.10", "(a)") and not idx.paragraph_exists("820.10", "(z)")


# --------------------------------------------------------------- matching


def _result(section="820.10", para="(a)", corpus="ecfr", docket=None):
    from regulus.retrieval.lexical import LexicalRetriever

    if corpus == "ecfr":
        return LexicalRetriever._ecfr_result(ecfr_row(section=section, para=para, ordinal=1), METHOD_FULL_TEXT, 1.0, {})
    return LexicalRetriever._guidance_result(guidance_row(docket=docket or "FDA-2016-D-2565"), METHOD_FULL_TEXT, 1.0, {})


def test_match_results_compares_identifiers_structurally():
    requested = extract_identifier("What does 21 CFR 820.10 require?")
    assert match_results(requested, [_result("820.10", "(a)")])
    assert not match_results(requested, [_result("112.45", "(a)")])
    # a similar-looking neighbour is not a match
    assert not match_results(extract_identifier("21 CFR 314.999"), [_result("314.99", "(a)")])


def test_paragraph_matching_does_not_read_across_siblings():
    requested = extract_identifier("What does 21 CFR 820.10(b)(2) require?")
    assert not match_results(requested, [_result("820.10", "(b)(1)")])
    assert not match_results(requested, [_result("820.10", "(b)")])  # parent does not contain the child text
    assert match_results(requested, [_result("820.10", "(b)(2)")])
    parent = extract_identifier("What does 21 CFR 820.10(b) require?")
    assert match_results(parent, [_result("820.10", "(b)(1)")])  # a child does establish the parent


def test_part_and_docket_matching():
    assert match_results(extract_identifier("21 CFR Part 820"), [_result("820.10", "(a)")])
    assert not match_results(extract_identifier("21 CFR Part 211"), [_result("820.10", "(a)")])
    d = extract_identifier("Summarize FDA-2016-D-2565")
    assert match_results(d, [_result(corpus="fda_guidance", docket="FDA-2016-D-2565")])
    assert not match_results(d, [_result(corpus="fda_guidance", docket="FDA-2003-D-0143")])


# ------------------------------------------------------------------- gate


def test_gate_refuses_a_verified_absent_identifier(index):
    gate = GroundingGate(index, GroundingConfig(enabled=True), snapshot_date="2026-09-03")
    _, decision = gate.check_identifier("What are the specific requirements of 21 CFR 314.999?")
    assert decision.refused and decision.reason == REASON_ABSENT
    assert "could not verify 21 CFR 314.999" in decision.answer and "2026-09-03" in decision.answer


def test_gate_refuses_context_that_does_not_carry_the_identifier(index):
    gate = GroundingGate(index, GroundingConfig(enabled=True))
    verification, pre = gate.check_identifier("What does 21 CFR 11.10 require?")
    assert not pre.refused
    post = gate.check_context(verification, [_result("820.10", "(a)")])
    assert post.refused and post.reason == REASON_CONTEXT_MISMATCH
    ok = gate.check_context(verification, [_result("11.10", "(a)")])
    assert not ok.refused and ok.matched_keys


def test_gate_passes_questions_without_identifiers_and_other_titles(index):
    gate = GroundingGate(index, GroundingConfig(enabled=True))
    _, d = gate.check_identifier("What is a medical device?")
    assert not d.refused and d.reason == "no_identifier_in_question"
    _, d2 = gate.check_identifier("What does 40 CFR 261.3 require?")
    assert not d2.refused and d2.reason == OUTSIDE_TITLE_21


def test_gate_is_inert_when_disabled_and_configurable(index):
    off = GroundingGate(index, GroundingConfig(enabled=False))
    _, d = off.check_identifier("What does 21 CFR 314.999 require?")
    assert not d.refused and not d.checked
    lenient = GroundingGate(index, GroundingConfig(enabled=True, refuse_context_mismatch=False))
    verification, _ = lenient.check_identifier("What does 21 CFR 11.10 require?")
    assert not lenient.check_context(verification, [_result("820.10", "(a)")]).refused
    # a part-level question is answerable from any section of that part
    strict = GroundingGate(index, GroundingConfig(enabled=True))
    v_part, _ = strict.check_identifier("What does 21 CFR Part 11 cover?")
    assert not strict.check_context(v_part, [_result("820.10", "(a)")]).refused


def test_refusal_wording_covers_every_reason(index):
    for q, reason in (
        ("What does 21 CFR 314.999 require?", REASON_ABSENT),
        ("What does 21 CFR 11.99 require?", REASON_RESERVED),
        ("What does 21 CFR 820.10(z) require?", REASON_PARAGRAPH_ABSENT),
        ("What does 21 CFR 11.10 require?", REASON_CONTEXT_MISMATCH),
    ):
        v = verify_question(q, index)
        text = refusal_text(v, reason, "2026-09-03")
        assert len(text) > 40 and is_refusal(text), (reason, text)
    docket = verify_question("Summarize FDA-2023-D-99999", index)
    assert "docket number FDA-2023-D-99999" in refusal_text(docket, REASON_ABSENT)


# -------------------------------------------------- pipeline integration


def test_pipeline_gate_replaces_the_answer_without_calling_the_model(index):
    from regulus.inference.generate import GenerationResult
    from regulus.rag import RagConfig, RagPipeline

    class FakeRetriever:
        def run(self, query, **kw):
            from regulus.retrieval.lexical import SearchResponse
            from regulus.retrieval.query import QueryType

            return SearchResponse(query, QueryType.EXACT_CFR, [_result("112.45", "(a)")], {}, {}, 1.0, [], {})

        def describe(self):
            return {"retriever": "FakeRetriever"}

    class FakeGenerator:
        def __init__(self):
            self.calls = 0

        def generate(self, messages):
            self.calls += 1
            return GenerationResult("q", "21 CFR 314.999 provides: invented text.", 10, 5, 0.1)

        def describe(self):
            return {"model_id": "fake"}

    gen = FakeGenerator()
    gate = GroundingGate(index, GroundingConfig(enabled=True), snapshot_date="2026-09-03")
    pipeline = RagPipeline(FakeRetriever(), gen, RagConfig(), grounding=gate)
    out = pipeline.answer("What are the specific requirements of 21 CFR 314.999?")
    assert gen.calls == 0 and not out.model_called
    assert "could not verify 21 CFR 314.999" in out.answer
    assert out.metadata["grounding"]["action"] == "refuse"
    assert len(out.retrieved_results) == 1  # retrieval still ran, so runs stay comparable
    assert "grounding" in pipeline.describe()

    # without the gate the same pipeline calls the model, as Stage 7 does
    gen2 = FakeGenerator()
    ungated = RagPipeline(FakeRetriever(), gen2, RagConfig())
    out2 = ungated.answer("What are the specific requirements of 21 CFR 314.999?")
    assert gen2.calls == 1 and out2.model_called and out2.metadata["grounding"] is None


# ---------------------------------------------------------------- metrics


def test_answer_classification_separates_refusal_from_hedging():
    assert classify_answer("The available regulatory sources do not provide enough information to answer this.") == REFUSAL
    assert classify_answer("") == REFUSAL
    hedged = "A clinical trial is a study that tests the safety of a new drug in humans over time. The available regulatory sources do not provide enough information to answer this."
    assert classify_answer(hedged) == HEDGED
    assert classify_answer("21 CFR 820.10(a) [1] provides: Document a quality management system.") == ANSWER
    assert is_refusal("I could not verify 21 CFR 314.999 in the available eCFR data, so I cannot state its requirements.")


def test_grounding_metrics_count_both_error_directions():
    run = {"results": [
        # refusal required, correctly refused
        {"question_id": "a", "expected_behavior": "acknowledge_uncertainty", "model_answer": "I could not verify 21 CFR 314.999, so I cannot state its requirements.", "question": "What does 21 CFR 314.999 require?", "diagnostics": {"context": {"sources": []}}},
        # refusal required, answered anyway -> unsupported
        {"question_id": "b", "expected_behavior": "acknowledge_uncertainty", "model_answer": "21 CFR 1400 (Drug Labeling) [1] provides sweeping requirements for artificial intelligence.", "question": "What does 21 CFR Part 1400 say?", "diagnostics": {"context": {"sources": [{"citation": "21 CFR 201.1"}]}}},
        # answerable, answered and grounded
        {"question_id": "c", "expected_behavior": "answer", "model_answer": "21 CFR 820.10 [1] provides: a quality management system must be documented.", "question": "What does 21 CFR 820.10 cover?", "diagnostics": {"context": {"sources": [{"citation": "21 CFR 820.10(a)"}]}}},
        # answerable, refused -> false refusal
        {"question_id": "d", "expected_behavior": "answer", "model_answer": "The available regulatory sources do not provide enough information to answer this.", "question": "What is a medical device?", "diagnostics": {"context": {"sources": [{"citation": "21 CFR 1.1"}]}}},
    ]}
    m = evaluate_grounding(run).to_dict()
    assert m["refusal_required"] == 2 and m["correct_refusals"] == 1 and m["refusal_rate"] == 0.5
    assert m["unsupported_answers"] == 1 and m["unsupported_answer_ids"] == ["b"]
    assert m["answerable"] == 2 and m["false_refusals"] == 1 and m["false_refusal_ids"] == ["d"]
    assert m["identifier_questions"] == 3
    assert m["ungrounded_identifier_ids"] == ["b"]  # claimed Part 1400 with only 201.1 retrieved
    assert m["answers_with_citations"] == 2 and m["citation_validity_rate"] == 1.0
    assert m["gate_active"] is False


def test_metrics_detect_degeneration_and_invalid_citations():
    run = {"results": [
        {"question_id": "x", "expected_behavior": "answer", "question": "q", "model_answer": "Part 11 " + " ".join(f"[{i}]" for i in range(1, 20)), "diagnostics": {"context": {"sources": [{"citation": "c"}]}}},
    ]}
    m = evaluate_grounding(run).to_dict()
    assert m["degenerate_answers"] == 1 and m["invalid_citation_ids"] == ["x"] and m["citation_validity_rate"] == 0.0


# -------------------------------------------------- new training categories


@pytest.fixture(scope="module")
def stage13_examples():
    from regulus.training import TrainingConfig

    corpus = make_corpus()
    cfg = TrainingConfig(target_examples=400)
    return {name: fn(corpus, cfg) for name, fn in STAGE13_GENERATORS.items()}, corpus


def test_every_stage13_category_generates_valid_examples(stage13_examples):
    made, _ = stage13_examples
    assert set(made) == {"context_mismatch", "wrong_context", "partial_context", "guidance_mismatch", "citation_grounding"}
    for name, examples in made.items():
        assert examples, f"{name} generated nothing"
        for e in examples:
            assert e.category == name and e.context, name
            if name == "citation_grounding":
                assert e.grounded and e.type == "regulatory_qa" and len(e.citations) == 1
            else:
                assert not e.grounded and e.type == "abstention" and e.citations == []
                assert is_refusal(e.answer), (name, e.answer)


def test_context_mismatch_uses_real_context_and_absent_identifiers(stage13_examples):
    made, corpus = stage13_examples
    idx = CorpusIdentifierIndex(corpus)
    for e in made["context_mismatch"]:
        v = verify_identifier(extract_identifier(e.question), idx)
        assert v is not None and v.verified_absent, e.question
        assert e.context and all(c.text.strip() for c in e.context)  # the context is legitimate
        assert e.extra["provided_source"] in {c.source_key for c in e.context}


def test_wrong_context_requests_an_existing_identifier(stage13_examples):
    made, corpus = stage13_examples
    idx = CorpusIdentifierIndex(corpus)
    for e in made["wrong_context"]:
        requested = e.extra["requested_identifier"]
        v = verify_identifier(extract_identifier(requested), idx)
        assert v is not None and v.exists, requested
        assert not match_results(extract_identifier(requested), []) and all(c.section != v.identifier.section for c in e.context)


def test_partial_context_supplies_a_sibling_not_the_requested_paragraph(stage13_examples):
    made, _ = stage13_examples
    for e in made["partial_context"]:
        requested = extract_identifier(e.extra["requested_identifier"])
        provided = e.context[0]
        assert provided.section == requested.section and provided.paragraph != requested.paragraph


def test_citation_grounding_cites_only_the_supporting_source(stage13_examples):
    made, _ = stage13_examples
    for e in made["citation_grounding"]:
        keys = {c.source_key for c in e.context}
        assert e.extra["supporting_source"] in keys and len(e.context) == 3
        cited = {c.source_key for c in e.context if c.citation in set(e.citations)}
        assert cited == {e.extra["supporting_source"]}
        assert not (cited & set(e.extra["distractors"]))


def test_guidance_mismatch_covers_both_directions(stage13_examples):
    made, _ = stage13_examples
    subtypes = {e.extra["subtype"] for e in made["guidance_mismatch"]}
    assert subtypes == {"regulation_asked_guidance_given", "guidance_asked_regulation_given"}
    for e in made["guidance_mismatch"]:
        kinds = {c.source_type for c in e.context}
        expected = {"fda_guidance"} if e.extra["subtype"] == "regulation_asked_guidance_given" else {"ecfr"}
        assert kinds == expected


def test_stage13_categories_are_deterministic(stage13_examples):
    from regulus.training import TrainingConfig

    made, corpus = stage13_examples
    cfg = TrainingConfig(target_examples=400)
    for name, fn in STAGE13_GENERATORS.items():
        again = fn(corpus, cfg)
        assert [e.to_dict() for e in again] == [e.to_dict() for e in made[name]], name


def test_v1_category_shares_do_not_generate_stage13_categories():
    from regulus.training import load_training_config

    v1 = load_training_config()
    assert all(v1.category_shares.get(c, 0.0) == 0.0 for c in STAGE13_GENERATORS)
    assert all(v1.category_targets()[c] == 0 for c in STAGE13_GENERATORS)
    v2 = load_training_config("configs/training_v2.yaml")
    assert all(v2.category_targets()[c] > 0 for c in STAGE13_GENERATORS)
    assert abs(sum(v2.category_shares.values()) - 1.0) < 1e-9
