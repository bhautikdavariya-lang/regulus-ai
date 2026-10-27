"""Required warning statements answered verbatim (WC1, 27 Oct 2026).

Part 740 prescribes label warnings word for word ("Warning—Avoid spraying in eyes. Contents under pressure. ...",
740.11(a)(1)). A compliance answer never paraphrases one: a paraphrased warning is a non-compliant warning, and the
keys of such questions name the statement and the section's permitted variations and exemptions. A question asking
what the warning or the label must say, about one Part 740 section that prescribes a statement, is answered with a
direct line naming the paragraph that holds it and every paragraph of the section, verbatim and cited, in order. A
question whether the statement is needed ("Do we need the warning?", "are we exempt?") is left to the model.
"""
from __future__ import annotations

import re

_SECTION_LABEL = re.compile(r"^21 CFR (740\.\d+)$")
_STATEMENT = re.compile(r"\b(?:Warning|Caution)\s*[—–-]\s*[A-Z]")
_ASKS_WORDING = re.compile(
    r"\bwhat\s+(?:warning|caution|statement)s?\b|\bwhat\s+must\s+(?:the|our|its|their|a)\s+(?:label|labeling|can|container|"
    r"package|carton|bottle)\s+(?:say|carry|bear|include|state|show)\b|\b(?:exact|required)\s+wording\b|"
    r"\bwhat\s+(?:does|must)\s+the\s+(?:warning|caution|statement)\s+say\b", re.I)
_ASKS_WHETHER = re.compile(r"\b(?:do|does|must)\s+(?:we|it|they|our\s+\w+)\s+(?:need|have\s+to)\b|\bexempt|\bexception", re.I)
LEAD = "The label must bear the statement in {cite} [{n}], verbatim; the section's paragraphs, verbatim:"


def compose(package, question: str) -> str | None:
    from regulus.rag.generation import _verbatim, whole_sentences

    if not _ASKS_WORDING.search(question or "") or _ASKS_WHETHER.search(question or ""):
        return None
    labels = [m.group(1) for _, label in package.requirements if (m := _SECTION_LABEL.match(label))]
    if len(labels) != 1:
        return None
    own = [s for s in package.sources if re.match(rf"^21 CFR {re.escape(labels[0])}(?:\(|$)", s.citation or "")]
    statement = next((s for s in own if _STATEMENT.search(s.text or "")), None)
    if statement is None:
        return None
    lines, seen = [LEAD.format(cite=statement.citation, n=statement.index)], set()
    for s in own:
        body = whole_sentences(s.text or "")
        if not body or (s.citation, body) in seen:
            continue
        seen.add((s.citation, body))
        lines.append(f"{s.citation} (eCFR, binding, verbatim): {_verbatim(body, s.index)}")
    return "\n".join(lines) if len(lines) > 1 else None
