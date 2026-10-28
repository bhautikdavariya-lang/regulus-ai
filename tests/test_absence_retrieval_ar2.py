from types import SimpleNamespace

from regulus.rag import pipeline as P
from regulus.rag import validator_switches as VS
from regulus.rag.pipeline import RagPipeline, absence_topics


def test_ar2_reads_what_a_draft_says_is_not_specified():
    assert absence_topics("The retention period for traceability records is not specified in the available sources.") == \
        ["retention period for traceability records"]   # H-007: 1.1455 holds it
    assert absence_topics("The provisions do not specify renewal requirements or timelines for renewal.") == \
        ["renewal requirements or timelines for renewal"]   # G-009
    assert absence_topics("Records must be kept for 2 years [1].") == []


def _answer(text, ok=True, fallback=None, sections=("1.1315",)):
    return SimpleNamespace(answer=text, metadata={"validation": {"final": {"ok": ok}}, "fallback_type": fallback,
                                                  "section_promotion": {"sections": list(sections), "companions": []}})


def _pipe(monkeypatch, answers, found):
    pipe = RagPipeline.__new__(RagPipeline)
    calls = []

    def once(question, on_event=None, context=None):
        calls.append(pipe.__dict__.get("_ar2_extra"))
        return answers[len(calls) - 1]

    monkeypatch.setattr(pipe, "_answer_once", once)
    pipe.__dict__["_promoter"] = SimpleNamespace(absence_sections=lambda q, topics, prev: found)
    return pipe, calls


def test_ar2_keeps_the_second_answer_only_when_it_validates_with_fewer_absence_claims(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"AR2"})
    first = _answer("The retention period for traceability records is not specified in the available sources.")
    second = _answer("Records must be retained for 2 years [3].")
    pipe, calls = _pipe(monkeypatch, [first, second], ["1.1455"])
    assert pipe.answer("What records must be kept?") is second and calls == [None, ("1.1455",)]
    bad = _answer("Records must be retained for 2 years [3].", ok=False)
    pipe, _ = _pipe(monkeypatch, [first, bad], ["1.1455"])
    assert pipe.answer("What records must be kept?") is first   # an unvalidated second answer never replaces the first


def test_ar2_off_answers_once(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION - {"AR2"})
    first = _answer("The retention period for traceability records is not specified in the available sources.")
    pipe, calls = _pipe(monkeypatch, [first], ["1.1455"])
    assert pipe.answer("q") is first and calls == [None]


def test_sections_the_promotion_adds_are_optional_labels():
    import re
    src = open(P.__file__).read()
    block = src[src.index("SP2: the picker's second regulation is further evidence"):][:900]
    for prefix in ("second pick: ", "reranked: ", "absence retrieval: "):
        assert prefix in block   # MS1/MS2 and AR2 additions never make an answer fail on their own (F-020)
