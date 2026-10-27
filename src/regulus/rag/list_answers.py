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
    r"say|cover|bear|carry|consist\s+of)\b|\bwhat\s+(?:information|data|items|details|elements|contents?)\b|"
    r"\bwhat\s+(?:goes|has\s+to\s+go|must\s+go)\s+(?:in|into|on)\b|\bminimum\s+(?:data|information|contents?)\b", re.I)
_ASKS_WHETHER = re.compile(r"\b(?:do|does|must)\s+(?:we|it|they|our\s+\w+)\s+(?:need|have\s+to)\b|\bexempt|\bexception|"
                           r"\bwhether\b", re.I)
_LEAD_IN = re.compile(r":\s*$")
_SECTION = re.compile(r"^21 CFR (\d+\.\d+[a-z]?)(\S*)$")
_STOP = set("""a an the of and or to in on for by with any be is are as such that this shall will may which under its from at
not other all must should what our we your their each following include includes contain contains state show list
record records name names""".split())
LEAD = "Under {section}, the regulation's list, verbatim:"


def _words(text: str) -> set[str]:
    return {re.sub(r"(?:es|s)$", "", w) for w in re.findall(r"[a-z]{4,}", (text or "").lower())} - _STOP


def compose(package, question: str) -> str | None:
    from regulus.rag.generation import _verbatim, whole_sentences

    if not _ASKS_CONTENTS.search(question or "") or _ASKS_WHETHER.search(question or ""):
        return None
    sections = [m.group(1) for _, label in package.requirements if (m := _SECTION.match(label)) and not m.group(2)]
    if len(sections) != 1:
        return None
    sec = sections[0]
    own = [s for s in package.sources if re.match(rf"^21 CFR {re.escape(sec)}(?:\(|$)", s.citation or "")]
    leads = [s for s in own if _LEAD_IN.search((s.text or "").strip())]
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
    lines, seen = [LEAD.format(section=f"21 CFR {sec}")], set()
    for s in [best] + kids:
        body = whole_sentences(s.text or "")
        if not body or (s.citation, body) in seen:
            continue
        seen.add((s.citation, body))
        lines.append(f"{s.citation} (eCFR, binding, verbatim): {_verbatim(body, s.index)}")
    return "\n".join(lines) if len(lines) > 2 else None
