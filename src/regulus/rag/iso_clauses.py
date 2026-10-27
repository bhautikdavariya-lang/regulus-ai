"""ISO 13485 clauses of the cited Part 820 provisions, named in the answer (ISO1, 27 Oct 2026).

The Quality Management System Regulation (21 CFR part 820, in force 2 February 2026) incorporates ISO 13485:2016 and
names, in its own text, the clause each provision supplements: "In addition to Clause 8.2.2 in ISO 13485, Complaint
Handling, ..." (820.35(a)); "For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, ..." (820.10(b)(3)).
The client's benchmark scores whether an answer names that clause and routes it through the right section; the model
mostly drops it. Every clause a cited Part 820 paragraph - or the lead-in of its section - names, and the answer does
not, is added on one line with that paragraph's citation, so each clause stated is in a cited source. A paragraph that
names no clause adds nothing: the mapping is never guessed.
"""
from __future__ import annotations

import re

_NUM = r"\d+(?:\.\d+)*"
_CLAUSES = re.compile(rf"\bClauses?\s+(?P<nums>{_NUM}(?:\s*,\s*(?:and\s+)?{_NUM}|\s+and\s+{_NUM})*)"
                      rf"(?:\s+(?:in|of)\s+ISO\s+13485)?(?:,\s*(?P<title>[A-Z][A-Za-z ,—-]{{2,60}}?)(?=,|\s+the\b|\s*\(|$))?")
LEAD = "ISO 13485:2016 clauses these provisions supplement, as the regulation names them:"


def clauses_in(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if "ISO 9000" in (text or "") and "13485" not in (text or ""):
        return out   # 820.7(a): ISO 9000's clause 3 (vocabulary), not a clause of ISO 13485
    for m in _CLAUSES.finditer(text or ""):
        if "ISO 9000" in (text or "")[max(0, m.start() - 40):m.end() + 20] and "13485" not in (text or "")[m.start():m.end() + 20]:
            continue   # ISO 9000 clause 3 (vocabulary), not an ISO 13485 clause
        title = (m.group("title") or "").strip(" ,")
        for n in re.findall(_NUM, m.group("nums")):
            out.append((n, title if len(re.findall(_NUM, m.group("nums"))) == 1 else ""))
    return out


def clause_line(answer: str, sources) -> str | None:
    """The line naming the ISO 13485 clauses of the cited Part 820 sources that the answer does not name, or None."""
    by_index = {s.index: s for s in sources}
    cited = sorted({int(m) for m in re.findall(r"\[(\d{1,3})\]", answer or "")} & set(by_index))
    lead_ins = {}
    for s in sources:   # a section's unnumbered lead-in ("In addition to the requirements of Clause 4.2.5 ...")
        m = re.match(r"^21 CFR (820\.\d+)$", s.citation or "")
        if m:
            lead_ins[m.group(1)] = s
    items: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    for i in cited:
        s = by_index[i]
        m = re.match(r"^21 CFR (820\.\d+)", s.citation or "")
        if not m:
            continue
        found = [(n, t, s.citation, s.index) for n, t in clauses_in(s.text)]
        lead = lead_ins.get(m.group(1))
        if lead is not None and lead.index != s.index:
            found += [(n, t, lead.citation, lead.index) for n, t in clauses_in(lead.text)]
        for n, t, cite, idx in found:
            if n in seen or re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", answer or ""):
                continue
            seen.add(n)
            items.append((n, t, cite, idx))
    if not items:
        return None
    parts = [f"Clause {n}{(' ' + t) if t else ''} ({cite}) [{idx}]" for n, t, cite, idx in items]
    return f"{LEAD} " + "; ".join(parts) + "."
