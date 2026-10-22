"""Read-only: for every EXTRACT / FP / DIV(table) / XREF / EDNOTE / EFFDNOT direct child of a section in the hash-verified
part payloads, is its text stored in any cfr_records row of that section? Also: do stored body_texts contain newlines, and
is a stored row's text exactly the whitespace-normalised XML text? Writes <out_json>."""
from __future__ import annotations
import json, sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401
from regulus.retrieval.db import Database  # noqa: E402
X = Path(__file__).resolve().parents[1] / "source_xml"
OUT = Path(sys.argv[1]).resolve()
norm = lambda t: " ".join((t or "").split())
db = Database.from_env(); db.connect()
res = {"elements": [], "by_tag": {}, "p_exact": Counter()}
try:
    res["newline_rows"] = db.query("SELECT count(*) AS n FROM cfr_records WHERE body_text LIKE '%%' || chr(10) || '%%'")[0]["n"]
    for part in ("701", "740", "71", "73", "74", "81"):
        root = ET.parse(X / f"part-{part}.xml").getroot()
        for s in root.iter():
            if not (s.tag.startswith("DIV") and s.get("TYPE") == "SECTION"):
                continue
            n = s.get("N")
            rows = db.query("SELECT body_text FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL", {"s": n})
            bodies = [r["body_text"] for r in rows]
            joined = norm(" ".join(bodies))
            for c in s:
                t = norm("".join(c.itertext()))
                if c.tag == "P":
                    res["p_exact"]["P stored exactly as one row" if t in bodies else "P text inside stored text" if t in joined else "P not stored"] += 1
                    continue
                if c.tag in ("HEAD", "CITA"):
                    continue
                stored = any(norm(b) == t for b in bodies) or (len(t) > 20 and t in joined)
                res["elements"].append({"part": part, "section": n, "tag": c.tag, "children": [g.tag for g in c][:8],
                                        "n_children": len(list(c)), "stored": stored, "text": t[:160]})
finally:
    db.close()
for e in res["elements"]:
    k = f"{e['tag']} stored={e['stored']}"
    res["by_tag"][k] = res["by_tag"].get(k, 0) + 1
res["p_exact"] = dict(res["p_exact"])
OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: res[k] for k in ("newline_rows", "by_tag", "p_exact")}, indent=1))
print("max EXTRACT children:", max(e["n_children"] for e in res["elements"] if e["tag"] == "EXTRACT"))
print(Counter(g for e in res["elements"] if e["tag"] == "EXTRACT" for g in e["children"]))
