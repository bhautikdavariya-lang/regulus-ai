"""The live answer-accuracy rubric: `regulus_live_evidence_assessment_v1`.

This is NOT the acceptance benchmark's rubric. `regulus_substantive_rubric_v1`
(docs/STAGE_A_RUBRIC.md) is contractual, is scored by a human against the text
of the governing provision, and is frozen; this file neither reads nor changes
it. What this rubric scores is a different and smaller thing:

    given the authoritative evidence that was actually retrieved for THIS
    question, what can be established about the answer by identity alone?

"By identity alone" is the whole design, and it is forced by measurement.
docs/STAGE_A_VALIDATOR_LIMITATION.md records that over the 299 scored
acceptance rows the content-recall proxy's passes are 85.5% wrong and the
production grounding validator's `valid` state is 97.8% wrong, both because a
bag of words cannot see negation, applicability or attribution. Its §7 is a
standing rule: no span-support or content-recall score may produce a verdict.

So this rubric decides a dimension only from things that are decidable:

    identifier comparison     does [3] exist; is 820.10(b)(2) the section the
                              sentence cites; does the named section exist in
                              the verified snapshot
    verbatim containment      is this claim's wording a contiguous substring of
                              the source it is attributed to, after normalising
                              case and whitespace only
    structural reports        the Stage 3 coverage report and the Stage 4/7
                              validation problems, which are themselves
                              identity- and structure-based

and abstains everywhere else. Verbatim containment is identity, not overlap:
"the provisions of this part do not apply to manufacturers of components" and
"manufacturers of components are subject to this part" have nearly identical
word bags and no common substring, which is exactly the M-003 / phase-D1-H4
failure that recall scored as a pass.

The consequence is deliberate and must not be "fixed" by loosening it: a
correct answer written as a paraphrase is NOT established, and the rubric
returns `unable_to_determine` rather than a number. Abstention is the safe
error here; a false pass is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# v2 (2026-10-08): question relevance became a first-class dimension, and the
# substantive verdict is decided per claim (support AND relevance) rather than
# by requiring every sentence to be verbatim. v1 passed acceptance row D-001 -
# twenty true quotations answering a different question - on substantive
# correctness. A score under v2 is not comparable with one under v1.
RUBRIC_ID = "regulus_live_evidence_assessment_v2"
RUBRIC_VERSION = "2.0.0"
FROZEN = "2026-10-08"

# ------------------------------------------------------------ dimensions

SUBSTANTIVE = "substantive_correctness"
QUESTION_RELEVANCE = "question_relevance"
EVIDENCE_SUPPORT = "evidence_support"
CITATION = "citation_correctness"
FABRICATION_FREE = "fabrication_free"
COMPLETENESS = "completeness"
SCOPE = "scope_correct"

DIMENSIONS = (QUESTION_RELEVANCE, SUBSTANTIVE, EVIDENCE_SUPPORT, CITATION, FABRICATION_FREE, COMPLETENESS, SCOPE)

# Human labels for the UI; kept here so the page and the JSON cannot drift apart.
LABELS = {
    QUESTION_RELEVANCE: "Answers the question",
    SUBSTANTIVE: "Substantive correctness",
    EVIDENCE_SUPPORT: "Evidence support",
    CITATION: "Citation correctness",
    FABRICATION_FREE: "Unsupported claims",
    COMPLETENESS: "Completeness",
    SCOPE: "Scope",
}

# What each dimension asserts when it PASSES. Shown in the UI detail view, because
# "Substantive correctness ✓" on its own would overclaim.
CLAIMS = {
    QUESTION_RELEVANCE: "the answer's statements answer what was asked: the regulation each one corresponds to is about the question's subject, from the right product domain and part",
    SUBSTANTIVE: "every requirement the answer states is borne out by the evidence retrieved for the question - verbatim, or as a paraphrase whose regulatory operators (strength, polarity, duty-holder, quantities, dates, conditions) all agree with it",
    EVIDENCE_SUPPORT: "every material claim is a verbatim passage of an authoritative source retrieved for this question",
    CITATION: "every citation resolves to a supplied source, and to the provision the sentence it is attached to is about",
    FABRICATION_FREE: "the answer names no section, clause, condition or figure that the authoritative evidence does not contain",
    COMPLETENESS: "every provision the question requested has authoritative text and is addressed in the answer",
    SCOPE: "the answer stays within Title 21 and the provisions asked about, renders no legal advice and guarantees no compliance outcome",
}

# ------------------------------------------------------------ states

PASS = "pass"
FAIL = "fail"
# Substantive correctness and completeness both have a middle state, because the
# rubric's own N and O are 0/1/2 scales. N=1 - "directionally right but
# incomplete in a way that could mislead, or a conditional requirement
# oversimplified" - is a DECIDED outcome that fails the verdict rule, not an
# abstention, so it must score rather than return "unable to determine".
PARTIAL = "partial"
NOT_ESTABLISHED = "not_established"   # the check is not decidable for this answer
NOT_APPLICABLE = "not_applicable"     # there is nothing for this check to judge

STATES = (PASS, FAIL, PARTIAL, NOT_ESTABLISHED, NOT_APPLICABLE)

# The flat JSON form asked for by the feature spec: true / false / "partial" / null.
FLAT = {PASS: True, FAIL: False, PARTIAL: PARTIAL, NOT_ESTABLISHED: None, NOT_APPLICABLE: None}

# ------------------------------------------------------------ assessment status

EVALUATED = "evaluated"
UNABLE = "unable_to_determine"
NOT_SCORED = "not_applicable"    # the answer asserts no regulatory requirement
ERROR = "evaluator_error"        # the evaluator itself failed; the answer is unaffected

# ------------------------------------------------------------ the formula

# Two dimensions are ABSOLUTE: a failure of either is not a deduction to be
# offset, it is the verdict. This mirrors the acceptance rubric, where
# fabrication fails the row outright (gate G2 is 0, absolute) and a PASS
# requires N=2; it is not an arbitrary weighting.
ABSOLUTE = (FABRICATION_FREE, SUBSTANTIVE, QUESTION_RELEVANCE)

# Deduction from 100 for each (dimension, state). A state missing from this
# table deducts nothing. Rationale per row:
#
#   fabricated / contradicted      100  absolute, see above
#   citation_correctness fail       40  a right rule under a wrong number sends the
#                                       user to the wrong provision: rubric L = 0
#   scope_correct fail              40  advice or a compliance guarantee is a
#                                       different kind of wrong, not a smaller one
#   evidence_support fail           35  a material claim no retrieved source makes
#   completeness fail               25  a governing requirement is missing (rubric O = 0)
#   completeness partial            10  the primary provision is there, something
#                                       requested was not retrieved and the answer says so
#   not_established                  5-15  an unverified dimension is not a verified-good
#                                       dimension; the score may not reach 100 on checks
#                                       that were never actually decided
DEDUCTIONS: dict[tuple[str, str], int] = {
    (FABRICATION_FREE, FAIL): 100,
    (SUBSTANTIVE, FAIL): 100,
    # An answer to a different question is a wrong answer, however true each of
    # its statements is: absolute, like a fabrication. A PARTIAL relevance result
    # carries no deduction of its own, because it already makes the substantive
    # verdict PARTIAL; charging it twice would double-count one defect.
    (QUESTION_RELEVANCE, FAIL): 100,
    # N=1 fails the rubric's verdict rule, so a partial substantive result must
    # land clearly below any passing score; it is not an absolute failure,
    # because the answer is directionally right and its citation, scope and
    # completeness still carry information.
    (SUBSTANTIVE, PARTIAL): 45,
    (CITATION, FAIL): 40,
    (SCOPE, FAIL): 40,
    (EVIDENCE_SUPPORT, FAIL): 35,
    (COMPLETENESS, FAIL): 25,
    (COMPLETENESS, PARTIAL): 10,
    (EVIDENCE_SUPPORT, NOT_ESTABLISHED): 15,
    (FABRICATION_FREE, NOT_ESTABLISHED): 10,
    (CITATION, NOT_ESTABLISHED): 10,
    (COMPLETENESS, NOT_ESTABLISHED): 5,
    (SCOPE, NOT_ESTABLISHED): 5,
}


def deduction(dimension: str, state: str) -> int:
    return DEDUCTIONS.get((dimension, state), 0)


def score(states: dict[str, str]) -> int:
    """score = max(0, 100 - sum of deductions). Deterministic and order-free."""
    return max(0, 100 - sum(deduction(d, s) for d, s in states.items()))


def status_for(states: dict[str, str], *, asserts_requirement: bool) -> str:
    """The abstention rule — the part of this rubric that matters most.

    A percentage is issued only when the gating dimension, substantive
    correctness, has actually been DECIDED. `not_established` there means the
    answer's wording could not be matched to the regulation's own wording, and
    no honest number follows from that; §6 of the feature spec and the rubric's
    own refusal to use UNDETERMINED as a soft pass or a soft fail both point the
    same way.

    A DECIDED failure is not an abstention: a detected fabrication or
    contradiction scores 0, which is a measurement, not a missing one.
    """
    if any(states.get(d) == FAIL for d in ABSOLUTE):
        # A detected fabrication or contradiction IS the verdict, whatever else
        # stayed undecided: the score is 0 because something was measured, not
        # because something was missing. This is the one case where a number is
        # issued without the gating dimension passing.
        return EVALUATED
    if states.get(SUBSTANTIVE) in (PASS, FAIL, PARTIAL):
        # Decided, and that is what matters. An answer that makes no claim can
        # still have a decided substantive result: a correct refusal is the
        # passing answer on a negative control, and a refusal where the evidence
        # WAS sufficient is N=0. Both are measurements, so neither may be
        # downgraded to "not scored" merely because no claim was asserted.
        return EVALUATED
    if not asserts_requirement:
        return NOT_SCORED
    return UNABLE


# ------------------------------------------------------------ wording for the UI

# The distinction §8 of the feature spec requires. Shown with every score.
BASIS_NOTE = ("Based on the authoritative regulatory evidence retrieved for this answer.")
NOT_THE_BENCHMARK = ("An evidence-based assessment of this one answer. It is not the 300-question "
                     "acceptance-test score and does not mean this answer passed that rubric.")

GLYPH = {PASS: "✓", FAIL: "✗", PARTIAL: "⚠", NOT_ESTABLISHED: "?", NOT_APPLICABLE: "–"}


@dataclass(frozen=True)
class Rubric:
    """The rubric as data, so a result can record exactly what scored it."""

    rubric_id: str = RUBRIC_ID
    version: str = RUBRIC_VERSION
    frozen: str = FROZEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "rubric_id": self.rubric_id,
            "version": self.version,
            "frozen": self.frozen,
            "dimensions": list(DIMENSIONS),
            "absolute": list(ABSOLUTE),
            "deductions": {f"{d}:{s}": v for (d, s), v in DEDUCTIONS.items()},
            "formula": "score = max(0, 100 - sum(deductions)); no score unless substantive_correctness is decided",
            "is_acceptance_rubric": False,
        }


RUBRIC = Rubric()
