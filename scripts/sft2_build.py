"""SFT dataset v2, step 2: audit, assemble and split.

Dataset construction only - no model is loaded, no inference is run, nothing is trained.

Audit checks, run on every example before admission:

  A1  every CFR section cited in the answer is in that example's evidence, is one the answer
      correctly names as absent, or is named as a cross-reference inside the supplied text
  A2  every cited section exists in the snapshot (no fabricated identifiers)
  A3  failure-mode labels come from the controlled vocabulary
  A4  an answer is present unless the example is explicitly rejected, and a rejection has a reason
  A5  evidence is present unless the example is a pure scope/professional-role refusal
  A6  ids are unique and trace to a real benchmark question
  A7  **paragraph-level support**: every `section(paragraph)` the answer cites is present in the
      packed evidence, as that paragraph or as an ancestor of it. This is the check that makes
      evidence packing safe - it fails loudly if compaction dropped something the answer needs.
  A8  evidence is production-sized (reported against the 3,000-character packing budget)
  A9  the answer is within the concision target (reported; an enumeration may exceed it)

A1, A2, A3, A5 and A7 reject. A8 and A9 report, because a genuine enumeration may legitimately run
long and a refusal legitimately carries little evidence.

Split: connected components over shared provisions, assigned whole, stratified by benchmark
category. No section and no source question appears on both sides.

    .venv/bin/python scripts/sft2_build.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.retrieval.db import Database  # noqa: E402

SFT2 = ROOT / "artifacts/sft2"
SNAPSHOT_DATE = "2026-09-03"
EVIDENCE_BUDGET = 3000
ANSWER_MIN, ANSWER_MAX = 400, 1200
VALIDATION_FRACTION = 0.18
SEED = "regulus-sft-v2"

VOCAB = {
    "incomplete_answer", "missing_subordinate_paragraphs", "wrong_provision_selection",
    "scope_applicability", "exceptions_and_conditions", "cross_reference_reasoning",
    "false_premise_handling", "temporal_version_reasoning", "evidence_faithful_interpretation",
    "answer_completeness_discipline", "abstention", "distinction_reasoning", "citation_selection",
}
# rows whose correct answer is a refusal on scope or professional-role grounds carry no provision
# evidence, and that is the right shape for them rather than a defect
NO_EVIDENCE_OK = {"SD-005", "SD-006", "SD-007", "SD-009", "SD-001", "SD-002", "SD-004"}
# "29 CFR 1910.1200" and "9 CFR" are other titles; a scope answer names them precisely in order to
# place them outside Title 21, so they must not be read as fabricated Title 21 sections
OTHER_TITLE = re.compile(r"\b(?!21\b)\d{1,2}\s*CFR\s*$", re.I)

CITE_RE = re.compile(r"\b(\d{1,4}(?:\.\d+)+)\b")
PARA_CITE_RE = re.compile(r"\b(\d{1,4}\.\d+)((?:\([a-z0-9]+\))+)")
# A7 extension. An answer may attribute content to a paragraph without writing the section number
# again - "...listed in 21 CFR 807.87:" followed by "(a) ... (d) ... (f) ...". Those lettered claims
# are paragraph-level assertions and must be supported like any other, but they expose no
# `section(paragraph)` token, so PARA_CITE_RE never sees them. This matches a marker that opens a
# clause, which is then attributed to the most recently named section.
LIST_MARKER_RE = re.compile(r"(?:^|\n|(?<=[.;:])\s|-\s)\((\w{1,4})\)\s+(?=[A-Za-z])", re.M)
SECTION_MENTION_RE = re.compile(r"\b(\d{1,4}\.\d+)\b")
# A citation may carry further paragraphs as a continuation rather than repeating the section:
# "(830.320(c)(1), (2))" or "(117.405(a)(1) through (3))". Those trailing markers are claims about
# their own paragraphs and are resolved against the preceding citation's parent path.
CONTINUATION_RE = re.compile(r"\s*(?:,|and|or|through|to|;)\s*((?:\([a-zA-Z0-9]{1,4}\))+)")
ISO_CONTEXT = re.compile(r"(clause|ISO\s*\d{3,5})[^.]{0,24}$", re.I)
# an answer must not contain visible reasoning: the target is the answer, never the derivation
COT_RE = re.compile(r"\b(let me think|step by step|first, I|we need to determine|reasoning:|thinking:)\b", re.I)


# a measurement is not a citation: "121.5 degrees C maintained for 20 minutes" in 606.11(b) was
# being read as 21 CFR 121.5
UNIT_AFTER = re.compile(r"^\s*(°|degrees|deg\b|percent|%|mg\b|mL\b|kg\b|g\b|hours?\b|minutes?\b|days?\b)", re.I)


def sections_in(text: str) -> set[str]:
    out = set()
    for m in CITE_RE.finditer(text or ""):
        num = m.group(1)
        if num.count(".") > 1:
            continue
        if ISO_CONTEXT.search((text or "")[max(0, m.start() - 40):m.start()]):
            continue
        if UNIT_AFTER.match((text or "")[m.end():m.end() + 14]):
            continue
        if OTHER_TITLE.search((text or "")[max(0, m.start() - 12):m.start()]):
            continue
        out.add(num)
    return out


def paragraph_cites(text: str) -> set[tuple[str, str]]:
    """(section, paragraph path) pairs the answer cites, e.g. ("820.35", "(b)(3)")."""
    out = set()
    for sec, paras in PARA_CITE_RE.findall(text or ""):
        out.add((sec, paras))
    return out


def continuation_claims(text: str) -> set[tuple[str, str]]:
    """Paragraphs named as a continuation of a preceding citation, at the same depth."""
    text = text or ""
    out = set()
    for m in PARA_CITE_RE.finditer(text):
        sec, paras = m.group(1), m.group(2)
        parts = re.findall(r"\([a-zA-Z0-9]+\)", paras)
        parent = "".join(parts[:-1])
        pos = m.end()
        while True:
            c = CONTINUATION_RE.match(text, pos)
            if not c:
                break
            # A continuation is written either as a sibling of the leaf ("(c)(1), (2)" -> (c)(2))
            # or as a full path from the section ("(b)(1), (b)(1)(i)"). Which one is meant is not
            # recoverable from the text, so both readings are offered and the claim counts as
            # supported if either is in the evidence.
            marker = c.group(1)
            if marker.count("(") == 1:
                alts = (parent + marker, marker)      # "(c)(1), (2)" -> (c)(2), else bare (2)
            else:
                alts = (marker, parent + marker)      # "(b)(1), (b)(1)(i)" -> an absolute path
            out.add((sec, alts))
            pos = c.end()
    return out


def list_marker_claims(text: str) -> set[tuple[str, str]]:
    """Lettered-list paragraph claims, attributed to the most recently named section.

    "...must contain the information listed in 21 CFR 807.87:" followed by "(a) ...", "(d) ..."
    asserts the content of 807.87(a) and 807.87(d) just as surely as writing the numbers out.
    Only markers that open a clause are taken, so a paragraph path inside a full citation such as
    "820.1(a)(2)" is not double-counted here.
    """
    text = text or ""
    out = set()
    for m in LIST_MARKER_RE.finditer(text):
        before = text[:m.start()]
        secs = SECTION_MENTION_RE.findall(before)
        if not secs:
            continue
        sec = secs[-1]
        if sec.count(".") != 1:
            continue
        if ISO_CONTEXT.search(before[-40:]):
            continue
        out.add((sec, f"({m.group(1)})"))
    return out


def cross_referenced(path: str, section_text: str) -> bool:
    """True when the section's own supplied text names this paragraph as a cross-reference.

    117.430(a) reads "Except as provided by paragraph (c), (d), or (e) of this section", so an
    answer that says (d) and (e) provide exceptions rests on text that *was* supplied. This is the
    paragraph-level form of the carve-out A1 already grants a cross-referenced section number.
    """
    return bool(re.search(r"paragraphs?\b[^.]{0,130}" + re.escape(path) + r"[^.]{0,90}of this section",
                          section_text or "", re.I | re.S))


def covered(sec: str, path: str, available: dict[str, set[str]], *, suffix_ok: bool = False,
            texts: dict[str, dict[str, str]] | None = None) -> bool:
    """True when the cited paragraph, or a descendant of it, is in the evidence.

    An *ancestor* only counts when the ancestor's own supplied text carries the child marker
    inline. In this corpus a parent paragraph is usually just a heading and its children are
    separate rows, so treating a bare ancestor as support let U-010 claim 830.320(c)(2) on the
    strength of a packed (c) that says nothing about (2).
    """
    paths = available.get(sec, set())
    # The section's undesignated stem does NOT support a claim about a specific paragraph. Treating
    # it as support ("—" in paths) silently satisfied every paragraph-level claim whenever the stem
    # happened to be packed, which is why P-001's unsupported (d) and (f) passed the audit.
    # A general statement that names only the section is covered by the section-level check A1.
    if path in paths:
        return True
    parts = re.findall(r"\([a-zA-Z0-9]+\)", path)
    sec_texts = (texts or {}).get(sec, {})
    for n in range(len(parts) - 1, 0, -1):
        anc = "".join(parts[:n])
        if anc in paths and "".join(parts[n:]) in sec_texts.get(anc, ""):
            return True
    if any(p.startswith(path) for p in paths):
        return True
    # A bare list marker may be the tail of a deeper path: "(i)" in a list under a section whose
    # evidence holds "(a)(1)(i)". Accepted for list claims only, to keep the check conservative.
    return suffix_ok and any(p.endswith(path) for p in paths)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers", type=Path, default=SFT2 / "ideal_answers2.jsonl")
    ap.add_argument("--out", type=Path, default=SFT2)
    args = ap.parse_args()

    selection = json.loads((SFT2 / "selection2.json").read_text())
    records = {r["id"]: r for r in selection["records"]}
    absences = json.loads((ROOT / "artifacts/sft/absence_checks.json").read_text())

    answers: dict[str, dict] = {}
    for src in (ROOT / "artifacts/sft/ideal_answers.jsonl", args.answers):
        if not src.exists():
            continue
        for line in src.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                if "id" in rec:
                    answers[rec["id"]] = rec          # the v2 file overrides v1 for the same id

    db = Database.from_env()
    db.connect()
    known = {r["number"] for r in db.query(
        "SELECT DISTINCT section_number AS number FROM cfr_records WHERE removed_on IS NULL")}

    examples, rejected, flagged = [], [], []
    for qid, src in records.items():
        ans = answers.get(qid)
        if ans is None:
            rejected.append({"id": qid, "audit": ["A4"], "reason": "no ideal answer authored"})
            continue
        if ans.get("reject"):
            rejected.append({"id": qid, "audit": ["A4"], "reason": ans.get("reject_reason", "rejected"),
                             "needs_sme": True})
            continue
        answer = (ans.get("ideal_answer") or "").strip()
        if not answer:
            rejected.append({"id": qid, "audit": ["A4"], "reason": "empty ideal answer"})
            continue

        problems: list[str] = []
        evidence_sections = {p["section"] for p in src["provisions"]}
        available = {p["section"]: {x["path"] for x in p["paragraphs"]} for p in src["provisions"]}
        para_text = {p["section"]: {x["path"]: x["text"] for x in p["paragraphs"]}
                     for p in src["provisions"]}
        absent_ok = {p["section"] for p in src["provisions_full"] if p["paragraph_count"] == 0}
        absence_text = json.dumps(absences.get(qid, []))
        absent_ok |= set(CITE_RE.findall(absence_text))
        has_absence = qid in absences
        evidence_text = json.dumps([p["paragraphs"] for p in src["provisions"]] + src.get("guidance", []))

        if not src["provisions"] and not has_absence and qid not in NO_EVIDENCE_OK:
            problems.append("A5: no evidence and no verified absence")

        cited = sections_in(answer)
        fabricated = sorted(c for c in cited if c not in known and c not in absent_ok)
        if fabricated:
            problems.append(f"A2: cited section(s) absent from the snapshot: {fabricated}")
        unsupported = sorted(c for c in cited if c not in evidence_sections and c not in absent_ok
                             and c not in CITE_RE.findall(evidence_text))
        if unsupported:
            problems.append(f"A1: cited section(s) with no support in the evidence: {unsupported}")

        # A7: paragraph-level support
        # A reserved or removed section reaches the evidence with zero paragraphs, and an answer
        # about it is supposed to name the paragraph that no longer exists; such a citation cannot
        # and should not be paragraph-supported.
        missing_paras = sorted(f"{s}{p}" for s, p in paragraph_cites(answer)
                               if s in evidence_sections and available.get(s)
                               and not covered(s, p, available, texts=para_text))
        if missing_paras:
            problems.append(f"A7: cited paragraph(s) not in the packed evidence: {missing_paras[:8]}")
        # A7b: the same requirement for lettered-list claims that name no section of their own
        sec_text = {p["section"]: "\n".join(f'{x["path"]} {x["text"]}' for x in p["paragraphs"])
                    for p in src["provisions"]}
        claims = {(s, (p,)) for s, p in list_marker_claims(answer)} | continuation_claims(answer)
        missing_list = sorted(f"{s}{alts[0]}" for s, alts in claims
                              if s in evidence_sections and available.get(s)
                              and not any(covered(s, p, available, suffix_ok=True, texts=para_text)
                                          or cross_referenced(p, sec_text.get(s, "")) for p in alts))
        if missing_list:
            problems.append(f"A7b: lettered-list or continuation claim(s) not in the packed "
                            f"evidence: {missing_list[:8]}")

        modes = ans.get("failure_mode") or []
        bad = [m for m in modes if m not in VOCAB]
        if bad:
            problems.append(f"A3: failure modes outside the vocabulary: {bad}")
        if not modes:
            problems.append("A3: no failure mode labelled")
        if COT_RE.search(answer):
            problems.append("A9: answer contains visible reasoning; the target must be the answer only")

        if problems:
            rejected.append({"id": qid, "audit": sorted({p[:2] for p in problems}),
                             "reason": "; ".join(problems), "needs_sme": bool(ans.get("needs_sme"))})
            continue

        ev_chars = src["evidence_chars_packed"]
        if ev_chars > EVIDENCE_BUDGET:
            flagged.append({"id": qid, "audit": "A8", "evidence_chars": ev_chars,
                            "note": "evidence over the packing budget; verify every paragraph is needed"})
        if len(answer) > ANSWER_MAX:
            flagged.append({"id": qid, "audit": "A9", "answer_chars": len(answer),
                            "note": "answer over the concision target; acceptable only for a genuine enumeration"})

        context = [{"source_type": "ecfr", "citation": f"21 CFR {p['section']}", "section": p["section"],
                    "heading": p["heading"],
                    "text": "\n".join(f"{x['path']} {x['text']}" for x in p["paragraphs"])}
                   for p in src["provisions"]]
        for g in src.get("guidance", []):
            context.append({"source_type": "fda_guidance", "section": None,
                            "citation": f"FDA Guidance: {g['title']} ({g['status']}, {g['issued_on']}, Docket {g['docket_number']})",
                            "heading": g["disclaimer"],
                            "text": "\n".join(c["text"] for c in g["chunks"])[:1200]})
        if has_absence:
            for chk in absences[qid]:
                context.append({"source_type": "verified_absence", "citation": "snapshot query",
                                "section": None, "heading": chk["check"],
                                "text": f"rows returned: {chk['row_count']}\n" +
                                        "\n".join(json.dumps(r) for r in chk["rows"][:8])})

        evidence_str = "\n\n".join(f"[{c['citation']}] {c['heading'] or ''}\n{c['text']}" for c in context)
        examples.append({
            "id": f"sft2-{qid}", "question": src["question"], "evidence": evidence_str,
            "ideal_answer": answer, "failure_mode": modes, "source_question_id": qid,
            "difficulty": src["difficulty"],
            "type": "regulatory_answer_construction", "category": src["type"],
            "context": context, "answer": answer,
            "citations": sorted(f"21 CFR {c}" for c in cited if c in evidence_sections or c in absent_ok),
            "generator": "sft/hand_authored/v2", "group": "", "snapshot_date": SNAPSHOT_DATE,
            "extra": {
                "domain": src["domain"], "key_citation_draft": src["key_citation_draft"],
                "key_elements": src["key_elements"], "key_sections": src["key_sections"],
                "supporting_sections": src["supporting_sections"],
                "baseline_verdict": src["baseline_verdict"],
                "baseline_failure_note": src["baseline_failure_note"],
                "attribution": src["attribution"], "needs_sme": bool(ans.get("needs_sme")),
                "in_v1_core": src["in_v1_core"], "revised_from_v1": bool(ans.get("revised_from_v1")),
                "revision_note": ans.get("revision_note"),
                "evidence_sections": sorted(evidence_sections),
                "evidence_chars": ev_chars, "evidence_chars_full": src["evidence_chars_full"],
                "paragraphs_kept": src["paragraphs_packed"], "paragraphs_available": src["paragraphs_full"],
                "verified_absence_checks": len(absences.get(qid, [])),
                "behaviour": ("abstention" if "abstention" in modes or "false_premise_handling" in modes
                              else "answer"),
            },
            "split": None,
        })

    # ---- leakage-safe, category-stratified split ---------------------------------------------
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for ex in examples:
        find(ex["id"])
        for sec in ex["extra"]["evidence_sections"]:
            union(ex["id"], f"sec:{sec}")
    comps: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        comps[find(ex["id"])].append(ex)
    comp_list = sorted(comps.values(), key=lambda c: (-len(c), c[0]["id"]))

    per_cat: dict[str, list[list[dict]]] = defaultdict(list)
    for comp in comp_list:
        per_cat[Counter(e["category"] for e in comp).most_common(1)[0][0]].append(comp)
    target_val = int(round(VALIDATION_FRACTION * len(examples)))
    val_count = 0
    for cat in sorted(per_cat):
        in_cat = sum(len(c) for c in per_cat[cat])
        quota = max(1, int(round(VALIDATION_FRACTION * in_cat)))
        taken = 0
        for comp in sorted(per_cat[cat],
                           key=lambda c: (len(c), hashlib.sha256((SEED + c[0]["id"]).encode()).hexdigest())):
            if taken + len(comp) <= quota and val_count + len(comp) <= target_val + 3:
                for ex in comp:
                    ex["split"] = "validation"
                taken += len(comp)
                val_count += len(comp)
    for comp in comp_list:
        group = comp[0]["id"].replace("sft2-", "grp-")
        for ex in comp:
            ex["split"] = ex["split"] or "train"
            ex["group"] = group

    sec_split: dict[str, set[str]] = defaultdict(set)
    for ex in examples:
        for sec in ex["extra"]["evidence_sections"]:
            sec_split[sec].add(ex["split"])
    leaks = sorted(s for s, v in sec_split.items() if len(v) > 1)

    train = [e for e in examples if e["split"] == "train"]
    val = [e for e in examples if e["split"] == "validation"]
    (args.out / "train.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in train))
    (args.out / "validation.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in val))

    ev = [e["extra"]["evidence_chars"] for e in examples] or [0]
    an = [len(e["answer"]) for e in examples] or [0]
    longest_ev = max(examples, key=lambda e: e["extra"]["evidence_chars"]) if examples else None
    longest_an = max(examples, key=lambda e: len(e["answer"])) if examples else None
    report = {
        "dataset": "benchmark-derived SFT v2 (regulatory answer construction)",
        "snapshot_date": SNAPSHOT_DATE,
        "totals": {
            "previous_total_v1": 57, "selected_rows": len(records), "admitted": len(examples),
            "added_vs_v1": len([e for e in examples if not e["extra"]["in_v1_core"]]),
            "carried_from_v1": len([e for e in examples if e["extra"]["in_v1_core"]]),
            "revised_from_v1": len([e for e in examples if e["extra"]["revised_from_v1"]]),
            "rejected": len(rejected), "train": len(train), "validation": len(val),
        },
        "by_category": dict(Counter(e["category"] for e in examples).most_common()),
        "by_failure_mode": dict(Counter(m for e in examples for m in e["failure_mode"]).most_common()),
        "by_difficulty": dict(Counter(e["difficulty"] for e in examples).most_common()),
        "by_cfr_part": dict(Counter(
            (e["extra"]["evidence_sections"][0].split(".")[0] if e["extra"]["evidence_sections"] else "none")
            for e in examples).most_common()),
        "by_behaviour": dict(Counter(e["extra"]["behaviour"] for e in examples).most_common()),
        "by_baseline_attribution": dict(Counter(e["extra"]["attribution"] for e in examples).most_common()),
        "lengths": {
            "evidence_mean": round(sum(ev) / len(ev)), "evidence_median": round(median(ev)),
            "evidence_max": max(ev), "evidence_over_budget": sum(1 for x in ev if x > EVIDENCE_BUDGET),
            "answer_mean": round(sum(an) / len(an)), "answer_median": round(median(an)),
            "answer_max": max(an), "answer_over_target": sum(1 for x in an if x > ANSWER_MAX),
            "answer_under_target": sum(1 for x in an if x < ANSWER_MIN),
            "longest_evidence_example": {"id": longest_ev["id"], "chars": longest_ev["extra"]["evidence_chars"]} if longest_ev else None,
            "longest_answer_example": {"id": longest_an["id"], "chars": len(longest_an["answer"])} if longest_an else None,
        },
        "split": {
            "method": "connected components over shared provisions, assigned whole, stratified by category",
            "components": len(comps), "target_validation_fraction": VALIDATION_FRACTION,
            "sections_in_both_splits": leaks, "leakage_free": not leaks,
            "source_questions_in_both": sorted(
                {e["source_question_id"] for e in train} & {e["source_question_id"] for e in val}),
            "validation_categories": dict(Counter(e["category"] for e in val).most_common()),
            "validation_failure_modes": dict(Counter(m for e in val for m in e["failure_mode"]).most_common()),
        },
        "audit": {
            "checks": ["A1 section support", "A2 no fabricated identifiers", "A3 mode vocabulary",
                       "A4 answer or explicit rejection", "A5 evidence present unless a pure refusal",
                       "A6 unique traceable ids", "A7 paragraph-level support",
                       "A7b lettered-list and continuation paragraph claims",
                       "A8 production-sized evidence", "A9 concise answer, no visible reasoning"],
            "rejected": rejected, "flagged": flagged,
            "needs_sme": sorted({e["source_question_id"] for e in examples if e["extra"]["needs_sme"]}
                                | {r["id"] for r in rejected if r.get("needs_sme")}),
            "examples_with_verified_absence_evidence": sum(
                1 for e in examples if e["extra"]["verified_absence_checks"]),
            "duplicate_ids": [i for i, n in Counter(e["id"] for e in examples).items() if n > 1],
        },
    }
    (args.out / "dataset_report2.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "audit"}, indent=2))
    a = report["audit"]
    print(f"\nrejected {len(a['rejected'])}  flagged {len(a['flagged'])}  needs_sme {len(a['needs_sme'])}")
    for r in a["rejected"][:25]:
        print(f"   REJECT {r['id']:8} {r['reason'][:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
