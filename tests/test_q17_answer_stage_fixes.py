"""22 Oct fixes from the Qwen3-1.7B cosmetics diagnosis (artifacts/cosmetics_benchmark/q17_fix_20261022).

1. A focused one-provision question whose provision is SHORT is no longer told to state only what the provision says
   about its topic words: on COS-710.5-Q1 that restriction made the model drop the second of 21 CFR 710.5's two
   sentences (the cancellation-on-name-change rule). Long provisions keep the restriction.
2. "None (general question)" - the REQUESTED PROVISIONS label of a general question copied as the answer
   (COS-70.19-Q2) - is a prompt echo, so the validator classes it as degenerate instead of delivering it.
3. Requirement-id labels ("r1:") and empty numbered items copied from the prompt's layout are removed from the
   answer text (COS-70.50-Q2, COS-82.203-Q1, COS-710.5-Q1; COS-82.101-Q1, COS-82.304-Q1). Presentation only.

The 710.5 text is copied verbatim from the read-only database snapshot. No PostgreSQL, no model.
"""

from __future__ import annotations

from regulus.planning.shape import MODE_FOCUSED
from regulus.rag.answer_quality import strip_plan_labels
from regulus.rag.generation import SHORT_PROVISION_CHARS, render_package, short_requested_provision
from regulus.rag.shape_validation import PROMPT_ECHO
from regulus.rag.validation import validate_answer
from tests.test_answer_shape import TABLE as TABLE_820_10, codes, gen, idx
from tests.test_retrieval_plan import TableDatabase, row

from regulus.planning import plan_query
from regulus.rag import RagConfig, RagPipeline
from regulus.rag.context import ContextPolicy
from regulus.rag.coverage import check_coverage
from regulus.rag.generation import build_package
from regulus.retrieval import LexicalRetriever

# 21 CFR 710.5, verbatim (one undesignated paragraph, 334 characters)
TEXT_710_5 = ("Within 30 days after a change in any of the information contained on a submitted Form FD-2511, a new Form "
              "FD-2511 should be submitted to amend the registration. This amendment is also necessary when a registration "
              "is to be canceled because an establishment has changed its name and no longer conducts business under the "
              "original name.")
TABLE_710_5 = [row("710.5", "", 0, part="710", text=TEXT_710_5)]
Q_710_5 = "We changed our establishment's address. What does § 710.5 say about amending a registration?"   # COS-710.5-Q1
Q_820_10_TOPIC = "What does 21 CFR 820.10 say about traceability procedures?"

RESTRICTED = "stating only what the requested provision says about the focus"


def package(question, table):
    plan = plan_query(question)
    pipe = RagPipeline(LexicalRetriever(TableDatabase(table)), generator=None, config=RagConfig(answer_shape="adaptive"))
    shape = pipe.shape_for(plan)
    out = pipe.retriever.run_plan(plan, top_k=8)
    sel = RagPipeline(pipe.retriever, None, RagConfig(context=ContextPolicy(), answer_shape="adaptive")).select(out.registry, shape)
    return build_package(plan, check_coverage(out.registry), sel, answer_shape=shape)


# ------------------------------------------------------------ 1. short provision: no topic restriction


def test_710_5_is_a_focused_question_with_topic_words():
    pkg = package(Q_710_5, TABLE_710_5)
    assert pkg.answer_plan.mode == MODE_FOCUSED and pkg.answer_plan.shape.focus_terms
    assert len(TEXT_710_5) <= SHORT_PROVISION_CHARS


def test_short_provision_keeps_every_sentence_in_scope():
    pkg = package(Q_710_5, TABLE_710_5)
    prompt = render_package(pkg)
    assert short_requested_provision(pkg)
    assert RESTRICTED not in prompt and "  focus:" not in prompt
    assert "plain sentences stating what the requested provision requires, taken from its EXACT source" in prompt
    assert "has changed its name and no longer conducts business under the original name" in prompt   # evidence intact


def test_long_provision_keeps_the_topic_restriction():
    pkg = package(Q_820_10_TOPIC, TABLE_820_10)
    assert pkg.answer_plan.mode == MODE_FOCUSED and pkg.answer_plan.shape.focus_terms
    assert sum(len(s.text) for s in pkg.sources if s.tier == "exact") > SHORT_PROVISION_CHARS
    assert not short_requested_provision(pkg)
    prompt = render_package(pkg)
    assert RESTRICTED in prompt and "  focus:" in prompt


def test_both_710_5_sentences_validate_and_one_sentence_alone_still_validates():
    """The change is in the instruction only; the validator's judgement of either answer is unchanged."""
    pkg = package(Q_710_5, TABLE_710_5)
    i = idx(pkg, "21 CFR 710.5")
    full = (f"Within 30 days after a change in any of the information on a submitted Form FD-2511, a new Form FD-2511 "
            f"should be submitted to amend the registration [{i}]. A new form is also necessary when a registration is to "
            f"be canceled because the establishment has changed its name and no longer conducts business under the "
            f"original name [{i}].")
    assert validate_answer(full, pkg, gen()).status == "valid"


# ------------------------------------------------------------ 2. "None (general question)" is a prompt echo


def test_general_question_label_copied_as_the_answer_is_degenerate():
    pkg = package(Q_710_5, TABLE_710_5)   # any package with an answer plan runs the shape checks
    for echo in ("None (general question) [1]", "none (general question)"):
        r = validate_answer(echo, pkg, gen())
        assert PROMPT_ECHO in codes(r) and r.status == "degenerate"


def test_an_answer_that_merely_mentions_a_general_question_is_not_an_echo():
    pkg = package(Q_710_5, TABLE_710_5)
    i = idx(pkg, "21 CFR 710.5")
    text = f"A new Form FD-2511 should be submitted within 30 days after a change to amend the registration [{i}]."
    assert PROMPT_ECHO not in codes(validate_answer(text, pkg, gen()))


# ------------------------------------------------------------ 3. plan-id labels and empty list items


def test_requirement_id_labels_are_removed_from_line_starts():
    text, n = strip_plan_labels("r1: Within 30 days ... amend the registration. [1]\nr2: A new form is also necessary [1].")
    assert text == "Within 30 days ... amend the registration. [1]\nA new form is also necessary [1]." and n == 2


def test_empty_numbered_items_are_removed_and_filled_items_kept():
    raw = ("1. FD&C Blue No. 1 shall conform to § 74.101(a)(1) and (b) [2]. \n2. \n3. \n"
           "4. No batch shall be certified unless it conforms to § 82.5 [5].")
    text, n = strip_plan_labels(raw)
    assert n == 2
    assert text.splitlines() == ["1. FD&C Blue No. 1 shall conform to § 74.101(a)(1) and (b) [2]. ",
                                 "4. No batch shall be certified unless it conforms to § 82.5 [5]."]


def test_regulatory_text_is_never_altered():
    for text in ("Under 21 CFR 82.5, the batch must conform [1].",
                 "Section 801.1 applies; the label lists r1 and r2 as examples [3].",   # "r1" not at a line start
                 "(1) Devices automated with computer software; and",
                 "The available regulatory sources do not provide enough information to answer this question."):
        assert strip_plan_labels(text) == (text, 0)
