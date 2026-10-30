"""AMB1 (30 Oct): a requirement written separately for each product type, asked without a product type, gets a clarifying
question; the reply naming one type is answered from that type's section. No database, no model."""
from __future__ import annotations

import pytest

from regulus.planning import plan_query
from regulus.rag import RagConfig, RagPipeline
from regulus.rag import answerability as A
from regulus.rag import product_clarification as P
from regulus.rag.conversation import ConversationContext, PriorTurn, Anchor, resolve, turn_anchor
from regulus.rag.fallback import FB_PRODUCT_CLARIFICATION
from regulus.rag.section_promotion import Promotion
from regulus.retrieval import LexicalRetriever
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, row

NET = "Declaration of net quantity of contents."
NAME = "name and place of business of manufacturer, packer, or distributor."


class _Index:
    """The section index's parallel lists (regulus.retrieval.section_index.SectionIndex)."""

    def __init__(self, rows):
        self.sections = [s for s, _, _ in rows]
        self.headings = [h for _, h, _ in rows]
        self.subparts = [sp for _, _, sp in rows]


INDEX = _Index([
    ("101.7", NET, "subpart a - general provisions"),
    ("201.51", NET, "subpart b - labeling requirements for prescription drugs and/or insulin"),
    ("201.62", NET, "subpart c - labeling requirements for over-the-counter drugs"),
    ("701.13", NET, "subpart b - labeling of specific ingredients"),
    ("801.62", NET, "subpart c - labeling requirements for over-the-counter devices"),
    ("101.5", f"Food; {NAME}", ""), ("201.1", f"Drugs; {NAME}", ""), ("801.1", f"Medical devices; {NAME}", ""),
    ("701.12", NAME.capitalize(), ""), ("501.5", f"Animal food; {NAME}", ""),
    ("101.9", "Nutrition labeling of food.", ""), ("117.20", "Plant and grounds.", ""), ("507.17", "Plant and grounds.", ""),
    ("101.1", "Principal display panel of package form food.", ""), ("201.60", "Principal display panel.", ""),
])


def cands(*secs):
    head = dict(zip(INDEX.sections, INDEX.headings))
    return [{"section": s, "heading": head.get(s, ""), "part": s.split(".")[0]} for s in secs]


def test_the_same_provision_for_several_product_types_is_asked_about():
    found = P.choices("How must net quantity of contents be declared?", cands("801.62", "101.7", "201.51", "701.13", "201.62"), INDEX)
    assert list(found) == ["food", "drug", "device", "cosmetic"]
    assert [c.section for c in found["drug"]] == ["201.51", "201.62"]
    text = P.answer(found)
    assert "21 CFR 101.7 (Declaration of net quantity of contents)" in text
    assert "21 CFR 201.62 (Declaration of net quantity of contents, Subpart C: labeling requirements for over-the-counter" in text
    assert text.endswith('for example "food" or "drugs" - and the answer will come from that section.')


def test_parallels_the_candidates_left_out_come_from_the_index():
    found = P.choices("What must the name and place of business declaration include?",
                      cands("701.12", "201.1", "117.20", "101.5", "801.1"), INDEX)
    assert P.sections(found) == ("101.5", "201.1", "801.1", "701.12", "501.5")   # 501.5 was not among the candidates


def test_fewer_than_four_ranked_product_types_is_not_ambiguous_enough():
    # K-008: record retention ranked for food, animal food and tobacco, the question naming a nonclinical study in words
    assert P.choices("What must the name and place of business declaration include?",
                     cands("701.12", "201.1", "101.5", "117.20"), INDEX) is None


@pytest.mark.parametrize("question", [
    "How must net quantity of contents be declared on a food label?",      # names its product type
    "How must an OTC drug declare its net quantity of contents?",
    "How must net quantity be declared for a color additive mixture?",     # a product the families do not cover
    "Do individually wrapped candy pieces need a net quantity of contents declaration?",   # an everyday product name
    "If a hairspray uses a chlorofluorocarbon propellant, how must net quantity of contents be declared?",
    'How must the name "acetaminophen" be displayed with the net quantity of contents?',
])
def test_a_question_naming_its_product_is_not_asked_about(question):
    assert P.choices(question, cands("801.62", "101.7", "201.62", "701.13"), INDEX) is None


def test_no_clarification_when_the_first_ranked_is_one_products_rule():
    assert P.choices("What must nutrition labeling include?", cands("101.9", "801.62", "101.7", "201.62"), INDEX) is None
    # food vs animal food CGMP (117.20 / 507.17): two product types are not enough (the FSVP questions, full300d)
    assert P.choices("What are the plant and grounds requirements?", cands("117.20", "507.17"), INDEX) is None
    # a generic heading never makes a group
    generic = _Index([("101.1", "Scope.", ""), ("201.1", "Scope.", "")])
    assert P.choices("What is the scope?", [{"section": "101.1", "heading": "Scope."}, {"section": "201.1", "heading": "Scope."}],
                     generic) is None


def test_a_question_not_using_the_headings_words_is_not_asked_about():
    # one shared word ("business") is not a subject: the lexical match was incidental
    assert P.choices("When does the rule apply to most businesses?", cands("701.12", "201.1", "101.5", "801.1"), INDEX) is None


def test_at_most_six_sections_are_offered_so_every_one_can_be_chosen():
    many = _Index([(f"{p}.{n}", NET, "") for p in (101, 201, 801, 701) for n in (7, 8)])
    found = P.choices("How must net quantity of contents be declared?",
                      [{"section": s, "heading": NET} for s in ("101.7", "201.7", "801.7", "701.7")], many)
    assert len(P.sections(found)) == P.MAX_SECTIONS


@pytest.mark.parametrize("reply, family", [
    ("food", "food"), ("It is for food.", "food"), ("medical device", "device"), ("For an OTC drug", "drug"),
    ("cosmetics", "cosmetic"), ("It's a dietary supplement", "food"), ("a shampoo", "cosmetic"), ("sunscreen", "drug"),
])
def test_a_reply_naming_one_offered_type_chooses_it(reply, family):
    anchor = ("101.7", "201.51", "201.62", "801.62", "701.13")
    fam, secs = P.narrowed(reply, anchor)
    assert fam == family and all(P.family_of(s) == family for s in secs) and secs


@pytest.mark.parametrize("reply", [
    "What are the food facility registration requirements and when must they be renewed?",   # a new question
    "food or drugs",                                                                          # two types
    "tobacco",                                                                                # not offered
])
def test_other_replies_do_not_choose(reply):
    assert P.narrowed(reply, ("101.7", "201.62", "801.62", "701.13")) is None


def test_one_family_anchor_is_never_narrowed():
    assert P.narrowed("food", ("101.7", "101.9")) is None


def test_suggestions_are_the_offered_types():
    assert P.suggestions(["101.7", "201.51", "201.62", "801.62", "701.13"]) == [
        "It is for food.", "It is for drugs.", "It is for medical devices.", "It is for cosmetics."]
    assert P.suggestions(["101.7"]) == []


# ------------------------------------------------------------ conversation


def _ctx(question, cfr):
    return ConversationContext((PriorTurn(question, Anchor(cfr=cfr)),))


def test_the_reply_is_answered_from_the_chosen_section(monkeypatch):
    from regulus.rag import validator_switches as VS
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"AMB1"})
    q = "How must net quantity of contents be declared?"
    fu = resolve("It is for medical devices.", _ctx(q, ("101.7", "201.51", "201.62", "801.62", "701.13")),
                 names_provision=False, other_entity=False)
    assert fu.anchored and fu.reason == "product_type_chosen" and fu.anchor == Anchor(cfr=("801.62",))
    assert fu.question == f"{q} (medical devices: 21 CFR 801.62)"
    assert [r.canonical for r in plan_query(fu.question).requirements] == ["21 CFR 801.62"]
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION - {"AMB1"})
    off = resolve("It is for medical devices.", _ctx(q, ("101.7", "201.51", "201.62", "801.62", "701.13")),
                  names_provision=False, other_entity=False)
    assert off.reason != "product_type_chosen"


def test_a_clarification_turn_anchors_every_offered_section():
    plan = plan_query("How must net quantity of contents be declared? (21 CFR 101.7, 201.51, 201.62, 801.62, 701.13)")
    pr = Promotion(sections=("101.7", "201.51", "201.62", "801.62", "701.13"), companions=(), method="product_clarification")
    assert turn_anchor(plan, pr, None).cfr == ("101.7", "201.51", "201.62", "801.62", "701.13")
    picked = Promotion(sections=("101.7", "201.51", "201.62", "801.62", "701.13"), companions=(), method="picker")
    assert len(turn_anchor(plan, picked, None).cfr) == 4   # any other promotion: as before


# ------------------------------------------------------------ pipeline: no model call


TABLE = [row(s, "", 0, text=f"{s} text on the net quantity of contents declaration.", section_heading=NET)
         for s in ("101.7", "201.51", "201.62", "801.62", "701.13")]


class _Promoter:
    mode = "picker"
    generator = None

    def resolve(self, question, parts=None, named_only=False):
        found = P.choices(question, cands("801.62", "101.7", "201.51", "701.13", "201.62"), INDEX)
        return Promotion(sections=P.sections(found), companions=(), method="product_clarification",
                         choices=tuple((k, tuple((c.section, c.heading, c.subpart) for c in v)) for k, v in found.items()))


def test_the_pipeline_asks_without_calling_the_model(monkeypatch):
    from regulus.rag import validator_switches as VS
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"AMB1"})
    g = ScriptedGenerator("21 CFR 801.62 requires a statement [1].")
    p = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), g, RagConfig(section_promotion="picker", answerability="gate"))
    monkeypatch.setattr(p, "section_promoter", lambda: _Promoter())
    out = p.answer("How must net quantity of contents be declared?")
    assert g.calls == []
    gate = out.metadata["answerability"]
    assert gate["state"] == A.AMBIGUOUS and gate["blocking_conditions"] == ["product_unspecified"]
    assert out.metadata["fallback_type"] == FB_PRODUCT_CLARIFICATION
    assert out.answer.startswith("The answer depends on the type of product")
    assert "- Medical devices: 21 CFR 801.62" in out.answer


def test_the_reply_turn_is_answered_from_the_chosen_section(monkeypatch):
    from regulus.rag import validator_switches as VS
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"AMB1", "CQ1"})
    g = ScriptedGenerator("21 CFR 101.7 requires the net quantity statement on the principal display panel [1].")
    p = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), g, RagConfig(section_promotion="picker", answerability="gate"))
    monkeypatch.setattr(p, "section_promoter", lambda: None)
    q = "How must net quantity of contents be declared?"
    ctx = ConversationContext((PriorTurn(q, Anchor(cfr=("101.7", "201.51", "201.62", "801.62", "701.13"))),))
    out = p.answer("It is for food.", context=ctx)
    fu = out.metadata["conversation"]["followup"]
    assert fu["reason"] == "product_type_chosen" and fu["question"] == f"{q} (food: 21 CFR 101.7)"
    assert len(g.calls) == 1   # the answer only: CQ1 did not rewrite the reader's choice
    assert out.metadata["conversation"]["anchor"]["cfr"] == ["101.7"]
