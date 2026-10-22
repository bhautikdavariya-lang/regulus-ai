"""Fetch a part's eCFR XML from the exact source_endpoint the database recorded for it, and keep it only if its sha256
equals the database's source_payload_sha256 for that part. Public GET only; writes <out_dir>/part-<N>.xml and a log.

    python fetch_verified_xml.py <out_dir> <part> [<part> ...]
"""
from __future__ import annotations
import gzip, hashlib, json, sys, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401
from regulus.retrieval.db import Database  # noqa: E402

out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
db = Database.from_env(); db.connect()
try:
    meta = {p: db.query("SELECT DISTINCT source_endpoint, source_payload_sha256 FROM cfr_records WHERE part_number = %(p)s", {"p": p})
            for p in sys.argv[2:]}
finally:
    db.close()
log = []
for part, rows in meta.items():
    assert len(rows) == 1, (part, rows)
    url, want = rows[0]["source_endpoint"], rows[0]["source_payload_sha256"]
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "regulus-source-repair/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    got = hashlib.sha256(data).hexdigest()
    rec = {"part": part, "url": url, "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bytes": len(data),
           "sha256": got, "db_source_payload_sha256": want, "verified": got == want}
    if rec["verified"]:
        (out / f"part-{part}.xml").write_bytes(data)
    log.append(rec)
    print(json.dumps(rec))
(out / "fetch_log.json").write_text(json.dumps(log, indent=1))
