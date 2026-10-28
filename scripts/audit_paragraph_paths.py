"""Audit cfr_records.paragraph_path against eCFR's own paragraph identifiers.

    python scripts/audit_paragraph_paths.py PATHS.tsv ECFR_HTML_DIR OUT_DIR

The eCFR versioner XML gives paragraphs as flat <P> elements, so their nesting has to be inferred, and "(i)" after
"(h)" is a letter or a roman numeral depending on context: the original ingestion read 111.210's "(i)" under (h)(3) as
paragraph (i) and filed (h)(4) as (i)(ii)(B)(4) (300Q S-018, 28 Oct 2026). The eCFR renderer
(/api/renderer/v1/content/enhanced/{date}/title-21?part=N) carries eCFR's paragraph ids (id="p-111.210(h)(3)(i)"),
which are the authority used here.

PATHS.tsv: id, section_number, ordinal, paragraph_path, the first 40 characters of body_text, one live row per line (a
SELECT over cfr_records). For each section the labelled rows, in order, are aligned with the section's eCFR ids by
their own leading label; a row whose stored path differs from its aligned id is a correction. Writes
OUT_DIR/corrections.tsv, OUT_DIR/repair.sql and OUT_DIR/rollback.sql (UPDATE ... WHERE id AND the old path, so a
changed row is never overwritten), and prints a summary. Nothing is written to the database.
"""
from __future__ import annotations

import collections
import html
import re
import sys
from pathlib import Path

ID = re.compile(r'id="p-(\d+\.\d+[a-z]?)((?:\([^)"]+\))+)"')
LEAD = re.compile(r"^\s*((?:\([a-zA-Z0-9]{1,6}\))+)")
LABEL = re.compile(r"\(([^)]+)\)")
# a paragraph designator: (a), (12), (iv), (B). Definitions sections are given ids by their terms ("1107.12(Premium
# cigars)(2)", "1.328(Farm)(1)(iii)"): not paths, and their rows do not align, so such a section is left as it is
DESIGNATOR = re.compile(r"^(?:\([a-zA-Z0-9]{1,6}\))+$")


def ecfr_ids(html_dir: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = collections.defaultdict(list)
    for f in sorted(html_dir.glob("part-*.html")):
        for sec, path in ID.findall(html.unescape(f.read_text(encoding="utf-8", errors="replace"))):
            if not out[sec] or out[sec][-1] != path:
                out[sec].append(path)
    return out


def align(rows: list[tuple[int, str, str, str]], ids: list[str]) -> list[tuple[str, str, str]]:
    """(record id, stored path, eCFR path) for each labelled row whose leading label matches the next eCFR id's last
    label; rows that cannot be aligned are left out (reported as unaligned)."""
    out, k = [], 0
    for _, rid, path, head in rows:
        m = LEAD.match(head)
        if not m:
            continue
        last = LABEL.findall(m.group(1))[-1]
        j = k
        while j < len(ids) and LABEL.findall(ids[j])[-1] != last:
            j += 1
        if j == len(ids):
            out.append((rid, path, None))
            continue
        # a row opening with several labels ("(a)(1) ...") is the deepest of them
        out.append((rid, path, ids[j]))
        k = j + 1
    return out


def main(paths_tsv: str, html_dir: str, out_dir: str) -> None:
    ids = ecfr_ids(Path(html_dir))
    rows: dict[str, list] = collections.defaultdict(list)
    for line in open(paths_tsv, encoding="utf-8"):
        rid, sec, ordn, path, head = (line.rstrip("\n").split("\t") + [""] * 5)[:5]
        rows[sec].append((int(ordn), rid, path, head))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fixes, unaligned, no_ids, checked, term_ids = [], 0, 0, 0, 0
    for sec, rs in sorted(rows.items()):
        rs.sort()
        if sec not in ids:
            no_ids += 1
            continue
        if not all(DESIGNATOR.match(i) for i in ids[sec]):
            term_ids += 1
            continue
        for rid, old, new in align(rs, ids[sec]):
            checked += 1
            if new is None:
                unaligned += 1
            elif new != old:
                fixes.append((sec, rid, old, new))
    with open(out / "corrections.tsv", "w") as f:
        f.writelines(f"{s}\t{r}\t{o}\t{n}\n" for s, r, o, n in fixes)
    q = lambda s: "'" + s.replace("'", "''") + "'"
    with open(out / "repair.sql", "w") as f:
        f.write("BEGIN;\n")
        f.writelines(f"UPDATE cfr_records SET paragraph_path = {q(n)} WHERE id = {q(r)} AND paragraph_path = {q(o)};\n"
                     for _, r, o, n in fixes)
        f.write("COMMIT;\n")
    with open(out / "rollback.sql", "w") as f:
        f.write("BEGIN;\n")
        f.writelines(f"UPDATE cfr_records SET paragraph_path = {q(o)} WHERE id = {q(r)} AND paragraph_path = {q(n)};\n"
                     for _, r, o, n in fixes)
        f.write("COMMIT;\n")
    secs = collections.Counter(s for s, *_ in fixes)
    print(f"sections with eCFR ids: {len(ids)} | sections without: {no_ids} | term-id sections left as they are: {term_ids} | "
          f"labelled rows checked: {checked} | "
          f"unaligned: {unaligned} | corrections: {len(fixes)} in {len(secs)} sections")
    print("most affected:", secs.most_common(20))


if __name__ == "__main__":
    main(*sys.argv[1:4])
