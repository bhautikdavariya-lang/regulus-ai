"""How a delivered answer is laid out on the page: a direct answer first, then what the regulation says, then notes
and limits, then the sources - the shape a reader expects from a professional regulatory assistant.

Why (26 Oct 2026): the delivered text is one block. A generated answer states its conclusion, then restates every
provision it relied on, often twice (the answer-first format asks for the conclusion and the provision wording); a
status note, an evidence limit or a "not found" statement sits in the middle of it; a withheld answer is a paragraph
of process language. All of it is correct, and none of it reads like an answer.

How: the delivered text is split, never rewritten. Each paragraph or line goes to exactly one place:
  * notes   - status notes (regulus.rag.status_notes), evidence limits, "not found" and "the sources do not provide"
              statements, the gap notice;
  * points  - a line or paragraph that restates one provision ("21 CFR 70.20 requires ...", "(b) ...", "FD&C Act §
              602(c) requires ..."), labelled with that provision;
  * lead    - everything else, in order: the direct answer.
Nothing is left out: removing repeated restatements was tried on 163 recorded answers and fired twice, once dropping a
list's lead-in ("A treatment IDE is required when:") - not worth the risk of losing a sentence.
A withheld or declined answer gets a short plain explanation and its consulted sources as a list (the delivered text
is kept beside it). The answer text itself - what is copied, stored, evaluated and scored - is never changed: this
is display only (result["presentation"], scripts/serve_ui.py).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# fallback types (regulus.rag.pipeline) and how they read
_WITHHELD = {"unvalidated_answer_withheld"}
_DECLINED = {"out_of_scope", "no_context", "refused", "general_knowledge", "ambiguous", "insufficient_evidence",
             "premise_not_established", "value_not_established", "requested_provision_not_found"}

_NOTE_LEADS = re.compile(
    r"^(?:Status note\b|Evidence limit:|Not found in the available eCFR data:|Note:|Gap notice:|"
    r"The available regulatory sources do not provide|The available eCFR data does not contain|"
    r"The retrieved evidence does not establish|The answer above covers only|"
    r"This answer (?:is|does) not|This is the provision.s own text, not an application|No (?:legal|binding) (?:opinion|advice)\b|(?:\[\d{1,3}\]\s*)?\(Note:)", re.I)
# the consulted list is one line: "Sources consulted: A, B and 3 more." (regulus.rag.fallback)
_SOURCES_CONSULTED = re.compile(r"\bSources consulted:\s*([^\n]+?)\.?[ \t]*(?:\n|$)")
# a restatement of one provision: "21 CFR 70.20 requires", "21 CFR 70.3(j) [2] defines", "(a) If a substance ...",
# "FD&C Act § 602(c) requires", "21 U.S.C. 364c(a)(4): ..."
_POINT = re.compile(
    r"^(?:(?P<cfr>21\s+CFR\s+(?:§\s*)?\d{1,4}\.\d{1,4}[a-z]?(?:\([a-zA-Z0-9]{1,6}\))*)"
    r"|(?P<act>(?:The\s+)?FD&C\s+Act\s+§\s*\d{3}[a-z]?(?:\([a-zA-Z0-9]{1,6}\))*)"
    r"|(?P<usc>21\s+U\.S\.C\.\s*\d{3}[a-z]*(?:\([a-zA-Z0-9]{1,6}\))*)"
    r"|(?P<sign>§\s*\d{1,4}\.\d{1,4}[a-z]?(?:\([a-zA-Z0-9]{1,6}\))*)"
    r"|(?P<para>\([a-z0-9]{1,4}\)(?:\([a-z0-9ivx]{1,6}\))*)\s)", re.I)
_VERDICT = re.compile(r"^(?P<v>Yes|No)\b[,.:;—-]", re.I)
_COMPOSED_VERDICT = re.compile(r"^(?P<what>[^.:\n]{2,60}):\s*(?P<v>permitted|not permitted|prohibited|allowed|"
                               r"not allowed|required|not required|exempt|not exempt)\.?\s*$", re.I)
_MARK = re.compile(r"\[(\d{1,3})\]")


@dataclass
class Point:
    label: str                 # "21 CFR 70.20", "FD&C Act § 602(c)", "(b)" (a paragraph of the provision above)
    text: str                  # the line as delivered, markers included
    cites: list[int] = field(default_factory=list)


@dataclass
class Presentation:
    kind: str                              # "answer" | "composed" | "withheld" | "declined"
    verdict: str | None = None             # "Yes", "No", "Permitted", ...
    verdict_subject: str | None = None     # composed: "Eye shadow"
    lead: list[str] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    consulted: list[str] = field(default_factory=list)   # withheld / declined: the sources consulted, by label
    summary: str | None = None             # withheld / declined: the plain explanation shown instead of process text
    detail: list[str] = field(default_factory=list)   # withheld / declined: the delivered text, kept behind "details"
    sources: list[dict[str, Any]] = field(default_factory=list)   # [{index, label, url}] cited by the answer
    context: dict[str, Any] | None = None  # follow-up: {earlier_question, provisions}
    suggestions: list[str] = field(default_factory=list)  # follow-up questions offered under the answer

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cites(text: str) -> list[int]:
    return sorted({int(m) for m in _MARK.findall(text)})


def _point_label(line: str) -> str | None:
    m = _POINT.match(line)
    if m is None:
        return None
    for g in ("cfr", "act", "usc", "sign", "para"):
        if m.group(g):
            return re.sub(r"\s+", " ", m.group(g)).replace("The FD&C", "FD&C").strip()
    return None


def _blocks(text: str) -> list[str]:
    """Each line: the pipeline writes a paragraph as one line, and a line break inside a paragraph starts a statement
    of its own (a provision restatement, a note, a composed answer's "Use limit: ..."); a line that starts in lower
    case continues the one before."""
    out: list[str] = []
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if out and line[0].islower():
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def _split_note_sentences(block: str) -> tuple[str, list[str]]:
    """A lead paragraph may end with a note sentence ("... The available regulatory sources do not provide ..."):
    the note sentences go to the notes, the rest stays."""
    sents = re.split(r"(?<=[.;])\s+(?=[A-Z])", block)
    keep = [s for s in sents if not _NOTE_LEADS.match(s)]
    notes = [s for s in sents if _NOTE_LEADS.match(s)]
    return " ".join(keep).strip(), notes


# suggested follow-ups (26 Oct 2026): offered under an answer, from the provision it was answered from, in forms the
# conversation resolves to that provision (regulus.rag.conversation) and that the pipeline answers deterministically
# where it can (records: RS1; eye-area use of a listed color: the listing composer). Never for a declined answer.
_LISTING_PART = re.compile(r"^(?:73|74|82)\.")
MAX_SUGGESTIONS = 3


def suggestions_for(anchor: dict | None, asked: str | None = None) -> list[str]:
    """Up to MAX_SUGGESTIONS follow-up questions about the provision a turn was resolved to."""
    a = anchor if isinstance(anchor, dict) else {}
    cfr = [x for x in a.get("cfr") or [] if isinstance(x, str)]
    act = [x for x in a.get("statute") or [] if isinstance(x, str)]
    out: list[str] = []
    if cfr and _LISTING_PART.match(cfr[0]):
        out = ["Can this color be used in eye-area products such as eye shadow?",
               "Does each batch of this color need FDA certification?",
               f"What records does 21 CFR {cfr[0]} require?"]
    elif cfr:
        out = [f"What records does 21 CFR {cfr[0]} require?", f"Are there exceptions or exemptions in 21 CFR {cfr[0]}?",
               f"Who does 21 CFR {cfr[0]} apply to?"]
    elif act:
        out = [f"What records does FD&C Act § {act[0]} require?", f"Are there exemptions under FD&C Act § {act[0]}?",
               f"Who does FD&C Act § {act[0]} apply to?"]
    seen = re.sub(r"\W+", " ", (asked or "").lower()).strip()
    return [q for q in out if re.sub(r"\W+", " ", q.lower()).strip() != seen][:MAX_SUGGESTIONS]


def present(answer: str, *, fallback_type: str | None = None, citations: list[dict] | None = None,
            followup: dict | None = None, asked: str | None = None) -> Presentation:
    """The page layout of a delivered answer (see the module docstring). `citations`: the result's citations
    ([{index, label, url, cited_in_answer}]); `followup`: the result's "followup" (regulus.rag.conversation)."""
    text = (answer or "").strip()
    cited = [c for c in (citations or []) if isinstance(c, dict)]
    sources = [{"index": c.get("index"), "label": c.get("label"), "url": c.get("url")}
               for c in cited if c.get("cited_in_answer", True)]
    context = None
    fu = (followup or {}).get("followup") if isinstance(followup, dict) else None
    if isinstance(fu, dict) and fu.get("anchored"):
        anchor = fu.get("anchor") or {}
        context = {"earlier_question": fu.get("earlier_question"),
                   "provisions": [f"21 CFR {s}" for s in anchor.get("cfr") or []]
                                 + [f"FD&C Act § {s}" for s in anchor.get("statute") or []]}
    if fallback_type in _WITHHELD or fallback_type in _DECLINED:
        return _not_answered(text, fallback_type, sources, context)
    offered = suggestions_for((followup or {}).get("anchor") if isinstance(followup, dict) else None, asked)
    kind = "composed" if (fallback_type or "").startswith("composed") else "answer"
    p = Presentation(kind=kind, sources=sources, context=context, suggestions=offered)
    for block in _blocks(text):
        if _NOTE_LEADS.match(block):
            p.notes.append(block)
            continue
        label = _point_label(block)
        if label is not None and (p.lead or p.points or p.notes):
            # a provision restatement after the answer: the first statement is the answer even when it opens with a
            # citation ("21 CFR 701.11 sets no recordkeeping requirement: ...", "21 CFR 70.20 requires ...")
            p.points.append(Point(label, block, _cites(block)))
            continue
        lead, notes = _split_note_sentences(block)
        p.notes.extend(notes)
        if lead:
            p.lead.append(lead)
    if not p.lead and p.notes and p.notes[0].startswith(("The available regulatory sources", "The available eCFR data")):
        p.lead.append(p.notes.pop(0))   # the answer is that the sources do not say: it is the answer, not a note
    if p.lead:
        first = p.lead[0]
        m = _COMPOSED_VERDICT.match(first)
        if m:
            p.verdict, p.verdict_subject = m.group("v").capitalize(), m.group("what").strip()
            p.lead = p.lead[1:]
        else:
            m = _VERDICT.match(first)
            if m:
                p.verdict = m.group("v").capitalize()
    return p


_SUMMARY = {
    "unvalidated_answer_withheld": ("An answer was drafted but could not be verified sentence by sentence against the "
                                    "regulation text, so it is not shown. The provisions consulted are listed below."),
    "out_of_scope": "This question is outside what Regulus answers: U.S. FDA regulations (21 CFR) and the FD&C Act.",
    "value_not_established": ("The regulation text retrieved does not state the figure asked for, so none is given."),
    "premise_not_established": ("The question assumes something the regulation text does not state, so it is not "
                                "confirmed."),
}


def _not_answered(text: str, fallback_type: str, sources: list[dict], context) -> Presentation:
    p = Presentation(kind="withheld" if fallback_type in _WITHHELD else "declined", sources=sources, context=context)
    body = text
    m = _SOURCES_CONSULTED.search(body)
    if m:
        p.consulted = [s.strip() for s in re.split(r",\s*(?![^\[]*\])|\s+and\s+(?=\d+\s+more)", m.group(1)) if s.strip()]
        body = (body[:m.start()] + "\n\n" + body[m.end():]).strip()
    for block in _blocks(body):
        (p.notes if _NOTE_LEADS.match(block) and not block.startswith("The available regulatory sources") else p.detail).append(block)
    p.summary = _SUMMARY.get(fallback_type)
    if p.summary is None and p.detail:
        p.summary, p.detail = p.detail[0], p.detail[1:]
    return p
