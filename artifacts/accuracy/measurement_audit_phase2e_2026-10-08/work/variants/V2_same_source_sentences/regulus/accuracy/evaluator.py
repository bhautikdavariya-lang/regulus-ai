"""The live answer-accuracy evaluator: an observer of a finished answer.

It is given the final text the user will see, the authoritative evidence that
was retrieved for that question, the citations, and the deterministic reports
the pipeline already produced. It returns an assessment. It holds no retriever,
no model and no corpus of its own, it never calls a generator, and it has no way
to alter the answer: `evaluate` takes strings and frozen dataclasses and returns
a new object. Nothing in regulus.rag imports this package.

What it decides and what it refuses to decide is set out in rubric.py. In short:
dimensions are decided from identifier comparison, verbatim containment and the
existing structural reports; where none of those can decide, the dimension is
`not_established`, and where substantive correctness is not established no
percentage is issued at all.

Reused, never re-derived:
    regulus.rag.validation         citation validity, provision-identity mismatch,
                                   unsupported figures, asserted missing provisions,
                                   provision identity and the parent/child relation
    regulus.rag.claim_validation   misattribution, invented condition, unsupported premise
    regulus.rag.shape_validation   enumeration and group coverage codes
    regulus.rag.coverage           which requested provisions have authoritative text
    regulus.retrieval.references   CFR reference parsing
    regulus.grounding.identifiers  existence of an identifier in the verified snapshot
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from regulus.accuracy import abstention as AB
from regulus.accuracy import answer as AN
from regulus.accuracy import claims as CL
from regulus.accuracy import intent as IN
from regulus.accuracy import relevance as RV
from regulus.accuracy import rubric as R
from regulus.accuracy.alignment import Aligner, LexicalAligner, passages
from regulus.accuracy.attribution import MARK_RE, normalise
from regulus.rag import claim_validation as CV
from regulus.rag import shape_validation as SV
from regulus.rag import validation as V
# Provision identity and the parent/child relation. Imported rather than copied:
# these two functions define what "the same provision" means for the whole
# pipeline, and a second definition here would be a second answer to that
# question. regulus.rag.claim_validation already takes them as injected
# parameters, which is the same reuse by a different route.
from regulus.rag.validation import _related_identity as related_identity
from regulus.rag.validation import _source_identity as source_identity
from regulus.retrieval.evidence import TIER_EXACT
from regulus.retrieval.references import parse_cfr_references
from regulus.traceability import evidence as TR

# ------------------------------------------------------------ what is a claim

_NEGATION_RE = re.compile(r"\b(?:not|no|never|neither|nor|cannot|except|unless|exempt)\b", re.I)

# Rubric P: no legal advice, no guaranteed compliance outcome. Narrow on purpose,
# and applied only to text that is NOT verbatim from a source: "procedures that
# will ensure compliance with this part" is how regulations are written, so
# "ensure compliance" cannot be in this pattern and quoting a provision can never
# be advice. What is left is phrasing only a speaker in their own voice produces.
_ADVICE_RE = re.compile(
    r"\b(?:we|i)\s+(?:recommend|advise|suggest)\b|\bour (?:advice|recommendation)\b|"
    r"\bthis (?:constitutes|is) legal advice\b|\byou should (?:consult|hire|retain)\b|"
    r"\bguarantee[sd]? (?:compliance|approval|clearance)\b|\byou are (?:fully )?compliant\b|"
    r"\byou (?:do not|don't) need to (?:comply|register|report)\b", re.I)

# The applicability contradiction: the class of failure phase D1's H4 arm produced
# and recall scored as a pass. Decided structurally, never by a score.
_EXCLUSION_RE = re.compile(
    r"\b(?:do(?:es)? not apply to|shall not apply to|are not subject to|is not subject to|"
    r"are exempt from|is exempt from|are not required to|is not required to)\b", re.I)
_POSITIVE_RE = re.compile(r"\b(?:applies to|apply to|are subject to|is subject to|must|shall|are required to|is required to)\b", re.I)
_CONTRADICTION_MIN_WORDS = 3     # the excluded subject must appear verbatim, this many words at least

APPLICABILITY_CONTRADICTION = "applicability_contradiction"

# Error-severity validation codes, grouped by the dimension each one fails. Every
# code here is an identity or structure finding; no overlap-based code appears.
_SUBSTANTIVE_FAIL = (V.ASSERTED_MISSING_PROVISION, CV.UNSUPPORTED_PREMISE, CV.PARAGRAPH_MISATTRIBUTION,
                     CV.INVENTED_CONDITION, V.DEGENERATE_OUTPUT, V.EMPTY_OUTPUT)
_CITATION_FAIL = (V.INVALID_CITATION, V.CITATION_MISMATCH, V.PROVISION_CITATION_MISMATCH,
                  V.DISCOVERY_CITED_FOR_REQUIREMENT, CV.PARAGRAPH_MISATTRIBUTION)
_FABRICATION_FAIL = (V.UNSUPPORTED_FIGURE, V.ASSERTED_MISSING_PROVISION, CV.INVENTED_CONDITION)
_COMPLETENESS_FAIL = (V.REQUIREMENT_NOT_ADDRESSED, SV.ENUMERATION_INCOMPLETE, SV.MATERIAL_GROUP_UNCOVERED)
_SCOPE_FAIL = (SV.SCOPE_EXPANSION,)


# ------------------------------------------------------------ result types


@dataclass(frozen=True)
class DimensionResult:
    dimension: str
    state: str
    detail: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "label": R.LABELS[self.dimension], "state": self.state,
                "glyph": R.GLYPH[self.state], "detail": self.detail, "evidence": list(self.evidence),
                "claim": R.CLAIMS[self.dimension]}


@dataclass(frozen=True)
class AccuracyAssessment:
    status: str
    accuracy: int | None
    reason: str
    dimensions: tuple[DimensionResult, ...] = ()
    deductions: tuple[tuple[str, str, int], ...] = ()
    checked: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    rubric_id: str = R.RUBRIC_ID
    # Where the evidence came from (regulus.traceability): provenance, fingerprint, item counts.
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def states(self) -> dict[str, str]:
        return {d.dimension: d.state for d in self.dimensions}

    def to_dict(self) -> dict[str, Any]:
        states = self.states
        out: dict[str, Any] = {
            "status": self.status,
            "accuracy": self.accuracy,
            "reason": self.reason,
            "rubric_id": self.rubric_id,
            "rubric": R.RUBRIC.to_dict(),
            "basis": R.BASIS_NOTE,
            "not_the_benchmark": R.NOT_THE_BENCHMARK,
            "answer_verdict": self.checked.get("answer_verdict"),
            "dimensions": [d.to_dict() for d in self.dimensions],
            "deductions": [{"dimension": d, "state": s, "points": p} for d, s, p in self.deductions],
            "checked": dict(self.checked),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "evidence_provenance": self.evidence.get("provenance"),
            "evidence": dict(self.evidence),
        }
        # the flat per-dimension form: true / false / "partial" / null
        for dimension in R.DIMENSIONS:
            out[dimension] = R.FLAT.get(states.get(dimension, R.NOT_ESTABLISHED))
        return out

    @classmethod
    def unavailable(cls, reason: str, *, status: str = R.UNABLE, elapsed_ms: float = 0.0,
                    checked: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None) -> AccuracyAssessment:
        return cls(status=status, accuracy=None, reason=reason,
                   dimensions=tuple(DimensionResult(d, R.NOT_ESTABLISHED, "not evaluated") for d in R.DIMENSIONS),
                   checked=checked or {}, elapsed_ms=elapsed_ms, evidence=evidence or {})


# ------------------------------------------------------------ helpers


def _errors(validation) -> dict[str, list]:
    out: dict[str, list] = {}
    for problem in (validation.problems if validation is not None else ()):
        if problem.severity == "error":
            out.setdefault(problem.code, []).append(problem)
    return out


def _contradictions(answer: str, package, claims) -> list[str]:
    """Applicability contradictions: the answer asserts an obligation under a
    provision whose own authoritative text excludes the subject it names.

    Decided by two structural facts and one verbatim containment, never by a
    similarity score: (1) the provision's EXACT text carries an explicit
    exclusion, (2) the excluded subject appears verbatim in the answer, (3) the
    answer asserts the obligation positively and nowhere repeats the exclusion.
    """
    from regulus.accuracy.operators import BINDING, authority_of

    answer_normalised = normalise(answer)
    found: list[str] = []
    for source in package.sources:
        if source.tier != TIER_EXACT:
            continue
        # a provision's own exclusion binds; a guidance document's description of
        # one does not, and guidance is tier EXACT when it is the requested
        # document (acceptance row H-006, read as the provision excluding the claim)
        if authority_of(getattr(source, "corpus", None)) != BINDING:
            continue
        match = _EXCLUSION_RE.search(source.text or "")
        if not match:
            continue
        source_normalised = normalise(source.text)
        # the answer repeats the exclusion itself: it is stating the rule, not contradicting it
        if f" {normalise(match.group(0)).strip()} " in answer_normalised:
            continue
        subject = normalise(source.text[match.end():]).split()
        for length in range(min(len(subject), 12), _CONTRADICTION_MIN_WORDS - 1, -1):
            phrase = " ".join(subject[:length])
            if f" {phrase} " not in answer_normalised:
                continue
            positive = [c for c in claims
                        if _POSITIVE_RE.search(MARK_RE.sub(" ", c)) and not _NEGATION_RE.search(MARK_RE.sub(" ", c))
                        and f" {phrase} " in normalise(c)]
            if positive and f" {phrase} " in source_normalised:
                found.append(f"{source.citation} excludes \"{phrase}\" ({match.group(0)}), and the answer states an "
                             f"obligation for it: {positive[0].strip()[:160]!r}")
            break
    return found


def _named_identifiers(answer: str, package, identifier_index):
    """Every CFR provision the answer names, classified by whether the evidence
    accounts for it. Returns (accounted, absent, unverifiable).

    A reference is ACCOUNTED FOR when a supplied source IS that provision, when
    it is one the question requested, or when a supplied source's own text
    cross-references it: "... in accordance with the requirements of part 830 of
    this chapter" inside the text of 820.10 is the regulation citing part 830,
    and an answer repeating it is quoting, not inventing. Only what survives all
    three is put to the identifier index, and a part is checked as a part - a
    part-level reference carries no section number, and asking the index for
    section `None` would report every cross-referenced part as fabricated.
    """
    identities = {s.index: source_identity(s) for s in package.sources}
    known = {i for i in identities.values() if i is not None}
    requested = {normalise(label).strip() for _, label in package.requirements}
    source_text = normalise(" ".join(s.text or "" for s in package.sources) + " " +
                            " ".join(s.citation or "" for s in package.sources))
    accounted, absent, unverifiable = [], [], []
    named = {r.canonical: r for r in parse_cfr_references(MARK_RE.sub(" ", answer))}
    for ref, parsed in named.items():
        is_part = parsed.section is None
        identity = (parsed.title, parsed.section, parsed.paragraph_path)
        # the phrase a supplied source would use to cross-reference it
        mention = f"part {parsed.part}" if is_part else parsed.section
        if not is_part and any(related_identity(identity, k) for k in known):
            accounted.append(ref)
        elif normalise(parsed.canonical).strip() in requested:
            accounted.append(ref)       # requested; found or reported not found by the validator
        elif f" {normalise(mention).strip()} " in source_text:
            accounted.append(ref)       # the regulation's own cross-reference, quoted
        elif identifier_index is None:
            unverifiable.append(ref)
        elif parsed.title and parsed.title != "21":
            unverifiable.append(ref)    # the corpus is Title 21 only: absent is not decidable
        else:
            exists, live = (identifier_index.part_status(parsed.part) if is_part
                            else identifier_index.section_status(parsed.section))
            (accounted if exists and live else absent).append(ref)
    return accounted, absent, unverifiable


# ------------------------------------------------------------ the evaluation


def _evaluate(
    question: str,
    answer: str,
    *,
    package=None,
    citations: Sequence[Any] = (),
    validation=None,
    coverage=None,
    model_called: bool = True,
    fallback_type: str | None = None,
    scope_status: str | None = None,
    scope_answered_anyway: bool = False,
    answerability: dict[str, Any] | None = None,
    identifier_index=None,
    aligner: Aligner | None = None,
) -> AccuracyAssessment:
    """Assess one delivered answer against the question and the evidence retrieved for it.

    Two questions are asked of every claim, separately, and both must pass:

        does it answer the question?   regulus.accuracy.relevance, against the
                                       question's intent (regulus.accuracy.intent)
        is it borne out?               regulus.accuracy.verdicts, against the
                                       retrieved evidence, decided by operators

    and the answer as a whole receives one verdict (regulus.accuracy.answer):
    correct, partial, incorrect, off-topic, unverifiable, or - for a refusal -
    abstention correct / incorrect (regulus.accuracy.abstention).

    Every argument is already produced by the pipeline; nothing is retrieved or
    generated. `aligner` only chooses which passage each claim is compared with
    and never decides a verdict. `identifier_index`, when given, lets a section
    the answer names be checked against the verified snapshot.
    """
    t0 = time.perf_counter()
    text = (answer or "").strip()
    ms = lambda: (time.perf_counter() - t0) * 1000.0

    if package is None:
        return AccuracyAssessment.unavailable(
            "No authoritative regulatory evidence was retrieved for this question, so there is nothing to "
            "assess the answer against.", elapsed_ms=ms(), checked={"sources": 0})
    if not text:
        return AccuracyAssessment.unavailable("No answer text was delivered.", elapsed_ms=ms())

    intent = IN.analyze(question)
    # guidance about another product area is not evidence for this question
    candidates, excluded_evidence = RV.domain_compatible(intent, passages(package.sources))
    sentences = CL.segment(text, question=question)
    claim_sentences = CL.claims(sentences)
    origins = CL.counts(sentences)

    # -- a refusal is an answer too: decided first, against the pipeline's state
    # and against what the retrieved evidence was about
    abstained = AB.assess(text, package=package, coverage=coverage, validation=validation,
                          model_called=model_called, fallback_type=fallback_type, scope_status=scope_status,
                          answerability=answerability, has_claims=bool(claim_sentences),
                          identifier_index=identifier_index, intent=intent, passages=candidates)
    if not package.sources and (not abstained.declined or abstained.outcome == AB.UNDECIDED):
        return AccuracyAssessment.unavailable(
            "No authoritative regulatory evidence was retrieved for this question, so there is nothing to "
            "assess the answer against.", elapsed_ms=ms(),
            checked={"sources": 0, "intent": intent.to_dict(), "abstention": abstained.to_dict(),
                     "answer_verdict": AN.AnswerVerdict(AN.ANSWER_UNVERIFIABLE, "no evidence was retrieved").to_dict()})

    errors = _errors(validation)
    aligner = aligner or LexicalAligner()

    claims: list[AN.ClaimAssessment] = []
    if not abstained.declined:
        prepare = getattr(aligner, "prepare", None)
        if callable(prepare):
            prepare([c.text for c in claim_sentences], candidates)   # one batched embedding call
        claims = AN.assess_claims(claim_sentences, sentences, intent, candidates, aligner, package)
    answering = [c for c in claims if c.answers_question]

    accounted, absent, unverifiable_ids = _named_identifiers(text, package, identifier_index)
    contradictions = _contradictions(text, package, [c.claim for c in answering]) if answering else []
    substantive_codes = [c for c in _SUBSTANTIVE_FAIL if c in errors]
    fabrication_codes = [c for c in _FABRICATION_FAIL if c in errors]

    decisive = None
    if contradictions:
        decisive = "the answer states an obligation that the governing provision's own text excludes: " + contradictions[0]
    elif substantive_codes:
        decisive = "; ".join(errors[c][0].detail for c in substantive_codes)
    elif fabrication_codes:
        decisive = "; ".join(errors[c][0].detail for c in fabrication_codes)
    elif absent:
        decisive = f"the answer names {', '.join(absent)}, which is not in the verified eCFR snapshot"

    verdict = _refusal_verdict(abstained) if abstained.declined else AN.verdict(intent, claims, decisive_failure=decisive)

    results: list[DimensionResult] = []
    add = lambda d, s, detail, ev=(): results.append(DimensionResult(d, s, detail, tuple(ev)))
    irrelevant = [c for c in claims if c.final == AN.IRRELEVANT]

    # ---- question relevance: first, because it decides what "correct" can mean
    if abstained.declined:
        add(R.QUESTION_RELEVANCE, R.NOT_APPLICABLE, "a refusal states no requirement to relate to the question")
    elif verdict.verdict == AN.OFF_TOPIC:
        add(R.QUESTION_RELEVANCE, R.FAIL, verdict.reason, [c.relevance.reason for c in irrelevant[:3]])
    elif irrelevant:
        add(R.QUESTION_RELEVANCE, R.PARTIAL,
            f"{len(irrelevant)} of {len(claims)} statement(s) answer a different question",
            [c.relevance.reason for c in irrelevant[:3]])
    elif answering:
        add(R.QUESTION_RELEVANCE, R.PASS,
            f"{len(answering)} statement(s) correspond to regulation about what the question asks"
            + (f" ({'/'.join(intent.topic)})" if intent.topic else ""))
    else:
        add(R.QUESTION_RELEVANCE, R.NOT_ESTABLISHED,
            "no statement could be related to the question: none corresponds to retrieved evidence or names its subject")

    # ---- substantive correctness: the answer verdict, decided per claim
    add(R.SUBSTANTIVE, _SUBSTANTIVE_OF[verdict.verdict], verdict.reason,
        [c.support_reason for c in answering if c.final in (AN.CONTRADICTED, AN.PARTIALLY_SUPPORTED)][:3])

    # ---- evidence support. Absence of evidence is reported as such, never as falsehood.
    unverified = [c for c in answering if c.final == AN.UNVERIFIABLE]
    if abstained.declined or not answering:
        add(R.EVIDENCE_SUPPORT, R.NOT_APPLICABLE, "no statement that answers the question to support")
    elif validation is not None and validation.status == V.STATUS_UNSUPPORTED:
        add(R.EVIDENCE_SUPPORT, R.FAIL, f"the pipeline's own validation found the answer unsupported ({validation.status})",
            sorted(errors))
    elif unverified:
        add(R.EVIDENCE_SUPPORT, R.NOT_ESTABLISHED,
            f"{len(unverified)} of {len(answering)} statement(s) that answer the question could not be checked: "
            f"{sum(c.support_basis == 'no_evidence' for c in unverified)} have no corresponding evidence, "
            f"{sum(c.support_basis == 'not_decisive' for c in unverified)} correspond to evidence that does not decide them",
            [c.claim[:160] for c in unverified[:3]])
    else:
        add(R.EVIDENCE_SUPPORT, R.PASS,
            f"every one of the {len(answering)} statement(s) that answer the question corresponds to authoritative "
            f"evidence and was compared with it operator by operator")

    # ---- citation, kept apart from support
    # The rubric's L: "every citation attached to a statement is correct", and 0
    # when "the answer is correct but carries no citation at all". A WRONG
    # attached citation fails the dimension; one uncited sentence in a cited
    # answer does not (acceptance row C-004 was scored L=1 with one). Uncited
    # statements stay flagged on the claim itself.
    citation_codes = [c for c in _CITATION_FAIL if c in errors]
    # Rubric L, per claim (regulus.accuracy.answer.judge_citation): a citation
    # shown to name a source that does not support its statement - another
    # source, the wrong paragraph of the right section, guidance for a binding
    # requirement, or no source at all - is a defect. A citation whose statement
    # nothing captured establishes is UNVERIFIED: not a defect, and not proof of
    # a correct citation either.
    defects = [c for c in answering if c.citation in AN.CITATION_DEFECTS]
    uncited = [c for c in answering if c.citation == AN.CITE_MISSING]
    unverified = [c for c in answering if c.citation == AN.CITE_UNVERIFIED]
    verified = [c for c in answering if c.citation == AN.CITE_CORRECT]
    stray = AN.nonclaim_citation_defects(sentences, {s.index: s for s in package.sources})
    if answering and len(uncited) == len(answering):
        defects = uncited
    if citation_codes:
        add(R.CITATION, R.FAIL, "; ".join(errors[c][0].detail for c in citation_codes), citation_codes)
    elif abstained.declined:
        if verdict.verdict == AN.ABSTENTION_CORRECT:
            add(R.CITATION, R.PASS, "the answer correctly declines and cites nothing, which the rubric requires of an "
                                    "abstention")
        else:
            add(R.CITATION, R.NOT_APPLICABLE, "a refusal attaches no citation to any requirement")
    elif not answering:
        add(R.CITATION, R.NOT_APPLICABLE, "no statement that answers the question to cite")
    elif defects:
        add(R.CITATION, R.FAIL,
            f"{len(defects)} of {len(answering)} statement(s) have a citation defect: {defects[0].citation_detail}",
            [f"{c.citation}: {c.claim[:120]}" for c in defects[:3]])
    elif stray:
        add(R.CITATION, R.FAIL, f"a citation outside the statements is wrong: {stray[0]}", stray[:3])
    elif not verified:
        add(R.CITATION, R.NOT_ESTABLISHED,
            f"no cited statement could be checked against its cited source: {len(unverified)} unverified"
            + (f", {len(uncited)} uncited" if uncited else ""),
            [f"unverified: {c.claim[:120]}" for c in unverified[:3]])
    else:
        add(R.CITATION, R.PASS,
            f"{len(verified)} of {len(answering)} statement(s) cite a source that supports them and none cites a "
            f"wrong one"
            + (f"; {len(unverified)} cited statement(s) could not be checked" if unverified else "")
            + (f"; {len(uncited)} carry no citation of their own" if uncited else ""),
            [f"uncited: {c.claim[:120]}" for c in uncited[:3]])

    # ---- fabrication / unsupported identifiers
    if fabrication_codes:
        add(R.FABRICATION_FREE, R.FAIL, "; ".join(errors[c][0].detail for c in fabrication_codes), fabrication_codes)
    elif absent:
        add(R.FABRICATION_FREE, R.FAIL,
            f"the answer names {', '.join(absent)}, which is not in the verified eCFR snapshot", absent)
    elif unverifiable_ids:
        add(R.FABRICATION_FREE, R.NOT_ESTABLISHED,
            f"the answer names {', '.join(unverifiable_ids)}, which the retrieved evidence does not account for and "
            f"which this corpus cannot verify", unverifiable_ids)
    else:
        add(R.FABRICATION_FREE, R.PASS,
            "every figure, condition and identifier in the answer appears in the supplied evidence"
            + (f" ({', '.join(accounted)})" if accounted else ""))

    # ---- completeness: against what the QUESTION asks for, not a sentence count
    completeness_codes = [c for c in _COMPLETENESS_FAIL if c in errors]
    if abstained.declined:
        add(R.COMPLETENESS, R.NOT_APPLICABLE if verdict.verdict != AN.PARTIAL else R.PARTIAL,
            abstained.reason if verdict.verdict == AN.PARTIAL else "a refusal is judged on whether declining was right")
    elif completeness_codes:
        add(R.COMPLETENESS, R.FAIL, "; ".join(errors[c][0].detail for c in completeness_codes), completeness_codes)
    elif len(intent.elements) >= 2 or (intent.elements and answering):
        covered, missing = verdict.elements_covered, verdict.elements_missing
        unverified_el = verdict.elements_unverified
        if missing:
            state = R.PARTIAL if (covered or unverified_el) else R.FAIL
            detail = (f"the answer does not address: {', '.join(missing)}"
                      + (f"; addresses {', '.join(covered + unverified_el)}" if covered or unverified_el else ""))
        elif unverified_el:
            state = R.NOT_ESTABLISHED
            detail = (f"the answer addresses {', '.join(unverified_el)}, but none of the statements doing so could be "
                      f"verified, so whether it covers it correctly is not established")
        else:
            state = R.PASS
            detail = f"covers every element the question asks for ({', '.join(covered)})"
        add(R.COMPLETENESS, state, detail, list(missing))
    elif coverage is not None and coverage.explicit and coverage.missing_labels:
        state = R.PARTIAL if all(normalise(label).strip() in normalise(text) for label in coverage.missing_labels) else R.FAIL
        add(R.COMPLETENESS, state,
            f"{len(coverage.missing_labels)} requested provision(s) had no authoritative text: "
            f"{', '.join(coverage.missing_labels)}"
            + ("; the answer states this" if state == R.PARTIAL else "; the answer does not state this"),
            coverage.missing_labels)
    elif validation is not None and validation.unaddressed:
        add(R.COMPLETENESS, R.FAIL, f"requested provisions left unaddressed: {', '.join(validation.unaddressed)}",
            validation.unaddressed)
    elif answering:
        add(R.COMPLETENESS, R.PASS, "the statements that answer the question cover what it asks for")
    else:
        add(R.COMPLETENESS, R.NOT_ESTABLISHED, "nothing in the answer could be related to what the question asks for")

    # ---- scope
    scope_codes = [c for c in _SCOPE_FAIL if c in errors]
    # only in the answer's own voice: a verbatim passage is the regulation speaking
    verbatim_claims = {c.sentence for c in claims if c.support_basis == "verbatim"}
    advice = next((m for m in (_ADVICE_RE.search(x.text) for x in sentences
                               if x.text not in verbatim_claims and x.origin != CL.QUOTATION) if m), None)
    outside = [r.canonical for r in parse_cfr_references(MARK_RE.sub(" ", text)) if r.title and r.title != "21"]
    if scope_answered_anyway or (scope_status == "out_of_scope" and model_called):
        add(R.SCOPE, R.FAIL, "the question was decided out of scope and the model answered it anyway", ["scope_mismatch"])
    elif scope_codes:
        add(R.SCOPE, R.FAIL, "; ".join(errors[c][0].detail for c in scope_codes), scope_codes)
    elif advice:
        add(R.SCOPE, R.FAIL, f"the answer renders advice or guarantees an outcome: {advice.group(0)!r}", ["legal_advice"])
    elif outside:
        add(R.SCOPE, R.NOT_ESTABLISHED, f"the answer names {', '.join(outside)}, outside Title 21, which this corpus "
                                        f"cannot check", outside)
    else:
        add(R.SCOPE, R.PASS, "the answer stays within Title 21 and the provisions asked about, renders no advice and "
                             "guarantees no outcome")

    states = {d.dimension: d.state for d in results}
    # every answer is judged as an answer (a refusal included), so "asserts no
    # requirement" never downgrades a decided verdict to "not scored"
    status = R.status_for(states, asserts_requirement=True)
    deductions = tuple((d, s, R.deduction(d, s)) for d, s in states.items() if R.deduction(d, s))
    accuracy = R.score(states) if status == R.EVALUATED else None
    finals = {s: sum(1 for c in claims if c.final == s) for s in
              (AN.SUPPORTED, AN.SUPPORTED_WITH_CITATION_DEFECT, AN.PARTIALLY_SUPPORTED, AN.CONTRADICTED,
               AN.IRRELEVANT, AN.UNVERIFIABLE)}
    checked = {
        "question": question,
        "intent": intent.to_dict(),
        "answer_verdict": verdict.to_dict(),
        "sources": len(package.sources),
        "evidence_passages": len(candidates),
        "evidence_excluded_domain": excluded_evidence,
        "citations": len(citations),
        "sentences": len(sentences),
        "material_claims": len(claims),
        "claims_answering_question": len(answering),
        "sentence_origins": origins,
        "claim_status": finals,
        "aligner": aligner.method,
        "identifiers_named": len(accounted) + len(absent) + len(unverifiable_ids),
        "identifiers_verified_absent": len(absent),
        "identifier_index_used": identifier_index is not None,
        "validation_status": getattr(validation, "status", None),
        "validation_error_codes": sorted(errors),
        "abstention": abstained.to_dict(),
        "fallback_type": fallback_type,
        "claims": [c.to_dict() for c in claims],
        "excluded_sentences": [s.to_dict() for s in sentences if not s.is_claim],
        # every sentence of the answer with its claim status: claim / non_claim / uncertain
        "claim_candidates": [{"sentence_index": i, **s.to_dict()} for i, s in enumerate(sentences)],
        "claim_status_counts": {st: sum(1 for x in sentences if x.claim_status == st)
                                for st in (CL.CLAIM_STATUS_CLAIM, CL.CLAIM_STATUS_NON_CLAIM, CL.CLAIM_STATUS_UNCERTAIN)},
    }
    return AccuracyAssessment(status=status, accuracy=accuracy, reason=_reason(status, results, accuracy, verdict),
                              dimensions=tuple(results), deductions=deductions, checked=checked, elapsed_ms=ms())


class _ExactEvidence:
    """The package as the evaluator reads it, with its sources replaced by the
    captured snapshot's items: the text the model actually saw. Every other
    attribute (requirements, answer plan ...) is read from the package."""

    def __init__(self, base, snapshot: TR.EvidenceSnapshot) -> None:
        self._base = base
        self.sources = snapshot.items

    def __getattr__(self, name: str):
        return getattr(self._base, name)


def evaluate(question: str, answer: str, *, package=None, evidence=None, evidence_provenance: str | None = None,
             coverage=None, **kwargs) -> AccuracyAssessment:
    """Assess one delivered answer (see `_evaluate` for how it is judged).

    This function decides only WHERE THE EVIDENCE COMES FROM:

      evidence=<snapshot>   the exact evidence captured when the answer was
                            generated (regulus.traceability). Verified against its
                            fingerprint, then used as the sources. Provenance EXACT.
      package only          evidence not captured with the answer - e.g. rebuilt
                            from an old artifact's labels. Judged the same way, but
                            labelled LEGACY_RECONSTRUCTED; it is never called exact.
      neither               nothing to judge against. Provenance MISSING, which is
                            "the evidence was not captured", not "the answer has
                            no supporting evidence".

    No evidence is ever retrieved, searched for, re-ranked or reconstructed here.
    """
    t0 = time.perf_counter()
    ms = lambda: (time.perf_counter() - t0) * 1000.0
    if evidence is not None:
        try:
            snapshot = TR.load(evidence)
        except Exception as exc:                  # noqa: BLE001 - a bad record is reported, never repaired
            info = {"provenance": TR.MISSING, "error": f"{type(exc).__name__}: {exc}"}
            return AccuracyAssessment.unavailable(
                "The evidence recorded for this answer failed its integrity check, so the answer is not assessed "
                "against it.", elapsed_ms=ms(), checked={"evidence_status": "integrity_failed"}, evidence=info)
        base = package if package is not None else snapshot
        info = {"provenance": TR.EXACT, **snapshot.summary()}
        if package is not None:
            info["package_matches_snapshot"] = [s.text for s in package.sources] == [i.text for i in snapshot.items]
        result = _evaluate(question, answer, package=_ExactEvidence(base, snapshot),
                           coverage=coverage if coverage is not None else snapshot, **kwargs)
    elif package is not None:
        provenance = evidence_provenance or TR.LEGACY_RECONSTRUCTED
        if provenance == TR.EXACT:
            raise ValueError("EXACT provenance requires the captured evidence snapshot (evidence=...)")
        info = {"provenance": provenance, "fingerprint": None, "items": len(package.sources),
                "guidance_items": sum(1 for s in package.sources if getattr(s, "corpus", "") == "fda_guidance")}
        result = _evaluate(question, answer, package=package, coverage=coverage, **kwargs)
    else:
        return AccuracyAssessment.unavailable(
            "The evidence this answer was generated from was not captured, so there is nothing to assess it "
            "against. This says nothing about whether the answer is supported.", elapsed_ms=ms(),
            checked={"sources": 0, "evidence_status": "not_captured"}, evidence={"provenance": TR.MISSING})
    return replace(result, evidence=info, checked={**result.checked, "evidence_provenance": info["provenance"]})


VERDICT_LABELS = {
    AN.CORRECT: "Correct", AN.PARTIAL: "Partially correct", AN.INCORRECT: "Incorrect",
    AN.OFF_TOPIC: "Answers a different question", AN.ANSWER_UNVERIFIABLE: "Cannot be verified",
    AN.ABSTENTION_CORRECT: "Correct refusal", AN.ABSTENTION_INCORRECT: "Incorrect refusal",
}

_SUBSTANTIVE_OF = {
    AN.CORRECT: R.PASS, AN.PARTIAL: R.PARTIAL, AN.INCORRECT: R.FAIL, AN.OFF_TOPIC: R.FAIL,
    AN.ANSWER_UNVERIFIABLE: R.NOT_ESTABLISHED, AN.ABSTENTION_CORRECT: R.PASS, AN.ABSTENTION_INCORRECT: R.FAIL,
}


def _refusal_verdict(result: AB.AbstentionResult) -> AN.AnswerVerdict:
    """A refusal's verdict. Withholding a draft that failed validation is a
    refusal in effect: the question went unanswered (rubric N=0)."""
    verdict = {AB.CORRECT: AN.ABSTENTION_CORRECT, AB.INCORRECT: AN.ABSTENTION_INCORRECT,
               AB.WITHHELD: AN.ABSTENTION_INCORRECT, AB.INCOMPLETE: AN.PARTIAL,
               AB.UNDECIDED: AN.ANSWER_UNVERIFIABLE}[result.outcome]
    return AN.AnswerVerdict(verdict, result.reason)


def _reason(status: str, results: Sequence[DimensionResult], accuracy: int | None,
            verdict: "AN.AnswerVerdict | None" = None) -> str:
    if verdict is not None:
        # the answer-level verdict leads: it is the one thing a reader must not miss
        return f"{VERDICT_LABELS[verdict.verdict]}: {verdict.reason}"
    if status == R.NOT_SCORED:
        return ("The answer states no regulatory requirement — it declines, or withholds what could not be "
                "validated — so there is no regulatory claim to score.")
    if status == R.UNABLE:
        gate = next((d for d in results if d.dimension == R.SUBSTANTIVE), None)
        return ("Not enough can be established from the authoritative evidence to score this answer. "
                + (gate.detail if gate is not None else ""))
    failed = [d for d in results if d.state == R.FAIL]
    partial = [d for d in results if d.state == R.PARTIAL]
    unknown = [d for d in results if d.state == R.NOT_ESTABLISHED]
    if failed:
        return "; ".join(f"{R.LABELS[d.dimension]}: {d.detail}" for d in failed)
    if partial or unknown:
        return "; ".join(f"{R.LABELS[d.dimension]}: {d.detail}" for d in (*partial, *unknown))
    return "Every check this rubric can decide from the retrieved evidence passed."


def evaluate_safely(*args, **kwargs) -> AccuracyAssessment:
    """`evaluate`, with the guarantee that it cannot affect answer delivery.

    Any exception becomes an assessment of `evaluator_error`. The caller shows
    the answer either way; this function exists so that the call site has no
    reason to contain a bare except of its own.
    """
    t0 = time.perf_counter()
    try:
        return evaluate(*args, **kwargs)
    except Exception as exc:                      # noqa: BLE001 - isolation is the point
        from regulus.evaluation.runner import sanitize_error

        return AccuracyAssessment.unavailable(
            f"The accuracy evaluator failed, so no assessment is shown. The answer itself is unaffected. "
            f"({sanitize_error(exc)})", status=R.ERROR, elapsed_ms=(time.perf_counter() - t0) * 1000.0)
