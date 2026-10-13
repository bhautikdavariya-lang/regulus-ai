"""Live answer-accuracy assessment (regulus.accuracy).

The evaluator is an observer: every test here builds a real GenerationPackage
from the in-memory table, runs the real Stage 4/7 validator over a scripted
answer, and then assesses the delivered text. Nothing is mocked except the
answer itself, which is scripted so that each failure mode is exercised on
purpose.

The cases are the ones the feature must get right, and one of them is the
measured failure that motivated the whole design: an answer that contradicts
the applicability rule in its own evidence, which bag-of-words recall scored as
a pass (docs/STAGE_A_VALIDATOR_LIMITATION.md §3).
"""

from regulus.accuracy import (
    ATTRIBUTED_EXACT,
    EVALUATED,
    EVALUATOR_ERROR,
    FAIL,
    NOT_APPLICABLE,
    NOT_ESTABLISHED,
    NOT_SCORED,
    PARTIAL,
    PASS,
    RUBRIC_ID,
    UNABLE,
    attribute,
    evaluate,
    evaluate_safely,
)
from regulus.accuracy import rubric as R
from regulus.accuracy.attribution import ATTRIBUTION_MIN_COVERAGE, UNATTRIBUTED
from regulus.inference.generate import GenerationResult
from regulus.rag.coverage import check_coverage
from regulus.rag.validation import validate_answer
from tests.test_generation_contract import package_for
from tests.test_retrieval_plan import TableDatabase, row

# -- a table whose text is real regulatory wording, so verbatim attribution means something

PURCHASING = ("Each manufacturer shall establish and maintain procedures to ensure that all purchased or otherwise "
              "received product and services conform to specified requirements.")
DESIGN = ("Each manufacturer of any class III or class II device shall establish and maintain procedures to control "
          "the design of the device in order to ensure that specified design requirements are met.")
APPLICABILITY = ("The provisions of this part do not apply to manufacturers of components or parts of finished "
                 "devices, but such manufacturers are encouraged to use appropriate provisions of this part as "
                 "guidance.")

TABLE = [
    row("820.10", "", 0, text="General provisions for the quality system."),
    row("820.10", "(b)", 1, text="Purchasing controls."),
    row("820.10", "(b)(2)", 2, text=PURCHASING),
    row("820.10", "(b)(4)", 3, text="Each manufacturer shall maintain records of acceptable suppliers."),
    row("820.30", "", 0, text="Design controls."),
    row("820.30", "(a)", 1, text=DESIGN),
    row("820.1", "", 0, text="Scope."),
    row("820.1", "(a)(2)", 1, text=APPLICABILITY),
]

ONE = "What does 21 CFR 820.10(b)(2) require?"
TWO = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.30(a) require?"
APPLIES = "Are manufacturers of components subject to 21 CFR 820.1(a)(2)?"


def db():
    return TableDatabase(TABLE)


def assess(question, answer, *, package=None, tokens=60, finished=True, **kwargs):
    """Build the package, run the real validator, then assess the answer."""
    pkg = package if package is not None else package_for(question, db=db())
    gen = GenerationResult("p", answer, 500, tokens, 1.0, finished=finished)
    report = validate_answer(answer, pkg, gen)
    return evaluate(question, answer, package=pkg, validation=report, coverage=_coverage(question), **kwargs), report


def _coverage(question):
    from regulus.planning import plan_query
    from regulus.retrieval import LexicalRetriever

    out = LexicalRetriever(db()).run_plan(plan_query(question), top_k=8)
    return check_coverage(out.registry)


def states(assessment):
    return assessment.states


def states_detail(assessment, dimension):
    return next(d.detail for d in assessment.dimensions if d.dimension == dimension)


# ------------------------------------------------------------ the rubric itself


def test_rubric_is_not_the_acceptance_rubric():
    """§8: the live score must never be presented as the contractual one."""
    assert RUBRIC_ID == "regulus_live_evidence_assessment_v2" != "regulus_substantive_rubric_v1"
    assert R.RUBRIC.to_dict()["is_acceptance_rubric"] is False
    assert "not the 300-question" in R.NOT_THE_BENCHMARK


def test_score_is_deterministic_and_documented():
    all_pass = {d: PASS for d in R.DIMENSIONS}
    assert R.score(all_pass) == 100
    # a serious failure is not averaged away by five passes
    assert R.score({**all_pass, R.FABRICATION_FREE: FAIL}) == 0
    assert R.score({**all_pass, R.SUBSTANTIVE: FAIL}) == 0
    # a minor completeness issue costs much less than a wrong citation
    assert R.score({**all_pass, R.COMPLETENESS: PARTIAL}) == 90
    assert R.score({**all_pass, R.CITATION: FAIL}) == 60
    assert R.deduction(R.COMPLETENESS, PARTIAL) < R.deduction(R.CITATION, FAIL) < R.deduction(R.FABRICATION_FREE, FAIL)


def test_the_same_inputs_always_give_the_same_score():
    a, _ = assess(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]")
    b, _ = assess(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]")
    assert (a.status, a.accuracy, states(a)) == (b.status, b.accuracy, states(b))


# ------------------------------------------------------------ attribution


def test_verbatim_attribution_sees_a_reversed_applicability_rule():
    """The measured failure of bag-of-words recall. Same words, opposite rule."""
    pkg = package_for(APPLIES, db=db())
    source = next(s for s in pkg.sources if "do not apply" in s.text)
    wrong = attribute("Manufacturers of components or parts of finished devices are subject to this part.", [source])
    right = attribute(APPLICABILITY, [source])
    assert wrong.grade == UNATTRIBUTED and wrong.coverage < ATTRIBUTION_MIN_COVERAGE
    assert right.grade == ATTRIBUTED_EXACT and right.coverage == 1.0


def test_a_fragment_of_a_source_does_not_attribute_a_long_claim():
    pkg = package_for(ONE, db=db())
    a = attribute("Each manufacturer shall establish and maintain procedures, and must also notify the agency within "
                  "thirty days of any supplier change.", pkg.sources)
    assert a.grade == UNATTRIBUTED and a.run_words >= 6  # a real run, but it does not cover the claim


# ------------------------------------------------------------ 13. the required cases


def test_correct_answer_scores_high():
    a, report = assess(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]")
    assert report.ok, report.to_dict()["codes"]
    assert a.status == EVALUATED and a.accuracy == 100
    assert states(a)[R.SUBSTANTIVE] == PASS and states(a)[R.EVIDENCE_SUPPORT] == PASS
    assert states(a)[R.CITATION] == PASS and states(a)[R.FABRICATION_FREE] == PASS
    assert states(a)[R.COMPLETENESS] == PASS and states(a)[R.SCOPE] == PASS
    assert a.checked["claim_status"]["supported"] == a.checked["material_claims"] == 1
    assert a.checked["answer_verdict"]["verdict"] == "correct"


def test_correct_answer_with_a_minor_omission_reduces_completeness_only():
    """A requested provision with no authoritative text, disclosed by the answer."""
    question = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.99(z) require?"
    answer = (f"21 CFR 820.10(b)(2): {PURCHASING} [1]\n"
              "Not found in the available eCFR data: 21 CFR 820.99(z). The answer above covers only the "
              "provisions that were retrieved.")
    a, _ = assess(question, answer)
    assert states(a)[R.COMPLETENESS] == PARTIAL
    assert states(a)[R.SUBSTANTIVE] == PASS
    assert a.status == EVALUATED and a.accuracy == 100 - R.deduction(R.COMPLETENESS, PARTIAL)
    # the answer did all it could and said so: correct, with completeness partial
    assert a.checked["answer_verdict"]["verdict"] == "correct"
    assert "820.99(z)" in states_detail(a, R.COMPLETENESS)


def test_an_undisclosed_omission_fails_completeness():
    question = "What do 21 CFR 820.10(b)(2) and 21 CFR 820.99(z) require?"
    a, _ = assess(question, f"21 CFR 820.10(b)(2): {PURCHASING} [1]")
    assert states(a)[R.COMPLETENESS] == FAIL


def test_incorrect_regulatory_claim_fails_substantive_correctness():
    answer = ("21 CFR 820.1(a)(2): Manufacturers of components or parts of finished devices must comply with the "
              "provisions of this part [1].")
    a, _ = assess(APPLIES, answer)
    assert states(a)[R.SUBSTANTIVE] == FAIL
    assert a.status == EVALUATED and a.accuracy == 0
    assert a.checked["answer_verdict"]["verdict"] == "incorrect"
    # decided on the claim itself: "must comply" against "do not apply to"
    assert any(c["final"] == "contradicted" for c in a.checked["claims"])


def test_fabricated_requirement_is_detected():
    answer = (f"21 CFR 820.10(b)(2): {PURCHASING} Suppliers must be re-audited within 45 days of any "
              "nonconformance [1].")
    a, report = assess(ONE, answer)
    assert "unsupported_figure" in report.to_dict()["codes"]
    assert states(a)[R.FABRICATION_FREE] == FAIL
    assert a.status == EVALUATED and a.accuracy == 0


def test_a_section_the_snapshot_does_not_contain_is_fabrication():
    class Index:
        def section_status(self, section):
            return (False, False)      # verified absent in the snapshot

    answer = f"21 CFR 820.10(b)(2): {PURCHASING} [1] This duty is restated in 21 CFR 820.777."
    a, _ = assess(ONE, answer, identifier_index=Index())
    assert states(a)[R.FABRICATION_FREE] == FAIL and "820.777" in a.reason
    assert a.checked["identifiers_verified_absent"] == 1


def test_a_section_that_cannot_be_checked_is_not_called_fabricated():
    """Without an index, an unaccounted-for section is unverifiable, not invented."""
    answer = f"21 CFR 820.10(b)(2): {PURCHASING} [1] This duty is restated in 21 CFR 820.777."
    a, _ = assess(ONE, answer)
    assert states(a)[R.FABRICATION_FREE] == NOT_ESTABLISHED
    assert "cannot verify" in states_detail(a, R.FABRICATION_FREE)
    # the unverifiable statement counts against "correct": it is not ignored
    assert a.checked["answer_verdict"]["verdict"] == "partial"
    assert "could not be verified" in a.checked["answer_verdict"]["reason"]


def test_an_absolute_failure_is_scored_even_when_substance_is_undecided():
    """A measured fabrication is a verdict; an undecided paraphrase is not."""
    class Index:
        def section_status(self, section):
            return (False, False)

    answer = "21 CFR 820.10(b)(2) obliges a maker to check bought-in goods, as does 21 CFR 820.777 [1]."
    a, _ = assess(ONE, answer, identifier_index=Index())
    assert states(a)[R.FABRICATION_FREE] == FAIL
    assert a.status == EVALUATED and a.accuracy == 0
    assert a.checked["answer_verdict"]["verdict"] == "incorrect"


def test_wrong_citation_fails_citation_correctness():
    """The sentence is about 820.10(b)(2) but cites the design-control source."""
    pkg = package_for(TWO, db=db())
    design = next(s for s in pkg.sources if "design" in (s.text or "").lower())
    answer = f"21 CFR 820.10(b)(2): {PURCHASING} [{design.index}]\n21 CFR 820.30(a): {DESIGN} [{design.index}]"
    a, report = assess(TWO, answer, package=pkg)
    assert {"citation_mismatch", "provision_citation_mismatch"} & set(report.to_dict()["codes"])
    assert states(a)[R.CITATION] == FAIL
    assert a.accuracy is None or a.accuracy <= 100 - R.deduction(R.CITATION, FAIL)


def test_an_uncited_requirement_fails_citation_correctness():
    """No marker, and no provision named in the statement: rubric L=0."""
    a, _ = assess(ONE, PURCHASING)
    assert states(a)[R.CITATION] == FAIL
    assert "carries no citation" in states_detail(a, R.CITATION)
    # a citation defect is not a substantive defect
    assert a.checked["claims"][0]["final"] == "supported_with_citation_defect"


def test_a_statement_that_names_its_provision_in_line_is_cited():
    """"21 CFR 820.10(b)(2): <text>" names the section the statement comes from,
    which is how the rubric's own scorer reads it."""
    a, _ = assess(ONE, f"21 CFR 820.10(b)(2): {PURCHASING}")
    assert states(a)[R.CITATION] == PASS


def test_one_paragraph_final_marker_cites_its_paragraph():
    """Acceptance row P-010 cites a whole paragraph with one trailing [1] and was
    scored L=1; the statements before the marker are cited by it."""
    answer = (f"Each manufacturer must establish purchasing procedures. {PURCHASING} [1]")
    a, _ = assess(ONE, answer)
    assert states(a)[R.CITATION] == PASS


def test_out_of_scope_answer_fails_scope():
    answer = (f"21 CFR 820.10(b)(2): {PURCHASING} [1] We recommend you consult counsel, and following this will "
              "guarantee compliance with the regulation.")
    a, _ = assess(ONE, answer)
    assert states(a)[R.SCOPE] == FAIL
    assert a.accuracy is None or a.accuracy <= 100 - R.deduction(R.SCOPE, FAIL)


def test_a_question_decided_out_of_scope_and_answered_anyway_fails_scope():
    a, _ = assess(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]", scope_status="out_of_scope", model_called=True)
    assert states(a)[R.SCOPE] == FAIL


def test_insufficient_evidence_gives_no_number():
    """§6: lack of evidence is never 0% and never 100%."""
    a = evaluate("What does 21 CFR 314.999 require?", "Some answer.", package=None)
    assert a.status == UNABLE and a.accuracy is None
    assert "nothing to assess" in a.reason
    assert all(d.state == NOT_ESTABLISHED for d in a.dimensions)


def test_a_paraphrase_whose_operators_all_agree_is_scored():
    """Phase 1: a close paraphrase of the provision is now decided, not abstained,
    because every regulatory operator that could be extracted agrees with it."""
    answer = ("21 CFR 820.10(b)(2): Each manufacturer must establish and maintain procedures to ensure that all "
              "purchased or otherwise received product and services conform to specified requirements [1].")
    a, _ = assess(ONE, answer)
    assert states(a)[R.SUBSTANTIVE] in (PASS, R.PARTIAL)
    assert a.status == EVALUATED and a.accuracy is not None
    status = a.checked["claim_status"]
    assert status["supported"] == a.checked["material_claims"]


def test_a_statement_with_too_few_decidable_operators_still_abstains():
    """Fail closed: when almost nothing about the claim can be compared with the
    evidence, the answer is undecidable rather than generously scored."""
    answer = "21 CFR 820.10(b)(2) is the governing provision for this topic [1]."
    a, _ = assess(ONE, answer)
    assert states(a)[R.SUBSTANTIVE] == NOT_ESTABLISHED
    assert a.status == UNABLE and a.accuracy is None


def test_an_incorrect_abstention_fails_rather_than_abstaining():
    """Required case 9. The requested provision HAD authoritative text, so
    declining left the question unanswered: the rubric scores that N=0."""
    answer = ("The available regulatory sources do not provide enough information to answer this. No sufficiently "
              "relevant eCFR or FDA guidance passage was retrieved for the question.")
    a, _ = assess(ONE, answer, model_called=False)
    assert a.status == EVALUATED and a.accuracy == 0
    assert states(a)[R.SUBSTANTIVE] == FAIL
    assert a.checked["abstention"]["outcome"] == "incorrect_abstention"


def test_evaluator_failure_is_isolated():
    """§12: the evaluator may fail; the answer is unaffected and nothing is claimed."""
    class Exploding:
        @property
        def sources(self):
            raise RuntimeError("/private/path/leaked boom")

    a = evaluate_safely(ONE, "an answer the user still sees", package=Exploding())
    assert a.status == EVALUATOR_ERROR and a.accuracy is None
    assert "answer itself is unaffected" in a.reason
    assert "/private/path" not in a.reason          # sanitised, like every other server-side error
    assert all(d.state == NOT_ESTABLISHED for d in a.dimensions)


# ------------------------------------------------------------ the payload shape


def test_the_result_has_the_documented_flat_shape():
    a, _ = assess(ONE, f"21 CFR 820.10(b)(2): {PURCHASING} [1]")
    d = a.to_dict()
    assert d["status"] == "evaluated" and d["accuracy"] == 100
    for dimension in R.DIMENSIONS:
        assert d[dimension] in (True, False, PARTIAL, None)
    assert d["substantive_correctness"] is True and d["rubric_id"] == RUBRIC_ID
    assert d["elapsed_ms"] >= 0 and d["checked"]["sources"] > 0
    assert len(d["dimensions"]) == len(R.DIMENSIONS)


def test_unable_to_determine_serialises_with_a_null_accuracy():
    d = evaluate(ONE, "x", package=None).to_dict()
    assert d == {**d, "status": "unable_to_determine", "accuracy": None}
    assert all(d[dim] is None for dim in R.DIMENSIONS)


# ------------------------------------------------------------ the pipeline's own sentences


def test_sentences_the_pipeline_appended_are_not_scored_as_the_model_s_claims():
    """The Stage 5 limitation note, the unresolved-provision statement and the
    mixed-scope note are appended AFTER validation, so they are the only text in
    a delivered answer that no ValidationReport describes. They are the
    pipeline's wording, not claims about the evidence, and must not be assessed
    as if the model had written them."""
    from regulus.accuracy.claims import MODEL, classify
    from regulus.rag.answer_quality import mixed_scope_note
    from regulus.rag.prompt import NO_CONTEXT_ANSWER, incomplete_coverage_answer, unresolved_provisions_statement

    appended = [
        "The retrieved evidence does not establish the temperature range asked for.",
        'The available regulatory sources do not cover "the EU MDR".',
        mixed_scope_note("the EU MDR"),
        unresolved_provisions_statement(("21 CFR 820.99(z)",)),
        incomplete_coverage_answer(("21 CFR 820.99(z)",)),
        NO_CONTEXT_ANSWER,
        "The generated answer could not be validated against the retrieved regulatory evidence, so it is not shown.",
    ]
    from regulus.evaluation.grounding_eval import split_sentences

    for text in appended:
        for sentence in split_sentences(text):
            assert classify(sentence).origin != MODEL, sentence


def test_a_verbatim_answer_with_an_appended_limitation_still_scores():
    answer = (f"21 CFR 820.10(b)(2): {PURCHASING} [1]\n"
              "The retrieved evidence does not establish the audit frequency asked for.")
    a, _ = assess(ONE, answer)
    assert a.status == EVALUATED and states(a)[R.SUBSTANTIVE] == PASS
    assert a.checked["material_claims"] == 1


# ------------------------------------------------------------ cross-references


def test_a_part_the_regulation_itself_cross_references_is_not_fabrication():
    """Found on the first live run: 820.10's own text says "in accordance with the
    requirements of part 830 of this chapter", and an answer repeating that was
    being scored as having invented part 830 - because a part-level reference
    carries no section number and the index was asked for section None."""
    table = list(TABLE) + [row("820.11", "", 0, text="Traceability shall be in accordance with the requirements of "
                                                      "part 821 of this chapter, if applicable.")]
    pkg = package_for("What does 21 CFR 820.11 require?", db=TableDatabase(table))

    class Index:
        def __init__(self):
            self.asked = []

        def part_status(self, part):
            self.asked.append(("part", part))
            return (True, True)

        def section_status(self, section):
            self.asked.append(("section", section))
            return (False, False)

    index = Index()
    answer = ("21 CFR 820.11: Traceability shall be in accordance with the requirements of part 821 of this "
              "chapter, if applicable [1].")
    a = evaluate("What does 21 CFR 820.11 require?", answer, package=pkg,
                 validation=None, coverage=None, identifier_index=index)
    assert next(d.state for d in a.dimensions if d.dimension == R.FABRICATION_FREE) == PASS
    assert index.asked == [], "a part the evidence already cross-references must not reach the index at all"


def test_an_unreferenced_part_is_checked_as_a_part_not_as_a_section():
    asked = []

    class Index:
        def part_status(self, part):
            asked.append(("part", part))
            return (False, False)

        def section_status(self, section):
            asked.append(("section", section))
            return (False, False)

    answer = f"21 CFR 820.10(b)(2): {PURCHASING} [1] See also 21 CFR part 1400."
    a, _ = assess(ONE, answer, identifier_index=Index())
    assert asked == [("part", "1400")]
    # the existing validator also catches 1400 as an unsupported figure, which is the
    # same dimension and the same deduction; what this pins is that the index was
    # asked about a PART, and that an unaccounted-for part fails the dimension
    assert states(a)[R.FABRICATION_FREE] == FAIL and "1400" in a.reason
    detail = states_detail(a, R.FABRICATION_FREE)
    assert "1400" in detail


def test_regulatory_text_that_says_ensure_compliance_is_not_advice():
    """"procedures that will ensure compliance with this part" is how the
    regulation is written; quoting it must not fail scope discipline."""
    text = ("Each manufacturer shall establish and maintain procedures that will ensure compliance with the "
            "applicable requirements of this part.")
    table = list(TABLE) + [row("820.12", "", 0, text=text)]
    pkg = package_for("What does 21 CFR 820.12 require?", db=TableDatabase(table))
    a = evaluate("What does 21 CFR 820.12 require?", f"21 CFR 820.12: {text} [1]", package=pkg)
    assert next(d.state for d in a.dimensions if d.dimension == R.SCOPE) == PASS
    assert a.status == EVALUATED and a.accuracy is not None
