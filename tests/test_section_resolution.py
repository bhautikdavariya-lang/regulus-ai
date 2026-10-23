"""Section resolution (23 Oct 2026): the benchmark's key parser, color-additive names, entity constraints, the FD&C Act
ordering, the rerank veto and question intents. No database and no model: fake indexes and stubbed scores."""
from dataclasses import dataclass

import numpy as np
import pytest

from regulus.evaluation.section_resolution import Resolved, parse_key, score_row, section_of
from regulus.rag import section_promotion as SP
from regulus.rag.section_promotion import SectionPromoter, rerank_label
from regulus.retrieval.entities import EntityIndex, normalize_heading
from regulus.retrieval.intent import intent_match, question_intents

USC = {"364a": "605", "364b": "606", "364e": "609", "364h": "612", "362": "602", "361": "601"}


# ------------------------------------------------------------ benchmark key parser


@pytest.mark.parametrize("key, want", [
    ("21 CFR 74.2101(c)(1), (c)(2), (e)", ["74.2101"]),
    ("21 CFR 82.706; 21 CFR 82.50", ["82.706", "82.50"]),
    ("FD&C Act 612(a) [21 U.S.C. 364h(a)]", ["612"]),
    ("FD&C Act 602(b) [21 U.S.C. 362(b)]", ["602"]),          # 362 is a U.S.C. number, never Act section 362
    ("FD&C Act 605(e)(1)–(2) (21 U.S.C. 364a); 612 (21 U.S.C. 364h); 609(a) (21 U.S.C. 364e)", ["605", "612", "609"]),
    ("21 CFR Parts 700–740 (no sanitation record provision); FD&C Act 601(c); 606", ["601", "606"]),
    ("21 CFR 700.23; 21 CFR 2.125(b), (c), (e)", ["700.23", "2.125"]),
])
def test_key_parser_reads_cfr_and_act_sections(key, want):
    assert parse_key(key, USC) == want


def test_section_of_and_score_row_count_acceptable_sections():
    assert section_of("70.3(v)") == "70.3" and section_of("21 CFR 74.2101") == "74.2101" and section_of("605(e)") == "605"
    row = {"id": "x", "source": "synthetic", "split": "synthetic", "primary": "80.37", "gold": ["80.37"],
           "acceptable": ["80.22"], "needs": ["80.37"]}
    s = score_row(row, Resolved("picker", ["80.21", "80.22", "80.37"], ["80.22"], []))
    assert s["hit"] and not s["primary"] and not s["cover"] and s["cand_rank"] == 3 and s["best_cand_rank"] == 2


# ------------------------------------------------------------ color additive names


SECTIONS = ["74.101", "74.1101", "74.2101", "82.101", "74.2340", "74.1340", "82.50", "82.51", "73.2087", "73.100",
            "73.1030", "73.30", "73.2030", "74.1602", "74.2602", "74.2602a", "70.3"]
PARTS = [s.split(".")[0] for s in SECTIONS]
HEADINGS = ["FD&C Blue No. 1.", "FD&C Blue No. 1", "FD&C Blue No. 1.", "FD&C Blue No. 1.", "FD&C Red No. 40.",
            "FD&C Red No. 40.", "General.", "Lakes (FD&C).", "Carmine.", "Cochineal extract; carmine.", "Annatto extract.",
            "Annatto extract.", "Annatto.", "D&C Violet No. 2.", "D&C Violet No. 2.", "Ext. D&C Violet No. 2.", "Definitions."]
SUBPARTS = ["Subpart A - Foods", "Subpart B - Drugs", "Subpart C - Cosmetics", "", "Subpart C - Cosmetics", "Subpart B - Drugs",
            "Subpart B - Certified provisionally listed colors", "", "Subpart C - Cosmetics", "Subpart A - Foods",
            "Subpart B - Drugs", "Subpart A - Foods", "Subpart C - Cosmetics", "Subpart B - Drugs", "Subpart C - Cosmetics",
            "Subpart C - Cosmetics", ""]


def entity_ix():
    return EntityIndex.from_sections(SECTIONS, PARTS, HEADINGS)


def test_headings_without_a_period_are_the_same_color():
    assert normalize_heading("FD&C Blue No. 1") == normalize_heading("FD&C Blue No. 1.") == "fd&c blue no. 1"


def test_listing_headings_become_color_keys_and_general_headings_do_not():
    E = entity_ix()
    assert set(E.cert[("fdc", "blue", "1")]) == {"74.101", "74.1101", "74.2101", "82.101"}
    assert not E.is_color_listing("82.50") and not E.is_color_listing("82.51") and not E.is_color_listing("70.3")
    assert E.is_color_listing("73.2087") and E.is_color_listing("73.100")


@pytest.mark.parametrize("question, sections", [
    ("Can we use Blue 1 in a mouthwash?", {"74.101", "74.1101", "74.2101", "82.101"}),
    ("Is FD&C Blue #1 Aluminum Lake allowed in eye shadow?", {"74.101", "74.1101", "74.2101", "82.101"}),
    ("Is Red No.40 OK in lipstick?", {"74.2340", "74.1340"}),
    ("Our blush uses carmine.", {"73.2087", "73.100"}),
    ("D&C Violet 2 in a contact lens?", {"74.1602", "74.2602"}),        # the family named: Ext. D&C is another color
])
def test_question_names_match_their_listings(question, sections):
    ms = entity_ix().match(question)
    assert len(ms) == 1 and set(ms[0].sections) == sections


def test_a_name_inside_a_longer_name_is_one_mention_and_lake_is_noticed():
    E = entity_ix()
    ms = E.match("Is annatto extract allowed in a lip balm?")
    assert len(ms) == 1 and set(ms[0].sections) == {"73.1030", "73.30", "73.2030"}
    ms = E.match("FD&C Blue No. 1 and a second shade with FD&C Blue No. 1 Aluminum Lake")
    assert len(ms) == 1 and ms[0].lake


def test_no_color_named_no_match_and_amounts_are_not_colors():
    E = entity_ix()
    assert E.match("Our pigment supplier sells a 'D&C Red lake blend' in a castor-oil carrier.") == []
    assert E.match("Must we keep records for 3 years?") == []
    assert E.match("Is a blue 1 percent tint too much?") == []


# ------------------------------------------------------------ entity constraints in the promoter


@dataclass
class _Ranked:
    section: str
    part: str
    heading: str
    subpart: str
    score: float = 0.0
    best_ordinal: int = 0


class _FakeIndex:
    def __init__(self):
        self.sections, self.parts, self.headings, self.subparts = SECTIONS, PARTS, HEADINGS, SUBPARTS
        self.row_section = np.arange(len(SECTIONS), dtype=np.int32)
        self.row_ordinal = np.ones(len(SECTIONS), dtype=np.int32)


def promoter():
    from regulus.retrieval import entities

    entities._CACHE.clear()
    return SectionPromoter(db=None, mode="picker", index=_FakeIndex())


def _r(s):
    i = SECTIONS.index(s)
    return _Ranked(s, PARTS[i], HEADINGS[i], SUBPARTS[i])


def test_other_colors_are_vetoed_and_the_named_listing_is_offered():
    pr = promoter()
    q = "We're formulating an eye shadow with FD&C Blue No. 1. Is it permitted?"
    ranked = [_r("74.2340"), _r("74.1340"), _r("82.51"), _r("70.3")]
    out = [r.section for r in pr._entity_constrained(q, ["eye", "shadow", "blue"], ranked, None)]
    assert "74.2340" not in out and "74.1340" not in out      # Red No. 40: not named
    assert "82.51" in out and "70.3" in out                   # no color listings: kept
    assert out[min(2, len(out) - 1)] == "74.2101"            # the cosmetics listing of the named color, offered third


def test_entity_pick_promotes_the_named_color_for_the_product_kind():
    pr = promoter()
    q = "We're formulating an eye shadow with FD&C Blue No. 1. Is it permitted?"
    cands = [{"section": "74.1101", "part": "74"}, {"section": "74.2101", "part": "74"}, {"section": "82.101", "part": "82"},
             {"section": "605", "statute": True}]
    # the cosmetics listing (the question names a cosmetic), with the Part 82 certification listing the ranking offered
    assert pr.entity_pick(q, ["eye", "shadow", "blue"], cands, None) == ["74.2101", "82.101"]
    # the Part 82 listing is a companion only when offered; it never replaces the listing that says where it may be used
    assert pr.entity_pick(q, ["eye", "shadow", "blue"], [c for c in cands if c["section"] != "82.101"], None) == ["74.2101"]
    # a part-only question ("Under Part 82") gets that part's listing
    assert pr.entity_pick(q, ["eye", "shadow", "blue"], cands, ("82",)) == ["82.101"]


def test_a_food_question_gets_the_food_listing_and_an_exact_name_beats_a_shorter_one():
    pr = promoter()
    cands = [{"section": "73.2030", "part": "73"}, {"section": "73.30", "part": "73"}]
    # "annatto extract" in a food product: the Foods listing, not the cosmetics "Annatto." listing
    q = "Is annatto extract allowed to color a cheese sauce?"
    assert pr.entity_pick(q, ["annatto", "extract", "color", "chees", "sauc"], cands, None) == ["73.30"]
    # the same name in a cosmetic: the cosmetics listing
    q = "Can annatto extract color our lip balm?"
    assert pr.entity_pick(q, ["annatto", "extract", "color", "lip", "balm"], cands, None) == ["73.2030"]


def test_entity_pick_leaves_the_picker_to_decide_when_a_rule_ranks_first():
    pr = promoter()
    q = "How do we request certification of a batch of FD&C Blue No. 1?"
    cands = [{"section": "82.50", "part": "82"}, {"section": "74.2101", "part": "74"}]
    assert pr.entity_pick(q, ["certif", "batch", "blue"], cands, None) is None


# ------------------------------------------------------------ rerank veto and the FD&C Act order


def test_rerank_veto_replaces_only_a_low_scored_pick_with_a_clearly_better_one(monkeypatch):
    pr = promoter()
    cands = [{"section": "720.9"}, {"section": "720.2"}, {"section": "720.4"}]
    monkeypatch.setattr(SP, "RERANK_VETO_BELOW", 0.3)
    monkeypatch.setattr(SP, "RERANK_VETO_MARGIN", 0.15)
    monkeypatch.setattr(pr, "rerank_scores", lambda q, c: {"720.9": (0.05, ""), "720.2": (0.81, "(a)"), "720.4": (0.10, "")})
    assert pr.rerank_veto("by when should it be filed?", cands, cands[0])["section"] == "720.2"
    # a pick the reranker does not rate low is kept, even when another scores higher (subpart near-ties)
    monkeypatch.setattr(pr, "rerank_scores", lambda q, c: {"720.9": (0.85, ""), "720.2": (0.90, ""), "720.4": (0.1, "")})
    assert pr.rerank_veto("q", cands, cands[0]) is None
    # without the reranker nothing changes
    monkeypatch.setattr(pr, "rerank_scores", lambda q, c: {})
    assert pr.rerank_veto("q", cands, cands[0]) is None


def test_statute_order_is_the_lexical_ranking_without_the_embedding_index(monkeypatch):
    import regulus.retrieval.paragraph_dense as PD

    pr = promoter()
    monkeypatch.setattr(PD, "paragraph_dense", lambda db: None)

    @dataclass
    class _S:
        score: float

    order = pr.statute_order("How long must adverse event records be kept?", {"605": _S(2.0), "610": _S(1.0)})
    assert order[:2] == ["605", "610"] and sorted(order) == sorted(SP.STATUTE_OFFERED)


def test_rerank_label_says_where_a_listing_sits():
    assert rerank_label({"section": "73.2085", "part": "73", "part_title": "Listing of Color Additives Exempt From Certification",
                         "subpart": "Subpart C - Cosmetics"}) == \
        "21 CFR 73.2085 (Listing of Color Additives Exempt From Certification; Subpart C - Cosmetics)"
    assert rerank_label({"section": "605", "statute": True}).startswith("FD&C Act § 605")


def test_picker_reply_cap_stays_16_unless_configured():
    assert SP.PICKER_MAX_TOKENS == 16 or "REGULUS_PICKER_MAX_TOKENS" in __import__("os").environ


# ------------------------------------------------------------ intents


def test_question_intent_cues():
    assert question_intents("If we choose to file a statement, by when should it be filed?")[0] == "deadline_timing"
    assert "claim_misbranding" in question_intents("Can we say 'FDA Registered' on the carton?")
    assert "status_effective" in question_intents("Is FD&C Red No. 4 still usable?")
    assert question_intents("") == []


def test_intent_match_uses_the_section_functions_file():
    assert intent_match(["deadline_timing"], "720.2") == 1.0
    assert intent_match([], "720.2") == 0.0 and intent_match(["deadline_timing"], "no-such-section") == 0.0
