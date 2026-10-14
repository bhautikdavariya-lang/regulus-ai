"""Stage 8 generation control: normalised repetition detection, keeping the valid prefix of a loop,
lead-in completion of the exact-evidence context, question verbs that are not topics, evidence
consolidation and the synthesis rule. In-memory tables and scripted generators: no PostgreSQL, no model.
"""

from __future__ import annotations

import pytest

from regulus.inference.repetition_text import normalise_sentence, repeated_sentence, trim_repetition
from regulus.rag import RagConfig, RagPipeline
from regulus.rag.generation import GROUNDED_SYSTEM_PROMPT
from regulus.retrieval import LexicalRetriever
from tests.test_answer_shape import TABLE
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, guidance_row, row

# the 21 CFR 830.20 pattern: correct answer, then one sentence repeated with an incrementing citation number
LOOP_WITH_MARKERS = ("21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [1]. "
                     + " ".join(f"The manufacturer must document procedures for traceability. [{n}]" for n in range(2, 9)))

LEAD_IN = [row("830.20", "", 0, text="A unique device identifier (UDI) must:"),
           row("830.20", "(a)", 1, text="(a) Be issued under a system operated by FDA or an FDA-accredited issuing agency;"),
           row("830.20", "(b)", 2, text="(b) Use only characters from the invariant character set.")]


def run(question, response, table=None, **cfg):
    g = ScriptedGenerator(response)
    db = TableDatabase(table if table is not None else TABLE, guidance=[guidance_row(0, rank=0.4)])
    return RagPipeline(LexicalRetriever(db), g, RagConfig(**cfg)).answer(question), g


# ------------------------------------------------------------ repetition


def test_a_sentence_repeated_with_changing_citation_numbers_is_one_repeated_sentence():
    assert repeated_sentence(LOOP_WITH_MARKERS) is not None
    assert normalise_sentence("The UDI must be shown. [5]") == normalise_sentence("the UDI must be shown [6]")
    assert normalise_sentence("Found in **SOURCE 1**: the rule.") == normalise_sentence("Found in SOURCE 2: the rule")


def test_different_sentences_sharing_a_clause_are_not_a_loop():
    text = ("For Clause 7.5.8, the manufacturer must document a UDI system [1]. For Clause 7.5.9.1, the manufacturer must "
            "document traceability [2]. For Clause 8.2.3, the manufacturer must notify FDA of complaints [3].")
    assert repeated_sentence(text) is None and trim_repetition(text) == (text, 0)


def test_trim_keeps_the_answer_before_the_loop_and_its_first_occurrence():
    kept, removed = trim_repetition(LOOP_WITH_MARKERS)
    assert removed == 6 and kept.count("must document procedures for traceability") == 1
    assert kept.startswith("21 CFR 820.10(b)(2) requires traceability procedures")


def test_a_loop_is_rejected_as_degenerate_not_trimmed_into_a_shown_answer():
    """Keeping the text before a loop was measured and rejected (S5-061, BM-S-001: not a valid answer); the loop is
    rejected and the requested provision is quoted verbatim instead."""
    out, _ = run("What does 21 CFR 820.10(b)(2) require?", LOOP_WITH_MARKERS)
    assert out.metadata["raw_model_output"] == LOOP_WITH_MARKERS
    assert "degenerate_output" in out.metadata["validation"]["initial"]["codes"]
    assert out.answer.count("must document procedures for traceability") <= 1
    assert out.metadata["validation"]["repair"] == "extractive_replacement"


def test_the_validator_sees_the_same_loop_the_generation_stop_sees():
    from regulus.rag.validation import _degenerate
    assert _degenerate(LOOP_WITH_MARKERS)[0]


def test_the_generation_stop_fires_on_a_loop_with_changing_markers():
    import torch
    from regulus.inference.repetition import CHECK_EVERY, RepetitionStop

    class Tok:
        def decode(self, ids, skip_special_tokens=True):
            return LOOP_WITH_MARKERS
    stop = RepetitionStop(Tok(), 10)
    assert bool(stop(torch.zeros((1, 10 + CHECK_EVERY), dtype=torch.long), None)[0])


# ------------------------------------------------------------ context and prompt


def test_a_lead_in_whose_own_subparagraphs_are_present_needs_no_related_material():
    out, _ = run("What does 21 CFR 830.20 require?", "x", table=LEAD_IN)
    tiers = {s.tier for s in out.context.sources}
    assert tiers <= {"exact", "structural"} and len(out.context.sources) == 3
    stage5, _ = run("What does 21 CFR 830.20 require?", "x", table=LEAD_IN, optional_context="always")
    assert any(s.tier == "supporting" for s in stage5.context.sources)


@pytest.mark.parametrize("verb", ["address", "cover", "govern", "concern", "establish", "regulate"])
def test_question_verbs_are_not_focus_topics(verb):
    from regulus.planning import plan_query
    from regulus.planning.shape import analyze_shape
    assert analyze_shape(plan_query(f"What does 21 CFR 830.20 {verb}?")).focus_terms == ()


def test_the_system_prompt_is_unchanged_by_stage8():
    # a "state each requirement once" rule was measured and REVERTED: it changed every answer and broke three
    # protected PASS questions (docs/generation_control_stage8.md); repetition is controlled by the guard instead
    assert "State each requirement once" not in GROUNDED_SYSTEM_PROMPT


# ------------------------------------------------------------ evidence consolidation


def labels(out):
    return [s.result.citation.label for s in out.context.sources]


def test_reserved_rows_are_dropped_from_a_part_level_context():
    table = TABLE + [row("820.5", "", 0, part="820", text="[Reserved]"), row("820.40", "", 0, part="820", text="[Reserved]")]
    out, _ = run("What does 21 CFR Part 820 require?", "x", table=table)
    assert "21 CFR 820.5" not in labels(out) and "21 CFR 820.40" not in labels(out)
    removed = out.selection.diagnostics["consolidated"]
    assert {r["reason"] for r in removed} == {"reserved (no content)"}


def test_a_requested_reserved_provision_is_kept_so_the_answer_can_say_so():
    table = [row("820.5", "", 0, text="[Reserved]")]
    out, _ = run("What does 21 CFR 820.5 require?", "x", table=table)
    assert "21 CFR 820.5" in labels(out)


def test_duplicate_rows_of_the_same_provision_become_one_item():
    same = "(b) Use only characters from the invariant character set."
    table = LEAD_IN[:2] + [row("830.20", "(b)", 2, text=same), row("830.20", "(b)", 3, text=same)]
    out, _ = run("What does 21 CFR 830.20 require?", "x", table=table)
    assert labels(out).count("21 CFR 830.20(b)") == 1


def test_identical_wording_in_different_provisions_is_kept_and_subsections_stay_distinct():
    wording = "(d) All applicable training in the development and application of risk-based preventive controls."
    table = [row("117.180", "(d)", 0, part="117", text=wording), row("507.53", "(d)", 0, part="507", text=wording)]
    out, _ = run("What do 21 CFR 117.180(d) and 21 CFR 507.53(d) require?", "x", table=table)
    assert {"21 CFR 117.180(d)", "21 CFR 507.53(d)"} <= set(labels(out))
    out2, _ = run("What does 21 CFR 830.20 require?", "x", table=LEAD_IN)
    assert {"21 CFR 830.20(a)", "21 CFR 830.20(b)"} <= set(labels(out2))


def test_near_duplicate_guidance_chunks_are_kept_once_but_parallel_cfr_provisions_are_not_merged():
    from regulus.rag.selection import consolidate_evidence
    text = "Manufacturers should establish procedures to control complaint handling and record every complaint received " * 3
    db = TableDatabase(TABLE, full_text=[row("111.155", "(a)", 0, part="111", text="(a) You must establish and follow written procedures for components.", rank=0.6),
                                         row("111.160", "(a)", 0, part="111", text="(a) You must establish and follow written procedures for packaging.", rank=0.5)],
                       guidance=[guidance_row(0, rank=0.4, body_text=text), guidance_row(1, rank=0.3, body_text=text + " today")])
    p = RagPipeline(LexicalRetriever(db), ScriptedGenerator("x"), RagConfig(evidence_consolidation="off"))
    plan_out = p.answer("How should complaint procedures be established?")
    consolidated, info = consolidate_evidence(plan_out.selection)
    kinds = [r["reason"] for r in info["removed"]]
    kept = [s.evidence.citation for s in consolidated.selected]
    assert kinds.count("duplicate") == 1
    assert "21 CFR 111.155(a)" in kept and "21 CFR 111.160(a)" in kept


def test_consolidation_can_be_switched_off_for_measurement():
    table = TABLE + [row("820.5", "", 0, part="820", text="[Reserved]")]
    out, _ = run("What does 21 CFR Part 820 require?", "x", table=table, evidence_consolidation="off")
    assert "21 CFR 820.5" in labels(out)



def test_an_identical_sentence_said_twice_is_said_once_and_near_duplicates_are_left_alone():
    from regulus.inference.repetition_text import drop_duplicate_sentences
    text = ("Each signature shall be unique to one individual. [1]\n\n"
            "- The certification shall be signed with a handwritten signature. [4]\n\n"
            "- The certification shall be signed with a handwritten signature. [4]\n\n"
            "Records shall be retained for the retention period. [2]")
    kept, removed = drop_duplicate_sentences(text)
    assert removed == 1 and kept.count("certification shall be signed") == 1 and "retention period" in kept
    near = ("The records required under subpart B must be kept in accordance with subpart P. "
            "The records required under subpart F must be kept in accordance with subpart P.")
    assert drop_duplicate_sentences(near) == (near, 0)


def test_the_pipeline_removes_a_repeated_identical_sentence_before_validation():
    answer = ("21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [1]. "
              "21 CFR 820.10(b)(2) requires traceability procedures under part 821, if applicable [1].")
    out, _ = run("What does 21 CFR 820.10(b)(2) require?", answer)
    assert out.answer.count("requires traceability procedures") == 1
    assert out.metadata["generation"]["duplicate_sentences_removed"] == 1 and out.metadata["raw_model_output"] == answer


# ------------------------------------------------------------ Stage 8 finalization: generic verification


@pytest.mark.parametrize("variant", [
    "The UDI must be shown on the label. The UDI must be shown on the label. The UDI must be shown on the label.",
    "The UDI must be shown on the label. [3] The UDI must be shown on the label. [4] The UDI must be shown on the label. [5]",
    "The UDI must be shown on the label. THE UDI MUST BE SHOWN ON THE LABEL. the udi must be shown on the label.",
    "- The UDI must be shown on the label.\n* The UDI must be shown on the label.\n1. The UDI must be shown on the label.",
])
def test_repetition_positive_cases(variant):
    assert repeated_sentence(variant) is not None


@pytest.mark.parametrize("text", [
    # legitimate repeated regulatory terminology in different requirements
    "The manufacturer must establish procedures for design control. The manufacturer must establish procedures for "
    "purchasing control. The manufacturer must establish procedures for production control.",
    # two different requirements with similar wording
    "Records required under subpart B must be kept in accordance with subpart P. Records required under subpart F "
    "must be kept in accordance with subpart P. Records required under subpart J must be kept in accordance with subpart P.",
    # a legitimate cross-reference repeated across statements
    "Complaints must be reported under part 803 of this chapter [1]. Advisory notices are handled under part 806 of this "
    "chapter [2]. Traceability follows part 821 of this chapter [3].",
    # different citations supporting separate statements
    "Each signature shall be unique [1]. Identity shall be verified before assignment [2]. Certification shall be submitted [3].",
])
def test_repetition_negative_cases(text):
    from regulus.inference.repetition_text import drop_duplicate_sentences
    assert repeated_sentence(text) is None and drop_duplicate_sentences(text) == (text, 0)


def test_the_repetition_code_names_no_regulation_question_or_sentence():
    from pathlib import Path
    import ast
    src = Path(__file__).resolve().parents[1] / "src" / "regulus" / "inference"
    for name in ("repetition_text.py", "repetition.py"):
        tree = ast.parse((src / name).read_text())
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        logic = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
        logic += [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
        for banned in ("830.20", "S5-061", "UDI", "device label", "question_id"):
            assert not any(banned in str(x) for x in logic), (name, banned)  # docstrings may describe the incident


# section completeness (lead-in chain rule), generic cases

def _ctx(question, table, **cfg):
    out, _ = run(question, "x", table=table, **cfg)
    return [s.result.citation.label for s in out.context.sources], {s.tier for s in out.context.sources}


def test_section_with_all_subparagraphs_present_needs_no_related_material():
    labels, tiers = _ctx("What does 21 CFR 830.20 require?", LEAD_IN)
    assert tiers <= {"exact", "structural"}


def test_section_with_a_missing_subparagraph_keeps_its_related_context():
    # the lead-in's chain is present, but a requested paragraph of another section is a fragment without its lead-in
    table = LEAD_IN + [row("830.40", "(a)", 0, text="(a) Be placed on the label and package; or")]
    labels, tiers = _ctx("What do 21 CFR 830.20 and 21 CFR 830.40(a) require?", table)
    assert "supporting" in tiers


def test_a_lead_in_without_its_subparagraphs_keeps_the_full_context():
    table = [row("830.20", "", 0, text="A unique device identifier (UDI) must:")]
    labels, tiers = _ctx("What does 21 CFR 830.20 require?", table)
    assert "supporting" in tiers


def test_a_section_with_cross_references_gets_no_referenced_part_added():
    table = [row("820.10", "(b)(3)", 0, text="(3) The manufacturer must notify FDA of complaints that meet the reporting criteria of part 803 of this chapter.")]
    labels, _ = _ctx("What does 21 CFR 820.10(b)(3) require?", table)
    assert not any(l.startswith("21 CFR 803") for l in labels)


def test_a_whole_part_request_keeps_its_rows_and_drops_only_reserved_ones():
    table = TABLE + [row("820.5", "", 0, part="820", text="[Reserved]")]
    labels, _ = _ctx("What does 21 CFR Part 820 require?", table)
    assert "21 CFR 820.5" not in labels and any(l.startswith("21 CFR 820.10") for l in labels)


# topic extraction: question verbs are not topics, the real topic stays

@pytest.mark.parametrize("question, topic", [
    ("What does 21 CFR 830.20 address?", ()),
    ("What does 21 CFR 830.20 govern?", ()),
    ("What does 21 CFR 830.20 require?", ()),
    ("What does 21 CFR 830.20 establish?", ()),
    ("What does 21 CFR 830.20 prohibit?", ("prohibit",)),
    ("What topics does 21 CFR 830.20 deal with?", ("topics",)),
    ("What does 21 CFR 820.10 say about traceability?", ("traceability",)),
    ("What does 21 CFR 820.10 address regarding complaint reporting?", ("complaint", "reporting")),
])
def test_question_verbs_are_not_topics_and_real_topics_survive(question, topic):
    from regulus.planning import plan_query
    from regulus.planning.shape import analyze_shape
    assert analyze_shape(plan_query(question)).focus_terms == topic


def test_evidence_order_is_deterministic():
    a = _ctx("What does 21 CFR Part 820 require?", TABLE + [row("820.5", "", 0, part="820", text="[Reserved]")])
    b = _ctx("What does 21 CFR Part 820 require?", TABLE + [row("820.5", "", 0, part="820", text="[Reserved]")])
    assert a == b
