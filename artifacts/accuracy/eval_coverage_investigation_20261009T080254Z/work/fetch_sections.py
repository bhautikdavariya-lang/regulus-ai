"""READ-ONLY (server-enforced read-only connection): the verbatim text of the sections in the six cases, and every
snapshot paragraph that defines the acronym FDA. Writes only OUT."""
import json, sys, hashlib
from regulus.retrieval import Database
OUT = sys.argv[1]
db = Database.from_env(); db.connect()
assert db.query("SELECT current_setting('transaction_read_only') AS ro")[0]["ro"] == "on"
out = {"sections": {}, "fda_definitions": []}
for sec in ("211.25", "312.32", "314.50", "801.15", "820.35"):
    rows = db.query("SELECT section_number, paragraph_path, section_heading, body_text, snapshot_date FROM cfr_records "
                    "WHERE removed_on IS NULL AND NOT is_reserved AND section_number = %s ORDER BY ordinal", (sec,))
    out["sections"][sec] = [{"paragraph": r["paragraph_path"] or "", "heading": r["section_heading"], "text": r["body_text"],
                             "sha256": hashlib.sha256((r["body_text"] or "").encode()).hexdigest(), "snapshot": str(r["snapshot_date"])} for r in rows]
    print(sec, len(rows), "records |", (rows[0]["section_heading"] if rows else ""))
rows = db.query("SELECT section_number, paragraph_path, body_text, snapshot_date FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved "
                "AND body_text ~* %s ORDER BY section_number", (r"\mFDA\M\W{0,3}\s*(means|stands for)\s+(the\s+)?(U\.S\.\s+)?Food and Drug Administration",))
for r in rows:
    out["fda_definitions"].append({"citation": f"21 CFR {r['section_number']}{r['paragraph_path'] or ''}", "text": r["body_text"][:400],
                                   "sha256": hashlib.sha256(r["body_text"].encode()).hexdigest(), "snapshot": str(r["snapshot_date"])})
print("paragraphs defining FDA:", len(rows)); [print("  ", d["citation"], "|", d["text"][:140]) for d in out["fda_definitions"][:12]]
db.close()
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
