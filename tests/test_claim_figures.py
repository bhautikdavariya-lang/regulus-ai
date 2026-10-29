"""FC2 (29 Oct): a figure stated under one paragraph's citation that only another supplied paragraph contains."""
from types import SimpleNamespace

import pytest

from regulus.rag import validator_switches as VS
from regulus.rag.claim_validation import FIGURE_MISATTRIBUTED, check_claims

# 117.201(c)(2)(i) is a lead-in; its children carry the deadlines (300Q F-016)
ROWS = [(16, "(c)(2)(i)", "(i) Submitted to FDA initially:"),
        (17, "(c)(2)(i)(A)", "(A) By December 17, 2018, for a facility that begins operations before September 17, 2018;"),
        (18, "(c)(2)(i)(B)", "(B) Before beginning operations, for a facility that begins operations after September 17, 2018; or"),
        (19, "(c)(2)(i)(C)", "(C) By July 31 of the applicable calendar year, when the status of a facility changes")]
PKG = SimpleNamespace(sources=[SimpleNamespace(index=i, text=t, citation=f"21 CFR 117.201{p}", requirement_ids=("r1",),
                                               tier="exact") for i, p, t in ROWS], answer_style="restate")
IDENT = lambda s: ("21", "117.201", s.citation.split("117.201")[1])
RELATED = lambda a, b: a[:2] == b[:2] and (a[2].startswith(b[2]) or b[2].startswith(a[2]))


def codes(sentence):
    return [f.code for f in check_claims([sentence], PKG, question="What must a qualified facility submit?",
                                         identity=IDENT, related=RELATED)]


@pytest.fixture(autouse=True)
def fc2_on(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION | {"FC2"})


def test_a_deadline_under_the_wrong_sibling_is_misattributed():
    assert FIGURE_MISATTRIBUTED in codes("21 CFR 117.201(c)(2)(i)(B) [18]: Submitted by July 31 of the applicable year.")


def test_the_same_deadline_under_its_own_paragraph_is_not():
    assert FIGURE_MISATTRIBUTED not in codes("21 CFR 117.201(c)(2)(i)(C) [19]: Submitted by July 31 of the applicable year.")


def test_a_lead_in_cited_for_its_childs_figure_is_tolerated():
    assert FIGURE_MISATTRIBUTED not in codes("21 CFR 117.201(c)(2)(i) [16]: Submitted initially by December 17, 2018.")


def test_paragraph_designators_and_section_numbers_are_not_figures():
    assert FIGURE_MISATTRIBUTED not in codes("21 CFR 117.201(c)(2)(i)(B) [18]: Before beginning operations (see 117.201(c)(2)(i)(C)).")


def test_off_without_the_switch(monkeypatch):
    monkeypatch.setattr(VS, "VALIDATOR_PRECISION", VS.VALIDATOR_PRECISION - {"FC2"})
    assert FIGURE_MISATTRIBUTED not in codes("21 CFR 117.201(c)(2)(i)(B) [18]: Submitted by July 31 of the applicable year.")
