"""ASSISTED REVIEW — NOT VERIFIED.

Offline evidence gathering for the assisted (non-authoritative) review of the
300-question acceptance benchmark. Read-only: it opens the benchmark through
the project loader, the frozen verification run, and the eCFR snapshot over a
connection it refuses to use unless the server reports it read-only.

It writes nothing outside this package directory. It never writes to the
workbook, to artifacts/benchmark_keys, or to any decision/sign-off/locked-key
file. No ISO 13485 text is available in this system (iso_clauses.body_text is
empty for all rows) and nothing here attempts to obtain any.

    python -u tools/gather_evidence.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
ROOT = PKG.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark  # noqa: E402
from regulus.evaluation.key_verification import DatabaseSources  # noqa: E402
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.references import parse_cfr_references  # noqa: E402

OUT = PKG / "evidence"
EXPECTED_SHA = "c009d5f9c649822097b02a6c6aba415715fb0929914ef452acb03c8c3ac4a110"
SECTION_CHAR_CAP = 80000
LABEL = "ASSISTED REVIEW — NOT VERIFIED. Evidence only; not an SME decision; never consumed by scoring or training."

SECTION_RE = re.compile(r"\b(\d{1,4})\.(\d{1,4}[a-z]?)\b")


def db_open() -> tuple[Database, DatabaseSources]:
    db = Database.from_env()
    db.connect()
    if str(db.status().get("default_transaction_read_only", "")).lower() not in ("on", "true", "1"):
        raise SystemExit("refusing: database connection is not read-only")
    return db, DatabaseSources(db)


def section_meta(db, section: str) -> dict:
    rows = db.query(
        """SELECT section_heading, min(effective_date)::text eff, max(last_amended_date)::text amended,
                  max(fr_citation) fr, bool_or(is_reserved) reserved, count(*) n,
                  count(*) FILTER (WHERE removed_on IS NULL) live, max(ecfr_permalink) link,
                  max(part_number) part, (array_agg(subpart_id))[1]::text subpart_id
           FROM cfr_records WHERE section_number = %(s)s GROUP BY section_heading""",
        {"s": section},
    )
    return rows[0] if rows else {}


def section_text(db, section: str, paragraph: str = "") -> dict:
    sql = """SELECT paragraph_path, body_text FROM cfr_records
             WHERE section_number = %(s)s AND removed_on IS NULL"""
    params = {"s": section}
    if paragraph:
        sql += " AND (paragraph_path = %(p)s OR paragraph_path LIKE %(pre)s)"
        params.update({"p": paragraph, "pre": paragraph + "(%"})
    sql += " ORDER BY path_ordinal, ordinal"
    parts, used, truncated = [], 0, False
    for r in db.query(sql, params):
        line = f"{r['paragraph_path'] or '(section)'} {' '.join((r['body_text'] or '').split())}"
        if used + len(line) > SECTION_CHAR_CAP:
            truncated = True
            break
        parts.append(line)
        used += len(line)
    return {"text": "\n".join(parts), "truncated": truncated}


def sections_between(db, part: str, lo: str, hi: str) -> list[dict]:
    def num(s):
        m = re.match(r"\d+\.(\d+)", s)
        return int(m.group(1)) if m else None
    a, b = num(lo), num(hi)
    rows = db.query(
        """SELECT DISTINCT section_number, section_heading, bool_or(is_reserved) OVER (PARTITION BY section_number) r
           FROM cfr_records WHERE part_number = %(p)s AND removed_on IS NULL""", {"p": part})
    out = {}
    for r in rows:
        n = num(str(r["section_number"]))
        if n is not None and a is not None and b is not None and a <= n <= b:
            out[r["section_number"]] = {"section": r["section_number"], "heading": r["section_heading"], "reserved": r["r"]}
    return sorted(out.values(), key=lambda x: num(x["section"]))


def subpart_listing(db, part: str) -> list[dict]:
    return db.query(
        """SELECT designation, title FROM cfr_subparts WHERE part_number = %(p)s ORDER BY sort_order""", {"p": part})


def part_sections(db, part: str) -> list[dict]:
    return db.query(
        """SELECT r.section_number, max(r.section_heading) heading, bool_or(r.is_reserved) reserved,
                  max(s.designation) subpart
           FROM cfr_records r LEFT JOIN cfr_subparts s ON s.id = r.subpart_id
           WHERE r.part_number = %(p)s AND r.removed_on IS NULL
           GROUP BY r.section_number ORDER BY min(r.path_ordinal), r.section_number""", {"p": part})


def sibling_sections(db, section: str) -> list[dict]:
    return db.query(
        """SELECT DISTINCT r2.section_number, r2.section_heading FROM cfr_records r1
           JOIN cfr_records r2 ON r2.subpart_id = r1.subpart_id AND r2.removed_on IS NULL
           WHERE r1.section_number = %(s)s AND r1.subpart_id IS NOT NULL
           ORDER BY r2.section_number LIMIT 80""", {"s": section})


def outgoing_refs(db, section: str) -> list[str]:
    rows = db.query(
        """SELECT DISTINCT x.target_citation FROM cfr_cross_references x
           JOIN cfr_records r ON r.id = x.from_record_id
           WHERE r.section_number = %(s)s AND r.removed_on IS NULL ORDER BY 1 LIMIT 40""", {"s": section})
    return [r["target_citation"] for r in rows]


def search_terms(db, part: str | None, terms: list[str], limit: int = 12) -> dict:
    hits = {}
    for t in terms:
        sql = """SELECT section_number, paragraph_path, left(body_text, 260) snippet FROM cfr_records
                 WHERE removed_on IS NULL AND body_text ILIKE %(t)s"""
        params = {"t": f"%{t}%"}
        if part:
            sql += " AND part_number = %(p)s"
            params["p"] = part
        sql += f" ORDER BY section_number, path_ordinal LIMIT {limit}"
        rows = db.query(sql, params)
        count = db.query(
            "SELECT count(*) n FROM cfr_records WHERE removed_on IS NULL AND body_text ILIKE %(t)s"
            + (" AND part_number = %(p)s" if part else ""), params)[0]["n"]
        hits[t] = {"total_matching_records": int(count),
                   "sample": [{"cite": f"{r['section_number']}{r['paragraph_path'] or ''}",
                               "snippet": " ".join((r["snippet"] or "").split())} for r in rows]}
    return {"scope": f"21 CFR part {part}" if part else "all of Title 21 in the snapshot", "terms": hits}


def guidance_search(db, terms: list[str]) -> dict:
    out = {}
    for t in terms:
        rows = db.query(
            """SELECT title, issued_on::text issued, status, center FROM fda_guidance
               WHERE title ILIKE %(t)s ORDER BY issued_on DESC NULLS LAST LIMIT 10""", {"t": f"%{t}%"})
        body = db.query("SELECT count(*) n FROM fda_guidance WHERE body_text ILIKE %(t)s", {"t": f"%{t}%"})[0]["n"]
        out[t] = {"title_matches": rows, "body_text_matches": int(body)}
    meta = db.query("SELECT count(*) n, min(issued_on)::text lo, max(issued_on)::text hi, max(retrieved_at)::text got FROM fda_guidance")[0]
    return {"guidance_table": meta,
            "caveat": "The fda_guidance table's coverage has not been assessed; no hit here is not proof the guidance does not exist.",
            "terms": out}


# Targeted absence / temporal / scope searches, written per row after reading the
# question. Terms include synonyms so a requirement worded differently can surface.
TARGETED: dict[str, list[tuple]] = {
    "NC-001": [("exists", "111.900"), ("part_sections", "111")],
    "NC-002": [("exists", "117.999"), ("subparts", "117"), ("part_sections", "117")],
    "NC-003": [("subparts", "820"), ("part_sections", "820")],
    "NC-004": [("search", "211", ["chief quality", "quality officer", "personally sign", "sign", "signature", "quality control unit"]),
               ("text", "211.192", ""), ("text", "211.188", ""), ("text", "211.186", ""), ("text", "211.22", "")],
    "NC-005": [("part_text", "820"), ("search", "820", ["management review", "quarter", "interval", "frequen"])],
    "NC-006": [("part_text", "820"), ("search", "820", ["corrective", "preventive", "maximum", "limit", "number of"]),
               ("search", None, ["open CAPA", "maximum number of corrective"])],
    "NC-007": [("search", "111", ["third-party", "third party", "certif", "accredit", "audit"]),
               ("search", None, ["third-party certification", "GMP certification"])],
    "NC-008": [("search", "111", ["shelf life", "shelf-life", "expiration", "expiry", "stability"]),
               ("search", "101", ["shelf life", "expiration date"]),
               ("search", None, ["maximum shelf life", "shelf life"])],
    "NC-009": [("text", "1.505", ""), ("text", "1.506", ""), ("search", "1", ["every 6 months", "six months", "every 3 years", "three years", "reevaluat", "re-evaluat"])],
    "NC-010": [("search", "11", ["biometric", "password", "identification code"]), ("text", "11.200", ""), ("text", "11.300", ""), ("text", "11.100", "")],
    "NC-011": [("part_text", "820"), ("search", "820", ["design review", "design and development", "review"])],
    "NC-012": [("search", None, ["green facility", "Green Facility"]), ("search", "111", ["green", "environmental", "certif"]),
               ("guidance", ["green facility", "green"])],
    "NC-013": [("subparts", "1250"), ("part_sections", "1250")],
    "NC-014": [("text", "101.9", "(k)"), ("search", "101", ["QR", "quick response", "machine-readable", "scannable", "bar code"])],
    "NC-015": [("guidance", ["artificial intelligence", "AI ", "machine learning", "dietary supplement manufacturing"])],
    "NC-016": [("exists", "820.30"), ("part_sections", "820")],
    "NC-017": [("exists", "820.15"), ("part_sections", "820")],
    "NC-018": [("subparts", "830"), ("part_sections", "830")],
    "NC-019": [("part_text", "820"), ("search", "820", ["nonconform", "notif", "per lot", "threshold"]),
               ("search", None, ["nonconformances per lot", "nonconforming product"])],
    "NC-020": [("part_text", "4"), ("search", "4", ["13485", "certif"]), ("search", "820", ["certif", "13485"])],
    "NC-021": [("iso_index", None)],
    "NC-022": [("guidance", ["certification body", "accreditation", "QMSR", "quality management system regulation"]),
               ("search", "820", ["certification body", "accreditation"])],
    "PB-001": [("search", None, ["greenhouse", "emission"]), ("guidance", ["greenhouse"])],
    "PB-006": [("search", None, ["14971", "risk management"]), ("text", "820.7", ""), ("text", "820.10", "")],
    "PB-007": [("search", None, ["retained for", "record retention", "retain records"])],
    "PB-008": [("subparts", "820"), ("part_sections", "820")],
    "SD-010": [("part_text", "4")],
    "SD-011": [("text", "820.10", ""), ("search", "820", ["certif", "notified body", "MDSAP"])],
    "SD-012": [("text", "820.10", ""), ("iso_index", "7.3")],
    "SD-013": [("search", "820", ["MDSAP", "certif", "audit"])],
    "X-004": [("part_sections", "4"), ("part_text", "4"), ("subparts", "4")],
}


def run_targeted(db, sources, qid: str) -> list[dict]:
    out = []
    for spec in TARGETED.get(qid, []):
        kind = spec[0]
        if kind == "exists":
            out.append({"kind": "section_state", "section": spec[1], "state": sources.section_state(spec[1])})
        elif kind == "subparts":
            out.append({"kind": "subpart_structure", "part": spec[1], "subparts": subpart_listing(db, spec[1])})
        elif kind == "part_sections":
            out.append({"kind": "part_section_list", "part": spec[1], "sections": part_sections(db, spec[1])})
        elif kind == "part_text":
            secs = part_sections(db, spec[1])
            out.append({"kind": "whole_part_text", "part": spec[1],
                        "sections": [{"section": s["section_number"], "heading": s["heading"], "reserved": s["reserved"],
                                      **section_text(db, s["section_number"])} for s in secs if "-" not in str(s["section_number"])]})
        elif kind == "search":
            out.append({"kind": "term_search", **search_terms(db, spec[1], spec[2]),
                        "caveat": "A search result is evidence about wording in the snapshot. No hit is consistent with absence; it does not establish it."})
        elif kind == "text":
            out.append({"kind": "provision_text", "section": spec[1], "paragraph": spec[2],
                        "meta": section_meta(db, spec[1]), **section_text(db, spec[1], spec[2])})
        elif kind == "guidance":
            out.append({"kind": "guidance_search", **guidance_search(db, spec[1])})
        elif kind == "iso_index":
            rows = db.query("SELECT clause, clause_title, depth, parent_clause FROM iso_clauses ORDER BY sort_key")
            if spec[1]:
                rows = [r for r in rows if str(r["clause"]).startswith(spec[1])]
            out.append({"kind": "iso_clause_index",
                        "note": "Internal clause index: clause numbers and titles only, no text. It is NOT the controlled standard.",
                        "top_level": sorted({str(r['clause']).split('.')[0] for r in rows}, key=lambda x: (len(x), x)),
                        "clauses": rows})
    return out


def iso_block(db, sources, q) -> dict:
    index = {str(r["clause"]): r["clause_title"] for r in db.query("SELECT clause, clause_title FROM iso_clauses")}
    clauses = list(q.iso_clauses)
    cited = [r.section for r in parse_cfr_references(q.expected_citation_draft) if r.section]
    cited += [f"{m.group(1)}.{m.group(2)}" for m in SECTION_RE.finditer(q.expected_citation_draft) if m.group(1) == "820"]
    cited = list(dict.fromkeys(cited))
    return {
        "draft_clauses": clauses,
        "draft_title_col_I": q.iso_clause_title,
        "clause_index_lookup": {c: index.get(c) for c in clauses},
        "crosswalk_by_cited_section": {s: sources.crosswalk(s) for s in cited},
        "iso_text_available": False,
        "weight": ("Crosswalk = internal project mapping at SECTION granularity, not authority. Clause index = "
                   "identity/title only. What a clause requires is only in the controlled ISO 13485:2016(E), "
                   "which is not held in this system."),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    workbook = ROOT / DEFAULT_WORKBOOK
    sha = hashlib.sha256(workbook.read_bytes()).hexdigest()
    if sha != EXPECTED_SHA:
        raise SystemExit(f"workbook hash {sha} is not the expected {EXPECTED_SHA}; refusing")
    bench = load_acceptance_benchmark(str(workbook))
    ver_path = sorted((ROOT / "artifacts" / "benchmark_verification").glob("*/verification.json"))[-1]
    ver = json.loads(ver_path.read_text(encoding="utf-8"))
    vrows = {r["question_id"]: r for r in ver["rows"]}
    db, sources = db_open()
    OUT.mkdir(parents=True, exist_ok=True)

    records = []
    for i, q in enumerate(bench.questions, 1):
        refs = parse_cfr_references(q.expected_citation_draft)
        cited = []
        seen = set()
        for ref in refs:
            if ref.section is None or (ref.section, ref.paragraph_path) in seen:
                continue
            seen.add((ref.section, ref.paragraph_path))
            meta = section_meta(db, ref.section)
            cited.append({
                "citation": ref.canonical, "section": ref.section, "paragraph": ref.paragraph_path,
                "state": sources.section_state(ref.section),
                "paragraph_exists": sources.paragraph_exists(ref.section, ref.paragraph_path) if ref.paragraph_path else None,
                "heading": meta.get("section_heading"), "effective_date": meta.get("eff"),
                "last_amended": meta.get("amended"), "fr_citation": meta.get("fr"),
                "provision": section_text(db, ref.section, ref.paragraph_path),
                "whole_section": section_text(db, ref.section) if ref.paragraph_path else None,
                "outgoing_cross_references": outgoing_refs(db, ref.section),
                "same_subpart_sections": sibling_sections(db, ref.section),
            })
        # Section ranges ("4.100 through 4.110") are only parsed to endpoints; expand them here.
        ranges = []
        for m in re.finditer(r"(\d+)\.(\d+)\s*(?:through|to|thru|[-–—])\s*(?:\1\.)?(\d+)\b", q.expected_citation_draft):
            part = m.group(1)
            lo, hi = f"{part}.{m.group(2)}", f"{part}.{m.group(3)}"
            ranges.append({"range": m.group(0), "part": part, "sections_present_in_snapshot": sections_between(db, part, lo, hi),
                           "endpoint_states": {lo: sources.section_state(lo), hi: sources.section_state(hi)}})
        # Sections named in the question and in column J, existence only (J is not evidence of correctness).
        mentioned = {}
        for field, text in (("question_F", q.question), ("key_elements_J", q.key_answer_elements)):
            for ref in parse_cfr_references(text):
                if ref.section and ref.section not in mentioned:
                    mentioned[ref.section] = {"from": field, "state": sources.section_state(ref.section),
                                              "heading": section_meta(db, ref.section).get("section_heading")}
        rec = {
            "_label": LABEL,
            "question_id": q.question_id, "row": q.row, "domain": q.domain, "focus": q.focus,
            "question_type": q.question_type, "difficulty": q.difficulty,
            "question": q.question, "draft_citation_G": q.expected_citation_draft,
            "draft_iso_H": q.iso_clause_draft, "iso_title_I": q.iso_clause_title,
            "key_answer_elements_J": q.key_answer_elements,
            "automated": {"state": vrows[q.question_id]["verification_status"],
                          "findings": [{"dimension": f["dimension"], "status": f["status"], "detail": f["detail"]}
                                       for f in vrows[q.question_id]["findings"] if f["status"] != "NOT_APPLICABLE"]},
            "cited_provisions": cited,
            "section_ranges": ranges,
            "sections_mentioned_in_question_or_J": mentioned,
            "iso": iso_block(db, sources, q) if q.in_g7_scope else None,
            "targeted": run_targeted(db, sources, q.question_id),
        }
        records.append(rec)
        print(f"[{i:3}/300] {q.question_id:7} cited={len(cited)} ranges={len(ranges)} targeted={len(rec['targeted'])}")

    meta = {"_label": LABEL, "workbook_sha256": sha, "benchmark_key": bench.benchmark_key,
            "verification_run": ver_path.parent.name, "sources": sources.describe(), "rows": len(records)}
    (OUT / "evidence_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    with (OUT / "evidence_all.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(f"wrote {len(records)} evidence records to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
