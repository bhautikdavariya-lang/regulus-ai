"""Stage 7: semantic fallback, scope policy, claim-level validation, repetition stop, backend seam,
replay and key-review honesty. In-memory tables, fake semantic search, scripted generators and a
local HTTP server: no PostgreSQL, no model, no network. General patterns only.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from regulus.rag import RagConfig, RagPipeline
from regulus.rag import answerability as A
from regulus.rag.claim_validation import (
    CONDITION_NOT_IN_CITED,
    INVENTED_CONDITION,
    PARAGRAPH_MISATTRIBUTION,
    UNSUPPORTED_CLAIM,
    UNSUPPORTED_PREMISE,
)
from regulus.rag.remote_generator import OpenAICompatibleGenerator
from regulus.retrieval import LexicalRetriever
from regulus.retrieval.domain import GENERAL_KNOWLEDGE, IN_SCOPE, POTENTIALLY_RELATED, DomainVocabulary, ScopePolicy
from regulus.retrieval.fallback import (
    REASON_NO_RESULTS,
    REASON_REFERENCE_ONLY,
    FallbackConfig,
    SemanticFallbackRetriever,
    mention_pattern,
)
from regulus.retrieval.lexical import SearchResponse
from regulus.retrieval.models import METHOD_SEMANTIC
from regulus.retrieval.query import classify
from tests.test_answer_shape import TABLE, TEXT
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, row

VOCAB = DomainVocabulary.from_texts(["Quality management system requirements", "Medical device reporting", "Labeling",
                                     "Traceability", "Complaint files", "Food labeling"])


class FakeSemantic:
    """Returns fixed rows as semantic hits, most similar first."""

    corpus_name = "fake"

    def __init__(self, rows, similarities=None):
        self.rows, self.sims = rows, similarities or [0.9 - 0.02 * i for i in range(len(rows))]
        self.calls = 0

    def run(self, query, *, corpus=None, top_k=10, filters=None, methods=None):
        self.calls += 1
        results = [LexicalRetriever._ecfr_result(dict(r), METHOD_SEMANTIC, s, {"cosine_similarity": s})
                   for r, s in zip(self.rows[:top_k], self.sims)]
        return SearchResponse(query, classify(query).query_type, results, {}, {}, 0.0, [], {"retrieval_mode": "semantic"})


REFERRING = row("820.10", "(b)(3)", 5, text="(3) The manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter.")
UNRELATED = row("101.3", "(b)", 0, text="(b) Such statement of identity shall be in terms of the common name.")
PART_803 = [row("803.10", "", 0, text="Generally, reports are submitted electronically."),
            row("803.10", "(a)", 1, text="(a) If you are a device user facility, you must submit reports.")]


def pipeline(sem=None, response="An answer [1].", table=None, config=None, scope=True, **db_kw):
    db = TableDatabase(table if table is not None else TABLE + PART_803, **db_kw)
    lexical = LexicalRetriever(db)
    retriever = lexical if sem is None else SemanticFallbackRetriever(
        lexical, lambda: sem, FallbackConfig(), skip_semantic=ScopePolicy(VOCAB).skip_semantic if scope else None)
    g = ScriptedGenerator(response)
    return RagPipeline(retriever, g, config or RagConfig(), scope_policy=ScopePolicy(VOCAB) if scope else None), g


# ------------------------------------------------------------ semantic fallback


def test_sufficient_lexical_evidence_is_returned_unchanged_and_semantic_never_runs():
    sem = FakeSemantic([UNRELATED])
    fb, _ = pipeline(sem)
    lex, _ = pipeline(None)
    a = fb.answer("What does 21 CFR 820.10(b)(2) require?")
    b = lex.answer("What does 21 CFR 820.10(b)(2) require?")
    assert [s.result.key for s in a.context.sources] == [s.result.key for s in b.context.sources]
    assert sem.calls == 0 and a.metadata["semantic_fallback"]["invoked"] is False


def test_a_missing_identifier_is_never_answered_from_similar_text():
    sem = FakeSemantic([REFERRING])
    p, g = pipeline(sem)
    out = p.answer("What does 21 CFR 820.999 require?")
    assert sem.calls == 0 and g.calls == [] and out.metadata["fallback_type"] == "provision_not_found"


def test_a_general_question_with_no_lexical_results_falls_back_to_semantic():
    sem = FakeSemantic([REFERRING])
    p, g = pipeline(sem, table=[])
    out = p.answer("Which complaint files must be kept?")
    fb = out.metadata["semantic_fallback"]
    assert fb["invoked"] and fb["lexical_insufficient"] == REASON_NO_RESULTS
    assert [s.result.citation.label for s in out.context.sources] == ["21 CFR 820.10(b)(3)"]
    assert out.context.sources[0].tier == "supporting"  # semantic similarity never makes evidence authoritative


def test_semantic_candidates_below_the_floor_are_rejected():
    sem = FakeSemantic([REFERRING], similarities=[0.5])
    p, _ = pipeline(sem, table=[])
    out = p.answer("Which complaint files must be kept?")
    assert out.metadata["semantic_fallback"]["semantic_rejected"][0]["why"] == "below floor" and not out.context.sources


def test_general_question_fallback_is_off_by_default():
    assert FallbackConfig().general_questions is False


def test_reference_lookup_searches_by_content_and_keeps_only_passages_that_mention_the_target():
    sem = FakeSemantic([UNRELATED, REFERRING])
    p, g = pipeline(sem)
    out = p.answer("Cite the provision that requires manufacturers to notify FDA of complaints meeting part 803 criteria.")
    assert out.metadata["reference_lookup"] == ["21 CFR part 803"]
    assert out.metadata["semantic_fallback"]["lexical_insufficient"] == REASON_REFERENCE_ONLY
    labels = [s.result.citation.label for s in out.context.sources]
    assert "21 CFR 820.10(b)(3)" in labels and "21 CFR 101.3(b)" not in labels
    assert not any(l.startswith("21 CFR 803") for l in labels)  # the referenced part itself is not the answer
    assert out.metadata["answerability"]["state"] != A.WRONG_PROVISION and len(g.calls) == 1


def test_without_a_content_search_the_reference_lookup_is_still_declined():
    p, g = pipeline(None)
    out = p.answer("Cite the provision that requires manufacturers to notify FDA of complaints meeting part 803 criteria.")
    assert out.metadata["answerability"]["state"] == A.WRONG_PROVISION and g.calls == []


def test_an_unavailable_semantic_index_leaves_the_lexical_result():
    def broken():
        raise FileNotFoundError("index missing")
    retriever = SemanticFallbackRetriever(LexicalRetriever(TableDatabase([])), broken)
    p = RagPipeline(retriever, ScriptedGenerator("x"), RagConfig())
    out = p.answer("Which complaints must the manufacturer notify?")
    assert "unavailable" in out.metadata["semantic_fallback"]["skipped"] and out.no_context


@pytest.mark.parametrize("label, text, hit", [("21 CFR part 803", "criteria of part 803 of this chapter", True),
                                              ("21 CFR part 803", "part 8030 applies", False),
                                              ("21 CFR 803.50", "under § 803.50(a)", True),
                                              ("21 CFR 803.50", "under § 803.501", False)])
def test_mention_patterns(label, text, hit):
    assert bool(mention_pattern(label).search(text)) is hit


# ------------------------------------------------------------ scope policy


def test_scope_classes():
    from regulus.planning import plan_query
    s = ScopePolicy(VOCAB)
    gk = s.decide("What is the capital of France?", plan_query("What is the capital of France?"), {"fallback_used": True}, results=True)
    rel = s.decide("Which complaint files are kept?", plan_query("Which complaint files are kept?"), {"fallback_used": True}, results=True)
    named = s.decide("What does 21 CFR 820.10 require?", plan_query("What does 21 CFR 820.10 require?"), {}, results=True)
    matched = s.decide("What is the capital of France?", plan_query("What is the capital of France?"), {"fallback_used": False}, results=True)
    assert (gk.status, rel.status, named.status, matched.status) == (GENERAL_KNOWLEDGE, POTENTIALLY_RELATED, IN_SCOPE, IN_SCOPE)


def test_general_knowledge_is_declined_without_the_model_and_without_semantic_search():
    sem = FakeSemantic([REFERRING])
    p, g = pipeline(sem, table=TABLE, or_ecfr=[row("801.1", "", 0, text="Labeling.", rank=0.1)])
    out = p.answer("What is the capital of France?")
    assert out.metadata["answerability"]["state"] == A.OUT_OF_SCOPE and g.calls == [] and sem.calls == 0
    assert "does not appear to be a regulatory question" in out.answer


def test_scope_policy_off_restores_previous_behaviour():
    p, g = pipeline(None, table=TABLE, or_ecfr=[row("801.1", "", 0, text="Labeling.", rank=0.1)], config=RagConfig(scope_policy="off"))
    out = p.answer("What is the capital of France?")
    assert out.metadata["scope_policy"] is None and out.metadata["answerability"]["state"] != A.OUT_OF_SCOPE


# ------------------------------------------------------------ claim-level validation


def validate(answer, question="What do 21 CFR 820.10(b)(1) and 21 CFR 820.10(b)(4) require?"):
    from regulus.rag.validation import validate_answer
    p, _ = pipeline(None)
    out = p.answer(question)
    return validate_answer(answer, out.package), out.package


def codes(report, severity=None):
    return {p.code for p in report.problems if severity is None or p.severity == severity}


def test_wrong_paragraph_attribution_is_caught():
    rep, _ = validate("21 CFR 820.10(b)(1) [1]: " + TEXT["(b)(1)"] + "\n21 CFR 820.10(b)(4) [2]: " + TEXT["(b)(1)"])
    assert PARAGRAPH_MISATTRIBUTION in codes(rep, "error")


def test_a_provision_named_inside_quoted_text_is_not_treated_as_the_row_label():
    rep, _ = validate("21 CFR 820.10(b)(1) requires a UDI system [1]. The notices are handled under 21 CFR 820.10(b)(4) [2].")
    assert PARAGRAPH_MISATTRIBUTION not in codes(rep)


def test_dropped_condition_is_detected():
    rep, _ = validate("21 CFR 820.10(b)(2) requires traceability procedures under part 821 [1].", "What does 21 CFR 820.10(b)(2) require?")
    assert "qualifier_dropped" in codes(rep)


def test_invented_condition_and_a_misplaced_real_one_are_both_errors():
    rep, _ = validate("21 CFR 820.10(b)(1) requires a UDI system, unless the device is exempt [1]. "
                      "21 CFR 820.10(b)(4) requires advisory notices under part 806 [2].")
    assert INVENTED_CONDITION in codes(rep, "error")
    rep2, _ = validate("21 CFR 820.10(b)(2) requires traceability procedures, if applicable [2].",
                       "What do 21 CFR 820.10(b)(2) and 21 CFR 820.10(b)(4) require?")
    # an error since the 16 Oct 2026 severity experiment (was a warning)
    assert CONDITION_NOT_IN_CITED in codes(rep2, "error") and INVENTED_CONDITION not in codes(rep2)
    assert not rep2.ok


def test_an_invented_sentence_is_removed_when_the_rest_of_the_answer_is_sound():
    answer = "21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [1]. If appropriate, the rule also covers imports [1]."
    p, _ = pipeline(None, response=answer)
    out = p.answer("What does 21 CFR 820.10(b)(2) require?")
    assert "invented_conditions_removed" in out.metadata["validation"]["repair"]
    assert "covers imports" not in out.answer and "part 821" in out.answer


def test_an_invented_sentence_is_not_removed_from_an_answer_that_fails_for_another_reason():
    answer = "21 CFR 820.10(b)(2) requires traceability audits every 90 days [1]. If appropriate, the rule also covers imports [1]."
    p, _ = pipeline(None, response=answer)
    out = p.answer("What does 21 CFR 820.10(b)(2) require?")
    assert "invented_conditions_removed" not in (out.metadata["validation"]["repair"] or "")
    assert "covers imports" not in out.answer and "90 days" not in out.answer


def test_an_affirmed_false_premise_is_answered_from_the_provision():
    p, _ = pipeline(None, response="21 CFR 820.10(b)(2) requires annual traceability audits [1].")
    out = p.answer("Does 21 CFR 820.10(b)(2) require annual traceability audits?")
    assert UNSUPPORTED_PREMISE in out.metadata["validation"]["initial"]["codes"]
    assert out.metadata["fallback_type"] == "premise_not_established" and "does not state" in out.answer
    assert TEXT["(b)(2)"][:40] in out.answer


def test_a_correct_no_answer_is_not_flagged_as_a_premise():
    p, _ = pipeline(None, response="No. 21 CFR 820.10(b)(2) does not require annual audits; it requires traceability procedures under part 821, if applicable [1].")
    out = p.answer("Does 21 CFR 820.10(b)(2) require annual traceability audits?")
    assert UNSUPPORTED_PREMISE not in out.metadata["validation"]["initial"]["codes"]


def test_unsupported_claims_are_enforced_and_refusals_are_not_claims():
    rep, _ = validate("21 CFR 820.10(b)(1) requires a UDI system [1]. Quarterly biometric turbine calibration logbooks stay mandatory [2].")
    # an error since the 16 Oct 2026 severity experiment (was a warning, reported but not enforced)
    assert UNSUPPORTED_CLAIM in codes(rep, "error") and UNSUPPORTED_CLAIM not in codes(rep, "warning")
    assert rep.status == "unsupported"
    rep2, _ = validate("The available regulatory sources do not provide enough information to answer this.")
    assert UNSUPPORTED_CLAIM not in codes(rep2)


def test_an_uncited_but_supported_answer_is_not_withheld_by_a_citation_count_rule():
    p, _ = pipeline(None, response="21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable.")
    out = p.answer("What does 21 CFR 820.10(b)(2) require?")
    assert out.metadata["fallback_type"] is None


def test_a_misattributed_row_is_replaced_in_place_by_its_own_verbatim_text():
    answer = "21 CFR 820.10(b)(1) [1]: " + TEXT["(b)(1)"] + "\n21 CFR 820.10(b)(4) [2]: " + TEXT["(b)(1)"]
    p, _ = pipeline(None, response=answer)
    out = p.answer("What do 21 CFR 820.10(b)(1) and 21 CFR 820.10(b)(4) require?")
    assert "misattributed_statements_replaced" in out.metadata["validation"]["repair"]
    assert TEXT["(b)(4)"][:40] in out.answer and out.answer.count(TEXT["(b)(1)"][:40]) == 1


def test_repair_finds_a_sentence_after_its_invalid_marker_was_stripped():
    answer = "21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [1]. If appropriate, the rule also covers imports [7]."
    p, _ = pipeline(None, response=answer)
    out = p.answer("What does 21 CFR 820.10(b)(2) require?")
    assert "covers imports" not in out.answer and out.metadata["fallback_type"] is None


def test_exhaustive_verbatim_repair_quotes_every_item_and_states_missing_provisions():
    from regulus.rag.generation import verbatim_requested
    p, _ = pipeline(None)
    out = p.answer("What do 21 CFR 820.10(b)(1) through (b)(4) and 21 CFR 820.999 require?")
    text = verbatim_requested(out.package)
    for para in ("(b)(1)", "(b)(2)", "(b)(3)", "(b)(4)"):
        assert TEXT[para][:30] in text
    assert "21 CFR 820.999: not found" in text


# ------------------------------------------------------------ degenerate output


def test_repeated_sentence_detection_and_its_false_positive_guard():
    from regulus.inference.repetition import repeated_sentence
    loop = " ".join(["Quality control personnel must ensure the operations are correct."] * 3)
    legit = ("For Clause 7.5.8, the manufacturer must document a UDI system. For Clause 7.5.9.1, the manufacturer must "
             "document traceability. For Clause 8.2.3, the manufacturer must notify FDA of complaints.")
    assert repeated_sentence(loop) and repeated_sentence(legit) is None


def test_repetition_stop_fires_only_on_a_confirmed_loop():
    import torch
    from regulus.inference.repetition import CHECK_EVERY, RepetitionStop

    class Tok:
        def __init__(self, text):
            self.text = text

        def decode(self, ids, skip_special_tokens=True):
            return self.text
    ids = torch.zeros((1, 10 + CHECK_EVERY), dtype=torch.long)
    looping = RepetitionStop(Tok(" ".join(["The manufacturer must keep records of every batch."] * 3)), 10)
    fine = RepetitionStop(Tok("The manufacturer must keep records. Each batch is reviewed. Records are retained."), 10)
    assert bool(looping(ids, None)[0]) and looping.triggered and not bool(fine(ids, None)[0])


# ------------------------------------------------------------ backend seam


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append({"body": body, "auth": self.headers.get("Authorization")})
        text = "21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [1]."
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in (text[:30], text[30:]):
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n".encode())
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 50, 'completion_tokens': 20}})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            payload = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 50, "completion_tokens": 20}}
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


@pytest.fixture()
def server(monkeypatch):
    monkeypatch.setenv("REGULUS_MODEL_API_KEY", "test-key-not-logged")
    _Handler.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_remote_generator_runs_the_unchanged_pipeline(server):
    gen = OpenAICompatibleGenerator(server, "any/model")
    p = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), gen, RagConfig())
    out = p.answer("What does 21 CFR 820.10(b)(2) require?")
    assert out.model_called and out.validation.ok and out.metadata["generation"]["generated_tokens"] == 20
    body = _Handler.seen[0]["body"]
    assert body["temperature"] == 0 and body["messages"][0]["role"] == "system" and body["max_tokens"] > 0


def test_remote_generator_streams_and_reports_timing(server):
    events = []
    gen = OpenAICompatibleGenerator(server, "any/model")
    p = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), gen, RagConfig())
    out = p.answer("What does 21 CFR 820.10(b)(2) require?", on_event=lambda k, d: events.append(k))
    assert events.count("delta") == 2 and out.metadata["generation"]["finished"] is True
    assert out.timings_ms.get("model_first_token_ms") is not None


def test_remote_generator_never_records_the_api_key(server):
    gen = OpenAICompatibleGenerator(server, "any/model")
    gen.generate([{"role": "user", "content": "q"}])
    assert _Handler.seen[0]["auth"] == "Bearer test-key-not-logged"
    assert "test-key" not in json.dumps(gen.describe())


def test_backend_is_selected_by_configuration(monkeypatch):
    from regulus.config import load_settings
    from regulus.config.settings import ConfigError
    from regulus.rag.remote_generator import load_generator
    monkeypatch.setenv("REGULUS_MODEL_BACKEND", "openai_compatible")
    monkeypatch.setenv("REGULUS_MODEL_ENDPOINT", "http://127.0.0.1:1/v1")
    assert isinstance(load_generator(load_settings()), OpenAICompatibleGenerator)
    monkeypatch.delenv("REGULUS_MODEL_ENDPOINT")
    with pytest.raises(ConfigError):
        load_settings()


# ------------------------------------------------------------ evaluation and key review


def test_replay_refuses_a_prompt_it_never_recorded(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("rd", Path(__file__).resolve().parents[1] / "scripts" / "run_diagnostics.py")
    rd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rd)
    from regulus.observability.trace import sha256
    msgs = [{"role": "user", "content": "q"}]
    (tmp_path / "traces.jsonl").write_text(json.dumps({"question_id": "T", "prompt_hash": sha256(msgs), "raw_model_output": "recorded",
                                                       "finished": True, "model": {"model_id": "m"}}) + "\n")
    replay = rd.ReplayGenerator(tmp_path)
    assert replay.generate(msgs).response == "recorded"
    with pytest.raises(rd.ReplayMismatch):
        replay.generate([{"role": "user", "content": "different"}])


def test_key_review_reason_categories_are_validated():
    from regulus.evaluation.key_review import Decision, ReviewError
    base = dict(benchmark_id="b", benchmark_key="k", verification_run_id="v", question_id="Q", reviewer="R", rationale="why",
                decided_at="2026-09-30", original_citation="", original_iso_clause="")
    assert Decision(state="NEEDS_RESEARCH", reason_category="ambiguous", **base).reason_category == "ambiguous"
    with pytest.raises(ReviewError):
        Decision(state="ACCEPTED", reason_category="ambiguous", **base)
    with pytest.raises(ReviewError):
        Decision(state="REJECTED", reason_category="guess", **base)
    old = Decision.from_dict({**base, "state": "ACCEPTED"})  # records written before Stage 7 still load
    assert old.reason_category is None
