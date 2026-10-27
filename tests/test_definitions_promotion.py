"""DF1 (27 Oct 2026): a question asking how FDA's definitions classify what it describes is resolved to the definition
paragraphs (regulus.rag.section_promotion.SectionPromoter.definitions_asked)."""
import pytest

from regulus.rag import validator_switches
from regulus.rag.section_promotion import SectionPromoter

_70_3 = [
    ("(f)", "(f) A color additive is any material, not exempted under section 201(t) of the act, that is a dye, pigment, "
            "or other substance ... capable of imparting a color."),
    ("(g)", "(g) For a material otherwise meeting the definition of color additive to be exempt from section 721 of the "
            "act, on the basis that it is used solely for a purpose other than coloring, ..."),
    ("(i)", "(i) Safe means that there is convincing evidence that establishes with reasonable certainty that no harm will result."),
    ("(j)", "(j) The term straight color means a color additive listed in parts 73, 74, and 81 of this chapter, and includes lakes."),
    ("(k)", "(k) The term mixture means a color additive made by mixing two or more straight colors, or one or more straight "
            "colors and one or more diluents."),
    ("(l)", "(l) The term lake means a straight color extended on a substratum by adsorption, coprecipitation, or chemical combination."),
    ("(m)", "(m) The term diluent means any component of a color additive mixture that is not of itself a color additive."),
    ("(s)", "(s) The term area of the eye means the area enclosed within the circumference of the supra-orbital ridge ..."),
    ("(u)", "(u) The hair dye exemption in section 601(a) of the act applies to coal tar hair dyes intended for use in altering the color of the hair."),
    ("(v)", "(v) The terms externally applied drugs and externally applied cosmetics mean drugs or cosmetics applied only to external parts of the body."),
]


class _DB:
    def query(self, sql, params):
        rows = _70_3 if params.get("s") == "70.3" else []
        return [{"paragraph_path": p, "body_text": t} for p, t in rows]


@pytest.fixture
def promoter(monkeypatch):
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", frozenset({"DF1"}))
    return SectionPromoter(db=_DB(), mode="lexical", index=object())


def test_a_color_additive_question_gets_the_definition_and_its_limit(promoter):
    q = ("Our shimmer body lotion uses mica coated with iron oxides, and our lip scrub has cocoa powder that tints it "
         "brown. Are these 'color additives' in FDA's sense?")
    assert promoter.definitions_asked(q) == ["70.3(f)", "70.3(g)"]


def test_one_word_terms_count_among_what_is_classified(promoter):
    q = ("Our pigment supplier sells us a 'D&C Red lake blend' in a castor-oil carrier. How do FDA's definitions "
         "classify the lake, the blend and the oil?")
    assert sorted(promoter.definitions_asked(q)) == ["70.3(j)", "70.3(k)", "70.3(l)", "70.3(m)"]


def test_quoted_terms_and_an_exemption(promoter):
    q = ("We make a brow tint, a lip gloss and a coal-tar-based permanent hair dye. How do FDA's color additive "
         "definitions treat 'area of the eye', 'externally applied' and the hair dye exemption?")
    assert promoter.definitions_asked(q) == ["70.3(s)", "70.3(u)", "70.3(v)"]


def test_the_acts_definitions_and_plain_questions_are_left_alone(promoter):
    assert promoter.definitions_asked("How does MoCRA define 'safe' for safety substantiation?") == []
    assert promoter.definitions_asked("Can we use a lake of FD&C Blue No. 1 in an eye shadow?") == []


def test_off_without_the_switch(monkeypatch):
    monkeypatch.setattr(validator_switches, "VALIDATOR_PRECISION", frozenset())
    pr = SectionPromoter(db=_DB(), mode="lexical", index=object())
    assert pr.definitions_asked("Are these 'color additives' in FDA's sense?") == []


def test_a_listing_silent_on_eye_use_is_the_eye_area_rule():
    from regulus.rag.section_promotion import _LISTING_SILENT_ON_EYE

    assert _LISTING_SILENT_ON_EYE.search("We want to use a certified FD&C red that's listed for cosmetics in our new "
                                         "eyeshadow. The listing doesn't mention eye-area use. Can we use it?")
    assert _LISTING_SILENT_ON_EYE.search("The color is not listed for the area of the eye. May we use it in mascara?")
    assert not _LISTING_SILENT_ON_EYE.search("Is FD&C Green No. 3 permitted in eye shadow?")


def test_df2_the_acts_definitions_need_the_act_named(monkeypatch):
    from regulus.rag.section_promotion import _NAMES_ACT

    assert _NAMES_ACT.search("is it a cosmetic under the fd&c act definition?")
    assert _NAMES_ACT.search("how does mocra define 'safe'?")
    assert not _NAMES_ACT.search("how does part 70 define 'safe' for a color additive?")
