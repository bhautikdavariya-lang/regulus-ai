"""Claim assessments, and the verdict on the answer as a whole.

One record per regulatory proposition, carrying every determination the
evaluator made about it, so that any displayed result can be traced back to
the claim, the passage and the operator that decided it:

    claim            the proposition (split out of its sentence when the sentence
                     lists several independent obligations)
    relevance        does it answer the question? (regulus.accuracy.relevance)
    evidence         the passages it was judged against, with citations
    support          SUPPORTED | PARTIALLY_SUPPORTED | CONTRADICTED | UNVERIFIABLE,
                     decided by regulus.accuracy.verdicts; never by similarity
    operators        strength / polarity / actor / quantity / date / condition,
                     each matched, mismatched, dropped or undetermined
    citation         correct | points_elsewhere | missing | invalid, kept apart
                     from support: a true claim with a bad citation is still true
    final            the one status the answer verdict counts

Three distinctions this module must never blur, all mandated:

* **absent evidence is not falsehood.** No corresponding passage makes a claim
  UNVERIFIABLE (basis `no_evidence`), not wrong. Only an operator conflict on
  an aligned passage makes it CONTRADICTED.
* **true is not responsive.** A claim the evidence supports but that answers a
  different question is IRRELEVANT, and IRRELEVANT outranks SUPPORTED.
* **a citation defect is not a substantive defect.** SUPPORTED_WITH_CITATION_DEFECT
  counts as supported for correctness and fails only the citation dimension.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from regulus.accuracy import operators as OP
from regulus.accuracy import relevance as RV
from regulus.accuracy import verdicts as VD
from regulus.accuracy.alignment import Passage
from regulus.accuracy.attribution import MARK_RE
from regulus.accuracy.claims import Sentence, cited, propositions
from regulus.accuracy.intent import QuestionIntent, matched, required_hits, terms

# ------------------------------------------------------------ claim support

SUPPORTED = "supported"
PARTIALLY_SUPPORTED = "partially_supported"
CONTRADICTED = "contradicted"
IRRELEVANT = "irrelevant"
UNVERIFIABLE = "unverifiable"
SUPPORTED_WITH_CITATION_DEFECT = "supported_with_citation_defect"

_SUPPORT_OF = {
    VD.SUPPORTED: (SUPPORTED, "verbatim"),
    VD.PARAPHRASE: (SUPPORTED, "paraphrase"),
    VD.PARTIAL: (PARTIALLY_SUPPORTED, "drops_a_condition"),
    VD.CONTRADICTED: (CONTRADICTED, "operator_conflict"),
    VD.UNSUPPORTED: (UNVERIFIABLE, "no_evidence"),
    VD.UNDECIDABLE: (UNVERIFIABLE, "not_decisive"),
}
_DECIDED = (VD.SUPPORTED, VD.PARAPHRASE, VD.PARTIAL, VD.CONTRADICTED)

# ------------------------------------------------------------ answer verdicts

CORRECT = "correct"
PARTIAL = "partial"
INCORRECT = "incorrect"
OFF_TOPIC = "off_topic"
ANSWER_UNVERIFIABLE = "unverifiable"
ABSTENTION_CORRECT = "abstention_correct"
ABSTENTION_INCORRECT = "abstention_incorrect"
ANSWER_VERDICTS = (CORRECT, PARTIAL, INCORRECT, OFF_TOPIC, ANSWER_UNVERIFIABLE, ABSTENTION_CORRECT,
                   ABSTENTION_INCORRECT)

# An answer is off-topic when no claim answers the question, or when at least
# this share of its claims answers a different one and none answers this one.
OFF_TOPIC_SHARE = 2 / 3


@dataclass(frozen=True)
class ClaimAssessment:
    claim: str
    sentence: str                      # the sentence it came from (equal to claim unless split)
    support: str
    support_basis: str
    support_reason: str
    relevance: RV.ClaimRelevance
    operators: dict[str, str]
    citation: str
    citation_detail: str
    evidence: tuple[dict[str, Any], ...]
    final: str
    evidence_text: str = ""            # the passages' text, for element coverage; not serialised
    # claim -> passage -> source authority -> both sides' operators -> relation -> verdict
    operator_trace: dict[str, Any] | None = None
    # Priority 3 claim trace: where the claim came from and how it was matched
    claim_id: str = ""
    sentence_index: int = -1
    normalized_text: str = ""
    resolved_from: str | None = None           # the antecedent a leading "These ..." was resolved to
    subclaim: dict[str, Any] | None = None     # {"head", "item"} for one item of an include-type list
    candidate_evidence: tuple[str, ...] = ()   # passages the aligner proposed (citations, best first)
    match_path: str = "sentence"               # sentence | descriptive | definition | list_item | adjacent_window
    citation_trace: dict[str, Any] | None = None   # each cited source and whether it supports the claim

    @property
    def counts_as_supported(self) -> bool:
        return self.final in (SUPPORTED, SUPPORTED_WITH_CITATION_DEFECT)

    @property
    def answers_question(self) -> bool:
        return self.relevance.verdict in (RV.RELEVANT, RV.PARTIALLY_RELEVANT)

    def to_dict(self) -> dict[str, Any]:
        return {"claim": self.claim[:300], "split_from": self.sentence[:300] if self.sentence != self.claim else None,
                "relevance": self.relevance.to_dict(), "evidence": list(self.evidence),
                "support": self.support, "support_basis": self.support_basis, "support_reason": self.support_reason,
                "operators": dict(self.operators), "operator_trace": self.operator_trace,
                "citation": self.citation, "citation_detail": self.citation_detail, "final": self.final,
                "claim_id": self.claim_id, "sentence_index": self.sentence_index,
                "normalized_text": self.normalized_text[:300], "resolved_from": self.resolved_from,
                "subclaim": self.subclaim, "candidate_evidence": list(self.candidate_evidence),
                "selected_evidence": self.evidence[0]["citation"] if self.evidence else None,
                "match_path": self.match_path, "citation_trace": self.citation_trace}


def _operator_trace(verdict) -> dict[str, Any] | None:
    """How the support/contradiction decision was reached, for forensic review:
    the passage, its source authority, each side's operators, every relation
    deliberately not counted as a conflict, and the verdict."""
    comparison = verdict.comparison
    if comparison is None:
        return None
    passage = verdict.alignment.passage if verdict.alignment is not None else None
    keep = ("strength", "polarity", "duty_holder", "conditions")
    return {"evidence_citation": passage.citation if passage is not None else None,
            "source_type": comparison.authority,
            "claim_operators": {k: (comparison.claim_operators or {}).get(k) for k in keep},
            "evidence_operators": {k: (comparison.evidence_operators or {}).get(k) for k in keep},
            "conflicts": [{"operator": c["operator"], "claim": c["claim"], "evidence": c["evidence"]}
                          for c in comparison.conflicts],
            "relations": list(comparison.relations), "support_blocked": comparison.support_blocked,
            "verdict": verdict.verdict, "content_gate": verdict.gate}


def _operator_report(comparison) -> dict[str, str]:
    """Each operator's outcome, by name, for the trace."""
    if comparison is None:
        return {}
    out: dict[str, str] = {}
    for name in comparison.agreed:
        out[name.split(":")[0]] = "matched"
    for name in comparison.undetermined:
        out.setdefault(name.split(":")[0], "undetermined")
    for c in comparison.conflicts:
        out[c["operator"]] = "mismatched"
    for o in comparison.omissions:
        out[o["operator"]] = "dropped"
    return out


# ------------------------------------------------------------ citation grounding
#
# Rubric column L (frozen, regulus_substantive_rubric_v1): "Every regulatory
# citation in the response is correct to the section, and to the paragraph where
# the response asserts a paragraph-level requirement." Machine rule:
#
#   a claim's citation is CORRECT when a source it cites supports the claim to
#   the same standard as the support verdict (verbatim / paraphrase / list item /
#   descriptive / adjacent window, Priority 2 operator rules intact). A cited
#   source that is about the claim but contradicts it is still the right source:
#   the defect is substantive, not a citation defect.
#
# Which sources a claim cites, and at what granularity:
#   own      [n] markers on the claim itself (or on its list item): a marker
#            cites the statement it is ATTACHED to, and each marked source is
#            checked at its own granularity - a paragraph when it is a paragraph
#            (acceptance row M-020: shifted paragraph pointers, L=0)
#   block    a line of markers and nothing else, after the claim (row E-001: a
#            standalone "[1]" under the answer, read by the reviewer as citing
#            it; 11.100(a) is not the section that states 11.1(a): L=0). Read at
#            SECTION level, since it names no statement in particular
#   named    no marker, but the claim names a provision that is an evidence
#            source: that provision is the citation, at the granularity named
#   trailing no marker of its own, but a later marker in its paragraph: that
#            marker cites it IF its source supports it; otherwise the statement
#            is simply uncited, never mis-cited. Both halves are the reviewer's:
#            row P-010 (an 812.40 quotation followed by a pointer carrying [1] ->
#            812.40: "quoted from 812.40 and cited to it", L=1) and row C-002 ("the
#            single citation to 701.10 matches the statement attached to it, so
#            citation accuracy is met", though other statements in its paragraph
#            come from 701.11 and 701.12, L=1); likewise G-004
#   none     anything else is UNCITED. Uncited is not a defect unless nothing in
#            the answer is cited (rubric L=0: "no citation at all")
#
# When some source states the claim VERBATIM, a cited source counts only if it
# states it at least as completely (its verbatim coverage of the claim is no
# lower than the best). Shared boilerplate otherwise passes for the claim: "Any
# cosmetic containing bithionol is deemed to be adulterated under section
# 601(a) ..." is 81% verbatim in the vinyl-chloride section - above the 80%
# verbatim threshold - and 100% in the bithionol section, which is the one that
# states it. Equal coverage is a tie and every tied source is a correct citation
# (row C-004: 84% in both 700.11(a) and 700.14(a)). Coverage is measured directly
# over every passage, so this is independent of any aligner's ranking. With no
# verbatim statement anywhere, a cited source supports at the support verdict's
# own paraphrase-level standard.
#
# The support aligner's top-ranked passage NEVER decides a citation (row C-004:
# 700.11(a) and 700.14(a) end in the same sentence; ranking 700.14(a) first made
# a correct [1] -> 700.11(a) look wrong). It is used only to know whether SOME
# source supports the claim, which separates "cites the wrong source" from
# "nothing captured establishes it" (unverified, never a defect).

CITE_CORRECT = "correct"
CITE_POINTS_ELSEWHERE = "points_elsewhere"
CITE_PARAGRAPH_MISMATCH = "paragraph_mismatch"
CITE_GUIDANCE_FOR_REQUIREMENT = "guidance_for_requirement"
CITE_INVALID = "invalid"
CITE_MISSING = "missing"
CITE_UNVERIFIED = "unverified"
CITATION_DEFECTS = (CITE_POINTS_ELSEWHERE, CITE_PARAGRAPH_MISMATCH, CITE_GUIDANCE_FOR_REQUIREMENT, CITE_INVALID)

_SECTION_RE = re.compile(r"(\d{1,4}\.\d+[a-z]?)")


def _section(citation: str | None) -> str | None:
    m = _SECTION_RE.search(citation or "")
    return m.group(1) if m else None


def _verbatim_coverage(unit: str, passages: Sequence[Passage]) -> float:
    """The best verbatim coverage of the claim in these passages, counted only when
    it meets the attribution standard (>= 80% and a run of >= 6 words); else 0."""
    from regulus.accuracy.attribution import (ATTRIBUTION_MIN_COVERAGE, ATTRIBUTION_MIN_RUN_WORDS, longest_run,
                                              normalise, strip_lead)

    words = normalise(strip_lead(unit)).split()
    best = 0.0
    for p in passages:
        run, _ = longest_run(words, normalise(p.text))
        coverage = run / len(words) if words else 0.0
        if coverage >= ATTRIBUTION_MIN_COVERAGE and run >= ATTRIBUTION_MIN_RUN_WORDS:
            best = max(best, coverage)
    return best


def support_against(unit: str, sub: dict[str, str] | None, antecedent: str | None,
                    cited: Sequence[Passage], evidence: Sequence[Passage] | None = None) -> "VD.ClaimVerdict | None":
    """The claim judged against ONLY the given passages, with the same support
    paths as the substantive verdict. Lexical alignment over just these passages:
    deterministic, and independent of how any aligner ranks the whole evidence."""
    from regulus.accuracy.alignment import LexicalAligner, adjacent_windows

    if not cited:
        return None
    pool = evidence if evidence is not None else cited
    alignments = LexicalAligner().align(unit, cited, top_k=len(cited))
    verdict = VD.judge(unit, alignments, evidence=pool)
    if verdict.verdict in _DECIDED:
        return verdict
    found = (VD.judge_item(unit, sub["head"], sub["item"], cited, context=antecedent or "")
             if sub is not None else None)
    if found is None and sub is None:
        found = VD.judge_descriptive(unit, alignments, evidence=pool)
    if found is None and sub is None:
        found = VD.judge_definition(unit, alignments, evidence=cited)
    if found is None:
        found = VD.judge_window(unit, adjacent_windows([a.passage for a in alignments], cited), evidence=pool)
    return found if found is not None else verdict


def _named_sources(text: str, sources) -> list:
    """Evidence sources a claim names in its text ("... (21 CFR 211.80(d))")."""
    from regulus.retrieval.references import parse_cfr_references

    named = [r for r in parse_cfr_references(MARK_RE.sub(" ", text)) if r.section]
    out = []
    for s in sources:
        have = next(iter(parse_cfr_references(s.citation or "")), None)
        if have is None or not have.section:
            continue
        if any(n.section == have.section and (have.paragraph_path.startswith(n.paragraph_path)
                                              or n.paragraph_path.startswith(have.paragraph_path)) for n in named):
            out.append(s)
    return out


def judge_citation(unit: str, sub: dict[str, str] | None, antecedent: str | None, sentence: Sentence,
                   sentences: Sequence[Sentence], passages: Sequence[Passage], by_index, provisions,
                   support: "VD.ClaimVerdict") -> tuple[str, str, dict[str, Any]]:
    """(status, detail, trace) for one claim's citation. See the block comment above."""
    own_text = sub["item"] if sub is not None and MARK_RE.search(sub["item"]) else sentence.text
    marks = list(dict.fromkeys(int(m) for m in MARK_RE.findall(own_text)))
    kind = "own"
    if not marks:
        # the first later marker: a marker-only line (block), or a marker on a
        # later statement of the same paragraph (trailing)
        at = next((i for i, s in enumerate(sentences) if s is sentence), None)
        for s in (sentences[at + 1:] if at is not None else []):
            if not MARK_RE.search(s.text):
                continue
            later = list(dict.fromkeys(int(m) for m in MARK_RE.findall(s.text)))
            if not re.sub(r"[\s.,;:]+", "", MARK_RE.sub("", s.text)):
                marks, kind = later, "block"
            elif s.paragraph == sentence.paragraph:
                marks, kind = later, "trailing"
            break
    trace: dict[str, Any] = {"kind": kind, "markers": [], "rule": None}
    invalid = [m for m in marks if m not in by_index]
    if invalid:
        trace["markers"] = [{"marker": m, "source": None, "verdict": "no such source"} for m in invalid]
        trace["rule"] = "a marker that matches no supplied source"
        return CITE_INVALID, f"[{invalid[0]}] matches no supplied source", trace
    cited_sources = [by_index[m] for m in marks]
    if not cited_sources:
        named = _named_sources(unit, by_index.values())
        if named:
            cited_sources, kind = named, "named"
            trace["kind"] = kind
        else:
            trace["kind"] = "none"
            return CITE_MISSING, "the statement carries no citation of its own", trace

    # Each cited source on its own. A source is cited by its index; its passages
    # are exactly the sentences of that source in the (exact or legacy) evidence.
    elsewhere = (support.alignment.passage
                 if support.alignment is not None and support.verdict in (VD.SUPPORTED, VD.PARAPHRASE, VD.PARTIAL)
                 else None)
    best_verbatim = _verbatim_coverage(unit, passages)
    supporting = []
    for s in cited_sources:
        mine = [p for p in passages if p.source_index == s.index]
        verdict = support_against(unit, sub, antecedent, mine, evidence=passages)
        decided = verdict is not None and verdict.verdict in (VD.SUPPORTED, VD.PARAPHRASE, VD.PARTIAL, VD.CONTRADICTED)
        if decided and best_verbatim:
            decided = _verbatim_coverage(unit, mine) >= best_verbatim
        trace["markers"].append({"marker": s.index if kind != "named" else None, "source": s.citation,
                                 "verdict": verdict.verdict if verdict is not None else "no_passages",
                                 "supports": decided})
        if decided:
            supporting.append((s, verdict))
    labels = ", ".join(s.citation for s in cited_sources)
    if supporting:
        # guidance cited for a binding requirement that the regulation itself states
        binding = [s for s, _ in supporting if OP.authority_of(getattr(s, "corpus", None)) == OP.BINDING]
        if (not binding and OP.strength(unit) == OP.MANDATORY and elsewhere is not None
                and elsewhere.authority == OP.BINDING):
            trace["rule"] = "guidance cited as the source of a requirement the regulation states"
            return (CITE_GUIDANCE_FOR_REQUIREMENT, f"cites guidance ({labels}) for a requirement stated in "
                    f"{elsewhere.citation}", trace)
        trace["rule"] = "a cited source supports the claim"
        return CITE_CORRECT, f"cites {supporting[0][0].citation}, which supports it", trace
    if kind == "trailing":
        trace["rule"] = "a later marker in the paragraph that does not support this statement: uncited, not mis-cited"
        return CITE_MISSING, f"the paragraph's marker ({labels}) does not cite this statement", trace
    if elsewhere is None:
        trace["rule"] = "no captured source establishes the claim, so neither can the citation"
        return CITE_UNVERIFIED, f"cites {labels}; the captured evidence does not establish the claim", trace
    if any(_section(elsewhere.citation) and re.search(rf"\b{re.escape(_section(elsewhere.citation))}\b", s.text or "")
           for s in cited_sources):
        trace["rule"] = "the cited source cross-references the provision that states the claim"
        return CITE_CORRECT, f"cites {labels}, which refers to {elsewhere.citation}", trace
    same_section = any(_section(s.citation) == _section(elsewhere.citation) for s in cited_sources)
    if same_section and kind == "block":
        trace["rule"] = "a standalone citation line naming the section that states the claim"
        return CITE_CORRECT, f"its paragraph cites {labels}, the section that states it ({elsewhere.citation})", trace
    if same_section:
        trace["rule"] = "right section, but the cited paragraph does not state the claim"
        return (CITE_PARAGRAPH_MISMATCH, f"cites {labels}, but the paragraph that states it is {elsewhere.citation}",
                trace)
    trace["rule"] = "the cited source does not support the claim; another source does"
    return CITE_POINTS_ELSEWHERE, f"cites {labels}, but the evidence that supports it is {elsewhere.citation}", trace


def nonclaim_citation_defects(sentences: Sequence[Sentence], by_index) -> list[str]:
    """Markers on sentences that are not claims (pointers, "the sources are [1][2]")
    are citations too. What they assert about a source is not checkable here, but
    a marker that matches no supplied source is wrong whatever the sentence."""
    from regulus.accuracy.claims import PIPELINE, QUOTATION

    out = []
    for s in sentences:
        if s.is_claim or s.origin in (PIPELINE, QUOTATION):
            continue
        for m in dict.fromkeys(int(x) for x in MARK_RE.findall(s.text)):
            if m not in by_index:
                out.append(f"[{m}] in \"{s.text.strip()[:80]}\" matches no supplied source")
    return out


def assess_claims(claim_sentences: Sequence[Sentence], sentences: Sequence[Sentence], intent: QuestionIntent,
                  passages: Sequence[Passage], aligner, package) -> list[ClaimAssessment]:
    """One ClaimAssessment per regulatory proposition.

    Per claim sentence: a leading "These ..." is resolved from the immediately
    preceding claim sentence (local only); the sentence is judged whole; only if
    it is not borne out is it split - a modal list into obligations that inherit
    the modal (`propositions`), an include-type list into items that inherit the
    head (`enumeration`). A unit not borne out by any single passage may still
    be supported by its list item (`judge_item`) or by two adjacent sentences of
    one source (`judge_window`); neither path can produce a contradiction.
    """
    from regulus.accuracy.alignment import adjacent_windows
    from regulus.accuracy.attribution import strip_lead
    from regulus.accuracy.claims import META, PIPELINE, QUOTATION, enumeration, resolve

    by_index = {s.index: s for s in package.sources}
    provisions = frozenset(s.citation for s in package.sources if s.citation)
    position = {id(s): i for i, s in enumerate(sentences)}
    sentence_relevance: dict[int, Any] = {}
    out: list[ClaimAssessment] = []
    for sentence in claim_sentences:
        at = position.get(id(sentence), -1)
        # the immediately preceding sentence, whatever its claim status (a
        # restatement of the question still names what "These" refers to), but
        # never text the pipeline wrote or a statement about the sources
        previous = (sentences[at - 1] if at > 0 and sentences[at - 1].origin not in (PIPELINE, QUOTATION, META)
                    else None)
        text, antecedent = resolve(sentence.text, previous.text if previous is not None else None)
        whole_alignments = aligner.align(text, passages)
        whole = VD.judge(text, whole_alignments, evidence=passages)
        enum = enumeration(text)
        units: list[tuple[str, dict[str, str] | None]] = [(text, None)]
        # Split only when the sentence as a whole is not borne out: a verbatim
        # sentence is correct as one, and cutting it would leave fragments no
        # passage contains contiguously.
        if not whole.borne_out:
            props = propositions(text)
            if len(props) > 1:
                units = [(u, None) for u in props]
            elif enum is not None and len(enum.items) > 1:
                units = [(u, {"head": enum.head, "item": item}) for u, item in zip(enum.units(), enum.items)]
            elif enum is not None:
                units = [(text, {"head": enum.head, "item": enum.items[0]})]
            if len(units) > 1:
                prepare = getattr(aligner, "prepare", None)
                if callable(prepare):
                    prepare([u for u, _ in units], passages)
        for n, (unit, sub) in enumerate(units):
            alignments = whole_alignments if unit == text else aligner.align(unit, passages)
            verdict = whole if unit == text else VD.judge(unit, alignments, evidence=passages)
            path = "sentence"
            if not verdict.borne_out and verdict.verdict != VD.CONTRADICTED:
                found = (VD.judge_item(unit, sub["head"], sub["item"], passages, context=antecedent or "")
                         if sub is not None else None)
                if found is None and sub is None:
                    found = VD.judge_descriptive(unit, alignments, evidence=passages)
                    path = "descriptive" if found is not None else path
                if found is None and sub is None:
                    found = VD.judge_definition(unit, alignments, evidence=passages)
                    path = "definition" if found is not None else path
                if found is not None:
                    verdict, path = found, ("list_item" if sub is not None else path)
                else:
                    found = VD.judge_window(unit, adjacent_windows([a.passage for a in alignments], passages),
                                            evidence=passages)
                    if found is not None:
                        verdict, path = found, "adjacent_window"
            passage = verdict.alignment.passage if verdict.alignment is not None and verdict.verdict in _DECIDED else None
            rel = RV.assess(unit, intent, passages, judged_against=passage)
            if sub is not None and rel.verdict in (RV.IRRELEVANT, RV.UNDETERMINED):
                # an item is about what its sentence is about: "mercury compounds"
                # alone names no subject, "prohibited ingredients include ..." does.
                # A DETERMINATE finding on the sentence carries to its items; when
                # the sentence's own relevance is undetermined, each item's own
                # evidence decides (a list of off-topic items is off-topic, row D-006).
                whole_rel = sentence_relevance.get(id(sentence))
                if whole_rel is None:
                    whole_rel = sentence_relevance[id(sentence)] = RV.assess(
                        text, intent, passages,
                        judged_against=whole.alignment.passage if whole.alignment is not None and whole.verdict in _DECIDED else None)
                if whole_rel.verdict in (RV.RELEVANT, RV.PARTIALLY_RELEVANT):
                    rel = whole_rel
            support, basis = _SUPPORT_OF[verdict.verdict]
            if path != "sentence" and support == SUPPORTED:
                basis = path
            citation, citation_detail, citation_trace = judge_citation(
                unit, sub, antecedent, sentence, sentences, passages, by_index, provisions, verdict)
            evidence_passages = [passage] if passage is not None else [p for p in passages if p.citation in rel.evidence]
            evidence = tuple({"citation": p.citation, "source_index": p.source_index,
                              "heading": p.heading, "text": p.text[:240]} for p in evidence_passages[:3])
            if rel.verdict == RV.IRRELEVANT:
                final = IRRELEVANT
            elif support == CONTRADICTED:
                final = CONTRADICTED
            elif support == SUPPORTED:
                final = (SUPPORTED_WITH_CITATION_DEFECT if citation in (CITE_MISSING, *CITATION_DEFECTS)
                         else SUPPORTED)
            else:
                final = support
            out.append(ClaimAssessment(
                claim=unit, sentence=sentence.text, support=support, support_basis=basis,
                support_reason=verdict.reason, relevance=rel, operators=_operator_report(verdict.comparison),
                citation=citation, citation_detail=citation_detail, evidence=evidence, final=final,
                evidence_text=" ".join(f"{p.heading or ''} {p.text}" for p in evidence_passages),
                operator_trace=_operator_trace(verdict), citation_trace=citation_trace,
                claim_id=f"s{at}" + (f".{n + 1}" if len(units) > 1 else ""), sentence_index=at,
                normalized_text=strip_lead(unit), resolved_from=antecedent, subclaim=sub,
                candidate_evidence=tuple(dict.fromkeys(a.passage.citation for a in alignments)), match_path=path))
    return out


def elements(intent: QuestionIntent, claims: Sequence[ClaimAssessment]) -> tuple[list[str], list[str], list[str]]:
    """(covered, unverified, missing) elements of what the question asks for.

    covered     a claim that answers the question and is at least partly
                supported is about the element
    unverified  only claims that could NOT be verified are about it: the answer
                addresses it, but nothing establishes that it does so correctly
    missing     nothing in the answer is about it

    Keeping "unverified" apart from "missing" is the mandated distinction between
    absent evidence and absent content. Treating them alike reported acceptance
    row C-004 - nine statements, all about prohibited cosmetic ingredients - as
    "does not cover the question's subject", because the evidence retrieved for
    it was recital text that could verify none of them.
    """
    verified = [c for c in claims if c.answers_question and c.final in (SUPPORTED, SUPPORTED_WITH_CITATION_DEFECT,
                                                                         PARTIALLY_SUPPORTED)]
    unverified_claims = [c for c in claims if c.answers_question and c.final == UNVERIFIABLE]

    def about(element, group) -> bool:
        if not element.terms:
            return bool(group)
        need = required_hits(len(element.terms))
        # a definitional question's term ("FDA") is its element even where it is a generic word elsewhere
        keep = frozenset(intent.topic) if "definition_term" in intent.signals else frozenset()
        return any(len(matched(element.terms, terms(c.relevance.content + " " + c.evidence_text, keep=keep))) >= need
                   for c in group)

    covered, unverified, missing = [], [], []
    for element in intent.elements:
        if about(element, verified):
            covered.append(element.label)
        elif about(element, unverified_claims):
            unverified.append(element.label)
        else:
            missing.append(element.label)
    return covered, unverified, missing


@dataclass(frozen=True)
class AnswerVerdict:
    verdict: str
    reason: str
    counts: dict[str, int] = field(default_factory=dict)
    elements_covered: tuple[str, ...] = ()
    elements_missing: tuple[str, ...] = ()
    elements_unverified: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reason": self.reason, "counts": dict(self.counts),
                "elements_covered": list(self.elements_covered), "elements_missing": list(self.elements_missing),
                "elements_unverified": list(self.elements_unverified)}


def verdict(intent: QuestionIntent, claims: Sequence[ClaimAssessment], *, decisive_failure: str | None = None
            ) -> AnswerVerdict:
    """The verdict on an answer that states requirements (refusals are decided
    in regulus.accuracy.abstention). `decisive_failure` carries an absolute
    finding made elsewhere: a fabricated identifier or figure, an applicability
    contradiction, a validation failure."""
    counts = {s: sum(1 for c in claims if c.final == s) for s in
              (SUPPORTED, SUPPORTED_WITH_CITATION_DEFECT, PARTIALLY_SUPPORTED, CONTRADICTED, IRRELEVANT, UNVERIFIABLE)}
    answering = [c for c in claims if c.answers_question]
    irrelevant = [c for c in claims if c.final == IRRELEVANT]
    contradicted = [c for c in answering if c.final == CONTRADICTED]
    supported = [c for c in answering if c.counts_as_supported]
    partial = [c for c in answering if c.final == PARTIALLY_SUPPORTED]
    partly_relevant = [c for c in answering if c.relevance.verdict == RV.PARTIALLY_RELEVANT]
    # Unverified content counts against "correct" whether or not its relevance
    # could be determined. A sentence like "This duty is restated in 21 CFR
    # 820.777" names no subject (relevance undetermined) and has no evidence
    # (unverifiable); leaving it out would let an answer be called correct while
    # carrying a statement nobody checked.
    unverified = [c for c in claims if c.final == UNVERIFIABLE and c.relevance.verdict != RV.IRRELEVANT]
    covered, unverified_elements, missing = elements(intent, claims)

    def result(v: str, why: str) -> AnswerVerdict:
        return AnswerVerdict(v, why, counts, tuple(covered), tuple(missing), tuple(unverified_elements))

    if decisive_failure:
        return result(INCORRECT, decisive_failure)
    if contradicted:
        return result(INCORRECT, f"{len(contradicted)} statement(s) that address the question are contradicted by "
                                 f"the evidence: {contradicted[0].support_reason}")
    if not answering:
        if irrelevant:
            return result(OFF_TOPIC, f"none of the {len(claims)} statement(s) answers the question; "
                                     f"{len(irrelevant)} answer a different one - e.g. {irrelevant[0].relevance.reason}")
        return result(ANSWER_UNVERIFIABLE, "no statement could be related to the question or checked against evidence")
    if not supported and not partial:
        if irrelevant and len(irrelevant) / len(claims) >= OFF_TOPIC_SHARE:
            return result(OFF_TOPIC, f"{len(irrelevant)} of {len(claims)} statement(s) answer a different question and "
                                     f"none of the rest could be verified")
        return result(ANSWER_UNVERIFIABLE, f"{len(answering)} statement(s) address the question but none could be "
                                           f"verified against the retrieved evidence")
    problems = []
    if partial:
        problems.append(f"{len(partial)} statement(s) drop a condition the evidence carries")
    if unverified:
        problems.append(f"{len(unverified)} statement(s) could not be verified")
    if irrelevant:
        problems.append(f"{len(irrelevant)} statement(s) answer a different question")
    if partly_relevant:
        problems.append(f"{len(partly_relevant)} statement(s) only partly address the question - e.g. "
                        f"{partly_relevant[0].relevance.reason}")
    if missing:
        problems.append(f"the answer does not cover: {', '.join(missing)}")
    if problems:
        return result(PARTIAL, "; ".join(problems))
    return result(CORRECT, f"all {len(supported)} statement(s) answer the question and are supported by the evidence"
                           + (f"; covers {', '.join(covered)}" if len(covered) > 1 else ""))
