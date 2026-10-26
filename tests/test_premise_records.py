"""FP1 (a confirmation question asserting a figure the provision does not state) and RS1 (a records question about a
section that requires none): the mechanical checks (26 Oct 2026). Both are default-off switches."""
from regulus.rag.premise_figures import PREMISE_SENTENCE_RE, absent_figures, claimed_figures, figures, puts_premise
from regulus.rag.records_silence import SILENCE_SENTENCE_RE, asks_records, silent


def test_figures_are_read_by_value_and_unit():
    got = {(f.value, f.unit) for f in figures("a deposit of $3,000.00, 180 days, a 24-month date, one year, 1/4 inch, 5%")}
    assert got >= {(3000.0, "money"), (180.0, "day"), (24.0, "month"), (1.0, "year"), (0.25, "inch"), (5.0, "percent")}


def test_only_a_figure_attributed_to_a_requirement_is_a_claim():
    assert [f.text for f in claimed_figures("Does 70.25(a)(4) require a 24-month expiry date?")] == ["24-month"]
    assert claimed_figures("Can we use D&C Yellow No. 8 at 2% in a body lotion?") == []        # the user's own fact
    assert claimed_figures("Our bar contains tribromsalan at 0.25%. Can we sell it?") == []


def test_a_figure_any_supplied_text_states_is_left_to_the_model():
    q = "Our consultant says committee members are paid $150 per member per day under 70.19. Correct?"
    assert [f.text for f in absent_figures(q, ["not to exceed $75.00 per member per day"])] == ["$150"]
    assert absent_figures("Is the deposit for a cosmetics-only petition $3,000?", ["a deposit of $3,000.00"]) == []
    assert absent_figures("FDA must act within thirty days, right?", ["within 30 days of receipt"]) == []


def test_a_confirmation_question_is_recognised():
    assert puts_premise("The identity statement must be at least 1/4 inch tall, correct?")
    assert puts_premise("Does 70.42(b) require a 2-year clinical trial?")
    assert not puts_premise("What fee applies to a petition?")


def test_the_premise_sentence_is_the_pipelines_own():
    s = ('No. The figure "$150" does not appear in the text of 21 CFR 70.19 supplied for this answer. What it says on '
         'this point, verbatim:')
    assert PREMISE_SENTENCE_RE.search(s)


def test_records_silence_needs_a_records_question_and_silent_text():
    assert asks_records("What records does § 701.11 require?") and asks_records("What should our receiving file show?")
    assert not asks_records("Can we use it in an eye shadow?")
    assert silent({"21 CFR 701.11": "The principal display panel shall bear a statement of identity in bold type."})
    assert not silent({"21 CFR 710.2": "Registration forms shall be filed ..."})
    assert not silent({"21 CFR 700.27": "Manufacturers ... shall maintain records ..."})
    assert not silent({})
    s = ("21 CFR 701.11 sets no recordkeeping requirement: no paragraph of its text in this system requires a record to "
         "be made or kept. What it requires, verbatim:")
    assert SILENCE_SENTENCE_RE.search(s)


def test_only_a_question_about_records_is_a_records_question():
    yes = ["What records does § 701.11 require?", "What should we keep as evidence of our official filing date?",
           "What should our receiving file show?", "What evidence shows compliance with § 700.35?",
           "What does this section require us to document for a batch of D&C Red No. 22?",
           "Do we need to keep copies of the certificate?"]
    no = ["Our vaginal product is kept behind the pharmacy counter, not on open shelves. Does (b) apply?",
          "What must the package itself show as evidence of the feature?", "Can we store it in a warehouse?",
          "Which document must accompany the petition?"]
    assert all(asks_records(q) for q in yes) and not any(asks_records(q) for q in no)


def test_a_premise_answer_prefers_figures_of_the_asserted_kind_then_a_rule():
    from regulus.rag.premise_figures import _OPERATIVE
    assert _OPERATIVE.search("any cosmetic aerosol product containing vinyl chloride is deemed adulterated")
    assert not _OPERATIVE.search("Vinyl chloride has been used as an ingredient in cosmetic aerosol products.")
