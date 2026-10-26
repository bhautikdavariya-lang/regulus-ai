"""Was declining the right answer?

A refusal is not an absence of an answer; under the acceptance rubric it is
often the ONLY passing answer. 50 of the 300 benchmark rows are trap rows whose
correct behaviour is to state that a provision, clause or rule does not exist,
and the rubric scores abstention explicitly: *"Abstaining where the evidence WAS
sufficient is N=0 (the question went unanswered); answering where it was
insufficient is scored on what was said"*, and on a negative control
*"L=1 = correctly declined"*.

The previous evaluator reported every declining answer as `not_applicable`
("no regulatory claim to score"), which is true of its claims and wrong about
the answer: whether declining was correct IS decidable, from state the pipeline
has already computed. 33 of those 50 trap rows went unscored for that reason.

Decided here, from existing sources of truth only - no new one is invented:

    coverage        (regulus.rag.coverage) which requested provisions have
                    authoritative EXACT text. Nothing satisfied -> there was
                    nothing to answer from, so declining is correct.
    answerability   (regulus.rag.answerability) the Stage 5 gate's own decision,
                    recorded whether or not it was acted on.
    validation      REFUSAL_WITH_EVIDENCE, which fires precisely when an answer
                    declines although EXACT sources were supplied.
    fallback_type   (regulus.rag.fallback) which deterministic message was used.
    scope           the Stage 7 scope decision.

Outcomes:

    CORRECT       the evidence could not establish an answer and the answer says so
    INCORRECT     the evidence could have established an answer and the answer declined
    INCOMPLETE    declining was right, but the answer does not name what it is
                  declining about, which the rubric requires of an abstention
    UNDECIDED     the pipeline state does not establish either way
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from regulus.accuracy.attribution import MARK_RE, normalise
from regulus.evaluation.grounding_eval import REFUSAL, classify_answer
from regulus.rag import validation as V

CORRECT = "correct_abstention"
INCORRECT = "incorrect_abstention"
INCOMPLETE = "incomplete_abstention"
WITHHELD = "answer_withheld"
UNDECIDED = "undecided_abstention"

# Fallbacks whose reason for refusing is a fact about the EVIDENCE: declining
# was the right answer because the corpus could not establish one
# (regulus.rag.fallback).
EVIDENCE_BASED_FALLBACKS = {
    "no_evidence": "no sufficiently relevant evidence was retrieved",
    "provision_not_found": "the requested provision has no authoritative text in the snapshot",
    "out_of_scope": "the question falls outside Title 21 and FDA guidance",
    "unsupported_request": "the question asks for a determination the sources cannot make",
    "ambiguous": "the question does not identify the provision it asks about",
    "wrong_provision": "the question names a provision it refers to, not the one it asks for",
    "value_not_established": "the retrieved evidence establishes no value of the kind asked for",
    "premise_not_established": "the identified provision does not state the premise the question assumes",
}

# Fallbacks that suppress an answer the model DID produce. The suppression is a
# safety outcome and is worth having; it is not evidence that declining was the
# right answer. Measured on acceptance row C-001: the evidence was present, the
# draft failed validation, nothing was delivered, and the rubric scores the row
# N=0 because the question went unanswered. Crediting these as correct
# abstentions scored that row 95%, which is the error this constant exists to
# prevent.
WITHHOLDING_FALLBACKS = {
    "unvalidated_answer_withheld": "the generated answer failed validation and was suppressed, so the question "
                                   "went unanswered - the suppression was right, the outcome is still no answer",
}
REFUSING_FALLBACKS = {**EVIDENCE_BASED_FALLBACKS, **WITHHOLDING_FALLBACKS}
# Deterministic ANSWERS: the pipeline wrote them without a model call, so `model_called` is False, but they answer. The
# color-listing composer (regulus.rag.color_listing) states each product's use and quotes the listing, cited; the
# blind scorers passed 19 of its 21 holdout answers, and this check called 20 of the composed PASS answers declines
# (23 Oct 2026, live evaluator vs blind verdicts).
ANSWERING_FALLBACKS = frozenset({"composed_from_listing", "composed_practice_silence", "composed_premise_figure",
                                 "composed_records_silence", "composed_qmsr", "composed_definitions"})

# The answerability states (regulus.rag.answerability) that ASSERT the evidence
# could not answer. Deliberately a whitelist: UNKNOWN means the gate did not
# decide, and PARTIALLY_ANSWERABLE means it decided the evidence answers part of
# the question - neither justifies a refusal. Treating "anything but ANSWERABLE"
# as justification credited two N=0 rows (C-003, D-005) as correct abstentions.
REFUSAL_STATES = frozenset({"INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "AMBIGUOUS", "WRONG_PROVISION",
                            "UNSUPPORTED_REQUEST"})

# Wording that makes a refusal explicit about what it is refusing. The pipeline's
# own deterministic messages all match one of these; a model-written refusal may
# not, and then the abstention is INCOMPLETE rather than correct.
_DECLINES_RE = re.compile(
    r"\bdoes not contain\b|\bdo(?:es)? not provide enough information\b|\bdo(?:es)? not (?:cover|establish|state)\b"
    r"|\bcannot state\b|\bcannot determine\b|\bnot found in the available\b|\bno exact text\b"
    r"|\bwill not infer\b|\bcould not be validated\b|\bis outside what\b|\bno answer is given\b"
    r"|\bnot retrieved\b|\bdoes not appear to be a regulatory question\b", re.I)


@dataclass(frozen=True)
class AbstentionResult:
    declined: bool
    outcome: str | None
    reason: str
    evidence: tuple[str, ...] = ()

    @property
    def correct(self) -> bool:
        return self.outcome == CORRECT

    def to_dict(self) -> dict[str, Any]:
        return {"declined": self.declined, "outcome": self.outcome, "reason": self.reason,
                "evidence": list(self.evidence)}


def _names_subject(answer: str, package) -> bool:
    """Does the refusal name the provision (or the question's subject) it declines about?"""
    text = normalise(MARK_RE.sub(" ", answer or ""))
    labels = [label for _, label in (package.requirements if package is not None else ())]
    if not labels:
        return True      # nothing specific was requested; there is no label to name
    return any(normalise(label).strip() in text for label in labels)


def _reserved_requests(package, identifier_index) -> tuple[str, ...]:
    """Requested provisions that EXIST in the regulation's structure but carry no
    live text - a reserved or superseded section.

    The distinction matters and is decidable: `regulus.grounding.identifiers`
    already separates "verified absent" from "reserved", and the rubric treats
    them differently. Declining about a section that does not exist is the
    passing answer on a negative control. Declining about a RESERVED section is
    only half the answer, because the requirement usually still reaches the
    reader through another provision and the rubric asks for that redirect:
    "a temporal row requires a correct substantive redirect, not a refusal".
    """
    if identifier_index is None or package is None:
        return ()
    from regulus.retrieval.references import parse_cfr_references

    out: list[str] = []
    for _, label in package.requirements:
        ref = next((r for r in parse_cfr_references(label) if r.section), None)
        if ref is None:
            continue
        try:
            exists, live = identifier_index.section_status(ref.section)
        except Exception:
            continue
        if exists and not live:
            out.append(label)
    return tuple(out)


def _topic_evidence(intent, passages) -> list[str]:
    """Citations of retrieved passages that are about what the question asks."""
    if intent is None or not passages:
        return []
    from regulus.accuracy.relevance import on_topic

    return list(dict.fromkeys(p.citation for p, _ in on_topic(intent, passages)))


def assess(answer: str, *, package=None, coverage=None, validation=None, model_called: bool = True,
           fallback_type: str | None = None, scope_status: str | None = None,
           answerability: dict[str, Any] | None = None, has_claims: bool = True,
           identifier_index=None, intent=None, passages=()) -> AbstentionResult:
    """Whether this answer declines, and whether declining was right."""
    text = (answer or "").strip()
    declined = bool(text) and (
        (fallback_type in REFUSING_FALLBACKS)
        or (not model_called and fallback_type not in ANSWERING_FALLBACKS)
        or classify_answer(text) == REFUSAL
        or not has_claims
    )
    if not declined:
        return AbstentionResult(False, None, "the answer states regulatory requirements rather than declining")

    codes = {p.code for p in (validation.problems if validation is not None else ()) if p.severity == "error"}
    satisfied = tuple(coverage.satisfied_ids) if coverage is not None else ()
    missing = tuple(coverage.missing_labels) if coverage is not None else ()

    # -- the answer was SUPPRESSED: the model did answer and validation removed it.
    # Checked first because it is the most precise description; it scores the
    # same as an incorrect abstention (the question went unanswered).
    if fallback_type in WITHHOLDING_FALLBACKS:
        return AbstentionResult(True, WITHHELD, WITHHOLDING_FALLBACKS[fallback_type],
                                (f"fallback_type={fallback_type}",))

    # -- declining was WRONG: the evidence was there
    if V.REFUSAL_WITH_EVIDENCE in codes:
        return AbstentionResult(True, INCORRECT,
                                "the answer declines although authoritative text was supplied for the requested "
                                "provision(s), so the question went unanswered",
                                (V.REFUSAL_WITH_EVIDENCE,))
    if coverage is not None and coverage.explicit and satisfied and not missing:
        return AbstentionResult(True, INCORRECT,
                                f"every requested provision had authoritative text ({', '.join(satisfied)}) and the "
                                f"answer still declined, so the question went unanswered",
                                ("coverage_complete_but_declined",))

    # -- declining was RIGHT: establish why, from pipeline state. Each branch
    # needs a POSITIVE record that the corpus could not answer; the absence of
    # sources is not one, because a package can be empty for reasons this
    # evaluator cannot see (it was measured crediting acceptance row C-003,
    # whose guidance evidence simply had no text in the reconstruction).
    why: str | None = None
    evidence: list[str] = []
    if fallback_type in EVIDENCE_BASED_FALLBACKS:
        why = EVIDENCE_BASED_FALLBACKS[fallback_type]
        evidence.append(f"fallback_type={fallback_type}")
    elif scope_status == "out_of_scope":
        why = "the question falls outside Title 21 and FDA guidance"
        evidence.append("scope=out_of_scope")
    elif coverage is not None and coverage.explicit and not satisfied:
        why = (f"no requested provision has authoritative text in the snapshot "
               f"({', '.join(missing) or 'none satisfied'})")
        evidence.append("coverage=no_exact_evidence")
    elif answerability is not None and answerability.get("state") in REFUSAL_STATES:
        why = f"the answerability gate decided {answerability.get('state')}: {answerability.get('reason') or ''}".strip()
        evidence.append(f"answerability={answerability.get('state')}")

    topic_evidence = _topic_evidence(intent, passages)
    if why is None:
        # No pipeline record says the corpus could not answer. The retrieved
        # evidence itself can: if it contains passages about exactly what was
        # asked, the material to answer from was in hand and declining left the
        # question unanswered (acceptance rows C-003 and D-005 declined although
        # the governing sections exist).
        if topic_evidence:
            return AbstentionResult(True, INCORRECT,
                                    f"the answer declines, but the retrieved evidence covers what was asked "
                                    f"({', '.join(topic_evidence[:3])})", ("retrieved_evidence_on_topic",))
        return AbstentionResult(True, UNDECIDED,
                                "the answer declines, and neither the pipeline state nor the retrieved evidence "
                                "establishes whether the question could have been answered")

    if not _DECLINES_RE.search(text):
        return AbstentionResult(True, INCOMPLETE,
                                f"declining was right ({why}), but the answer does not say that it cannot answer",
                                tuple(evidence))
    if not _names_subject(text, package):
        return AbstentionResult(True, INCOMPLETE,
                                f"declining was right ({why}), but the answer does not name the provision it declines "
                                f"about, which an abstention must restate", tuple(evidence))
    # A refusal that rests on "the requested provision has no text" is complete
    # only when the question asks for nothing BUT that provision. When it asks
    # about a subject as well ("What does 21 CFR 820.30 require for DESIGN
    # CONTROLS?"), the requirement may now live in another provision - the
    # rubric scores exactly that refusal N=1, "a temporal row requires a correct
    # substantive redirect, not a refusal" - and a superseded section is
    # indistinguishable in the snapshot from one that never existed. So:
    #   no subject beyond the provision           -> correct
    #   retrieved evidence is about the subject   -> incomplete: a redirect was possible
    #   nothing retrieved is about the subject    -> undecided: cannot tell whether one was owed
    # This replaced crediting every such refusal as correct, which scored the
    # seven temporal rows M-031..M-038 at 95 against a human N=1.
    rests_on_absence = (fallback_type == "provision_not_found"
                        or (coverage is not None and coverage.explicit and not satisfied))
    if rests_on_absence and intent is not None and intent.topic:
        if topic_evidence:
            return AbstentionResult(True, INCOMPLETE,
                                    f"declining to state the requested provision is right ({why}), but the retrieved "
                                    f"evidence covers {'/'.join(intent.topic)} ({', '.join(topic_evidence[:3])}), so "
                                    f"the answer could have redirected to it and did not",
                                    tuple(evidence) + ("subject_covered_elsewhere",))
        return AbstentionResult(True, UNDECIDED,
                                f"declining to state the requested provision is right ({why}), but the question also "
                                f"asks about {'/'.join(intent.topic)}; whether that requirement now lives in another "
                                f"provision cannot be determined from the retrieved evidence",
                                tuple(evidence) + ("redirect_owed_undetermined",))
    reserved = _reserved_requests(package, identifier_index)
    if reserved:
        return AbstentionResult(True, INCOMPLETE,
                                f"{', '.join(reserved)} is reserved rather than nonexistent, so declining is only half "
                                f"the answer: the requirement may now reach the reader through another provision and "
                                f"the answer does not redirect to it",
                                tuple(evidence) + ("requested_provision_reserved",))
    return AbstentionResult(True, CORRECT, f"correctly declined: {why}", tuple(evidence))
