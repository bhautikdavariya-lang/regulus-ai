"""LS1 (27 Oct 2026): a "what must it contain" question is answered with the regulation's whole list."""
from types import SimpleNamespace as NS

from regulus.rag.list_answers import compose

SRC = [NS(citation="21 CFR 80.21", index=1, text="A request for certification of a batch of color additive shall:"),
       NS(citation="21 CFR 80.21(a)", index=2, text="(a) Be addressed to the Commissioner of Food and Drugs."),
       NS(citation="21 CFR 80.21(c)", index=3, text="(c) Be submitted in duplicate."),
       NS(citation="21 CFR 80.21(f)", index=4, text="(f) Be accompanied by the fee prescribed in § 80.10."),
       NS(citation="21 CFR 80.21(g)", index=5, text="(g) Be accompanied by the sample prescribed in § 80.22 consisting of:"),
       NS(citation="21 CFR 80.21(g)(1)", index=6, text="(1) Four ounces in the case of straight colors and lakes.")]
PKG = NS(requirements=(("r1", "21 CFR 80.21"),), sources=SRC)


def test_the_whole_list_is_quoted():
    out = compose(PKG, "What must our request for certification of a color additive batch contain?")
    assert out.startswith("Under 21 CFR 80.21, the regulation's list, verbatim:")
    assert all(f"[{i}]" in out for i in range(1, 7))


def test_whether_questions_and_other_questions_are_left_alone():
    assert compose(PKG, "Do we need to submit the request in duplicate?") is None
    assert compose(PKG, "Who signs the certification request?") is None


def test_a_passive_question_asks_for_contents():
    from regulus.rag.list_answers import _ASKS_CONTENTS
    assert _ASKS_CONTENTS.search("What must be recorded for complaints involving the possible failure of a device?")
    assert _ASKS_CONTENTS.search("What must be included in a servicing record?")
    assert not _ASKS_CONTENTS.search("What must be done before release?")
