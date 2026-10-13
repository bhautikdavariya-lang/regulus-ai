"""Two-sentence (adjacent window) support, and the safeguards any change to it must keep.

Evidence: VERBATIM 21 CFR 211.192 (tests/fixtures/accuracy_211_192_rows.json, one undivided paragraph of four
sentences: S1 QCU review before release, S2 investigate, S3 extend to other batches/products, S4 written record).

The window gate (`verdicts.judge_window`) needs a verbatim run of >= 5 words into EACH sentence. That rejects a
correct merged paraphrase of S2+S3 (the live 211.192 NOT EVALUATED, artifacts/accuracy/
not_evaluated_211_192_20261013T060000Z), but the same gate is also what keeps a merged claim with a fabricated
period, a substituted actor or a narrowed scope from being supported: the paraphrase judge does not detect those
on its own (see the single-sentence xfails below). The run gate can therefore only be relaxed after the judge
itself rejects them. Strict xfails mark the behaviour still wanted; an XPASS means it changed and must be reviewed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from regulus.accuracy import answer as AN
from regulus.accuracy import evaluate
from regulus.accuracy import verdicts as VD
from regulus.accuracy.alignment import LexicalAligner, Passage, adjacent_windows
from regulus.accuracy.review import NOT_EVALUATED, PASS
from tests.test_accuracy_claim_extraction import Cov, Pkg, Src
from tests.test_accuracy_pass_integrity import production
from tests.test_retrieval_plan import row

_F = json.loads((Path(__file__).parent / "fixtures" / "accuracy_211_192_rows.json").read_text(encoding="utf-8"))
TEXT = _F["paragraphs"][0]["text"]
HEADING = _F["section_heading"]
S1, S2, S3, S4 = [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", " ".join(TEXT.split()))]
T211 = [row("211.192", "", 1, text=TEXT, section_heading=HEADING)]
PASSAGES = [Passage(1, "21 CFR 211.192", "exact", s, HEADING, "binding_regulation", i) for i, s in enumerate((S1, S2, S3, S4))]

BROAD = "What does 21 CFR 211.192 require?"
FOCUSED = "Under 21 CFR 211.192, what must a manufacturer do when a batch fails to meet specifications?"

TAIL = ", and that investigation must extend to other batches of the same drug product and other associated drug products."
MERGED = "Any unexplained discrepancy or batch failure to meet specifications must be thoroughly investigated" + TAIL
MERGED_ANSWER = MERGED + " A written record of the investigation, including conclusions and followup, must be made. [1]"


def window(claim):
    return VD.judge_window(claim, adjacent_windows(PASSAGES, PASSAGES), evidence=PASSAGES)


def claim_final(question, claim):
    a = evaluate(question, claim + " [1]", package=Pkg(question, (Src(1, "21 CFR 211.192", TEXT, HEADING),)),
                 coverage=Cov(), aligner=LexicalAligner())
    return a.checked["claims"][0]["final"]


# ------------------------------------------------------------- valid support across two adjacent sentences


def test_a_near_verbatim_merge_of_two_adjacent_sentences_is_supported():
    claim = ("The failure of a batch or any of its components to meet any of its specifications shall be thoroughly "
             "investigated, and the investigation shall extend to other batches of the same drug product and other "
             "drug products.")
    assert window(claim) is not None
    assert claim_final(BROAD, claim) == AN.SUPPORTED


@pytest.mark.xfail(strict=True, reason="the run gate rejects a correct S2+S3 paraphrase (run of 3 words into S2); "
                                       "relaxing it is blocked until the judge rejects the fabrications below")
def test_a_correct_paraphrase_spread_over_two_adjacent_sentences_is_supported():
    assert window(MERGED) is not None
    assert claim_final(BROAD, MERGED) == AN.SUPPORTED


# ------------------------------------------------------------- safeguards a window change must keep


def test_one_sentence_carrying_the_match_while_the_other_only_adds_terms_is_not_window_support():
    """Row F-007's shape on 211.192: S3 is quoted, the rest is not in S2."""
    claim = ("The quality control unit must approve every drug product release procedure, and the investigation shall "
             "extend to other batches of the same drug product and other drug products that may have been associated.")
    assert window(claim) is None
    assert claim_final(BROAD, claim) != AN.SUPPORTED


@pytest.mark.parametrize("claim", [
    pytest.param("Any unexplained discrepancy or batch failure to meet specifications must be thoroughly investigated "
                 "within 30 days" + TAIL, id="fabricated-period"),
    pytest.param("FDA must thoroughly investigate any unexplained discrepancy or batch failure to meet specifications"
                 ", and FDA's investigation must extend to other batches of the same drug product and other associated "
                 "drug products.", id="fabricated-actor"),
    pytest.param("Only an unexplained discrepancy or batch failure in a batch that has not been distributed must be "
                 "thoroughly investigated" + TAIL, id="narrowed-scope"),
])
def test_a_merged_claim_with_a_fabricated_detail_is_not_supported(claim):
    assert window(claim) is None
    assert claim_final(BROAD, claim) != AN.SUPPORTED


def test_partial_support_does_not_become_full_support():
    claim = ("Any unexplained discrepancy or batch failure to meet specifications must be thoroughly investigated and "
             "reported to FDA within 15 days" + TAIL)
    assert window(claim) is None
    assert claim_final(BROAD, claim) not in (AN.SUPPORTED, AN.SUPPORTED_WITH_CITATION_DEFECT)


@pytest.mark.parametrize("claim", [
    "Any unexplained discrepancy or batch failure to meet specifications need not be investigated" + TAIL,
    "Any unexplained discrepancy or batch failure to meet specifications may be investigated, and that investigation "
    "may extend to other batches of the same drug product and other associated drug products.",
], ids=["negation", "weakened-modal"])
def test_a_merged_claim_that_reverses_polarity_or_modality_is_contradicted(claim):
    assert window(claim) is None
    assert claim_final(BROAD, claim) == AN.CONTRADICTED


# ------------------------------------------------------------- pre-existing single-sentence gaps (no window involved)


@pytest.mark.xfail(strict=True, reason="pre-existing: the paraphrase judge has no actor-substitution check; a passive "
                                       "duty of the manufacturer restated as FDA's is supported")
def test_a_duty_reassigned_to_fda_is_not_supported():
    claim = "FDA must thoroughly investigate any unexplained discrepancy or failure of a batch to meet its specifications."
    assert claim_final(FOCUSED, claim) != AN.SUPPORTED


def test_a_duty_narrowed_to_undistributed_batches_is_not_supported():
    """Was a strict xfail (Stage A): the narrowing is now withheld - unverifiable, never contradicted."""
    claim = ("Only a failure of a batch that has not been distributed to meet its specifications must be thoroughly "
             "investigated.")
    assert claim_final(FOCUSED, claim) == AN.UNVERIFIABLE


@pytest.mark.xfail(strict=True, reason="pre-existing: a period the evidence never states is supported by the evaluator "
                                       "(the pipeline's validation withholds such an answer before delivery)")
def test_a_period_the_evidence_never_states_is_not_supported_by_the_evaluator():
    claim = ("Any unexplained discrepancy or failure of a batch to meet its specifications must be thoroughly "
             "investigated within 30 days.")
    assert claim_final(FOCUSED, claim) != AN.SUPPORTED


def test_a_period_the_evidence_never_states_is_withheld_by_the_pipeline():
    v, d, out = production(FOCUSED, "Any unexplained discrepancy or failure of a batch to meet its specifications "
                                     "must be thoroughly investigated within 30 days. [1]", T211)
    assert "30 days" not in out.answer and v["live_check_score"] != 100


# ------------------------------------------------------------- the 211.192 question variants, production path


def test_the_complete_verbatim_answer_to_the_broad_question_passes():
    v, d, out = production(BROAD, f"{S1} {S2} {S3} {S4} [1]", T211)
    assert (v["status"], v["live_check_score"]) == (PASS, 100)


@pytest.mark.xfail(strict=True, reason="the correct merged S2+S3 answer to the focused question is NOT EVALUATED: "
                                       "the merged claim is unverifiable (run gate) and S4 alone reads as off-topic")
def test_the_merged_answer_to_the_focused_question_is_evaluated():
    v, d, out = production(FOCUSED, MERGED_ANSWER, T211)
    assert v["status"] != NOT_EVALUATED


@pytest.mark.xfail(strict=True, reason="Stage B: one paragraph holding four obligations is one completeness unit, so a "
                                       "broad answer omitting S1 (QCU review before release) passes")
def test_a_broad_answer_omitting_the_record_review_obligation_does_not_pass():
    v, d, out = production(BROAD, f"{S2} {S3} {S4} [1]", T211)
    assert v["live_check_score"] != 100
