"""Stage A / D2: output-integrity diagnostic - what happens between RAW MODEL OUTPUT and FINAL ANSWER.

Deliverable 4. For all 300 acceptance rows this compares `raw_model_output` with the delivered
`answer` and attributes every difference to the pipeline stage that caused it, using the stage
fields the run already recorded (`repair`, `fallback_type`, `validation_initial/final`,
`stop_reason`, `model_called`). Nothing is re-executed: the question is what the recorded pipeline
did to text it had already generated.

Per row it records:

  change_class        none | declined_before_model | replaced_by_safe_message | edited | appended_only
  stages              the individual repair operations that fired, in the order the pipeline names them
  removed_sentences   sentences present in the raw output and absent from the final answer
  appended_chars      characters the pipeline added (verbatim provision text, truncation notice)
  identifiers_lost    CFR identifiers the raw output named that the final answer does not
  key_section_in_raw / key_section_in_final
                      whether the benchmark's governing section is named in each text - the one
                      content test that does not depend on lexical overlap with the answer key

It then builds the **corruption candidate set**: FAIL rows where post-processing removed or replaced
substantive text. Only those rows can possibly be output-processing failures rather than model
failures, so the set bounds how large that category could be before any row is read.

Read-only. Consumes `artifacts/stage_a/dataset.jsonl`, writes under `artifacts/stage_a/`.

    python3 scripts/stage_a_output_integrity.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# the canned texts the fallback builder substitutes for a generated answer (regulus.rag.fallback)
SAFE_MESSAGE_MARKERS = (
    "could not be validated against the retrieved regulatory evidence",
    "The retrieved sources were not verified to answer",
    "does not contain a provision",
    "could not be established from",
    "outside the scope",
)
TRUNCATION_NOTICE = "(Incomplete: generation stopped at the token limit"
# operations that delete or overwrite model text, as opposed to adding to it
DESTRUCTIVE = {
    "unvalidated_answer_withheld", "failed_repair_fallback", "extractive_replacement", "safe_message",
    "mismatched_statements_replaced", "misattributed_statements_replaced", "invented_conditions_removed",
    "invalid_citations_removed", "premise_not_established", "provision_not_found",
}
ADDITIVE = {"appended_missing_provisions", "appended_missing_items", "truncation_noted"}

CFR_RE = re.compile(r"\b(?:21\s*CFR\s*)?(\d{1,4}\.\d+(?:\([a-z0-9]+\))*)")
SENT_RE = re.compile(r"(?<=[.;:])\s+|\n+")
MARKER_RE = re.compile(r"\[\d+\]")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_RE.split(text or "") if s.strip()]


def bare(text: str) -> str:
    """Text with citation markers dropped and whitespace collapsed.

    The repair stage calls `attach_trailing_markers`, which moves `[n]` markers inside the sentence
    they belong to. Comparing raw and final verbatim therefore reports a sentence as deleted when
    only its marker moved, so every content comparison here is made on marker-free text.
    """
    return re.sub(r"\s+", " ", MARKER_RE.sub(" ", text or "")).strip()


def identifiers(text: str) -> set[str]:
    return set(CFR_RE.findall(text or ""))


def key_sections(row: dict) -> list[str]:
    """The governing section(s) from the forensic record, falling back to the draft key string."""
    raw = row.get("rev_key_sections") or ""
    secs = [s.strip() for s in re.split(r"[;,]", raw) if s.strip()]
    return secs or sorted(identifiers(row.get("key_citation_draft") or ""))


def classify(row: dict, raw: str, final: str) -> tuple[str, list[str]]:
    stages = [s for s in (row.get("repair") or "").split("+") if s]
    if row.get("fallback_type") and row["fallback_type"] not in stages:
        stages.append(row["fallback_type"])
    if row.get("model_called") is False:
        return "declined_before_model", stages or ["pre_model_decline"]
    if norm(raw) == norm(final):
        return "none", stages
    if bare(raw) == bare(final):
        return "markers_only", stages
    if any(m in final for m in SAFE_MESSAGE_MARKERS) and bare(raw) not in bare(final):
        return "replaced_by_safe_message", stages
    if bare(raw) in bare(final):
        return "appended_only", stages
    return "edited", stages


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "artifacts/stage_a/dataset.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_a")
    args = ap.parse_args()

    data = [json.loads(l) for l in args.dataset.read_text().splitlines() if l.strip()]
    rows = []
    for d in data:
        raw, final = d["raw_model_output"] or "", d["answer"] or ""
        change_class, stages = classify(d, raw, final)
        bf = bare(final)
        removed = [s for s in sentences(raw) if bare(s) and bare(s) not in bf]
        lost = sorted(identifiers(raw) - identifiers(final))
        keys = key_sections(d)
        rows.append({
            "id": d["id"], "type": d["type"], "result": d["result"], "N": d["N"], "L": d["L"],
            "change_class": change_class,
            "stages": stages,
            "destructive_stages": sorted(set(stages) & DESTRUCTIVE),
            "additive_stages": sorted(set(stages) & ADDITIVE),
            "raw_chars": len(raw), "final_chars": len(final),
            "char_delta": len(final) - len(raw),
            "removed_sentences": removed,
            "removed_sentence_count": len(removed),
            "removed_chars": sum(len(s) for s in removed),
            "appended_chars": max(0, len(bf) - len(bare(raw))) if change_class == "appended_only" else None,
            "identifiers_lost": lost,
            "truncation_noticed": TRUNCATION_NOTICE in final,
            "stop_reason": d["stop_reason"],
            "validation_initial": d["validation_initial"],
            "validation_final": d["validation_final"],
            "key_sections": keys,
            "key_section_in_raw": bool(keys) and any(k in raw for k in keys),
            "key_section_in_final": bool(keys) and any(k in final for k in keys),
            "rev_withheld": d["rev_withheld"],
            "rev_truncated": d["rev_truncated"],
            "notes": d["notes"],
            "rev_reviewer_note": d["rev_reviewer_note"],
        })

    # ---- corruption candidate set -------------------------------------------------------------
    # A row can only be an output-processing failure if the delivered answer failed AND
    # post-processing removed or replaced model text. Appends and no-ops cannot have destroyed
    # anything, and a PASS by definition was not damaged.
    candidates = [r for r in rows
                  if r["result"] == "FAIL"
                  and r["change_class"] in ("replaced_by_safe_message", "edited")
                  and (r["removed_chars"] > 0 or r["destructive_stages"])]
    # within the candidates, the subset where the raw output named the governing section and the
    # delivered answer does not: the only mechanically visible sign that processing lost the right rule
    lost_key = [r for r in candidates if r["key_section_in_raw"] and not r["key_section_in_final"]]

    summary = {
        "stage": "A", "deliverable": "4 - D2 output-integrity diagnostic", "rows": len(rows),
        "change_class": dict(Counter(r["change_class"] for r in rows).most_common()),
        "change_class_by_result": {
            cls: dict(Counter(r["result"] for r in rows if r["change_class"] == cls).most_common())
            for cls in dict(Counter(r["change_class"] for r in rows))
        },
        "stage_frequency": dict(Counter(s for r in rows for s in r["stages"]).most_common()),
        # `markers_only` rows keep every word the model wrote; what changed is citation markers.
        # Stripping an INVALID marker leaves the claim standing with no citation at all, which is a
        # citation-integrity event even though no prose was lost - so the two causes are split out.
        "markers_only_breakdown": {
            "invalid_citation_markers_stripped": sum(
                1 for r in rows if r["change_class"] == "markers_only"
                and "invalid_citations_removed" in r["stages"]),
            "marker_reattachment_only": sum(
                1 for r in rows if r["change_class"] == "markers_only"
                and "invalid_citations_removed" not in r["stages"]),
        },
        "text_unchanged_rows": sum(1 for r in rows if r["change_class"] == "none"),
        "text_changed_rows": sum(1 for r in rows if r["change_class"] not in ("none", "declined_before_model")),
        "rows_losing_sentences": sum(1 for r in rows if r["removed_sentence_count"]),
        "sentences_removed_total": sum(r["removed_sentence_count"] for r in rows),
        "chars_removed_total": sum(r["removed_chars"] for r in rows),
        "rows_losing_identifiers": sum(1 for r in rows if r["identifiers_lost"]),
        "rows_truncated_notice": sum(1 for r in rows if r["truncation_noticed"]),
        "rows_stopped_on_repetition": sum(1 for r in rows if r["stop_reason"] == "repetition"),
        "key_section_named": {
            "in_raw_only": sum(1 for r in rows if r["key_section_in_raw"] and not r["key_section_in_final"]),
            "in_final_only": sum(1 for r in rows if r["key_section_in_final"] and not r["key_section_in_raw"]),
            "in_both": sum(1 for r in rows if r["key_section_in_raw"] and r["key_section_in_final"]),
            "in_neither": sum(1 for r in rows if not r["key_section_in_raw"] and not r["key_section_in_final"]),
        },
        "corruption_candidates": {
            "count": len(candidates),
            "pct_of_all_rows": round(100 * len(candidates) / len(rows), 1),
            "ids": [r["id"] for r in candidates],
            "by_change_class": dict(Counter(r["change_class"] for r in candidates).most_common()),
            "lost_governing_section_in_processing": {"count": len(lost_key), "ids": [r["id"] for r in lost_key]},
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "output_integrity.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out / "output_integrity_rows.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    print(json.dumps({k: v for k, v in summary.items() if k != "corruption_candidates"}, indent=2))
    c = summary["corruption_candidates"]
    print(f"\ncorruption candidates: {c['count']} ({c['pct_of_all_rows']}% of rows) {c['by_change_class']}")
    print(f"lost the governing section in processing: {c['lost_governing_section_in_processing']['count']} "
          f"{c['lost_governing_section_in_processing']['ids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
