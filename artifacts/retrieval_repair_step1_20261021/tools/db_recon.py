"""Read-only reconnaissance of the target database for the source-text repair (Step 1). SELECT only; never prints the
connection URL. Writes <out_json>.

    python db_recon.py <out_json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401  (SELECT-only Database.query, semantic loader refused)

from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
ROWS = [("740.11", "(a)(1)"), ("740.11", "(b)(1)"), ("740.12", "(b)"), ("701.3", "(c)(2)(i)(a)"), ("701.3", "(c)(2)(i)(b)"),
        ("701.3", "(c)(2)(i)(c)"), ("701.13", "(n)"), ("71.1", "(c)"), ("73.2180", "(a)(2)"), ("73.2250", "(b)"),
        ("74.2602a", "(b)"), ("81.30", "(d)"), ("81.30", "(e)"), ("73.2725", "(b)"), ("73.2180", "(b)")]
q = None


def one(sql, p=None):
    r = q(sql, p)
    return r[0] if r else None


db = Database.from_env()
db.connect()
q = db.query
try:
    status = {k: v for k, v in db.status().items() if k != "url"}
    fp0 = RB.database_fingerprint(db)
    out = {"status_without_url": status,
           "identity": one("SELECT current_database() AS db, current_user AS role, session_user, inet_server_addr()::text AS server_addr, "
                           "inet_server_port() AS port, version() AS version, current_setting('default_transaction_read_only') AS ro, "
                           "current_setting('transaction_read_only') AS tx_ro"),
           "role_attrs": one("SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname = current_user"),
           "can_update_cfr_records": one("SELECT has_table_privilege(current_user, 'cfr_records', 'UPDATE') AS upd, "
                                         "has_table_privilege(current_user, 'cfr_records', 'INSERT') AS ins"),
           "triggers": q("SELECT tgname, pg_get_triggerdef(t.oid) AS def FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                         "WHERE c.relname IN ('cfr_records', 'cfr_record_versions', 'cfr_sections') AND NOT t.tgisinternal"),
           "constraints": q("SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conrelid = 'cfr_records'::regclass"),
           "indexes": q("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'cfr_records'"),
           "columns": q("SELECT column_name, data_type, is_nullable, column_default, is_generated, generation_expression "
                        "FROM information_schema.columns WHERE table_name = 'cfr_records' ORDER BY ordinal_position"),
           "versions_columns": q("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'cfr_record_versions' "
                                 "ORDER BY ordinal_position"),
           "content_sha_rule": one("SELECT count(*) AS n, sum((content_sha256 = encode(sha256(convert_to(body_text, 'UTF8')), 'hex'))::int) "
                                   "AS sha_of_body FROM cfr_records"),
           "path_ordinal": q("SELECT path_ordinal, count(*) AS n FROM cfr_records GROUP BY 1 ORDER BY 1 LIMIT 10"),
           "path_ordinal_examples": q("SELECT section_number, paragraph_path, path_ordinal, left(body_text, 120) AS t FROM cfr_records "
                                      "WHERE path_ordinal > 0 ORDER BY section_number LIMIT 8"),
           "ingestion_runs_cfr": q("SELECT kind, state, snapshot_date::text, started_at::text, finished_at::text, manifest_sha256 "
                                   "FROM ingestion_runs WHERE kind = 'cfr' ORDER BY started_at DESC LIMIT 3"),
           "snapshot_dates": q("SELECT snapshot_date::text, count(*) AS n FROM cfr_records GROUP BY 1"),
           "corpus_leadins_without_children": one(
               "SELECT count(*) AS n, count(DISTINCT r.part_number) AS parts FROM cfr_records r "
               "WHERE r.removed_on IS NULL AND rtrim(r.body_text) LIKE '%:' AND r.paragraph_path IS NOT NULL AND r.paragraph_path <> '' "
               "AND NOT EXISTS (SELECT 1 FROM cfr_records c WHERE c.section_number = r.section_number AND c.removed_on IS NULL "
               "AND c.paragraph_path LIKE r.paragraph_path || '(%%')"),
           "rows": {}}
    for sec, path in ROWS:
        r = q("SELECT id, section_number, paragraph_path, path_ordinal, ordinal, part_number, subpart_id, section_heading, "
              "effective_date::text, snapshot_date::text, retrieved_at::text, source_endpoint, ecfr_permalink, content_sha256, "
              "source_payload_sha256, fr_citation, length(body_text) AS chars, body_text, embedding IS NOT NULL AS has_embedding, "
              "embedding_source_sha256 FROM cfr_records WHERE section_number = %(s)s AND paragraph_path = %(p)s AND removed_on IS NULL "
              "ORDER BY path_ordinal", {"s": sec, "p": path})
        out["rows"][f"{sec}{path}"] = r
    fp1 = RB.database_fingerprint(db)
    out["database_unchanged"] = all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))
finally:
    db.close()
OUT.write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
show = {k: v for k, v in out.items() if k not in ("rows", "columns", "indexes")}
print(json.dumps(show, indent=1, default=str)[:6000])
for k, v in out["rows"].items():
    for r in v:
        print(k, r["id"], "po", r["path_ordinal"], "ord", r["ordinal"], r["snapshot_date"], r["source_endpoint"], "sha_ok?", r["chars"], "emb", r["has_embedding"])
