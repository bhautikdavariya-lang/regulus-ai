"""Regulatory logic on FDA guidance (Priority 2).

The evaluator's operators were built for binding regulation. Applied to FDA
guidance they produced false contradictions - the most damaging error the
evaluator can make, a correct answer scored INCORRECT 0 - and false support:

    E-007  "... must be linked ... to ensure that the signatures cannot be
           excised" read as a NEGATED duty (negation inside a purpose clause)
    K-003  guidance "should include" read as contradicting "must include"
    H-001  "FDA provides an abbreviated renewal process" read as moving the
           facility's duty onto FDA
    H-006  guidance silent on an "except" read as excluding the claim, twice:
           as an invented condition and as the provision's own exclusion
    C-005  dietary-supplement guidance "supporting" a cosmetics (MoCRA) claim

These tests pin the fixes, and - just as important - that genuine
contradictions are still found and that guidance still supports what it says.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy import evaluate
from regulus.accuracy import operators as OP
from regulus.accuracy import relevance as RV
from regulus.accuracy.alignment import Passage
from regulus.accuracy.intent import analyze

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "accuracy_guidance_rows.json").read_text(encoding="utf-8"))
REAL = {r["id"]: r for r in FIXTURE["rows"]}


@dataclass(frozen=True)
class Src:
    index: int
    citation: str
    text: str
    corpus: str = "ecfr"
    heading: str | None = None
    tier: str = "exact"
    requirement_ids: tuple[str, ...] = ()
    citation_fields: dict[str, Any] = field(default_factory=dict)
    is_docket: bool = False


@dataclass(frozen=True)
class Pkg:
    question: str
    sources: tuple[Src, ...]
    requirements: tuple[tuple[str, str], ...] = ()
    satisfied_ids: tuple[str, ...] = ()
    answer_plan: Any = None
    question_analysis: Any = None

    @property
    def requirement_labels(self) -> dict[str, str]:
        return dict(self.requirements)


@dataclass(frozen=True)
class Cov:
    requirements: tuple[Any, ...] = ()
    satisfied_ids: tuple[str, ...] = ()
    missing_labels: tuple[str, ...] = ()
    explicit: bool = False


GUIDE = "FDA Guidance: Purchasing Controls for Medical Device Manufacturers (final, 2024-01-01, Docket FDA-2024-D-0001)"
SUPPLEMENT_GUIDE = ("FDA Guidance: Questions and Answers Regarding Adverse Event Reporting for Dietary Supplements "
                    "(final, 2013-09-01, Docket FDA-2007-D-0372)")


def judge(question, answer, sources):
    srcs = tuple(Src(i + 1, c, t, corpus) for i, (c, t, corpus) in enumerate(sources))
    return evaluate(question, answer, package=Pkg(question, srcs), coverage=Cov())


def claim(assessment, n=0):
    return assessment.checked["claims"][n]


def conflicts(claim_text, evidence_text, authority):
    return [c["operator"] for c in OP.compare(claim_text, evidence_text, authority=authority).conflicts]


# ======================================================= the eight required cases


def test_1_should_in_guidance_does_not_contradict_must():
    c, e = "Each manufacturer must maintain complaint files.", "Manufacturers should maintain complaint files."
    assert conflicts(c, e, OP.GUIDANCE) == []
    rel = OP.compare(c, e, authority=OP.GUIDANCE).relations
    assert rel[0]["operator"] == "strength" and rel[0]["relation"] == "guidance_weaker"
    assert rel[0]["claim"] == "mandatory" and rel[0]["evidence"] == "recommended"
    # the same wording in binding regulation IS a modal conflict: the rule is unchanged for eCFR
    assert conflicts(c, e, OP.BINDING) == ["strength"]


def test_2_a_recommendation_does_not_contradict_a_requirement():
    c = "The manufacturer must submit the annual report to FDA."
    e = "FDA recommends submitting the annual report electronically."
    assert conflicts(c, e, OP.GUIDANCE) == []


def test_3_what_fda_does_is_not_a_transferred_duty():
    c = "The manufacturer must submit the annual report to FDA."
    assert conflicts(c, "FDA reviews the annual report within 60 days.", OP.GUIDANCE) == []
    assert conflicts(c, "FDA reviews the annual report.", OP.BINDING) == []
    # the H-001 sentence: a description of FDA's process, compared with the facility's duty
    h001 = ("If a facility has not had any changes to its registration information since the previous "
            "registration, renewal, or update, FDA provides an abbreviated biennial renewal process.")
    duty = "A facility must renew its registration during the period beginning on October 1 of each even-numbered year."
    for authority in (OP.GUIDANCE, OP.BINDING):
        assert "actor" not in conflicts(h001, duty, authority)


@pytest.mark.parametrize("authority", [OP.BINDING, OP.GUIDANCE])
def test_4_an_actual_negation_is_still_a_contradiction(authority):
    c = "The manufacturer must submit the report to FDA."
    e = "The manufacturer must not submit the report to FDA."
    assert "polarity" in conflicts(c, e, authority)


@pytest.mark.parametrize("authority", [OP.BINDING, OP.GUIDANCE])
def test_5_prohibited_versus_permitted_is_still_a_contradiction(authority):
    c = "The use of vinyl chloride in cosmetic aerosol products is prohibited."
    e = "The use of vinyl chloride in cosmetic aerosol products is permitted."
    assert "polarity" in conflicts(c, e, authority)


def test_6_a_negative_inside_a_purpose_clause_is_not_the_duty_negated():
    evidence = ("Electronic signatures must be linked to their respective electronic records to ensure that the "
                "signatures cannot be excised, copied, or otherwise transferred.")
    assert OP.polarity(evidence) == OP.AFFIRM
    assert OP.polarity("The procedure is designed to ensure that the signature cannot be excised.") != OP.NEGATE
    claimed = ("The FDA guidance specifies that electronic signatures must be linked to the respective electronic "
               "records to ensure that the signatures cannot be excised by ordinary means.")
    for authority in (OP.GUIDANCE, OP.BINDING):
        assert "polarity" not in conflicts(claimed, evidence, authority)
    # a negation that does govern the duty is still read as one
    assert OP.polarity("Records must not be altered, so that the audit trail is complete.") == OP.NEGATE
    assert OP.polarity("The process shall be validated where the results cannot be fully verified.") == OP.AFFIRM


def test_6b_the_complement_of_ensure_is_not_the_polarity_of_the_duty():
    """Found while validating this change (E-010, eCFR only): fixing the purpose
    clause on the evidence side alone left the answer's "ensure ... that
    signatures cannot be repudiated" negated, and created a contradiction."""
    claim_text = ("These provisions ensure the authenticity, integrity, and confidentiality of electronic records, and "
                  "that electronic signatures cannot be repudiated.")
    reg = ("Persons who use closed systems shall employ procedures and controls designed to ensure the authenticity, "
           "integrity, and, when appropriate, the confidentiality of electronic records, and to ensure that the signer "
           "cannot readily repudiate the signed record as not genuine.")
    assert "polarity" not in conflicts(claim_text, reg, OP.BINDING)
    assert OP.polarity("The manufacturer shall ensure that devices are not adulterated.") == OP.AFFIRM
    assert OP.polarity("The manufacturer must not ship devices that are adulterated.") == OP.NEGATE


def test_7_guidance_from_another_product_area_is_not_supporting_evidence():
    q = "What adverse event reporting obligations does MoCRA create for cosmetic responsible persons?"
    text = ("A responsible person must submit a serious adverse event report to FDA within 15 business days of "
            "receiving the report.")
    a = judge(q, text + " [1]", [(SUPPLEMENT_GUIDE, text, "fda_guidance")])
    assert claim(a)["support"] not in (AN.SUPPORTED, AN.PARTIALLY_SUPPORTED)
    assert a.checked["evidence_excluded_domain"][0]["citation"] == SUPPLEMENT_GUIDE
    assert "dietary supplements" in a.checked["evidence_excluded_domain"][0]["reason"]
    # the same passage IS evidence for a question about dietary supplements
    q2 = "What adverse event reporting obligations apply to dietary supplement responsible persons?"
    b = judge(q2, text + " [1]", [(SUPPLEMENT_GUIDE, text, "fda_guidance")])
    assert b.checked["evidence_excluded_domain"] == [] and claim(b)["support"] == AN.SUPPORTED


def test_8_guidance_still_supports_what_it_says():
    q = "What does FDA guidance recommend for evaluating suppliers?"
    g = ("FDA recommends that manufacturers evaluate suppliers on the basis of their ability to meet specified "
         "requirements and document the results.")
    a = judge(q, g + " [1]", [(GUIDE, g, "fda_guidance")])
    assert claim(a)["support"] == AN.SUPPORTED and a.checked["answer_verdict"]["verdict"] == AN.CORRECT
    trace = claim(a)["operator_trace"]
    assert trace["source_type"] == OP.GUIDANCE and trace["conflicts"] == [] and trace["support_blocked"] is None


# ======================================================= what must NOT happen


def test_a_requirement_stated_from_a_recommendation_is_not_supported_either():
    """Not a contradiction - and not support: guidance that RECOMMENDS X does not
    establish that X is REQUIRED. The claim is left unverifiable, with why."""
    q = "What must the device description include?"
    g = "The investigational device description should include an explanation of how the device functions."
    a = judge(q, "The investigational device description must include an explanation of how the device functions [1].",
              [(GUIDE, g, "fda_guidance")])
    c = claim(a)
    assert c["support"] == AN.UNVERIFIABLE and c["final"] != AN.CONTRADICTED
    assert "does not establish the mandatory requirement" in c["support_reason"]
    assert c["operator_trace"]["relations"][0]["relation"] == "guidance_weaker"


def test_a_modal_mismatch_against_binding_regulation_is_still_a_contradiction():
    q = "What does 21 CFR 820.30(a) require?"
    reg = "Each manufacturer of any class III or class II device shall establish procedures to control the design of the device."
    a = judge(q, "Each manufacturer of any class III or class II device may establish procedures to control the design of "
                 "the device [1].", [("21 CFR 820.30(a)", reg, "ecfr")])
    assert claim(a)["final"] == AN.CONTRADICTED and a.checked["answer_verdict"]["verdict"] == AN.INCORRECT


def test_a_duty_on_a_different_regulated_party_is_still_a_contradiction_in_regulation():
    c = "Each manufacturer shall submit a report to FDA no later than 30 calendar days after receipt."
    e = "Each importer shall submit a report to FDA no later than 30 calendar days after receipt."
    assert conflicts(c, e, OP.BINDING) == ["actor"]
    assert conflicts(c, e, OP.GUIDANCE) == []        # guidance addresses its own reader


def test_a_different_number_is_still_a_contradiction_against_guidance():
    c = "Complaints must be evaluated within 90 days of receipt."
    e = "FDA recommends that complaints be evaluated within 30 days of receipt."
    assert conflicts(c, e, OP.GUIDANCE) == ["quantity"]


def test_an_invented_condition_is_judged_only_against_a_passage_that_states_the_rule():
    c = "Records must be kept for two years, except when the product is exported."
    assert conflicts(c, "Records must be kept for two years.", OP.BINDING) == ["invented_condition"]
    assert conflicts(c, "Records of distribution are described in the following sections.", OP.BINDING) == []
    assert conflicts(c, "Records must be kept for two years.", OP.GUIDANCE) == []


def test_guidance_naming_no_product_is_never_excluded_by_domain():
    intent = analyze("What adverse event reporting obligations does MoCRA create for cosmetic responsible persons?")
    general = Passage(1, "FDA Guidance: Electronic Systems, Electronic Records, and Electronic Signatures (final, "
                         "2024-10-01, Docket FDA-2017-D-1105)", "exact", "Records must be retained.", None, OP.GUIDANCE)
    assert RV.guidance_domain_conflict(intent, general) is None
    regulation = Passage(1, "21 CFR 111.30", "exact", "Equipment must be designed.", None, OP.BINDING)
    assert RV.guidance_domain_conflict(intent, regulation) is None      # eCFR keeps its own (part-based) check
    assert RV.guidance_domain_conflict(analyze("What does guidance say about records?"),
                                       Passage(1, SUPPLEMENT_GUIDE, "exact", "x y z w", None, OP.GUIDANCE)) is None


def test_a_guidance_exclusion_is_not_the_governing_provision_excluding_the_claim():
    q = "Which foods are subject to the traceability recordkeeping requirements?"
    g = "The recordkeeping requirements do not apply to farms that sell directly to consumers."
    a = judge(q, "The recordkeeping requirements apply to farms that sell directly to consumers [1].",
              [("FDA Guidance: Food Traceability (final, 2023-01-01, Docket FDA-2014-N-0053)", g, "fda_guidance")])
    assert "excludes" not in a.reason
    r = judge(q, "The recordkeeping requirements apply to farms that sell directly to consumers [1].",
              [("21 CFR 1.1305(a)", g, "ecfr")])
    assert r.checked["answer_verdict"]["verdict"] == AN.INCORRECT      # the regulation's own exclusion still binds


# ======================================================= the real forensic rows


def run_real(row_id):
    row = REAL[row_id]
    srcs = tuple(Src(i + 1, s["citation"], s["text"], s["corpus"], is_docket=s["corpus"] == "fda_guidance")
                 for i, s in enumerate(row["sources"]))
    return row, evaluate(row["question"], row["answer"] or "", package=Pkg(row["question"], srcs), coverage=Cov(),
                         model_called=row["model_called"], fallback_type=row["fallback_type"])


def contradicted(a):
    return [c for c in a.checked.get("claims", []) if c["final"] == AN.CONTRADICTED]


@pytest.mark.parametrize("row_id", ["E-007", "K-003", "H-006", "H-001", "L-010", "C-005"])
def test_no_real_row_is_contradicted_by_guidance_wording(row_id):
    row, a = run_real(row_id)
    assert not contradicted(a), f"{row_id}: {[c['support_reason'] for c in contradicted(a)]}"
    if row["N"] == 2:
        assert a.checked["answer_verdict"]["verdict"] != AN.INCORRECT


def test_E007_correct_answer_is_no_longer_scored_incorrect():
    row, a = run_real("E-007")
    assert row["N"] == 2 and a.checked["answer_verdict"]["verdict"] != AN.INCORRECT and a.accuracy != 0


def test_H006_guidance_does_not_exclude_the_claim():
    _, a = run_real("H-006")
    assert a.checked["answer_verdict"]["verdict"] != AN.INCORRECT and "excludes" not in a.reason


def test_C005_supplement_guidance_does_not_support_a_cosmetics_answer():
    _, a = run_real("C-005")
    assert a.checked["evidence_excluded_domain"]
    assert not [c for c in a.checked["claims"] if c["support"] in (AN.SUPPORTED, AN.PARTIALLY_SUPPORTED)]


def test_C003_tobacco_guidance_does_not_decide_a_cosmetics_refusal():
    _, a = run_real("C-003")
    assert {e["citation"].split(":")[1].strip()[:40] for e in a.checked["evidence_excluded_domain"]}
    assert all("tobacco" in e["reason"] for e in a.checked["evidence_excluded_domain"])


def test_D005_on_topic_guidance_still_decides_an_incorrect_refusal():
    """Guidance is not ignored: drug-manufacturing guidance on aseptic processing
    is on topic for an aseptic-processing question."""
    row, a = run_real("D-005")
    assert row["N"] == 0 and a.checked["answer_verdict"]["verdict"] == AN.ABSTENTION_INCORRECT
    assert a.checked["evidence_excluded_domain"] == []
