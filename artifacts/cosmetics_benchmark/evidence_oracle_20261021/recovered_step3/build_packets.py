"""Build and verify the fixed evidence packets (read-only DB, SELECT only). Writes packets.json to argv[1]."""
import json, re, sys, hashlib, glob, os
sys.dont_write_bytecode = True
OUT, SNAP, RUN = sys.argv[1], sys.argv[2], sys.argv[3]
from regulus.retrieval.db import Database
from regulus.retrieval import sql as SQLM
db = Database.from_env(); _q = db.query
def q(s, p=None):
    assert re.match(r"(?is)^\s*(select|with)\b", s); return _q(s, p)
st = {k: v for k, v in db.status().items() if k != "url"}
assert st["transaction_read_only"] == "on" and st["default_transaction_read_only"] == "on"

PACKETS = {
    "COS-710.5-Q1":   [("710.5", "")],
    "COS-700.18-Q1":  [("700.18", "(a)"), ("700.18", "(b)")],
    "COS-82.1321-Q1": [("82.1321", ""), ("82.1050", "")],
    "COS-740.12-Q1":  [("740.12", "(a)"), ("740.12", "(b)"), ("740.12", "(c)")],
    "COS-70.50-Q2":   [("70.50", "(a)"), ("70.50", "(b)"), ("70.50", "(c)")],
    "COS-82.101-Q1":  [("82.101", ""), ("82.50", ""), ("82.5", "*")],
    "COS-720.4-Q3":   [("720.4", "(c)(6)*"), ("720.4", "(c)(7)*"), ("720.4", "(d)"), ("720.4", "(d)(1)"), ("720.4", "(d)(2)"),
                       ("720.4", "(d)(3)"), ("720.4", "(e)")],
    "COS-70.3-Q3":    [("70.3", "(s)"), ("70.3", "(u)"), ("70.3", "(v)")],
    "COS-80.10-Q1":   [("80.10", "(a)"), ("80.10", "(c)"), ("80.10", "(d)")],
    "COS-73.2725-Q1": [("73.2725", "(a)"), ("73.2725", "(b)"), ("73.2725", "(c)"), ("73.2725", "(d)"), ("73.2725", "(e)")],
    "COS-74.2317-Q1": [("74.2317", "(b)"), ("74.2317", "(c)"), ("74.2317", "(d)"), ("70.3", "(v)")],
    "COS-700.15-Q1":  [("700.15", "(a)"), ("700.15", "(b)"), ("700.15", "(c)")],
}
snap = {}
for l in open(SNAP):
    d = json.loads(l)
    if d["corpus"] == "ecfr":
        m = d["metadata"]; snap[(m["section_number"], m.get("paragraph_path") or "")] = d["text"]
hist = {}
for f in glob.glob(os.path.join(RUN, "responses", "*.json")):
    r = json.load(open(f))
    for s in r.get("sources") or []:
        if s.get("corpus") == "ecfr" and not s.get("truncated"):
            mm = re.match(r"21 CFR (\d+\.\d+[a-z]?)((?:\([^)]+\))*)$", s["citation"])
            if mm: hist[(mm.group(1), mm.group(2))] = s["text"]

out = {"session": st, "questions": {}}
for qid, spec in PACKETS.items():
    rows = []
    for sec, path in spec:
        allrows = q("SELECT section_number, paragraph_path, ordinal, section_heading, body_text, snapshot_date "
                    "FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL AND NOT is_reserved ORDER BY ordinal", {"s": sec})
        if path == "*":
            sel = allrows
        elif path.endswith("*"):
            p = path[:-1]; sel = [r for r in allrows if r["paragraph_path"] == p or r["paragraph_path"].startswith(p + "(")]
        else:
            sel = [r for r in allrows if (r["paragraph_path"] or "") == path]
        assert sel, (qid, sec, path)
        for r in sel:
            key = (r["section_number"], r["paragraph_path"] or "")
            text = r["body_text"]
            rows.append({"section": key[0], "path": key[1], "citation": f"21 CFR {key[0]}{key[1]}", "heading": r["section_heading"],
                         "text": text, "chars": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest(),
                         "snapshot_date": str(r["snapshot_date"]),
                         "matches_corpus_snapshot": (snap[key] == text) if key in snap else None,
                         "matches_20oct_prompt_text": (hist[key] == text) if key in hist else None})
    out["questions"][qid] = {"rows": rows, "total_chars": sum(r["chars"] for r in rows), "n_rows": len(rows)}
db.close()
json.dump(out, open(os.path.join(OUT, "packets.json"), "w"), indent=1, default=str)
for qid, v in out["questions"].items():
    snapc = [r["matches_corpus_snapshot"] for r in v["rows"]]; histc = [r["matches_20oct_prompt_text"] for r in v["rows"]]
    print(f"{qid:16} rows={v['n_rows']:2} chars={v['total_chars']:5} | snapshot match {sum(1 for x in snapc if x)}/{sum(1 for x in snapc if x is not None)} "
          f"(mismatch {sum(1 for x in snapc if x is False)}) | 20-Oct prompt match {sum(1 for x in histc if x)}/{sum(1 for x in histc if x is not None)} "
          f"(mismatch {sum(1 for x in histc if x is False)}) | snapshot_date {set(r['snapshot_date'] for r in v['rows'])}")
