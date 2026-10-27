"""FX1 (27 Oct 2026): the example never comes from the question's own provisions or from the question itself."""
import numpy as np

from regulus.rag import answer_examples as AX


class _Emb:
    def embed_query(self, text):
        v = np.zeros(8, dtype=np.float32)
        for w in text.lower().split():
            v[sum(map(ord, w)) % 8] += 1.0
        return v


def test_the_example_skips_covered_sections_and_the_question_itself(monkeypatch):
    ex = [{"id": "A", "sections": ["70.3"], "question": "Is cocoa a color additive?", "covers": "x"},
          {"id": "B", "sections": ["71.1"], "question": "What must a color additive petition contain?", "covers": "y"},
          {"id": "C", "sections": ["70.19"], "question": "What deposit is due for a petition?", "covers": "z"}]
    emb = _Emb()
    vecs = np.array([emb.embed_query(e["question"]) for e in ex])
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    monkeypatch.setitem(AX._CACHE, id(emb), (ex, vecs))
    assert AX.choose(emb, "What must a color additive petition contain?", {"70.19"})["id"] != "B"   # never itself
    assert AX.choose(emb, "What deposit is due for our petition?", {"70.19"})["id"] != "C"          # nor its provision


def test_without_an_embedder_there_is_no_example():
    assert AX.choose(None, "Is cocoa a color additive?", set()) is None
