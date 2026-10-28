from types import SimpleNamespace

from regulus.rag import section_promotion as SP
from regulus.rag.section_promotion import SectionPromoter, authority_sections
from regulus.retrieval.statute import StatuteIndex


def test_au1_authority_of_the_pmta_part_is_910_not_502():
    secs = authority_sections(["1114"])
    assert "910" in secs and "502" not in secs   # T-002 was offered 502 (SA1, 26 Oct)


def _index(rows):
    st = StatuteIndex.__new__(StatuteIndex)
    st.rows = rows
    st.by_sec = {"910": list(range(len(rows)))}
    st.idf, st.row_lex = {"application": 1.0}, [set() for _ in rows]
    st.usc = lambda s: "387j"
    return st


def test_ap1_blocks_follow_the_cross_encoder_not_word_overlap():
    rows = [{"paragraph_path": "(a)", "body_text": "x" * 900}, {"paragraph_path": "(b)", "body_text": "y" * 900},
            {"paragraph_path": "(c)", "body_text": "z" * 900}]
    st = _index(rows)
    st.row_lex = [{"application"}, set(), set()]   # word overlap favours (a)
    kept, _ = st.blocks("910", {"application", "contain", "pmta"}, budget=1000, header=0, prefer={"(b)": 0.9, "(a)": 0.1})
    assert kept == [[1]]   # T-001: 910(b) holds what an application must contain


class _Para(SimpleNamespace):
    pass


def test_ap1_scores_the_sections_most_similar_paragraphs(monkeypatch):
    paras = [(_Para(path="(b)(1)"), 0.8), (_Para(path="(a)"), 0.5)]
    pd = SimpleNamespace(section_paragraphs=lambda q, s: paras, text=lambda p: "text")
    rr = SimpleNamespace(score=lambda q, passages: [0.95, 0.2])
    import regulus.retrieval.paragraph_dense as PD
    import regulus.retrieval.rerank as RR
    monkeypatch.setattr(PD, "paragraph_dense", lambda db: pd)
    monkeypatch.setattr(RR, "reranker", lambda name: rr)
    monkeypatch.setattr(SP, "RERANKER", "bge-m3")
    pr = SectionPromoter.__new__(SectionPromoter)
    pr.db = None
    assert pr.act_paragraph_scores("What must a PMTA contain?", "910") == {"(b)(1)": 0.95, "(a)": 0.2}


def test_au2_a_lone_act_section_brings_its_implementing_regulation(monkeypatch):
    pr = SectionPromoter.__new__(SectionPromoter)
    cands = [{"section": "101.4", "part": "101"}, {"section": "801.62", "part": "801"}, {"section": "403", "part": "FDCA", "statute": True}]
    pr.__dict__["_order_scores"] = ("q", ("101.4", "801.62", "403"), {"101.4": (0.8, ""), "801.62": (0.9, "")})
    assert pr.implementing_regulation("q", "403", cands) == "101.4"   # L-010: Part 101 is issued under 403; 801 is not
