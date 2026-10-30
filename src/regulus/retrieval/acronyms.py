"""The acronyms 21 CFR defines in its own text (switch SY4, 30 Oct 2026).

A question writing "RACC" shares no word with 101.12 ("Reference amounts customarily consumed per eating occasion"), so
the section was never a candidate (L-008, full300d: 101.12 missing, PARTIALLY PASS). data/reference/acronyms_v1.json
(scripts/build_acronyms.py) holds every acronym the regulations spell out before it in parentheses ("reference amount
commonly consumed (RACC)"), with the senses questions do not use excluded (PDP is a product development protocol in
the corpus and a principal display panel on a label). The expansion is added to the search words only: the picker and
the model read the question as asked.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[3] / "data" / "reference" / "acronyms_v1.json"
_ACRONYM = re.compile(r"(?<![\w&])([A-Z][A-Z&]{2,7})s?(?![\w&])")


@lru_cache(maxsize=1)
def table() -> dict[str, str]:
    try:
        return {k: v["expansion"] for k, v in json.loads(PATH.read_text(encoding="utf-8"))["acronyms"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def expansions(question: str) -> list[str]:
    """The expansions of the defined acronyms the question writes in capitals and does not already spell out."""
    known, q = table(), (question or "").lower()
    out = []
    for acronym in dict.fromkeys(_ACRONYM.findall(question or "")):
        words = known.get(acronym)
        if words and words not in q and words not in out:
            out.append(words)
    return out
