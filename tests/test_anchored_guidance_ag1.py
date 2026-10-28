from regulus.retrieval.lexical import _GUIDANCE_ASKED, ag1_or_query


def test_ag1_builds_an_or_query_of_the_questions_content_words():
    q = "An HPLC assay result is out of specification. What does Part 211 require, and what does the Barr decision framework add?"
    terms = ag1_or_query(q).split(" or ")
    assert {"hplc", "assay", "specification", "barr", "framework"} <= set(terms)   # D-023
    assert "require" not in terms and "what" not in terms


def test_ag1_runs_only_for_questions_that_ask_beyond_the_regulation():
    assert _GUIDANCE_ASKED.search("what does the Barr decision framework add?")
    assert _GUIDANCE_ASKED.search("What does FDA recommend for cleaning validation?")
    assert not _GUIDANCE_ASKED.search("What must the batch production record contain under Part 111?")
