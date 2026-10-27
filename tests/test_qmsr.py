"""QM1 (regulus.rag.qmsr): former Quality System regulation sections and ISO 13485 clauses (26 Oct 2026)."""
from types import SimpleNamespace

from regulus.planning import plan_query
from regulus.rag import qmsr

LIVE = {"820.1", "820.3", "820.7", "820.10", "820.35", "820.45"}


def src(index, citation, text, tier="exact"):
    return SimpleNamespace(index=index, citation=citation, text=text, tier=tier, is_docket=False, requirement_ids=("r1",))


def test_a_former_section_with_no_live_text_is_found_and_a_live_one_is_not():
    assert qmsr.former_refs(plan_query("What does 21 CFR 820.30(j) require?"), LIVE) == [("820.30", "(j)")]
    assert qmsr.former_refs(plan_query("What does 21 CFR 820.45 require?"), LIVE) == []
    assert qmsr.former_refs(plan_query("What does 21 CFR 211.22 require?"), LIVE) == []


def test_successors_and_clauses_come_from_the_reference_file():
    assert qmsr.successors([("820.198", "")]) == ["820.35"] and qmsr.successors([("820.100", "")]) == ["820.10"]
    assert qmsr.clauses_for("820.100", "") == (["8.5.2", "8.5.3"], "fr")
    assert qmsr.clauses_for("820.30", "(j)")[0] == ["7.3.10"]
    assert qmsr.clause_label("8.5.2") == "Clause 8.5.2 (Corrective action)"


def test_an_iso_clause_the_standard_does_not_have_is_found():
    assert qmsr.unknown_clauses("What does ISO 13485 Clause 9.2 require?") == ["9.2"]
    assert qmsr.unknown_clauses("What does Clause 8.5.2 of ISO 13485 require?") == []
    assert qmsr.unknown_clauses("Is ISO 13485:2016 required?") == []


def test_the_answer_quotes_the_live_text_and_names_the_clause_with_its_basis():
    package = SimpleNamespace(sources=[
        src(1, "21 CFR 820.10", "A manufacturer subject to this part as described by § 820.1(a) must:"),
        src(2, "21 CFR 820.10(a)", "(a) Document. Document a quality management system that complies with ISO 13485."),
        src(3, "21 CFR 820.10(b)(1)", "(1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document UDI."),
        src(4, "21 CFR 820.10(c)", "(c) Design and development. Manufacturers must comply with Clause 7.3 and its Subclauses.")])
    text = qmsr.compose(package, "What does 21 CFR 820.30 require for design controls?", [("820.30", "")])
    assert text.startswith('21 CFR 820.30 ("Design controls") is not in the current eCFR')
    assert "21 CFR 820.10(c) (eCFR, binding, verbatim)" in text and "820.10(b)(1)" not in text   # UDI is off-subject
    assert "Clause 7.3 (Design and development)" in text and "no section-by-section mapping" not in text   # basis: reg
    audit = qmsr.compose(package, "What are the requirements of 21 CFR 820.22?", [("820.22", "")])
    assert "Clause 8.2.4 (Internal audit)" in audit and "FDA published no section-by-section mapping" in audit
    assert qmsr.compose(SimpleNamespace(sources=[]), "q", [("820.22", "")]) is None   # nothing current to quote


def test_the_pipeline_sentences_are_recognised_by_the_validator():
    from regulus.rag.claim_validation import _NOT_A_CLAIM

    for line in ['21 CFR 820.22 ("Quality audit") is not in the current eCFR: it belonged to the former Quality System '
                 'regulation, which the Quality Management System Regulation replaced on 2 February 2026.',
                 "In ISO 13485:2016 (incorporated by reference, 21 CFR 820.7) the subject is addressed by Clause 8.2.4.",
                 "ISO 13485:2016 has no Clause 9.2: its requirements are organized in Clauses 4 through 8."]:
        assert _NOT_A_CLAIM.search(line) and qmsr.PIPELINE_SENTENCES_RE.search(line)


def test_former_record_types_named_in_words_are_their_former_sections():
    from regulus.rag.qmsr import former_by_name
    live = {"820.1", "820.3", "820.7", "820.10", "820.35", "820.45"}
    q = "What is the difference between a Device Master Record, a Device History Record, and a Design History File?"
    assert former_by_name(q, live) == [("820.181", ""), ("820.184", ""), ("820.30", "(j)")]
    assert former_by_name("What must complaint records contain under Part 820?", live) == []


def test_the_certification_answer_rests_on_820_10_a():
    pkg = SimpleNamespace(sources=[src(1, "21 CFR 820.10", "A manufacturer subject to this part as described by § 820.1(a) must:"),
                                   src(2, "21 CFR 820.10(a)", "(a) Document. Document a quality management system that "
                                       "complies with the applicable requirements of ISO 13485 and other applicable requirements of this part; and")])
    q = "Does Part 820 require a manufacturer to hold ISO 13485 certification?"
    text = qmsr.compose_certification(pkg, q)
    assert text.startswith("Part 820 does not require ISO 13485 certification") and "[2]" in text and "820.10(a) (eCFR" in text
    assert qmsr.compose_certification(SimpleNamespace(sources=pkg.sources[:1]), q) is None
    assert not qmsr.asks_certification("What does 21 CFR 820.10 require?")
