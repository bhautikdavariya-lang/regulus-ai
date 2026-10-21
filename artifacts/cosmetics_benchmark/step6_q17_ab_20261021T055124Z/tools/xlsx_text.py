"""Read-only .xlsx text dump with the standard library (no openpyxl): sheet names, or one sheet's rows.

    python xlsx_text.py <book.xlsx>                 list sheets
    python xlsx_text.py <book.xlsx> <sheet name>    print that sheet's non-empty rows, cells joined by ' | '
"""
from __future__ import annotations

import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def sheets(z: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    out = {}
    for s in wb.find("m:sheets", NS):
        t = target[s.get("{%s}id" % NS["r"])]
        out[s.get("name")] = "xl/" + t.lstrip("/").removeprefix("xl/")
    return out


def shared(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])) for si in root.findall("m:si", NS)]


def rows(z: zipfile.ZipFile, path: str, strings: list[str]):
    root = ET.fromstring(z.read(path))
    for row in root.iter("{%s}row" % NS["m"]):
        cells = []
        for c in row.findall("m:c", NS):
            v = c.find("m:v", NS)
            if c.get("t") == "s" and v is not None:
                cells.append(strings[int(v.text)])
            elif c.get("t") == "inlineStr":
                cells.append("".join(t.text or "" for t in c.iter("{%s}t" % NS["m"])))
            elif v is not None:
                cells.append(v.text)
        cells = [x for x in cells if x not in (None, "")]
        if cells:
            yield cells


def main() -> int:
    with zipfile.ZipFile(sys.argv[1]) as z:
        sh = sheets(z)
        if len(sys.argv) < 3:
            print("\n".join(sh))
            return 0
        strings = shared(z)
        for cells in rows(z, sh[sys.argv[2]], strings):
            print(re.sub(r"\s+", " ", " | ".join(cells)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
