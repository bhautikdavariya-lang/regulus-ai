"""Stage 12: adaptive answer shape and evidence planning.

The same evidence must be synthesized for "What does 21 CFR 820.10 require?"
and enumerated for "List all requirements under 21 CFR 820.10."; a focused
question must stay on its provision; a comparison must compare. None of it
may drop a qualifier, an applicability limit, a citation or a source, and
none of it may touch the Stage 11 token budget.

The in-memory table holds the real text of 21 CFR 820.10 (copied from the
verified database, unmodified), so qualifiers, headings and cross-references
are exercised on the wording they will meet in production. No PostgreSQL,
no model.
"""

from __future__ import annotations

import re

import pytest

from regulus.inference.generate import GenerationResult
from regulus.planning import plan_query
from regulus.planning.shape import (
    MODE_COMPARISON,
    MODE_DIRECT,
    MODE_ENUMERATION,
    MODE_FOCUSED,
    MODE_SYNTHESIS,
    SCOPE_MULTIPLE,
    SCOPE_PART,
    SCOPE_SECTION,
    SCOPE_SUBSECTION,
    SCOPE_TOPIC,
    analyze_shape,
)
from regulus.rag import RagConfig, RagPipeline
from regulus.rag.answer_plan import (
    ROLE_CONSEQUENCE,
    ROLE_CONTEXT,
    ROLE_LEAD_IN,
    ROLE_RELATED,
    ROLE_REQUIREMENT,
    ROLE_SUBORDINATE,
    extract_applicability,
    extract_cross_references,
    extract_heading,
    extract_qualifiers,
)
from regulus.rag.citations import build_answer_citations
from regulus.rag.context import ContextPolicy
from regulus.rag.coverage import check_coverage
from regulus.rag.generation import GROUNDED_SYSTEM_PROMPT, GenerationBudget, build_package, render_package
from regulus.rag.selection import REASON_SUBORDINATE
from regulus.rag.shape_validation import (
    APPLICABILITY_DROPPED,
    ENUMERATION_INCOMPLETE,
    EVIDENCE_BY_EVIDENCE,
    PROMPT_ECHO,
    MATERIAL_GROUP_UNCOVERED,
    QUALIFIER_DROPPED,
    QUALIFIER_MISAPPLIED,
    REPEATED_STATEMENT,
    SCOPE_EXPANSION,
    SYNTHESIS_CITATION_GAP,
)
from regulus.rag.validation import STATUS_INCOMPLETE, STATUS_VALID, TRUNCATED, validate_answer
from regulus.retrieval import LexicalRetriever
from tests.test_answer_validation import ScriptedGenerator
from tests.test_retrieval_plan import TableDatabase, row

# 21 CFR 820.10, verbatim from the verified snapshot
TEXT = {
    "": "A manufacturer subject to this part as described by § 820.1(a) must:",
    "(a)": "(a) Document. Document a quality management system that complies with the applicable requirements of ISO 13485 "
           "(incorporated by reference, see § 820.7) and other applicable requirements of this part; and",
    "(b)": "(b) Applicable regulatory requirements. Comply, as appropriate, with the other applicable regulatory requirements "
           "in this title, including, but not limited to the following, to fully comply with the listed ISO 13485 Clause:",
    "(b)(1)": "(1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique "
              "device identification to the medical device in accordance with the requirements of part 830 of this chapter.",
    "(b)(2)": "(2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for "
              "traceability in accordance with the requirements of part 821 of this chapter, if applicable.",
    "(b)(3)": "(3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of "
              "complaints that meet the reporting criteria of part 803 of this chapter.",
    "(b)(4)": "(4) For Clauses 7.2.3, 8.2.3, and 8.3.3, advisory notices shall be handled in accordance with the requirements "
              "of part 806 of this chapter.",
    "(c)": "(c) Design and development. Manufacturers of class II, class III, and those class I devices listed in paragraph "
           "(c)(1) of this section and table 1 to paragraph (c)(2) of this section must comply with the requirements in "
           "Design and Development, Clause 7.3 and its Subclauses in ISO 13485. The class I devices are as follows:",
    "(c)(1)": "(1) Devices automated with computer software; and",
    "(c)(2)": "(2) The devices listed in the following table:",
    "(d)": "(d) Devices that support or sustain life. Manufacturers of devices that support or sustain life, the failure of "
           "which to perform when properly used in accordance with instructions for use provided in the labeling can be "
           "reasonably expected to result in a significant injury, must comply with the requirements in Traceability for "
           "Implantable Devices, Clause 7.5.9.2 in ISO 13485, in addition to all other applicable requirements in this "
           "part, as appropriate.",
    "(e)": "(e) Enforcement. The failure to comply with any applicable requirement in this part renders a device adulterated "
           "under section 501(h) of the Federal Food, Drug, and Cosmetic Act. Such a device, as well as any person "
           "responsible for the failure to comply, is subject to regulatory action.",
}
TABLE = [row("820.10", para, n, text=text) for n, (para, text) in enumerate(TEXT.items())]

BROAD = "What does 21 CFR 820.10 require?"
EXHAUSTIVE = "List all requirements under 21 CFR 820.10."
FOCUSED = "What does 21 CFR 820.10(b)(2) require?"
RANGE = "Explain 21 CFR 820.10(a) through (e)."
COMPARE = "Compare 21 CFR 820.10(c) and 820.10(d)."
CONDITIONAL = "What does 21 CFR 820.10(d) require?"
MULTI = "What does §820.10(b)(1)–(b)(4) require?"


def package(question, *, shaped=True, budget=None, policy=None):
    plan = plan_query(question)
    pipe = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), generator=None, config=RagConfig(answer_shape="adaptive" if shaped else "off"))
    shape = pipe.shape_for(plan)
    out = pipe.retriever.run_plan(plan, top_k=8)
    cov = check_coverage(out.registry)
    sel = RagPipeline(pipe.retriever, None, RagConfig(context=policy or ContextPolicy(), answer_shape=pipe.config.answer_shape)).select(out.registry, shape)
    return build_package(plan, cov, sel, budget=budget, answer_shape=shape)


def idx(pkg, citation):
    return next(s.index for s in pkg.sources if s.citation == citation)


def gen(tokens=80, finished=True):
    return GenerationResult("p", "x", 500, tokens, 1.0, finished=finished)


def codes(report):
    return set(report.codes())


# ============================================================ shape detection


@pytest.mark.parametrize("question, mode, scope, exhaustive", [
    (BROAD, MODE_SYNTHESIS, SCOPE_SECTION, False),
    ("What does 21 CFR 820.10 say?", MODE_SYNTHESIS, SCOPE_SECTION, False),
    ("Summarize 21 CFR 803.13.", MODE_SYNTHESIS, SCOPE_SECTION, False),
    ("Give an overview of all requirements in 21 CFR 820.10.", MODE_SYNTHESIS, SCOPE_SECTION, False),
    ("Does 21 CFR 820.10 apply to all manufacturers?", MODE_SYNTHESIS, SCOPE_SECTION, False),
    (EXHAUSTIVE, MODE_ENUMERATION, SCOPE_SECTION, True),
    ("Explain every requirement in §820.10.", MODE_ENUMERATION, SCOPE_SECTION, True),
    ("Walk through each subsection of 21 CFR 820.10.", MODE_ENUMERATION, SCOPE_SECTION, True),
    (FOCUSED, MODE_FOCUSED, SCOPE_SUBSECTION, False),
    ("What is required for traceability under §820.10(b)(2)?", MODE_FOCUSED, SCOPE_SUBSECTION, False),
    (CONDITIONAL, MODE_FOCUSED, SCOPE_SUBSECTION, False),
    ("List the requirements in 21 CFR 820.10(b).", MODE_ENUMERATION, SCOPE_SUBSECTION, True),
    (RANGE, MODE_ENUMERATION, SCOPE_MULTIPLE, True),
    (MULTI, MODE_ENUMERATION, SCOPE_MULTIPLE, True),
    ("What are all the requirements under §820.10(b)(1)–(b)(4)?", MODE_ENUMERATION, SCOPE_MULTIPLE, True),
    (COMPARE, MODE_COMPARISON, SCOPE_MULTIPLE, False),
    ("How does 21 CFR 820.10(c) differ from 820.10(d)?", MODE_COMPARISON, SCOPE_MULTIPLE, False),
    ("What is Part 821?", MODE_DIRECT, SCOPE_PART, False),
    ("What is a quality management system?", MODE_DIRECT, SCOPE_TOPIC, False),
    ("What are the requirements for complaint handling?", MODE_SYNTHESIS, SCOPE_TOPIC, False),
    ("List all requirements for complaint handling.", MODE_ENUMERATION, SCOPE_TOPIC, True),
    ("Compare design controls and complaint handling.", MODE_COMPARISON, SCOPE_TOPIC, False),
])
def test_shape_is_read_from_structure_and_wording_together(question, mode, scope, exhaustive):
    shape = analyze_shape(plan_query(question))
    assert (shape.mode, shape.scope, shape.exhaustive) == (mode, scope, exhaustive), shape.to_dict()
    assert shape.rationale


def test_what_does_wording_over_several_named_provisions_is_not_a_broad_synthesis():
    shape = analyze_shape(plan_query(MULTI))
    assert shape.mode == MODE_ENUMERATION and len(shape.requested_units) == 4
    assert "several_named_provisions" in shape.signals


def test_all_counts_only_when_bound_to_a_requirement_noun():
    assert analyze_shape(plan_query("Does 21 CFR 820.10 apply to all manufacturers?")).mode == MODE_SYNTHESIS
    assert analyze_shape(plan_query("What are all the requirements in 21 CFR 820.10?")).mode == MODE_ENUMERATION


def test_identifiers_are_never_read_as_wording():
    # "(a) through (e)" contains no list word once the identifiers are masked
    assert "list_verb" not in analyze_shape(plan_query(RANGE)).signals


def test_a_topic_inside_a_section_focuses_the_answer():
    shape = analyze_shape(plan_query("What does 21 CFR 820.10 say about complaints?"))
    assert shape.mode == MODE_FOCUSED and shape.focus_terms == ("complaints",)


def test_shape_is_deterministic_and_serialisable():
    a, b = analyze_shape(plan_query(BROAD)), analyze_shape(plan_query(BROAD))
    assert a == b and a.to_dict() == b.to_dict()


# ============================================================ A: broad synthesis


def test_a_broad_question_groups_children_under_their_parent():
    pkg = package(BROAD)
    plan = pkg.answer_plan
    assert plan.mode == MODE_SYNTHESIS
    assert [g.key for g in plan.groups] == ["820.10(a)", "820.10(b)", "820.10(c)", "820.10(d)", "820.10(e)"]
    b = next(g for g in plan.groups if g.key == "820.10(b)")
    assert b.head == idx(pkg, "21 CFR 820.10(b)")
    assert b.items == tuple(idx(pkg, f"21 CFR 820.10(b)({n})") for n in range(1, 5))
    assert plan.lead_in == (idx(pkg, "21 CFR 820.10"),)
    assert [g.heading for g in plan.groups] == ["Document", "Applicable regulatory requirements", "Design and development",
                                               "Devices that support or sustain life", "Enforcement"]
    assert plan.source(idx(pkg, "21 CFR 820.10(e)")).role == ROLE_CONSEQUENCE
    assert plan.source(idx(pkg, "21 CFR 820.10(b)(3)")).role == ROLE_SUBORDINATE


def test_a_broad_question_is_told_to_write_per_group_not_per_source():
    text = render_package(package(BROAD))
    head = text.split("EVIDENCE")[0]
    assert "answer shape: synthesized overview (not exhaustive)" in head
    assert "requirement groups, in order: (a) Document [2]; (b) Applicable regulatory requirements [3] with " \
           "sub-requirements the manufacturer must document a system to assign unique device identification" in head
    assert "part 821 of this chapter, if applicable [5]" in head and "(e) Enforcement [12]" in head
    fmt = text.split("ANSWER FORMAT:")[1]
    assert "one paragraph for each of its requirement groups" in fmt
    assert "instead of giving each source a paragraph of its own. Do not leave a group out" in fmt


def test_a_the_plan_is_never_rendered_as_a_copyable_block():
    """Live runs showed the 0.6B model copying the last list it read (a plan
    block after the evidence; lists inside the format line). Lists sit under
    REQUESTED PROVISIONS, before the evidence; the final line has none."""
    for q in (BROAD, EXHAUSTIVE, FOCUSED, RANGE, COMPARE, CONDITIONAL, MULTI):
        text = render_package(package(q))
        assert "ANSWER PLAN" not in text and "GROUP A" not in text
        assert text.index("answer shape:") < text.index("EVIDENCE")
        fmt = text.split("ANSWER FORMAT:")[1]
        assert text.count("ANSWER FORMAT:") == 1 and "\n" not in fmt
        assert not re.search(r"\[\d+\](?!\[)", fmt.replace("[4][5]", "")), fmt  # no source list in the final line


def test_a_an_answer_that_copies_the_instructions_is_degenerate_and_replaced():
    pkg = package(BROAD)
    echo = "- Lead-in: SOURCE 1\n- GROUP A: 21 CFR 820.10(a) \"Document\" = SOURCE 2"
    r = validate_answer(echo, pkg, gen())
    assert PROMPT_ECHO in codes(r) and r.status == "degenerate"
    repaired, how = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), None, RagConfig()).repair_answer(echo, pkg, r)
    assert how == "extractive_replacement" and "GROUP A" not in repaired
    assert PROMPT_ECHO not in codes(validate_answer(SYNTHESIS, pkg, gen()))


DUMP = "\n".join(
    f"21 CFR 820.10{p}: {t.split('. ', 1)[-1][:60]} [{i}]." for i, (p, t) in enumerate(TEXT.items(), start=1) if p
)
SYNTHESIS = (
    "21 CFR 820.10 requires a manufacturer to document a quality management system that complies with ISO 13485 [2].\n"
    "It must also comply, as appropriate, with other applicable requirements: unique device identification under part 830 [4], "
    "traceability procedures under part 821 if applicable [5], reporting complaints to FDA under part 803 [6] and handling "
    "advisory notices under part 806 [7][3].\n"
    "Manufacturers of class II, class III and listed class I devices, such as software-automated devices, must meet the design "
    "and development requirements of Clause 7.3 [8][9][10].\n"
    "Manufacturers of devices that support or sustain life must also meet Clause 7.5.9.2 on implantable-device traceability, "
    "as appropriate [11].\n"
    "Failure to comply renders a device adulterated and subject to regulatory action [12]."
)


def test_a_row_by_row_dump_is_flagged_and_a_synthesis_is_not():
    pkg = package(BROAD)
    dump = validate_answer(DUMP, pkg, gen())
    assert EVIDENCE_BY_EVIDENCE in codes(dump)
    good = validate_answer(SYNTHESIS, pkg, gen())
    assert EVIDENCE_BY_EVIDENCE not in codes(good)
    assert good.status == STATUS_VALID, good.to_dict()["problems"]
    shape = good.diagnostics["shape"]
    assert shape["groups_covered"] == shape["groups"] == 5 and shape["material_items_covered"] == shape["material_items"]


def test_a_synthesis_that_drops_a_whole_group_is_completed_from_the_source():
    """A missing requirement group is a completeness failure, not a style one:
    repair appends that group verbatim (live runs showed the 0.6B model
    dropping groups). The rest of the synthesis is kept as written."""
    pkg = package(BROAD)
    without_e = SYNTHESIS.rsplit("\n", 1)[0]
    r = validate_answer(without_e, pkg, gen())
    assert MATERIAL_GROUP_UNCOVERED in codes(r) and r.status == STATUS_INCOMPLETE
    assert r.diagnostics["shape"]["uncovered_groups"] == ["21 CFR 820.10(e)"]
    repaired, how = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), None, RagConfig()).repair_answer(without_e, pkg, r)
    assert how == "appended_missing_items" and repaired.startswith(without_e)
    assert "adulterated" in repaired and validate_answer(repaired, pkg, gen()).status == STATUS_VALID


def test_a_direct_answer_is_not_required_to_cover_every_group():
    db = TableDatabase([row("821.1", "(a)", 0, part="821", text="(a) The regulations in this part implement device tracking."),
                        row("821.3", "", 0, part="821", text="The following definitions apply to this part."),
                        row("821.4", "", 0, part="821", text="Nothing in this part preempts other requirements.")])
    plan = plan_query("What is Part 821?")
    pipe = RagPipeline(LexicalRetriever(db), None, RagConfig())
    out = pipe.retriever.run_plan(plan, top_k=8)
    pkg = build_package(plan, check_coverage(out.registry), pipe.select(out.registry, pipe.shape_for(plan)), answer_shape=pipe.shape_for(plan))
    assert pkg.answer_plan.mode == MODE_DIRECT and len(pkg.answer_plan.groups) >= 2
    r = validate_answer("Part 821 sets out medical device tracking requirements [1].", pkg, gen())
    assert MATERIAL_GROUP_UNCOVERED not in codes(r)


def test_a_requested_child_keeps_its_own_group_beside_its_requested_parent():
    pkg = package("What do 21 CFR 820.10(b) and 820.10(b)(1) require?")
    groups = {g.label: g for g in pkg.answer_plan.groups}
    b1 = idx(pkg, "21 CFR 820.10(b)(1)")
    assert groups["21 CFR 820.10(b)(1)"].head == b1
    assert b1 not in groups["21 CFR 820.10(b)"].members
    assert sorted(pkg.answer_plan.all_indices()) == sorted(s.index for s in pkg.sources)


# ============================================================ B: focused


def test_b_focused_plan_holds_only_the_requested_provision():
    pkg = package(FOCUSED)
    plan = pkg.answer_plan
    assert plan.mode == MODE_FOCUSED
    assert [g.members for g in plan.groups] == [(idx(pkg, "21 CFR 820.10(b)(2)"),)]
    assert {plan.source(i).role for i in plan.context} == {ROLE_CONTEXT}
    assert not any(s.citation in ("21 CFR 820.10(b)(1)", "21 CFR 820.10(b)(3)", "21 CFR 820.10(e)") for s in pkg.sources)
    assert "Do not describe other paragraphs of the section" in render_package(pkg)
    assert 'conditions to keep: "if applicable" [1]' in render_package(pkg)


def test_b_focused_answer_expanding_into_siblings_is_flagged():
    pkg = package(FOCUSED)
    i = idx(pkg, "21 CFR 820.10(b)(2)")
    ok = validate_answer(f"21 CFR 820.10(b)(2) requires documented traceability procedures under part 821, if applicable [{i}].", pkg, gen())
    assert SCOPE_EXPANSION not in codes(ok) and ok.status == STATUS_VALID
    wide = validate_answer(
        f"21 CFR 820.10(b)(2) requires documented traceability procedures under part 821, if applicable [{i}]. "
        "In addition, 21 CFR 820.10(b)(3) requires complaints to be reported to FDA.", pkg, gen())
    assert SCOPE_EXPANSION in codes(wide)
    assert wide.diagnostics["shape"]["out_of_scope_named"] == ["21 CFR 820.10(b)(3)"]


# ============================================================ C: explicit enumeration


def test_c_the_same_evidence_is_enumerated_when_every_requirement_is_asked_for():
    broad, full = package(BROAD), package(EXHAUSTIVE)
    assert [s.evidence_id for s in broad.sources] == [s.evidence_id for s in full.sources]  # same evidence
    assert full.answer_plan.mode == MODE_ENUMERATION and full.answer_shape.exhaustive
    assert render_package(broad) != render_package(full)                                   # different shape
    text = render_package(full)
    assert "answer shape: every item, listed separately (exhaustive)" in text
    assert "21 CFR 820.10(b)(1) [4]; 21 CFR 820.10(b)(2) [5]; 21 CFR 820.10(b)(3) [6]; 21 CFR 820.10(b)(4) [7]" in text
    assert "Keep distinct items separate and include every one" in text


def test_c_a_missing_item_of_an_explicit_enumeration_is_an_error_and_repair_restores_it_verbatim():
    pkg = package(EXHAUSTIVE)
    b3 = idx(pkg, "21 CFR 820.10(b)(3)")
    answer = SYNTHESIS.replace("reporting complaints to FDA under part 803 [6] and ", "")
    r = validate_answer(answer, pkg, gen())
    assert ENUMERATION_INCOMPLETE in codes(r) and r.status == STATUS_INCOMPLETE
    assert [p.citation for p in r.problems if p.code == ENUMERATION_INCOMPLETE] == [b3]
    pipe = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), None, RagConfig())
    repaired, how = pipe.repair_answer(answer, pkg, r)
    assert how == "appended_missing_items"
    assert TEXT["(b)(3)"][:-1] in repaired and f"[{b3}]" in repaired
    assert validate_answer(repaired, pkg, gen()).status == STATUS_VALID


def test_c_long_answers_are_not_penalised():
    pkg = package(EXHAUSTIVE)
    long_answer = "\n".join(f"21 CFR 820.10{p}: {t.rstrip(':')} [{i}]." for i, (p, t) in enumerate(TEXT.items(), start=1) if p)
    r = validate_answer(long_answer, pkg, gen(tokens=1500))
    assert r.status == STATUS_VALID, r.to_dict()["problems"]
    assert not any("long" in p.code for p in r.problems)


# ============================================================ D: subsection range


def test_d_a_range_keeps_every_child_of_every_requested_subsection():
    tight = ContextPolicy(max_results=6, max_total_chars=1500)
    shaped, legacy = package(RANGE, policy=tight), package(RANGE, shaped=False, policy=tight)
    wanted = {f"21 CFR 820.10(b)({n})" for n in range(1, 5)} | {"21 CFR 820.10(c)(1)", "21 CFR 820.10(c)(2)"}
    assert wanted <= {s.citation for s in shaped.sources}
    assert not wanted <= {s.citation for s in legacy.sources}  # the soft budget used to drop them
    plan = shaped.answer_plan
    assert [g.label for g in plan.groups] == [f"21 CFR 820.10({x})" for x in "abcde"]
    assert all(plan.source(i).tier == "structural" for g in plan.groups for i in g.items)


def test_d_children_are_selected_as_subordinate_evidence_not_promoted_to_exact():
    pkg = package(RANGE)
    plan_query(RANGE)
    subordinate = [s for s in pkg.sources if s.tier == "structural" and s.citation.count("(") == 2]
    assert subordinate and not any(s.protected for s in subordinate)


# ============================================================ E: comparison


def test_e_comparison_builds_a_two_sided_plan_from_relevant_evidence_only():
    pkg = package(COMPARE)
    plan = pkg.answer_plan
    assert plan.mode == MODE_COMPARISON
    assert [g.label for g in plan.groups] == ["21 CFR 820.10(c)", "21 CFR 820.10(d)"]
    assert {s.citation for s in pkg.sources}.isdisjoint({"21 CFR 820.10(a)", "21 CFR 820.10(b)", "21 CFR 820.10(e)",
                                                         "21 CFR 820.10(b)(1)", "21 CFR 820.10(b)(3)"})
    text = render_package(pkg)
    c, d = idx(pkg, "21 CFR 820.10(c)"), idx(pkg, "21 CFR 820.10(d)")
    assert f"sides: 21 CFR 820.10(c) [{c}]" in text and f"; 21 CFR 820.10(d) [{d}]" in text
    assert "then state how they differ" in text


def test_e_comparing_two_sections_makes_each_section_one_side():
    db = TableDatabase(TABLE + [row("820.30", "", 20, text="Each manufacturer must establish design controls."),
                                row("820.30", "(a)", 21, text="(a) General. Design controls apply to class II devices.")])
    plan = plan_query("Compare 21 CFR 820.10 and 21 CFR 820.30.")
    pipe = RagPipeline(LexicalRetriever(db), None, RagConfig())
    out = pipe.retriever.run_plan(plan, top_k=8)
    pkg = build_package(plan, check_coverage(out.registry), pipe.select(out.registry, pipe.shape_for(plan)), answer_shape=pipe.shape_for(plan))
    assert [g.label for g in pkg.answer_plan.groups] == ["21 CFR 820.10", "21 CFR 820.30"]
    assert sorted(pkg.answer_plan.all_indices()) == sorted(s.index for s in pkg.sources)


def test_e_comparison_that_wanders_into_other_paragraphs_is_flagged():
    pkg = package(COMPARE)
    c, d = idx(pkg, "21 CFR 820.10(c)"), idx(pkg, "21 CFR 820.10(d)")
    answer = (f"21 CFR 820.10(c) applies design and development requirements to class II and class III devices [{c}]. "
              f"21 CFR 820.10(d) applies Clause 7.5.9.2 to devices that support or sustain life, as appropriate [{d}]. "
              "21 CFR 820.10(e) makes non-compliant devices adulterated.")
    assert SCOPE_EXPANSION in codes(validate_answer(answer, pkg, gen()))


# ============================================================ F: qualifiers


def test_f_qualifiers_applicability_and_cross_references_are_extracted_from_the_source_text():
    assert extract_qualifiers(TEXT["(b)(2)"]) == ("if applicable",)
    assert "as appropriate" in extract_qualifiers(TEXT["(b)"]) and "as appropriate" in extract_qualifiers(TEXT["(d)"])
    assert "in addition to" in extract_qualifiers(TEXT["(d)"])
    assert extract_applicability(TEXT["(c)"]).startswith("class II, class III, and those class I devices")
    assert extract_applicability(TEXT["(d)"]).startswith("devices that support or sustain life")
    assert extract_cross_references(TEXT["(b)(2)"]) == ("Clause 7.5.9.1", "part 821")
    assert extract_cross_references(TEXT["(e)"]) == ("section 501(h)",)
    assert "§ 820.7" in extract_cross_references(TEXT["(a)"])
    assert extract_heading(TEXT["(b)"]) == "Applicable regulatory requirements"
    assert extract_heading(TEXT["(b)(1)"]) is None


def test_f_the_prompt_asks_for_every_condition_to_be_kept():
    text = render_package(package(BROAD))
    assert '"if applicable" [5]' in text and '"as appropriate" [3]' in text
    assert "applies only to devices that support or sustain life" in text
    assert "applies only to class II, class III" in text
    assert "never make a conditional requirement unconditional" in text


def test_f_if_applicable_turned_into_must_is_flagged_and_kept_is_not():
    pkg = package(FOCUSED)
    i = idx(pkg, "21 CFR 820.10(b)(2)")
    lost = validate_answer(f"21 CFR 820.10(b)(2) requires that the manufacturer must document traceability procedures under part 821 [{i}].", pkg, gen())
    assert QUALIFIER_DROPPED in codes(lost)
    kept = validate_answer(f"21 CFR 820.10(b)(2) requires documented traceability procedures under part 821 where applicable [{i}].", pkg, gen())
    assert QUALIFIER_DROPPED not in codes(kept)


def test_f_as_appropriate_and_device_applicability_survive_or_are_flagged():
    pkg = package(CONDITIONAL)
    i = idx(pkg, "21 CFR 820.10(d)")
    lost = validate_answer(f"21 CFR 820.10(d) requires manufacturers to comply with Clause 7.5.9.2 in ISO 13485 [{i}].", pkg, gen())
    assert {QUALIFIER_DROPPED, APPLICABILITY_DROPPED} <= codes(lost)
    kept = validate_answer(f"21 CFR 820.10(d) requires manufacturers of devices that support or sustain life to comply with "
                           f"Clause 7.5.9.2 in ISO 13485, as appropriate [{i}].", pkg, gen())
    assert not {QUALIFIER_DROPPED, APPLICABILITY_DROPPED} & codes(kept)


def test_f_a_qualifier_attached_to_the_wrong_requirement_is_caught():
    # live run: the model wrote "part 830 ..., if applicable" - only (b)(2)/part 821 carries it
    pkg = package(BROAD)
    wrong = ("The manufacturer must document a system to assign unique device identification in accordance with part 830 "
             "of this chapter, if applicable, and procedures for traceability under part 821, if applicable [4][5].")
    found = [p for p in validate_answer(wrong, pkg, gen()).problems if p.code == QUALIFIER_MISAPPLIED]
    assert len(found) == 1 and "part 830" in found[0].detail
    right = "Traceability procedures under part 821 are required if applicable [5]."
    assert QUALIFIER_MISAPPLIED not in codes(validate_answer(right, pkg, gen()))


def test_g_a_label_line_marker_is_checked_against_the_text_it_heads():
    # live run: the (b)(3) label introduced the text of (b)(4) and vice versa
    pkg = package(EXHAUSTIVE)
    swapped = ("21 CFR 820.10(b)(3) [6]\nFor Clauses 7.2.3, 8.2.3, and 8.3.3, advisory notices shall be handled in accordance "
               "with the requirements of part 806 of this chapter.\n21 CFR 820.10(b)(4) [7]\nThe manufacturer must notify FDA "
               "of complaints that meet the reporting criteria of part 803 of this chapter.")
    gaps = [p for p in validate_answer(swapped, pkg, gen()).problems if p.code == SYNTHESIS_CITATION_GAP]
    assert {"part 806", "part 803"} <= {p.detail.split(" comes")[0] for p in gaps}
    straight = swapped.replace("[6]", "[X]").replace("[7]", "[6]").replace("[X]", "[7]")
    assert SYNTHESIS_CITATION_GAP not in codes(validate_answer(straight, pkg, gen()))


def test_f_a_qualifier_lost_in_uncited_synthesis_is_still_caught():
    pkg = package(BROAD)
    lead = idx(pkg, "21 CFR 820.10")
    answer = f"Manufacturers must document traceability procedures in accordance with part 821 [{lead}]."
    assert QUALIFIER_DROPPED in codes(validate_answer(answer, pkg, gen()))


# ============================================================ G: citations


def test_g_a_synthesized_statement_whose_citation_does_not_support_it_is_flagged():
    pkg = package(BROAD)
    lead, b4 = idx(pkg, "21 CFR 820.10"), idx(pkg, "21 CFR 820.10(b)(4)")
    one_cite = validate_answer(f"Manufacturers must handle advisory notices under part 806 [{lead}].", pkg, gen())
    gaps = [p for p in one_cite.problems if p.code == SYNTHESIS_CITATION_GAP]
    assert gaps and gaps[0].citation == b4 and f"SOURCE {b4}" in gaps[0].detail
    right = validate_answer(f"Manufacturers must handle advisory notices under part 806 [{b4}].", pkg, gen())
    assert SYNTHESIS_CITATION_GAP not in codes(right)


def test_g_a_combined_sentence_lists_every_source_it_cites():
    pkg = package(BROAD)
    r = validate_answer(SYNTHESIS, pkg, gen())
    cites = build_answer_citations(SYNTHESIS, pkg, r.addressed)
    listed = {i for c in cites for i in c.indices}
    assert set(range(2, 13)) <= listed  # every requirement row the synthesis relied on stays traceable
    assert all(c.label == pkg.source(c.index).citation for c in cites)


def test_g_repeated_statements_are_reported():
    pkg = package(FOCUSED)
    i = idx(pkg, "21 CFR 820.10(b)(2)")
    s = f"The manufacturer must document procedures for traceability under part 821, if applicable [{i}]."
    assert REPEATED_STATEMENT in codes(validate_answer(f"{s} {s.replace('The manufacturer', 'Manufacturers')}", pkg, gen()))


# ============================================================ H: no information loss


@pytest.mark.parametrize("question", [BROAD, EXHAUSTIVE, FOCUSED, RANGE, COMPARE, CONDITIONAL, MULTI])
def test_h_every_source_is_placed_exactly_once(question):
    pkg = package(question)
    placed = pkg.answer_plan.all_indices()
    assert sorted(placed) == sorted(s.index for s in pkg.sources)
    assert len(placed) == len(set(placed))
    assert not pkg.answer_plan.notes or "no place in the plan" not in " ".join(pkg.answer_plan.notes)


def test_h_grouping_keeps_the_underlying_evidence_attached():
    pkg = package(BROAD)
    by_id = {s.index: s.evidence_id for s in pkg.sources}
    b = next(g for g in pkg.answer_plan.groups if g.key == "820.10(b)")
    assert [by_id[i] for i in b.members] == [s.evidence_id for s in pkg.sources if s.citation.startswith("21 CFR 820.10(b)")]
    d = pkg.to_dict()
    assert d["answer_plan"]["groups"][1]["members"] == list(b.members)


def test_h_synthesis_never_removes_evidence_from_the_package():
    assert [s.evidence_id for s in package(BROAD).sources] == [s.evidence_id for s in package(BROAD, shaped=False).sources]
    assert {s.evidence_id for s in package(FOCUSED, shaped=False).sources} <= {s.evidence_id for s in package(FOCUSED).sources}


# ============================================================ I: Stage 11 compatibility


@pytest.mark.parametrize("question", [BROAD, EXHAUSTIVE, FOCUSED, COMPARE, CONDITIONAL, MULTI])
def test_i_the_budget_does_not_depend_on_the_shape(question):
    """Same evidence, with and without a shape: the same allowance. Stage 12
    decides structure; Stage 11 alone decides headroom."""
    shaped = package(question)
    plan = plan_query(question)
    pipe = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), None, RagConfig())
    out = pipe.retriever.run_plan(plan, top_k=8)
    sel = pipe.select(out.registry, pipe.shape_for(plan))
    unshaped = build_package(plan, check_coverage(out.registry), sel)  # identical selection, no shape
    assert shaped.max_new_tokens == unshaped.max_new_tokens
    assert shaped.budget == unshaped.budget


def test_i_no_length_limit_or_brevity_instruction_is_introduced():
    counted = re.compile(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|a few|several)\b"
        r"(?:\s+(?:to|or)\s+\w+)?\s+(?:\w+\s+)?(sentences|words|paragraphs)\b"
        r"|\b(at most|no more than|up to|maximum of|limit of)\s+\d+\s+(sentences|words|tokens|paragraphs)\b"
        r"|\b(concise|concisely|brief|briefly|short answer|keep it short)\b",
        re.IGNORECASE)
    for q in (BROAD, EXHAUSTIVE, FOCUSED, RANGE, COMPARE, CONDITIONAL, MULTI, "What is Part 821?"):
        text = render_package(package(q))
        shaped_part = text[text.index("ANSWER FORMAT:"):]
        assert not counted.search(shaped_part), f"{q}: {counted.search(shaped_part).group(0)}"


def test_i_ceiling_and_truncation_are_unchanged():
    pkg = package(EXHAUSTIVE, budget=GenerationBudget(hard_max_tokens=300))
    assert pkg.max_new_tokens <= 300
    r = validate_answer(SYNTHESIS, pkg, gen(tokens=pkg.max_new_tokens, finished=False))
    assert TRUNCATED in codes(r) and r.truncated


def test_i_the_system_prompt_is_unchanged():
    # hashed into the pipeline fingerprint and shared with Stage 6 training data
    assert "Use the minimum amount of text a complete and accurate answer needs" in GROUNDED_SYSTEM_PROMPT
    assert "synthesized overview" not in GROUNDED_SYSTEM_PROMPT


# ============================================================ J: legacy rendering and the pipeline


def test_j_without_a_shape_the_package_renders_exactly_as_before():
    """Stage 6 training examples and answer_shape="off" build packages with no
    plan; their prompt must not change by a byte."""
    plain = package(BROAD, shaped=False)
    assert plain.answer_plan is None and "answer_plan" not in plain.to_dict()
    text = render_package(plain)
    assert "synthesized overview" not in text
    assert text.endswith("ANSWER FORMAT: plain sentences stating what the requested provision requires, taken from its EXACT "
                         "source, each ending with the source number in brackets. Write as much as the provision needs and no "
                         "more: briefly when its text is brief, at greater length when it carries conditions, exceptions or "
                         "limits on its scope.")


def test_j_the_pipeline_sends_the_shape_and_records_it():
    g = ScriptedGenerator(SYNTHESIS)
    out = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), g, RagConfig()).answer(BROAD)
    user = g.calls[0]["messages"][1]["content"]
    assert "answer shape: synthesized overview" in user and "(b) Applicable regulatory requirements [3]" in user
    assert out.metadata["answer_shape"]["mode"] == MODE_SYNTHESIS
    assert out.metadata["generation"]["answer_plan"]["groups"]
    assert "shape" in out.metadata["validation"]["initial"]
    assert out.diagnostics()["answer_shape"]["scope"] == SCOPE_SECTION


def test_j_answer_shape_off_restores_the_previous_prompt():
    g = ScriptedGenerator(SYNTHESIS)
    out = RagPipeline(LexicalRetriever(TableDatabase(TABLE)), g, RagConfig(answer_shape="off")).answer(BROAD)
    assert "synthesized overview" not in g.calls[0]["messages"][1]["content"]
    assert out.metadata["answer_shape"] is None and "shape" not in out.metadata["validation"]["initial"]


def test_j_invalid_setting_is_rejected():
    with pytest.raises(ValueError):
        RagConfig(answer_shape="short")


def test_roles_cover_the_whole_section():
    plan = package(BROAD).answer_plan
    roles = {s.citation: s.role for s in plan.sources}
    assert roles["21 CFR 820.10"] == ROLE_LEAD_IN
    assert roles["21 CFR 820.10(a)"] == ROLE_REQUIREMENT
    assert roles["21 CFR 820.10(c)(1)"] == ROLE_SUBORDINATE
    assert package(FOCUSED).answer_plan.source(3) is None or package(FOCUSED).answer_plan.source(3).role in (ROLE_CONTEXT, ROLE_RELATED)
