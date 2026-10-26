"""A question about the records a provision requires, when it requires none (fix RS1, 26 Oct 2026).

"What records does § 701.11 require?", "An investigator asks what this section requires us to keep for D&C Orange No.
4", "What evidence shows compliance with § 700.35?" - 95 of the question bank's 220 records follow-ups have keys that
begin "<section> sets no recordkeeping requirement", then state what the section does require. Asked such a question,
Qwen3-4B described the section's requirements and never said it prescribes no records (701.11-Q1-F5, partly failed), or
named records it invented.

The silence is a search, never an assumption: the FULL text of every identified 21 CFR section (from the database, not
only the paragraphs supplied to the model) is searched for record-keeping language. Only when none of them has any is the
answer composed: "<section> sets no recordkeeping requirement: no paragraph of its text in this system requires a record
to be made or kept. What it does require, verbatim:" and the section's paragraphs that share most subject words with the
question, cited. A section that speaks of records, files, logs, retention or documentation is left to the model.
Switched by "RS1" in regulus.rag.validator_switches.
"""
from __future__ import annotations

import re

# the question asks what to record, keep or show
_ASKS_RECORDS = re.compile(r"\b(?:records?|record-?keeping|documentation|document(?:ed)?|on\s+file|keep|kept|retain\w*|"
                           r"logs?|evidence|proof|prove|paperwork|receiving\s+file)\b", re.I)
# record-keeping language in a provision: any of these ends the silence
RECORD_LANGUAGE = re.compile(r"\brecords?\b|\brecord-?keeping\b|\bretain\w*|\bretention\b|\bmaintain\w*\b|\bkeep\b|\bkept\b|"
                             r"\blogs?\b|\bdocumentation\b|\bdocument(?:ed|s)?\b|\bfiles?\b|\bfiled\b|\bwritten\s+procedures?\b|"
                             r"\bcertificates?\b|\breports?\b", re.I)
# the answer's first sentence: what the search found (written by the pipeline, not a claim taken from the evidence)
SILENCE_SENTENCE_RE = re.compile(r"[^\n]*? sets? no recordkeeping requirement: no paragraph of [^\n]*? in this system "
                                 r"requires a record to be made or kept\.")


def asks_records(question: str) -> bool:
    return bool(_ASKS_RECORDS.search(question or ""))


def silent(section_texts: dict[str, str]) -> bool:
    """Every identified section's full text is free of record-keeping language (and there is some text)."""
    return bool(section_texts) and all(t and not RECORD_LANGUAGE.search(t) for t in section_texts.values())


def compose(package, question: str, section_texts: dict[str, str], *, limit: int = 3) -> str | None:
    """`section_texts`: {"21 CFR 701.11": its full text, ...} for the identified sections. None unless the question asks
    about records and every section is silent on them."""
    from regulus.rag.conversation import subject_words
    from regulus.rag.generation import _verbatim, whole_sentences
    from regulus.retrieval.evidence import TIER_EXACT

    if package is None or not asks_records(question) or not silent(section_texts):
        return None
    asked = subject_words(question)
    scored = []
    for s in package.sources:
        if s.tier != TIER_EXACT or not s.requirement_ids or s.is_docket:
            continue
        body = whole_sentences(s.text or "")
        if body:
            scored.append((-len(asked & subject_words(body)), s.index, s, body))
    if not scored:
        return None
    kept = sorted(scored, key=lambda x: x[:2])[:limit]
    names = list(section_texts)
    subject = " and ".join(names[:2]) + (" and the other provisions" if len(names) > 2 else "")
    verb = "set" if len(names) > 1 else "sets"
    lines = [f"{subject} {verb} no recordkeeping requirement: no paragraph of {'their' if len(names) > 1 else 'its'} "
             f"text in this system requires a record to be made or kept. What {'they require' if len(names) > 1 else 'it requires'}, verbatim:"]
    for _, _, s, body in sorted(kept, key=lambda x: x[1]):
        lines.append(f"{s.citation} (eCFR, binding, verbatim): {_verbatim(body, s.index)}")
    return "\n".join(lines)
