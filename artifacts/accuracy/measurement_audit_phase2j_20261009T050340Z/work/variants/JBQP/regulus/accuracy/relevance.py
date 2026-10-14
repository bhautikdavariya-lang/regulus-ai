"""Does a claim answer the question that was asked?

The second question every claim must pass, separate from whether it is true.
Phase 1 asked only "is this sentence borne out by some regulatory text?", and
acceptance row D-001 showed why that is not enough: twenty sentences quoted
verbatim from 21 CFR 211.100-211.132 (production and process controls), given
in answer to "What is the SCOPE of 21 CFR Part 211 and how does it relate to
Part 210?", every one of them true, the answer as a whole wrong.

    TRUE REGULATORY STATEMENT + WRONG QUESTION = WRONG ANSWER

How it is decided
-----------------
A claim is about whatever the REGULATION it corresponds to is about. That is
the core of the mechanism, and the reason is a measured failure: on acceptance
row D-003 the model wrote "Under Part 211, personnel qualification and training
requirements include written procedures for production and process control,
charge-in of components, calculation of yield ...". Its own words repeat the
question, so any test on the claim's wording calls it relevant. Its CONTENT -
everything after "include" - is production-control text, and the passages it
comes from say nothing about personnel. The evidence cannot be dressed up the
way a sentence can.

So for each claim:

1. **content** - the part of the claim that asserts something. A lead that
   restates the question ("<topic> requirements include ...") is set aside.
2. **corresponding evidence** - the passage the claim was judged against when
   its support verdict was decided; otherwise every passage the content draws
   on (sharing at least `MIN_DRAW` of its content terms).
3. **domain** - a passage from a different Title 21 subchapter than the
   question's product words name is off-topic ("drug manufacturing" answered
   from 21 CFR 111.30, the dietary-supplement section, acceptance row D-008).
   Subchapter A (general provisions) never conflicts.
4. **provision** - when the question names a section and the claim's evidence
   is in a different part, it is off-topic, unless the question is itself a
   cross-reference question.
5. **topic** - the question's subject terms (regulus.accuracy.intent) are looked
   for in the corresponding evidence and its section heading. Half of them,
   rounded up, makes the claim RELEVANT; some makes it PARTIALLY_RELEVANT; none,
   when the evidence is known, makes it IRRELEVANT.

When there is no corresponding evidence at all, the claim's own content is
checked; with no topic term in it the claim is UNDETERMINED, never IRRELEVANT,
because a sentence can refer to its subject without naming it ("It also
requires ...") and the evidence that would settle it is absent.

Why bag-of-words is admissible HERE and nowhere in the correctness path: it was
measured to capture topicality and to be blind to negation, applicability and
attribution (docs/STAGE_A_VALIDATOR_LIMITATION.md). Relevance IS topicality.
Correctness is still decided only by regulus.accuracy.operators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from regulus.accuracy.alignment import Passage
from regulus.accuracy.attribution import MARK_RE
from regulus.retrieval.references import parse_cfr_references
from regulus.accuracy.intent import (
    CROSS_REFERENCE,
    SUBCHAPTER_NAMES,
    QuestionIntent,
    matched,
    part_of,
    required_hits,
    subchapter,
    terms,
)

RELEVANT = "relevant"
PARTIALLY_RELEVANT = "partially_relevant"
IRRELEVANT = "irrelevant"
UNDETERMINED = "undetermined"
VERDICTS = (RELEVANT, PARTIALLY_RELEVANT, IRRELEVANT, UNDETERMINED)

# A passage is one the claim's content draws on when it holds this share of the
# content's terms. Low on purpose: a list claim draws on several passages at
# once, and each holds only part of it.
MIN_DRAW = 0.2
# ... and the content must be found, across those passages, to this extent
# before the passages are taken to say what the claim is about.
MIN_CONTENT_FOUND = 0.5

# A lead that restates the question, then a verb that introduces what the claim
# asserts about it.
_LEAD_SPLIT_RE = re.compile(
    r"\b(?:include|includes|including|are|is|consist\s+of|consists\s+of|comprise|comprises|cover|covers|"
    r"involve|involves|require|requires|mean|means|focus(?:es)?\s+on|are\s+focused\s+on|state|states)\b|:",
    re.I)


@dataclass(frozen=True)
class ClaimRelevance:
    verdict: str
    reason: str
    content: str
    basis: str                                   # "evidence" | "claim_text" | "provision" | "none"
    topic_hits: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()               # citations the decision rested on
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reason": self.reason, "content": self.content[:240],
                "basis": self.basis, "topic_hits": list(self.topic_hits), "evidence": list(self.evidence),
                "checks": dict(self.checks)}


def content_of(claim: str, intent: QuestionIntent) -> tuple[str, str | None]:
    """(what the claim asserts, the lead that restated the question, if any)."""
    text = MARK_RE.sub(" ", claim).strip()
    if not intent.topic:
        return text, None
    m = _LEAD_SPLIT_RE.search(text)
    if not m or m.start() < 3:
        return text, None
    lead, rest = text[: m.start()], text[m.end():]
    if len(terms(rest)) < 2:
        return text, None
    lead_hits = matched(intent.topic, terms(lead))
    if len(lead_hits) >= required_hits(len(intent.topic)) and len(lead_hits) >= len(matched(intent.topic, terms(rest))):
        return rest.strip(" ,;:"), lead.strip()
    return text, None


def _passage_text(p: Passage) -> str:
    return f"{p.heading or ''} {p.text}"


def drawn_from(content: str, passages: Sequence[Passage]) -> tuple[list[Passage], float]:
    """The passages a claim's content draws on, and how much of it they hold."""
    wanted = terms(content)
    if not wanted:
        return [], 0.0
    used: list[Passage] = []
    found: set[str] = set()
    for p in passages:
        hit = matched(wanted, terms(p.text))
        if len(hit) / len(wanted) >= MIN_DRAW:
            used.append(p)
            found |= set(hit)
    return used, len(found) / len(wanted)


def _domain_conflict(intent: QuestionIntent, citations: Sequence[str]) -> str | None:
    if not intent.domains:
        return None
    allowed = set(intent.domains) | {"A"}
    for citation in citations:
        sc = subchapter(part_of(citation))
        if sc and sc not in allowed:
            return (f"{citation} is in subchapter {sc} ({SUBCHAPTER_NAMES[sc]}); the question is about "
                    f"{', '.join(SUBCHAPTER_NAMES[d] for d in sorted(intent.domains))}")
    return None


def guidance_domain_conflict(intent: QuestionIntent, passage: Passage) -> str | None:
    """A guidance passage from a product area the question is not about.

    Guidance carries no CFR part, so `_domain_conflict` never sees it. Its
    product area is read from its own document title with the question's
    product vocabulary (`intent._DOMAIN_WORDS`). Conservative: only when the
    question names a product area AND the title names one AND they share none
    ("general", subchapter A, never conflicts). A guidance whose title names no
    product - most procedural guidance - is never excluded.
    """
    from regulus.accuracy.intent import _DOMAIN_WORDS
    from regulus.accuracy.operators import GUIDANCE

    if getattr(passage, "authority", None) != GUIDANCE or not intent.domains:
        return None
    title = re.sub(r"^\s*FDA\s+Guidance:\s*", "", passage.citation or "", flags=re.I)
    found: set[str] = set()
    for pattern, letters in _DOMAIN_WORDS:
        if pattern.search(title):
            found |= set(letters)
    found -= {"A"}
    if not found or found & (set(intent.domains) | {"A"}):
        return None
    return (f"the guidance is about {', '.join(SUBCHAPTER_NAMES[d] for d in sorted(found))}; the question is about "
            f"{', '.join(SUBCHAPTER_NAMES[d] for d in sorted(intent.domains))}")


def domain_compatible(intent: QuestionIntent, passages: Sequence[Passage]
                      ) -> tuple[list[Passage], list[dict[str, str]]]:
    """The passages that may serve as evidence for this question, and the
    guidance excluded for being about another product area (with why)."""
    kept: list[Passage] = []
    excluded: dict[str, str] = {}
    for p in passages:
        why = guidance_domain_conflict(intent, p)
        if why:
            excluded.setdefault(p.citation, why)
        else:
            kept.append(p)
    return kept, [{"citation": c, "reason": r} for c, r in excluded.items()]


def _provision_conflict(intent: QuestionIntent, citations: Sequence[str], text: str) -> str | None:
    if not intent.parts or intent.kind == CROSS_REFERENCE:
        return None
    parts = [part_of(c) for c in citations if part_of(c)]
    if not parts:
        return None
    if any(p in intent.parts for p in parts):
        return None
    # the regulation itself cross-references a requested part: not a conflict
    if any(re.search(rf"\bpart\s+{re.escape(p)}\b|\b{re.escape(p)}\.\d", text, re.I) for p in intent.parts):
        return None
    return (f"the question asks about part {', '.join(intent.parts)}, and this statement comes from part "
            f"{', '.join(sorted(set(parts)))}")


def _other_section(intent: QuestionIntent, citations: Sequence[str], text: str) -> str | None:
    if not intent.sections or intent.kind == CROSS_REFERENCE:
        return None
    secs = [m.group(1) for m in (re.search(r"\b(\d{1,4}\.\d+[a-z]?)", c or "") for c in citations) if m]
    if not secs or any(s in intent.sections for s in secs):
        return None
    if any(re.search(rf"\b{re.escape(s)}\b", text) for s in intent.sections):
        return None
    return (f"it comes from {', '.join(dict.fromkeys(secs))}, not from {', '.join(intent.sections)}, "
            f"which the question asks about")


def _section_relation(intent: QuestionIntent, citations: Sequence[str]) -> str:
    """For a question that names provisions but no topic: is the evidence that provision?"""
    secs = [re.search(r"\b(\d{1,4}\.\d+[a-z]?)", c or "") for c in citations]
    secs = [m.group(1) for m in secs if m]
    if intent.sections and any(s in intent.sections for s in secs):
        return RELEVANT
    if any(part_of(c) in intent.parts for c in citations):
        return RELEVANT if not intent.sections else PARTIALLY_RELEVANT
    return IRRELEVANT if secs else UNDETERMINED


def assess(claim: str, intent: QuestionIntent, passages: Sequence[Passage], *,
           judged_against: Passage | None = None) -> ClaimRelevance:
    """Relevance of one claim to the question. `judged_against` is the passage the
    claim's support verdict was decided on, when it was decided."""
    content, lead = content_of(claim, intent)
    checks: dict[str, Any] = {"lead_restating_question": lead}

    if judged_against is not None:
        evidence = [judged_against]
        found = 1.0
    else:
        evidence, found = drawn_from(content, passages)
    citations = tuple(dict.fromkeys(p.citation for p in evidence))
    evidence_text = " ".join(_passage_text(p) for p in evidence)
    checks.update({"content_found_in_evidence": round(found, 2), "evidence_passages": len(evidence)})

    # -- domain: a statement attributed to, or drawn from, the wrong body of
    # regulation. A section the claim NAMES is decisive on its own (acceptance
    # row D-008: "... as required by 21 CFR 111.30", the dietary-supplement
    # section, in answer to a drug question). For evidence the claim merely
    # draws on, the passage it matches best decides, not any one of several.
    named = tuple(f"21 CFR {r.section or ('part ' + str(r.part))}"
                  for r in parse_cfr_references(MARK_RE.sub(" ", claim)) if r.part)
    best = (max(evidence, key=lambda p: len(matched(terms(content), terms(p.text)))) if evidence else None)
    decisive = named + ((best.citation,) if best is not None and found >= MIN_CONTENT_FOUND else ())
    conflict = _domain_conflict(intent, decisive)
    checks["domain"] = conflict or "consistent"
    if conflict:
        source = "names" if any(_domain_conflict(intent, (n,)) for n in named) else "corresponds to"
        return ClaimRelevance(IRRELEVANT, f"the statement {source} {conflict}", content, "evidence", (),
                              decisive, checks)

    # -- provision: the question names parts and the statement comes from another
    conflict = _provision_conflict(intent, decisive or citations, evidence_text + " " + content)
    checks["provision"] = conflict or "consistent"
    if conflict and (named or found >= MIN_CONTENT_FOUND):
        return ClaimRelevance(IRRELEVANT, conflict, content, "evidence", (), decisive or citations, checks)

    # -- a question that names a provision but no separate subject
    if not intent.topic:
        verdict = _section_relation(intent, citations) if citations and found >= MIN_CONTENT_FOUND else UNDETERMINED
        reason = {RELEVANT: "comes from the provision the question asks about",
                  PARTIALLY_RELEVANT: "comes from the part the question asks about, not the named section",
                  IRRELEVANT: "comes from a provision the question does not ask about",
                  UNDETERMINED: "no corresponding evidence, and the question names no subject to check against"}[verdict]
        return ClaimRelevance(verdict, reason, content, "provision" if citations else "none", (), citations, checks)

    need = required_hits(len(intent.topic))
    if evidence and found >= MIN_CONTENT_FOUND:
        hits = matched(intent.topic, terms(evidence_text))
        verdict = RELEVANT if len(hits) >= need else PARTIALLY_RELEVANT if hits else IRRELEVANT
        what = ", ".join(citations[:3]) + (" ..." if len(citations) > 3 else "")
        reason = (f"the regulation it corresponds to ({what}) is about {'/'.join(hits)}" if hits else
                  f"the regulation it corresponds to ({what}) says nothing about "
                  f"{'/'.join(intent.topic)}, which is what the question asks about")
        # a question that names a section asks about THAT section: a statement
        # from another section that does not refer to it shares the subject at
        # best, and shared generic words ("control") must not make it the answer
        other = _other_section(intent, decisive or citations, evidence_text + " " + content)
        checks["section"] = other or "consistent"
        if other and verdict == RELEVANT:
            verdict, reason = PARTIALLY_RELEVANT, other
        if lead and verdict == IRRELEVANT:
            reason = (f"it presents {what} content as the answer to '{lead}', but that regulation is about something "
                      f"else")
        return ClaimRelevance(verdict, reason, content, "evidence", hits, citations, checks)

    hits = matched(intent.topic, terms(content))
    verdict = RELEVANT if len(hits) >= need else PARTIALLY_RELEVANT if hits else UNDETERMINED
    reason = (f"no corresponding evidence; the statement itself is about {'/'.join(hits)}" if hits else
              "no corresponding evidence, and the statement names nothing the question asks about")
    return ClaimRelevance(verdict, reason, content, "claim_text", hits, citations, checks)


def on_topic(intent: QuestionIntent, passages: Sequence[Passage]) -> list[tuple[Passage, tuple[str, ...]]]:
    """Passages whose text or heading is about the question's subject.

    Used to judge a refusal: if the retrieved evidence contains passages about
    what was asked, the evidence to answer from was there.
    """
    if not intent.topic:
        return []
    need = max(required_hits(len(intent.topic)), min(2, len(intent.topic)))
    out = []
    for p in passages:
        hits = matched(intent.topic, terms(_passage_text(p)))
        if len(hits) >= need and _domain_conflict(intent, (p.citation,)) is None:
            out.append((p, hits))
    return out
