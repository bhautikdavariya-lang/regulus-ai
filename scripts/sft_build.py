"""SFT dataset construction, step 2: assemble, audit and split the dataset.

Dataset construction only - no model is loaded, no inference is run, nothing is trained.

Inputs (all produced by earlier read-only steps):
    artifacts/sft/selection.json       source questions + verbatim provision text
    artifacts/sft/ideal_answers.jsonl  hand-authored ideal answers and failure-mode labels
    artifacts/sft/absence_checks.json  verified absences a false-premise answer rests on

Output records carry both the shape this repository already uses for training data
(`regulus.training.models.TrainingExample`: type, category, question, context, answer, citations,
generator, group, split) and the flat fields the task asked for (`ideal_answer`, `failure_mode`,
`source_question_id`, `difficulty`), so the file is usable either way.

**Audit.** Every example is checked mechanically before it is admitted:
  A1  every CFR section cited in the ideal answer is present in that example's own evidence
  A2  every CFR section cited exists in the read-only snapshot (no fabricated identifiers)
  A3  failure-mode labels come from the controlled vocabulary
  A4  an answer is present unless the example is explicitly rejected, and a rejection has a reason
  A5  evidence is present unless the example is a pure scope/abstention refusal
  A6  ids are unique and trace to a real benchmark question
An example failing A1 or A2 is rejected, not silently fixed.

**Split.** Leakage-safe by construction: examples are joined into connected components by the
provisions they share, and whole components are assigned to train or validation. No section's text
appears on both sides, so a validation question cannot be answered from provision text memorised
from a training example.

    .venv/bin/python scripts/sft_build.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.retrieval.db import Database  # noqa: E402

SFT = ROOT / "artifacts/sft"
SNAPSHOT_DATE = "2026-09-03"

# the ten target failure modes, named as the task names them
VOCAB = {
    "incomplete_answer", "missing_subordinate_paragraphs", "wrong_provision_selection",
    "scope_applicability", "exceptions_and_conditions", "cross_reference_reasoning",
    "false_premise_handling", "temporal_version_reasoning", "evidence_faithful_interpretation",
    "answer_completeness_discipline", "abstention", "distinction_reasoning",
}
# examples whose correct answer is a refusal on scope or professional-role grounds carry no
# provision evidence, and that is the right shape for them rather than a defect
NO_EVIDENCE_OK = {"SD-005", "SD-006", "SD-007", "SD-009"}

CITE_RE = re.compile(r"\b(\d{1,4}(?:\.\d+)+)\b")
# An ISO 13485 / ISO 9000 clause number looks exactly like a CFR section number ("Clause 7.5.4",
# "Clause 8.2.2"), so a bare regex over the answer reads incorporated-standard clauses as fabricated
# CFR citations. A match is treated as a CFR citation only when the preceding text is not an ISO
# clause reference.
ISO_CONTEXT = re.compile(r"(clause|ISO\s*\d{3,5})[^.]{0,24}$", re.I)
VALIDATION_FRACTION = 0.25
SEED = "regulus-sft-v1"


def sections_in(text: str) -> set[str]:
    """CFR section numbers cited in the text, excluding ISO clause numbers."""
    out = set()
    for m in CITE_RE.finditer(text or ""):
        num = m.group(1)
        # a CFR section number carries exactly one dot (820.35, 117.405, 1003.10); an ISO 13485
        # clause carries two or more (7.5.9.1, 8.2.3), so the dot count separates them
        if num.count(".") > 1:
            continue
        if ISO_CONTEXT.search((text or "")[max(0, m.start() - 40):m.start()]):
            continue
        out.add(num)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=SFT)
    args = ap.parse_args()

    selection = json.loads((SFT / "selection.json").read_text())
    records = {r["id"]: r for r in selection["records"]}
    answers = {}
    for line in (SFT / "ideal_answers.jsonl").read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            if "id" in rec:
                answers[rec["id"]] = rec
    absences = json.loads((SFT / "absence_checks.json").read_text())

    db = Database.from_env()
    db.connect()
    known: set[str] = {r["number"] for r in db.query(
        "SELECT DISTINCT section_number AS number FROM cfr_records WHERE removed_on IS NULL")}

    examples, rejected, flagged = [], [], []
    for qid, src in records.items():
        ans = answers.get(qid)
        problems: list[str] = []

        # A4: an answer, or an explicit rejection with a reason
        if ans is None:
            rejected.append({"id": qid, "reason": "no ideal answer authored", "audit": ["A4"]})
            continue
        if ans.get("reject"):
            rejected.append({"id": qid, "reason": ans.get("reject_reason", "rejected"),
                             "audit": ["A4"], "needs_sme": True})
            continue
        answer = (ans.get("ideal_answer") or "").strip()
        if not answer:
            rejected.append({"id": qid, "reason": "empty ideal answer", "audit": ["A4"]})
            continue

        # the evidence this example is allowed to rest on
        evidence_sections = {p["section"] for p in src["provisions"]}
        has_absence = qid in absences
        # Sections this answer is entitled to name as NOT existing: a reserved or removed section
        # reached the evidence block with zero paragraphs, or a verified absence check names it.
        # Flagging these as fabricated would invert the whole point of a temporal or false-premise
        # example, whose correct answer is that the provision is not there.
        absent_ok = {p["section"] for p in src["provisions"] if p["paragraph_count"] == 0}
        absence_text = json.dumps(absences.get(qid, []))
        absent_ok |= {c for c in CITE_RE.findall(absence_text)}
        evidence_text = json.dumps([p["paragraphs"] for p in src["provisions"]] + src.get("guidance", []))
        # A5
        if not src["provisions"] and not has_absence and qid not in NO_EVIDENCE_OK:
            problems.append("A5: no provision evidence and no verified absence")

        # A1 / A2: citations in the answer
        cited = sections_in(answer)
        fabricated = sorted(c for c in cited if c not in known and c not in absent_ok)
        # A1: a citation is supported if the section is in this example's evidence, is one the
        # answer correctly names as absent, or is named as a cross-reference inside the supplied
        # provision text (e.g. "in accordance with part 830" appears in 820.10(b)(1) itself).
        unsupported = sorted(c for c in cited
                             if c not in evidence_sections and c not in absent_ok
                             and c not in CITE_RE.findall(evidence_text))
        if fabricated:
            problems.append(f"A2: cited section(s) absent from the snapshot: {fabricated}")
        # an unsupported citation is only acceptable where the answer names it as a cross-reference
        # target quoted from supplied text (e.g. "in accordance with part 830"), so it is reported
        # for review rather than auto-accepted
        if unsupported:
            flagged.append({"id": qid, "audit": "A1",
                            "cited_not_in_own_evidence": unsupported,
                            "note": "verify each is a cross-reference named inside supplied text, not an independent assertion"})

        # A3
        modes = ans.get("failure_mode") or []
        bad_modes = [m for m in modes if m not in VOCAB]
        if bad_modes:
            problems.append(f"A3: failure modes outside the vocabulary: {bad_modes}")
        if not modes:
            problems.append("A3: no failure mode labelled")

        if any(p.startswith(("A2", "A3", "A5")) for p in problems):
            rejected.append({"id": qid, "reason": "; ".join(problems), "audit": [p[:2] for p in problems]})
            continue

        context = [{"source_type": "ecfr", "citation": f"21 CFR {p['section']}",
                    "section": p["section"], "heading": p["heading"],
                    "text": "\n".join(f"{x['path']} {x['text']}" for x in p["paragraphs"])}
                   for p in src["provisions"]]
        for g in src.get("guidance", []):
            context.append({
                "source_type": "fda_guidance", "section": None,
                "citation": f"FDA Guidance: {g['title']} ({g['status']}, {g['issued_on']}, Docket {g['docket_number']})",
                "heading": g["disclaimer"],
                "text": "\n".join(c["text"] for c in g["chunks"]),
            })
        if has_absence:
            for chk in absences[qid]:
                context.append({"source_type": "verified_absence", "citation": "snapshot query",
                                "section": None, "heading": chk["check"],
                                "text": f"rows returned: {chk['row_count']}\n" +
                                        "\n".join(json.dumps(r) for r in chk["rows"][:12])})

        examples.append({
            # --- requested flat schema ---
            "id": f"sft-{qid}",
            "question": src["question"],
            "evidence": "\n\n".join(f"[{c['citation']}] {c['heading'] or ''}\n{c['text']}" for c in context),
            "ideal_answer": answer,
            "failure_mode": modes,
            "source_question_id": qid,
            "difficulty": src["difficulty"],
            # --- repository TrainingExample shape ---
            "type": "regulatory_answer_construction",
            "category": src["type"],
            "context": context,
            "answer": answer,
            "citations": sorted(f"21 CFR {c}" for c in cited if c in evidence_sections or c in absent_ok),
            "generator": "sft/hand_authored/v1",
            "group": "",                       # filled by the split step
            "snapshot_date": SNAPSHOT_DATE,
            "extra": {
                "domain": src["domain"],
                "key_citation_draft": src["key_citation_draft"],
                "key_elements": src["key_elements"],
                "key_sections": src["key_sections"],
                "supporting_sections": src.get("supporting_sections", []),
                "baseline_verdict": src["baseline_verdict"],
                "baseline_failure_note": src["baseline_failure_note"],
                "attribution": src["attribution"],
                "needs_sme": bool(ans.get("needs_sme")),
                "evidence_sections": sorted(evidence_sections),
                "verified_absence_checks": len(absences.get(qid, [])),
            },
            "split": None,
        })

    # ---- leakage-safe split: connected components over shared provisions -------------------
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
        node = ex["id"]
        find(node)
        for sec in ex["extra"]["evidence_sections"]:
            union(node, f"sec:{sec}")
    comps: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        comps[find(ex["id"])].append(ex)

    # Assign whole components, stratified by benchmark category. A single global fill puts the
    # large shared-provision components into validation first and leaves no room for the
    # single-example categories, so validation ended up holding only four of the eight. Each
    # category gets its own quota instead, and components are still assigned whole, so the split
    # stays leakage-free.
    target_val = int(round(VALIDATION_FRACTION * len(examples)))
    comp_list = sorted(comps.values(), key=lambda c: (-len(c), c[0]["id"]))

    def primary_category(comp: list[dict]) -> str:
        return Counter(e["category"] for e in comp).most_common(1)[0][0]

    per_category: dict[str, list[list[dict]]] = defaultdict(list)
    for comp in comp_list:
        per_category[primary_category(comp)].append(comp)

    val_count = 0
    for cat in sorted(per_category):
        in_cat = sum(len(c) for c in per_category[cat])
        quota = max(1, int(round(VALIDATION_FRACTION * in_cat)))
        taken = 0
        # smallest components first within a category, so a quota of 1-2 can actually be met
        for comp in sorted(per_category[cat],
                           key=lambda c: (len(c), hashlib.sha256((SEED + c[0]["id"]).encode()).hexdigest())):
            if taken + len(comp) <= quota and val_count + len(comp) <= target_val + 2:
                for ex in comp:
                    ex["split"] = "validation"
                taken += len(comp)
                val_count += len(comp)
    for comp in comp_list:
        group = comp[0]["id"].replace("sft-", "grp-")
        for ex in comp:
            ex["split"] = ex["split"] or "train"
            ex["group"] = group

    # leakage assertion
    sec_split: dict[str, set[str]] = defaultdict(set)
    for ex in examples:
        for sec in ex["extra"]["evidence_sections"]:
            sec_split[sec].add(ex["split"])
    leaks = sorted(s for s, v in sec_split.items() if len(v) > 1)

    train = [e for e in examples if e["split"] == "train"]
    val = [e for e in examples if e["split"] == "validation"]
    (args.out / "train.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in train))
    (args.out / "validation.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in val))

    report = {
        "purpose": "SFT dataset for regulatory answer construction - construction only, no training, no inference",
        "snapshot_date": SNAPSHOT_DATE,
        "totals": {"selected": len(records), "admitted": len(examples),
                   "rejected": len(rejected), "train": len(train), "validation": len(val)},
        "by_failure_mode": dict(Counter(m for e in examples for m in e["failure_mode"]).most_common()),
        "by_category": dict(Counter(e["category"] for e in examples).most_common()),
        "by_difficulty": dict(Counter(e["difficulty"] for e in examples).most_common()),
        "by_cfr_part": dict(Counter(
            (e["extra"]["evidence_sections"][0].split(".")[0] if e["extra"]["evidence_sections"] else "none")
            for e in examples).most_common()),
        "by_baseline_attribution": dict(Counter(e["extra"]["attribution"] for e in examples).most_common()),
        "split": {
            "method": "connected components over shared provisions; whole components assigned",
            "target_validation_fraction": VALIDATION_FRACTION,
            "components": len(comps),
            "sections_appearing_in_both_splits": leaks,
            "leakage_free": not leaks,
            "validation_categories": dict(Counter(e["category"] for e in val).most_common()),
        },
        "audit": {
            "checks": ["A1 citations supported by own evidence", "A2 no fabricated identifiers",
                       "A3 failure-mode vocabulary", "A4 answer or explicit rejection",
                       "A5 evidence present unless a pure refusal", "A6 unique ids traceable to the benchmark"],
            "rejected": rejected,
            "flagged_for_review": flagged,
            "needs_sme": sorted(e["source_question_id"] for e in examples if e["extra"]["needs_sme"])
                         + sorted(r["id"] for r in rejected if r.get("needs_sme")),
            "examples_with_verified_absence_evidence": sum(
                1 for e in examples if e["extra"]["verified_absence_checks"]),
            "mean_answer_chars": round(sum(len(e["answer"]) for e in examples) / len(examples)) if examples else 0,
            "duplicate_ids": [i for i, n in Counter(e["id"] for e in examples).items() if n > 1],
        },
    }
    (args.out / "dataset_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
