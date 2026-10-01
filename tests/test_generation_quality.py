"""Stage 6 generation quality: exact-evidence context, and the behaviours the
Stage 6 investigation relies on. In-memory tables and scripted generators: no
PostgreSQL, no model. General patterns only, no benchmark question or provision rule.
"""

from __future__ import annotations

import pytest

from regulus.rag import RagConfig, RagPipeline
from regulus.rag import answerability as A
from regulus.rag.fallback import FB_UNVALIDATED
from regulus.rag.generation import build_grounded_messages
from regulus.retrieval import LexicalRetriever
from tests.test_answer_shape import TABLE, TEXT
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, guidance_row, row

GOOD = "21 CFR 820.10(b)(2) requires documented traceability procedures under part 821, if applicable [1]."
# a loop INSIDE one sentence (Stage 8): the 4-gram test rejects it and repetition trimming cannot rescue it;
# a whole sentence repeated is now trimmed to its first occurrence instead (tests/test_stage8_generation_control.py)
LOOP = "Labels must carry the name " + "of the product and the name " * 12 + "of the product."


def run(question, response=GOOD, *, guidance=True, table=None, **cfg):
    db = TableDatabase(table if table is not None else TABLE, guidance=[guidance_row(0, rank=0.4)] if guidance else [])
    g = ScriptedGenerator(response)
    out = RagPipeline(LexicalRetriever(db), g, RagConfig(**cfg)).answer(question)
    return out, g


def tiers(out):
    return [s.tier for s in out.context.sources]


# ------------------------------------------------------------ exact-evidence context


def test_complete_exact_evidence_leaves_optional_sources_out_of_the_prompt():
    stage5, _ = run("What does 21 CFR 820.10(b)(2) require?", optional_context="always")
    stage6, g = run("What does 21 CFR 820.10(b)(2) require?")
    assert any(t in ("supporting", "discovery") for t in tiers(stage5))
    assert all(t in ("exact", "structural") for t in tiers(stage6))
    assert len(g.calls[0]["messages"][1]["content"]) < len(build_grounded_messages(stage5.package)[1]["content"])
    dropped = stage6.metadata["selection"]["dropped"]
    assert any(d["reason"] == "optional_not_needed_exact_evidence_complete" for d in dropped)


def test_optional_sources_are_kept_when_a_requested_provision_is_missing():
    out, _ = run("What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?")
    assert out.coverage.state != "COMPLETE" and any(t in ("supporting", "discovery") for t in tiers(out))


def test_general_questions_keep_their_context():
    db = TableDatabase(TABLE, full_text=[row("801.1", "", 0, text="Labeling applies.", rank=0.5)])
    out = RagPipeline(LexicalRetriever(db), ScriptedGenerator("Labeling applies [1]."), RagConfig()).answer("What must a drug label carry?")
    assert out.context.sources and not out.coverage.explicit


def test_exact_evidence_context_keeps_every_item_of_an_enumeration():
    out, _ = run("List all requirements under 21 CFR 820.10.", "x")
    labels = [s.result.citation.label for s in out.context.sources]
    for para in ("(a)", "(b)", "(b)(1)", "(b)(4)", "(c)", "(d)", "(e)"):
        assert f"21 CFR 820.10{para}" in labels, para


def test_exact_evidence_context_keeps_the_qualifier_bearing_source_and_validation_still_flags_a_dropped_qualifier():
    out, _ = run("What does 21 CFR 820.10(b)(2) require?", "21 CFR 820.10(b)(2) requires traceability procedures under part 821 [1].")
    assert "if applicable" in out.context.sources[0].text
    assert "qualifier_dropped" in out.metadata["validation"]["initial"]["codes"]


def test_sources_are_renumbered_and_citations_point_at_the_right_provision():
    out, _ = run("What do 21 CFR 820.10(b)(2) and 21 CFR 820.10(b)(4) require?",
                 "21 CFR 820.10(b)(2): traceability procedures under part 821, if applicable [1].\n"
                 "21 CFR 820.10(b)(4): advisory notices are handled under part 806 [2].")
    assert [s.index for s in out.context.sources] == list(range(1, len(out.context.sources) + 1))
    assert {c.label for c in out.citations} >= {"21 CFR 820.10(b)(2)", "21 CFR 820.10(b)(4)"}
    assert out.validation.ok


def test_citing_a_source_that_is_no_longer_supplied_is_caught():
    out, _ = run("What does 21 CFR 820.10(b)(2) require?", "21 CFR 820.10(b)(2) requires traceability, if applicable [7].")
    assert "invalid_citation" in out.metadata["validation"]["initial"]["codes"] and "[7]" not in out.answer


def test_stage5_context_remains_reachable_for_measurement():
    with pytest.raises(ValueError):
        RagConfig(optional_context="sometimes")
    assert RagConfig().optional_context == "incomplete_only"


# ------------------------------------------------------------ safety that Stage 6 must preserve


def test_degenerate_general_answer_is_withheld_not_quoted():
    """The S5-061 pattern: a general question, related-only evidence, repetitive generation."""
    db = TableDatabase(TABLE, full_text=[row("801.30", "(c)", 0, text="(c) Exception for shipping containers.", rank=0.5)])
    out = RagPipeline(LexicalRetriever(db), ScriptedGenerator(LOOP), RagConfig()).answer("What must a label identifier contain?")
    assert out.metadata["fallback_type"] == FB_UNVALIDATED and "Exception for shipping containers" not in out.answer


def test_failed_repair_is_never_shown(monkeypatch):
    g = ScriptedGenerator("21 CFR 820.10(b)(2) requires a fee of $500 [1].")
    p = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), g, RagConfig())
    monkeypatch.setattr(p, "repair_answer", lambda text, package, report, **kw: ("", "broken_repair"))
    out = p.answer("What does 21 CFR 820.10(b)(2) require?")
    assert "$500" not in out.answer and out.validation.ok and out.metadata["repair_output"] == ""


@pytest.mark.parametrize("target", ["part 803", "part 806", "part 821"])
def test_a_lookup_naming_only_the_referenced_provision_is_declined_for_any_target(target):
    """S5-090 generalised: the named provision is the object of the reference, not the answer."""
    table = TABLE + [row(target.split()[1] + ".1", "", 0, text="Scope of this part.")]
    out, g = run(f"Cite the provision that requires manufacturers to handle notices meeting {target} criteria.", table=table)
    assert out.metadata["answerability"]["state"] == A.WRONG_PROVISION and g.calls == []


def test_a_lookup_that_names_its_container_is_generated():
    """S5-091 generalised: the container is what is asked about, so the model is asked."""
    out, g = run("Which provision of 21 CFR 820.10 refers to part 806?")
    assert out.metadata["answerability"]["state"] != A.WRONG_PROVISION and len(g.calls) == 1


def test_generation_is_deterministic_for_the_same_evidence():
    a, ga = run("What does 21 CFR 820.10(b)(2) require?")
    b, gb = run("What does 21 CFR 820.10(b)(2) require?")
    assert ga.calls[0]["messages"] == gb.calls[0]["messages"] and a.answer == b.answer


def test_a_comparison_keeps_its_related_context():
    """Stage 6 scope: the exact-evidence context is not applied to a comparison (AS-05 overstated a scope without it)."""
    out, _ = run("Compare 21 CFR 820.10(c) and 820.10(d).", "x")
    stage5, _ = run("Compare 21 CFR 820.10(c) and 820.10(d).", "x", optional_context="always")
    assert [s.result.key for s in out.context.sources] == [s.result.key for s in stage5.context.sources]


def test_a_lead_in_provision_keeps_the_full_context():
    """A requested provision whose text is a lead-in (ends with a colon) keeps the Stage 5 context (the S5-011 pattern)."""
    text = dict(TEXT, **{"(c)": "(c) Design and development. The class I devices are as follows:"})
    table = [row("820.10", p, n, text=t) for n, (p, t) in enumerate(text.items())]
    out, _ = run("What does 21 CFR 820.10(c) require?", "x", table=table)
    stage5, _ = run("What does 21 CFR 820.10(c) require?", "x", table=table, optional_context="always")
    assert [s.result.key for s in out.context.sources] == [s.result.key for s in stage5.context.sources]


@pytest.mark.parametrize("text, complete", [("(1) The name of the food.", True), ("(2) The common name; or, in the absence thereof,", False),
                                            ("(b) Such statement shall be in terms of:", False), ("(3) Handled as required (see part 806).", True)])
def test_complete_sentence_detection(text, complete):
    from regulus.rag.selection import is_complete_sentence
    assert is_complete_sentence(text) is complete


def test_a_complete_provision_does_not_keep_unrequested_children():
    text = dict(TEXT, **{"(b)": "(b) Applicable regulatory requirements. Comply with the other applicable requirements in this title."})
    table = [row("820.10", p, n, text=t) for n, (p, t) in enumerate(text.items())]
    out, _ = run("What does 21 CFR 820.10(b) require?", "x", table=table)
    labels = [s.result.citation.label for s in out.context.sources]
    assert "21 CFR 820.10(b)" in labels and not any(l.startswith("21 CFR 820.10(b)(") for l in labels)
