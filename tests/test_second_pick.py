"""SP2: the picker's second regulation joins the first as a companion when it is in the same part, outside the
cosmetics programme (regulus.rag.section_promotion.second_in_part, 26 Oct 2026)."""
import regulus.rag.validator_switches as VS
from regulus.rag.section_promotion import second_in_part


def _c(section, statute=False):
    return {"section": section, "part": section.split(".")[0], "statute": statute}


CANDS = [_c("11.200"), _c("11.300"), _c("117.425"), _c("1.505"), _c("74.2708"), _c("82.2708"), _c("605", statute=True)]


def test_off_without_the_switch(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset())
    assert second_in_part([1, 2], CANDS, CANDS[0]) is None


def test_same_part_second_pick_joins(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset({"SP2"}))
    assert second_in_part([1, 2], CANDS, CANDS[0]) == "11.300"


def test_other_part_cosmetics_and_act_picks_do_not(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset({"SP2"}))
    assert second_in_part([3, 4], CANDS, CANDS[2]) is None          # 117.425 then 1.505: another part
    assert second_in_part([5, 6], CANDS, CANDS[4]) is None          # a cosmetics listing: its own companion rules
    assert second_in_part([1, 7], CANDS, CANDS[0]) is None          # an Act section is not a regulation
    assert second_in_part([1], CANDS, CANDS[0]) is None


def test_after_a_rerank_veto_the_final_pick_decides(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset({"SP2"}))
    assert second_in_part([3, 2], CANDS, CANDS[0]) == "11.300"      # veto 117.425 -> 11.200: 11.300 is its part


# ------------------------------------------------------------ PO2: part-only questions outside the cosmetics programme


def test_po2_resolves_a_part_only_question_in_any_part(monkeypatch):
    from regulus.planning.plan import plan_query
    from regulus.rag.pipeline import may_promote

    q = "What are the reserve sample requirements under Part 211?"
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset())
    assert may_promote(q, plan_query(q)) is None
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset({"PO2"}))
    assert may_promote(q, plan_query(q)) == "any"
    for q in ("Under 16 CFR Part 500, what must a label state?", "Which FDA guidance covers drug labeling under Part 201?",
              "Under the EU Cosmetics Regulation, what must a lipstick label list?"):
        assert not may_promote(q, plan_query(q)), q
    q = "What does FD&C Act § 607 require of a cosmetics facility?"
    assert may_promote(q, plan_query(q)) == "named_statute"


# ------------------------------------------------------------ SA1: the FD&C Act offered to a general question


class _Statute:
    by_sec = {"301": [0], "403": [1], "604": [2], "910": [3]}


def test_sa1_offers_a_general_question_the_act_sections_it_is_about(monkeypatch):
    from regulus.rag import section_promotion as SP

    class _Promoter(SP.SectionPromoter):
        def __init__(self):
            self.mode, self._statute_ix, self.db = "picker", _Statute(), None

        @property
        def statute(self):
            return self._statute_ix

        def named_statute(self, question, lex):
            return []

        def candidates(self, question, parts=None):
            return ["tobacco"], [{"section": "1114.7", "part": "1114", "heading": "", "subpart": ""}]

        def statute_candidates(self, lexemes, question=None, offered=SP.STATUTE_OFFERED):
            return [{"statute": True, "section": s} for s in offered]

    monkeypatch.setattr(SP.SectionIndex, "question_lexemes", staticmethod(lambda db, q: ["tobacco"]))
    p = _Promoter()
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset())
    assert [c["section"] for c in p.prepare("What must a PMTA contain?")[1]] == ["1114.7"]
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", frozenset({"SA1"}))
    # chapter VI stays the cosmetics offering, 301 is never offered
    assert [c["section"] for c in p.prepare("What must a PMTA contain?")[1]] == ["1114.7", "403", "910"]
