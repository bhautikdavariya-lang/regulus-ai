"""SP1 (27 Oct 2026): spelling correction against the regulations' vocabulary (regulus.retrieval.spelling)."""
from collections import Counter

from regulus.retrieval.spelling import Vocabulary, distance

V = Vocabulary(Counter({"carmine": 40, "annatto": 12, "dihydroxyacetone": 9, "certification": 300, "deposit": 30,
                        "india": 5, "refill": 3, "withdraw": 8, "substrate": 6, "eyeshadows": 2}),
               english={"launch", "does", "the", "we", "use", "blush", "colored", "with", "may", "it"})


def test_typos_of_regulation_words_are_corrected():
    text, fixes = V.correct("We're launching a blush colored with carmin. May we use it?")
    assert fixes == [("carmin", "carmine")] and "carmine" in text and "launching" in text
    assert V.correct("Can we use anatto?")[1] == [("anatto", "annatto")]
    assert V.correct("dihydroxyacetne in lotion")[1] == [("dihydroxyacetne", "dihydroxyacetone")]


def test_words_forms_and_quotes_are_left_alone():
    for q in ("Our indie brand", "Can we refile it?", "We withdrew it", "The substrata used", "Our eyeshadow line",
              "Doesn't it apply?", "Is 'carmin' the label name?"):
        assert V.correct(q)[1] == [], q


def test_distance_counts_a_transposition_once():
    assert distance("carmien", "carmine") == 1 and distance("carmin", "carmine") == 1
