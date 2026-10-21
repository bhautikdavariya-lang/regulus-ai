"""A general question that asks how the regulations DEFINE the things it names gets the CFR paragraphs that
define them (lexical step 5c, query.definitional_terms / defined_term_pattern / choose_defining_section).

Client question, 2026-10-19: "...mica coated with iron oxides ... cocoa powder that tints it brown. Are these
'color additives' in FDA's sense?" Keyword search returned orthopedic-coating guidance and colour LISTINGS,
never 21 CFR 70.3 (Definitions). 70.3(f) opens "A color additive is ...", which the "<term> means" lookup
cannot see. The step only adds evidence; with it off, or for any other question, retrieval is unchanged.

Paragraph openings below are the snapshot's own wording of 21 CFR 70.3 (first sentence only); 880.6310 and
73.9999 are written for the test.
"""
from __future__ import annotations

import re

import pytest

from regulus.planning import plan_query
from regulus.retrieval import LexicalRetriever
from regulus.retrieval import sql as sql_module
from regulus.retrieval.models import METHOD_DEFINITION
from regulus.retrieval.query import (choose_defining_section, defined_term_pattern, definitional_terms,
                                     question_words)
from tests.test_retrieval_plan import TableDatabase, guidance_row, row

P70_F = row("70.3", "(f)", 6, text="(f) A color additive is any material, not exempted under section 201(t) of the act, "
                                   "that is a dye, pigment, or other substance made by a process of synthesis.",
            section_heading="Definitions.")
P70_L = row("70.3", "(l)", 12, text="(l) The term lake means a straight color extended on a substratum by adsorption, "
                                    "coprecipitation, or chemical combination.", section_heading="Definitions.")
P70_S = row("70.3", "(s)", 19, text="(s) The term area of the eye means the area enclosed with in the circumference of "
                                    "the supra-orbital ridge and the infra-orbital ridge.", section_heading="Definitions.")
P70_U = row("70.3", "(u)", 21, text="(u) The hair dye exemption in section 601(a) of the act applies to coal tar hair "
                                    "dyes intended for use in altering the color of the hair.", section_heading="Definitions.")
P70_V = row("70.3", "(v)", 22, text="(v) The terms externally applied drugs and externally applied cosmetics mean drugs "
                                    "or cosmetics applied only to external parts of the body.", section_heading="Definitions.")
LISTING = row("73.9999", "(a)(1)", 1, text="(a)(1) The color additive mica-based pearlescent pigment is a lustrous pigment "
                                           "of mica coated with iron oxides.", section_heading="Mica-based pearlescent pigments.")
MDDS = row("880.6310", "(a)(1)", 1, text="(a)(1) A medical device data system (MDDS) is a device that transfers data.",
           section_heading="Medical device data system.")
CLIENT_1 = ("Our shimmer body lotion uses mica coated with iron oxides, and our lip scrub has cocoa powder that tints it "
            "brown. Are these 'color additives' in FDA's sense?")
CLIENT_3 = ("We make a brow tint, a lip gloss and a coal-tar-based permanent hair dye. How do FDA's color additive "
            "definitions treat 'area of the eye', 'externally applied' and the hair dye exemption?")


def pg(pattern: str):
    """The PostgreSQL pattern in Python's dialect (\\M = end of word)."""
    return re.compile(pattern.replace(r"\M", r"\b"), re.IGNORECASE)


class DefinedTermsDatabase(TableDatabase):
    """TableDatabase that also answers the two defined-term statements from the table, with the statements'
    own phrase prefilter (every word of the term) and regular expression."""

    def query(self, statement, params=None):
        if statement == sql_module.ECFR_DEFINED_TERM:
            self.calls.append(("ECFR_DEFINED_TERM", dict(params)))
            words, pattern = params["query"].lower().split(), pg(params["pattern"])
            hits = [dict(r) for r in self.table if all(w in r["body_text"].lower() for w in words)
                    and pattern.search(r["body_text"])]
            return sorted(hits, key=lambda r: (r["section_number"], r["ordinal"]))[: params["limit"]]
        if statement == sql_module.ECFR_SECTION_TEXT:
            self.calls.append(("ECFR_SECTION_TEXT", dict(params)))
            rows = sorted((r for r in self.table if r["section_number"] == params["section_number"]), key=lambda r: r["ordinal"])
            return [{"body_text": " ".join(r["body_text"] for r in rows) or None}]
        return super().query(statement, params)


TABLE = [P70_F, P70_L, P70_S, P70_U, P70_V, LISTING, MDDS]
NOISE = [guidance_row(0, title_text="Characterization of Metallic Coatings on Orthopedic Devices",
                      body_text="coated orthopedic implants with metallic coatings", rank=0.3)]


def run(question, *, defined_terms=True, table=TABLE, or_guidance=NOISE):
    db = DefinedTermsDatabase(table, or_guidance=or_guidance)
    out = LexicalRetriever(db, defined_terms=defined_terms).run_plan(plan_query(question), top_k=8)
    return out, db


def labels(out):
    return [r.citation.label for r in out.response.results]


# ---------------------------------------------------- which questions invoke definitions, and their terms

@pytest.mark.parametrize("question", [
    CLIENT_1, CLIENT_3,
    "Our pigment supplier sells us a 'D&C Red lake blend' in a castor-oil carrier. How do FDA's definitions classify "
    "the lake, the blend and the oil?",
    "How is a combination product defined?",
    "What counts as a medical food?",
])
def test_questions_that_ask_how_terms_are_defined_invoke_the_lookup(question):
    assert definitional_terms(question)


@pytest.mark.parametrize("question", [
    "What does 21 CFR 820.30 require?",
    "When must a device correction be reported to FDA?",
    "We want to use a certified FD&C red that's listed for cosmetics in our new eyeshadow. Can we use it?",
    "How are medical devices classified?",
])
def test_other_questions_do_not(question):
    assert definitional_terms(question) == {}


def test_terms_are_multi_word_n_grams_and_single_words_only_inside_quotes():
    terms = definitional_terms(CLIENT_1)
    assert terms["color additives"] == terms["color additive"] == 3      # quoted; plural tried singular
    assert terms["iron oxides"] == 2                                     # unquoted multi-word term
    assert terms["color"] == 1 and terms["additive"] == 1                # inside the quoted 'color additives'
    assert "mica" not in terms and "lotion" not in terms                 # unquoted single words never count
    assert not any(t.startswith(("are ", "the ")) or t.endswith((" in", " of")) for t in terms)


def test_generic_regulatory_words_may_be_part_of_a_term():
    assert definitional_terms("How is a combination product defined?")["combination product"] == 2


# ---------------------------------------------------- what counts as a defining paragraph

@pytest.mark.parametrize("term,text", [
    ("color additive", P70_F["body_text"]),
    ("lake", P70_L["body_text"]),
    ("area of the eye", P70_S["body_text"]),
    ("hair dye exemption", P70_U["body_text"]),
    ("externally applied", P70_V["body_text"]),
])
def test_a_paragraph_that_opens_by_defining_the_term_matches(term, text):
    assert pg(defined_term_pattern(term)).search(text)


@pytest.mark.parametrize("term,text", [
    ("medical device", MDDS["body_text"]),                                           # a longer term after "A"
    ("color additive", "(c) Each color additive shall be certified before use."),    # mentions, does not define
    ("lake", "(b) A lake of FD&C Red No. 40 may be used in drugs."),                 # "A lake of ..." is not "A lake is"
])
def test_a_paragraph_that_only_mentions_or_extends_the_term_does_not(term, text):
    assert not pg(defined_term_pattern(term)).search(text)


# ---------------------------------------------------- which section is chosen

def test_the_definitions_section_wins_over_a_listing_that_defines_the_same_term():
    hits = {"73.9999": {"color additive": LISTING}, "70.3": {"color additive": P70_F}}
    headings = {"73.9999": "Mica-based pearlescent pigments.", "70.3": "Definitions."}
    assert choose_defining_section(hits, {"color additive": 2}, headings, lambda s: 9 if s == "73.9999" else 0) \
        == ("70.3", ["color additive"])


def test_a_longer_defined_term_subsumes_the_words_inside_it_and_ties_go_to_the_better_overlap():
    hits = {"60.3": {"color additive": P70_F, "color": P70_F}, "70.3": {"color additive": P70_F}}
    headings = {"60.3": "Definitions.", "70.3": "Definitions."}
    chosen = choose_defining_section(hits, {"color additive": 2, "color": 1}, headings, {"60.3": 1, "70.3": 4}.get)
    assert chosen == ("70.3", ["color additive"])


def test_a_single_quoted_word_counts_only_in_a_definitions_section_with_question_context():
    weights = {"lake": 1}
    assert choose_defining_section({"70.3": {"lake": P70_L}}, weights, {"70.3": "Definitions."}, lambda s: 3) == ("70.3", ["lake"])
    # 'quantum wellness supplement': the word is defined somewhere, but nothing else of the question is there
    assert choose_defining_section({"70.3": {"lake": P70_L}}, weights, {"70.3": "Definitions."}, lambda s: 0) is None
    assert choose_defining_section({"184.9": {"lake": P70_L}}, weights, {"184.9": "Red lake pigment."}, lambda s: 3) is None
    assert choose_defining_section({}, weights, {}, lambda s: 0) is None


# ---------------------------------------------------- precision defects measured on 19 probe questions (2026-10-20)

def test_an_apostrophe_is_not_a_quote():
    terms = definitional_terms("How do FDA's definitions treat a 'medical food'?")
    assert "medical food" in terms and "definitions" not in terms and "treat" not in terms


def test_a_definition_from_another_domain_is_not_added():
    """'serious adverse event' for dietary supplements: only a medical-gas Definitions section defines the phrase;
    the question's own domain (dietary supplements) is part 111's. Nothing is better than the wrong domain."""
    q = "What counts as a 'serious adverse event' for dietary supplements in FDA's sense?"
    hits = {"230.3": {"serious adverse event": P70_F}, "111.113": {"dietary supplement": P70_F}}
    headings = {"230.3": "Definitions.", "111.113": "Quality control operations."}
    titles = {"230.3": "Certification and Postmarketing Reporting for Designated Medical Gases",
              "111.113": "Current Good Manufacturing Practice ... for Dietary Supplements"}
    assert choose_defining_section(hits, definitional_terms(q), headings, lambda s: 0, part_titles=titles,
                                   question_words=question_words(q)) is None


def test_the_quoted_term_outranks_an_unquoted_one_and_hyphens_and_plurals_match():
    q = "How does FDA define 'food contact surface' for human food facilities?"
    w = definitional_terms(q)
    assert w["food contact surface"] == w["food contact surfaces"] == 3 and w["human food"] == 2
    assert pg(defined_term_pattern("food contact surfaces")).search(
        "Food-contact surfaces are those surfaces that contact human food.")
    hits = {"117.3": {"food contact surfaces": P70_F}, "507.12": {"human food": P70_F}}
    titles = {"117.3": "Current Good Manufacturing Practice ... for Human Food", "507.12": "... for Food for Animals"}
    headings = {"117.3": "Definitions.", "507.12": "Applicability."}
    assert choose_defining_section(hits, w, headings, lambda s: 0, part_titles=titles,
                                   question_words=question_words(q))[0] == "117.3"


def test_the_part_title_picks_the_regulation_about_the_term():
    """'color additive' is defined both in 60.3 (Patent Term Restoration) and 70.3 (Color Additives)."""
    q = "Is a 'smart pill bottle' a 'color additive' in FDA's sense?"
    hits = {"60.3": {"color additive": P70_F}, "70.3": {"color additive": P70_F}}
    headings = {"60.3": "Definitions.", "70.3": "Definitions."}
    titles = {"60.3": "Patent Term Restoration", "70.3": "Color Additives"}
    assert choose_defining_section(hits, definitional_terms(q), headings, lambda s: 0, part_titles=titles,
                                   question_words=question_words(q)) == ("70.3", ["color additive"])


# ---------------------------------------------------- the retriever: it only adds

def test_the_client_question_gets_the_color_additive_definition():
    out, db = run(CLIENT_1)
    assert "21 CFR 70.3(f)" in labels(out)
    hit = next(r for r in out.response.results if r.citation.label == "21 CFR 70.3(f)")
    assert hit.retrieval_method == METHOD_DEFINITION and hit.metadata.get("leg") == "defined_terms"
    assert "21 CFR 73.9999(a)(1)" not in labels(out)          # the listing defines the term too, but is not chosen


def test_every_term_the_definitions_section_defines_is_kept_in_document_order():
    out, _ = run(CLIENT_3)
    got = [l for l in labels(out) if l.startswith("21 CFR 70.3")]
    assert sorted(got) == ["21 CFR 70.3(f)", "21 CFR 70.3(s)", "21 CFR 70.3(u)", "21 CFR 70.3(v)"]


def test_a_definition_that_is_a_list_lead_in_brings_its_sub_paragraphs():
    lead = row("3.2", "(e)", 5, text="(e) Combination product includes:", section_heading="Definitions.")
    kids = [row("3.2", f"(e)({i})", 5 + i, text=f"({i}) A product comprised of two or more regulated components, case {i}.",
                section_heading="Definitions.") for i in (1, 2, 3, 4)]
    other = row("3.2", "(f)", 10, text="(f) Drug constituent part means a drug ...", section_heading="Definitions.")
    out, _ = run("How is a combination product defined?", table=[lead, *kids, other])
    assert [l for l in labels(out) if l.startswith("21 CFR 3.2")] == \
        ["21 CFR 3.2(e)", "21 CFR 3.2(e)(1)", "21 CFR 3.2(e)(2)", "21 CFR 3.2(e)(3)", "21 CFR 3.2(e)(4)"]


def test_with_the_step_on_every_other_leg_runs_exactly_as_with_it_off():
    on, db_on = run(CLIENT_1)
    off, db_off = run(CLIENT_1, defined_terms=False)
    other = lambda db: [(n, p) for n, p in db.calls if n not in ("ECFR_DEFINED_TERM", "ECFR_SECTION_TEXT")]
    assert other(db_on) == other(db_off)                       # same statements, same parameters, same order
    assert set(labels(off)) <= set(labels(on))                 # it adds; nothing the other legs found is dropped here
    assert "ECFR_DEFINED_TERM" not in db_off.names()


def test_a_question_that_names_a_provision_never_runs_it():
    out, db = run("What does 21 CFR 70.3 say about how a color additive is defined?")
    assert "ECFR_DEFINED_TERM" not in db.names()


def test_a_general_question_that_does_not_ask_about_definitions_never_runs_it():
    out, db = run("Can a mica pigment coated with iron oxides be used in a body lotion?")
    assert "ECFR_DEFINED_TERM" not in db.names()


def test_when_no_section_qualifies_retrieval_is_unchanged():
    on, db = run("How is a shimmer lotion defined?")               # no table row defines any of its terms
    off, _ = run("How is a shimmer lotion defined?", defined_terms=False)
    assert "ECFR_DEFINED_TERM" in db.names() and labels(on) == labels(off)


def test_the_retriever_reports_the_setting():
    assert LexicalRetriever(DefinedTermsDatabase(TABLE)).describe()["defined_terms"] is True
    assert LexicalRetriever(DefinedTermsDatabase(TABLE), defined_terms=False).describe()["defined_terms"] is False


def test_the_new_statements_are_read_only_and_registered():
    for name in ("ECFR_DEFINED_TERM", "ECFR_SECTION_TEXT"):
        stmt = sql_module.ALL_STATEMENTS[name]
        assert stmt.lstrip().upper().startswith("SELECT")
    assert "%(pattern)s" in sql_module.ECFR_DEFINED_TERM and "phraseto_tsquery" in sql_module.ECFR_DEFINED_TERM
