"""Claim extraction and claim-to-evidence matching (Priority 3).

The extractor used to end with a verb allow-list: a sentence whose verb was not
on it was "asserting nothing" and silently dropped - 43 of 377 sentences in the
60-row validation, 9 of F-007's 12. Simply removing the gate was measured to
drop the correct answer G-004 from 100 to 40, because what it then admitted
could not be matched to the evidence. So extraction and matching change
together:

    extraction  every sentence is CLAIM / NON_CLAIM / UNCERTAIN, by what it is
                about (headings, labels, pointers, meta-statements, pipeline
                text are not claims), never by its verb
    splitting   a modal list into obligations that inherit the modal; an
                include-type list into items that inherit the head
    context     a leading "These ..." resolved from the previous sentence only
    matching    list items, descriptive restatements and two adjacent evidence
                sentences may SUPPORT a claim under strict conditions; none of
                them can contradict one, and none is a similarity threshold

The guiding rule: recover information; do not manufacture correctness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy import claims as CL
from regulus.accuracy import evaluate
from regulus.accuracy import operators as OP
from regulus.accuracy.attribution import strip_lead

FIX = Path(__file__).parent / "fixtures"
ROWS = {r["id"]: r for r in json.loads((FIX / "accuracy_extraction_rows.json").read_text(encoding="utf-8"))["rows"]}
REAL = {r["id"]: r for r in json.loads((FIX / "accuracy_real_rows.json").read_text(encoding="utf-8"))["rows"]}
GUIDE = {r["id"]: r for r in json.loads((FIX / "accuracy_guidance_rows.json").read_text(encoding="utf-8"))["rows"]}


@dataclass(frozen=True)
class Src:
    index: int
    citation: str
    text: str
    heading: str | None = None
    corpus: str = "ecfr"
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


def judge(question, answer, sources, **kw):
    srcs = tuple(Src(i + 1, *s) if isinstance(s, tuple) else s for i, s in enumerate(sources))
    return evaluate(question, answer, package=Pkg(question, srcs), coverage=Cov(), **kw)


def frozen(row_id, table=ROWS):
    r = table[row_id]
    srcs = tuple(Src(s["index"], s["citation"], s["text"], s.get("heading"), citation_fields=s.get("citation_fields") or {})
                 for s in r["sources"])
    reqs = tuple(tuple(x) for x in r.get("requirements") or ())
    pkg = Pkg(r["question"], srcs, reqs, tuple(r.get("satisfied_ids") or ()))
    cov = Cov(reqs, tuple(r.get("satisfied_ids") or ()), tuple(r.get("missing_labels") or ()), bool(r.get("explicit")))
    return r, evaluate(r["question"], r["answer"], package=pkg, coverage=cov, model_called=r["model_called"],
                       fallback_type=r["fallback_type"])


def MARK_strip(text):
    import re
    return re.sub(r"\s*\[\d+\]", "", text).strip(" .")


def status(sentence, question=None):
    return CL.classify(sentence, question=question).claim_status


def verdict(a):
    return a.checked["answer_verdict"]["verdict"]


RECORDS = ("21 CFR 820.198(a)", "Each manufacturer shall maintain complaint files, investigation records, and service "
           "records, and shall ensure that all records are complete and accurate.")


# ======================================================= 1-4: descriptive verbs are claims


def test_1_an_include_sentence_is_a_claim_and_its_items_are_checked():
    s = "Required records include complaint files, investigation records, and service records [1]."
    assert status(s) == CL.CLAIM_STATUS_CLAIM
    assert CL.enumeration(s).items == ("complaint files", "investigation records", "service records [1]")
    a = judge("What records are required?", s, [RECORDS])
    assert verdict(a) == AN.CORRECT and all(c["final"] == AN.SUPPORTED for c in a.checked["claims"])
    assert {c["match_path"] for c in a.checked["claims"]} == {"list_item"}


def test_2_an_ensure_sentence_is_a_claim_and_keeps_its_structure():
    s = "The manufacturer must ensure that all records are complete and accurate [1]."
    assert status(s) == CL.CLAIM_STATUS_CLAIM
    # the obligation is to ENSURE; what is ensured is its content, not a separate duty or a negation
    assert OP.strength(s) == OP.MANDATORY and OP.main_clause(s).strip().endswith("must")
    assert OP.polarity("The manufacturer must ensure that records are not altered.") == OP.AFFIRM
    a = judge("What must the manufacturer ensure about records?", s, [RECORDS])
    assert a.checked["claims"][0]["final"] == AN.SUPPORTED


def test_3_a_contain_sentence_is_a_claim():
    s = "The submission must contain the device name and the intended use [1]."
    assert status(s) == CL.CLAIM_STATUS_CLAIM
    a = judge("What must the submission contain?", s,
              [("21 CFR 807.87(a)", "The submission shall contain the device name and the intended use of the device.")])
    assert a.checked["claims"] and a.checked["claims"][0]["final"] != AN.CONTRADICTED


def test_4_a_comprise_sentence_is_a_claim_with_its_items():
    s = ("The device master record comprises the device specifications, the production process specifications, and "
         "the quality assurance procedures.")
    assert status(s) == CL.CLAIM_STATUS_CLAIM and len(CL.enumeration(s).items) == 3


# ======================================================= 5-8: splitting and normalisation


def test_5_coordinated_obligations_are_separate_propositions():
    units = CL.propositions("The manufacturer must maintain records, investigate complaints, and report serious events.")
    assert len(units) == 3


def test_6_each_proposition_inherits_the_modal_and_compound_verbs_stay_whole():
    units = CL.propositions("The manufacturer must maintain records, investigate complaints, and report serious events.")
    assert all(u.startswith("The manufacturer must ") for u in units)
    assert CL.propositions("Each manufacturer shall establish and maintain procedures to control the design.") == \
        ["Each manufacturer shall establish and maintain procedures to control the design."]


def test_7_lists_split_only_where_they_are_lists():
    marked = CL.enumeration("21 CFR 820.35 adds the name of the device [3], the name, address, and phone number of the "
                            "complainant [6], and any test and inspection data [16]")
    assert marked.marked and marked.items[1] == "the name, address, and phone number of the complainant [6]"
    # a modifier after a comma is not an item; a bare "and"/"or" joins words, it does not start an item
    assert CL.enumeration("The requirements include identifying and implementing preventive controls to minimize or "
                          "prevent hazards, as appropriate.").items == (
        "identifying and implementing preventive controls to minimize or prevent hazards, as appropriate",)
    assert CL.enumeration('The requirements include the title "Drug Facts" appearing on each panel, with the title using '
                          'uppercase letters.').items == ('the title "Drug Facts" appearing on each panel',
                                                          "the title using uppercase letters")


def test_8_lead_ins_are_normalised_and_the_proposition_kept():
    assert strip_lead("The scope of 21 CFR Part 11 is defined in section 11.1(a), which states that the regulations in "
                      "this part set forth the criteria.").startswith("the regulations in this part")
    assert strip_lead("In other words, the manufacturer must keep records.") == "the manufacturer must keep records."
    assert status("In other words, the manufacturer must keep records for two years.") == CL.CLAIM_STATUS_CLAIM
    kept = "Each manufacturer shall establish procedures, which require review of complaints."
    assert strip_lead(kept) == kept            # a main clause before "which" is never framing


# ======================================================= 9-11: citations and non-claims


def test_9_a_list_item_keeps_its_own_citation():
    q = "What do the records include?"
    # (each source must actually support its item: before Phase 2A a cited claim
    # with no supporting passage was reported "correct" unchecked)
    srcs = [("21 CFR 820.180", "Each manufacturer shall maintain records, including complaint files."),
            ("21 CFR 820.181", "Each manufacturer shall maintain device history records.")]
    a = judge(q, "The required records include complaint files [1], and device history records [1].", srcs)
    by_item = {c["subclaim"]["item"]: c for c in a.checked["claims"]}
    assert by_item["complaint files [1]"]["citation"] == "correct"
    assert by_item["device history records [1]"]["citation"] == "points_elsewhere"
    assert all("[1]" not in c["normalized_text"] for c in a.checked["claims"])


@pytest.mark.parametrize("fragment", ["21 CFR 820.30(a)", "§ 820.30(a):", "[1] [2]", "21 CFR 820.30(a) [3]:"])
def test_10_a_citation_only_fragment_is_not_a_claim(fragment):
    assert status(fragment) == CL.CLAIM_STATUS_NON_CLAIM


@pytest.mark.parametrize("heading", ["Requirements:", "Applicable section", "Answer", "These requirements include:"])
def test_11_a_heading_is_not_a_claim(heading):
    assert status(heading) == CL.CLAIM_STATUS_NON_CLAIM


def test_11b_meta_statements_are_not_claims_and_uncertain_ones_are_recorded_not_judged():
    assert CL.classify("The sources that support these requirements are [1][2].").origin == CL.META
    for s in ("Prompt submission is important for public health reasons.", "The update to the FTL is scheduled for YY."):
        assert status(s) == CL.CLAIM_STATUS_UNCERTAIN
    a = judge("When must reports be submitted?",
              "Prompt submission is important for public health reasons. Reports must be submitted within 15 days [1].",
              [("21 CFR 803.50(a)", "Reports must be submitted within 15 days.")])
    statuses = [c["claim_status"] for c in a.checked["claim_candidates"]]
    assert statuses == [CL.CLAIM_STATUS_UNCERTAIN, CL.CLAIM_STATUS_CLAIM]
    assert len(a.checked["claims"]) == 1 and verdict(a) == AN.CORRECT      # uncertain neither judged nor penalised


# ======================================================= 12-15: context and matching


def test_12_a_leading_pronoun_is_resolved_from_the_previous_sentence_only():
    assert CL.resolve("These include complaint files and investigation records.",
                      "The manufacturer must maintain records.") == \
        ("records include complaint files and investigation records.", "records")
    assert CL.resolve("These provisions ensure integrity.", "A firm applies 21 CFR 11.10 and 21 CFR 11.30.")[1] == \
        "21 CFR 11.10 and 21 CFR 11.30"
    assert CL.resolve("These records are kept.", "The manufacturer must maintain records.")[1] is None
    a = judge("What records must be maintained?",
              "The manufacturer must maintain records [1]. These include complaint files and investigation records [1].",
              [("21 CFR 820.198(a)", "Each manufacturer shall maintain records. Such records shall include complaint "
                                     "files and investigation records.")])
    resolved = [c for c in a.checked["claims"] if c["resolved_from"] == "records"]
    assert resolved and all(c["final"] == AN.SUPPORTED for c in resolved)


def test_13_two_adjacent_evidence_sentences_can_support_one_claim():
    src = ("21 CFR 117.20(a)", "The grounds about a food plant must be kept in a condition that will protect against the "
           "contamination of food. The methods for adequate maintenance of grounds must include proper storage of "
           "equipment and removal of litter.")
    claim = ("The grounds must be kept in a condition that will protect against the contamination of food, and the "
             "methods for adequate maintenance must include proper storage of equipment [1].")
    a = judge("What are the requirements for plant grounds?", claim, [src])
    c = a.checked["claims"][0]
    assert c["final"] == AN.SUPPORTED and c["match_path"] == "adjacent_window"


def test_13b_a_window_must_use_both_sentences():
    """One sentence matching and the other only adding terms is not window support (row F-007)."""
    src = ("21 CFR 117.165(a)", "You must verify that the preventive controls are consistently implemented. To do so you "
           "must conduct activities, as appropriate to the nature of the preventive control and its role in the "
           "facility's food safety system.")
    claim = ("A food safety plan must contain requirements for hazard analysis and preventive controls, as appropriate "
             "to the nature of the preventive control and its role in the facility's food safety system [1].")
    c = judge("What must a food safety plan contain?", claim, [src]).checked["claims"][0]
    assert c["final"] != AN.SUPPORTED


def test_14_a_close_match_that_says_the_opposite_is_contradicted_not_supported():
    src = ("21 CFR 820.180(b)", "Records shall not be discarded and shall be retained for a period of two years.")
    a = judge("How long must records be retained?", "Records may be discarded and retained for a period of two years [1].",
              [src])
    assert a.checked["claims"][0]["final"] == AN.CONTRADICTED and verdict(a) == AN.INCORRECT


def test_15_a_close_match_from_another_topic_is_irrelevant_not_support():
    row, a = frozen("D-006")
    assert row["N"] == 0 and verdict(a) == AN.OFF_TOPIC and a.accuracy == 0


def test_15b_a_list_item_merely_mentioned_in_a_recital_is_not_supported():
    """"Prohibited ingredients include vinyl chloride" is not borne out by a
    recital saying vinyl chloride HAS BEEN USED (row C-004, 21 CFR 700.14(a))."""
    row, a = frozen("C-004")
    items = [c for c in a.checked["claims"] if (c.get("subclaim") or {}).get("item", "").startswith("vinyl chloride")]
    assert items and items[0]["final"] != AN.SUPPORTED


# ======================================================= 16-18: refusals, wrong topic, correct


def test_16_refusals_stay_refusals():
    for s in ("The available regulatory sources do not provide enough information to answer this question.",
              "The retrieved sources were not verified to answer the question as asked, so their text is not quoted as an "
              "answer.", "No sufficiently relevant eCFR or FDA guidance passage was retrieved for the question."):
        assert status(s) == CL.CLAIM_STATUS_NON_CLAIM, s
    a = judge("What does 21 CFR 820.30(a) require?",
              "The available regulatory sources do not provide enough information to answer this question.",
              [("21 CFR 820.30(a)", "Each manufacturer shall establish procedures to control the design of the device.")])
    assert a.checked["abstention"]["declined"] and verdict(a) in (AN.ABSTENTION_INCORRECT, AN.ANSWER_UNVERIFIABLE)


def test_17_D001_wrong_topic_stays_off_topic():
    row, a = frozen("D-001", REAL) if "requirements" in REAL["D-001"] else (REAL["D-001"], None)
    from tests.test_accuracy_relevance import run_real

    row, a = run_real("D-001")
    assert verdict(a) in (AN.OFF_TOPIC, AN.INCORRECT) and (a.accuracy or 0) < 50


def test_18_D002_correct_answer_stays_correct():
    from tests.test_accuracy_relevance import run_real

    row, a = run_real("D-002")
    assert row["human"]["N"] == 2 and verdict(a) == AN.CORRECT and a.accuracy == 100


# ======================================================= 19-20: earlier priorities intact


@pytest.mark.parametrize("row_id", ["K-003", "E-007", "H-006"])
def test_19_priority2_guidance_rows_still_carry_no_false_contradiction(row_id):
    from tests.test_accuracy_guidance_logic import contradicted, run_real

    _, a = run_real(row_id)
    assert not contradicted(a) and verdict(a) != AN.INCORRECT


def test_20_exact_evidence_fingerprint_is_unchanged_and_every_claim_is_traced():
    from tests.test_evidence_traceability import ONE, answer, roundtrip
    from tests.test_accuracy_evaluation import PURCHASING

    out, _, _ = answer(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1] These include procedures for purchased product [1].")
    stored = roundtrip(out.evidence_snapshot)
    a = evaluate(ONE, out.answer, evidence=stored)
    assert a.evidence["provenance"] == "exact" and a.evidence["fingerprint"] == out.evidence_snapshot.fingerprint
    for c in a.checked["claims"]:
        for key in ("claim_id", "sentence_index", "normalized_text", "candidate_evidence", "selected_evidence",
                    "match_path", "support", "relevance", "operator_trace", "final"):
            assert key in c, key
    assert all("claim_status" in s for s in a.checked["claim_candidates"])


# ======================================================= the mandatory real rows


def test_F007_recovers_its_dropped_sentences_without_fragments():
    row, a = frozen("F-007")
    assert row["N"] == 1
    statuses = [c["claim_status"] for c in a.checked["claim_candidates"]]
    assert statuses.count(CL.CLAIM_STATUS_CLAIM) == 12             # all 12 sentences, 9 of them formerly dropped
    claims = a.checked["claims"]
    items = [MARK_strip(c["subclaim"]["item"]) for c in claims if c.get("subclaim")]
    assert len(claims) >= 12 and "as appropriate" not in items and "reanalysis" not in items
    reanalysis = [c for c in claims if "every 3 years" in c["claim"]]
    assert reanalysis and reanalysis[0]["final"] in (AN.SUPPORTED, AN.SUPPORTED_WITH_CITATION_DEFECT)
    assert verdict(a) == AN.PARTIAL                                # touches several contents, omits others (human N=1)


def test_E010_both_dropped_sentences_are_now_judged():
    row, a = frozen("E-010")
    assert len(a.checked["claims"]) == 3
    wrong = [c for c in a.checked["claims"] if "enforcement discretion" in c["claim"]]
    assert wrong and wrong[0]["final"] not in (AN.SUPPORTED, AN.SUPPORTED_WITH_CITATION_DEFECT)
    assert verdict(a) != AN.CORRECT


def test_G004_does_not_regress_when_its_dropped_sentences_are_judged():
    row, a = frozen("G-004")
    assert row["N"] == 2 and len(a.checked["claims"]) > 3
    assert verdict(a) == AN.CORRECT and a.accuracy == 100


def test_M020_an_enumerated_answer_is_checked_item_by_item():
    row, a = frozen("M-020")
    assert row["N"] == 2 and len(a.checked["claims"]) == 12
    assert verdict(a) == AN.CORRECT
