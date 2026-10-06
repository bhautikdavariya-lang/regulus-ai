"""SFT dataset v2, step 1: select over the full 300-question benchmark and pack production-sized evidence.

Dataset construction only - no model is loaded, no inference is run, nothing is trained.

Two changes from v1:

1. **Source universe is all 300 questions**, not the 150-row Stage A priority pool. Every remaining
   Cross-Reference, Application, Distinction, Temporal/Version, Negative Control and Scope/Boundary
   question is taken, because those are the categories that score zero passes in the baseline and
   they are scarce; Direct Lookup is capped per CFR part so it cannot dominate on the strength of
   being easy to construct.

2. **Evidence is packed to a production-realistic budget.** v1 handed whole governing sections to
   the model - up to 19,000 characters against a production prompt budget of 3,600 - which teaches
   reasoning over a context dump rather than over useful evidence. Here each example gets a compact
   package: the section's operative stem, every applicability or exception paragraph, every
   paragraph pinned because the ideal answer cites it, then the most relevant remaining paragraphs
   until the budget is reached, emitted in document order.

   Relevance for *evidence selection* is lexical overlap with the question and the benchmark's key
   answer elements. That is retrieval, which is inherently lexical; it is not used to score answers.

    .venv/bin/python scripts/sft2_select.py
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

SFT = ROOT / "artifacts/sft"
OUT = ROOT / "artifacts/sft2"
SECTION_RE = re.compile(r"(\d{1,4})\.(\d+)")
PARA_CITE_RE = re.compile(r"\b(\d{1,4}\.\d+)((?:\([a-z0-9]+\))+)")

EVIDENCE_BUDGET = 3000        # preferred ceiling for the relevance fill
EVIDENCE_HARD_CEILING = 3600  # production's actual prompt budget; pins may run to here
MIN_PER_SECTION = 2           # paragraphs guaranteed to every governing section
DIRECT_LOOKUP_PART_CAP = 6    # new Direct Lookup examples per CFR part
# categories taken in full from the remaining benchmark, being both scarce and the weakest
TAKE_ALL = ("Cross-Reference", "Application", "Distinction", "Temporal/Version",
            "Negative Control", "Scope/Boundary", "Abstention")
DIRECT_LOOKUP_TARGET = 32   # all reasoning categories are taken in full; Direct Lookup is the slice
                            # that controls total size. Raised from 25 to 32 after ten rows were rejected
                            # on evidence-faithfulness grounds, to keep the admitted set at or above 150

# Paragraphs pinned by hand for an example whose answer has not been written yet, where the lexical
# fill would otherwise miss the paragraph that actually answers the question. Recorded here rather
# than applied silently, so the choice is auditable.
MANUAL_PINS: dict[str, list[tuple[str, str]]] = {
    "NC-009": [("1.505", "(c)(2)")],          # the 3-year reevaluation rule the false premise turns on
    "H-006": [("1.1315", "(a)"), ("1.1320", "(a)"), ("1.1340", "(a)")],
    "U-008": [("801.55", "(a)"), ("801.55", "(b)"), ("801.30", "(a)")],
    # (c)(2) is deliberately not pinned: at 2,060 characters it cannot join (c)(1)'s 1,987 inside
    # the 3,600-character ceiling, so the target states only what the supplied text carries.
    "Y-004": [("108.35", "(c)(1)")],
    "K-009": [("312.32", "(c)(1)"), ("312.32", "(c)(2)"), ("312.23", "(a)(1)")],
    "X-004": [("4.102", "(a)"), ("4.102", "(b)"), ("4.104", "(a)")],
    "S-012": [("111.87", "—"), ("111.75", "(d)(2)")],   # (d)(2) is cited: +133 -> 3,075, fits
    "M-023": [("820.35", "(c)"), ("820.10", "(b)(1)")],
    "L-008": [("101.9", "(b)(12)"), ("101.9", "(b)(12)(i)"), ("101.9", "(b)(12)(i)(A)")],
    "PB-002": [("1114.7", "(g)"), ("1114.7", "(i)")],
    "PB-009": [("820.35", "(a)")],
    "B-003": [("601.2", "(a)"), ("601.2", "(d)")],
    # QA fix: the answers state these paragraphs' content, so the evidence has to carry them. Every
    # addition was measured against the 3,600-character production ceiling before use, and none is
    # allowed to push its row over it:
    #   P-001 807.87(a)-(h) pinned = 2,068 of 3,600; (d), (f) and (g) were the missing items
    #   U-010 2,875 + 287 = 3,162   830.320(c)(2), the deeming rule the answer states
    #   B-001 2,949 + 420 = 3,369   600.10(c)(1) and (c)(2), the personnel restrictions
    #   F-004 2,924 + 315 = 3,239   117.35(e), non-food-contact surfaces
    #   R-007 2,883 + 262 = 3,145   7.41(b), the classification step
    # P-001's answer enumerates 807.87(a) through (h) as a lettered list rather than as repeated
    # "807.87(x)" citations, so the automatic pin derivation never saw those paragraphs and the
    # lexical fill kept evicting one or another of them. They are pinned explicitly: the eight
    # together are 2,068 characters, comfortably inside the 3,600-character ceiling.
    "P-001": [("807.87", c) for c in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)")],
    "U-010": [("830.320", "(c)(2)")],
    "B-001": [("600.10", "(c)"), ("600.10", "(c)(1)"), ("600.10", "(c)(2)")],
    "F-004": [("117.35", "(e)")],
    "R-007": [("7.41", "(b)")],

    "A-004": [("558.6", "(c)(3)"), ("558.6", "(c)(4)"), ("558.6", "(b)(3)")],
    "K-003": [("50.51", "(a)"), ("50.52", "(a)"), ("50.53", "(a)"), ("50.55", "(a)"), ("50.55", "(e)")],
}

# Sections added to a row's evidence where the benchmark key is not a CFR citation but the correct
# answer still has to rest on provision text - a scope refusal that points at the real obligation,
# for instance, must show the provision it points at.
EXTRA_SECTIONS_V2: dict[str, list[str]] = {
    "SD-011": ["820.7", "820.10"],   # the QMSR obligation a certificate does not discharge
    "SD-012": ["820.7", "820.10"],   # identifies the incorporated standard without reproducing it
    "SD-008": ["101.9"],             # the Part 101 requirements an analysis may be offered against
    "A-004": ["225.1", "225.10"],    # the key names Part 225 at part level; these carry the CGMP
    # a key written as a range ("50.50 through 50.56") yields only its endpoints, so the sections
    # in between - which carry the substance - have to be named
    "K-003": ["50.51", "50.52", "50.53", "50.55"],
    "H-006": ["1.1320", "1.1340"],   # the lot-code and shipping records the key elements name
    "U-008": ["801.55"],             # already keyed, listed so the request route is never dropped
    "X-004": ["4.102", "4.103", "4.104"],   # 4.110 is reserved; these carry the reporting duties
    "S-026": ["111.515", "111.520", "111.525"],   # another range key; endpoints alone miss the substance
    "M-023": ["820.10"],             # the assignment duty the record requirement is contrasted with
    "M-005": ["820.10"],             # the duty the conflicts rule operates on
    "G-009": ["207.29"],             # the renewal provision the key element names
    "M-002": ["820.7", "820.10"],    # the supplier-control route the answer points at
    "S-020": ["111.255"],            # the rule that the BPR must follow the MMR
    "C-004": ["700.13", "700.14", "700.15", "700.18", "700.19", "700.23"],  # the other restrictions
}

APPLICABILITY_RE = re.compile(
    r"\b(except|exception|does not apply|do not apply|shall not apply|unless|exempt|"
    r"applies to|applicable to|subject to this part|scope|means)\b", re.I)
STOP = set("what does which require requires required requirement requirements must shall under that this with from "
           "part section about their there these those have when where into such each every apply applies the and for "
           "are not you your how many give list cite explain describe summarize summarise walk tell do is it its on in "
           "of a an be by or if my our we can confirm so also including include any other may been will".split())


def words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z-]{3,}", (t or "").lower())} - STOP


def part_of(text: str) -> str | None:
    m = SECTION_RE.search(text or "")
    return m.group(1) if m else None


def key_sections(row: dict) -> list[str]:
    secs = [s.strip() for s in re.split(r"[;,]", row.get("rev_key_sections") or "") if s.strip()]
    if secs:
        return list(dict.fromkeys(secs))
    return sorted({f"{a}.{b}" for a, b in SECTION_RE.findall(row.get("key_citation_draft") or "")})


def pack(provisions: list[dict], query_terms: set[str], pins: set[tuple[str, str]],
         budget: int = EVIDENCE_BUDGET, cited_sections: set[str] | None = None) -> list[dict]:
    """Choose the paragraphs that go into the evidence block.

    **A pinned paragraph is added regardless of the preferred budget**, up to the hard ceiling of
    production's real prompt budget. A pin means the ideal answer cites that paragraph, so dropping
    it would leave the answer unsupportable by its own evidence - which is the one defect this
    packing must not introduce. The preferred budget governs only the relevance fill; an example
    whose pins exceed it is reported, so its answer can be tightened rather than its evidence
    quietly truncated.
    """
    chosen: dict[str, set[int]] = defaultdict(set)
    used = 0

    def add(sec: str, para: dict, pinned: bool = False) -> bool:
        nonlocal used
        if para["i"] in chosen[sec]:
            return True
        cost = len(para["text"]) + 8
        limit = EVIDENCE_HARD_CEILING if pinned else budget
        if used + cost > limit:
            return False
        chosen[sec].add(para["i"])
        used += cost
        return True

    # a pin names a paragraph path; where a path repeats (definitions), the first row wins
    index: dict[tuple[str, str], dict] = {}
    for p in provisions:
        for x in p["paragraphs"]:
            index.setdefault((p["section"], x["path"]), x)
    # 1. paragraphs the answer cites directly. Taken round-robin across sections: a flat sort puts
    # every pin of the first section ahead of the first pin of the last, so a long section starves
    # a short one and the answer loses support for the section it cites last.
    by_sec: dict[str, list[str]] = defaultdict(list)
    for sec, path in sorted(pins):
        if (sec, path) in index:
            by_sec[sec].append(path)
    while any(by_sec.values()):
        for sec in sorted(by_sec):
            if by_sec[sec]:
                add(sec, index[(sec, by_sec[sec].pop(0))], pinned=True)
    # 1b. the paragraph that carries a cross-reference the answer relies on. Where the answer cites
    # section S as a cross-reference target, the evidence must contain the passage that makes the
    # reference - otherwise the answer asserts a link the model was never shown.
    for s_cited in sorted(cited_sections or set()):
        if any(s_cited == p["section"] for p in provisions):
            continue
        best = None
        for p in provisions:
            for x in p["paragraphs"]:
                if re.search(r"\b" + re.escape(s_cited) + r"\b", x["text"]):
                    if best is None or len(x["text"]) < len(best[1]["text"]):
                        best = (p["section"], x)
        if best:
            add(best[0], best[1], pinned=True)
    # 2. stem + applicability/exception paragraphs, and a floor per section
    for p in provisions:
        kept = 0
        for x in p["paragraphs"]:
            if x["path"] == "—" or APPLICABILITY_RE.search(x["text"]):
                if add(p["section"], x):
                    kept += 1
            if kept >= MIN_PER_SECTION:
                break
        for x in p["paragraphs"]:
            if len(chosen[p["section"]]) >= MIN_PER_SECTION:
                break
            add(p["section"], x)
    # 3. best lexical matches with the question and key elements
    scored = []
    for p in provisions:
        for x in p["paragraphs"]:
            if x["i"] in chosen[p["section"]]:
                continue
            w = words(x["text"])
            overlap = len(w & query_terms) / (1 + len(w) ** 0.5)
            scored.append((overlap, p["section"], x))
    for _, sec, x in sorted(scored, key=lambda t: (-t[0], t[1], t[2]["path"])):
        add(sec, x)

    out = []
    for p in provisions:
        keep = [x for x in p["paragraphs"] if x["i"] in chosen[p["section"]]]
        if keep or not p["paragraphs"]:
            out.append({"section": p["section"], "heading": p["heading"], "reserved": p["reserved"],
                        "paragraph_count": p["paragraph_count"], "paragraphs_kept": len(keep),
                        "paragraphs": keep})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = {json.loads(l)["id"]: json.loads(l)
            for l in (ROOT / "artifacts/stage_a/dataset.jsonl").read_text().splitlines() if l.strip()}
    attr = {json.loads(l)["id"]: json.loads(l)
            for l in (ROOT / "artifacts/stage_a/attribution_rows.jsonl").read_text().splitlines() if l.strip()}
    v1_sel = json.loads((SFT / "selection.json").read_text())
    v1_records = {r["id"]: r for r in v1_sel["records"]}
    core = sorted(v1_records)                       # the 59 v1 source rows (57 admitted + 2 rejected)

    # ---- select the new rows ------------------------------------------------------------------
    remaining = [q for q in data if q not in v1_records and data[q]["result"] != "ERROR"]
    by_cat: dict[str, list[str]] = defaultdict(list)
    for q in remaining:
        by_cat[data[q]["type"]].append(q)

    def priority(qid: str) -> tuple:
        row = data[qid]
        elements = len(re.split(r"[;,]", row.get("key_elements") or ""))
        had_evidence = 1 if attr[qid]["subcategory"] == "governing_section_supplied" else 0
        advanced = 1 if row["difficulty"] in ("Advanced", "Trap") else 0
        return (-elements, -had_evidence, -advanced, qid)

    new_ids: list[str] = []
    log: list[dict] = []
    for cat in TAKE_ALL:
        for qid in sorted(by_cat.get(cat, []), key=priority):
            new_ids.append(qid)
            log.append({"id": qid, "category": cat, "decision": "selected",
                        "reason": "category taken in full: scarce and scores zero passes at baseline"})
    part_count: Counter = Counter()
    for qid in sorted(by_cat.get("Direct Lookup", []), key=priority):
        if len(new_ids) - len([x for x in new_ids if data[x]["type"] != "Direct Lookup"]) >= DIRECT_LOOKUP_TARGET:
            log.append({"id": qid, "category": "Direct Lookup", "decision": "not selected",
                        "reason": "Direct Lookup target reached"})
            continue
        keys = key_sections(data[qid])
        pt = part_of(keys[0]) if keys else "none"
        if part_count[pt] >= DIRECT_LOOKUP_PART_CAP:
            log.append({"id": qid, "category": "Direct Lookup", "decision": "not selected",
                        "reason": f"per-part cap reached for part {pt}"})
            continue
        part_count[pt] += 1
        new_ids.append(qid)
        log.append({"id": qid, "category": "Direct Lookup", "decision": "selected",
                    "reason": f"part {pt} within cap"})

    # ---- pins: paragraphs an already-authored v1 answer cites ---------------------------------
    # Pins are read from the EFFECTIVE answer set - the v2 file overriding v1 for the same id -
    # because a revised answer cites different paragraphs from the one it replaces, and pinning the
    # superseded citations would pack evidence for an answer no longer in the dataset.
    pins: dict[str, set[tuple[str, str]]] = defaultdict(set)
    v1_answers: dict[str, dict] = {}
    answer_lines: list[str] = []
    for src in (SFT / "ideal_answers.jsonl", OUT / "ideal_answers2.jsonl"):
        if src.exists():
            answer_lines += src.read_text().splitlines()
    for line in answer_lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        if "id" not in rec or not rec.get("ideal_answer"):
            continue
        v1_answers[rec["id"]] = rec            # later file wins, so a revision supersedes its v1 original
    for qid_a, rec in v1_answers.items():
        for sec, paras in PARA_CITE_RE.findall(rec["ideal_answer"]):
            pins[qid_a].add((sec, paras))
            pins[qid_a].add((sec, paras.split(")")[0] + ")"))   # the parent paragraph too

    # ---- assemble -----------------------------------------------------------------------------
    db = Database.from_env()
    db.connect()
    extra = {}
    try:
        from importlib import import_module
        extra = import_module("scripts.sft_select").EXTRA_SECTIONS  # reuse v1's additions
    except Exception:
        extra = {}

    records = []
    for qid in core + new_ids:
        row = data[qid]
        keys = key_sections(row)
        v1 = v1_records.get(qid)
        extras = list(v1.get("supporting_sections", [])) if v1 else list(extra.get(qid, []))
        extras += [s for s in EXTRA_SECTIONS_V2.get(qid, []) if s not in extras]
        provisions = []
        for sec in keys + [s for s in extras if s not in keys]:
            rows = db.query(
                "SELECT paragraph_path, body_text, is_reserved, section_heading"
                "  FROM cfr_records WHERE section_number = %(s)s AND removed_on IS NULL"
                "  ORDER BY ordinal LIMIT 60", {"s": sec})
            provisions.append({
                "section": sec, "heading": rows[0]["section_heading"] if rows else None,
                "reserved": bool(rows and rows[0]["is_reserved"]), "paragraph_count": len(rows),
                # `i` is the paragraph's position in the section. A definitions section carries
                # dozens of rows that all have an undesignated path, so de-duplicating by path
                # alone collapses them into one key and then keeps every one of them - 117.3 packed
                # 48 definitions and 16,446 characters that way. Position is the stable identity.
                "paragraphs": [{"i": n, "path": r["paragraph_path"] or "—",
                                "text": (r["body_text"] or "").strip()}
                               for n, r in enumerate(rows)]})
        terms = words(row["question"]) | words(row["key_elements"])
        cited = set()
        a = (v1_answers.get(qid) or {}).get("ideal_answer") or ""
        for m in re.finditer(r"\b(\d{1,4}\.\d+)\b", a):
            cited.add(m.group(1))
        row_pins = set(pins.get(qid, set())) | set(MANUAL_PINS.get(qid, []))
        packed = pack(provisions, terms, row_pins, cited_sections=cited)
        records.append({
            "id": qid, "question": row["question"], "type": row["type"], "domain": row["domain"],
            "difficulty": row["difficulty"], "key_citation_draft": row["key_citation_draft"],
            "key_elements": row["key_elements"], "iso_clause_draft": row["iso_clause_draft"],
            "key_sections": keys, "supporting_sections": extras,
            "trap_row": row["rev_trap_row"], "attribution": attr[qid]["category"] + "/" + attr[qid]["subcategory"],
            "baseline_verdict": {k: row[k] for k in ("result", "L", "M", "N", "O", "P", "Q")},
            "baseline_failure_note": row["notes"],
            "in_v1_core": qid in v1_records,
            "guidance": (v1 or {}).get("guidance", []),
            "evidence_chars_full": sum(len(x["text"]) for p in provisions for x in p["paragraphs"]),
            "evidence_chars_packed": sum(len(x["text"]) for p in packed for x in p["paragraphs"]),
            "paragraphs_full": sum(p["paragraph_count"] for p in provisions),
            "paragraphs_packed": sum(p["paragraphs_kept"] for p in packed),
            "provisions": packed,
            "provisions_full": provisions,
        })

    manifest = {
        "source_universe": "all 300 benchmark questions",
        "v1_core_rows": len(core), "new_rows": len(new_ids), "total_rows": len(records),
        "evidence_budget_chars": EVIDENCE_BUDGET,
        "direct_lookup_target": DIRECT_LOOKUP_TARGET, "direct_lookup_part_cap": DIRECT_LOOKUP_PART_CAP,
        "by_category": dict(Counter(r["type"] for r in records).most_common()),
        "new_by_category": dict(Counter(data[q]["type"] for q in new_ids).most_common()),
        "by_part": dict(Counter(part_of(r["key_sections"][0]) if r["key_sections"] else "none"
                                for r in records).most_common()),
        "packing": {
            "mean_full_chars": round(sum(r["evidence_chars_full"] for r in records) / len(records)),
            "mean_packed_chars": round(sum(r["evidence_chars_packed"] for r in records) / len(records)),
            "over_preferred_budget": sorted(r["id"] for r in records if r["evidence_chars_packed"] > EVIDENCE_BUDGET),
        "over_hard_ceiling": sorted(r["id"] for r in records if r["evidence_chars_packed"] > EVIDENCE_HARD_CEILING),
        },
    }
    (args.out / "selection2.json").write_text(json.dumps({"manifest": manifest, "records": records}, indent=2) + "\n")
    (args.out / "selection_log.json").write_text(json.dumps(log, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
