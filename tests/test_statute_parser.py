"""U.S. Code section parser (regulus.ingestion.statute): designator paths, captions, notes dropped."""
import pytest

from regulus.ingestion.statute import parse_section

HEADER = """SOURCE: https://www.govinfo.gov/content/pkg/USCODE-2024-title21/html/x.htm
LABEL: FDCA 605 = 21 U.S.C. 364a

U.S.C. Title 21 - FOOD AND DRUGS
SUBCHAPTER VI - COSMETICS
§364a. Adverse events
"""


def paths(text):
    return [(r.paragraph_path, r.paragraph_heading, r.body_text[:12]) for r in parse_section(HEADER + text)]


def test_captions_attach_to_the_following_text_and_notes_are_dropped():
    rows = parse_section(HEADER + """(a) Serious adverse event reporting requirements
The responsible person shall submit any report.
(b) Submission of reports
(1) Serious adverse event report
The responsible person shall submit a report no later than 15 business days after it is received.
(June 25, 1938, ch. 675, §605, as added Pub. L. 117-328.)
Editorial Notes
(a) Not law.
""")
    assert [(r.paragraph_path, r.paragraph_heading) for r in rows] == [
        ("(a)", "Serious adverse event reporting requirements"), ("(b)(1)", "Serious adverse event report")]
    assert rows[1].label == "FD&C Act § 605(b)(1) [21 U.S.C. 364a(b)(1)]"
    assert rows[0].source_url.endswith("x.htm")


def test_chained_designators_and_subsection_i_after_h():
    got = paths("""(h)(1) The term "device" means an instrument which is—
(A) recognized in the official National Formulary;
(B) intended for use in diagnosis;
(i) The term "cosmetic" means articles intended to be applied to the human body.
(j) The term "official compendium" means the official United States Pharmacopoeia.
""")
    assert [p for p, _, _ in got] == ["(h)(1)", "(h)(1)(A)", "(h)(1)(B)", "(i)", "(j)"]


def test_roman_clauses_under_a_subparagraph():
    got = paths("""(3) Facility
(B) Such term does not include any of the following:
(i) Beauty shops and salons.
(ii) Cosmetic product retailers.
(viii) An establishment that solely performs one or more of the following:
(I) Labeling.
(II) Relabeling.
""")
    assert [p for p, _, _ in got] == ["(3)(B)", "(3)(B)(i)", "(3)(B)(ii)", "(3)(B)(viii)", "(3)(B)(viii)(I)",
                                      "(3)(B)(viii)(II)"]


def test_refuses_text_that_is_not_a_fetched_section():
    with pytest.raises(ValueError):
        parse_section("(a) Something.\n")
