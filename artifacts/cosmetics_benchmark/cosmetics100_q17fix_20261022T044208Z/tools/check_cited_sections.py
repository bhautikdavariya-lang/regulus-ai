"""Check that every CFR section named in a delivered answer's text exists (live, not removed) in the read-only database."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from regulus.retrieval.db import Database
run = Path(sys.argv[1]).resolve()
pat = re.compile(r"(?:21 CFR|§|§§)\s*(\d{1,4}\.\d+[a-z]?)|\b(\d{1,4}\.\d+[a-z]?)(?=\s*\()")
found = {}
for line in (run / "results.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    if r.get("fallback_type") == "unvalidated_answer_withheld":
        continue   # withholding notices list retrieved sources, not claims
    for a, b in pat.findall(r.get("answer") or ""):
        found.setdefault(a or b, set()).add(r["question_id"])
db = Database.from_env(); db.connect()
rows = db.query("SELECT DISTINCT section_number FROM cfr_records WHERE removed_on IS NULL AND section_number = ANY(%(s)s)",
                {"s": sorted(found)})
exists = {x["section_number"] for x in rows}
db.close()
out = {"checked_sections": len(found), "exist": sorted(exists),
       "not_found": {s: sorted(found[s]) for s in sorted(found) if s not in exists}}
(run / "scoring" / "cited_section_check.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
