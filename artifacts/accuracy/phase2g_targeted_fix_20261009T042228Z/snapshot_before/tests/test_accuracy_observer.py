"""§14: the accuracy feature is observational.

Run A answers a set of questions with the feature off; Run B answers the same
set with it on. The answer, the citations and the evidence must be identical,
byte for byte, and the only difference in the payload must be the assessment
itself.

This runs the real Stage 1-7 pipeline on the in-memory table with scripted
generations, so it covers the paths that differ from one another: a clean
answer, a repaired one, an answer the gate blocks, a provision with no
evidence, and an answer that fails validation outright. No model and no
database are needed, so it runs on every commit rather than once by hand; the
live equivalent over the real model is scripts/accuracy_regression.py.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys

from regulus.accuracy import evaluate_safely
from regulus.inference.generate import GenerationResult
from regulus.rag import RagConfig, RagPipeline
from regulus.retrieval import LexicalRetriever
from tests.test_accuracy_evaluation import PURCHASING, TABLE

# (question, what the model is scripted to say)
CASES = [
    ("What does 21 CFR 820.10(b)(2) require?", f"21 CFR 820.10(b)(2): {PURCHASING} [1]"),
    ("What does 21 CFR 820.10(b)(2) require?", "21 CFR 820.10(b)(2) obliges a maker to check bought-in goods [1]."),
    ("What do 21 CFR 820.10(b)(2) and 21 CFR 820.30(a) require?", f"21 CFR 820.10(b)(2): {PURCHASING} [1]"),
    ("What does 21 CFR 820.99(z) require?", "21 CFR 820.99(z) requires an annual audit [1]."),
    ("What does 21 CFR 820.10(b)(2) require?", ""),                      # empty: repaired
    ("What does 21 CFR 820.10(b)(2) require?", "It depends. " * 40),      # degenerate: repaired
    ("What is the capital of France?", "Paris is the capital of France."),
    ("What does 21 CFR 820.1(a)(2) say about component manufacturers?",
     "21 CFR 820.1(a)(2): Manufacturers of components or parts of finished devices must comply with this part [1]."),
]


class Scripted:
    def __init__(self, response):
        self.response = response

    def generate(self, messages, max_new_tokens=None):
        return GenerationResult("p", self.response, 500, 40, 1.0, finished=True)

    def describe(self):
        return {"model_id": "scripted"}


def answer_one(question, response):
    from tests.test_retrieval_plan import TableDatabase

    pipe = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), Scripted(response), RagConfig())
    return pipe.answer(question)


def payload(out, *, accuracy: bool) -> dict:
    """What the server sends: the answer-bearing parts, plus the assessment when on."""
    record = {
        "answer": out.answer,
        "citations": [c.to_dict() for c in out.citations],
        "evidence": [s.to_dict() for s in out.context.sources],
        "sources_text": [s.text for s in out.context.sources],
        "validation": out.validation.to_dict() if out.validation is not None else None,
        "coverage": out.coverage.to_dict() if out.coverage is not None else None,
        "package": out.package.to_dict() if out.package is not None else None,
        "metadata": {k: v for k, v in out.metadata.items() if k != "retrieval_timings_ms"},
    }
    if accuracy:
        record["accuracy"] = evaluate_safely(
            out.question, out.answer, package=out.package, citations=out.citations,
            validation=out.validation, coverage=out.coverage, model_called=out.model_called,
            fallback_type=out.metadata.get("fallback_type"),
            scope_status=(out.metadata.get("question_analysis") or {}).get("scope_status"),
        ).to_dict()
    return record


def run(*, accuracy: bool) -> list[dict]:
    return [payload(answer_one(q, r), accuracy=accuracy) for q, r in CASES]


# ------------------------------------------------------------ the regression


def test_run_a_and_run_b_deliver_the_same_answers():
    a, b = run(accuracy=False), run(accuracy=True)
    assert len(a) == len(b) == len(CASES)
    for (question, _), ra, rb in zip(CASES, a, b):
        assert ra["answer"].encode() == rb["answer"].encode(), question    # byte for byte
        assert ra["citations"] == rb["citations"], question
        assert ra["evidence"] == rb["evidence"] and ra["sources_text"] == rb["sources_text"], question
        assert ra["validation"] == rb["validation"], question
        assert ra["coverage"] == rb["coverage"] and ra["package"] == rb["package"], question
        assert ra["metadata"] == rb["metadata"], question
        # the ONLY difference in the whole payload
        assert set(rb) - set(ra) == {"accuracy"} and ra == {k: v for k, v in rb.items() if k != "accuracy"}


def test_every_case_is_assessed_and_the_assessment_is_never_empty():
    """The comparison above would also pass if the evaluator did nothing."""
    verdicts = {r["accuracy"]["answer_verdict"]["verdict"] for r in run(accuracy=True)}
    assert verdicts <= {"correct", "partial", "incorrect", "off_topic", "unverifiable",
                        "abstention_correct", "abstention_incorrect"}
    assert len(verdicts) >= 3, "the cases are meant to exercise several different verdicts"


def test_the_evaluator_does_not_mutate_the_answer_it_is_given():
    out = answer_one(*CASES[0])
    before = copy.deepcopy(payload(out, accuracy=False))
    for _ in range(3):
        evaluate_safely(out.question, out.answer, package=out.package, validation=out.validation,
                        coverage=out.coverage, model_called=out.model_called)
    assert payload(out, accuracy=False) == before


def test_the_assessment_is_reproducible():
    out = answer_one(*CASES[0])
    kwargs = dict(package=out.package, validation=out.validation, coverage=out.coverage, model_called=out.model_called)
    first = evaluate_safely(out.question, out.answer, **kwargs).to_dict()
    second = evaluate_safely(out.question, out.answer, **kwargs).to_dict()
    del first["elapsed_ms"], second["elapsed_ms"]     # wall clock is the one thing that may differ
    assert first == second


def test_the_answering_pipeline_does_not_import_the_evaluator():
    """Observer status, enforced rather than promised: nothing under regulus.rag,
    regulus.retrieval or regulus.planning may reach regulus.accuracy."""
    code = ("import regulus.rag.pipeline, regulus.rag.validation, regulus.retrieval, regulus.planning, sys;"
            "print([m for m in sys.modules if m.startswith('regulus.accuracy')])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout.strip().replace("'", '"')) == []


def test_the_evaluator_adds_no_measurable_latency_to_answering():
    """It must stay in the noise next to a 30-90 s generation; a regression here
    means something started doing real work (a query, a second pass, a model)."""
    out = answer_one(*CASES[0])
    worst = max(evaluate_safely(out.question, out.answer, package=out.package, validation=out.validation,
                                coverage=out.coverage, model_called=out.model_called).elapsed_ms
                for _ in range(20))
    assert worst < 50.0, f"{worst:.1f} ms per assessment"
