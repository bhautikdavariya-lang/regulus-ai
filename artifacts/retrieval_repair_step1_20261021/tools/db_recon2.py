"""Read-only follow-up: how the original ingestion stored undesignated text after a designated paragraph; hash and
embedding rules for the affected rows; payload provenance. SELECT only. Writes <out_json>."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401
from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
OUT = Path(sys.argv[1]).resolve()
db = Database.from_env(); db.connect(); q = db.query
try:
    fp0 = RB.database_fingerprint(db)
    out = {
      "designated_path_with_po_gt0": q("SELECT count(*) AS n, count(DISTINCT section_number) AS sections FROM cfr_records WHERE paragraph_path <> '' AND path_ordinal > 0")[0],
      "designated_po_examples": q("SELECT r.section_number, r.paragraph_path, r.path_ordinal, r.ordinal, left(p.body_text, 90) AS lead, left(r.body_text, 110) AS t "
                                  "FROM cfr_records r JOIN cfr_records p ON p.section_number = r.section_number AND p.paragraph_path = r.paragraph_path AND p.path_ordinal = 0 "
                                  "WHERE r.paragraph_path <> '' AND r.path_ordinal > 0 ORDER BY r.section_number LIMIT 12"),
      "designated_po_lead_colon": q("SELECT count(*) AS n FROM cfr_records r JOIN cfr_records p ON p.section_number = r.section_number AND p.paragraph_path = r.paragraph_path "
                                    "AND p.path_ordinal = 0 WHERE r.paragraph_path <> '' AND r.path_ordinal = 1 AND rtrim(p.body_text) LIKE '%%:'")[0],
      "ordinal_contiguous_sample": q("SELECT section_number, array_agg(ordinal ORDER BY ordinal) AS ords FROM cfr_records WHERE section_number IN ('740.11','701.3','1.1102') GROUP BY 1"),
      "embedding_null": q("SELECT count(*) FILTER (WHERE embedding IS NULL) AS null_emb, count(*) AS n FROM cfr_records")[0],
      "affected_hash_rule": q("SELECT section_number, paragraph_path, content_sha256 = encode(sha256(convert_to(body_text, 'UTF8')), 'hex') AS sha_is_body, "
                              "embedding_source_sha256 = content_sha256 AS emb_src_is_content, embedding_model, source_payload_sha256 "
                              "FROM cfr_records WHERE (section_number, paragraph_path) IN (('740.11','(a)(1)'),('740.11','(b)(1)'),('740.12','(b)'),('701.3','(c)(2)(i)(a)'),"
                              "('701.3','(c)(2)(i)(b)'),('701.3','(c)(2)(i)(c)'),('701.13','(n)'))"),
      "payload_sha_by_part": q("SELECT part_number, count(DISTINCT source_payload_sha256) AS n, min(source_payload_sha256) AS sha FROM cfr_records "
                               "WHERE part_number IN ('701','740','71','73','74','81') GROUP BY 1"),
      "non_body_hash_examples": q("SELECT section_number, paragraph_path, left(body_text, 80) AS t FROM cfr_records "
                                  "WHERE content_sha256 <> encode(sha256(convert_to(body_text, 'UTF8')), 'hex') LIMIT 5"),
      "sections_740_701_rows": q("SELECT section_number, paragraph_path, path_ordinal, ordinal, length(body_text) AS chars FROM cfr_records "
                                 "WHERE section_number IN ('740.11','740.12','701.13') ORDER BY section_number, ordinal"),
    }
    fp1 = RB.database_fingerprint(db)
    out["database_unchanged"] = all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters"))
finally:
    db.close()
OUT.write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, default=str, ensure_ascii=False)[:9000])
