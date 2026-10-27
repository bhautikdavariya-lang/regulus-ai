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


def test_ls2_what_a_list_section_requires_is_its_whole_list(monkeypatch):
    from regulus.rag import validator_switches as VS
    src = [NS(citation="21 CFR 820.10", index=1, text="A manufacturer subject to this part as described by § 820.1(a) must:"),
           NS(citation="21 CFR 820.10(a)", index=2, text="(a) Document. Document a quality management system that complies with ISO 13485; and"),
           NS(citation="21 CFR 820.10(b)", index=3, text="(b) Comply, as appropriate, with other applicable requirements."),
           NS(citation="21 CFR 820.10(c)", index=4, text="(c) Design and development. Manufacturers of class II devices must comply with Clause 7.3.")]
    pkg = NS(requirements=(("r1", "21 CFR 820.10"),), sources=src)
    q = "What does 21 CFR 820.10 require of a manufacturer subject to Part 820?"
    assert compose(pkg, q) is None                                   # LS2 off
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"LS2"})
    out = compose(pkg, q)
    assert out.startswith("Under 21 CFR 820.10, the regulation's list, verbatim:") and all(f"[{i}]" in out for i in range(1, 5))
    assert compose(pkg, "Is a class I device covered by 21 CFR 820.10?") is None


def test_no_module_constant_is_shadowed_by_a_local_import_in_the_pipeline():
    # 27 Oct: a local re-import of FB_COMPOSED_LIST made it unbound in answer() whenever LS1's branch did not run
    import types
    from regulus.rag import pipeline as P
    for cls in (P.RagPipeline,):
        for name, f in vars(cls).items():
            if isinstance(f, types.FunctionType):
                assert not [n for n in f.__code__.co_varnames if n.isupper() and n in vars(P)], name


def test_ws1_an_overview_of_the_sections_own_subject_is_the_whole_section():
    from regulus.rag.list_answers import compose_section
    src = [NS(citation="21 CFR 211.170", index=1, heading="Reserve samples.", text="Reserve samples shall be retained as follows."),
           NS(citation="21 CFR 211.170(a)", index=2, heading="Reserve samples.", text="(a) A reserve sample shall consist of at least twice the quantity necessary for all tests."),
           NS(citation="21 CFR 211.170(b)", index=3, heading="Reserve samples.", text="(b) Reserve samples shall be examined visually at least once a year.")]
    pkg = NS(requirements=(("r1", "21 CFR 211.170"),), sources=src)
    out = compose_section(pkg, "What are the reserve sample requirements under Part 211?")
    assert out.startswith("Under 21 CFR 211.170, the regulation's text in full (Reserve samples), verbatim:")
    assert all(f"[{i}]" in out for i in (1, 2, 3))
    assert compose_section(pkg, "How long must reserve samples be kept?") is None          # a specific question
    assert compose_section(pkg, "What are the stability testing requirements?") is None    # another subject


def test_a_question_of_several_parts_takes_the_list_only_when_the_list_answers_each_part():
    from regulus.rag.list_answers import _asks_covered
    items = "(a) examined for accuracy: (1) UDI (2) Expiration date (3) Storage instructions"
    assert not _asks_covered("What controls prevent mixups, and what must be documented?", items)
    assert _asks_covered("What must the request include, and how is it submitted?", "shall: (c) Be submitted in duplicate.")
    assert _asks_covered("What must a servicing record contain?", items)   # one part: unchanged
