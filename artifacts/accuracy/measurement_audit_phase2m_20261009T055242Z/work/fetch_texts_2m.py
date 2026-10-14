"""READ-ONLY (server-enforced read-only connection): fetch the verbatim eCFR paragraphs used by the Phase 2M diagnostics,
with snapshot date and SHA-256 of the body text. Writes only OUT."""
import hashlib, json, sys
from regulus.retrieval import Database
OUT = sys.argv[1]
WANT = [("1.379", "(a)"), ("1.379", "(b)"), ("1150.1", ""), ("701.13", "(d)"), ("113.40", "(a)(6)"), ("1141.1", "(b)"),
        ("211.180", "(a)"), ("178.3760", ""), ("112.203", "(d)(2)"), ("800.55", "(c)"), ("1.24", "(a)(4)"), ("1141.1", "(a)")]
db = Database.from_env(); db.connect()
assert db.query("SELECT current_setting('transaction_read_only') AS ro")[0]["ro"] == "on"
out = {}
for sec, para in WANT:
    rows = db.query("SELECT section_number, paragraph_path, body_text, snapshot_date FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved "
                    "AND section_number = %s AND coalesce(paragraph_path,'') = %s ORDER BY ordinal", (sec, para))
    for r in rows[:1]:
        b = r["body_text"]; cit = f"21 CFR {sec}{para}"
        out[cit] = {"text": b, "snapshot_date": str(r["snapshot_date"]), "content_sha256": hashlib.sha256(b.encode("utf-8")).hexdigest()}
        print(cit, out[cit]["content_sha256"][:12], "|", b[:150].replace("\n", " "))
    if not rows: print("MISSING", sec, para)
db.close()
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
