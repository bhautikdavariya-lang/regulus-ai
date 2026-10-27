"""Questions about what something must contain, answered with the regulation's whole list (LS1, 27 Oct 2026).

"What must our certification request contain?" is answered by 21 CFR 80.21: "A request for certification of a batch of
color additive shall:" followed by (a)-(i). The model summarises such a list and drops items (the request's fee, its
sample, the signer), or names only its headings; the keys name every item. Extractive answering of list questions is
how structured legal search handles them: the lead-in paragraph that introduces the list ("shall include the
following:", "shall be labeled to show:") is chosen by the words it shares with the question, and it is quoted with
every paragraph under it, verbatim and cited, in order. A question whether something is needed, or about an
exemption, is left to the model; so is any package without exactly one requested 21 CFR section.
"""
from __future__ import annotations

import re

_ASKS_CONTENTS = re.compile(
    r"\bwhat\s+(?:must|should|does|do|shall|has\s+to|have\s+to)\b[^?]{0,80}?\b(?:include|contain|state|show|list|record|"
    r"say|cover|bear|carry|consist\s+of)\b|\bwhat\s+(?:must|should|shall|has\s+to|have\s+to)\s+be\s+(?:included|contained|"
    r"stated|shown|listed|recorded|documented)\b|\bwhat\s+(?:information|data|items|details|elements|contents?)\b|"
    r"\bwhat\s+(?:goes|has\s+to\s+go|must\s+go)\s+(?:in|into|on)\b|\bminimum\s+(?:data|information|contents?)\b", re.I)
_ASKS_WHETHER = re.compile(r"\b(?:do|does|must)\s+(?:we|it|they|our\s+\w+)\s+(?:need|have\s+to)\b|\bexempt|\bexception|"
                           r"\bwhether\b", re.I)
_LEAD_IN = re.compile(r":\s*$")
# LS2 (27 Oct): "What does 21 CFR 820.10 require (of a manufacturer)?" about a section whose own lead-in introduces its
# list ("A manufacturer subject to this part ... must:" then (a)-(e)) - the key walks the list; the model summarised it
# into one sentence no single paragraph supports and was withheld (device baseline M-012)
_ASKS_SECTION_REQUIRES = re.compile(r"\bwhat\s+(?:does|do)\s+(?:21\s+CFR\s+)?(?:§\s*)?\d+\.\d+[a-z]?\s+require\b|"
                                    # "What charge-in of components controls does Part 211 require?" (D-012): one
                                    # promoted section whose own lead-in introduces the list
                                    r"\bwhat\b[^?]{0,80}?\b(?:does|do)\s+(?:21\s+CFR\s+)?part\s+\d+\s+require\b", re.I)
_SECTION = re.compile(r"^21 CFR (\d+\.\d+[a-z]?)(\S*)$")
_STOP = set("""a an the of and or to in on for by with any be is are as such that this shall will may which under its from at
not other all must should what our we your their each following include includes contain contains state show list
record records name names""".split())
LEAD = "Under {section}, the regulation's list, verbatim:"


def _words(text: str) -> set[str]:
    return {re.sub(r"(?:es|s)$", "", w) for w in re.findall(r"[a-z]{4,}", (text or "").lower())} - _STOP


_ASK_SPLIT = re.compile(r",?\s+and\s+(?=(?:what|how|who|when|where|which|whether|does|do|is|are|must|can|may)\b)", re.I)


def _asks_covered(question: str, list_text: str) -> bool:
    """Every part of a question of several parts names something the list's text names: "What must the request include,
    and how is it submitted?" is answered by 80.21's list ("Be submitted in duplicate"); "What controls ... prevent
    mixups, and what must be documented?" is not answered by 820.45(a)'s examination items (M-028, PASS lost)."""
    from regulus.rag.section_promotion import _topic_stems, multi_part

    if not multi_part(question):
        return True
    parts = _ASK_SPLIT.split(re.split(r"(?<=[.!?])\s+", (question or "").strip())[-1])
    have = _topic_stems(list_text)
    return all(not _topic_stems(p) or _topic_stems(p) & have for p in parts)


def compose(package, question: str) -> str | None:
    from regulus.rag.generation import _verbatim, whole_sentences

    from regulus.rag.validator_switches import enabled

    whole_section = enabled("LS2") and bool(_ASKS_SECTION_REQUIRES.search(question or ""))
    if not (_ASKS_CONTENTS.search(question or "") or whole_section) or _ASKS_WHETHER.search(question or ""):
        return None
    sections = [m.group(1) for _, label in package.requirements if (m := _SECTION.match(label)) and not m.group(2)]
    if len(sections) != 1:
        return None
    sec = sections[0]
    own = [s for s in package.sources if re.match(rf"^21 CFR {re.escape(sec)}(?:\(|$)", s.citation or "")]
    leads = [s for s in own if _LEAD_IN.search((s.text or "").strip())]
    if whole_section and not _ASKS_CONTENTS.search(question or ""):
        leads = [s for s in leads if s.citation == f"21 CFR {sec}"]   # LS2: only the section's own lead-in
        if not re.search(r"\d+\.\d+", question or ""):
            # "what ... does Part 211 require": only when the question names this section's heading as its subject
            from regulus.rag.section_promotion import heading_phrase_in

            leads = [s for s in leads if heading_phrase_in(getattr(s, "heading", "") or "", question)]
    if not leads:
        return None
    q = _words(question)

    def children(lead):
        base = lead.citation
        prefix = base + "(" if base.endswith(sec) else base
        return [s for s in own if s is not lead and (s.citation or "").startswith(prefix) and s.citation != base]

    def score(lead):
        kids = children(lead)
        return (len(q & _words(lead.text)) * 2 + len(q & set().union(*(_words(k.text) for k in kids)) if kids else 0), len(kids))

    best = max(leads, key=score)
    kids = children(best)
    if len(kids) < 2 or score(best)[0] < 2:
        return None   # not a list, or not the list the question is about
    if not _asks_covered(question, " ".join((s.text or "") for s in [best] + kids)):
        return None   # a question of several parts that the list does not answer whole (M-028: mixups, documentation)
    lines, seen = [LEAD.format(section=f"21 CFR {sec}")], set()
    for s in [best] + kids:
        body = whole_sentences(s.text or "")
        if not body or (s.citation, body) in seen:
            continue
        seen.add((s.citation, body))
        lines.append(f"{s.citation} (eCFR, binding, verbatim): {_verbatim(body, s.index)}")
    return "\n".join(lines) if len(lines) > 2 else None


# WS1 (27 Oct): an overview question whose subject is the promoted section's own heading - "What are the reserve sample
# requirements under Part 211?" (211.170, Reserve samples), "What is required by the stability testing regulation?"
# (211.166) - answered with the whole section, verbatim and cited, when it is short enough to give complete. Extractive
# answering, as legal research tools give a provision's text for "what does X require": the model's paraphrases dropped
# clauses (211.170's twice-quantity, storage and annual examination) or misread scope (211.166(c), homeopathic only).
WS1_MAX_CHARS = 3600
WS1_LEAD = "Under {section}, the regulation's text in full ({heading}), verbatim:"
_OVERVIEW = re.compile(r"^\s*what\s+(?:are|is)\s+(?:the\s+)?[^?]{0,60}\brequire(?:ments?|d)\b|^\s*what\s+is\s+required\s+by\b|"
                       r"^\s*what\s+requirements\s+apply\b|^\s*what\s+[^?]{0,40}\brequirements\s+apply\b", re.I)
_SPECIFIC = re.compile(r"\b(?:whether|do we|must we|can we|may we|how many|how long|how much|which)\b", re.I)


def compose_section(package, question: str) -> str | None:
    from regulus.rag.generation import _verbatim, whole_sentences
    from regulus.rag.section_promotion import _GENERIC_HEADING, heading_phrase_in

    if not _OVERVIEW.search(question or "") or _SPECIFIC.search(question or ""):
        return None
    sections = [m.group(1) for _, label in package.requirements if (m := _SECTION.match(label)) and not m.group(2)]
    if len(sections) != 1:
        return None
    sec = sections[0]
    own = [s for s in package.sources if re.match(rf"^21 CFR {re.escape(sec)}(?:\(|$)", s.citation or "")]
    heading = next((getattr(s, "heading", "") for s in own if getattr(s, "heading", "")), "")
    if not own or not heading or _GENERIC_HEADING.match(heading) or not heading_phrase_in(heading, question):
        return None
    if sum(len(s.text or "") for s in own) > WS1_MAX_CHARS or any(getattr(s, "truncated", False) for s in own):
        return None
    lines, seen = [WS1_LEAD.format(section=f"21 CFR {sec}", heading=heading.rstrip("."))], set()
    for s in sorted(own, key=lambda x: x.index):
        body = whole_sentences(s.text or "")
        if body and (s.citation, body) not in seen:
            seen.add((s.citation, body))
            lines.append(f"{s.citation} (eCFR, binding, verbatim): {_verbatim(body, s.index)}")
    return "\n".join(lines) if len(lines) > 1 else None
