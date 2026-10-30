"""Build data/reference/acronyms_v1.json: the acronyms 21 CFR defines in its own text ("reference amount commonly consumed
(RACC)"), for SY4 (regulus.rag.section_promotion) - a question writing "RACC" is searched with the words the regulations use.

    python scripts/build_acronyms.py [--out data/reference/acronyms_v1.json]

Reads the live cfr_records rows only (nothing is written to the database). An acronym is kept when an expansion whose
initials spell it stands right before it in parentheses; the most frequent expansion wins. Acronyms of fewer than three
letters, and those whose corpus sense is not the one questions use, are listed under "excluded" with the reason.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.retrieval import Database  # noqa: E402

_SMALL = {"of", "and", "the", "for", "to", "in", "on", "a", "an", "or"}
# the corpus sense is not the one questions mean, or the letters are an English word
EXCLUDED = {
    "PDP": "corpus: product development protocol (814); labeling questions mean principal display panel (101.1, 201.60)",
    "IEC": "corpus: independent ethics committee (312.120); device questions mean the International Electrotechnical Commission",
    "WHO": "an English word",
}


def expansions(rows) -> dict[str, collections.Counter]:
    found: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for text in rows:
        for m in re.finditer(r"\(([A-Z][A-Z&]{1,7})s?\)", text):
            acronym, before = m.group(1), text[:m.start()].rstrip()
            letters = [c for c in acronym if c.isalpha()]
            words = re.findall(r"[A-Za-z][A-Za-z'-]*", before)[-12:]
            for i in range(len(words) - 1, -1, -1):
                initials = [w[0].upper() for w in words[i:] if w.lower() not in _SMALL]
                if initials == letters:
                    found[acronym][" ".join(words[i:]).lower()] += 1
                    break
                if len(initials) > len(letters):
                    break
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/reference/acronyms_v1.json"))
    a = ap.parse_args()
    db = Database.from_env()
    db.connect()
    rows = [r["body_text"] for r in db.query("SELECT body_text FROM cfr_records WHERE removed_on IS NULL AND "
                                             "body_text ~ '\\([A-Z][A-Za-z&]{1,7}s?\\)'", {})]
    table, excluded = {}, dict(EXCLUDED)
    for acronym, counts in sorted(expansions(rows).items()):
        if acronym in excluded:
            continue
        if sum(c.isalpha() for c in acronym) < 3:
            excluded[acronym] = "fewer than three letters"
            continue
        expansion, n = counts.most_common(1)[0]
        table[acronym] = {"expansion": expansion, "count": n}
    Path(a.out).write_text(json.dumps({"built_from": "cfr_records (live rows)", "acronyms": table,
                                       "excluded": dict(sorted(excluded.items()))}, indent=1) + "\n")
    print(f"{len(table)} acronyms, {len(excluded)} excluded -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
