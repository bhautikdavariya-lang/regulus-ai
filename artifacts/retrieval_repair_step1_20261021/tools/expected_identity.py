"""Read-only: (1) reproduce the database's current eCFR corpus identity from its rows; (2) compute the identity the
plan must produce (renumbered ordinals, inserted rows' content hashes); (3) back up every current row of the planned
sections (all columns except the embedding vector, which the repair does not touch). Writes <out_dir>/expected_identity.json
and <out_dir>/backup_before_apply.json."""
import hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401
from regulus.retrieval.db import Database  # noqa: E402
from regulus.traceability.corpus import corpus_identity  # noqa: E402
D = Path(sys.argv[1]).resolve()
plan = json.loads((D / "plan.json").read_text())
secs = [s["section_number"] for s in plan["sections"] if s["status"] == "planned"]
db = Database.from_env(); db.connect()
try:
    live = corpus_identity(db)["ecfr"] if callable(corpus_identity) else None
    rows = db.query("SELECT section_number, ordinal, id::text AS id, content_sha256 FROM cfr_records "
                    "WHERE removed_on IS NULL AND NOT is_reserved ORDER BY section_number, ordinal, id")
    backup = db.query("SELECT id::text, title, chapter, subchapter_code, part_number, subpart_id, section_number, paragraph_path, "
                      "path_ordinal, ordinal, section_heading, parent_headings, body_text, effective_date::text, last_amended_date::text, "
                      "fr_citation, ecfr_permalink, govinfo_pdf_url, source_endpoint, retrieved_at::text, snapshot_date::text, "
                      "content_sha256, source_payload_sha256, is_reserved, removed_on::text, created_at::text, updated_at::text, "
                      "embedding_model, embedded_at::text, embedding_source_sha256 FROM cfr_records WHERE section_number = ANY(%(s)s) "
                      "ORDER BY section_number, ordinal", {"s": secs})
finally:
    db.close()
sha = lambda xs: hashlib.sha256(",".join(xs).encode()).hexdigest()
now = sha([r["content_sha256"] for r in rows])
upd = {u[0]: u[2] for s in plan["sections"] for u in s["ordinal_updates"]}
new = {}
for s in plan["sections"]:
    for r in s["inserts"]:
        new.setdefault(r["section_number"], []).append({"section_number": r["section_number"], "ordinal": r["ordinal"],
                                                         "id": "~new", "content_sha256": r["content_sha256"]})
out, i = [], 0
while i < len(rows):
    j = i
    while j < len(rows) and rows[j]["section_number"] == rows[i]["section_number"]:
        j += 1
    group = [dict(r, ordinal=upd.get(r["id"], r["ordinal"])) for r in rows[i:j]] + new.get(rows[i]["section_number"], [])
    assert len({g["ordinal"] for g in group}) == len(group), rows[i]["section_number"]
    out += sorted(group, key=lambda g: g["ordinal"])
    i = j
res = {"current": {"rows": len(rows), "sha256_reproduced": now, "sha256_reported_by_corpus_identity": live and live.get("sha256"),
                   "reproduction_matches": live is not None and now == live.get("sha256")},
       "expected_after_apply": {"rows": len(out), "sha256": sha([r["content_sha256"] for r in out])},
       "plan_sha256": plan["plan_sha256"], "backup_rows": len(backup)}
(D / "expected_identity.json").write_text(json.dumps(res, indent=1))
(D / "backup_before_apply.json").write_text(json.dumps(backup, indent=1, ensure_ascii=False, default=str))
print(json.dumps(res, indent=1))
