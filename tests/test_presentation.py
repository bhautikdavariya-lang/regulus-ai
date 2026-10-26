"""Answer layout (regulus.rag.presentation): the delivered text split into answer, provisions and notes, never
rewritten (26 Oct 2026)."""
import re

from regulus.rag.presentation import present

GENERATED = (
    "No, § 700.14 does not apply to a non-aerosol pump spray, because it addresses cosmetic aerosol products [1].\n\n"
    "21 CFR 700.14(a) prohibits vinyl chloride as an ingredient of cosmetic aerosol products [1].  \n"
    "21 CFR 700.14(b) makes any such aerosol product subject to regulatory action [2].\n"
    "Evidence limit: not all of the retrieved text of 21 CFR 700.14 fit in the evidence supplied for this answer "
    "(1 paragraph left out). The answer above does not cover that text; consult the full provisions."
)


def words(text):
    return re.sub(r"\s+", " ", text).strip()


def test_a_generated_answer_is_split_into_verdict_answer_provisions_and_notes():
    p = present(GENERATED, citations=[{"index": 1, "label": "21 CFR 700.14(a)", "url": "u1", "cited_in_answer": True},
                                      {"index": 2, "label": "21 CFR 700.14(b)", "url": "u2", "cited_in_answer": False}])
    assert p.kind == "answer" and p.verdict == "No"
    assert p.lead == ["No, § 700.14 does not apply to a non-aerosol pump spray, because it addresses cosmetic aerosol products [1]."]
    assert [x.label for x in p.points] == ["21 CFR 700.14(a)", "21 CFR 700.14(b)"] and p.points[1].cites == [2]
    assert p.notes and p.notes[0].startswith("Evidence limit:")
    assert p.sources == [{"index": 1, "label": "21 CFR 700.14(a)", "url": "u1"}]   # cited only


def test_nothing_is_lost_or_rewritten():
    p = present(GENERATED)
    shown = words(" ".join(p.lead + [x.text for x in p.points] + p.notes))
    for line in GENERATED.splitlines():
        if line.strip():
            assert words(line) in shown


def test_a_first_paragraph_that_opens_with_a_citation_is_the_answer():
    p = present("21 CFR 70.20 requires that straight colors be packaged in sealed containers [1].")
    assert p.lead and not p.points


def test_a_composed_listing_answer_gets_its_verdict_and_quotes():
    text = ('Eye shadow: permitted.\n21 CFR 73.2162(b) states: "The color additive bismuth oxychloride may be safely '
            'used in coloring cosmetics generally." [6].\nUse limit: no percentage is stated [6].')
    p = present(text, fallback_type="composed_from_listing")
    assert (p.kind, p.verdict, p.verdict_subject) == ("composed", "Permitted", "Eye shadow")
    assert [x.label for x in p.points] == ["21 CFR 73.2162(b)"] and p.lead == ["Use limit: no percentage is stated [6]."]


def test_a_withheld_answer_reads_plainly_and_lists_what_was_consulted():
    text = ("The generated answer could not be validated against the retrieved regulatory evidence, so it is not shown. "
            "The retrieved sources were not verified to answer the question as asked, so their text is not quoted as an "
            "answer. Sources consulted: 21 CFR 700.25(a), FD&C Act § 613(a) [21 U.S.C. 364i(a)], 21 CFR 700.25(c) and 8 more.\n"
            "Evidence limit: not all of the retrieved text of 21 CFR 700.25 fit in the evidence supplied for this answer "
            "(2 paragraphs left out). The answer above does not cover that text; consult the full provisions.")
    p = present(text, fallback_type="unvalidated_answer_withheld")
    assert p.kind == "withheld" and "not shown" in p.summary
    assert p.consulted == ["21 CFR 700.25(a)", "FD&C Act § 613(a) [21 U.S.C. 364i(a)]", "21 CFR 700.25(c)", "8 more"]
    assert p.notes[0].startswith("Evidence limit:") and p.detail[0].startswith("The generated answer")


def test_a_sources_do_not_say_answer_leads_with_that_statement():
    text = ("The available regulatory sources do not provide enough information to answer this.\n\n"
            "21 CFR 720.4(a)(1) [2] requires the name and address of the person designated on the label.")
    p = present(text)
    assert p.lead[0].startswith("The available regulatory sources") and [x.label for x in p.points] == ["21 CFR 720.4(a)(1)"]


def test_a_repeated_paragraph_is_kept_the_layout_never_drops_text():
    first = "The fee to object and request a hearing on an order is $250.00 [11]."
    assert present(first + "\n\n" + first).lead == [first, first]


def test_an_anchored_follow_up_names_its_context():
    fu = {"anchor": {"cfr": ["74.2708"], "statute": []},
          "followup": {"anchored": True, "anchor": {"cfr": ["74.2708"], "statute": ["607"]}, "earlier_question": "Q1?"}}
    p = present("Yes, it may be used [1].", followup=fu)
    assert p.context == {"earlier_question": "Q1?", "provisions": ["21 CFR 74.2708", "FD&C Act § 607"]}
    assert present("Yes [1].", followup={"anchor": {}, "followup": {"anchored": False}}).context is None


def test_a_composed_answer_opening_with_a_citation_leads_with_it():
    text = ("21 CFR 701.11 sets no recordkeeping requirement: no paragraph of its text in this system requires a record "
            "to be made or kept. What it requires, verbatim:\n"
            "21 CFR 701.11(a) (eCFR, binding, verbatim): (a) The principal display panel shall bear a statement of identity [1].")
    p = present(text, fallback_type="composed_records_silence")
    assert p.kind == "composed" and p.lead[0].startswith("21 CFR 701.11 sets no recordkeeping")
    assert [x.label for x in p.points] == ["21 CFR 701.11(a)"]
