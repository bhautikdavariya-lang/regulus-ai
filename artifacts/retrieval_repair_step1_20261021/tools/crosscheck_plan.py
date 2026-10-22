"""Independent cross-check of every planned row's text (no database): (1) against the plain whitespace-normalised
itertext of its source element; (2) for parts 701 and 740, against the independent review's own rendering of the same
payload (sources/ecfr_2026-10-14/part-*.txt, whose source XML has the same SHA-256). Writes <out_json>."""
import hashlib, json, sys
from pathlib import Path
from xml.etree import ElementTree as ET
D = Path(__file__).resolve().parents[1]
ROOT = D.parents[1]
TXT = ROOT / "artifacts/benchmark_verification/independent_review_20261019T103917Z/sources/ecfr_2026-10-14"
LOG = ROOT / "artifacts/benchmark_verification/independent_review_20261019T103917Z/sources/ecfr_fetch_log.jsonl"
norm = lambda t: " ".join((t or "").split())
plan = json.loads((D / "plan.json").read_text())
review = {json.loads(l)["part"]: json.loads(l) for l in LOG.read_text().splitlines() if l.strip()}
out = []
for s in plan["sections"]:
    part = s["section_number"].split(".")[0]
    xml = (D / "source_xml" / f"part-{part}.xml").read_bytes()
    root = ET.fromstring(xml)
    sec = next(e for e in root.iter() if e.tag.startswith("DIV") and e.get("TYPE") == "SECTION" and e.get("N") == s["section_number"])
    plain = [norm("".join(c.itertext())) for c in sec if c.tag in ("EXTRACT", "FP")]
    txt_lines = None
    if part in review and review[part].get("xml_sha256") == hashlib.sha256(xml).hexdigest():
        txt = (TXT / f"part-{part}.txt").read_text(encoding="utf-8")
        assert hashlib.sha256(txt.encode()).hexdigest() == review[part]["txt_sha256"]
        txt_lines = set(txt.splitlines())
    for r in s["inserts"]:
        out.append({"row": f"{s['section_number']}{r['paragraph_path']}#{r['path_ordinal']}", "equals_plain_itertext": r["body_text"] in plain,
                    "equals_independent_review_rendering": (r["body_text"] in txt_lines) if txt_lines is not None else None})
(D / "plan_crosscheck.json").write_text(json.dumps(out, indent=1))
print(f"{sum(o['equals_plain_itertext'] for o in out)}/{len(out)} equal plain itertext; "
      f"{sum(o['equals_independent_review_rendering'] is True for o in out)}/{sum(o['equals_independent_review_rendering'] is not None for o in out)} equal the independent review rendering")
