"""Stage 11: model-free, database-free tests of the training-data pipeline.

A small in-memory Corpus stands in for the database; every generator,
the de-duplication, benchmark exclusion, splitting, validation and the
determinism of the whole build are exercised on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regulus.training import ContextItem, ExampleError, TrainingConfig, TrainingConfigError, TrainingExample, build_examples, load_training_config, read_jsonl, to_messages, validate_dataset, write_jsonl
from regulus.training.config import CATEGORIES, STAGE11_CATEGORIES
from regulus.training.dedup import deduplicate, exclude_benchmark, select_balanced
from regulus.training.generators import definition_answer, gen_cfr_vs_guidance, gen_citation, gen_definitions, gen_direct_cfr, gen_guidance, gen_multi_context, gen_relationships, gen_section_paragraph, recommendation_sentence, scope_sentence
from regulus.training.models import make_id
from regulus.training.negatives import fake_dockets, fake_part_numbers, fake_section_numbers, gen_abstention, is_refusal
from regulus.training.pipeline import dataset_paths
from regulus.training.sources import Corpus, CrossRef, Definition, GuidanceChunk, GuidanceDoc, Part, Record, Section, Subchapter, Subpart
from regulus.training.splits import assign_splits, group_overlap, split_for_group
from regulus.training.text import heading_topic, identifiers, is_clean_paragraph, leadin, normalise_question, strip_label
from regulus.training.validate import check_leakage, scan_secrets, ValidationReport

URL = "https://www.ecfr.gov/current/title-21/section-"
LONG = " The manufacturer must keep records of this activity and make them available for inspection on request."


def rec(section, para, ordinal, text, heading, part, sub="H", path_ordinal=0):
    return Record(section, para, path_ordinal, ordinal, heading, text, URL + section, part, sub)


def make_corpus() -> Corpus:
    subchapters = {"A": Subchapter("A", "General", "1 - 99"), "H": Subchapter("H", "Medical Devices", "800 - 898")}
    parts = {
        "11": Part("11", "Electronic Records; Electronic Signatures", "A", "https://www.ecfr.gov/part-11", False),
        "820": Part("820", "Quality Management System Regulation", "H", "https://www.ecfr.gov/part-820", False),
        "83-98": Part("83-98", None, "A", None, True),
    }
    subparts = {
        "sp11a": Subpart("sp11a", "11", "A", "General Provisions", 0),
        "sp11b": Subpart("sp11b", "11", "B", "Electronic Records", 1),
        "sp820a": Subpart("sp820a", "820", "A", "General Provisions", 0),
    }
    s = {}
    s["11.1"] = Section("11.1", "Scope.", "11", "sp11a", False, 0, [
        rec("11.1", "(a)", 0, "(a) The regulations in this part set forth the criteria under which the agency considers electronic records and electronic signatures to be trustworthy, reliable, and generally equivalent to paper records.", "Scope.", "11", "A"),
        rec("11.1", "(b)", 1, "(b) This part applies to records in electronic form that are created, modified, maintained, archived, retrieved, or transmitted under any records requirements set forth in agency regulations.", "Scope.", "11", "A"),
    ])
    s["11.3"] = Section("11.3", "Definitions.", "11", "sp11a", False, 1, [
        rec("11.3", "(a)", 0, "(a) The definitions and interpretations of terms contained in section 201 of the act apply to those terms when used in this part.", "Definitions.", "11", "A"),
        rec("11.3", "(b)(6)", 1, "(6) Electronic record means any combination of text, graphics, data, audio, pictorial, or other information representation in digital form that is created, modified, maintained, archived, retrieved, or distributed by a computer system.", "Definitions.", "11", "A"),
        rec("11.3", "(b)(4)", 2, "(4) Closed system means an environment in which system access is controlled by persons who are responsible for the content of electronic records that are on the system.", "Definitions.", "11", "A"),
    ])
    s["11.10"] = Section("11.10", "Controls for closed systems.", "11", "sp11b", False, 2, [
        rec("11.10", "", 0, "Persons who use closed systems to create, modify, maintain, or transmit electronic records shall employ procedures and controls designed to ensure the authenticity, integrity, and, when appropriate, the confidentiality of electronic records.", "Controls for closed systems.", "11", "A"),
        rec("11.10", "(a)", 1, "(a) Validation of systems to ensure accuracy, reliability, consistent intended performance, and the ability to discern invalid or altered records." + LONG, "Controls for closed systems.", "11", "A"),
    ])
    s["820.1"] = Section("820.1", "Scope.", "820", "sp820a", False, 0, [
        rec("820.1", "(a)", 0, "(a) Applicability. Current good manufacturing practice requirements are set forth in this quality management system regulation. The requirements in this part govern the methods used in the design and manufacture of finished devices.", "Scope.", "820"),
    ])
    s["820.3"] = Section("820.3", "Definitions.", "820", "sp820a", False, 1, [
        rec("820.3", "(a)", 0, "(a) Act means the Federal Food, Drug, and Cosmetic Act, as amended by later legislation of the Congress.", "Definitions.", "820"),
        rec("820.3", "(b)", 1, "(b) The term component means any raw material, substance, piece, part, software, firmware, labeling, or assembly which is intended to be included as part of the finished device.", "Definitions.", "820"),
    ])
    s["820.7"] = Section("820.7", "Incorporation by reference.", "820", "sp820a", False, 2, [
        rec("820.7", "", 0, "Certain material is incorporated by reference into this part with the approval of the Director of the Federal Register and is available for inspection at the agency.", "Incorporation by reference.", "820"),
    ])
    s["820.10"] = Section("820.10", "Requirements for a quality management system.", "820", "sp820a", False, 3, [
        rec("820.10", "", 0, "A manufacturer subject to this part as described by § 820.1(a) must:", "Requirements for a quality management system.", "820"),
        rec("820.10", "(a)", 1, "(a) Document. Document a quality management system that complies with the applicable requirements of ISO 13485 as incorporated by reference in § 820.7 and the supplemental provisions of this part.", "Requirements for a quality management system.", "820"),
        rec("820.10", "(b)", 2, "(b) Applicable regulatory requirements. Comply with all applicable regulatory requirements when a provision of ISO 13485 refers to them, including the requirements of this chapter.", "Requirements for a quality management system.", "820"),
        rec("820.10", "(c)", 3, "(c) Design and development. Manufacturers of class II and class III devices must establish and maintain design and development procedures that satisfy the applicable requirements of ISO 13485.", "Requirements for a quality management system.", "820"),
    ])
    s["820.999x"] = Section("820.999x", "[Reserved]", "820", "sp820a", True, 4, [])
    for sec in s.values():
        parts[sec.part].sections.append(sec.number)
        if sec.subpart_id:
            subparts[sec.subpart_id].sections.append(sec.number)
    for sp in subparts.values():
        parts[sp.part].subparts.append(sp.id)
    definitions = [
        Definition("Electronic record", s["11.3"].records[1]),
        Definition("Closed system", s["11.3"].records[2]),
        Definition("Act", s["820.3"].records[0]),
        Definition("component", s["820.3"].records[1]),
    ]
    cross_refs = [
        CrossRef(s["820.10"].records[1], "§ 820.7", s["820.7"].records[0]),
        CrossRef(s["820.10"].records[0], "§ 820.1(a)", s["820.1"].records[0]),
    ]
    doc = GuidanceDoc(
        "Part 11, Electronic Records; Electronic Signatures - Scope and Application", "FDA-2003-D-0143", "final", "CDER", "drug", "2003-08-01",
        "https://www.fda.gov/media/75414/download", "11", "11.10", "This guidance represents the current thinking of FDA on this topic.", True,
        intro_chunks=[GuidanceChunk(0, "Guidance for Industry. This guidance is intended to describe the Food and Drug Administration's current thinking regarding the scope and application of part 11 of Title 21. It applies to electronic records.")],
        recommendation_chunks=[GuidanceChunk(5, "Approach to validation. FDA recommends that you base your approach on a justified and documented risk assessment and a determination of the potential of the system to affect product quality and safety. Further text follows here.")],
        anchor_chunks=[GuidanceChunk(7, "Audit trails. Persons must still comply with all applicable predicate rule requirements related to documentation, and the controls in § 11.10 apply to closed systems used for electronic records. More text.")],
        anchors=[("11", "11.10")],
    )
    return Corpus(
        {"ecfr_snapshot_date": "2026-09-03"}, subchapters, parts, subparts, s, definitions, cross_refs, [doc],
        {"11", "820", "83-98"}, set(s), {"FDA-2003-D-0143"},
    )


@pytest.fixture(scope="module")
def corpus():
    return make_corpus()


@pytest.fixture
def config(tmp_path):
    bench = tmp_path / "bench.jsonl"
    bench.write_text(json.dumps({"id": "b1", "question": "What does 21 CFR 820.10 cover?"}) + "\n" + json.dumps({"id": "b2", "query": "elements of informed consent"}) + "\n", encoding="utf-8")
    return TrainingConfig(target_examples=400, output_dir=tmp_path / "out", benchmarks=(bench,))


# ------------------------------------------------------------------ schema


def test_example_schema_roundtrip_and_validation():
    ctx = [ContextItem("ecfr", "21 CFR 820.10(a)", "Document a quality management system.", url="u", part="820", section="820.10", paragraph="(a)", source_key="ecfr:820.10:(a):0")]
    ex = TrainingExample("regulatory_qa", "section_paragraph", "What does 21 CFR 820.10(a) provide?", ctx, "21 CFR 820.10(a) [1] provides: Document a quality management system.", ["21 CFR 820.10(a)"], True, "gen/v1", "ecfr:820.10", "2026-09-03")
    ex.split = "train"
    d = ex.to_dict()
    assert set(d) >= {"id", "type", "category", "question", "context", "answer", "citations", "grounded", "provenance", "split"}
    assert d["context"][0]["source_type"] == "ecfr" and "text" in d["context"][0] and "heading" not in d["context"][0]
    back = TrainingExample.from_dict(json.loads(json.dumps(d)))
    assert back.to_dict() == d
    with pytest.raises(ExampleError):
        TrainingExample("regulatory_qa", "nope", "q?", ctx, "a", ["c"], True, "g", "grp")
    with pytest.raises(ExampleError):
        TrainingExample("regulatory_qa", "direct_cfr", "q?", [], "answer", [], True, "g", "grp")  # grounded without context
    with pytest.raises(ExampleError):
        ContextItem("wiki", "x", "y", source_key="k")
    with pytest.raises(ExampleError):
        TrainingExample.from_dict({"id": "x"})


def test_ids_are_deterministic_content_hashes():
    a = make_id("direct_cfr", "g", ["ecfr:820.10::0"], "What does 21 CFR 820.10 cover?")
    assert a == make_id("direct_cfr", "g", ["ecfr:820.10::0"], "What does 21 CFR 820.10 cover?") and a.startswith("example_") and len(a) == 24
    assert a != make_id("direct_cfr", "g", ["ecfr:820.10::0"], "What is 21 CFR 820.10?")


def test_to_messages_uses_rag_prompt_layout():
    ctx = [ContextItem("fda_guidance", "FDA Guidance: X (final)", "chunk text", url="https://www.fda.gov/x", source_key="fda_guidance:https://www.fda.gov/x#0")]
    ex = TrainingExample("regulatory_qa", "fda_guidance", "What does guidance X say?", ctx, "It says chunk text [1].", ["FDA Guidance: X (final)"], True, "g", "guidance:x")
    msgs = to_messages(ex)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    assert "SOURCE 1" in msgs[1]["content"] and "Corpus: FDA Guidance" in msgs[1]["content"] and "QUESTION: What does guidance X say?" in msgs[1]["content"]
    assert msgs[2]["content"] == ex.answer


# ------------------------------------------------------------------ text


def test_text_helpers():
    assert strip_label("(b)(1) For Clause 7.5.8") == "For Clause 7.5.8"
    assert leadin("(c) Design and development. Manufacturers of class II devices must do things.") == ("Design and development", "Manufacturers of class II devices must do things.")
    assert leadin("(a) Each manufacturer shall establish procedures. The procedures shall be documented.")[0] is None
    assert leadin("(6) Electronic record means any combination of text.")[0] is None
    assert heading_topic("Responsibilities of quality control unit.") == "responsibilities of quality control unit"
    assert heading_topic("What records must I keep?") is None
    assert is_clean_paragraph("(a) " + "word " * 20 + "end.", 60, 1500) and not is_clean_paragraph("(a) A manufacturer must:", 10, 1500)
    assert not is_clean_paragraph("(a) [Reserved]", 5, 100)
    assert identifiers("What does 21 CFR Part 11 cover?") == {"21", "11"} and identifiers("Explain § 820.10(b)(1)") == {"820.10(b)(1)"}
    assert normalise_question("What DOES 21 C.F.R. 820.10 cover?") == "what does 21 c.f.r 820.10 cover"


def test_definition_answer_forms():
    assert definition_answer("21 CFR 11.3(b)(6)", "Electronic record", "Electronic record means any combination of text.") == 'Under 21 CFR 11.3(b)(6) [1], "Electronic record" means any combination of text.'
    assert definition_answer("21 CFR 1.1", "owner", "The term owner means the person who makes entry.").startswith('Under 21 CFR 1.1 [1], "owner" means the person')
    assert definition_answer("21 CFR 1.1", "Foreign supplier", "Foreign supplier means, for an article of food, the establishment.") == 'Under 21 CFR 1.1 [1], "Foreign supplier" means, for an article of food, the establishment.'
    assert definition_answer("21 CFR 1.1", "Body", "Body has the same meaning as auditor.") == 'Under 21 CFR 1.1 [1], "Body" has the same meaning as auditor.'
    assert definition_answer("21 CFR 1.1", "Farm", "Farmhouse means x.") is None
    assert definition_answer("21 CFR 1.1", "Act", "Act means:") is None


def test_guidance_sentence_extraction():
    assert recommendation_sentence(GuidanceChunk(0, "Intro. In addition, FDA recommends that sponsors document the risk assessment in the submission. Next")) == "In addition, FDA recommends that sponsors document the risk assessment in the submission."
    assert recommendation_sentence(GuidanceChunk(0, "Although FDA recommends RCTs, we will consider alternative designs if they are")) is None  # chunk-boundary fragment
    assert recommendation_sentence(GuidanceChunk(0, "FDA recommends that applicants monitor drugs2 for delays in a timely manner today.")) is None  # footnote artifact
    assert scope_sentence(GuidanceChunk(0, "Title. This guidance provides recommendations on an optional approach that may be used to demonstrate substantial equivalence. More.")).startswith("This guidance provides")


# ------------------------------------------------------------ generators


def test_direct_cfr_generation(corpus, config):
    out = gen_direct_cfr(corpus, config)
    parts = [e for e in out if e.extra["subtype"] == "part"]
    assert {e.citations[0] for e in parts} == {"21 CFR 11.1(a)", "21 CFR 820.1(a)"}
    p820 = next(e for e in parts if "820" in e.question)
    assert "Quality Management System Regulation" in p820.answer and "Subchapter H (Medical Devices)" in p820.answer and "[1]" in p820.answer
    assert p820.context[0].text in p820.answer  # answer text is the verbatim context
    sections = [e for e in out if e.extra["subtype"] == "section"]
    assert all("Definitions" not in e.answer.split(",")[1] for e in sections)
    s820_10 = next(e for e in sections if "820.10" in e.question)
    assert s820_10.citations == ["21 CFR 820.10", "21 CFR 820.10(a)", "21 CFR 820.10(b)", "21 CFR 820.10(c)"] and "It provides:" in s820_10.answer
    for e in out:
        assert e.grounded and e.type == "regulatory_qa" and e.category == "direct_cfr" and e.citations == [c.citation for c in e.context]


def test_section_paragraph_and_definition_generation(corpus, config):
    paras = gen_section_paragraph(corpus, config)
    assert paras and all(e.category == "section_paragraph" and len(e.context) == 1 for e in paras)
    lead = next(e for e in paras if e.context[0].citation == "21 CFR 820.10(c)")
    assert "design and development" in lead.question.lower() or "paragraph (c)" in lead.question
    assert lead.answer.startswith('21 CFR 820.10(c) [1] ("Design and development") provides: Manufacturers of class II')
    per_section = {}
    for e in paras:
        per_section[e.group] = per_section.get(e.group, 0) + 1
    assert max(per_section.values()) <= config.quality.max_paragraph_examples_per_section
    defs = gen_definitions(corpus, config)
    terms = {e.extra["term"] for e in defs}
    assert terms == {"Electronic record", "Closed system", "Act", "component"}
    er = next(e for e in defs if e.extra["term"] == "Electronic record")
    assert er.answer.startswith('Under 21 CFR 11.3(b)(6) [1], "Electronic record" means any combination') and er.citations == ["21 CFR 11.3(b)(6)"]
    comp = next(e for e in defs if e.extra["term"] == "component")
    assert 'the term "component"' not in comp.answer and '"component" means any raw material' in comp.answer


def test_relationship_citation_multi_and_distinction_generation(corpus, config):
    rel = gen_relationships(corpus, config)
    kinds = {e.extra["subtype"] for e in rel}
    assert kinds == {"subpart_sections", "section_location", "section_paragraphs", "cross_reference"}
    sp = next(e for e in rel if e.extra["subtype"] == "subpart_sections" and "820" in e.question)
    assert sp.context[0].source_type == "ecfr_hierarchy" and sp.citations == ["21 CFR Part 820, Subpart A"] and "§ 820.10 (Requirements for a quality management system)" in sp.answer
    loc = next(e for e in rel if e.extra["subtype"] == "section_location" and "11.10" in e.question)
    assert "Subpart B (Electronic Records) of Part 11" in loc.answer and "Subchapter A (General)" in loc.answer
    xr = next(e for e in rel if e.extra["subtype"] == "cross_reference")
    assert xr.context[0].citation == "21 CFR 820.10(a)" and "points to 21 CFR 820.7" in xr.answer and "[2]" in xr.answer
    sp_paras = next(e for e in rel if e.extra["subtype"] == "section_paragraphs")
    assert sp_paras.context[0].section == "820.10" and "(a) Document [1]; (b) Applicable regulatory requirements [2]; (c) Design and development [3]" in sp_paras.answer

    cit = gen_citation(corpus, config)
    heads = [e for e in cit if e.extra["subtype"] == "heading"]
    assert any("controls for closed systems" in e.question for e in heads) and all(e.citations[0].startswith("21 CFR ") for e in heads)
    assert not any("scope" in e.question.lower() for e in heads)  # non-unique two-word heading is skipped
    dcit = [e for e in cit if e.extra["subtype"] == "definition"]
    assert any('defines "Closed system"' in e.question or '"Closed system" defined' in e.question or 'definition of "Closed system"' in e.question for e in dcit)

    multi = gen_multi_context(corpus, config)
    assert {e.extra["subtype"] for e in multi} == {"cross_reference", "guidance_section"}
    gs = next(e for e in multi if e.extra["subtype"] == "guidance_section")
    assert [c.source_type for c in gs.context] == ["ecfr", "fda_guidance"] and "§ 11.10 apply to closed systems" in gs.answer and "non-binding" in gs.answer
    for e in multi:
        assert len(e.context) == 2 and len(e.citations) == 2

    vs = gen_cfr_vs_guidance(corpus, config)
    assert {e.extra["subtype"] for e in vs} == {"ecfr_only", "guidance_only", "pair"}
    g_only = next(e for e in vs if e.extra["subtype"] == "guidance_only")
    assert "from FDA guidance" in g_only.answer and "not legally binding" in g_only.answer and g_only.citations == [g_only.context[0].citation]
    e_only = next(e for e in vs if e.extra["subtype"] == "ecfr_only")
    assert "from the eCFR" in e_only.answer and "legally binding" in e_only.answer


def test_guidance_generation_identifies_guidance_as_guidance(corpus, config):
    out = gen_guidance(corpus, config)
    assert {e.extra["subtype"] for e in out} == {"scope", "recommendation"}
    for e in out:
        assert e.context[0].source_type == "fda_guidance" and e.context[0].docket_number == "FDA-2003-D-0143"
        assert "non-binding" in e.answer and "FDA guidance" in e.answer
        assert e.citations == [e.context[0].citation] and "Docket FDA-2003-D-0143" in e.citations[0]
    rec_ex = next(e for e in out if e.extra["subtype"] == "recommendation")
    assert '"FDA recommends that you base your approach on a justified and documented risk assessment' in rec_ex.answer


# ------------------------------------------------------------- negatives


def test_negative_identifiers_never_exist(corpus, config):
    for part, fake in fake_section_numbers(corpus, 10):
        assert part in corpus.parts and fake not in corpus.all_section_numbers
    for n in fake_part_numbers(corpus, 20):
        assert n not in corpus.all_part_numbers and int(n) not in corpus.reserved_part_numbers()
    assert 90 not in {int(n) for n in fake_part_numbers(corpus, 2000)}  # inside the reserved 83-98 range
    for d in fake_dockets(corpus, 20):
        assert d.startswith("FDA-") and d not in corpus.all_dockets
    assert fake_dockets(corpus, 5) == fake_dockets(corpus, 5)


def test_abstention_examples_refuse_and_carry_no_citations(corpus, config):
    out = gen_abstention(corpus, config)
    kinds = {e.extra["subtype"] for e in out}
    assert kinds >= {"fake_section", "fake_part", "fake_docket", "invalid_paragraph", "unrecorded_date", "future_revision"}
    for e in out:
        assert e.type == "abstention" and not e.grounded and e.citations == [] and is_refusal(e.answer)
        assert "negative" in e.extra and e.extra["negative"]["identifier"]
    with_ctx = [e for e in out if e.context]
    assert with_ctx and all("[1]" in e.answer for e in with_ctx)
    inv = next(e for e in out if e.extra["subtype"] == "invalid_paragraph")
    assert inv.extra["negative"]["paragraph"] not in {c.paragraph for c in inv.context}
    assert not any("2026-09-03" not in e.answer for e in out if e.extra["subtype"] == "future_revision")


# ---------------------------------------------------- dedup / selection


def _ex(q, a="An answer that is long enough.", group="g", cite="21 CFR 1.1", subtype="s"):
    ctx = [ContextItem("ecfr", cite, "context text", source_key=f"ecfr:{cite.split()[-1]}::0")]
    return TrainingExample("regulatory_qa", "direct_cfr", q, ctx, a, [cite], True, "gen", group, extra={"subtype": subtype})


def test_deduplicate_exact_and_near():
    a = _ex("What does 21 CFR 1.1 cover?")
    b = _ex("What does 21 CFR 1.1 cover?")  # same id
    c = _ex("What does 21 CFR 1.1  cover ?")  # same normalised question -> exact duplicate
    d = _ex("What does 21 CFR 1.1 cover today?")  # near duplicate in the same group
    e = _ex("What does 21 CFR 1.1 cover today?", group="other")  # other group: kept
    kept, report = deduplicate([a, b, c, d, e], 0.8)
    assert [k.question for k in kept] == [a.question, e.question]
    assert report == {"duplicate_ids": 1, "exact_duplicates": 1, "near_duplicates": 1}


def test_exclude_benchmark_requires_matching_identifiers():
    bench = ["What does 21 CFR 820.10 cover?", "elements of informed consent"]
    same = _ex("What does 21 CFR 820.10 cover?")
    near_same_id = _ex("What does 21 CFR 820.10 cover exactly?")
    other_id = _ex("What does 21 CFR 820.1 cover?")
    no_id = _ex("Elements of informed consent?")  # normalises to the benchmark query
    loose = _ex("What are the elements of informed consent?")  # Jaccard 0.57 < 0.75: kept
    kept, excluded = exclude_benchmark([same, near_same_id, other_id, no_id, loose], bench, 0.75)
    assert set(excluded) == {same.id, near_same_id.id, no_id.id} and kept == [other_id, loose]
    reworded = _ex("What is 21 CFR 820.10 about?")  # same identifier, different wording
    kept, excluded = exclude_benchmark([reworded, other_id], bench, 0.75, 0.5)
    assert excluded == [reworded.id] and kept == [other_id]


def test_select_balanced_round_robins_subtypes():
    exs = [_ex(f"q{i}?", subtype="a") for i in range(10)] + [_ex(f"r{i}?", subtype="b") for i in range(2)]
    chosen = select_balanced(exs, 6, 42)
    assert len(chosen) == 6 and sum(e.extra["subtype"] == "b" for e in chosen) == 2
    assert [e.id for e in select_balanced(exs, 6, 42)] == [e.id for e in chosen]
    assert select_balanced(exs, 0, 42) == []


# ------------------------------------------------------------- splits


def test_splits_are_deterministic_and_group_level(config):
    exs = [_ex(f"q{i}?", group=f"ecfr:{i % 7}") for i in range(50)]
    counts = assign_splits(exs, config)
    assert sum(counts.values()) == 50 and set(counts) == {"train", "validation", "test"}
    assert group_overlap(exs) == []
    assert split_for_group("ecfr:820.10", config) == split_for_group("ecfr:820.10", config)
    other = TrainingConfig(seed=7, benchmarks=config.benchmarks, output_dir=config.output_dir)
    assert any(split_for_group(f"ecfr:{i}", config) != split_for_group(f"ecfr:{i}", other) for i in range(200))
    bad_ratio = dict(train_ratio=0.5, validation_ratio=0.1, test_ratio=0.1)
    with pytest.raises(TrainingConfigError):
        TrainingConfig(**bad_ratio)


def test_leakage_check_flags_cross_split_duplicates():
    a = _ex("Same question?", group="g1")
    a.split = "train"
    b = _ex("Same question?", group="g2")
    b.split = "test"
    report = ValidationReport()
    check_leakage({"train": [a], "validation": [], "test": [b]}, report)
    assert report.checks["leakage_question_answer_exact"] == 1 and not report.ok


# ------------------------------------------------------------ end to end


def test_build_is_deterministic_and_respects_targets(corpus, config):
    # put the exact question the generator asks about 820.10 into the benchmark file
    q_820_10 = next(e.question for e in gen_direct_cfr(corpus, config) if e.group == "ecfr:820.10")
    config.benchmarks[0].write_text(json.dumps({"id": "b1", "question": q_820_10}) + "\n", encoding="utf-8")
    examples, info = build_examples(corpus, config)
    again, _ = build_examples(corpus, config)
    assert [e.to_dict() for e in examples] == [e.to_dict() for e in again]
    # the v1-style config carries shares only for the Stage 11 categories, so the
    # Stage 13 grounding categories must not appear in a v1 build
    assert len(examples) > 40 and {e.category for e in examples} == set(STAGE11_CATEGORIES)
    targets = config.category_targets()
    for cat, row in info["per_category"].items():
        assert row["selected"] <= targets[cat]
    assert info["per_category"]["direct_cfr"]["benchmark_excluded"] >= 1
    assert not any(normalise_question(e.question) == normalise_question(q_820_10) for e in examples)
    assert all(e.split in ("train", "validation", "test") for e in examples) and group_overlap(examples) == []


def test_written_dataset_validates_offline_and_detects_tampering(corpus, config, tmp_path):
    examples, _ = build_examples(corpus, config)
    paths = dataset_paths(config)
    for split, path in paths.items():
        write_jsonl([e for e in examples if e.split == split], path)
    first = {s: p.read_bytes() for s, p in paths.items()}
    for split, path in paths.items():
        write_jsonl([e for e in examples if e.split == split], path)
    assert {s: p.read_bytes() for s, p in paths.items()} == first  # byte-identical rewrite
    report = validate_dataset(paths, config, db=None)
    assert report.ok, report.errors
    assert report.checks["provenance"].startswith("skipped") and report.checks["secret_findings"] == {}
    assert report.stats["total"] == len(examples) and report.stats["negative_examples"] > 0
    assert read_jsonl(paths["train"])[0].split == "train"
    # tamper: a grounded example citing something outside its context
    rows = [json.loads(l) for l in paths["train"].read_text(encoding="utf-8").splitlines()]
    target = next(r for r in rows if r["grounded"])
    target["citations"] = ["21 CFR 999.999"]
    paths["train"].write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    report = validate_dataset(paths, config, db=None)
    assert not report.ok and any("citation not among context citations" in e for e in report.errors)


def test_secret_scan_flags_connection_strings(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"answer": "see postgresql://user:hunter2@localhost/db"}) + "\n", encoding="utf-8")
    report = ValidationReport()
    scan_secrets({"train": p}, report)
    assert report.checks["secret_findings"].get("database_url") == 1 and not report.ok
    clean = tmp_path / "c.jsonl"
    clean.write_text(json.dumps({"answer": "password protection is described in 21 CFR 11.300"}) + "\n", encoding="utf-8")
    report = ValidationReport()
    scan_secrets({"train": clean}, report)
    assert report.ok


def test_config_loads_yaml_and_overrides():
    cfg = load_training_config()
    assert cfg.version == "v1" and cfg.seed == 42 and abs(sum(cfg.category_shares.values()) - 1.0) < 1e-6
    assert cfg.category_targets()["direct_cfr"] == 2500 and cfg.output_dir.name == "datasets"
    assert load_training_config(target_examples=100, seed=3).category_targets()["abstention"] == 5
    with pytest.raises(TrainingConfigError):
        load_training_config(nonsense=1)
