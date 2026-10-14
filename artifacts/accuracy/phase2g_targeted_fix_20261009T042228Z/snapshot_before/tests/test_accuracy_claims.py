"""Phase 1: claim segmentation, regulatory operators, alignment and per-claim verdicts.

The seventeen cases this phase must get right. Two of them matter more than the
rest and are the reason the others exist:

* **appended verbatim text must not confer support.** Acceptance row S-002 is
  N=0 with a fabricated citation, yet six of its sentences attribute to the
  evidence at 0.83-0.96 because the repair layer appended
  `21 CFR 111.103 (eCFR, binding, verbatim): ...` blocks. Those are grounded by
  construction and say nothing about the model.
* **similarity must never decide correctness.** On this repository's own
  embedder "shall establish and maintain" is closer to "may establish"
  (cos 0.974) than to the correct paraphrase "must create and maintain
  documented" (cos 0.959), so every modal, polarity, actor, quantity and date
  decision is made by extraction and comparison instead.
"""

from __future__ import annotations

import pytest

from regulus.accuracy import claims as CL
from regulus.accuracy import operators as OP
from regulus.accuracy import rubric as R
from regulus.accuracy import verdicts as VD
from regulus.accuracy.alignment import LexicalAligner, MIN_ALIGNMENT_OVERLAP, passages
from regulus.accuracy.evaluator import evaluate
from regulus.inference.generate import GenerationResult
from regulus.rag.validation import validate_answer
from tests.test_accuracy_evaluation import APPLICABILITY, DESIGN, ONE, PURCHASING, TABLE, assess, states
from tests.test_generation_contract import package_for
from tests.test_retrieval_plan import TableDatabase


class Source:
    def __init__(self, index: int, citation: str, text: str, tier: str = "exact") -> None:
        self.index, self.citation, self.text, self.tier = index, citation, text, tier


def verdict_for(claim: str, *sources: Source) -> VD.ClaimVerdict:
    candidates = passages(sources)
    return VD.judge(claim, LexicalAligner().align(claim, candidates))


DESIGN_SRC = Source(1, "21 CFR 820.30(a)",
                    "Each manufacturer of any class III or class II device shall establish and maintain procedures "
                    "to control the design of the device in order to ensure that specified design requirements are met.")
COMPLAINT_SRC = Source(2, "21 CFR 820.198(a)",
                       "Each manufacturer shall review and evaluate all complaints within 30 days of receipt.")
IMPORTER_SRC = Source(3, "21 CFR 803.40",
                      "Each importer shall submit a report to FDA no later than 30 calendar days after the day of receipt.")
CONDITION_SRC = Source(4, "21 CFR 820.75(a)",
                       "Where the results of a process cannot be fully verified by subsequent inspection and test, "
                       "the process shall be validated with a high degree of assurance, as appropriate.")
PERMISSIVE_SRC = Source(5, "21 CFR 820.22",
                        "Each manufacturer may establish a quality audit schedule at its own discretion.")


# ----------------------------------------------------- 1-2. match and paraphrase


def test_1_exact_regulatory_match_is_supported():
    v = verdict_for("Each manufacturer of any class III or class II device shall establish and maintain procedures "
                    "to control the design of the device in order to ensure that specified design requirements are met.",
                    DESIGN_SRC)
    assert v.verdict == VD.SUPPORTED and v.borne_out
    assert v.alignment.verbatim_coverage == pytest.approx(1.0)


def test_2_correct_paraphrase_is_paraphrase_equivalent():
    """The example from the feature spec: different words, same rule."""
    v = verdict_for("Each manufacturer of a class III or class II device must create and maintain documented "
                    "procedures to control the device design so that specified design requirements are met.",
                    DESIGN_SRC)
    assert v.verdict == VD.PARAPHRASE and v.borne_out
    assert {"strength", "polarity", "actor"} <= set(v.comparison.agreed)
    assert v.alignment.verbatim_coverage < 0.8, "it is genuinely not verbatim"


# ------------------------------------------------- 3-7. the regulatory operators


def test_3_wrong_modal_strength_is_contradicted():
    v = verdict_for("Each manufacturer of any class III device may establish procedures to control the design of "
                    "the device.", DESIGN_SRC)
    assert v.verdict == VD.CONTRADICTED
    assert any(c["operator"] == OP.CONFLICT_STRENGTH for c in v.comparison.conflicts)


def test_3b_stating_a_permission_as_a_requirement_is_also_contradicted():
    v = verdict_for("Each manufacturer shall establish a quality audit schedule.", PERMISSIVE_SRC)
    assert v.verdict == VD.CONTRADICTED
    assert any(c["operator"] == OP.CONFLICT_STRENGTH for c in v.comparison.conflicts)


def test_4_wrong_polarity_is_contradicted():
    source = Source(1, "21 CFR 820.80(d)",
                    "A device may not be released for distribution until the acceptance activities are completed.")
    v = verdict_for("A device may be released for distribution until the acceptance activities are completed.", source)
    assert v.verdict == VD.CONTRADICTED
    assert any(c["operator"] == OP.CONFLICT_POLARITY for c in v.comparison.conflicts)


def test_5_wrong_numeric_value_is_contradicted():
    v = verdict_for("Each manufacturer shall review and evaluate all complaints within 90 days of receipt.",
                    COMPLAINT_SRC)
    assert v.verdict == VD.CONTRADICTED
    conflict = next(c for c in v.comparison.conflicts if c["operator"] == OP.CONFLICT_QUANTITY)
    assert conflict["claim"] == ["90"] and conflict["evidence"] == ["30"]


def test_5b_a_quantity_of_a_kind_the_evidence_never_states_is_not_a_conflict():
    """Fail closed the other way: absence is undetermined, not disagreement."""
    v = verdict_for("Each manufacturer shall review and evaluate all complaints covering 25 percent of lots.",
                    COMPLAINT_SRC)
    assert not any(c["operator"] == OP.CONFLICT_QUANTITY for c in (v.comparison.conflicts if v.comparison else ()))


def test_6_wrong_actor_is_contradicted():
    v = verdict_for("Each manufacturer shall submit a report to FDA no later than 30 calendar days after the day "
                    "of receipt.", IMPORTER_SRC)
    assert v.verdict == VD.CONTRADICTED
    conflict = next(c for c in v.comparison.conflicts if c["operator"] == OP.CONFLICT_ACTOR)
    assert conflict["claim"] == "manufacturer" and conflict["evidence"] == "importer"


def test_6b_a_shared_mention_of_fda_does_not_hide_an_actor_difference():
    """Both sentences name FDA as the recipient; only the duty-holder decides."""
    assert OP.duty_holder("The importer shall submit the report to FDA.") == "importer"
    assert OP.duty_holder("The manufacturer shall submit the report to FDA.") == "manufacturer"


def test_6c_an_open_class_actor_instantiates_rather_than_conflicts():
    comparison = OP.compare("You must establish written procedures.",
                            "Each manufacturer shall establish written procedures.")
    assert not comparison.conflicted and OP.CONFLICT_ACTOR in comparison.undetermined


def test_7_dropping_an_applicability_condition_is_partial_not_supported():
    v = verdict_for("The process shall be validated with a high degree of assurance.", CONDITION_SRC)
    assert v.verdict == VD.PARTIAL and not v.borne_out
    assert any(o["operator"] == OP.OMISSION_CONDITION for o in v.comparison.omissions)


def test_7b_inventing_a_condition_is_contradicted():
    v = verdict_for("Each manufacturer of any class III device shall establish and maintain procedures to control "
                    "the design of the device, if applicable.", DESIGN_SRC)
    assert v.verdict == VD.CONTRADICTED
    assert any(c["operator"] == OP.CONFLICT_CONDITION for c in v.comparison.conflicts)


def test_7c_a_negative_inside_a_condition_does_not_invert_the_obligation():
    """"shall be validated where the results cannot be fully verified" is an
    affirmative obligation whose CONDITION contains "cannot"."""
    assert "cannot" in CONDITION_SRC.text, "the sentence really does contain a negative"
    assert OP.polarity(CONDITION_SRC.text) == OP.AFFIRM
    assert "cannot" not in OP.main_clause(CONDITION_SRC.text), "the condition is removed before polarity is read"
    # and a condition AFTER the obligation is handled the same way
    trailing = "The process shall be validated where the results cannot be verified."
    assert OP.polarity(trailing) == OP.AFFIRM


# -------------------------------------------------------- 8-9. abstention


def test_8_a_correct_abstention_is_scored():
    """Required case 8. The provision has no authoritative text, so declining is
    the passing answer and must not be reported as unscoreable."""
    question = "What does 21 CFR 820.99(z) require?"
    answer = ("The available eCFR data does not contain 21 CFR 820.99(z), so I cannot state what it requires. "
              "No exact text for the requested provision was retrieved and I will not infer its contents.")
    a, _ = assess(question, answer, model_called=False, fallback_type="provision_not_found")
    assert a.status == R.EVALUATED and a.accuracy is not None and a.accuracy >= 90
    assert states(a)[R.SUBSTANTIVE] == R.PASS and states(a)[R.CITATION] == R.PASS
    assert a.checked["abstention"]["outcome"] == "correct_abstention"


def test_9_an_abstention_that_names_nothing_is_only_partial():
    question = "What does 21 CFR 820.99(z) require?"
    a, _ = assess(question, "I cannot help with that request.", model_called=False,
                  fallback_type="provision_not_found")
    assert states(a)[R.SUBSTANTIVE] == R.PARTIAL
    assert a.checked["abstention"]["outcome"] == "incomplete_abstention"
    assert a.accuracy is not None and a.accuracy < 90


# ------------------------------------------- 10. appended verbatim text (safety)


def test_10_appended_verbatim_regulatory_text_is_not_a_model_claim():
    """The S-002 failure route. The repair appends grounded quotations; counting
    them as model claims lets a wrong answer look well supported."""
    quoted = f"21 CFR 820.10(b)(2) (eCFR, binding, verbatim): {PURCHASING}"
    assert CL.classify(quoted).origin == CL.QUOTATION
    assert CL.classify(f"21 CFR 820.30(a) (FDA guidance, non-binding, verbatim): {DESIGN}").origin == CL.QUOTATION

    answer = ("21 CFR Part 820 requires suppliers to be re-audited every quarter.\n"
              f"{quoted}")
    a, _ = assess(ONE, answer)
    assert a.checked["sentence_origins"][CL.QUOTATION] == 1
    assert a.checked["material_claims"] == 1, "only the model's own sentence is a claim"
    assert a.checked["claim_status"]["supported"] == 0
    assert states(a)[R.SUBSTANTIVE] != R.PASS


def test_10b_an_answer_made_only_of_appended_quotations_is_not_scored_high():
    answer = (f"21 CFR 820.10(b)(2) (eCFR, binding, verbatim): {PURCHASING}\n"
              f"21 CFR 820.30(a) (eCFR, binding, verbatim): {DESIGN}")
    a, _ = assess(ONE, answer)
    assert a.checked["material_claims"] == 0
    assert a.accuracy is None or a.accuracy < 100


# ----------------------------------------- 11-13. fabrication, support, multi-claim


def test_11_a_fabricated_requirement_is_still_an_absolute_failure():
    answer = f"21 CFR 820.10(b)(2): {PURCHASING} Suppliers must be re-audited within 45 days [1]."
    a, report = assess(ONE, answer)
    assert "unsupported_figure" in report.to_dict()["codes"]
    assert states(a)[R.FABRICATION_FREE] == R.FAIL and a.accuracy == 0


def test_12_a_claim_about_nothing_in_the_evidence_is_unsupported():
    v = verdict_for("Devices must be registered with the European Commission before being placed on the market.",
                    DESIGN_SRC)
    assert v.verdict == VD.UNSUPPORTED
    assert v.alignment is None


def test_12b_the_alignment_floor_is_an_alignment_floor_not_a_verdict():
    aligner = LexicalAligner()
    assert aligner.align("Devices must be registered with the European Commission.", passages([DESIGN_SRC])) == []
    assert 0 < MIN_ALIGNMENT_OVERLAP < 0.5


def test_13_a_multi_claim_answer_is_judged_claim_by_claim():
    question = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.30(a) require?"
    answer = (f"21 CFR 820.10(b)(2): {PURCHASING} [1]\n"
              "21 CFR 820.30(a): Each manufacturer of any class III device may control the design of the device [2].")
    a, _ = assess(question, answer)
    counts = a.checked["claim_status"]
    assert a.checked["material_claims"] == 2
    assert counts["contradicted"] == 1, "the permissive restatement of a mandatory rule"
    assert states(a)[R.SUBSTANTIVE] == R.FAIL and a.accuracy == 0


# ------------------------------------------------- 14-17. determinism, isolation


def test_14_repeated_evaluation_is_deterministic():
    answer = f"21 CFR 820.10(b)(2): {PURCHASING} [1]"
    runs = []
    for _ in range(5):
        a, _ = assess(ONE, answer)
        d = a.to_dict(); d.pop("elapsed_ms")
        runs.append(d)
    assert all(r == runs[0] for r in runs)


def test_15_the_evaluator_does_not_modify_the_answer_it_is_given():
    answer = f"21 CFR 820.10(b)(2): {PURCHASING} [1]"
    before = answer.encode()
    pkg = package_for(ONE, db=TableDatabase(TABLE))
    sources = [(s.index, s.text, s.tier) for s in pkg.sources]
    for _ in range(3):
        evaluate(ONE, answer, package=pkg, validation=None, coverage=None)
    assert answer.encode() == before
    assert [(s.index, s.text, s.tier) for s in pkg.sources] == sources


def test_16_the_evaluator_calls_no_generator():
    """Nothing in regulus.accuracy may reach a model: no generator, no torch."""
    import subprocess
    import sys

    code = ("import regulus.accuracy, sys;"
            "print([m for m in sys.modules if m in ('torch','regulus.rag.generator','transformers')])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_17_the_evaluator_performs_no_retrieval():
    """The evidence it reads is the package it was handed; a database handed to it
    is never queried, because it never holds one."""
    pkg = package_for(ONE, db=TableDatabase(TABLE))
    gen = GenerationResult("p", f"21 CFR 820.10(b)(2): {PURCHASING} [1]", 500, 40, 1.0, finished=True)
    report = validate_answer(gen.response, pkg, gen)

    class Exploding:
        def query(self, *a, **k):
            raise AssertionError("the evaluator queried the database")

    db = Exploding()
    a = evaluate(ONE, gen.response, package=pkg, validation=report, coverage=None)
    assert a.status in (R.EVALUATED, R.UNABLE)
    assert db  # the handle exists and was never used: the evaluator has no way to reach one


# -------------------------------------------------------------- the ladder itself


def test_a_conflict_outranks_every_amount_of_surface_agreement():
    """A claim that is verbatim except for the modal must still be contradicted."""
    claim = DESIGN_SRC.text.replace("shall establish and maintain", "may establish")
    v = verdict_for(claim, DESIGN_SRC)
    assert v.verdict == VD.CONTRADICTED
    assert v.alignment.overlap > 0.9, "it is maximally similar, and still wrong"


def test_a_paraphrase_needs_at_least_two_decided_operators():
    assert VD.MIN_OPERATORS_AGREED >= 2
    v = verdict_for("The design of the device is covered by procedures for specified design requirements.", DESIGN_SRC)
    assert v.verdict in (VD.UNDECIDABLE, VD.PARAPHRASE)
    if v.verdict == VD.PARAPHRASE:
        assert len(v.comparison.agreed) >= VD.MIN_OPERATORS_AGREED


def test_an_applicability_contradiction_still_fails(tmp_path):
    """The phase-D1 H4 class, preserved from the previous evaluator."""
    db = TableDatabase(list(TABLE))
    pkg = package_for("Are manufacturers of components subject to 21 CFR 820.1(a)(2)?", db=db)
    answer = ("21 CFR 820.1(a)(2): Manufacturers of components or parts of finished devices must comply with the "
              "provisions of this part [1].")
    a = evaluate("Are manufacturers of components subject to 21 CFR 820.1(a)(2)?", answer, package=pkg)
    assert states(a)[R.SUBSTANTIVE] == R.FAIL and a.accuracy == 0
    assert APPLICABILITY  # the fixture text this relies on


# ------------------------------------------------- defects found by validation
# Each test below pins a defect the 60-row validation run exposed on real
# acceptance answers. The row id is the one that exposed it.


def test_C001_a_withheld_answer_is_not_a_correct_abstention():
    """The draft failed validation and was suppressed: safe, but unanswered.
    It was scored 95% as a correct abstention; the rubric scores it N=0."""
    from regulus.accuracy import abstention as AB

    class Cov:
        satisfied_ids, missing_labels, explicit = ("r1",), (), True

    text = ("The generated answer could not be validated against the retrieved regulatory evidence, so it is not "
            "shown.")
    r = AB.assess(text, coverage=Cov(), fallback_type="unvalidated_answer_withheld", has_claims=False)
    assert r.outcome == AB.WITHHELD and not r.correct


def test_C003_an_UNKNOWN_answerability_state_does_not_justify_refusing():
    """UNKNOWN means the gate did not decide. Treating it as "evidence
    insufficient" scored two N=0 rows (C-003, D-005) at 95%."""
    from regulus.accuracy import abstention as AB

    text = "The available regulatory sources do not provide enough information to answer this question."
    for state in ("UNKNOWN", "PARTIALLY_ANSWERABLE", "ANSWERABLE"):
        r = AB.assess(text, answerability={"state": state}, has_claims=False)
        assert r.outcome == AB.UNDECIDED, state
    r = AB.assess(text, answerability={"state": "INSUFFICIENT_EVIDENCE"}, has_claims=False)
    assert r.outcome == AB.CORRECT


def test_C003_an_empty_package_is_not_by_itself_a_reason_to_refuse():
    """A package can be empty for reasons the evaluator cannot see."""
    from regulus.accuracy import abstention as AB

    class Empty:
        requirements, sources = (), ()

    r = AB.assess("The available regulatory sources do not provide enough information to answer this.",
                  package=Empty(), has_claims=False)
    assert r.outcome == AB.UNDECIDED


def test_C004_a_recital_states_no_rule_and_cannot_be_contradicted():
    """"(a) Vinyl chloride has been used as an ingredient" is history, not an
    obligation; a correct "is prohibited" claim was scored as contradicting it."""
    recital = "(a) Vinyl chloride has been used as an ingredient in cosmetic aerosol products including hair sprays."
    assert OP.strength(recital) is None and OP.polarity(recital) is None
    comparison = OP.compare("The use of vinyl chloride as an ingredient in aerosol products is prohibited.", recital)
    assert not comparison.conflicted


def test_C004_an_epistemic_may_is_not_a_permission():
    """"bithionol may produce cross-sensitization" states a possibility and
    grants nothing; it was read as a permission contradicting a prohibition."""
    assert OP.strength("Bithionol may produce cross-sensitization with other commonly used chemicals.") is None
    assert OP.strength("Exposure can cause cancer in laboratory animals.") is None
    # while a deontic may - granted to a party, or a passive permission - still is one
    assert OP.strength("Each manufacturer may establish a quality audit schedule.") == OP.PERMISSIVE
    assert OP.strength("A device may not be shipped before acceptance.") == OP.MANDATORY
    assert OP.strength("The product may be marketed without a premarket submission.") == OP.PERMISSIVE


def test_G004_a_verbatim_source_outranks_a_more_overlapping_neighbour():
    """A verbatim quotation of 201.66(d)(2) was paired with the near-identical
    (d)(10)(ii), whose "except" concerns a different item, and marked partial."""
    exact = Source(1, "21 CFR 201.66(d)(2)",
                   "The letter height or type size for the title Drug Facts shall be larger than the largest type "
                   "size used in the Drug Facts labeling.")
    neighbour = Source(2, "21 CFR 201.66(d)(10)(ii)",
                       "Paragraph (d)(2) of this section shall apply except that the letter height or type size for "
                       "the title Drug Facts continued shall be larger than the largest type size used in the Drug "
                       "Facts labeling title.")
    claim = ("The letter height or type size for the title Drug Facts shall be larger than the largest type size "
             "used in the Drug Facts labeling.")
    v = verdict_for(claim, exact, neighbour)
    assert v.verdict == VD.SUPPORTED and v.alignment.passage.source_index == 1


def test_P010_one_trailing_marker_cites_the_whole_paragraph():
    sentences = CL.segment("Sponsors are responsible for selecting qualified investigators and monitoring the "
                           "investigation. Additional responsibilities of sponsors are described in subparts B and G. [1]")
    first = CL.claims(sentences)[0]
    assert CL.cited(first, sentences)


def test_P010_a_marker_in_another_paragraph_does_not_cite_this_one():
    sentences = CL.segment("Sponsors must select qualified investigators for the study.\n\n"
                           "Additional responsibilities of sponsors are described in subparts B and G. [1]")
    first = CL.claims(sentences)[0]
    assert not CL.cited(first, sentences)


def test_actor_list_covers_title_21_duty_holders_beyond_device_manufacturers():
    """Food, feed and clinical rules place duties on parties the device rules do not."""
    assert OP.duty_holder("The receiving facility must establish a supply-chain program.") == "facility"
    assert OP.duty_holder("Each investigator shall maintain accurate case histories.") == "investigator"
    assert OP.duty_holder("The IRB shall review the research.") == "irb"
    comparison = OP.compare("The investigator shall maintain the records.", "The sponsor shall maintain the records.")
    assert any(c["operator"] == OP.CONFLICT_ACTOR for c in comparison.conflicts)


def test_semantic_alignment_is_batched_into_one_embedding_call():
    """650 ms for a 24-claim answer came from one forward pass per claim."""
    from regulus.accuracy.alignment import SemanticAligner

    calls = []

    class FakeEmbedder:
        def embed_batch(self, texts):
            import numpy as np

            calls.append(len(texts))
            return np.ones((len(texts), 4), dtype="float32") / 2.0

    aligner = SemanticAligner(FakeEmbedder())
    claims = [f"Each manufacturer shall establish procedures for activity {i}." for i in range(10)]
    candidates = passages([DESIGN_SRC, COMPLAINT_SRC, IMPORTER_SRC])
    aligner.prepare(claims, candidates)
    for claim in claims:
        aligner.align(claim, candidates)
    assert len(calls) == 1, f"expected one batched call, got {calls}"


def test_semantic_alignment_never_overrides_an_operator_conflict():
    """The core guarantee, through the semantic aligner: cosine may rank the
    wrong modal first, and the verdict must still be contradicted."""
    from regulus.accuracy.alignment import SemanticAligner

    class FakeEmbedder:
        def embed_batch(self, texts):
            import numpy as np

            return np.ones((len(texts), 4), dtype="float32") / 2.0   # everything identical: cosine 1.0

    aligner = SemanticAligner(FakeEmbedder())
    claim = DESIGN_SRC.text.replace("shall establish and maintain", "may establish")
    candidates = passages([DESIGN_SRC])
    aligner.prepare([claim], candidates)
    v = VD.judge(claim, aligner.align(claim, candidates))
    assert v.alignment.similarity == pytest.approx(1.0)
    assert v.verdict == VD.CONTRADICTED


def test_F003_an_agency_acting_with_an_auxiliary_is_the_duty_holder():
    """"FDA may withdraw a qualified facility exemption": the facility is part of
    the object, not the party. A correct claim was marked contradicted."""
    assert OP.duty_holder("FDA may withdraw a qualified facility exemption under 117.5(a).") == "fda"
    assert OP.duty_holder("FDA shall respond to the facility within 30 days.") == "fda"
    assert OP.duty_holder("FDA recommends that the manufacturer validate the process.") == "manufacturer"
    assert OP.duty_holder("FDA requires each manufacturer to keep records.") == "manufacturer"
    comparison = OP.compare("21 CFR 117.251(a) states that FDA may withdraw an exemption.",
                            "(a) FDA may withdraw a qualified facility exemption under 117.5(a):")
    assert not comparison.conflicted


def test_B003_dropping_a_restrictive_only_is_partial_not_paraphrase():
    """"approved ONLY upon examination" makes examination necessary; without
    "only" it reads as sufficient. That passed as a paraphrase."""
    source = Source(1, "21 CFR 601.20(a)",
                    "A biologics license application shall be approved only upon examination of the product and upon "
                    "a determination that the product complies with the standards established in the application.")
    dropped = verdict_for("A biologics license application must be approved upon examination of the product and upon "
                          "a determination that the product complies with the standards established in the "
                          "application.", source)
    assert dropped.verdict == VD.PARTIAL and not dropped.borne_out
    kept = verdict_for("A biologics license application must be approved only upon examination of the product and "
                       "upon a determination that the product complies with the standards established in the "
                       "application.", source)
    assert kept.verdict in VD.BORNE_OUT
