"""SFT dataset construction, step 1: select the source questions and assemble their evidence.

Dataset construction only - no model is loaded, no inference is run, nothing is trained.

Selection draws on what the measurement phases established rather than on the benchmark as a whole:
the highest-value training rows are the ones where the system **had the governing provision and
still answered wrongly** (Stage A `MODEL_ANSWER / governing_section_supplied`), plus the trap rows
that need no provision at all (`no_governing_section_required`), plus every Temporal/Version row,
because temporal reasoning is a named target failure mode and those rows mostly fell into
EVIDENCE_SUPPLY for a different reason.

Quotas keep the set balanced by benchmark category, and a per-CFR-part cap stops Part 820 - which
is 28 of the 141 priority rows - from dominating. Within a stratum, rows are taken in a deterministic
priority order: more key answer elements first, then multi-section keys, then benchmark id.

For each selected question the governing sections' paragraphs are read verbatim from the read-only
snapshot. That text is the only regulatory material an ideal answer may rest on.

    .venv/bin/python scripts/sft_select.py            # writes artifacts/sft/selection.json + evidence.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.retrieval.db import Database  # noqa: E402

SECTION_RE = re.compile(r"(\d{1,4})\.(\d+)")

# benchmark category -> how many examples to build. Chosen so the reasoning categories, which score
# 0 passes in the baseline, are represented far above their share of the 300-question bank.
QUOTAS = {
    "Direct Lookup": 18,
    "Cross-Reference": 8,
    "Distinction": 8,
    "Application": 7,
    "Scope/Boundary": 7,
    "Negative Control": 8,
    "Temporal/Version": 5,
    "Abstention": 1,
}
PART_CAP = 8          # at most this many selected questions per CFR part...
# ...except that the cap is counted per (part, category). Every Temporal/Version row in the bank is
# a Part 820 reserved-section trap, so a flat per-part cap silently excluded the whole category -
# which is a named target failure mode. Counting per (part, category) keeps Part 820 from dominating
# the ordinary lookups while still admitting the temporal reasoning rows, which are a structurally
# different question, not another instance of the same template.
TEMPORAL_PART_ALLOWANCE = 4

# Sections added to an example's evidence block beyond the benchmark's own key, because a required
# answer element lives there. The rule the dataset is built on is that an ideal answer may rest only
# on text present in that example's evidence, so where an element needs another provision, that
# provision is supplied rather than the element dropped or written from memory. Added as the need is
# found while authoring, and recorded separately from the keyed sections so the addition is visible.
EXTRA_SECTIONS: dict[str, list[str]] = {
    "M-001": ["820.10"],    # the QMS duty the key element names sits in 820.10, not 820.1
    "F-012": ["117.165"],   # calibration, product testing and environmental monitoring are here
    # these three rows carry a part- or subpart-level key, so there is no section to assemble from it
    "Z-004": ["1003.10", "1003.20", "1003.21", "1004.1", "1004.2", "1004.3", "1004.4"],
    "F-022": ["117.405", "1.502", "1.504"],
    "SD-010": ["4.1", "4.3", "4.4"],
    "M-042": ["807.20", "830.20"],   # the registration/listing and UDI anchors the question asks for
    # added after the A1 audit showed the ideal answer resting on provisions outside its evidence
    "R-006": ["806.1"],              # the exemptions themselves live in 806.1(b), not 806.10/806.20
    "E-010": ["11.1"],               # the scope provision the answer opens from
    "SD-005": ["7.3", "7.41", "7.46"],  # the Part 7 provisions offered in place of a legal opinion
}

# Guidance documents an example's ideal answer quotes. Guidance is non-binding and is never the
# source of a requirement, but where an answer reports what a guidance document says, that text
# must be in the evidence like any other source. Keyed by docket number; only the chunks that
# mention enforcement discretion or the predicate-rule relationship are attached.
EXTRA_GUIDANCE: dict[str, list[str]] = {
    "E-010": ["FDA-2003-D-0143"],   # Part 11 Scope and Application (final, 2003-09-05)
}
MAX_PARAGRAPHS = 48   # per governing section. Must be high enough that no required element
                      # is cut off: an ideal answer may only rest on text actually assembled here.


def part_of(text: str) -> str | None:
    m = SECTION_RE.search(text or "")
    return m.group(1) if m else None


def key_sections(row: dict) -> list[str]:
    secs = [s.strip() for s in re.split(r"[;,]", row.get("rev_key_sections") or "") if s.strip()]
    if secs:
        return list(dict.fromkeys(secs))   # a key naming 820.7(a) and 820.7(b) yields 820.7 twice
    return sorted({f"{a}.{b}" for a, b in SECTION_RE.findall(row.get("key_citation_draft") or "")})


def priority(row: dict, attr: dict) -> tuple:
    """Deterministic ordering: harder and more element-rich rows first."""
    elements = len(re.split(r"[;,]", row.get("key_elements") or ""))
    multi = 1 if len(key_sections(row)) > 1 else 0
    had_evidence = 1 if attr.get("subcategory") == "governing_section_supplied" else 0
    advanced = 1 if row.get("difficulty") in ("Advanced", "Trap") else 0
    return (-elements, -multi, -had_evidence, -advanced, row["id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/sft")
    args = ap.parse_args()

    data = {json.loads(l)["id"]: json.loads(l)
            for l in (ROOT / "artifacts/stage_a/dataset.jsonl").read_text().splitlines() if l.strip()}
    attr = {json.loads(l)["id"]: json.loads(l)
            for l in (ROOT / "artifacts/stage_a/attribution_rows.jsonl").read_text().splitlines() if l.strip()}
    es1 = {}
    p = ROOT / "artifacts/stage_b/run_es1.jsonl"
    if p.exists():
        es1 = {json.loads(l)["question_id"]: json.loads(l) for l in p.read_text().splitlines() if l.strip()}

    # candidate pool
    candidates = []
    for qid, row in data.items():
        a = attr[qid]
        eligible = (a["category"] == "MODEL_ANSWER") or (row["type"] == "Temporal/Version")
        if not eligible or row["result"] == "ERROR":
            continue
        candidates.append(qid)

    by_cat: dict[str, list[str]] = defaultdict(list)
    for qid in candidates:
        by_cat[data[qid]["type"]].append(qid)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda q: priority(data[q], attr[q]))

    selected, part_count = [], Counter()
    skipped_for_part_cap = []
    for cat, quota in QUOTAS.items():
        taken = 0
        for qid in by_cat.get(cat, []):
            if taken >= quota:
                break
            keys = key_sections(data[qid])
            pt = part_of(keys[0]) if keys else None
            if pt:
                bucket = (pt, "temporal") if cat == "Temporal/Version" else (pt, "other")
                cap = TEMPORAL_PART_ALLOWANCE if cat == "Temporal/Version" else PART_CAP
                if part_count[bucket] >= cap:
                    skipped_for_part_cap.append(qid)
                    continue
                part_count[bucket] += 1
            selected.append(qid)
            taken += 1

    # assemble the verbatim provision text for every selected question
    db = Database.from_env()
    db.connect()
    records = []
    for qid in selected:
        row, a = data[qid], attr[qid]
        keys = key_sections(row)
        extras = [s for s in EXTRA_SECTIONS.get(qid, []) if s not in keys]
        provisions = []
        for sec in keys + extras:
            rows = db.query(
                "SELECT paragraph_path, body_text, is_reserved, section_heading"
                "  FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL"
                "  ORDER BY ordinal LIMIT %(n)s", {"s": sec, "n": MAX_PARAGRAPHS})
            provisions.append({
                "section": sec,
                "heading": rows[0]["section_heading"] if rows else None,
                "reserved": bool(rows and rows[0]["is_reserved"]),
                "paragraph_count": len(rows),
                "paragraphs": [{"path": r["paragraph_path"] or "—", "text": (r["body_text"] or "").strip()}
                               for r in rows],
            })
        guidance = []
        for docket in EXTRA_GUIDANCE.get(qid, []):
            meta = db.query("SELECT id, title, status, issued_on, docket_number, disclaimer_text"
                            "  FROM fda_guidance WHERE docket_number = %(d)s", {"d": docket})
            for g in meta:
                chunks = db.query(
                    "SELECT ordinal, body_text FROM fda_guidance_chunks"
                    "  WHERE guidance_id = %(g)s AND (body_text ILIKE '%%enforcement discretion%%'"
                    "        OR body_text ILIKE '%%predicate rule%%') ORDER BY ordinal LIMIT 24",
                    {"g": g["id"]})
                guidance.append({
                    "docket_number": g["docket_number"], "title": g["title"], "status": g["status"],
                    "issued_on": str(g["issued_on"]), "disclaimer": g["disclaimer_text"],
                    "chunks": [{"ordinal": c["ordinal"], "text": (c["body_text"] or "").strip()} for c in chunks],
                })

        records.append({
            "id": qid,
            "question": row["question"],
            "type": row["type"],
            "domain": row["domain"],
            "difficulty": row["difficulty"],
            "key_citation_draft": row["key_citation_draft"],
            "key_elements": row["key_elements"],
            "iso_clause_draft": row["iso_clause_draft"],
            "key_sections": keys,
            "supporting_sections": extras,
            "trap_row": row["rev_trap_row"],
            "attribution": a["category"] + "/" + a["subcategory"],
            "baseline_verdict": {"result": row["result"], "L": row["L"], "M": row["M"], "N": row["N"],
                                 "O": row["O"], "P": row["P"], "Q": row["Q"]},
            "baseline_failure_note": row["notes"],
            "baseline_answer": row["answer"],
            "es1_answer": (es1.get(qid) or {}).get("answer"),
            "provisions": provisions,
            "guidance": guidance,
        })

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": "SFT source selection and verbatim evidence assembly - construction only, no inference",
        "selected": len(records),
        "quotas": QUOTAS,
        "part_cap": PART_CAP,
        "by_category": dict(Counter(r["type"] for r in records).most_common()),
        "by_part": dict(Counter(part_of(r["key_sections"][0]) if r["key_sections"] else "none"
                                for r in records).most_common()),
        "temporal_part_allowance": TEMPORAL_PART_ALLOWANCE,
        "by_difficulty": dict(Counter(r["difficulty"] for r in records).most_common()),
        "by_attribution": dict(Counter(r["attribution"] for r in records).most_common()),
        "skipped_for_part_cap": skipped_for_part_cap,
        "candidate_pool": len(candidates),
    }
    (args.out / "selection.json").write_text(json.dumps({"manifest": manifest, "records": records}, indent=2) + "\n")

    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
