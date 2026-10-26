"""How common each word is in Title 21, for the yes/no premise check (fix PR2, 26 Oct 2026).

The premise check (regulus.rag.claim_validation) withholds a yes/no answer that repeats a question word no supplied
source contains, as affirming a premise the provision does not state. Measured on recorded follow-ups, it fired on
ordinary words - "instead" (hand-deliver instead of mailing), "outer" (the outer carton), "appear", "without", "show",
"serve" - and replaced three correct yes/no answers with "the retrieved text does not state ...". A premise the
regulation does not establish is a term foreign to it ("Green Facility program", "biannual", "conceal"); a word used
in 40 or more of Title 21's 7,829 sections is ordinary regulatory English and does not make a premise by itself.

The counts (sections using each word, after claim_validation's own tokenisation) are built from the database into
data/reference/title21_word_sections.json:  python -m regulus.rag.premise_vocabulary
Switched by "PR2" in regulus.rag.validator_switches.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[3] / "data" / "reference" / "title21_word_sections.json"
# a word in at least this many sections of Title 21 is ordinary regulatory English
COMMON_SECTIONS = 40


@lru_cache(maxsize=1)
def _counts() -> dict[str, int]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))["sections_using"]
    except (OSError, ValueError, KeyError):
        return {}   # without the file every word stays a possible premise, as before


def common(word: str) -> bool:
    return _counts().get(word, 0) >= COMMON_SECTIONS


def build(db) -> dict:
    import collections

    from regulus.rag.claim_validation import _words

    per_section: dict[str, set[str]] = collections.defaultdict(set)
    for r in db.query("SELECT section_number, section_heading, body_text FROM cfr_records "
                      "WHERE removed_on IS NULL AND NOT is_reserved"):
        per_section[r["section_number"]] |= _words(f"{r['section_heading'] or ''} {r['body_text'] or ''}")
    counts = collections.Counter(w for ws in per_section.values() for w in ws)
    return {"sections": len(per_section), "built_from": "cfr_records (live, not reserved)",
            "sections_using": dict(sorted(counts.items()))}


if __name__ == "__main__":
    from regulus.retrieval.db import Database

    _db = Database.from_env()
    _db.connect()
    try:
        data = build(_db)
    finally:
        _db.close()
    PATH.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{PATH}: {len(data['sections_using'])} words over {data['sections']} sections")
