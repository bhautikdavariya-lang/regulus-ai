"""READ-ONLY (server-enforced read-only connection): real snapshot sentences with temperature limits and age thresholds."""
import json, re, sys, hashlib
from regulus.retrieval import Database
from regulus.evaluation.grounding_eval import split_sentences
db = Database.from_env(); db.connect()
assert db.query("SELECT current_setting('transaction_read_only') AS ro")[0]["ro"] == "on"
out = {}
for name, rx, sql in [
    ("temp", re.compile(r"\b(?:not\s+(?:more|less)\s+than|at\s+least|below|above|exceed\w*)\s+\d+(?:\.\d+)?\s*°\s*[CF]\b|\b(?:not\s+(?:more|less)\s+than|at\s+least|below|above)\s+\d+\s+degrees?\s+(?:F|C|Fahrenheit|Celsius)\b", re.I), r"(°\s*[CF]|degrees?\s+(F|C|Fahrenheit|Celsius))"),
    ("age", re.compile(r"\b(?:under|over|less\s+than|at\s+least|younger\s+than|older\s+than)\s+\d+\s+(?:years?|months?)\s+(?:of\s+age|old)\b", re.I), r"(years?|months?) (of age|old)")]:
    rows = db.query("SELECT section_number, paragraph_path, body_text, snapshot_date FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved AND body_text ~* %s", (sql,))
    hits = []
    for r in rows:
        for s in split_sentences(r["body_text"] or ""):
            if rx.search(s):
                hits.append({"citation": f"21 CFR {r['section_number']}{r['paragraph_path'] or ''}", "sentence": s.strip(), "snapshot_date": str(r["snapshot_date"]),
                             "content_sha256": hashlib.sha256(r["body_text"].encode()).hexdigest(), "paragraph": r["body_text"]})
    out[name] = hits
    print(name, len(hits))
    for h in hits[:8]: print("  ", h["citation"], "|", h["sentence"][:200])
db.close()
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
