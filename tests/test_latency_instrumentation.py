"""Latency baseline instrumentation: timings are recorded, answers are not touched.

No model: the first-token timer is exercised with a fake `generate()` that
calls the streamer the way transformers does (prompt ids first, then one call
per new token), and the pipeline with scripted generators.
"""

from __future__ import annotations

from regulus.inference.generate import _FirstTokenTimer
from regulus.inference.types import GenerationResult
from regulus.rag import RagConfig, RagPipeline
from regulus.retrieval import LexicalRetriever
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase

STAGE_KEYS = ("plan_ms", "retrieval_ms", "context_ms", "package_ms", "prompt_ms", "generation_ms", "validation_ms",
              "citations_ms", "total_ms", "metadata_ms")


def test_first_token_timer_skips_the_prompt_and_forwards_everything():
    seen = []

    class Inner:
        def put(self, v):
            seen.append(v)

        def end(self):
            seen.append("end")

    t = _FirstTokenTimer(Inner())
    t.put("prompt ids")
    assert t.first_token_at is None          # the prompt is not a generated token
    t.put("token 1")
    first = t.first_token_at
    t.put("token 2")
    t.end()
    assert first is not None and t.first_token_at == first
    assert seen == ["prompt ids", "token 1", "token 2", "end"]  # the caller's streamer sees exactly what it did before


def test_decode_rate_excludes_prefill_and_is_absent_when_unmeasured():
    g = GenerationResult("p", "x", 1000, 101, 11.0, finished=True, first_token_seconds=1.0)
    assert g.decode_tokens_per_second == 10.0 and round(g.tokens_per_second, 2) == 9.18
    assert GenerationResult("p", "x", 1000, 101, 11.0).decode_tokens_per_second is None
    # positional construction used across the tests still works (new fields default to None)
    assert GenerationResult("p", "x", 500, 40, 1.0, True).first_token_seconds is None


class TimedGenerator(ScriptedGenerator):
    def generate(self, messages, max_new_tokens=None):
        self.calls.append({"messages": messages, "max_new_tokens": max_new_tokens})
        return GenerationResult("p", self.response, 500, 41, 5.0, finished=True,
                                prepare_seconds=0.004, first_token_seconds=1.0, detokenize_seconds=0.001)


def test_pipeline_records_every_stage_and_the_model_breakdown():
    out = RagPipeline(LexicalRetriever(TableDatabase()), TimedGenerator("21 CFR 820.10(b)(2) requires traceability [1]."),
                      RagConfig()).answer("What does 21 CFR 820.10(b)(2) require?")
    t = out.timings_ms
    assert all(k in t for k in STAGE_KEYS)
    assert t["model_first_token_ms"] == 1000.0 and t["model_decode_ms"] == 4000.0 and t["model_prepare_ms"] == 4.0
    g = out.metadata["generation"]
    assert g["decode_tokens_per_second"] == 10.0 and g["tokens_per_second"] == 8.2


def test_instrumentation_does_not_change_the_answer_or_the_prompt():
    answer = "21 CFR 820.10(b)(2) requires traceability [1]."
    plain, timed = ScriptedGenerator(answer), TimedGenerator(answer)
    a = RagPipeline(LexicalRetriever(TableDatabase()), plain, RagConfig()).answer("What does 21 CFR 820.10(b)(2) require?")
    b = RagPipeline(LexicalRetriever(TableDatabase()), timed, RagConfig()).answer("What does 21 CFR 820.10(b)(2) require?")
    assert a.answer == b.answer and plain.calls[0]["messages"] == timed.calls[0]["messages"]
    assert plain.calls[0]["max_new_tokens"] == timed.calls[0]["max_new_tokens"]
    assert "model_first_token_ms" not in a.timings_ms  # generators that do not measure it report nothing, not zero
