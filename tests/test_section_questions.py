"""Step D: index-time question generation (scripts/build_section_questions.py) and the HQ1 question index."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_section_questions import parse_questions  # noqa: E402

from regulus.retrieval import section_questions as SQ  # noqa: E402


def test_a_good_reply_gives_its_questions():
    reply = "1. How long must supplier records be kept?\n2. Who reviews the records?\n- What must a record show?"
    assert parse_questions(reply) == (["How long must supplier records be kept?", "Who reviews the records?",
                                       "What must a record show?"], None)


def test_a_line_citing_a_section_or_not_a_question_is_dropped_on_its_own():
    reply = "Here are the questions:\n1. What does 21 CFR 117.315 require?\n2. Who signs?\n3. When is it due?\n4. Does it apply under part 11?"
    assert parse_questions(reply) == (["Who signs?", "When is it due?", "Does it apply under part 11?"], None)
    assert parse_questions("Who must comply with this regulation?\nWho signs?\nWhen?")[0] == \
        ["Who must comply with this regulation?", "Who signs?", "When?"]   # how users ask: kept


def test_too_few_usable_questions_rejects_the_reply():
    questions, why = parse_questions("What does § 1.1113(d) say?\nWho signs?\nWhen?")
    assert questions == [] and why.startswith("2 usable questions")


class _Embedder:
    """Bag-of-words vectors over a tiny vocabulary: enough to rank by shared words."""

    VOCAB = ["keep", "records", "long", "signs", "batch", "label", "allergen", "warning"]

    def _v(self, text):
        v = np.array([float(w in text.lower()) for w in self.VOCAB], dtype=np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    def embed_batch(self, texts):
        return np.stack([self._v(t) for t in texts])

    def embed_query(self, text):
        return self._v(text)

    def describe(self):
        return {"revision": "fake"}


def _index(tmp_path, monkeypatch):
    monkeypatch.setattr(SQ, "CACHE_DIR", tmp_path)
    path = tmp_path / "q.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in [
        {"section": "117.315", "part": "117", "questions": ["How long do we keep records?", "Who signs records?"]},
        {"section": "101.17", "part": "101", "questions": ["When does a label need an allergen warning?"]},
        {"section": "111.1", "part": "111", "questions": [], "rejected": "2 questions"}]))
    return SQ.SectionQuestions.load(path, _Embedder()), path


def test_sections_rank_by_their_best_question_inside_the_parts_asked(tmp_path, monkeypatch):
    ix, _ = _index(tmp_path, monkeypatch)
    assert ix.rank("how long should we keep batch records")[0][0] == "117.315"
    assert ix.rank("label allergen warning", parts=("117",), min_score=0.5) == []   # 101.17 is outside the part asked
    assert ix.rank("label allergen warning", min_score=0.99)[0][0] == "101.17"


def test_vectors_are_cached_by_content(tmp_path, monkeypatch):
    _, path = _index(tmp_path, monkeypatch)
    assert len(list(tmp_path.glob("vectors_*.npy"))) == 1
    SQ.SectionQuestions.load(path, _Embedder())
    assert len(list(tmp_path.glob("vectors_*.npy"))) == 1


def test_without_the_questions_file_the_index_is_off(tmp_path):
    assert SQ.section_questions(tmp_path / "absent.jsonl") is None
