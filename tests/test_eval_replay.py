"""run_cosmetics_eval --replay-promotions answers as the recorded run did (29 Oct)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_cosmetics_eval as R  # noqa: E402


class _Pipe:
    def __init__(self):
        self.promoter = type("Promoter", (), {})()

    def section_promoter(self):
        return self.promoter


def test_a_replayed_promotion_keeps_its_method_and_reranker_score():
    """Q2 quotes a withheld answer only for a picker promotion with a reranker score: a promotion replayed as
    method "replay" without one was answered differently from the run it replays."""
    pipe = _Pipe()
    R._replay(pipe, "q", {"sections": ["820.45"], "companions": ["820.35"], "method": "picker", "rerank": 0.947,
                          "picker_output": "21 CFR 820.45", "notes": ["reranked: 820.35"]})
    pr = pipe.promoter.resolve("q")
    assert (pr.method, pr.rerank, pr.citations, pr.notes) == ("picker", 0.947, ("820.45", "820.35"), ("reranked: 820.35",))


def test_a_question_recorded_without_a_promotion_gets_none():
    pipe = _Pipe()
    R._replay(pipe, "q", {"sections": [], "method": "picker"})
    assert pipe.promoter.resolve("q") is None
