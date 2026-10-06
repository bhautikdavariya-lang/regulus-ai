"""SFT dataset construction, step 1b: verify the absence a false-premise answer depends on.

A negative-control example teaches the model to correct a premise. The ideal answer may only say a
provision, requirement or guidance document does not exist if that absence has actually been checked
against the read-only snapshot - otherwise the dataset is asserting a negative on faith, which is
the same fault it is meant to correct.

Each check below is a query over the snapshot; the result (including a count of zero) becomes part
of that example's evidence block. Read-only: SELECT only, no model, no inference.

    .venv/bin/python scripts/sft_absence_checks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.retrieval.db import Database  # noqa: E402

# question id -> list of (label, sql, params). Each query states the thing the ideal answer asserts.
CHECKS: dict[str, list[tuple[str, str, dict]]] = {
    "NC-003": [
        ("subparts of 21 CFR Part 820 in the snapshot",
         "SELECT designation, title FROM cfr_subparts WHERE part_number = '820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
        ("reserved section ranges of Part 820",
         "SELECT number FROM cfr_sections WHERE part_number='820' AND is_reserved ORDER BY number", {}),
    ],
    "NC-004": [
        ("Part 211 paragraphs mentioning a Chief Quality Officer",
         "SELECT section_number FROM cfr_records WHERE part_number='211' AND removed_on IS NULL"
         "  AND body_text ILIKE '%chief quality officer%'", {}),
        ("the provision that does govern batch record review",
         "SELECT section_number, paragraph_path, body_text FROM cfr_records"
         "  WHERE section_number='211.192' AND removed_on IS NULL ORDER BY ordinal", {}),
    ],
    "NC-006": [
        ("Part 820 paragraphs imposing a numeric limit on open CAPAs",
         "SELECT section_number FROM cfr_records WHERE part_number='820' AND removed_on IS NULL"
         "  AND (body_text ILIKE '%corrective and preventive action%' OR body_text ILIKE '%CAPA%')", {}),
        ("live sections of Part 820 (the whole of the QMSR)",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "NC-007": [
        ("Part 111 paragraphs requiring third-party or accredited certification",
         "SELECT section_number FROM cfr_records WHERE part_number='111' AND removed_on IS NULL"
         "  AND (body_text ILIKE '%third-party certification%' OR body_text ILIKE '%accredited certification%'"
         "       OR body_text ILIKE '%certification body%')", {}),
    ],
    "NC-008": [
        ("Part 111 paragraphs setting a maximum shelf life or mandatory expiration date",
         "SELECT section_number, left(body_text, 160) AS snippet FROM cfr_records"
         "  WHERE part_number='111' AND removed_on IS NULL"
         "  AND (body_text ILIKE '%shelf life%' OR body_text ILIKE '%expiration date%')", {}),
    ],
    "NC-010": [
        ("Part 11 paragraphs mentioning biometrics",
         "SELECT section_number, paragraph_path, body_text FROM cfr_records"
         "  WHERE part_number='11' AND removed_on IS NULL AND body_text ILIKE '%biometric%' ORDER BY section_number, ordinal", {}),
    ],
    "NC-012": [
        ("any CFR paragraph establishing a 'Green Facility' certification programme",
         "SELECT section_number FROM cfr_records WHERE removed_on IS NULL AND body_text ILIKE '%green facility%'", {}),
    ],
    "NC-015": [
        ("FDA guidance documents on artificial intelligence in dietary supplement manufacturing",
         "SELECT title, issued_on, status FROM fda_guidance"
         "  WHERE title ILIKE '%artificial intelligence%' AND (title ILIKE '%dietary%' OR title ILIKE '%supplement%')", {}),
        ("FDA guidance documents whose title mentions artificial intelligence at all",
         "SELECT title, issued_on, status FROM fda_guidance WHERE title ILIKE '%artificial intelligence%' LIMIT 20", {}),
    ],
    "PB-008": [
        ("reserved section ranges of Part 820",
         "SELECT number FROM cfr_sections WHERE part_number='820' AND is_reserved ORDER BY number", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "PB-001": [
        ("any Title 21 paragraph on greenhouse gas emissions reporting",
         "SELECT section_number FROM cfr_records WHERE removed_on IS NULL"
         "  AND (body_text ILIKE '%greenhouse gas%' OR body_text ILIKE '%emissions reporting%')", {}),
    ],
    "SD-013": [
        ("Part 820 paragraphs requiring a certificate or certification",
         "SELECT section_number, paragraph_path, left(body_text,160) AS snippet FROM cfr_records"
         "  WHERE part_number='820' AND removed_on IS NULL AND body_text ILIKE '%certificat%'", {}),
        ("any Title 21 paragraph mentioning MDSAP",
         "SELECT section_number FROM cfr_records WHERE removed_on IS NULL AND body_text ILIKE '%MDSAP%'", {}),
    ],
    "M-031": [
        ("live rows for 820.30 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.30' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-032": [
        ("live rows for 820.100 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.100' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-033": [
        ("live rows for 820.198 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.198' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-034": [
        ("live rows for 820.181 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.181' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "PB-004": [
        ("FDA guidance on shelf-life or stability testing for dietary supplements",
         "SELECT title, status, issued_on FROM fda_guidance"
         "  WHERE (title ILIKE '%shelf%' OR title ILIKE '%stability%')"
         "    AND (title ILIKE '%supplement%' OR title ILIKE '%dietary%')", {}),
        ("Part 111 paragraphs requiring shelf-life testing",
         "SELECT section_number, left(body_text,160) AS snippet FROM cfr_records"
         "  WHERE part_number='111' AND removed_on IS NULL AND body_text ILIKE '%shelf life%'", {}),
    ],
    "PB-003": [
        ("FDA guidance listing harmful and potentially harmful constituents",
         "SELECT title, status, issued_on FROM fda_guidance WHERE title ILIKE '%harmful%'", {}),
        ("Title 21 paragraphs listing harmful or potentially harmful constituents",
         "SELECT section_number FROM cfr_records WHERE removed_on IS NULL"
         "  AND body_text ILIKE '%potentially harmful constituent%'", {}),
    ],
    "M-035": [
        ("live rows for 820.20 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.20' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-036": [
        ("live rows for 820.22 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.22' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-037": [
        ("live rows for 820.50 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.50' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-038": [
        ("live rows for 820.75 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.75' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-039": [
        ("live rows for 820.72 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.72' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "M-040": [
        ("live rows for 820.250 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.250' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "NC-005": [
        ("live rows for 820.20 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.20' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "NC-011": [
        ("live rows for 820.30 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.30' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "NC-016": [
        ("live rows for 820.30 in the snapshot",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.30' AND removed_on IS NULL", {}),
        ("subparts of 21 CFR Part 820",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='820' ORDER BY designation", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "NC-001": [
        ("live rows for 21 CFR 111.900",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='111.900' AND removed_on IS NULL", {}),
        ("highest-numbered live sections of Part 111",
         "SELECT number, heading FROM cfr_sections WHERE part_number='111' AND NOT is_reserved"
         "  ORDER BY (split_part(number,'.',2))::int DESC LIMIT 6", {}),
    ],
    "NC-002": [
        ("live rows for 21 CFR 117.999",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='117.999' AND removed_on IS NULL", {}),
        ("Part 117 subpart G sections, which do carry supply-chain records requirements",
         "SELECT number, heading FROM cfr_sections WHERE part_number='117'"
         "  AND number IN ('117.405','117.410','117.415','117.420','117.425','117.430','117.435','117.475')"
         "  ORDER BY number", {}),
    ],
    "NC-013": [
        ("subparts of 21 CFR Part 1250",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='1250' ORDER BY designation", {}),
        ("live sections of Part 1250",
         "SELECT number, heading FROM cfr_sections WHERE part_number='1250' AND NOT is_reserved ORDER BY number LIMIT 12", {}),
    ],
    "NC-014": [
        ("Part 101 paragraphs mentioning a QR code or two-dimensional barcode",
         "SELECT section_number FROM cfr_records WHERE part_number='101' AND removed_on IS NULL"
         "  AND (body_text ILIKE '%QR code%' OR body_text ILIKE '%two-dimensional barcode%'"
         "       OR body_text ILIKE '%quick response code%')", {}),
        ("live paragraphs of 101.9(k)",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='101.9' AND removed_on IS NULL"
         "  AND paragraph_path LIKE '(k)%' ORDER BY ordinal", {}),
    ],
    "NC-017": [
        ("live rows for 21 CFR 820.15",
         "SELECT paragraph_path FROM cfr_records WHERE section_number='820.15' AND removed_on IS NULL", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "NC-018": [
        ("subparts of 21 CFR Part 830",
         "SELECT designation, title FROM cfr_subparts WHERE part_number='830' ORDER BY designation", {}),
    ],
    "NC-019": [
        ("Part 820 paragraphs setting a nonconformance threshold or an FDA notification trigger by count",
         "SELECT section_number FROM cfr_records WHERE part_number='820' AND removed_on IS NULL"
         "  AND (body_text ILIKE '%nonconform%' OR body_text ILIKE '%maximum number%')", {}),
        ("live sections of Part 820",
         "SELECT number, heading FROM cfr_sections WHERE part_number='820' AND NOT is_reserved ORDER BY number", {}),
    ],
    "NC-020": [
        ("Part 4 paragraphs requiring certification",
         "SELECT section_number, paragraph_path FROM cfr_records WHERE part_number='4' AND removed_on IS NULL"
         "  AND body_text ILIKE '%certificat%'", {}),
        ("Part 820 paragraphs requiring certification",
         "SELECT section_number FROM cfr_records WHERE part_number='820' AND removed_on IS NULL"
         "  AND body_text ILIKE '%certificat%'", {}),
    ],
    "NC-021": [
        ("Title 21 paragraphs referring to any ISO 13485 Clause 9",
         "SELECT section_number, paragraph_path FROM cfr_records WHERE removed_on IS NULL"
         "  AND body_text ILIKE '%Clause 9%'", {}),
        ("what 820.7 incorporates, and for which sections",
         "SELECT paragraph_path, body_text FROM cfr_records WHERE section_number='820.7'"
         "  AND removed_on IS NULL ORDER BY ordinal", {}),
    ],
    "NC-022": [
        ("FDA guidance on QMSR certification body accreditation",
         "SELECT title, status, issued_on FROM fda_guidance"
         "  WHERE title ILIKE '%QMSR%' OR (title ILIKE '%certification body%')"
         "     OR (title ILIKE '%accreditation%' AND title ILIKE '%quality%')", {}),
        ("FDA guidance issued in March 2026",
         "SELECT title, status, issued_on FROM fda_guidance WHERE issued_on >= '2026-03-01'"
         "  AND issued_on < '2026-04-01' LIMIT 10", {}),
    ],
    "PB-006": [
        ("Title 21 paragraphs incorporating or referring to ISO 14971",
         "SELECT section_number, paragraph_path FROM cfr_records WHERE removed_on IS NULL"
         "  AND body_text ILIKE '%14971%'", {}),
        ("what 820.7 does incorporate, and for which sections",
         "SELECT paragraph_path, body_text FROM cfr_records WHERE section_number='820.7'"
         "  AND removed_on IS NULL ORDER BY ordinal", {}),
    ],
    "PB-007": [
        ("record retention periods differ by part: a sample of retention provisions across Title 21",
         "SELECT section_number, left(body_text, 150) AS snippet FROM cfr_records"
         "  WHERE removed_on IS NULL AND body_text ILIKE '%retain%'"
         "    AND (body_text ILIKE '%1 year%' OR body_text ILIKE '%2 years%' OR body_text ILIKE '%3 years%'"
         "         OR body_text ILIKE '%10 years%')"
         "    AND section_number IN ('111.605','117.315','211.180','803.18','806.20','606.160','1.1455')"
         "  ORDER BY section_number", {}),
    ],
    "SD-003": [
        ("any Title 21 paragraph that is a USDA FSIS meat labeling requirement",
         "SELECT section_number FROM cfr_records WHERE removed_on IS NULL AND body_text ILIKE '%FSIS%'", {}),
    ],
}


def main() -> int:
    db = Database.from_env()
    db.connect()
    out = {}
    for qid, checks in CHECKS.items():
        results = []
        for label, sql, params in checks:
            rows = db.query(sql, params or None)   # None: no placeholder parsing, so ILIKE % patterns are literal
            results.append({"check": label, "row_count": len(rows),
                            "rows": [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in rows[:30]]})
            print(f"{qid:8} {len(rows):4} rows  {label}")
        out[qid] = results
    path = ROOT / "artifacts/sft/absence_checks.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
