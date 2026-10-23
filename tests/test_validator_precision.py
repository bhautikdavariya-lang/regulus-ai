"""Validator precision fixes A1-A4 (23 Oct 2026, regulus.rag.validator_switches): each is off unless switched on, and
each releases only the false finding it targets. No database, no model."""
from types import SimpleNamespace

from regulus.rag import validator_switches
from regulus.rag.claim_validation import absence_supported, scoped_absence
from regulus.rag.generation import PackagedSource
from regulus.rag.validation import (ValidationProblem, ValidationReport, _figures, _strip_supplied_citations,
                                    excise_unsupported_sentences, repoint_named_citations)


def _src(index, section, paragraph, text, tier="exact"):
    return PackagedSource(index=index, tier=tier, requirement_ids=("r1",), protected=True, corpus="ecfr",
                          citation=f"21 CFR {section}{paragraph}", heading=None, url=None, text=text, truncated=False,
                          evidence_id=f"e{index}", key=f"k{index}",
                          citation_fields={"title": "21", "section": section, "paragraph": paragraph})


def _report(*problems):
    return ValidationReport(status="unsupported", problems=tuple(problems), addressed=(), unaddressed=(), cited=(),
                            invalid_citations=(), truncated=False, finished=True, generated_tokens=None,
                            max_new_tokens=None, answer_class="answer")


def _unsupported(sentence):
    return ValidationProblem("unsupported_claim", "error", "only 10% of its content words appear in any supplied source",
                             sentence=sentence)


# ------------------------------------------------------------ switches


def test_every_fix_is_off_by_default():
    assert validator_switches.VALIDATOR_PRECISION == frozenset() or \
        "REGULUS_VALIDATOR_PRECISION" in __import__("os").environ


# ------------------------------------------------------------ A1 citations are not figures


def test_a1_a_supplied_citation_is_not_a_figure_but_an_invented_one_still_is():
    supplied = "shall conform to the requirements of § 74.705 (a)(1) and (b) of this chapter; FD&C Act § 605(e)"
    assert _figures("conform to §74.705(a)(1) and (b) [1].") == {"74"}                  # the old false figure
    assert _figures(_strip_supplied_citations("conform to §74.705(a)(1) and (b) [1].", supplied)) == set()
    assert _figures(_strip_supplied_citations("conform to § 74.799(a) [1].", supplied)) == {"74"}
    assert _figures(_strip_supplied_citations("keep records 6 years under § 605(e) [2]", supplied)) == set()


def test_a1_never_touches_amounts():
    assert _figures(_strip_supplied_citations("the fee is $75 per petition", "§ 70.19 fees")) == {"75"}
    assert _figures(_strip_supplied_citations("not more than 0.6 percent", "not more than 0.5 percent")) == set()


# ------------------------------------------------------------ A2 scoped absence statements

GMP_USE = ("(c) Uses and restrictions. Disodium EDTA-copper may be safely used in amounts consistent with good "
           "manufacturing practices in the coloring of shampoos which are cosmetics.")
SPEC = "Free copper, not more than 100 parts per million. Lead (as Pb), not more than 20 parts per million."


def test_a2_scoped_absence_is_recognized_and_unscoped_denial_is_not():
    assert scoped_absence("These provisions set no limit on the amount of guanine that may be used.")
    assert scoped_absence("21 CFR 73.2120 does not specify any maximum concentration.")
    assert scoped_absence("No specific amount limit is stated in 21 CFR 82.1330.")
    assert not scoped_absence("There is no limit on how much guanine you can use.")
    assert not scoped_absence("FDA does not regulate this product.")


def test_a2_checks_the_kind_of_limit_against_the_uses_text():
    s = "These provisions impose no specific limits on the amount of disodium EDTA-copper that can be added."
    assert absence_supported(s, [SPEC, GMP_USE])                       # purity limits are not use amounts
    assert not absence_supported(s, [SPEC, "(c) It may be used in an amount not to exceed 0.5 percent by weight."])
    assert not absence_supported(s, ["(c) It may be safely used subject to the restrictions in paragraph (b)."])
    assert not absence_supported(s, [SPEC])                             # no uses text: nothing to verify against
    assert not absence_supported("These provisions say nothing more.", [GMP_USE])   # no kind of limit named


# ------------------------------------------------------------ A3 excision of unsupported filler

DRAFT = ("Disodium EDTA-copper may be used to tint shampoos, but it is not permitted in body washes [1]. "
         "The use in shampoos is limited to amounts consistent with good manufacturing practice [1]. "
         "The labeling must conform to the requirements of section 70.25 [2]. "
         "The use in body washes is not addressed in any provision, so it is not permitted under current regulations.")
QUESTION = "Can we use disodium EDTA-copper to tint a body wash and a shampoo?"


def test_a3_drops_an_uncited_unsupported_sentence_whose_point_is_already_made():
    filler = "The use in body washes is not addressed in any provision, so it is not permitted under current regulations."
    out = excise_unsupported_sentences(DRAFT, _report(_unsupported(filler)), QUESTION)
    assert out is not None and filler not in out[0] and out[1] == 1
    assert out[0].startswith("Disodium EDTA-copper may be used to tint shampoos")


def test_a3_never_drops_the_verdict_sentence_or_a_cited_claim():
    first = "Disodium EDTA-copper may be used to tint shampoos, but it is not permitted in body washes [1]."
    assert excise_unsupported_sentences(DRAFT, _report(_unsupported(first)), QUESTION) is None
    cited = "The labeling must conform to the requirements of section 70.25 [2]."
    assert excise_unsupported_sentences(DRAFT, _report(_unsupported(cited)), QUESTION) is None


def test_a3_keeps_the_only_sentence_that_answers_part_of_the_question():
    draft = ("Records must be kept for two years after creation [1]. They must be available to FDA for inspection [1]. "
             "No provision requires holding lots in quarantine until verified.")
    q = "What records must we keep, and must we hold lots in quarantine until verification?"
    only = "No provision requires holding lots in quarantine until verified."
    assert excise_unsupported_sentences(draft, _report(_unsupported(only)), q) is None


def test_a3_leaves_a_draft_whose_unsupported_sentences_are_its_answer():
    draft = ("21 CFR 700.27 governs prohibited cattle materials in cosmetics [1]. "
             "None of these provisions address contamination by rodent droppings. "
             "The recycled resin is not governed by any requirement in this section. "
             "Rodent droppings may still raise concerns.")
    probs = [_unsupported(s) for s in ("None of these provisions address contamination by rodent droppings.",
                                       "The recycled resin is not governed by any requirement in this section.",
                                       "Rodent droppings may still raise concerns.")]
    assert excise_unsupported_sentences(draft, _report(*probs), "Which provisions cover rodent droppings and resin?") is None


def test_a3_needs_every_error_to_be_excisable():
    filler = "The use in body washes is not addressed in any provision, so it is not permitted under current regulations."
    fig = ValidationProblem("unsupported_figure", "error", "figure(s) not found in any supplied source: 74")
    assert excise_unsupported_sentences(DRAFT, _report(_unsupported(filler), fig), QUESTION) is None


# ------------------------------------------------------------ A4 citation numbers re-pointed to the named provision


def test_a4_repoints_a_marker_to_the_one_source_that_is_the_named_provision():
    pkg = SimpleNamespace(sources=(
        _src(1, "71.30", "(a)", "(a) Objections and hearings relating to color additive regulations shall be governed by parts 10 and 12."),
        _src(2, "71.30", "(b)", "(b) The fees specified in § 70.19 of this chapter shall be applicable.")))
    text = "21 CFR 71.30(b) requires that the fees specified in §70.19 be applicable when filing an objection to a color additive regulation [1]."
    out, n = repoint_named_citations(text, pkg)
    assert n == 1 and out.endswith("regulation [2].")


def test_a4_leaves_a_correct_or_uncertain_citation_alone():
    pkg = SimpleNamespace(sources=(
        _src(1, "71.30", "(a)", "(a) Objections and hearings relating to color additive regulations shall be governed by parts 10 and 12."),
        _src(2, "71.30", "(b)", "(b) The fees specified in § 70.19 of this chapter shall be applicable.")))
    right = "21 CFR 71.30(b) makes the fees in §70.19 applicable [2]."
    assert repoint_named_citations(right, pkg) == (right, 0)
    unrelated = "21 CFR 71.30(b) says that cosmetics must carry a warning statement about aerosols and flammability [1]."
    assert repoint_named_citations(unrelated, pkg) == (unrelated, 0)      # the words are not the named provision's


def test_a2_does_not_vouch_for_a_missing_deadline():
    # a deadline usually lives in another section than the one cited (P-010: 812.40 cited, 812.46 sets the timeframe)
    s = "These provisions set no specific timeframes for monitoring the investigation."
    assert scoped_absence(s) and not absence_supported(s, ["(a) Sponsors shall select qualified investigators."])


def test_a3_never_trims_a_cut_off_draft():
    filler = "The use in body washes is not addressed in any provision, so it is not permitted under current regulations."
    rep = _report(_unsupported(filler))
    cut = ValidationReport(**{**rep.__dict__, "truncated": True})
    unfinished = ValidationReport(**{**rep.__dict__, "finished": False})
    assert excise_unsupported_sentences(DRAFT, cut, QUESTION) is None
    assert excise_unsupported_sentences(DRAFT, unfinished, QUESTION) is None


def test_a3_leaves_a_draft_whose_verdict_says_the_evidence_does_not_govern():
    draft = ("A retailer cannot establish compliance under 21 CFR 700.27 because this regulation does not govern talc "
             "storage [1]. Records must be retained for 2 years [2]. Storage rules are not part of these records.")
    only = "Storage rules are not part of these records."
    assert excise_unsupported_sentences(draft, _report(_unsupported(only)), "What storage records prove our talc compliance?") is None
