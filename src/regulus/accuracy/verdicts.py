"""The verdict on one claim against the evidence aligned to it.

The ladder, applied in this order, and the reason for the order:

1. **contradicted** - a regulatory operator disagrees on the best-aligned
   passage (strength, polarity, duty-holder, a quantity of a kind the evidence
   also quantifies, a date, or a condition the claim invents). Decided by
   `operators.compare`, never by similarity. This is checked FIRST so that no
   amount of surface agreement can outvote a disagreement about what the rule
   actually requires.
2. **supported** - the claim is a verbatim passage of the aligned evidence
   (contiguous run covering ATTRIBUTION_MIN_COVERAGE of it) and no operator
   conflicts. Identity, as before.
3. **paraphrase_equivalent** - not verbatim, but every operator that could be
   extracted from both sides AGREES, at least `MIN_OPERATORS_AGREED` of them
   were actually decided, and the claim's content terms are largely present in
   the aligned passage. The overlap term is deliberately last and never acts
   alone: it establishes that the claim is *about* this passage, while the
   operators establish that it says the same thing. Overlap alone was measured
   at 85.5% false passes on this corpus
   (docs/STAGE_A_VALIDATOR_LIMITATION.md), which is why it may not decide
   anything by itself.
4. **partial** - operators agree but the evidence carries a condition or
   applicability limit the claim drops. The rubric scores exactly this as N=1,
   "incomplete in a way that could mislead", so it is decided, not abstained.
5. **unsupported** - nothing in the evidence aligned to the claim at all.
6. **undecidable** - aligned, but too few operators could be extracted to say
   anything. The honest outcome, and the one the evaluator abstains on.

`MIN_OPERATORS_AGREED` is 2: one agreeing operator is too thin to carry a
paraphrase (almost every regulatory sentence is affirmative, so polarity alone
agrees by default). Nothing here produces a numeric confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

from regulus.accuracy import operators as OP
from regulus.accuracy.alignment import Alignment, Passage, content_terms
from regulus.accuracy.attribution import ATTRIBUTION_MIN_COVERAGE, ATTRIBUTION_MIN_RUN_WORDS, MARK_RE, strip_lead

SUPPORTED = "supported"
PARAPHRASE = "paraphrase_equivalent"
PARTIAL = "partial"
CONTRADICTED = "contradicted"
UNSUPPORTED = "unsupported"
UNDECIDABLE = "undecidable"

VERDICTS = (SUPPORTED, PARAPHRASE, PARTIAL, CONTRADICTED, UNSUPPORTED, UNDECIDABLE)
# the verdicts that mean "the evidence bears this claim out"
BORNE_OUT = (SUPPORTED, PARAPHRASE)

# A paraphrase must have at least this many operators actually decided and
# agreeing. Fail closed: fewer means undecidable, not equivalent.
MIN_OPERATORS_AGREED = 2
# ... and this share of its content terms present in the aligned passage. A
# supporting condition, never a sufficient one.
MIN_PARAPHRASE_OVERLAP = 0.7


@dataclass(frozen=True)
class ClaimVerdict:
    claim: str
    verdict: str
    reason: str
    alignment: Alignment | None = None
    comparison: OP.OperatorComparison | None = None
    gate: dict[str, Any] | None = None          # content-support gate trace (Phase 2D)

    @property
    def borne_out(self) -> bool:
        return self.verdict in BORNE_OUT

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.strip()[:300],
            "verdict": self.verdict,
            "reason": self.reason,
            "alignment": self.alignment.to_dict() if self.alignment is not None else None,
            "operators": self.comparison.to_dict() if self.comparison is not None else None,
            "content_gate": self.gate,
        }


# ------------------------------------------------------------ content-support gate
#
# INVARIANT (Phase 2D): evidence earns SUPPORTED, PARAPHRASE or PARTIAL only after
# it has independently established the claim's core proposition. Word overlap,
# agreeing modality, or a condition the passage carries can never establish it.
# A condition mismatch DOWNGRADES an established proposition to PARTIAL; it never
# makes one. (Phase 2C: 26 of 35 partial verdicts were granted only because the
# aligned passage carried "as appropriate" / "except as provided".)
#
# The proposition is established by one passage when
#   (1) no DISTINGUISHING term of the claim is missing from it, and
#   (2) it states the claim verbatim (>= 80%, run >= 6 - the attribution
#       standard), or it meets the existing paraphrase standard (>= 2 regulatory
#       operators agree and >= 70% of the claim's content terms are in it) AND
#       >= 70% of the claim's CORE terms (content terms less the generic
#       vocabulary below) are in it. Both, so the gate is never weaker than the
#       standard it guards: generic words dropped from the core must not lift a
#       passage that the plain paraphrase standard already rejects.
#
# A term is DISTINGUISHING when it is substantive (not in _GENERIC_TERMS, not
# the noun of a leading "These/Such ..." anaphor), ABSENT from the candidate's
# own source (text and heading) and PRESENT in a different evidence source - the
# evidence itself then shows it names a different regulated object: bithionol
# (700.11) vs chlorofluorocarbons (700.23), application vs annual information
# (601.28), operations (211.130) vs materials (211.122), validation (117.160) vs
# verification (117.165). A word found in no source ("adds", "specifically") or a
# synonym (files / records, kept / maintained) cannot be contrastive, so a
# legitimate paraphrase is never blocked by a missing word alone.

# Modal / operation verbs, structural words and discourse words: they say what is
# done or how, never WHICH regulated object - so they are never distinguishing.
_GENERIC_WORDS = """must may shall should can will require requires required requirement requirements mandate mandates
mandatory ensure ensures ensuring establish establishes established maintain maintains maintained follow follows
followed apply applies applied applicable include includes including contain contains contained provide provides
provided conduct conducts conducted implement implements implemented specify specifies specified state states stated
submit submits submitted comply complies compliance record records report reports add adds achieve achieved make
makes keep kept use used uses also additional general certain specific specifically following such these those
this that other any each all same part subpart section paragraph chapter title cfr fda agency regulation regulations
provision provisions requested""".split()
CONTENT_MIN_OVERLAP = MIN_PARAPHRASE_OVERLAP
# A passage that states no strength and no polarity ("are subject to the
# following components") gives the operators nothing to agree WITH: agreement
# is untestable, not refused. Content is then established by terms alone, to a
# stricter standard: every core term and nearly every framed term present.
SILENT_MIN_OVERLAP = 0.9
# The paraphrase standard's term overlap, with FRAMING words left out of it: the
# modal and "require" family, the agency, and discourse words say that a rule
# exists, not what it is about, so their absence from the passage ("The FDA
# requires additional controls ..." vs 11.30 "Persons ... shall employ controls")
# must not defeat a statement whose content is all there. ACTION words (submit,
# record, report, maintain ...) still count: "must report X" vs "must record X"
# differ in what is required, and that difference must keep failing.
_FRAMING_WORDS = frozenset("""must may shall should can will require requires required mandate mandates mandated
mandatory fda agency commissioner additional also specifically certain general including include includes
requested provision""".split())
_ANAPHOR_RE = re.compile(r"^\s*(?:-\s*)?(?:these|those|such|this|that)\s+((?:[a-z][\w-]*\s+){0,2}?[a-z][\w-]*)"
                         r"(?=\s+(?:is|are|was|were|must|shall|may|should|will|can|include|includes|have|has|apply|"
                         r"applies|require|requires|also|do|does)\b)", re.I)


@lru_cache(maxsize=1)
def _generic() -> frozenset[str]:
    from regulus.accuracy.intent import stem

    return frozenset(stem(w) for w in _GENERIC_WORDS)


def core_terms(claim: str) -> set[str]:
    """The claim's content-carrying stems: generic vocabulary and the noun of a
    leading anaphor ("These ingredients ..." - its antecedent is the previous
    sentence, row C-004) removed."""
    plain = strip_lead(claim)
    anaphor = _ANAPHOR_RE.match(plain)
    exempt = _stems(anaphor.group(1)) if anaphor else set()
    return {t for t in _stems(plain) if t not in _generic() and t not in exempt}


def distinguishing_terms(claim: str, passage: Passage, evidence: Sequence[Passage]) -> dict[str, list[str]]:
    """Core terms of the claim absent from the passage's own source but present in
    another evidence source, with the sources that carry them."""
    from regulus.accuracy.intent import same_term

    own_text = " ".join({p.text for p in evidence if p.source_index == passage.source_index} | {passage.text})
    own = _stems(f"{own_text} {passage.heading or ''}")
    others: dict[str, set[str]] = {}
    for p in evidence:
        if p.source_index != passage.source_index:
            others.setdefault(p.citation, set()).update(_stems(f"{p.text} {p.heading or ''}"))
    out: dict[str, list[str]] = {}
    for t in sorted(core_terms(claim)):
        if any(same_term(t, h) for h in own):
            continue
        where = [c for c, st in others.items() if any(same_term(t, h) for h in st)]
        if where:
            out[t] = where[:3]
    return out


def framed_overlap(claim: str, passage: Passage) -> float:
    """The paraphrase standard's overlap (unstemmed content terms, as the aligner
    measures it), less the framing words."""
    mine = {t for t in content_terms(strip_lead(claim)) if t not in _FRAMING_WORDS}
    if not mine:
        return 0.0
    return len(mine & content_terms(passage.text)) / len(mine)


def core_overlap(claim: str, passage: Passage) -> float:
    from regulus.accuracy.intent import same_term

    core = core_terms(claim)
    if not core:
        return 0.0
    have = _stems(passage.text)
    return sum(1 for t in core if any(same_term(t, h) for h in have)) / len(core)


def _unstated_narrowing(claim: str, passage_text: str) -> str | None:
    """The restrictive word ("only", "solely", "exclusively", "limited to") with which `claim` narrows
    a requirement, when `passage_text` states no restriction of its own; None otherwise.

    Operators and terms can all agree while the scope is changed ("Only a failure of a batch that has
    not been distributed must be investigated" against "... whether or not the batch has already been
    distributed"), so a narrowing the passage does not state withholds support on every support path.
    It never contradicts: the narrowing may be true for reasons this passage does not give. The
    conditional form ("only if ...") is a condition and is compared by the operators instead."""
    narrowing = OP.restrictive_scope(claim)
    if narrowing is None or OP.RESTRICTIVE_ONLY in OP.conditions(claim) or OP.states_a_restriction(passage_text):
        return None
    return narrowing


def _unstated_figure(claim: str, passage_text: str) -> str | None:
    """A figure the claim asserts - a quantity with its unit, or a date - that `passage_text` does
    not state at all; None otherwise.

    Operators that cannot compare a figure leave it undetermined, so "... must be thoroughly
    investigated within 30 days" was supported by a passage stating no period, on strength and
    polarity alone. A figure the passage never states withholds support on every support path; it
    never contradicts (the figure may be right, from another provision). Whether a figure the passage
    DOES state is used correctly stays with the operators' quantity, limit and date comparisons."""
    stated = OP.stated_numbers(passage_text)
    passage_dates = OP.dates(passage_text)
    for kind, value in OP.figures(claim):
        if value in stated or (kind == "date" and value in passage_dates):
            continue
        return f"{value} {kind}" if kind != "date" else value
    return None


def _agency_duty_unstated(claim: str, passage_text: str) -> bool:
    """True when `claim` places the obligation on FDA and `passage_text` gives FDA no such role.

    A passive duty of the regulated party ("... shall be thoroughly investigated") restated as FDA's
    ("FDA must thoroughly investigate ...") agreed on strength and polarity, its duty-holder was
    undetermined because the passage names none, and "fda" is a framing word for the term checks - so
    the role inversion was supported (Stage A). Narrow on purpose, measured on the 299 hand-scored
    acceptance answers: FDA speaking the rule ("FDA requires that ...") is not FDA's duty, a regulated
    party named for a passive rule ("the manufacturer must ...") is not touched, and FDA as the passive
    agent ("... by FDA") counts as the passage giving FDA the role. Withholds support; never contradicts."""
    return OP.agency_is_obligated(claim) and not OP.agency_role_stated(passage_text)


def content_gate(claim: str, alignment: Alignment, comparison: "OP.OperatorComparison",
                 evidence: Sequence[Passage] | None) -> dict[str, Any]:
    """Does this passage, on its own, establish the claim's core proposition?
    Candidate SELECTION (the aligner) is recorded but never decides this."""
    evidence = list(evidence) if evidence else [alignment.passage]
    verbatim = (alignment.verbatim_coverage >= ATTRIBUTION_MIN_COVERAGE
                and alignment.verbatim_run >= ATTRIBUTION_MIN_RUN_WORDS)
    complete = alignment.verbatim_coverage >= 0.999
    distinct = {} if complete else distinguishing_terms(claim, alignment.passage, evidence)
    overlap = core_overlap(claim, alignment.passage)
    has_core = bool(core_terms(claim))
    framed = framed_overlap(claim, alignment.passage)
    agreed = list(comparison.agreed)
    ev_ops = comparison.evidence_operators or {}
    silent = ev_ops.get("strength") is None and ev_ops.get("polarity") is None
    narrowing = _unstated_narrowing(claim, alignment.passage.text)
    figure = _unstated_figure(claim, alignment.passage.text)
    agency = _agency_duty_unstated(claim, alignment.passage.text)
    if distinct:
        verdict, reason = "blocked", (f"the claim names {', '.join(distinct)}, which {alignment.passage.citation} does "
                                      f"not and another source does ({'; '.join(f'{t}: {v[0]}' for t, v in distinct.items())})")
    elif narrowing is not None:
        verdict, reason = "not_established", (f"the claim narrows the requirement with '{narrowing}', which "
                                              f"{alignment.passage.citation} does not state")
    elif figure is not None:
        verdict, reason = "not_established", (f"the claim states {figure}, which {alignment.passage.citation} "
                                              f"does not state")
    elif agency:
        verdict, reason = "not_established", (f"the claim places the requirement on FDA, which "
                                              f"{alignment.passage.citation} does not")
    elif verbatim:
        verdict, reason = "established", f"{alignment.verbatim_coverage:.0%} verbatim"
    elif (len(agreed) >= MIN_OPERATORS_AGREED and framed >= MIN_PARAPHRASE_OVERLAP
          and (overlap >= CONTENT_MIN_OVERLAP or not has_core)):
        verdict, reason = "established", (f"{', '.join(agreed)} agree, {framed:.0%} of its terms and "
                                          f"{overlap:.0%} of its core terms are present")
    elif silent and not agreed and has_core and overlap >= 0.999 and framed >= SILENT_MIN_OVERLAP:
        # terms alone: enough to found a PARTIAL (the omission is then the
        # substantive difference), never a full support - the paraphrase
        # standard's operator agreement is not relaxed (a bare heading such as
        # "(a) Corrective action procedures." holds every term and no rule)
        verdict, reason = "established_terms_only", (f"the passage states no strength or polarity to compare; "
                                                     f"{framed:.0%} of its terms and every core term are present")
    else:
        verdict, reason = "not_established", (f"{len(agreed)} operator(s) agree, {framed:.0%} of its terms "
                                              f"and {overlap:.0%} of its core terms are present: the passage does not "
                                              f"state the claim")
    founded = verdict.startswith("established")
    return {"content_gate_verdict": verdict, "content_support_reason": reason if founded else None,
            "support_block_reason": reason if not founded else None,
            "distinguishing_terms": sorted(distinct), "distinguishing_term_sources": distinct,
            "core_overlap": round(overlap, 2), "term_overlap": round(framed, 2),
            "raw_term_overlap": round(alignment.overlap, 2),
            "verbatim_coverage": round(alignment.verbatim_coverage, 2),
            "operators_agreed": agreed, "operator_silent_passage": silent,
            # No grammatical roles are parsed: subject and object are tested together,
            # by the contrastive core-term test; the action's modality and polarity
            # by the Priority-2 operators (its verb by the core terms, generic verbs exempt).
            "core_object_match": not distinct, "core_subject_match": not distinct,
            "core_action_match": ("matched" if {"strength", "polarity"} <= set(agreed) else "undetermined"),
            "core_actor_match": ("matched" if "actor" in agreed else "undetermined"),
            "condition_match": not comparison.omissions,
            "material_omissions": [o["evidence"] for o in comparison.omissions],
            "candidate_selection": {"passage": alignment.passage.citation, "method": alignment.method,
                                    "similarity": alignment.similarity}}


# Operators whose disagreement still means the same thing when it is read against a NEIGHBOURING
# paragraph rather than the aligned one; see `_conflict_elsewhere`.
_NUMERIC_CONFLICTS = frozenset({OP.CONFLICT_QUANTITY, OP.CONFLICT_LIMIT, "date"})


def _conflict_elsewhere(claim: str, gate: dict[str, Any], best: Alignment,
                        pool: Sequence[Passage]) -> tuple[str, "OP.OperatorComparison"] | None:
    """The supplied source the claim is really about, when that source disagrees with the claim.

    `content_gate` blocks support when the claim names terms the aligned passage does not have and
    another supplied source does; it already records WHICH source. The aligner can land on a near
    neighbour that shares the claim's FIGURE while the subject matter belongs elsewhere: a claim
    putting the 15-calendar-day deadline of 21 CFR 312.32(c)(1) on the unexpected fatal or
    life-threatening suspected adverse reactions of (c)(2) aligns to (c)(1), agrees with it that
    the period is 15 calendar days, and so was abstained on - although (c)(2), in the same
    evidence, says 7. Comparing the claim with the source the gate named decides it.

    Conservative by construction, in two ways. Only a determinate conflict is reported: if the
    named source agrees with the claim, or states nothing comparable, None is returned and the
    verdict is left exactly as it was. And only a NUMERIC disagreement counts - a quantity, a
    limit's direction or a date. A number means the same thing in a neighbouring paragraph, so
    reading it across one is sound; strength, polarity and duty-holder do not. Measured over 120
    hand-scored acceptance rows, accepting those too turned four substantively correct or merely
    incomplete answers into "incorrect", among them C-004, which the rubric scores N=2.
    """
    sources = gate.get("distinguishing_term_sources") or {}
    if not sources:
        return None
    named = dict.fromkeys(c for citations in sources.values() for c in citations)
    for citation in named:
        if citation == best.passage.citation:
            continue
        passages = [x for x in pool if x.citation == citation]
        text = " ".join(x.text for x in passages)
        if not text.strip():
            continue
        comparison = OP.compare(claim, text, authority=getattr(passages[0], "authority", OP.BINDING))
        if any(c.get("operator") in _NUMERIC_CONFLICTS for c in comparison.conflicts):
            return citation, comparison
    return None


def _label(alignment: Alignment) -> str:
    return f"{alignment.passage.citation} (SOURCE {alignment.passage.source_index})"


def judge(claim: str, alignments: Sequence[Alignment], *, evidence: Sequence[Passage] | None = None) -> ClaimVerdict:
    """The verdict on one claim, given the passages aligned to it."""
    if not alignments:
        return ClaimVerdict(claim, UNSUPPORTED,
                            "no passage of the authoritative evidence is about this statement")

    # Operators are compared against every candidate: a conflict with the best
    # alignment is conclusive, but a claim that agrees with ANY aligned passage
    # is not contradicted just because it disagrees with a less relevant one.
    compared = [(a, OP.compare(claim, a.passage.text, authority=getattr(a.passage, "authority", OP.BINDING)))
                for a in alignments]
    clean = [(a, c) for a, c in compared if not c.conflicted]

    if not clean:
        best, comparison = compared[0]
        return ClaimVerdict(claim, CONTRADICTED,
                            "; ".join(c["detail"] for c in comparison.conflicts)
                            + f" (compared with {_label(best)})",
                            best, comparison)

    # A passage that does not contradict the claim may still be unable to
    # support it: guidance that RECOMMENDS what the claim states as a
    # requirement neither contradicts nor establishes that requirement.
    supportable = [(a, c) for a, c in clean if c.support_blocked is None]
    if not supportable:
        best, comparison = clean[0]
        return ClaimVerdict(claim, UNDECIDABLE, f"{comparison.support_blocked} ({_label(best)})", best, comparison)
    clean = supportable

    # A claim that is a verbatim passage of ONE candidate is supported by that
    # passage, whatever a similar neighbour says. Ranking by overlap alone was
    # measured to pair a verbatim quotation of 21 CFR 201.66(d)(2) with the
    # near-identical (d)(10)(ii), whose "except" is about "Drug Facts
    # (continued)" - a different item - and to mark the correct claim partial
    # (acceptance row G-004). Verbatim candidates are therefore tried first.
    verbatim = sorted([(a, c) for a, c in clean
                       if a.verbatim_coverage >= ATTRIBUTION_MIN_COVERAGE and a.verbatim_run >= ATTRIBUTION_MIN_RUN_WORDS],
                      key=lambda pair: -pair[0].verbatim_coverage)
    ordered = verbatim + [pair for pair in clean if pair not in verbatim]
    pool = list(evidence) if evidence else [a.passage for a in alignments]

    # Content gate on the SELECTED candidate. The gate only withholds credit:
    # letting it walk on to lower-ranked candidates was measured to grant
    # supports the selected one never would ("21 CFR 117.190(a) requires
    # attestations" from 117.201(a)), so a candidate that fails the gate makes
    # the claim undecidable rather than handing the decision to the next one.
    for best, comparison in ordered[:1]:
        gate = content_gate(claim, best, comparison, pool)
        if not gate["content_gate_verdict"].startswith("established"):
            continue
        if gate["content_gate_verdict"] == "established_terms_only" and not comparison.omissions:
            continue                      # content without operator agreement founds only a partial
        # Framing words are discounted only to FOUND a partial; full paraphrase
        # support keeps the unchanged standard's raw term overlap. Discounting
        # them there too was measured to admit new supports ("charge-in of
        # components" from a 211.101 passage that never says charge-in).
        if (not comparison.omissions and not gate["content_support_reason"].endswith("verbatim")
                and best.overlap < MIN_PARAPHRASE_OVERLAP):
            continue
        if comparison.omissions:          # downgrade an established proposition, never establish one
            return ClaimVerdict(claim, PARTIAL,
                                ("verbatim, but " if best.verbatim_coverage >= ATTRIBUTION_MIN_COVERAGE else "")
                                + "; ".join(o["detail"] for o in comparison.omissions) + f" ({_label(best)})",
                                best, comparison, gate)
        if gate["content_support_reason"].endswith("verbatim"):
            return ClaimVerdict(claim, SUPPORTED,
                                f"{best.verbatim_coverage:.0%} of it is verbatim in {_label(best)} and no regulatory "
                                f"operator disagrees", best, comparison, gate)
        return ClaimVerdict(claim, PARAPHRASE,
                            f"not verbatim, but {', '.join(comparison.agreed)} agree with {_label(best)} and "
                            f"{gate['core_overlap']:.0%} of its core terms are in that passage", best, comparison, gate)

    best, comparison = ordered[0]
    gate = content_gate(claim, best, comparison, pool)
    elsewhere = _conflict_elsewhere(claim, gate, best, pool)
    if elsewhere is not None:
        citation, against = elsewhere
        return ClaimVerdict(claim, CONTRADICTED,
                            "; ".join(c["detail"] for c in against.conflicts
                                      if c.get("operator") in _NUMERIC_CONFLICTS)
                            + f" (the statement is about {citation}, which the evidence supplies, not about "
                              f"{best.passage.citation}, which it was aligned to)",
                            best, against, gate)
    block = gate["support_block_reason"] or (f"{gate['content_support_reason']}, but no regulatory operator agrees, "
                                             f"so it is not established as stated")
    return ClaimVerdict(claim, UNDECIDABLE, f"aligned to {_label(best)}, but it does not establish the claim: {block}",
                        best, comparison, gate)


# ------------------------------------------------------------ list items

# Words a list's head uses to name the KIND of thing listed ("the requirements
# for X include ..."): they say what the items are, not which provision.
_GENERIC_HEAD = frozenset("""requirement requirements require required include includes including contain contains
comprise comprises consist consists add adds following element elements item items thing things content format
also general specific certain other such these those this that they them part subpart section paragraph chapter
cfr""".split())
# a structural label in a list head ("... under Part 117 Subpart B include ...") is proof of nothing by
# itself: the source must establish that it belongs to that subpart (row F-003)
_SUBPART_RE = re.compile(r"\bsubpart\s+([A-Z]{1,2})\b", re.I)
ITEM_MIN_TERMS = 3            # content terms an item needs for term-containment support
ITEM_MIN_CONTAINED = 0.85     # share of the item's (stemmed) content terms present in the passage
ITEM_MIN_RUN = 3              # ... and a verbatim run of at least this many words


def _stems(text: str) -> set[str]:
    """Stemmed content terms. A short gerund the stemmer leaves whole ("using",
    "making") is reduced to its base form too, so it meets "use" / "make"."""
    return set(_stems_cached(text))


@lru_cache(maxsize=8192)
def _stems_cached(text: str) -> frozenset[str]:
    from regulus.accuracy.intent import stem

    out = set()
    for t in content_terms(text):
        s = stem(t)
        if s == t and t.endswith("ing") and len(t) >= 5:
            s = stem(t[:-3] + "e")
        out.add(s)
    return frozenset(out)


def _contained(mine: set[str], theirs: set[str]) -> float:
    from regulus.accuracy.intent import same_term

    if not mine:
        return 0.0
    return sum(1 for t in mine if any(same_term(t, u) for u in theirs)) / len(mine)


def judge_item(claim: str, head: str, item: str, candidates: Sequence[Passage], *, context: str = "") -> ClaimVerdict | None:
    """Support for one item of "<head> include <item>, ...", or None.

    The item is the content; the head says what it belongs to. An item is
    supported only by a passage that (1) is from the provision the head names,
    or shares a term with the head, (2) contains the item verbatim (80% coverage,
    run >= 6 or the whole item) or contains its stemmed content terms (>= 85%,
    with a verbatim run of >= 3 words and >= 3 terms), (3) agrees on negation and
    on every number and date, and (4) is not guidance recommending what the head
    calls a requirement. This path can support; it never contradicts.
    """
    from regulus.accuracy.attribution import longest_run, normalise
    from regulus.retrieval.references import parse_cfr_references

    item_plain = MARK_RE.sub(" ", item).strip().rstrip(".")
    item_words = normalise(item_plain).split()
    item_terms = _stems(item_plain)
    if len(item_words) < 2 or len(item_terms) < 2:
        return None          # a single content word is a mention, not a statement that can be borne out
    frame = f"{head} {context}"
    refs = [r for r in parse_cfr_references(MARK_RE.sub(" ", frame)) if r.section]
    from regulus.accuracy.intent import stem

    generic = {stem(w) for w in _GENERIC_HEAD}
    head_terms = {t for t in _stems(strip_lead(head) + " " + context) if t not in generic}

    def belongs(p: Passage) -> bool:
        if refs:
            return any(r.section in (p.citation or "") for r in refs)
        about = _stems(f"{p.text} {p.heading or ''} {p.citation or ''}")
        return bool(head_terms) and _contained(head_terms, about) > 0

    requirement_head = bool(re.search(r"\brequir|\bmust\b|\bshall\b|\bmandator", head, re.I))
    # what the head says the items ARE decides what the passage must state: a
    # requirement / prohibition / restriction needs a MANDATORY passage (an
    # epistemic "may be exposed" in a recital is not one, row C-004); a
    # permission or exemption needs a deontic passage of any strength
    mandatory_head = requirement_head or bool(re.search(r"\bprohibit|\brestrict|\bobligat", head, re.I))
    deontic_head = mandatory_head or bool(re.search(r"\bpermit|\bexempt|\ballow", head, re.I))
    subparts = {m.upper() for m in _SUBPART_RE.findall(MARK_RE.sub(" ", head))}
    best: tuple[tuple, Passage, int, float, OP.OperatorComparison] | None = None
    for p in candidates:
        if not belongs(p):
            continue
        if subparts and not all(re.search(rf"\bsubpart\s+{x}\b", f"{p.text} {p.heading or ''}", re.I) for x in subparts):
            continue
        # the item must name nothing that a different source governs (content gate)
        if distinguishing_terms(item_plain, p, candidates):
            continue
        run, _ = longest_run(item_words, normalise(p.text))
        coverage = run / len(item_words)
        verbatim = coverage >= ATTRIBUTION_MIN_COVERAGE and run >= min(ATTRIBUTION_MIN_RUN_WORDS, len(item_words))
        contained = _contained(item_terms, _stems(p.text))
        by_terms = len(item_terms) >= ITEM_MIN_TERMS and contained >= ITEM_MIN_CONTAINED and run >= ITEM_MIN_RUN
        if not (verbatim or by_terms):
            continue
        comparison = OP.compare(item_plain, p.text, authority=p.authority)
        if comparison.conflicts or comparison.support_blocked or _unstated_narrowing(item_plain, p.text) \
                or _unstated_figure(item_plain, p.text) or _agency_duty_unstated(item_plain, p.text):
            continue
        if (OP.polarity(item_plain) == OP.NEGATE) != (OP.polarity(p.text) == OP.NEGATE):
            continue
        if requirement_head and p.authority == OP.GUIDANCE and OP.strength(p.text) in (OP.RECOMMENDED, OP.PERMISSIVE):
            continue
        # "prohibited ingredients include X" is not borne out by a passage that
        # merely MENTIONS X: a recital ("X has been used as an ingredient") states
        # no rule (acceptance row C-004, 21 CFR 700.14(a))
        if deontic_head and OP.strength(p.text) is None:
            continue
        if mandatory_head and OP.strength(p.text) != OP.MANDATORY:
            continue
        key = (verbatim, coverage, contained)
        if best is None or key > best[0]:
            best = (key, p, run, contained, comparison)
    if best is None:
        return None
    (verbatim, coverage, contained), p, run, contained, comparison = best
    alignment = Alignment(p, contained, run, len(item_words), method="list_item")
    gate = {"content_gate_verdict": "established", "distinguishing_terms": [], "core_object_match": True,
            "condition_match": not comparison.omissions,
            "material_omissions": [o["evidence"] for o in comparison.omissions],
            "content_support_reason": "list item stated by the source its head refers to",
            "candidate_selection": {"passage": p.citation, "method": "list_item"}}
    how = (f"{coverage:.0%} of it is verbatim" if verbatim else
           f"{contained:.0%} of its terms, with a {run}-word verbatim run, are")
    if comparison.omissions:   # established, then downgraded: the item drops a condition its source carries (E-005)
        return ClaimVerdict(claim, PARTIAL,
                            f"the listed item \"{item_plain[:80]}\" is in {_label(alignment)}, but "
                            + "; ".join(o["detail"] for o in comparison.omissions), alignment, comparison, gate)
    return ClaimVerdict(claim, SUPPORTED if verbatim else PARAPHRASE,
                        f"the listed item \"{item_plain[:80]}\": {how} in {_label(alignment)}, the source its heading refers "
                        f"to, and no regulatory operator disagrees", alignment, comparison, gate)


WINDOW_MIN_OVERLAP = 0.85
WINDOW_MIN_RUN_EACH = 5
DESCRIPTIVE_MIN_TERMS = 4
DESCRIPTIVE_MIN_CONTAINED = 0.85
DESCRIPTIVE_MIN_RUN = 6


def judge_descriptive(claim: str, alignments: Sequence[Alignment], *,
                      evidence: Sequence[Passage] | None = None) -> ClaimVerdict | None:
    """Support for a claim that states a rule descriptively, without a modal:
    "The headings ... USE uppercase letters for the first word" restating
    "All headings ... SHALL USE an uppercase letter ...". The operator ladder
    needs two agreeing operators and a modal-less sentence has at most one, so
    such a sentence could never be decided however exactly it restates its source.

    Strict, and support-only: the claim states no modality of its own; >= 85% of
    its (stemmed) content terms are in ONE passage, with a verbatim run of >= 6
    words and >= 4 terms; every regulated party it names is named there; negation
    agrees; and no operator conflicts or blocks support (Priority 2 rules intact).
    """
    from regulus.accuracy.attribution import longest_run, normalise

    plain = strip_lead(claim)
    if OP.strength(plain) is not None:
        return None
    terms = _stems(plain)
    claim_words = normalise(plain).split()
    if len(terms) < DESCRIPTIVE_MIN_TERMS:
        return None
    for a in alignments:
        p = a.passage
        contained = _contained(terms, _stems(p.text))
        run, _ = longest_run(claim_words, normalise(p.text))
        if contained < DESCRIPTIVE_MIN_CONTAINED or run < DESCRIPTIVE_MIN_RUN:
            continue
        if not OP.actors(plain) <= OP.actors(p.text):
            continue
        if (OP.polarity(plain) == OP.NEGATE) != (OP.polarity(p.text) == OP.NEGATE):
            continue
        comparison = OP.compare(plain, p.text, authority=p.authority)
        if comparison.conflicts or comparison.support_blocked or comparison.omissions or _unstated_narrowing(plain, p.text) \
                or _unstated_figure(plain, p.text) or _agency_duty_unstated(plain, p.text):
            continue
        pool = list(evidence) if evidence else [a.passage for a in alignments]
        if distinguishing_terms(claim, p, pool):
            continue
        reason = (f"a descriptive restatement: {contained:.0%} of its terms, with a {run}-word verbatim run, are "
                  f"in {_label(a)}, it names no other party, and no regulatory operator disagrees")
        # the descriptive standard IS this path's content standard: record it in the gate's terms
        gate = content_gate(claim, a, comparison, pool)
        gate.update({"content_gate_verdict": "established", "content_support_reason": reason,
                     "support_block_reason": None})
        return ClaimVerdict(claim, PARAPHRASE, reason,
                            Alignment(p, contained, run, len(claim_words), method="descriptive"), comparison, gate)
    return None


# ------------------------------------------------------------ definitions

# "FDA stands for the Food and Drug Administration" restates "FDA means the Food
# and Drug Administration" (21 CFR 10.3(a)), but neither the paraphrase ladder
# (no operators to agree) nor the descriptive standard (a 6-word verbatim run a
# short definition cannot reach) can decide it. A definition is decided by
# IDENTITY instead: the passage is the CFR's own definition of the same term
# ("<term> means <definiens>"), and the claim's definiens is that definiens,
# word for word after case, articles and punctuation. Anything else - another
# expansion, a partial one, a longer gloss - is not decided here.
_DEFINITION_CLAIM_RE = re.compile(
    r"^\s*(?:the\s+)?(?P<term>[A-Za-z][A-Za-z&/\-]*(?:\s+[A-Za-z][A-Za-z&/\-]*){0,4}?)\s+"
    r"(?:stands\s+for|is\s+short\s+for|is\s+an?\s+(?:abbreviation|acronym)\s+(?:for|of)|means|refers\s+to|is\s+defined\s+as)"
    r"\s+(?P<definiens>[^.;:]+?)\s*\.?\s*$", re.I)


_US_RE = re.compile(r"\bU\.S\.(?=\s|$)")     # "U.S." is one word, not the end of the definiens


def _definition_words(text: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9&]+", text.lower())
    while words and words[0] in ("the", "a", "an"):
        words = words[1:]
    return tuple(words)


def _defines(passage_text: str, term: str) -> tuple[str, ...] | None:
    """The definiens when the passage OPENS by defining `term` ("(x) FDA means ..."), else None."""
    m = re.match(r"^\s*(?:\([0-9A-Za-z]{1,6}\)\s*)*" + r"\s+".join(map(re.escape, term.split()))
                 + r"\s+means\s+(?P<d>[^.;:]+?)\s*(?:[.;:]|$)", _US_RE.sub("US", passage_text or ""), re.I)
    return _definition_words(m.group("d")) if m else None


def judge_definition(claim: str, alignments: Sequence[Alignment], *,
                     evidence: Sequence[Passage] | None = None) -> ClaimVerdict | None:
    """Support for a definitional claim by the CFR's own definition of the same term (see above)."""
    plain = MARK_RE.sub(" ", strip_lead(claim)).strip()
    m = _DEFINITION_CLAIM_RE.match(_US_RE.sub("US", plain))
    if not m:
        return None
    term, definiens = " ".join(m.group("term").split()), _definition_words(m.group("definiens"))
    if not definiens:
        return None
    candidates = [a.passage for a in alignments] + [p for p in (evidence or ()) if p not in [a.passage for a in alignments]]
    for p in candidates:
        if _defines(p.text, term) != definiens:
            continue
        comparison = OP.compare(plain, p.text, authority=p.authority)
        if (comparison.conflicts or comparison.support_blocked or _unstated_narrowing(plain, p.text)
                or _unstated_figure(plain, p.text) or _agency_duty_unstated(plain, p.text)):
            continue
        pool = list(evidence) if evidence else candidates
        reason = (f"a definition: {p.citation} defines {term} as \"{' '.join(definiens)}\", word for word what the "
                  f"answer states")
        alignment = Alignment(p, 1.0, len(definiens), len(plain.split()), method="definition")
        gate = content_gate(claim, alignment, comparison, pool)
        gate.update({"content_gate_verdict": "established", "content_support_reason": reason,
                     "support_block_reason": None})
        return ClaimVerdict(claim, PARAPHRASE, reason, alignment, comparison, gate)
    return None


def judge_window(claim: str, windows: Sequence[Passage], *,
                 evidence: Sequence[Passage] | None = None) -> ClaimVerdict | None:
    """Support from two adjacent sentences of one source; None otherwise. A window
    is only ever evidence FOR a claim: a conflict with a window is ignored, since
    joining two sentences can put one sentence's modal next to the other's subject."""
    from regulus.accuracy.alignment import LexicalAligner
    from regulus.accuracy.attribution import longest_run, normalise
    from regulus.evaluation.grounding_eval import split_sentences

    if not windows:
        return None
    verdict = judge(claim, LexicalAligner().align(claim, windows), evidence=evidence)
    if verdict.verdict not in BORNE_OUT:
        return None
    # A window must be NEEDED and USED: a verbatim run of >= 5 words into each of
    # its two sentences, and >= 85% of the claim's terms. Otherwise one sentence
    # carries the match and the other only adds terms that inflate the overlap
    # (row F-007: a plan-contents claim "supported" by a verification passage).
    words = normalise(strip_lead(claim)).split()
    halves = split_sentences(verdict.alignment.passage.text)
    if len(halves) < 2 or verdict.alignment.overlap < WINDOW_MIN_OVERLAP:
        return None
    if any(longest_run(words, normalise(h))[0] < WINDOW_MIN_RUN_EACH for h in halves[:2]):
        return None
    return ClaimVerdict(claim, verdict.verdict, "across two adjacent sentences of one source: " + verdict.reason,
                        verdict.alignment, verdict.comparison, verdict.gate)


def counts(verdicts: Sequence[ClaimVerdict]) -> dict[str, int]:
    out = {v: 0 for v in VERDICTS}
    for v in verdicts:
        out[v.verdict] += 1
    return out
