"""ASSISTED REVIEW — NOT VERIFIED — package builder.

Merges the proposals (first pass, second pass, coordinator's special rows) into
the offline human-review package. Reads only files inside this package plus the
frozen verification run; writes only inside this package.

    python -u tools/build_package.py
"""

from __future__ import annotations

import csv
import glob
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
ROOT = PKG.parents[2]
LABEL = "ASSISTED REVIEW — NOT VERIFIED"
NOTICE = (f"{LABEL}. These are proposals produced with AI assistance for a human SME. They are NOT SME "
          "decisions, are NOT recorded in the authoritative review store, and must NEVER be consumed by "
          "scoring or training.")

# ------------------------------------------------------------------ inputs
ev = {json.loads(l)["question_id"]: json.loads(l)
      for l in (PKG / "evidence" / "evidence_all.jsonl").read_text(encoding="utf-8").splitlines()}
order = list(ev)
ver_path = sorted((ROOT / "artifacts" / "benchmark_verification").glob("*/verification.json"))[-1]
ver = {r["question_id"]: r for r in json.loads(ver_path.read_text(encoding="utf-8"))["rows"]}

first = {}
for f in sorted(glob.glob(str(PKG / "proposals" / "batch_*.json"))):
    for p in json.loads(Path(f).read_text(encoding="utf-8")):
        first[p["question_id"]] = p
second = {}
for f in sorted(glob.glob(str(PKG / "pass2" / "out_*.json"))):
    for p in json.loads(Path(f).read_text(encoding="utf-8")):
        second[p["question_id"]] = p
special = {p["question_id"]: p for p in json.loads((PKG / "proposals" / "special_rows.json").read_text(encoding="utf-8"))}

final = {}
for q in order:
    if q in special:
        p, src = special[q], "coordinator (special rows)"
    elif q in second:
        p, src = second[q], "batch reviewer, second pass (supplemental section text)"
    else:
        p, src = first[q], "batch reviewer, first pass"
    p = dict(p)
    p["_proposal_source"] = src
    if q in second and q in first:
        p["_first_pass_decision"] = first[q]["proposed_decision"]
    final[q] = p
assert len(final) == 300

# ------------------------------------------------------------------ mandated sets (from the automated verification)
def status(q, dim):
    for f in ver[q]["findings"]:
        if f["dimension"] == dim:
            return f["status"]
    return None

ISO_CONFLICTS = [q for q in order if status(q, "iso_clause") == "REQUIRES_SME"]
ABSENCE = [q for q in order if status(q, "negative_control") == "REQUIRES_SME"]
TEMPORAL = [q for q in order if ev[q]["question_type"] == "Temporal/Version"]
assert (len(ISO_CONFLICTS), len(ABSENCE), len(TEMPORAL)) == (23, 15, 11), (len(ISO_CONFLICTS), len(ABSENCE), len(TEMPORAL))

# ------------------------------------------------------------------ external sources
KEYS = [
    ("ISO_13485_CONTROLLED_COPY", r"ISO 13485|controlled (copy|source)|Controlled source"),
    ("FEDERAL_REGISTER", r"Federal Register|\bFR\b|89 FR"),
    ("STATUTE_FDCA", r"FD&C Act|statut|U\.S\.C|section 9\d\d|section 5\d\d|MoCRA"),
    ("FDA_GUIDANCE_DATABASE", r"guidance database|guidance document|FDA guidance|\bguidance\b"),
    ("LIVE_ECFR", r"live eCFR|LIVE eCFR"),
    ("CASE_LAW", r"\bBarr\b|decision"),
]


def external_sources(p):
    out = set()
    cs = p.get("controlled_source") or ""
    if cs:
        for name, rx in KEYS:
            if re.search(rx, cs, re.I):
                if name == "ISO_13485_CONTROLLED_COPY" and "Optional" in cs:
                    out.add("ISO_13485_CONTROLLED_COPY (optional: clause named in CFR text)")
                else:
                    out.add(name)
    if p["proposed_decision"] == "NEEDS_RESEARCH" or p.get("key_elements_issue"):
        blob = " ".join(p.get("needs_research_items") or [])
        for name, rx in KEYS:
            if name == "CASE_LAW" and not re.search(r"\bBarr\b", blob):
                continue
            if re.search(rx, blob, re.I):
                out.add(name)
    return sorted(out)


def iso_required(p):
    return any(s == "ISO_13485_CONTROLLED_COPY" for s in external_sources(p))


# ------------------------------------------------------------------ flags
rows = []
for q in order:
    p, r = final[q], ev[q]
    reasons = []
    if q in ISO_CONFLICTS: reasons.append("ISO conflict (mandated)")
    if q in ABSENCE: reasons.append("absence claim (mandated)")
    if q in TEMPORAL: reasons.append("temporal/version (mandated)")
    if q == "X-004": reasons.append("X-004 automated contradiction (mandated)")
    if p["proposed_decision"] == "CORRECTED": reasons.append("proposed CORRECTED (key change)")
    if p["proposed_decision"] == "REJECTED": reasons.append("proposed REJECTED")
    if p["proposed_decision"] == "NEEDS_RESEARCH": reasons.append("materially uncertain (NEEDS_RESEARCH)")
    if p.get("evidence_conflict"): reasons.append("conflicting evidence")
    if p.get("confidence") == "LOW": reasons.append("low confidence")
    if p.get("key_elements_issue"): reasons.append("column J not fully supported by text")
    if p["substantive_judgment"] == "incorrect" or p["completeness_judgment"] == "incorrect":
        reasons.append("a judgment is 'incorrect'")
    ext = external_sources(p)
    rows.append({
        "label": LABEL,
        "question_id": q, "row": r["row"], "domain": r["domain"], "question_type": r["question_type"],
        "question": r["question"], "draft_citation_G": r["draft_citation_G"], "draft_iso_H": r["draft_iso_H"],
        "key_answer_elements_J": r["key_answer_elements_J"],
        "automated_state": ver[q]["verification_status"],
        "proposed_decision": p["proposed_decision"],
        "proposed_corrected": p.get("proposed_corrected_citation") or "",
        "proposed_substantive": p["substantive_judgment"], "proposed_completeness": p["completeness_judgment"],
        "citation_correctness": p.get("citation_correctness", ""), "provision_exists": p.get("provision_exists", ""),
        "applicability": p.get("applicability", ""),
        "confidence": p["confidence"], "rationale": p["rationale"],
        "uncertainty": p.get("uncertainty", ""), "completeness_note": p.get("completeness_note", ""),
        "key_elements_issue": p.get("key_elements_issue", ""),
        "evidence_conflict": bool(p.get("evidence_conflict")),
        "evidence_refs": " | ".join(p.get("evidence_refs") or []),
        "elements": p.get("elements") or [],
        "needs_research_items": p.get("needs_research_items") or [],
        "iso_tier": (p.get("iso_assessment") or {}).get("tier", ""),
        "absence_established": (p.get("absence_assessment") or {}).get("absence_established", ""),
        "external_sources": ext,
        "controlled_source_consultation": bool([s for s in ext if "optional" not in s]),
        "human_review_required": True,
        "second_review_required": bool(reasons),
        "second_review_reasons": reasons,
        "proposal_source": p["_proposal_source"],
        "first_pass_decision": p.get("_first_pass_decision", ""),
        "full_proposal": p,
    })
by_id = {r["question_id"]: r for r in rows}

# ------------------------------------------------------------------ writers
def write_csv(path, fieldnames, items):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([f"# {NOTICE}"])
        w.writerow(fieldnames)
        for it in items:
            w.writerow([it.get(k, "") if not isinstance(it.get(k), list) else " | ".join(map(str, it.get(k)))
                        for k in fieldnames])


MASTER_COLS = ["label", "question_id", "row", "domain", "question_type", "question", "draft_citation_G", "draft_iso_H",
               "key_answer_elements_J", "automated_state", "proposed_decision", "proposed_corrected",
               "proposed_substantive", "proposed_completeness", "citation_correctness", "provision_exists",
               "applicability", "confidence", "iso_tier", "absence_established", "rationale", "uncertainty",
               "completeness_note", "key_elements_issue", "evidence_conflict", "evidence_refs",
               "needs_research_items", "external_sources", "controlled_source_consultation",
               "human_review_required", "second_review_required", "second_review_reasons", "proposal_source",
               "first_pass_decision",
               "SME_agrees_with_proposal (Y/N)", "SME_decision", "SME_corrected_citation_or_clause",
               "SME_substantive", "SME_completeness", "SME_rationale", "SME_name_title", "SME_date"]
write_csv(PKG / "01_master_review_table.csv", MASTER_COLS, rows)

with (PKG / "02_proposals_full.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps({"_label": LABEL, "_notice": NOTICE, **{k: v for k, v in r.items() if k != "elements"}},
                            ensure_ascii=False) + "\n")

SR_COLS = ["label", "question_id", "domain", "question_type", "proposed_decision", "proposed_corrected", "confidence",
           "second_review_reasons", "external_sources", "rationale", "needs_research_items",
           "SECOND_REVIEWER_decision", "SECOND_REVIEWER_agrees_with_first (Y/N)", "SECOND_REVIEWER_name", "date"]
second_q = [r for r in rows if r["second_review_required"]]
prio = lambda r: (0 if r["question_id"] == "X-004" else 1 if any("mandated" in x for x in r["second_review_reasons"]) else 2,
                  {"CORRECTED": 0, "REJECTED": 0, "NEEDS_RESEARCH": 1, "ACCEPTED": 2}[r["proposed_decision"]])
write_csv(PKG / "03_second_review_queue.csv", SR_COLS, sorted(second_q, key=prio))

research = [r for r in rows if r["proposed_decision"] == "NEEDS_RESEARCH"]
RQ_COLS = ["label", "question_id", "domain", "question_type", "external_sources", "needs_research_items", "rationale",
           "key_elements_issue", "confidence", "RESEARCH_owner", "RESEARCH_finding", "RESEARCH_source_consulted", "date"]
write_csv(PKG / "04_unresolved_research_queue.csv", RQ_COLS, research)


# ------------------------------------------------------------------ markdown helpers
def md_elements(p):
    out = []
    for e in p.get("elements") or []:
        quote = f" — “{e['quote']}”" if e.get("quote") else ""
        note = f" _({e['note']})_" if e.get("note") else ""
        out.append(f"  - **{e['support']}** · {e['element']} · `{e.get('cite', '')}`{quote}{note}")
    return "\n".join(out) or "  - (no element breakdown)"


def md_row(r, extra=""):
    p = r["full_proposal"]
    lines = [f"### {r['question_id']} — proposed **{r['proposed_decision']}** ({r['confidence']})",
             f"*{r['question_type']} · {r['domain']}*", "",
             f"**Question.** {r['question']}", "",
             f"**Draft key G.** {r['draft_citation_G']}  ", f"**Draft ISO H.** {r['draft_iso_H']}  ",
             f"**Key elements J.** {r['key_answer_elements_J']}", ""]
    if r["proposed_corrected"]:
        lines += [f"**Proposed correction (NOT applied).** {r['proposed_corrected']}", ""]
    lines += [f"**Rationale.** {r['rationale']}", "", "**Element-by-element evidence (verbatim eCFR quotes, machine-checked):**",
              md_elements(p), ""]
    if p.get("iso_assessment"):
        a = p["iso_assessment"]
        lines += [f"**ISO assessment.** tier `{a['tier']}` · draft `{a['draft_H']}` · clauses named in cited CFR text: "
                  f"`{', '.join(a['clauses_named_in_cited_cfr_text']) or 'none'}` · internal crosswalk: `{a['internal_crosswalk']}`  ",
                  f"{a['note']}", ""]
    if p.get("absence_assessment"):
        a = p["absence_assessment"]
        lines += [f"**Absence assessment.** scope: {a['search_scope']} · method: {a['method']} · result: `{a['result']}` · "
                  f"**absence established: {a['absence_established']}**  ", f"{a['note']}", ""]
    if r["key_elements_issue"]:
        lines += [f"**Column J issue.** {r['key_elements_issue']}", ""]
    if r["needs_research_items"]:
        lines += ["**What the SME must establish:**"] + [f"1. {x}" for x in r["needs_research_items"]] + [""]
    if r["uncertainty"]:
        lines += [f"**Uncertainty.** {r['uncertainty']}", ""]
    lines += [f"**External sources:** {', '.join(r['external_sources']) or 'none beyond the eCFR snapshot'} · "
              f"**second review:** {'; '.join(r['second_review_reasons']) or 'no'}", extra, "---", ""]
    return "\n".join(lines)


HEADER = f"> **{NOTICE}**\n\n"

# ---- X-004 packet
x = by_id["X-004"]
xe = ev["X-004"]
rng = xe["section_ranges"][0]
x_md = [f"# X-004 review packet\n", HEADER,
        "## Why this row is special\n",
        "The automated verifier marked the draft citation **CONTRADICTED**: it cites `21 CFR 4.100 through 4.110`, and "
        "4.110 does not exist in the eCFR snapshot (2026-09-03). This packet does **not** correct the row; it sets out "
        "what an SME must verify and the disposition the evidence supports.\n",
        "## What the snapshot holds\n",
        "| Section | Heading | Reserved |", "|---|---|---|"]
x_md += [f"| {s['section']} | {s['heading']} | {s['reserved']} |" for s in rng["sections_present_in_snapshot"]]
x_md += ["", f"Endpoint states: `4.100` exists={rng['endpoint_states']['4.100']['exists']}; "
         f"`4.110` exists={rng['endpoint_states']['4.110']['exists']}, reserved={rng['endpoint_states']['4.110']['reserved']}, "
         "not covered by any reserved range. Part 4 subparts: **A** (CGMP for combination products), "
         "**B** (Postmarketing Safety Reporting for Combination Products). Subpart B = 4.100–4.105 exactly.\n",
         "## Verification checklist for the SME\n",
         "1. **Live source.** Confirm in the *live* eCFR that Part 4 Subpart B ends at 4.105 (the snapshot is dated 2026-09-03).",
         "2. **Drafting intent.** Was `4.110` a slip for `4.105`, or did the drafter intend the key to reach further "
         "(4.100(c) says the subpart supplements parts 314, 600, 606, 803 and 806)?",
         "3. **Does the corrected range satisfy column J?** The element evidence below says yes for every element.",
         "4. **Completeness.** Decide whether naming the underlying parts (803/806, 314, 600/606) is required for G5.",
         "5. **Record** CORRECTED with the range you determine (the original key is preserved automatically), or NEEDS_RESEARCH.\n",
         "## Proposed disposition\n", md_row(x)]
(PKG / "05_X-004_review_packet.md").write_text("\n".join(x_md), encoding="utf-8")

# ---- ISO packet
g7 = [q for q in order if ev[q]["iso"] is not None]
tiers = Counter(by_id[q]["iso_tier"] for q in ISO_CONFLICTS)
iso_md = [f"# ISO 13485 conflict packet\n", HEADER,
          "## Ground rules\n",
          "* **No ISO 13485 text is held in this system** (`iso_clauses.body_text` is empty for all 88 clauses). No clause text "
          "was consulted or reproduced. Clauses are identified by number and title only.",
          "* The **internal crosswalk** (189 rows, 87 sections) is a project artefact at **section** granularity. It is evidence "
          "of an internal position, **not authority**, and it never outranks the controlled standard.",
          "* The **eCFR text itself** frequently names ISO clauses at **paragraph** level (820.10(b)–(d), 820.35(a)–(c), 820.45(b)–(c), "
          "4.4(b)(1), 820.3(b)). Where it does, that is regulation text (a US Government work) and settles which clause the regulation "
          "invokes; the controlled copy is then needed only to confirm the title.",
          "* **Workbook rule to keep in view:** a column H of `None` means naming *any* clause scores Q=0 **and triggers column M "
          "(fabricated citation)** — a G2 zero-tolerance failure.\n",
          "## Evidence tiers\n",
          "| Tier | Meaning | Proposal policy |", "|---|---|---|",
          "| `T1_CFR_TEXT` | the cited CFR paragraph names the draft clause | may be ACCEPTED; controlled copy optional (title check) |",
          "| `T2_CORROBORATED` | crosswalk maps the section to the same clause or its parent; index title matches | ACCEPTED at MEDIUM, **controlled copy required** before recording |",
          "| `T3_UNRESOLVED` | draft names a clause the crosswalk does not, CFR silent | NEEDS_RESEARCH |",
          "| `NONE_CLAIM` | draft says no clause; crosswalk maps the section | NEEDS_RESEARCH (policy + controlled copy) |",
          "| `RANGE` | whole standard / clause range | decided on the CFR text; scoring convention to confirm |\n",
          "## The 23 automated ISO conflicts at a glance\n",
          "| Row | Draft H | Crosswalk (section level) | Clauses named in cited CFR text | Tier | Proposed |",
          "|---|---|---|---|---|---|"]
for q in ISO_CONFLICTS:
    a = by_id[q]["full_proposal"].get("iso_assessment") or {}
    iso_md.append(f"| {q} | {ev[q]['draft_iso_H']} | {a.get('internal_crosswalk', '')} | "
                  f"{', '.join(a.get('clauses_named_in_cited_cfr_text') or []) or '—'} | {a.get('tier', '')} | "
                  f"{by_id[q]['proposed_decision']} |")
iso_md += ["", f"Tier counts among the 23: {dict(tiers)}\n",
           "**Reading.** The conflict set is dominated by one mechanism: the crosswalk assigns 820.35 → 4.2.5 and 820.45 → 7.5.1 "
           "for the whole section (from each section's introductory sentence), while the benchmark keys paragraphs. Where the "
           "paragraph names its own clause, the draft matches the regulation and the crosswalk is simply coarser. The genuinely "
           "open items are the eight `None` rows, sibling-clause disagreements (M-038 7.5.7; M-040 8.2.6 vs 8.2.5), M-028's 4.2.3, "
           "M-042's omitted 7.5.1 (inconsistent with M-023), and NC-005/NC-011, whose negative claims reach into the standard's text.\n",
           "## Row detail — the 23 conflicts\n"]
iso_md += [md_row(by_id[q]) for q in ISO_CONFLICTS]
iso_md += ["## Other ISO-bearing rows (column H not '—'), for completeness\n",
           "| Row | Draft H | Tier | Proposed | Confidence |", "|---|---|---|---|---|"]
iso_md += [f"| {q} | {ev[q]['draft_iso_H']} | {by_id[q]['iso_tier']} | {by_id[q]['proposed_decision']} | {by_id[q]['confidence']} |"
           for q in g7 if q not in ISO_CONFLICTS]
(PKG / "06_ISO_conflict_packet.md").write_text("\n".join(iso_md), encoding="utf-8")

# ---- negative control packet
nc_rows = [q for q in order if ev[q]["question_type"] == "Negative Control"]
nc_md = [f"# Negative-control packet (22 rows; 15 automated absence claims)\n", HEADER,
         "## How to read the absence evidence\n",
         "Three different things are kept apart here:\n",
         "* **NOT_PRESENT / structural** — a section, paragraph or subpart designation does not exist in the snapshot's structure "
         "(section lookup, reserved-range resolution, subpart list). This *establishes* absence within the snapshot.",
         "* **POSITIVE_CONTRARY_EVIDENCE** — the regulation affirmatively says something else (e.g. 211.192 assigns batch-record "
         "approval to the quality control unit). This refutes the premise without relying on a negative.",
         "* **NO_RESULT** — a term/synonym search found nothing. This is *consistent with* absence and is labelled "
         "established only where the scope is complete (a whole small part inspected in full, or all of Title 21 for an exact name). "
         "Where the requirement could sit in ISO 13485 (not held) or in FDA guidance (table coverage unassessed), absence is "
         "**not** established and the row is NEEDS_RESEARCH.\n",
         "| Row | Automated | Result | Absence established | Proposed | Conf. |", "|---|---|---|---|---|---|"]
for q in nc_rows:
    a = by_id[q]["full_proposal"].get("absence_assessment") or {}
    nc_md.append(f"| {q}{' ★' if q in ABSENCE else ''} | {status(q, 'negative_control')} | {a.get('result', '')} | "
                 f"{a.get('absence_established', '')} | {by_id[q]['proposed_decision']} | {by_id[q]['confidence']} |")
nc_md += ["", "★ = one of the 15 automated absence claims (negative_control = REQUIRES_SME).\n",
          "Also in the absence family (not typed Negative Control): PB-001 (Title 21 coverage), PB-006 (ISO 14971 not incorporated), "
          "M-041/SD-011/SD-013 (no certification requirement in Part 820). Their detail is in the master table.\n",
          "## Row detail\n"]
nc_md += [md_row(by_id[q]) for q in nc_rows]
(PKG / "07_negative_control_packet.md").write_text("\n".join(nc_md), encoding="utf-8")

# ------------------------------------------------------------------ statistics
dec = Counter(r["proposed_decision"] for r in rows)
conf = Counter(r["confidence"] for r in rows)
ext = Counter(s for r in rows for s in r["external_sources"])
csc = [r["question_id"] for r in rows if r["controlled_source_consultation"]]
by_dom = defaultdict(Counter)
for r in rows:
    by_dom[r["domain"]][r["proposed_decision"]] += 1
by_type = defaultdict(Counter)
for r in rows:
    by_type[r["question_type"]][r["proposed_decision"]] += 1
kei = [r["question_id"] for r in rows if r["key_elements_issue"]]
conflict = [r["question_id"] for r in rows if r["evidence_conflict"]]
mand = sorted(set(ISO_CONFLICTS) | set(ABSENCE) | set(TEMPORAL) | {"X-004"}, key=order.index)

# workload model (minutes, low/high) — planning figures, stated in the summary.
# Confirming a proposal whose quotes are already in the packet is cheaper than an
# unassisted first pass; research time depends on which external source is needed,
# and some lookups are shared (one Federal Register check settles every date row).
W = {("ACCEPTED", "HIGH"): (2, 4), ("ACCEPTED", "MEDIUM"): (4, 7), ("ACCEPTED", "LOW"): (6, 10),
     ("CORRECTED", None): (6, 12), ("REJECTED", None): (8, 15)}
PER_SOURCE = {"ISO_13485_CONTROLLED_COPY": (8, 15), "STATUTE_FDCA": (15, 30), "FDA_GUIDANCE_DATABASE": (10, 20),
              "CASE_LAW": (20, 40), "LIVE_ECFR": (5, 10), "FEDERAL_REGISTER": (0, 0)}
SHARED = {"FEDERAL_REGISTER": (20, 40)}   # one lookup, all rows
lo = hi = 0
for r in rows:
    if r["proposed_decision"] == "NEEDS_RESEARCH":
        srcs = [s for s in r["external_sources"] if s in PER_SOURCE]
        a, b = (5, 10) if srcs else (8, 15)   # base: read packet, decide; no-source rows are text judgments
        for s in srcs:
            a += PER_SOURCE[s][0]; b += PER_SOURCE[s][1]
    else:
        k = (r["proposed_decision"], r["confidence"]) if r["proposed_decision"] == "ACCEPTED" else (r["proposed_decision"], None)
        a, b = W[k]
    lo += a; hi += b
lo += sum(v[0] for v in SHARED.values()); hi += sum(v[1] for v in SHARED.values())
sr_lo, sr_hi = 4 * len(second_q), 8 * len(second_q)
stats = {
    "_label": LABEL, "_notice": NOTICE,
    "benchmark_sha256": hashlib.sha256((ROOT / "Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx").read_bytes()).hexdigest(),
    "verification_run": ver_path.parent.name,
    "questions_processed": len(rows),
    "proposed_decisions": dict(dec),
    "confidence": dict(conf),
    "second_review_required": len(second_q),
    "second_review_mandated_minimum": len(mand),
    "controlled_or_external_source_consultation": len(csc),
    "external_sources_by_kind": dict(ext),
    "unresolved_NEEDS_RESEARCH": len(research),
    "rows_with_column_J_issue": len(kei),
    "rows_with_conflicting_evidence": len(conflict),
    "iso_conflicts_23_by_tier": dict(tiers),
    "iso_conflicts_23_by_proposal": dict(Counter(by_id[q]["proposed_decision"] for q in ISO_CONFLICTS)),
    "absence_claims_15_by_proposal": dict(Counter(by_id[q]["proposed_decision"] for q in ABSENCE)),
    "absence_claims_15_established": sum(1 for q in ABSENCE if (by_id[q]["full_proposal"].get("absence_assessment") or {}).get("absence_established") is True),
    "temporal_11_by_proposal": dict(Counter(by_id[q]["proposed_decision"] for q in TEMPORAL)),
    "by_question_type": {k: dict(v) for k, v in by_type.items()},
    "by_domain": {k: dict(v) for k, v in by_dom.items()},
    "pass2_transitions": dict(Counter(f"{r['first_pass_decision']}->{r['proposed_decision']}" for r in rows if r["first_pass_decision"])),
    "quotes_machine_checked": sum(1 for r in rows for e in r["elements"] if e.get("quote")),
    "workload_minutes_first_pass": [lo, hi], "workload_minutes_second_review": [sr_lo, sr_hi],
    "ids": {"CORRECTED": [r["question_id"] for r in rows if r["proposed_decision"] == "CORRECTED"],
            "NEEDS_RESEARCH": [r["question_id"] for r in research],
            "REJECTED": [r["question_id"] for r in rows if r["proposed_decision"] == "REJECTED"],
            "second_review": [r["question_id"] for r in second_q],
            "controlled_source": csc, "column_J_issue": kei, "conflicting_evidence": conflict,
            "iso_conflicts": ISO_CONFLICTS, "absence_claims": ABSENCE, "temporal": TEMPORAL},
}
(PKG / "08_summary_statistics.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

# ------------------------------------------------------------------ offline HTML viewer (not published anywhere)
def esc(s): return html.escape(str(s))
trs = []
for r in rows:
    p = r["full_proposal"]
    els = "".join(f"<li><b>{esc(e['support'])}</b> · {esc(e['element'])} · <code>{esc(e.get('cite',''))}</code>"
                  + (f"<blockquote>{esc(e['quote'])}</blockquote>" if e.get('quote') else "")
                  + (f"<i>{esc(e['note'])}</i>" if e.get('note') else "") + "</li>" for e in r["elements"])
    res = "".join(f"<li>{esc(x)}</li>" for x in r["needs_research_items"])
    trs.append(
        f"<tr data-d='{r['proposed_decision']}' data-s='{int(r['second_review_required'])}' data-t='{esc(r['question_type'])}'>"
        f"<td><b>{r['question_id']}</b><br><small>{esc(r['question_type'])}</small></td>"
        f"<td class='d {r['proposed_decision']}'>{r['proposed_decision']}<br><small>{r['confidence']}</small></td>"
        f"<td>{esc(r['question'])}<details><summary>key &amp; evidence</summary>"
        f"<p><b>G</b> {esc(r['draft_citation_G'])}<br><b>H</b> {esc(r['draft_iso_H'])}<br><b>J</b> {esc(r['key_answer_elements_J'])}</p>"
        + (f"<p><b>Proposed correction (not applied):</b> {esc(r['proposed_corrected'])}</p>" if r['proposed_corrected'] else "")
        + f"<ul>{els}</ul>"
        + (f"<p><b>Research needed</b></p><ol>{res}</ol>" if res else "")
        + (f"<p><b>Column J issue:</b> {esc(r['key_elements_issue'])}</p>" if r['key_elements_issue'] else "")
        + f"<p><small>source: {esc(r['proposal_source'])}</small></p></details></td>"
        f"<td>{esc(r['rationale'])}</td>"
        f"<td>{esc('; '.join(r['second_review_reasons']))}<br><small>{esc(', '.join(r['external_sources']))}</small></td></tr>")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assisted Review Proposals</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2dfd6;--acc:#b3261e;--ok:#1f6b3a;--warn:#8a5a00;--info:#1f4f8a;--card:#fff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161614;--fg:#ecebe6;--mut:#a3a29b;--line:#34332e;--acc:#ff8a80;--ok:#7fd49b;--warn:#f3c26b;--info:#8fb8ff;--card:#1e1e1b}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:16px;max-width:1400px;margin:auto}}
.banner{{border:2px solid var(--acc);color:var(--acc);padding:10px 14px;border-radius:6px;font-weight:600;margin-bottom:12px}}
table{{border-collapse:collapse;width:100%;background:var(--card)}}td{{border-top:1px solid var(--line);padding:8px;vertical-align:top}}
.d{{font-weight:700;white-space:nowrap}}.ACCEPTED{{color:var(--ok)}}.CORRECTED{{color:var(--info)}}.NEEDS_RESEARCH{{color:var(--warn)}}.REJECTED{{color:var(--acc)}}
blockquote{{margin:4px 0 4px 8px;padding-left:8px;border-left:3px solid var(--line);color:var(--mut)}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}}select,input{{padding:4px;background:var(--card);color:var(--fg);border:1px solid var(--line)}}
@media (max-width:700px){{td:nth-child(4),td:nth-child(5){{display:none}}}}
</style></head><body>
<div class="banner">{esc(NOTICE)}</div>
<p>Proposals: {esc(dict(dec))} · second review: {len(second_q)} · unresolved: {len(research)}. Offline file — not published.</p>
<div class="bar"><select id="fd"><option value="">all decisions</option><option>ACCEPTED</option><option>CORRECTED</option><option>NEEDS_RESEARCH</option><option>REJECTED</option></select>
<label><input type="checkbox" id="fs"> second review only</label><input id="fq" placeholder="search text"></div>
<table><tbody id="tb">{''.join(trs)}</tbody></table>
<script>
const f=()=>{{const d=fd.value,s=fs.checked,q=fq.value.toLowerCase();for(const tr of tb.rows){{tr.style.display=((!d||tr.dataset.d===d)&&(!s||tr.dataset.s==='1')&&(!q||tr.textContent.toLowerCase().includes(q)))?'':'none'}}}};
fd.onchange=f;fs.onchange=f;fq.oninput=f;
</script></body></html>"""
(PKG / "01_master_review_table.html").write_text(page, encoding="utf-8")

print(json.dumps({k: stats[k] for k in ("questions_processed", "proposed_decisions", "confidence", "second_review_required",
                                        "second_review_mandated_minimum", "controlled_or_external_source_consultation",
                                        "external_sources_by_kind", "unresolved_NEEDS_RESEARCH", "rows_with_column_J_issue",
                                        "rows_with_conflicting_evidence", "iso_conflicts_23_by_tier", "iso_conflicts_23_by_proposal",
                                        "absence_claims_15_by_proposal", "absence_claims_15_established", "temporal_11_by_proposal",
                                        "pass2_transitions", "quotes_machine_checked", "workload_minutes_first_pass",
                                        "workload_minutes_second_review")}, indent=1, ensure_ascii=False))
print("by type:", json.dumps(stats["by_question_type"]))
