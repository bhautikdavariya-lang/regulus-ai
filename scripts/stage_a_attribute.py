"""Stage A: attribute every benchmark failure to a cause, by one documented decision procedure.

Deliverable 6's engine. Stage A's closing question is what share of the failures are genuinely
model-answer failures, what share are output-processing failures, what share are citation/grounding
failures, and what share cannot yet be determined. This applies one ordered rule set to all 300
rows; first match wins, so every row lands in exactly one category and the reason is reproducible.

    PASS                   the frozen rubric scored the row PASS
    UNDETERMINED           the verdict itself cannot be relied on:
                             - execution_error      technical failure, no answer exists
                             - evaluation_uncertain the draft key is in doubt, or the scorer flagged
                                                    the row borderline
    OUTPUT_PROCESSING      post-processing changed the verdict: the raw model output, delivered
                           unchanged, would have met the PASS rule. Taken from the hand review in
                           artifacts/stage_a/d2_candidate_review.jsonl, which covers every row where
                           this was possible (the raw text named the governing section and
                           post-processing then edited or replaced it).
    CITATION_GROUNDING     the substance was right and the row failed only on grounding:
                           N=2, O>=1, P=1, and L=0 or M=1 or Q=0.
    EVIDENCE_SUPPLY        the governing provision never reached the model. Computed here, not
                           taken from a label: the row names a governing section and no retrieved
                           evidence item carries that section. Undetermined with respect to model
                           capability - the model was never given the rule it was asked about.
    MODEL_ANSWER           everything else: the governing provision was supplied (or the question
                           needed none, as with a negative control), post-processing did not change
                           the verdict, and the answer was still wrong, partial or unresponsive.

Two overlays are reported separately, because they are real but do not change a verdict and so
must not inflate a category:

    output_processing_contributory   post-processing removed substantive content without changing
                                    the verdict (from the same hand review)
    no_answer_delivered             the pipeline withheld or declined, so the user got nothing

Read-only. Consumes `artifacts/stage_a/dataset.jsonl` and the D2 review, writes under
`artifacts/stage_a/`.

    python3 scripts/stage_a_attribute.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTION_RE = re.compile(r"(\d{1,4})\.(\d+)")


def section_of(label: str) -> str | None:
    m = SECTION_RE.search(label or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def key_sections(row: dict) -> list[str]:
    return [s.strip() for s in re.split(r"[;,]", row.get("rev_key_sections") or "") if s.strip()]


def attribute(d: dict, review: dict) -> tuple[str, str, str]:
    """(category, subcategory, the fact that decided it)."""
    if d["result"] == "PASS":
        return "PASS", "pass", "rubric verdict PASS"
    if d["result"] == "ERROR":
        return "UNDETERMINED", "execution_error", f"execution_status={d['execution_status']}: {d['error']}"
    if d["rev_key_possibly_wrong"] == "candidate":
        return "UNDETERMINED", "evaluation_uncertain", "the draft answer key is itself in doubt for this row"
    if d["rev_borderline"] == "Y":
        return "UNDETERMINED", "evaluation_uncertain", "the scorer flagged the row borderline"

    r = review.get(d["id"])
    if r and r["raw_would_pass"] == "yes":
        return "OUTPUT_PROCESSING", "verdict_changed", f"raw output would have passed; {r['loss']}"

    if d["N"] == 2 and (d["O"] or 0) >= 1 and d["P"] == 1:
        failed = [c for c, bad in (("L", d["L"] == 0), ("M", d["M"] == 1), ("Q", d["Q"] == 0)) if bad]
        return "CITATION_GROUNDING", "substance_right_grounding_wrong", f"N=2, O>=1, P=1; failed on {'+'.join(failed) or 'none'}"

    keys = key_sections(d)
    if keys:
        supplied = {section_of(e) for e in (d["evidence"] or [])}
        if not (set(keys) & supplied):
            return "EVIDENCE_SUPPLY", "governing_section_not_retrieved", \
                f"governing section(s) {','.join(keys)} absent from the {len(d['evidence'] or [])} retrieved sources"

    return "MODEL_ANSWER", ("no_governing_section_required" if not keys else "governing_section_supplied"), \
        ("the question required a refusal or a judgement, not a provision lookup" if not keys
         else "the governing section was supplied and the answer is still wrong, partial or unresponsive")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "artifacts/stage_a/dataset.jsonl")
    ap.add_argument("--review", type=Path, default=ROOT / "artifacts/stage_a/d2_candidate_review.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_a")
    args = ap.parse_args()

    data = [json.loads(l) for l in args.dataset.read_text().splitlines() if l.strip()]
    review = {}
    for line in args.review.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            if "id" in rec:
                review[rec["id"]] = rec

    rows = []
    for d in data:
        cat, sub, why = attribute(d, review)
        r = review.get(d["id"])
        rows.append({
            "id": d["id"], "type": d["type"], "domain": d["domain"], "result": d["result"],
            "category": cat, "subcategory": sub, "decided_by": why,
            "L": d["L"], "M": d["M"], "N": d["N"], "O": d["O"], "P": d["P"], "Q": d["Q"],
            # a named post-processing defect, or a raw output that stated the governing rule
            # correctly before processing touched it. A merely partial raw output whose only loss
            # was invented text is not contributory - the removal was right.
            "output_processing_contributory": bool(r and (r["defect"] or r["raw_substance"] == "yes")),
            "no_answer_delivered": d["rev_withheld"] == "yes" or d["model_called"] is False,
            "rev_mechanical_root_cause": d["rev_mechanical_root_cause"],
        })

    fails = [r for r in rows if r["result"] != "PASS"]
    n_fail = len(fails)
    counts = Counter(r["category"] for r in rows)
    fail_counts = Counter(r["category"] for r in fails)

    def pct(n, d):
        return round(100 * n / d, 1) if d else None

    summary = {
        "stage": "A", "deliverable": "6 - baseline failure attribution", "rows": len(rows),
        "verdicts": dict(Counter(r["result"] for r in rows).most_common()),
        "categories_all_rows": {c: {"n": n, "pct_of_300": pct(n, len(rows))} for c, n in counts.most_common()},
        "answer_to_the_stage_a_question": {
            "denominator": "the 290 rows that are not a rubric PASS",
            "n": n_fail,
            "model_answer_failures": {"n": fail_counts["MODEL_ANSWER"], "pct": pct(fail_counts["MODEL_ANSWER"], n_fail)},
            "output_processing_failures": {"n": fail_counts["OUTPUT_PROCESSING"], "pct": pct(fail_counts["OUTPUT_PROCESSING"], n_fail)},
            "citation_grounding_failures": {"n": fail_counts["CITATION_GROUNDING"], "pct": pct(fail_counts["CITATION_GROUNDING"], n_fail)},
            "evidence_supply_failures": {"n": fail_counts["EVIDENCE_SUPPLY"], "pct": pct(fail_counts["EVIDENCE_SUPPLY"], n_fail)},
            "cannot_yet_be_determined": {"n": fail_counts["UNDETERMINED"], "pct": pct(fail_counts["UNDETERMINED"], n_fail)},
        },
        "subcategories": dict(Counter(f"{r['category']}/{r['subcategory']}" for r in rows).most_common()),
        # Where a category's size depends on an unresolved judgement, give the bound rather than a
        # guess. Six UNDETERMINED rows scored N=2 and failed only on a citation the scorer judged
        # borderline; if an SME ruled those citation defects disqualifying they would move to
        # CITATION_GROUNDING, and if not they would move to PASS.
        "sensitivity": {
            "citation_grounding_upper_bound": {
                "n": fail_counts["CITATION_GROUNDING"] + sum(
                    1 for r in rows if r["category"] == "UNDETERMINED" and r["N"] == 2),
                "pct": pct(fail_counts["CITATION_GROUNDING"] + sum(
                    1 for r in rows if r["category"] == "UNDETERMINED" and r["N"] == 2), n_fail),
                "borderline_ids": [r["id"] for r in rows if r["category"] == "UNDETERMINED" and r["N"] == 2],
                "note": "substance scored correct (N=2); only the citation verdict is unresolved",
            },
            # The one judgement call in the procedure. On a part-level plan the retriever supplies
            # the part's passages; `ECFR_EXACT_PART` filters `ordinal = 0`
            # (src/regulus/retrieval/sql.py:64), so the governing section reaches the prompt with at
            # most one paragraph and its requirement text generally does not. Those rows are counted
            # as EVIDENCE_SUPPLY here. Counting them the other way - the right part was retrieved,
            # so call the evidence sufficient - gives this bound instead.
            "if_part_level_retrieval_counts_as_evidence_supplied": {
                "model_answer": {
                    "n": fail_counts["MODEL_ANSWER"] + len(part_only := [
                        r for r in rows if r["category"] == "EVIDENCE_SUPPLY"
                        and r["decided_by"].startswith("governing section")
                        and (d := next(x for x in data if x["id"] == r["id"]))["rev_key_retrieved"] == "part_only"]),
                    "pct": pct(fail_counts["MODEL_ANSWER"] + len(part_only), n_fail),
                },
                "evidence_supply": {
                    "n": fail_counts["EVIDENCE_SUPPLY"] - len(part_only),
                    "pct": pct(fail_counts["EVIDENCE_SUPPLY"] - len(part_only), n_fail),
                },
                "rows_moved": len(part_only),
            },
            "undetermined_rows_with_wrong_substance": {
                "n": sum(1 for r in rows if r["category"] == "UNDETERMINED" and r["N"] != 2),
                "note": "these would move to MODEL_ANSWER or EVIDENCE_SUPPLY, not to a pass",
            },
        },
        "overlays": {
            "output_processing_contributory": {
                "n": sum(1 for r in rows if r["output_processing_contributory"]),
                "ids": [r["id"] for r in rows if r["output_processing_contributory"]],
            },
            "no_answer_delivered": {
                "n": sum(1 for r in rows if r["no_answer_delivered"]),
                "by_category": dict(Counter(r["category"] for r in rows if r["no_answer_delivered"]).most_common()),
            },
        },
        "by_question_type": {
            t: dict(Counter(r["category"] for r in rows if r["type"] == t).most_common())
            for t in sorted({r["type"] for r in rows})
        },
        # agreement with the free-text cause the scorer recorded per row, as a cross-check only:
        # that label was assigned by hand and has no decision procedure behind it.
        "cross_check_vs_reviewer_root_cause": {
            cat: dict(Counter(r["rev_mechanical_root_cause"] for r in rows if r["category"] == cat).most_common(6))
            for cat in counts
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "attribution.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out / "attribution_rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    print(json.dumps({k: summary[k] for k in
                      ("verdicts", "categories_all_rows", "answer_to_the_stage_a_question", "subcategories", "sensitivity", "overlays")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
