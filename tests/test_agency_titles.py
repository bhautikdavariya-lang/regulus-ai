"""Agency resolution for CFR references (regulus.retrieval.references, REGULUS_AGENCY_TITLES, OFF by default).

Found on the noise set (2026-10-20): "What does FAA Part 107 require for a remote drone pilot certificate?" was parsed
as 21 CFR part 107 (infant formula) and answered from it. A reference written without a title takes the title of an
agency the question names right next to it; everything else keeps the Title 21 default."""

import pytest

import regulus.retrieval.references as references


@pytest.fixture
def resolving(monkeypatch):
    monkeypatch.setattr(references, "AGENCY_TITLES_ENABLED", True)


def refs(text):
    return [r.canonical for r in references.parse_cfr_references(text)]


@pytest.mark.parametrize("question,expected", [
    ("What does FAA Part 107 require for a remote drone pilot certificate?", ["14 CFR part 107"]),
    ("What do EPA rules in part 152 say?", ["40 CFR part 152"]),
    ("What does Part 1910 of the OSHA standards require for scaffolds?", ["29 CFR part 1910"]),
    ("What does the Federal Aviation Administration's part 107 cover?", ["14 CFR part 107"]),
    ("USDA organic part 205 labeling?", ["7 CFR part 205"]),
])
def test_an_explicit_non_fda_agency_sets_the_title(resolving, question, expected):
    assert refs(question) == expected


@pytest.mark.parametrize("question,expected", [
    ("What does Part 107 require?", ["21 CFR part 107"]),                         # no agency: Title 21, as before
    ("Does FDA's Part 11 apply to electronic records?", ["21 CFR part 11"]),
    ("What does 21 CFR 820.30 require?", ["21 CFR 820.30"]),
    ("What does 14 CFR part 107 require?", ["14 CFR part 107"]),                  # an explicit title is never changed
    ("The FAA is unrelated. What does part 820 require?", ["21 CFR part 820"]),   # another sentence
    ("What does 820.30(b) through (d) require?", ["21 CFR 820.30(b)", "21 CFR 820.30(c)", "21 CFR 820.30(d)"]),
])
def test_fda_and_ambiguous_references_keep_their_title(resolving, question, expected):
    assert refs(question) == expected


def test_mixed_references_resolve_independently(resolving):
    assert refs("Compare FAA part 107 with 21 CFR 820.30.") == ["14 CFR part 107", "21 CFR 820.30"]


@pytest.mark.parametrize("question", ["What does FAA part require?", "What does 21 CFR part require?",
                                      "What does part 0 of the FAA rules say?", "FAA rules for drones?"])
def test_malformed_or_missing_references_yield_nothing(resolving, question):
    assert refs(question) == []


def test_off_by_default_the_title_21_default_is_unchanged():
    assert references.AGENCY_TITLES_ENABLED is False
    assert refs("What does FAA Part 107 require?") == ["21 CFR part 107"]
