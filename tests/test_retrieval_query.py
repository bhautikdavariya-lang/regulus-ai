"""Query classification and CFR reference parsing. No database."""

import pytest

from regulus.retrieval import QueryType, classify, parse_cfr_reference
from regulus.retrieval.query import looks_like_identifier, parse_docket


@pytest.mark.parametrize(
    "text,title,part,section,para",
    [
        ("21 CFR 820.10", "21", "820", "820.10", ""),
        ("What does 21 CFR 820.10 say?", "21", "820", "820.10", ""),
        ("Explain 21 CFR 820.30(b)(1)", "21", "820", "820.30", "(b)(1)"),
        ("21 C.F.R. § 211.132", "21", "211", "211.132", ""),
        ("21 CFR §820.10 (b) (1)", "21", "820", "820.10", "(b)(1)"),
        ("21 CFR Part 820", "21", "820", None, ""),
        ("21 cfr part 11", "21", "11", None, ""),
        ("§ 801.109(a)(1)(i)", "21", "801", "801.109", "(a)(1)(i)"),
        ("§§ 314.50", "21", "314", "314.50", ""),
        ("section 50.25 elements of informed consent", "21", "50", "50.25", ""),
        ("see part 820 for details", "21", "820", None, ""),
        ("CFR 1.1121", "21", "1", "1.1121", ""),
        ("42 CFR 493.1", "42", "493", "493.1", ""),
    ],
)
def test_parse_cfr_reference(text, title, part, section, para):
    ref = parse_cfr_reference(text)
    assert ref is not None, text
    assert (ref.title, ref.part, ref.section, ref.paragraph_path) == (title, part, section, para)


@pytest.mark.parametrize("text", ["", "   ", "What are the design control requirements?", "21 CFR", "CFR", "part 0820", "in 2024 the rule changed", "the dose is 2.5 mg", "version 3.1"])
def test_no_reference(text):
    assert parse_cfr_reference(text) is None


def test_bare_section_number_is_a_reference():
    # Stage 1: bare references are recognised ("Compare 820.10 with 820.20"). Before Stage 1
    # this text was asserted to parse as nothing; a bare dotted number is now a reference
    # unless a measurement, version, currency or clause cue sits next to it.
    ref = parse_cfr_reference("820.10 alone is ambiguous")
    assert ref is not None and ref.section == "820.10" and ref.paragraph_path == ""


def test_reference_levels_and_labels():
    assert parse_cfr_reference("21 CFR part 820").level == "part"
    assert parse_cfr_reference("21 CFR part 820").label == "21 CFR part 820"
    sec = parse_cfr_reference("21 CFR 820.10")
    assert sec.level == "section" and sec.label == "21 CFR 820.10"
    par = parse_cfr_reference("21 CFR 820.10(b)(1)")
    assert par.level == "paragraph" and par.label == "21 CFR 820.10(b)(1)"


def test_classify_exact_cfr():
    c = classify("21 CFR 820.30")
    assert c.query_type is QueryType.EXACT_CFR
    assert c.cfr.section == "820.30"


def test_classify_paragraph():
    c = classify("Explain 21 CFR 820.10(b)(1)")
    assert c.query_type is QueryType.EXACT_CFR and c.cfr.paragraph_path == "(b)(1)"


def test_classify_general():
    c = classify("What are the design control requirements?")
    assert c.query_type is QueryType.GENERAL_REGULATORY_SEARCH and c.cfr is None and c.docket is None


def test_classify_guidance_keyword_and_docket():
    assert classify("process validation guidance").query_type is QueryType.GUIDANCE_SEARCH
    c = classify("summarise fda-2016-d-2565")
    assert c.query_type is QueryType.GUIDANCE_SEARCH and c.docket == "FDA-2016-D-2565"


def test_classify_docket_with_cfr_reference_is_exact_cfr_and_keeps_docket():
    c = classify("21 CFR 820.10 and FDA-2021-D-1158")
    assert c.query_type is QueryType.EXACT_CFR and c.docket == "FDA-2021-D-1158"


@pytest.mark.parametrize("text", ["", "   ", None])
def test_classify_empty(text):
    assert classify(text).query_type is QueryType.EMPTY


@pytest.mark.parametrize("text", ["21 CFR", "CFR 820", "21 CFR 820.", "section 820", "21 CFR abc.10"])
def test_malformed_identifiers_do_not_classify_as_exact_section(text):
    c = classify(text)
    assert c.query_type is not QueryType.EXACT_CFR or c.cfr.section is None


def test_parse_docket_and_identifier_heuristic():
    assert parse_docket("no docket here") is None
    assert parse_docket("Docket FDA-2003-D-0143 applies") == "FDA-2003-D-0143"
    assert looks_like_identifier("820.3")
    assert looks_like_identifier("labeling 801.109")
    assert not looks_like_identifier("design controls")
