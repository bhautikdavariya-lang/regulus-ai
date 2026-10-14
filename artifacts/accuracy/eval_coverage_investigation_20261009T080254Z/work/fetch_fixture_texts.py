"""READ-ONLY (server-enforced read-only connection): verbatim paragraphs for the regression fixtures, with
snapshot date and SHA-256 of body_text. Writes only OUT."""
import hashlib, json, sys
from regulus.retrieval import Database
WANT = [("10.3", "(a)"), ("203.3", "(n)"), ("114.3", "(c)"), ("211.25", "(a)"), ("211.25", "(b)"), ("211.25", "(c)"),
        ("314.50", ""), ("314.50", "(a)(1)"), ("314.50", "(a)(2)"), ("314.50", "(a)(3)")] + \
       [("820.35", p) for p in ("", "(a)", "(a)(1)", "(a)(2)", "(a)(3)", "(a)(4)", "(a)(5)", "(a)(6)", "(a)(7)", "(b)", "(b)(1)",
                                "(b)(2)", "(b)(3)", "(b)(4)", "(b)(5)", "(b)(6)")]
db = Database.from_env(); db.connect()
assert db.query("SELECT current_setting('transaction_read_only') AS ro")[0]["ro"] == "on"
out = []
for sec, para in WANT:
    # a definitions paragraph holds one record per defined term: take the record that defines it
    opens = {"10.3": "FDA means", "203.3": "(n) FDA means", "114.3": "(c) Lot means"}.get(sec, "")
    r = db.query("SELECT body_text, snapshot_date FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved AND section_number = %s "
                 "AND coalesce(paragraph_path,'') = %s AND body_text LIKE %s ORDER BY ordinal LIMIT 1", (sec, para, opens + "%"))[0]
    out.append({"citation": f"21 CFR {sec}{para}", "text": r["body_text"], "snapshot_date": str(r["snapshot_date"]),
                "content_sha256": hashlib.sha256(r["body_text"].encode()).hexdigest()})
db.close()
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
print(len(out), "paragraphs;", [o["citation"] for o in out][:6])
