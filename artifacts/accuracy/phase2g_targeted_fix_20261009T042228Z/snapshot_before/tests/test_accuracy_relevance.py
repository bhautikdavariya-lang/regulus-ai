"""Question relevance, claim-level verdicts and refusal judgement (rubric v2).

The single most important property this file pins: a true regulatory statement
that answers a different question is a WRONG answer. Phase 1 passed acceptance
row D-001 on substantive correctness - twenty verbatim quotations of
21 CFR 211.100-211.132 given to a question about the SCOPE of Part 211 - and
that is the failure these tests exist to prevent from coming back.

The first group runs on real acceptance rows (tests/fixtures/accuracy_real_rows.json:
question, delivered answer and human labels from run acceptance_rev02, evidence
text from the read-only eCFR snapshot). The rest builds small packages directly,
one per behaviour the evaluator must get right.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy import intent as IN
from regulus.accuracy import relevance as RV
from regulus.accuracy import rubric as R
from regulus.accuracy.alignment import passages
from regulus.accuracy.claims import POINTER, RESTATEMENT, HEADING, classify, propositions
from regulus.accuracy.evaluator import evaluate

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "accuracy_real_rows.json").read_text(encoding="utf-8"))
REAL = {r["id"]: r for r in FIXTURE["rows"]}


# ------------------------------------------------------------------ shims


@dataclass(frozen=True)
class Src:
    index: int
    citation: str
    text: str
    heading: str | None = None
    tier: str = "exact"
    requirement_ids: tuple[str, ...] = ()
    citation_fields: dict[str, Any] = field(default_factory=dict)
    corpus: str = "ecfr"
    is_docket: bool = False


@dataclass(frozen=True)
class Pkg:
    question: str
    requirements: tuple[tuple[str, str], ...]
    satisfied_ids: tuple[str, ...]
    sources: tuple[Src, ...]
    answer_plan: Any = None
    question_analysis: Any = None

    @property
    def requirement_labels(self) -> dict[str, str]:
        return dict(self.requirements)


@dataclass(frozen=True)
class Cov:
    requirements: tuple[Any, ...]
    satisfied_ids: tuple[str, ...]
    missing_labels: tuple[str, ...]
    explicit: bool


def _fields(citation: str) -> dict[str, Any]:
    import re

    m = re.match(r"21 CFR (\d+\.\d+[a-z]?)((?:\([^)]+\))*)$", citation)
    return {"title": "21", "section": m.group(1), "paragraph": m.group(2)} if m else {}


def package(question: str, sources: list[tuple[str, str, str | None]]) -> tuple[Pkg, Cov]:
    """A package and coverage for a question, built the way the validation harness
    rebuilds them: requested provisions from the pipeline's own parser, satisfied
    when an evidence source IS that provision or one of its paragraphs."""
    from regulus.planning import plan_query
    from regulus.retrieval.references import parse_cfr_references

    srcs = tuple(Src(i + 1, c, t, h, citation_fields=_fields(c)) for i, (c, t, h) in enumerate(sources))
    plan = plan_query(question)
    reqs = tuple((r.id, r.canonical) for r in plan.requirements)
    have = [ref for s in srcs for ref in parse_cfr_references(s.citation)]
    sat = []
    for rid, canon in reqs:
        want = next(iter(parse_cfr_references(canon)), None)
        if want and any(h.section == want.section and h.paragraph_path.startswith(want.paragraph_path)
                        for h in have if h.section):
            sat.append(rid)
    return (Pkg(question, reqs, tuple(sat), srcs),
            Cov(reqs, tuple(sat), tuple(c for r, c in reqs if r not in sat), bool(reqs)))


def run(question: str, answer: str, sources, **kw):
    pkg, cov = package(question, sources)
    return evaluate(question, answer, package=pkg, coverage=cov, **kw)


def run_real(row_id: str):
    row = REAL[row_id]
    srcs = [(s["citation"], s["text"], s.get("heading")) for s in row["sources"]]
    return row, run(row["question"], row["answer"] or "", srcs, model_called=row["model_called"],
                    fallback_type=row["fallback_type"],
                    answerability={"state": row["answerability"]} if row.get("answerability") else None)


def verdict(a) -> str:
    return a.checked["answer_verdict"]["verdict"]


# ======================================================= real acceptance rows


def test_19_D001_true_statements_answering_a_different_question_is_a_wrong_answer():
    """THE regression. Twenty verbatim, individually true quotations of
    21 CFR 211.100-211.132 (production and process controls), given to "What is
    the SCOPE of 21 CFR Part 211 and how does it relate to Part 210?". Human: N=0.
    Phase 1 scored substantive correctness PASS."""
    row, a = run_real("D-001")
    assert row["human"]["N"] == 0
    assert verdict(a) in (AN.OFF_TOPIC, AN.INCORRECT)
    assert a.accuracy is not None and a.accuracy < 50, f"D-001 scored {a.accuracy}"
    assert a.states[R.SUBSTANTIVE] != R.PASS
    assert a.states[R.QUESTION_RELEVANCE] == R.FAIL
    claims = a.checked["claims"]
    assert len(claims) >= 10, "the answer is many true statements, which is the point"
    assert all(c["final"] == AN.IRRELEVANT for c in claims), "every statement answers a different question"
    # and the reason says WHY, from the evidence, not from the wording
    assert "says nothing about" in claims[0]["relevance"]["reason"]


def test_19b_D001_scores_low_whatever_the_aligner():
    """The guarantee may not depend on the optional semantic aligner."""
    from regulus.accuracy.alignment import LexicalAligner

    row = REAL["D-001"]
    pkg, cov = package(row["question"], [(s["citation"], s["text"], s.get("heading")) for s in row["sources"]])
    a = evaluate(row["question"], row["answer"], package=pkg, coverage=cov, aligner=LexicalAligner())
    assert verdict(a) in (AN.OFF_TOPIC, AN.INCORRECT) and (a.accuracy or 0) < 50


@pytest.mark.parametrize("row_id", ["M-031", "M-032", "M-033", "M-035", "M-036", "M-037", "M-038"])
def test_20_temporal_refusals_are_not_credited_as_correct(row_id):
    """Seven refusals of superseded Part 820 sections ("820.30 for design
    controls"). Human: N=1 FAIL - the rubric requires a redirect to where the
    requirement now lives. Phase 1 scored every one 95. A superseded section and
    one that never existed are indistinguishable in the snapshot, so these may
    not be credited as correct refusals."""
    row, a = run_real(row_id)
    assert row["human"]["N"] == 1 and row["fallback_type"] == "provision_not_found"
    assert verdict(a) != AN.ABSTENTION_CORRECT
    assert a.accuracy is None or a.accuracy < 90, f"{row_id} scored {a.accuracy}"


def test_D003_answer_that_restates_the_question_then_lists_other_content_is_off_topic():
    """"Under Part 211, personnel qualification and training requirements include
    written procedures for production and process control ..." - the wording
    echoes the question; the content is production control."""
    row, a = run_real("D-003")
    assert row["human"]["N"] == 0
    assert verdict(a) in (AN.OFF_TOPIC, AN.INCORRECT) and (a.accuracy or 0) < 50
    echo = [c for c in a.checked["claims"] if c["relevance"]["checks"].get("lead_restating_question")]
    assert echo, "the lead that restates the question is recognised"
    assert all(c["relevance"]["verdict"] != RV.RELEVANT for c in echo), "... and does not make the content relevant"
    assert any(c["final"] == AN.IRRELEVANT for c in a.checked["claims"])


def test_D008_answer_from_the_wrong_product_domain_is_off_topic():
    """A drug-manufacturing question answered from 21 CFR 111.30 (dietary supplements)."""
    row, a = run_real("D-008")
    assert row["human"]["N"] == 0
    assert verdict(a) in (AN.OFF_TOPIC, AN.INCORRECT) and (a.accuracy or 0) < 50
    assert any("dietary supplements" in c["relevance"]["reason"] for c in a.checked["claims"])


def test_D002_correct_verbatim_answer_is_correct():
    """N=2: the quality control unit's responsibilities, quoted from 211.22(a)-(d)."""
    row, a = run_real("D-002")
    assert row["human"]["N"] == 2
    assert verdict(a) == AN.CORRECT and a.accuracy >= 90
    assert all(c["relevance"]["verdict"] == RV.RELEVANT for c in a.checked["claims"])


def test_NC003_withheld_answer_to_a_negative_control_is_an_incorrect_refusal():
    row, a = run_real("NC-003")
    assert row["human"]["N"] == 0
    assert verdict(a) == AN.ABSTENTION_INCORRECT and a.accuracy == 0


def test_C004_evidence_that_cannot_verify_is_not_called_missing_content():
    """Nine statements about prohibited ingredients against recital-only evidence:
    unverified, which is not the same as not covering the subject."""
    row, a = run_real("C-004")
    assert row["human"]["N"] == 2
    assert verdict(a) != AN.OFF_TOPIC
    assert a.states[R.COMPLETENESS] != R.FAIL
    assert a.checked["answer_verdict"]["elements_missing"] == []


@pytest.mark.parametrize("row_id", sorted(REAL))
def test_no_real_row_is_scored_high_unless_the_human_passed_its_substance(row_id):
    """Across every frozen real row: nothing scores >= 90 unless the human gave N=2."""
    row, a = run_real(row_id)
    if a.accuracy is not None and a.accuracy >= 90:
        assert row["human"]["N"] == 2, f"{row_id}: human N={row['human']['N']}, evaluator {a.accuracy}"


# ======================================================= question intent


def test_intent_reads_the_subject_not_the_wording():
    it = IN.analyze("What is the scope of 21 CFR Part 211 and how does it relate to Part 210?")
    assert it.kind == IN.CROSS_REFERENCE
    assert set(it.parts) == {"211", "210"} and "C" in it.domains
    assert [e.terms for e in it.elements] == [("scop",), ("relat",)]


def test_intent_distinction_items_are_told_apart_by_their_modifier():
    it = IN.analyze("What is the difference between a process preventive control, a sanitation preventive control, "
                    "and an allergen preventive control under Part 117?")
    assert it.kind == IN.DISTINCTION
    assert [e.terms for e in it.elements] == [("proces",), ("sanit",), ("allergen",)]


def test_intent_compound_question_has_one_element_per_clause():
    it = IN.analyze("Which facilities must register with FDA, and how often must registration be renewed?")
    assert len(it.elements) == 2


def test_intent_application_and_temporal_kinds():
    assert IN.analyze("A firm uses a cloud-hosted LIMS. Which Part 11 provisions apply to the vendor's controls?").kind \
        == IN.APPLICATION
    assert IN.analyze("Our manual follows the Quality System Regulation. Do Subparts C through O still apply?").kind \
        == IN.TEMPORAL


def test_part_of_reads_the_part_not_the_title():
    """The first number in "21 CFR 111.30" is the title; reading it as the part put
    every source in subchapter A and disabled every domain check."""
    assert IN.part_of("21 CFR 111.30") == "111" and IN.part_of("21 CFR part 211") == "211"
    assert IN.subchapter(IN.part_of("21 CFR 111.30")) == "B"
    assert IN.part_of("FDA Guidance: x (Docket FDA-2013-D-0743)") is None


# ======================================================= the required cases

DESIGN_Q = "What does 21 CFR 820.30(a) require?"
DESIGN = ("21 CFR 820.30(a)", "Each manufacturer of any class III or class II device shall establish and maintain "
          "procedures to control the design of the device in order to ensure that specified design requirements are met.",
          "Design controls.")
PURCHASE = ("21 CFR 820.50(a)", "Each manufacturer shall establish and maintain procedures to ensure that all "
            "purchased or otherwise received product and services conform to specified requirements.",
            "Purchasing controls.")
SCOPE_211 = ("21 CFR 211.1(a)", "The regulations in this part contain the minimum current good manufacturing practice "
             "for preparation of drug products for administration to humans or animals.", "Scope.")
PROD_211 = ("21 CFR 211.100(a)", "There shall be written procedures for production and process control designed to "
            "assure that the drug products have the identity, strength, quality, and purity they purport or are "
            "represented to possess.", "Written procedures; deviations.")
SUPPLEMENT = ("21 CFR 111.30", "You must use equipment and utensils that are of appropriate design, construction and "
              "workmanship to enable them to perform their intended functions in dietary supplement manufacture.",
              "What requirements apply to the design and construction of automated equipment?")


def test_1_correct_direct_answer():
    a = run(DESIGN_Q, f"21 CFR 820.30(a): {DESIGN[1]} [1]", [DESIGN])
    assert verdict(a) == AN.CORRECT and a.accuracy == 100


def test_2_correct_paraphrase():
    a = run(DESIGN_Q, "21 CFR 820.30(a): Each manufacturer of any class III or class II device must create and "
                      "maintain documented procedures to control the device design so that specified design "
                      "requirements are met [1].", [DESIGN])
    assert verdict(a) == AN.CORRECT
    assert a.checked["claims"][0]["support_basis"] == "paraphrase"


def test_3_wrong_topic_true_regulatory_answer_is_wrong():
    """A true quotation from Part 211 production controls, given to a scope question."""
    q = "What is the scope of 21 CFR Part 211?"
    a = run(q, f"{PROD_211[1]} [2]", [SCOPE_211, PROD_211])
    assert a.checked["claims"][0]["support"] == AN.SUPPORTED, "the statement is TRUE"
    assert a.checked["claims"][0]["final"] == AN.IRRELEVANT, "... and does not answer the question"
    assert verdict(a) == AN.OFF_TOPIC and a.accuracy == 0


def test_4_partially_correct_answer():
    """One requirement right, one statement about something else."""
    q = "What does 21 CFR 820.30(a) require for design controls?"
    a = run(q, f"21 CFR 820.30(a): {DESIGN[1]} [1] {PURCHASE[1]} [2]", [DESIGN, PURCHASE])
    assert verdict(a) == AN.PARTIAL
    assert 0 < a.accuracy < 100


def test_5_explicitly_contradicted_answer():
    a = run(DESIGN_Q, "21 CFR 820.30(a): Each manufacturer of any class III or class II device may establish "
                      "procedures to control the design of the device [1].", [DESIGN])
    assert verdict(a) == AN.INCORRECT and a.accuracy == 0
    assert a.checked["claims"][0]["operators"]["strength"] == "mismatched"


def test_6_unsupported_claim_is_unverifiable_not_wrong():
    """Absence of evidence is not falsehood."""
    a = run(DESIGN_Q, "Design reviews for class III devices must be repeated after every software release [1].",
            [DESIGN])
    claim = a.checked["claims"][0]
    assert claim["support"] == AN.UNVERIFIABLE and claim["final"] != AN.CONTRADICTED
    assert verdict(a) != AN.INCORRECT


def test_7_correct_refusal():
    q = "Summarize the requirements of 21 CFR 111.900."
    a = run(q, "The available eCFR data does not contain 21 CFR 111.900, so I cannot state what it requires. "
               "No exact text for the requested provision was retrieved and I will not infer its contents.",
            [("21 CFR 111.90(a)", "You must establish and follow written procedures for quality control.", None)],
            model_called=False, fallback_type="provision_not_found")
    assert verdict(a) == AN.ABSTENTION_CORRECT and a.accuracy >= 90


def test_8_incorrect_refusal_when_the_retrieved_evidence_covers_the_question():
    """C-003 / D-005 pattern: declines, but a passage about exactly what was asked was retrieved."""
    q = "What procedures must be established to control the design of a class III device?"
    a = run(q, "The available regulatory sources do not provide enough information to answer this question.",
            [DESIGN], model_called=True)
    assert verdict(a) == AN.ABSTENTION_INCORRECT and a.accuracy == 0
    assert "retrieved evidence covers" in a.checked["abstention"]["reason"]


def test_8b_refusal_of_a_missing_section_with_a_subject_the_evidence_covers_is_partial():
    """A redirect was possible: the evidence on hand is about the subject."""
    q = "What does 21 CFR 820.99 require for design controls?"
    a = run(q, "The available eCFR data does not contain 21 CFR 820.99, so I cannot state what it requires. "
               "No exact text for the requested provision was retrieved and I will not infer its contents.",
            [DESIGN], model_called=False, fallback_type="provision_not_found")
    assert verdict(a) == AN.PARTIAL and a.accuracy < 90


def test_8c_refusal_with_a_subject_nothing_retrieved_covers_is_unverifiable():
    q = "What does 21 CFR 820.99 require for design controls?"
    a = run(q, "The available eCFR data does not contain 21 CFR 820.99, so I cannot state what it requires. "
               "No exact text for the requested provision was retrieved and I will not infer its contents.",
            [PURCHASE], model_called=False, fallback_type="provision_not_found")
    assert verdict(a) == AN.ANSWER_UNVERIFIABLE and a.accuracy is None


def test_9_cross_reference_question_is_evaluable():
    q = "What is the scope of 21 CFR Part 211 and how does it relate to Part 210?"
    a = run(q, f"21 CFR 211.1(a): {SCOPE_211[1]} [1]", [SCOPE_211, PROD_211])
    assert verdict(a) in (AN.CORRECT, AN.PARTIAL)
    assert a.accuracy is not None
    # the relation to Part 210 is asked for and not answered
    assert a.checked["answer_verdict"]["elements_missing"]


def test_10_distinction_question_is_evaluable_and_checks_each_side():
    q = "How does a design control differ from a purchasing control under Part 820?"
    full = run(q, f"{DESIGN[1]} [1] {PURCHASE[1]} [2]", [DESIGN, PURCHASE])
    one_side = run(q, f"{DESIGN[1]} [1]", [DESIGN, PURCHASE])
    assert verdict(full) == AN.CORRECT
    assert verdict(one_side) == AN.PARTIAL and one_side.accuracy < full.accuracy


def test_11_application_question_is_evaluable():
    q = "A firm makes a class II device. What must it establish to control the design of the device?"
    a = run(q, f"21 CFR 820.30(a): {DESIGN[1]} [1]", [DESIGN])
    assert a.checked["intent"]["kind"] == IN.APPLICATION
    assert verdict(a) == AN.CORRECT and a.accuracy >= 90


def test_12_multi_claim_answer_mixing_correct_and_incorrect():
    q = "What do 21 CFR 820.30(a) and 21 CFR 820.50(a) require?"
    a = run(q, f"21 CFR 820.30(a): {DESIGN[1]} [1]\n21 CFR 820.50(a): Each manufacturer may establish procedures to "
               f"ensure that all purchased product conforms to specified requirements [2].", [DESIGN, PURCHASE])
    finals = [c["final"] for c in a.checked["claims"]]
    assert AN.SUPPORTED in finals and AN.CONTRADICTED in finals
    assert verdict(a) == AN.INCORRECT


def test_12b_a_sentence_listing_several_obligations_is_judged_per_obligation():
    s = "The manufacturer must establish a QMS, maintain UDI procedures, and ensure all personnel receive annual training [1]."
    assert len(propositions(s)) == 3
    assert propositions("Each manufacturer shall establish and maintain procedures to control the design [1].") == \
        ["Each manufacturer shall establish and maintain procedures to control the design [1]."]


def test_13_modal_strength_mismatch():
    a = run(DESIGN_Q, "21 CFR 820.30(a): Each manufacturer of any class III or class II device should establish "
                      "procedures to control the design of the device [1].", [DESIGN])
    assert a.checked["claims"][0]["operators"]["strength"] == "mismatched"
    assert verdict(a) == AN.INCORRECT


def test_14_actor_mismatch():
    q = "What must an importer submit under 21 CFR 803.40?"
    src = ("21 CFR 803.40", "Each importer shall submit a report to FDA no later than 30 calendar days after the day "
           "of receipt.", "Importer reporting.")
    a = run(q, "21 CFR 803.40: Each manufacturer shall submit a report to FDA no later than 30 calendar days after "
               "the day of receipt [1].", [src])
    assert a.checked["claims"][0]["operators"]["actor"] == "mismatched"
    assert verdict(a) == AN.INCORRECT


def test_15_applicability_condition_dropped():
    q = "When must a process be validated under 21 CFR 820.75(a)?"
    src = ("21 CFR 820.75(a)", "Where the results of a process cannot be fully verified by subsequent inspection and "
           "test, the process shall be validated with a high degree of assurance, as appropriate.", "Process validation.")
    a = run(q, "21 CFR 820.75(a): The process shall be validated with a high degree of assurance [1].", [src])
    assert a.checked["claims"][0]["final"] == AN.PARTIALLY_SUPPORTED
    assert verdict(a) == AN.PARTIAL


def test_16_numeric_mismatch():
    q = "Within what time must complaints be evaluated under 21 CFR 820.198(a)?"
    src = ("21 CFR 820.198(a)", "Each manufacturer shall review and evaluate all complaints within 30 days of receipt.",
           "Complaint files.")
    a = run(q, "21 CFR 820.198(a): Each manufacturer shall review and evaluate all complaints within 90 days of "
               "receipt [1].", [src])
    assert a.checked["claims"][0]["operators"]["quantity"] == "mismatched"
    assert verdict(a) == AN.INCORRECT


def test_17_citation_defect_without_substantive_defect():
    """Cited to the wrong source: the statement is still true; only citation fails."""
    q = "What do 21 CFR 820.30(a) and 21 CFR 820.50(a) require?"
    a = run(q, f"21 CFR 820.30(a): {DESIGN[1]} [2]\n21 CFR 820.50(a): {PURCHASE[1]} [2]", [DESIGN, PURCHASE])
    first = a.checked["claims"][0]
    assert first["support"] == AN.SUPPORTED and first["citation"] == "points_elsewhere"
    assert first["final"] == AN.SUPPORTED_WITH_CITATION_DEFECT
    assert a.states[R.CITATION] == R.FAIL and a.states[R.SUBSTANTIVE] == R.PASS


def test_18_missing_evidence_is_unverifiable_and_gets_no_number():
    a = evaluate("What does 21 CFR 820.30(a) require?", "Design controls are required.", package=None)
    assert a.status == R.UNABLE and a.accuracy is None


def test_18b_an_answer_whose_statements_have_no_evidence_is_unverifiable():
    a = run(DESIGN_Q, "21 CFR 820.30(a) requires a design history file reviewed by an independent auditor [1].",
            [PURCHASE])
    assert verdict(a) in (AN.ANSWER_UNVERIFIABLE, AN.OFF_TOPIC)
    assert verdict(a) != AN.CORRECT


# ======================================================= relevance mechanism


def test_relevance_is_decided_by_the_evidence_a_claim_corresponds_to():
    it = IN.analyze("What is the scope of 21 CFR Part 211?")
    ps = passages([Src(1, *SCOPE_211), Src(2, *PROD_211)])
    on = RV.assess(f"{SCOPE_211[1]}", it, ps)
    off = RV.assess(f"{PROD_211[1]}", it, ps)
    assert on.verdict == RV.RELEVANT and "Scope" in (on.evidence[0] + str(on.topic_hits)) or on.verdict == RV.RELEVANT
    assert off.verdict == RV.IRRELEVANT


def test_relevance_sees_a_wrong_domain_named_in_the_claim():
    it = IN.analyze("What requirements apply to automated equipment used in drug manufacturing?")
    ps = passages([Src(1, *SUPPLEMENT)])
    r = RV.assess("Calibration of automated equipment must be done under a written program, as required by "
                  "21 CFR 111.30.", it, ps)
    assert r.verdict == RV.IRRELEVANT and "dietary supplements" in r.reason


def test_relevance_without_evidence_is_undetermined_not_irrelevant():
    """A sentence can refer to its subject without naming it."""
    it = IN.analyze("What does 21 CFR 820.30(a) require for design controls?")
    r = RV.assess("It also requires that these be documented and approved.", it, [])
    assert r.verdict == RV.UNDETERMINED


# ======================================================= claim segmentation


@pytest.mark.parametrize("sentence,question,origin", [
    ("21 CFR 600.3 [9]: As used in this subchapter: [9]", None, HEADING),
    ("[10] 21 CFR 600.80(a) [10]: Postmarketing reporting of adverse experiences [10] [11].", None, HEADING),
    ("Under Part 211, yield calculation and reconciliation requirements are specified in [1].",
     "What are the yield calculation and reconciliation requirements under Part 211?", POINTER),
    ("Under Part 117 Subpart B, sanitation requirements apply to plant and grounds.",
     "What sanitation requirements apply to plant and grounds under Part 117 Subpart B?", RESTATEMENT),
])
def test_sentences_that_assert_no_proposition_are_not_claims(sentence, question, origin):
    assert classify(sentence, question=question).origin == origin


def test_a_long_proposition_with_unlisted_verbs_is_not_a_heading():
    """"obliges ... to check" uses no listed verb; it is a full proposition."""
    assert classify("21 CFR 820.10(b)(2) obliges a maker to check bought-in goods [1].").is_claim


# ======================================================= the rubric


def test_rubric_v2_makes_relevance_absolute():
    assert R.RUBRIC_ID == "regulus_live_evidence_assessment_v2"
    assert R.QUESTION_RELEVANCE in R.ABSOLUTE and R.QUESTION_RELEVANCE in R.DIMENSIONS
    allp = {d: R.PASS for d in R.DIMENSIONS}
    assert R.score({**allp, R.QUESTION_RELEVANCE: R.FAIL}) == 0
