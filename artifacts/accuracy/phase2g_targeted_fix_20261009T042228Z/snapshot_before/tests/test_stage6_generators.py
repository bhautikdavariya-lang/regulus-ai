"""Stage 6: evidence-relation logic, the grounded prompt contract, and the
multi-provision / range / partial generators.

No database and no model: a small in-memory Corpus stands in for the eCFR
tables, so every assertion here is deterministic.
"""

import pytest

from regulus.rag.generation import GROUNDED_SYSTEM_PROMPT, SHAPE_DOCKET, SHAPE_PER_PROVISION, SHAPE_SINGLE
from regulus.retrieval.evidence import TIER_EXACT, TIER_STRUCTURAL, TIER_SUPPORTING
from regulus.stage6.generators import (
    FAMILY,
    children_of,
    find_absent_child,
    gen_multi_provision,
    gen_partial_provision,
    gen_range_provision,
    numbered_groups,
    present_paragraph_paths,
)
from regulus.stage6.prompting import _relation, example_package, to_grounded_messages
from regulus.training.config import TrainingConfig
from regulus.training.models import ContextItem, TrainingExample
from regulus.training.sources import Corpus, Part, Record, Section

CFG = TrainingConfig(version="test", target_examples=100)


# ------------------------------------------------------------------ fixtures


def rec(section="820.10", para="(b)(1)", ordinal=3, text=None, part=None):
    part = part or section.split(".")[0]
    return Record(
        section=section, paragraph=para, path_ordinal=0, ordinal=ordinal, heading="Quality management system",
        text=text or f"({para.strip('()')}) The manufacturer must document the {para} obligation in accordance with this chapter.",
        url=f"https://www.ecfr.gov/current/title-21/section-{section}", part=part, subchapter="H",
    )


def section(number="820.10", records=None, part=None):
    part = part or number.split(".")[0]
    s = Section(number=number, heading="Quality management system", part=part, subpart_id=None, is_reserved=False, sort_order=1)
    s.records = records if records is not None else []
    return s


def corpus(sections):
    by_number = {s.number: s for s in sections}
    parts = {s.part: Part(number=s.part, title=f"Part {s.part}", subchapter="H", url=None, is_reserved=False) for s in sections}
    return Corpus(
        snapshot={"ecfr_snapshot_date": "2026-09-03"}, subchapters={}, parts=parts, subparts={}, sections=by_number,
        definitions=[], cross_refs=[], guidance=[], all_part_numbers=set(parts), all_section_numbers=set(by_number), all_dockets=set(),
    )


def item(section_no="820.10", paragraph="(b)(1)", part="820", source_type="ecfr", docket=None, title=None):
    return ContextItem(
        source_type=source_type,
        citation=(f"21 CFR {section_no}{paragraph}" if source_type == "ecfr" else f"FDA Guidance: {title or 'Some Guidance'}"),
        text="body text", url="https://example.invalid/x", part=part, section=section_no if source_type == "ecfr" else None,
        paragraph=paragraph if source_type == "ecfr" else None, heading="Heading", document_title=title, docket_number=docket,
        source_key=(f"ecfr:{section_no}:{paragraph}:0" if source_type == "ecfr" else "fda_guidance:https://example.invalid/x#0"),
    )


FULL_SECTION = section("820.10", [
    rec("820.10", "", 0, text="A manufacturer subject to this part must:"),
    rec("820.10", "(b)", 2, text="(b) Applicable regulatory requirements. Comply, as appropriate, with the other applicable requirements."),
    rec("820.10", "(b)(1)", 3),
    rec("820.10", "(b)(2)", 4),
    rec("820.10", "(b)(3)", 5),
    rec("820.10", "(b)(4)", 6),
    rec("820.10", "(c)", 7),
])


# ------------------------------------------------- _relation: identity rules


def test_requested_paragraph_relations():
    """Requested (b)(2): itself exact, parent and child structural, sibling neither."""
    req = ("820.10", "(b)(2)", "820")
    assert _relation(*req, item("820.10", "(b)(2)")) == "exact"
    assert _relation(*req, item("820.10", "(b)")) == "parent"
    assert _relation(*req, item("820.10", "")) == "parent"            # the section row
    assert _relation(*req, item("820.10", "(b)(2)(i)")) == "child"
    assert _relation(*req, item("820.10", "(b)(1)")) == "sibling"
    assert _relation(*req, item("820.10", "(b)(20)")) == "sibling"    # prefix must not fool it
    assert _relation(*req, item("820.30", "(b)(2)")) == "none"        # different section


def test_relation_tiers_follow_from_the_rules():
    """Sibling and unrelated rows must not become exact or structural evidence."""
    req = ("820.10", "(b)(2)", "820")
    tiers = {rel: rel for rel in ("exact", "parent", "child", "sibling", "none")}
    assert tiers[_relation(*req, item("820.10", "(b)(2)"))] == "exact"
    assert _relation(*req, item("820.10", "(b)(1)")) not in ("exact", "parent", "child")
    assert _relation(*req, item("820.30", "(a)")) not in ("exact", "parent", "child")


def test_section_level_requirement_matches_its_rows_only():
    req = ("820.10", "", "820")
    assert _relation(*req, item("820.10", "(b)(2)")) == "exact"
    assert _relation(*req, item("820.10", "")) == "exact"
    assert _relation(*req, item("820.30", "(a)")) == "none"


def test_part_level_requirement_matches_rows_of_that_part_only():
    req = (None, "", "820")
    assert _relation(*req, item("820.30", "(a)", part="820")) == "exact"
    assert _relation(*req, item("801.109", "(a)", part="801")) == "none"


def test_guidance_context_is_never_a_cfr_relation():
    req = ("820.10", "(b)(2)", "820")
    assert _relation(*req, item(source_type="fda_guidance", docket="FDA-2016-D-2565", title="QMS")) == "none"


# ------------------------------------------------- package / prompt contract


def example(question, context, answer="21 CFR 820.10(b)(2): body [1].", citations=("21 CFR 820.10(b)(2)",), category="multi_provision"):
    return TrainingExample(
        type="regulatory_qa", category=category, question=question, context=list(context), answer=answer,
        citations=list(citations), grounded=True, generator="test", group="820.10", snapshot_date="2026-09-03",
        extra={"family": FAMILY, "prompt_format": "grounded"},
    )


def test_package_assigns_tiers_from_identity_not_from_order():
    ex = example("What do 21 CFR 820.10(b)(2) and 21 CFR 820.10(b)(4) require?",
                 [item("820.10", "(b)(2)"), item("820.10", "(b)(4)"), item("820.10", "(b)"), item("820.10", "(b)(1)")])
    pkg = example_package(ex)
    tiers = [(s.citation, s.tier, s.requirement_ids) for s in pkg.sources]
    assert tiers[0] == ("21 CFR 820.10(b)(2)", TIER_EXACT, ("r1",))
    assert tiers[1] == ("21 CFR 820.10(b)(4)", TIER_EXACT, ("r2",))
    assert tiers[2] == ("21 CFR 820.10(b)", TIER_STRUCTURAL, ("r1", "r2"))
    assert tiers[3] == ("21 CFR 820.10(b)(1)", TIER_SUPPORTING, ())  # sibling of both, evidence for neither
    assert pkg.satisfied_ids == ("r1", "r2") and pkg.missing_labels == () and pkg.shape == SHAPE_PER_PROVISION


def test_package_marks_a_requested_provision_with_no_context_as_missing():
    ex = example("What do 21 CFR 820.10(b)(2) and 21 CFR 820.10(b)(9) require?", [item("820.10", "(b)(2)")])
    pkg = example_package(ex)
    assert pkg.satisfied_ids == ("r1",) and pkg.missing_labels == ("21 CFR 820.10(b)(9)",)
    assert pkg.coverage_state == "INCOMPLETE"


def test_docket_question_marks_the_matching_guidance_exact():
    ex = example("Summarise FDA-2016-D-2565", [item(source_type="fda_guidance", docket="FDA-2016-D-2565", title="QMS"),
                                                item(source_type="fda_guidance", docket="FDA-2020-D-1111", title="Other")],
                 answer="The guidance says x [1].", citations=("FDA Guidance: QMS",))
    pkg = example_package(ex)
    assert pkg.shape == SHAPE_DOCKET
    assert (pkg.sources[0].tier, pkg.sources[0].is_docket) == (TIER_EXACT, True)
    assert (pkg.sources[1].tier, pkg.sources[1].is_docket) == (TIER_SUPPORTING, False)


def test_training_messages_use_the_inference_prompt_contract():
    ex = example("What do 21 CFR 820.10(b)(2) and 21 CFR 820.10(b)(4) require?",
                 [item("820.10", "(b)(2)"), item("820.10", "(b)(4)"), item("820.10", "(b)")])
    msgs = to_grounded_messages(ex)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    assert msgs[0]["content"] == GROUNDED_SYSTEM_PROMPT
    user = msgs[1]["content"]
    assert "REQUESTED PROVISIONS:\nr1: 21 CFR 820.10(b)(2)\nr2: 21 CFR 820.10(b)(4)" in user
    assert "Tier: EXACT (authoritative text of r1)" in user
    assert "Tier: STRUCTURAL (parent or child of r1, r2; context only, not the requested text)" in user
    assert "ANSWER FORMAT:" in user
    assert msgs[2]["content"] == ex.answer


def test_single_provision_example_uses_the_single_shape():
    ex = example("What does 21 CFR 820.10(b)(2) require?", [item("820.10", "(b)(2)")])
    assert example_package(ex).shape == SHAPE_SINGLE


# ------------------------------------------------------ corpus-level helpers


def test_numbered_groups_finds_consecutive_children_only():
    s = section("820.10", [rec("820.10", "(b)", 2), rec("820.10", "(b)(1)", 3), rec("820.10", "(b)(2)", 4), rec("820.10", "(b)(4)", 6)])
    groups = list(numbered_groups(s, CFG))
    assert len(groups) == 1
    parent, prec, run = groups[0]
    assert parent == "(b)" and prec is not None
    assert [r.paragraph for r in run] == ["(b)(1)", "(b)(2)"]  # stops at the gap, (b)(4) is not reached


def test_absent_child_is_proven_against_the_section_records():
    s = section("820.10", [rec("820.10", "(b)(1)", 3), rec("820.10", "(b)(2)", 4)])
    assert present_paragraph_paths(s) == {"(b)(1)", "(b)(2)"}
    assert children_of(s, "(b)") == {1: "(b)(1)", 2: "(b)(2)"}
    assert find_absent_child(s, "(b)") == (3, "(b)(3)")
    # a section whose next numbers DO exist must not offer them as absent
    s2 = section("820.10", [rec("820.10", "(b)(1)", 3), rec("820.10", "(b)(2)", 4), rec("820.10", "(b)(3)", 5)])
    number, path = find_absent_child(s2, "(b)")
    assert path not in present_paragraph_paths(s2) and number == 4
    assert find_absent_child(section("820.10", []), "(b)") is None


# --------------------------------------------------------------- generators


def test_multi_provision_examples_quote_every_requested_provision():
    out = gen_multi_provision(corpus([FULL_SECTION]), CFG)
    assert out, "expected at least one example"
    ex = out[0]
    assert ex.category == "multi_provision" and ex.group == "820.10"
    assert ex.extra["family"] == FAMILY and ex.extra["prompt_format"] == "grounded"
    assert len(ex.citations) >= 2
    lines = [l for l in ex.answer.splitlines() if l.strip()]
    assert len(lines) == len(ex.citations)
    for i, cit in enumerate(ex.citations, start=1):
        assert lines[i - 1].startswith(cit + ":") and f"[{i}]" in lines[i - 1]
    pkg = example_package(ex)
    assert len(pkg.satisfied_ids) == len(ex.citations) and pkg.missing_labels == ()


def test_range_examples_cover_the_whole_run():
    out = gen_range_provision(corpus([FULL_SECTION]), CFG)
    assert out
    ex = out[0]
    assert ex.category == "range_provision" and len(ex.citations) >= 3
    assert example_package(ex).missing_labels == ()


def test_partial_examples_record_and_prove_the_absent_identifier():
    out = gen_partial_provision(corpus([FULL_SECTION]), CFG)
    assert out
    ex = out[0]
    meta = ex.extra["missing_provision"]
    for key in ("requested_identifier", "section", "parent_paragraph", "requested_child_number", "absent_verified", "snapshot_date"):
        assert meta.get(key) is not None, key
    assert meta["absent_verified"] is True and meta["snapshot_date"] == "2026-09-03"
    assert meta["section"] == "820.10" and meta["parent_paragraph"] == "(b)"
    # the identifier it calls absent really is absent from the section
    path = f"{meta['parent_paragraph']}({meta['requested_child_number']})"
    assert path not in present_paragraph_paths(FULL_SECTION)
    assert meta["requested_identifier"] == f"21 CFR 820.10{path}"
    assert meta["parent_children_present"] == ["(b)(1)", "(b)(2)", "(b)(3)", "(b)(4)"]
    # the answer states the absence rather than inventing content for it
    assert f"{meta['requested_identifier']}: not found in the available eCFR data." in ex.answer
    assert meta["requested_identifier"] not in ex.citations
    pkg = example_package(ex)
    assert pkg.missing_labels == (meta["requested_identifier"],)


def test_generators_are_deterministic():
    c1, c2 = corpus([FULL_SECTION]), corpus([FULL_SECTION])
    for gen in (gen_multi_provision, gen_range_provision, gen_partial_provision):
        a, b = gen(c1, CFG), gen(c2, CFG)
        assert [(e.id, e.question, e.answer) for e in a] == [(e.id, e.question, e.answer) for e in b]


def test_every_example_is_grouped_by_its_section_for_split_separation():
    c = corpus([FULL_SECTION, section("801.109", [rec("801.109", "(a)(1)", 1, part="801"), rec("801.109", "(a)(2)", 2, part="801")])])
    for gen in (gen_multi_provision, gen_range_provision, gen_partial_provision):
        for ex in gen(c, CFG):
            assert ex.group in {"820.10", "801.109"}
            assert all(cit.startswith(f"21 CFR {ex.group}") for cit in ex.citations)
