"""Stage A / A3: citation and grounding diagnostic.

Deliverable 5. Measures, for the delivered answer of all 300 acceptance rows, the five separate
questions the Stage A scope keeps apart - analysis only, nothing about the citation system is
redesigned here:

  L1  citation present / absent              a marker attached to a claim, or a CFR reference in prose
  L2  citation resolves to a real provision  rubric column M (fabricated citation) plus unresolved markers
  L3  citation points to the correct provision  does the cited set include the governing section
  L4  governing rule vs merely related words   right part / wrong section, vs wrong part entirely
  L5  unsupported claims despite a citation    rubric column L = 0 while a citation is present

A distinction the run data makes and a summary count would hide: `citations` in `answers.jsonl` is
the whole marker-to-source map the pipeline offered, not the citations the answer actually used. A
claim is only cited if its marker appears in the delivered text, so markers are extracted from the
answer itself and only those are counted as citations.

Column L (citation exact, hand-verified against the regulation snapshot) is the authority for
whether a citation supports its claim. The production validator's own support codes are reported
beside it as an independent machine signal, with their agreement rate - never as the judgement,
because `stage_a_proxy_check.py` shows that signal cannot carry a correctness verdict.

Read-only. Consumes `artifacts/stage_a/dataset.jsonl`, writes under `artifacts/stage_a/`.

    python3 scripts/stage_a_citations.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MARKER_RE = re.compile(r"\[(\d+)\]")
# a CFR reference written in prose: "21 CFR 820.10(b)(1)", "§ 820.1(a)", "part 830"
PROSE_CFR_RE = re.compile(r"(?:21\s*CFR\s*|§\s*)(\d{1,4})\.(\d+)((?:\([a-z0-9]+\))*)", re.I)
SECTION_RE = re.compile(r"(\d{1,4})\.(\d+)")
GUIDANCE_PREFIX = "FDA Guidance:"
# validator codes that assert a claim is not carried by the source it cites
SUPPORT_CODES = {
    "low_overlap_with_cited_source", "condition_not_in_cited_source", "provision_citation_mismatch",
    "paragraph_misattribution", "unsupported_claim", "unsupported_figure", "unsupported_premise",
    "synthesis_citation_gap", "uncited_statement",
}


def section_of(label: str) -> str | None:
    m = SECTION_RE.search(label or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def part_of(label: str) -> str | None:
    m = SECTION_RE.search(label or "")
    return m.group(1) if m else None


def key_sections(row: dict) -> list[str]:
    raw = row.get("rev_key_sections") or ""
    secs = [s.strip() for s in re.split(r"[;,]", raw) if s.strip()]
    if secs:
        return secs
    return sorted({f"{a}.{b}" for a, b, _ in PROSE_CFR_RE.findall(row.get("key_citation_draft") or "")})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "artifacts/stage_a/dataset.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_a")
    args = ap.parse_args()

    data = [json.loads(l) for l in args.dataset.read_text().splitlines() if l.strip()]
    rows = []
    for d in data:
        answer = d["answer"] or ""
        offered = {str(c["index"]): c["label"] for c in (d["citations"] or [])}
        used_idx = [i for i in dict.fromkeys(MARKER_RE.findall(answer))]
        used = [offered.get(i) for i in used_idx]
        unresolved = [i for i in used_idx if i not in offered]
        cited_labels = [u for u in used if u]
        cited_cfr = [u for u in cited_labels if not u.startswith(GUIDANCE_PREFIX)]
        cited_guidance = [u for u in cited_labels if u.startswith(GUIDANCE_PREFIX)]
        prose = sorted({f"{a}.{b}" for a, b, _ in PROSE_CFR_RE.findall(answer)})

        keys = key_sections(d)
        key_parts = {part_of(k) for k in keys if part_of(k)}
        cited_sections = {s for s in (section_of(c) for c in cited_cfr) if s}
        all_sections = cited_sections | set(prose)   # marker-attached plus prose references
        cited_parts = {part_of(s) for s in all_sections if part_of(s)}

        any_citation = bool(cited_labels) or bool(prose)
        matched = all_sections & set(keys)
        cites_governing = bool(keys) and bool(matched)
        # A match is worthless if the answer only repeated a section the question already named -
        # notably the Temporal/Version rows, which name the reserved section in the question itself.
        asked = {f"{a}.{b}" for a, b, _ in PROSE_CFR_RE.findall(d["question"] or "")}
        asked |= {f"{a}.{b}" for a, b in SECTION_RE.findall(d["question"] or "")}
        echoed = bool(matched) and matched <= asked
        rows.append({
            "id": d["id"], "type": d["type"], "result": d["result"], "L": d["L"], "M": d["M"], "N": d["N"],
            "citations_offered": len(offered),
            "markers_used": len(used_idx),
            "unresolved_markers": unresolved,
            "cited_cfr": cited_cfr,
            "cited_guidance_only": bool(cited_guidance) and not cited_cfr,
            "prose_cfr_refs": prose,
            "any_citation": any_citation,
            "key_sections": keys,
            "cites_governing": cites_governing,
            "governing_match_is_question_echo": echoed,
            "same_part_wrong_section": bool(keys) and not cites_governing and bool(cited_parts & key_parts),
            "wrong_part_only": bool(keys) and bool(cited_parts) and not (cited_parts & key_parts),
            "no_cfr_section_at_all": not all_sections,
            "support_codes": sorted(set(d["validation_initial_codes"] or []) & SUPPORT_CODES),
            "rev_invalid_markers": d["rev_invalid_markers"],
            "rev_cited_sections_absent": d["rev_cited_sections_absent"],
            "rev_guidance_in_answer": d["rev_guidance_in_answer"],
            "withheld": d["rev_withheld"] == "yes",
            "notes": d["notes"],
        })

    scored = [r for r in rows if r["result"] != "ERROR"]
    delivered = [r for r in scored if not r["withheld"]]   # rows where an answer actually reached the user

    def pct(n, d):
        return round(100 * n / d, 1) if d else None

    cited = [r for r in delivered if r["any_citation"]]
    summary = {
        "stage": "A", "deliverable": "5 - citation / grounding diagnostic",
        "rows": len(rows), "scored": len(scored),
        "withheld_no_answer_to_cite": sum(1 for r in scored if r["withheld"]),
        "delivered_answers": len(delivered),
        "L1_citation_present": {
            "with_citation": len(cited), "pct": pct(len(cited), len(delivered)),
            "without_any_citation": len(delivered) - len(cited),
            "marker_attached": sum(1 for r in delivered if r["cited_cfr"] or r["cited_guidance_only"]),
            "prose_reference_only": sum(1 for r in delivered if r["prose_cfr_refs"] and not r["cited_cfr"]),
            "guidance_cited_but_no_cfr_section": sum(1 for r in delivered if r["cited_guidance_only"]),
        },
        "L2_citation_resolves": {
            "fabricated_citation_rubric_M1": sum(1 for r in scored if r["M"] == 1),
            "fabricated_ids": [r["id"] for r in scored if r["M"] == 1],
            "unresolved_markers_rows": sum(1 for r in scored if r["unresolved_markers"]),
            "rows_with_invalid_markers_recorded": sum(1 for r in scored if (r["rev_invalid_markers"] or 0)),
            "rows_citing_an_absent_section": sum(1 for r in scored if r["rev_cited_sections_absent"]),
        },
        "L3_points_to_governing_provision": {
            "cites_governing_section": sum(1 for r in cited if r["cites_governing"]),
            "pct_of_cited_answers": pct(sum(1 for r in cited if r["cites_governing"]), len(cited)),
            "does_not": sum(1 for r in cited if not r["cites_governing"]),
            "match_was_only_a_section_the_question_named": sum(
                1 for r in cited if r["governing_match_is_question_echo"]),
            "located_a_governing_section_not_given_in_the_question": sum(
                1 for r in cited if r["cites_governing"] and not r["governing_match_is_question_echo"]),
        },
        "L4_governing_rule_vs_related_words": {
            "right_part_wrong_section": sum(1 for r in cited if r["same_part_wrong_section"]),
            "wrong_part_entirely": sum(1 for r in cited if r["wrong_part_only"]),
            "no_cfr_section_cited": sum(1 for r in cited if r["no_cfr_section_at_all"]),
        },
        "L5_unsupported_claims_despite_citation": {
            "citation_present_but_rubric_L0": sum(1 for r in cited if r["L"] == 0),
            "pct_of_cited_answers": pct(sum(1 for r in cited if r["L"] == 0), len(cited)),
            "citation_present_and_L1": sum(1 for r in cited if r["L"] == 1),
            "cites_governing_section_but_still_substantively_wrong_N_lt_2":
                sum(1 for r in cited if r["cites_governing"] and r["N"] != 2),
            "validator_support_codes_raised": sum(1 for r in cited if r["support_codes"]),
            "code_frequency": dict(Counter(c for r in cited for c in r["support_codes"]).most_common()),
        },
        # does the production validator's support signal agree with the hand-verified L column?
        "validator_support_vs_rubric_L": {
            "codes_raised_and_L0": sum(1 for r in cited if r["support_codes"] and r["L"] == 0),
            "codes_raised_and_L1": sum(1 for r in cited if r["support_codes"] and r["L"] == 1),
            "no_codes_and_L0": sum(1 for r in cited if not r["support_codes"] and r["L"] == 0),
            "no_codes_and_L1": sum(1 for r in cited if not r["support_codes"] and r["L"] == 1),
        },
        "by_question_type": {
            t: {
                "n": len([r for r in delivered if r["type"] == t]),
                "cites_governing": sum(1 for r in delivered if r["type"] == t and r["cites_governing"]),
                "L1": sum(1 for r in delivered if r["type"] == t and r["L"] == 1),
            }
            for t in sorted({r["type"] for r in delivered})
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "citation_grounding.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out / "citation_rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
