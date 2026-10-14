"""Stage 1: multi-reference parsing, range/list expansion and QueryPlan.

No database, no model. The parser answers "what did the user ask for?";
existence checks belong to later stages, so nonexistent provisions must
parse like any other.
"""

import pytest

from regulus.planning import QueryPlan, Requirement, plan_query
from regulus.retrieval import QueryType, classify, parse_cfr_reference, parse_cfr_references
from regulus.retrieval.references import CfrReference, MAX_RANGE_EXPANSION, scan_references


def labels(text: str) -> list[str]:
    return [r.label for r in parse_cfr_references(text)]


# ---------------------------------------------------------------- single


@pytest.mark.parametrize(
    "text",
    [
        "21 CFR 820.10(b)(1)",
        "§ 820.10(b)(1)",
        "section 820.10(b)(1)",
        "820.10(b)(1)",
        "What does 21 CFR 820.10(b)(1) require?",
        "What does 820.10(b)(1) require?",
        "21 C.F.R. § 820.10 (b) (1)",
        "Section 820.10(b)(1) of Title 21",
    ],
)
def test_single_reference_forms_normalise_to_one_canonical_reference(text):
    refs = parse_cfr_references(text)
    assert len(refs) == 1, refs
    ref = refs[0]
    assert (ref.title, ref.part, ref.section, ref.paragraph_path) == ("21", "820", "820.10", "(b)(1)")
    assert ref.canonical == "21 CFR 820.10(b)(1)"
    assert ref.raw  # the original text is kept


def test_equivalent_forms_have_equal_keys():
    keys = {parse_cfr_references(t)[0].key for t in ("21 CFR 820.10(b)(1)", "§ 820.10(b)(1)", "820.10(b)(1)")}
    assert len(keys) == 1


def test_nonexistent_provision_parses_without_any_existence_check():
    refs = parse_cfr_references("What does 21 CFR 820.999 require?")
    assert [r.section for r in refs] == ["820.999"]
    assert labels("Explain 820.10(b)(9).") == ["21 CFR 820.10(b)(9)"]


@pytest.mark.parametrize(
    "text",
    [
        "What does 21 CFR 820.10(b)(2) require?",
        "What does 820.10(b)(2) require?",
        "Under 820.10(b)(2), when must FDA be notified?",
        "Explain 820.10(b)(2) in plain English.",
    ],
)
def test_natural_language_embedding(text):
    assert labels(text) == ["21 CFR 820.10(b)(2)"]


# ---------------------------------------------------------------- ranges

FOUR = ["21 CFR 820.10(b)(1)", "21 CFR 820.10(b)(2)", "21 CFR 820.10(b)(3)", "21 CFR 820.10(b)(4)"]


@pytest.mark.parametrize(
    "text",
    [
        "820.10(b)(1) through (b)(4)",
        "820.10(b)(1)-(b)(4)",
        "820.10(b)(1)–(b)(4)",
        "820.10(b)(1) — (b)(4)",
        "820.10(b)(1) to (b)(4)",
        "820.10(b)(1) thru (b)(4)",
        "§ 820.10(b)(1) through § 820.10(b)(4)",
        "21 CFR 820.10(b)(1) through 820.10(b)(4)",
        "§820.10(b)(1)-(b)(4)",
        "What are the requirements in 820.10(b)(1) through (b)(4)?",
        "List all of the specific requirements in 21 CFR § 820.10(b)(1) through (b)(4).",
        "820.10(b)(1)-(4)",
    ],
)
def test_range_expands_to_atomic_references(text):
    assert labels(text) == FOUR


def test_range_expansion_is_recorded_for_observability():
    scan = scan_references("820.10(b)(1) through (b)(4)")
    assert len(scan.mentions) == 2
    assert len(scan.ranges) == 1 and scan.ranges[0].expanded and scan.ranges[0].count == 4
    plan = plan_query("820.10(b)(1) through (b)(4)")
    # the abbreviated end point is a continuation of the first mention; the inner two are expansions
    assert [r.origin for r in plan.requirements] == ["explicit", "range_expansion", "range_expansion", "continuation"]
    plan = plan_query("§ 820.10(b)(1) through § 820.10(b)(4)")
    assert [r.origin for r in plan.requirements] == ["explicit", "range_expansion", "range_expansion", "explicit"]


def test_letter_and_roman_ranges():
    assert labels("820.30(a) through (d)") == [f"21 CFR 820.30({c})" for c in "abcd"]
    assert labels("801.109(a)(1)(i) through (iv)") == [f"21 CFR 801.109(a)(1)({r})" for r in ("i", "ii", "iii", "iv")]
    # at depth 1 "(i)" is the letter i, not roman one
    assert labels("820.30(g) through (i)") == ["21 CFR 820.30(g)", "21 CFR 820.30(h)", "21 CFR 820.30(i)"]


def test_range_across_sections_keeps_both_endpoints_unexpanded():
    scan = scan_references("820.10 through 820.30")
    assert [r.label for r in scan.references] == ["21 CFR 820.10", "21 CFR 820.30"]
    assert scan.ranges and not scan.ranges[0].expanded
    assert any("section-level" in n or "not expanded" in n for n in scan.notes)


def test_reversed_range_keeps_endpoints():
    assert labels("820.10(b)(4) through (b)(1)") == ["21 CFR 820.10(b)(4)", "21 CFR 820.10(b)(1)"]


def test_oversized_range_keeps_endpoints():
    end = MAX_RANGE_EXPANSION + 5
    scan = scan_references(f"820.10(b)(1) through (b)({end})")
    assert [r.label for r in scan.references] == ["21 CFR 820.10(b)(1)", f"21 CFR 820.10(b)({end})"]
    assert not scan.ranges[0].expanded


# ---------------------------------------------------------------- lists


@pytest.mark.parametrize(
    "text,expected",
    [
        ("820.10(b)(1), (b)(2), (b)(3)", FOUR[:3]),
        ("820.10(b)(1), (b)(3), (b)(4)", [FOUR[0], FOUR[2], FOUR[3]]),
        ("820.10(b)(1) and (b)(4)", [FOUR[0], FOUR[3]]),
        ("§ 820.10(b)(1), § 820.10(b)(2), and § 820.10(b)(4)", [FOUR[0], FOUR[1], FOUR[3]]),
        ("820.10(b)(1), (b)(2), and (b)(4)", [FOUR[0], FOUR[1], FOUR[3]]),
        ("820.10(b)(1) or (b)(2)", FOUR[:2]),
        ("820.10(b)(1) and (2)", FOUR[:2]),  # shorter fragment inherits the parent path
        ("What are the requirements of 21 CFR § 820.10(b)(1), (b)(2), and (b)(3)?", FOUR[:3]),
    ],
)
def test_lists_preserve_order(text, expected):
    assert labels(text) == expected


def test_list_order_is_textual_not_pattern_priority():
    # the old parser preferred "21 CFR" matches over "§" matches regardless of position
    assert labels("§ 820.30(a) and 21 CFR 820.10(b)") == ["21 CFR 820.30(a)", "21 CFR 820.10(b)"]


# ---------------------------------------------------------------- mixed


def test_multiple_complete_references():
    assert labels("What does 21 CFR 820.10(b)(1) and 21 CFR 820.10(b)(4) require?") == [FOUR[0], FOUR[3]]


def test_continuation_then_full_reference():
    assert labels("820.10(b)(1), (b)(2), and 820.10(b)(4)") == [FOUR[0], FOUR[1], FOUR[3]]


def test_references_to_different_sections():
    assert labels("Compare 820.10 with 820.20") == ["21 CFR 820.10", "21 CFR 820.20"]
    assert labels("What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?") == ["21 CFR 820.10(b)(2)", "21 CFR 820.999"]
    assert labels("Compare § 820.10(b)(2) and § 820.10(b)(4).") == [FOUR[1], FOUR[3]]


def test_continuation_does_not_cross_a_part_reference():
    # "(b)" after "part 820" cannot inherit a section
    assert labels("part 820 (b)") == ["21 CFR part 820"]


def test_part_and_section_and_paragraph_levels():
    refs = parse_cfr_references("21 CFR Part 820, 21 CFR 820.10 and 21 CFR 820.10(b)")
    assert [r.level for r in refs] == ["part", "section", "paragraph"]


def test_other_title_is_kept():
    assert labels("42 CFR 493.1 and 21 CFR 820.10") == ["42 CFR 493.1", "21 CFR 820.10"]


# ---------------------------------------------------------------- duplicates


def test_duplicate_mentions_collapse_to_one_requirement():
    assert labels("21 CFR 820.10(b)(1) ... as § 820.10(b)(1) says, 820.10(b)(1) requires") == [FOUR[0]]
    scan = scan_references("820.10(b)(1) and 820.10(b)(1)")
    assert len(scan.mentions) == 2 and len(scan.references) == 1
    assert any("duplicate" in n for n in scan.notes)


def test_range_and_member_together_do_not_duplicate():
    assert labels("820.10(b)(1) through (b)(4), especially (b)(3)") == FOUR


def test_parent_and_children_are_distinct():
    assert labels("820.10(b), (b)(1), and (b)(2)") == ["21 CFR 820.10(b)", FOUR[0], FOUR[1]]


def test_continuation_only_follows_list_connectors():
    # ordinary words between the reference and a fragment break the chain (safety over recall)
    assert labels("820.10(b) and its items (b)(1) and (b)(2)") == ["21 CFR 820.10(b)"]


def test_punctuation_variants_do_not_duplicate():
    assert labels("820.10(b)(1); 820.10 (b) (1), and 820.10(b)(1).") == [FOUR[0]]


# ---------------------------------------------------------------- safety


@pytest.mark.parametrize(
    "text",
    [
        "What is the purpose of a quality management system?",
        "How many records are required?",
        "The regulation requires 20 records",
        "in 2024 the rule changed",
        "the dose is 2.5 mg twice a day",
        "a concentration of 0.5 percent",
        "pH 6.5 to 7.5",
        "version 3.1 of the software",
        "ISO 13485 clause 7.5.8",
        "ISO 13485 Clause 7.5",
        "costs $12.50 per unit",
        "a 4.2% failure rate",
        "1.2.3 is a version string",
        "an increase of 1.5 fold",
        "within 2.5 hours",
        "Phase 3.2 begins",
        "Fig. 2.1 shows the flow",
        "",
        "   ",
    ],
)
def test_non_references_are_not_parsed(text):
    assert parse_cfr_references(text) == ()
    assert parse_cfr_reference(text) is None


def test_paragraph_fragment_without_a_preceding_reference_is_ignored():
    assert parse_cfr_references("(b)(1) requires a system") == ()


def test_paragraph_fragment_after_ordinary_words_is_not_a_continuation():
    assert labels("What does 820.10(b)(1) require (a) documentation") == [FOUR[0]]


def test_part_word_before_a_bare_decimal_is_not_a_reference():
    # "part 2.5" is not a CFR form; with paragraph tokens the structure wins
    assert parse_cfr_references("part 2.5 of the plan") == ()
    assert labels("part 820.30(b) applies") == ["21 CFR 820.30(b)"]


# ---------------------------------------------------------------- compatibility


def test_parse_cfr_reference_returns_the_first_reference_in_text_order():
    ref = parse_cfr_reference("820.10(b)(1) through (b)(4)")
    assert ref == parse_cfr_references("820.10(b)(1) through (b)(4)")[0]
    assert ref.label == FOUR[0]


def test_classify_exposes_all_references_and_keeps_first_as_cfr():
    c = classify("What are the requirements of 21 CFR § 820.10(b)(1) and § 820.10(b)(2)?")
    assert c.query_type is QueryType.EXACT_CFR
    assert c.cfr.label == FOUR[0]
    assert [r.label for r in c.references] == FOUR[:2]


def test_classify_bare_paragraph_reference_is_exact_cfr():
    c = classify("What does 820.10(b)(1) require?")
    assert c.query_type is QueryType.EXACT_CFR and c.cfr.paragraph_path == "(b)(1)"


def test_classify_general_has_no_references():
    c = classify("What is the purpose of a quality management system?")
    assert c.query_type is QueryType.GENERAL_REGULATORY_SEARCH and c.references == ()


def test_cfr_reference_is_frozen_and_hashable():
    ref = CfrReference(title="21", part="820", section="820.10", paragraph_path="(b)(1)", raw="x")
    with pytest.raises(Exception):
        ref.title = "42"  # type: ignore[misc]
    assert hash(ref)


# ---------------------------------------------------------------- QueryPlan


def test_plan_single_provision():
    plan = plan_query("What does 21 CFR 820.10(b)(2) require?")
    assert isinstance(plan, QueryPlan)
    assert plan.kind == "single_provision"
    assert plan.query_type is QueryType.EXACT_CFR
    assert len(plan.requirements) == 1
    r = plan.requirements[0]
    assert isinstance(r, Requirement)
    assert r.id == "r1" and r.order == 1
    assert r.canonical == "21 CFR 820.10(b)(2)"
    assert (r.section, r.paragraph_path, r.part, r.level) == ("820.10", "(b)(2)", "820", "paragraph")
    assert r.raw == "21 CFR 820.10(b)(2)"
    assert r.origin == "explicit"


def test_plan_range():
    plan = plan_query("What does 21 CFR 820.10(b)(1) through (b)(4) require?")
    assert plan.kind == "range"
    assert [r.id for r in plan.requirements] == ["r1", "r2", "r3", "r4"]
    assert [r.canonical for r in plan.requirements] == FOUR
    assert [r.origin for r in plan.requirements] == ["explicit", "range_expansion", "range_expansion", "continuation"]
    # expanded requirements keep the range text they came from
    assert plan.requirements[1].raw == "21 CFR 820.10(b)(1) through (b)(4)"
    assert plan.requirements[0].raw == "21 CFR 820.10(b)(1)"
    assert plan.scan.ranges[0].count == 4


def test_plan_list_is_multi_provision():
    plan = plan_query("820.10(b)(1), (b)(3), (b)(4)")
    assert plan.kind == "multi_provision"
    assert [r.canonical for r in plan.requirements] == [FOUR[0], FOUR[2], FOUR[3]]
    assert [r.origin for r in plan.requirements] == ["explicit", "continuation", "continuation"]


def test_plan_multiple_reference_across_sections():
    plan = plan_query("Compare 820.10 with 820.20")
    assert plan.kind == "multiple_reference"
    assert [r.canonical for r in plan.requirements] == ["21 CFR 820.10", "21 CFR 820.20"]


def test_plan_general_and_unknown():
    assert plan_query("What is the purpose of a quality management system?").kind == "general"
    assert plan_query("What is the purpose of a quality management system?").requirements == ()
    assert plan_query("   ").kind == "unknown"
    assert plan_query("   ").query_type is QueryType.EMPTY


def test_plan_keeps_docket_and_guidance_flags():
    plan = plan_query("summarise the guidance in FDA-2016-D-2565 and 21 CFR 820.10")
    assert plan.docket == "FDA-2016-D-2565" and plan.guidance_requested
    assert plan.kind == "single_provision"


def test_plan_normalises_whitespace_but_keeps_the_original():
    q = "  What does   21 CFR 820.10(b)(1)\trequire? "
    plan = plan_query(q)
    assert plan.question == q
    assert plan.normalized_question == "What does 21 CFR 820.10(b)(1) require?"


def test_plan_is_frozen_and_serialisable():
    plan = plan_query("820.10(b)(1) through (b)(4)")
    with pytest.raises(Exception):
        plan.kind = "general"  # type: ignore[misc]
    d = plan.to_dict()
    assert d["kind"] == "range"
    assert [r["canonical"] for r in d["requirements"]] == FOUR
    assert d["scan"]["ranges"][0]["count"] == 4
    assert isinstance(d["scan"]["mentions"], list) and d["scan"]["mentions"][0]["form"]


def test_plan_explain_lists_the_pipeline_of_understanding():
    text = plan_query("What does 21 CFR 820.10(b)(1) through (b)(4) require?").explain()
    for needle in ("question:", "mentions:", "ranges:", "requirements:", "r1", "r4", "range"):
        assert needle in text
