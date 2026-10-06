"""Evidence-supply experiment: control vs treatment comparison.

Deliverables 6-9. Joins the arm runs, computes the evidence-supply, regression/safety, size and
latency comparisons mechanically, and reports which rows need a fresh substantive verdict.

Substantive PASS/FAIL is never computed here. It comes from hand scoring under
`regulus_substantive_rubric_v1`, read from `artifacts/stage_b/verdicts_<arm>.jsonl`. A treatment row
whose evidence hash and answer are byte-identical to control inherits control's frozen Stage A
verdict - decoding is greedy, so identical evidence means an identical answer and re-scoring it
would be re-scoring the same text.

    .venv/bin/python scripts/es_compare.py                      # mechanical comparison + scoring queue
    .venv/bin/python scripts/es_compare.py --with-verdicts      # add the PASS/FAIL comparison
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE_B = ROOT / "artifacts/stage_b"

# validator codes that stand in for the safety regressions the experiment must watch
HALLUCINATION_CODES = {"invented_condition", "unsupported_claim", "unsupported_figure",
                       "unsupported_premise", "invalid_citation", "condition_not_in_cited_source"}
WITHHELD_FALLBACKS = {"unvalidated_answer_withheld", "provision_not_found", "value_not_established",
                      "out_of_scope", "premise_not_established"}

# The run records `metadata["validation"]["initial"]["codes"]` etc. under the wrong keys, so the
# validator's own code stream is absent from all three arms (absent identically, so the arms stay
# comparable). The safety signals below are therefore derived from the recorded text, which is
# complete: a withheld answer is recognised by the fallback builder's own wording, and a generation
# that never emitted end-of-turn is recognised by hitting its pinned allowance exactly.
SAFE_MESSAGE_MARKERS = (
    "could not be validated against the retrieved regulatory evidence",
    "The retrieved sources were not verified to answer",
    "do not provide enough information",
    "does not contain a provision",
    "could not be established from",
    "outside the scope",
)
TRUNCATION_NOTICE = "(Incomplete: generation stopped at the token limit"


def load(arm: str) -> dict[str, dict]:
    p = STAGE_B / f"run_{arm}.jsonl"
    if not p.exists():
        return {}
    return {json.loads(l)["question_id"]: json.loads(l)
            for l in p.read_text().splitlines() if l.strip()}


def strata() -> dict[str, str]:
    return {json.loads(l)["id"]: json.loads(l)["stratum"]
            for l in (STAGE_B / "phase1_rows.jsonl").read_text().splitlines() if l.strip()}


def verdicts(arm: str) -> dict[str, dict]:
    p = STAGE_B / f"verdicts_{arm}.jsonl"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if "id" in r:
                out[r["id"]] = r
    return out


def stage_a_verdicts() -> dict[str, dict]:
    return {json.loads(l)["id"]: json.loads(l)
            for l in (ROOT / "artifacts/stage_a/dataset.jsonl").read_text().splitlines() if l.strip()}


def num(x, default=0):
    return x if isinstance(x, (int, float)) else default


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 1) if xs else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", default="control,es1,es1_deep")
    ap.add_argument("--with-verdicts", action="store_true")
    args = ap.parse_args()

    arms = [a for a in args.arms.split(",") if a.strip()]
    runs = {a: load(a) for a in arms}
    present = [a for a in arms if runs[a]]
    strat = strata()
    base = stage_a_verdicts()
    control = runs.get("control", {})
    ids = sorted(control) or sorted(next(iter(runs.values())))

    per_row = []
    for qid in ids:
        c = control.get(qid, {})
        row = {"id": qid, "stratum": strat.get(qid), "key_sections": c.get("key_sections"),
               "question": (c.get("question") or "")[:110]}
        for a in present:
            r = runs[a].get(qid, {})
            codes = set(r.get("validation_initial_codes") or [])
            # Derived here, not read from the run record, so every arm is measured the same way:
            # supply means the governing section's TEXT is among the selected evidence. A section
            # number named in the prompt by the question or by a guidance chunk is not supply.
            gp = r.get("governing_presence") or {}
            row[a] = {
                "governing_text_supplied": any(v.get("in_evidence") for v in gp.values()) if gp else None,
                "governing_named_in_prompt": any(v.get("named_in_prompt") for v in gp.values()) if gp else None,
                "governing_paragraphs": sum(v.get("paragraphs_in_evidence", 0) for v in gp.values()),
                "carve_out_present": r.get("carve_out_present"),
                "n_blocks": r.get("n_evidence_blocks"),
                "evidence_tokens": r.get("evidence_tokens"),
                "prompt_tokens": r.get("prompt_tokens"),
                "evidence_sha16": r.get("evidence_sha16"),
                "answer": r.get("answer"),
                "withheld": (r.get("fallback_type") in WITHHELD_FALLBACKS
                             or any(m in (r.get("answer") or "") for m in SAFE_MESSAGE_MARKERS)),
                "truncation_noticed": TRUNCATION_NOTICE in (r.get("answer") or ""),
                "hit_token_ceiling": (num(r.get("generated_tokens"), -1) >= num(r.get("max_new_tokens"), 10 ** 9)),
                "fallback_type": r.get("fallback_type"),
                "hallucination_codes": sorted(codes & HALLUCINATION_CODES),
                "generated_tokens": r.get("generated_tokens"),
                "stop_reason": r.get("stop_reason"),
                "seconds": r.get("seconds"),
                "cites_governing": bool(r.get("citations")) and any(
                    k in (ct.get("label") or "") for k in (r.get("key_sections") or [])
                    for ct in (r.get("citations") or [])),
                "error": r.get("error"),
            }
        for a in present:
            if a == "control":
                continue
            row[a]["evidence_changed"] = (row[a]["evidence_sha16"] != row["control"]["evidence_sha16"]
                                          if row.get("control") else None)
            row[a]["answer_changed"] = (row[a]["answer"] != row["control"]["answer"]
                                        if row.get("control") else None)
        per_row.append(row)

    report = {"arms": present, "rows": len(per_row), "by_arm": {}, "by_stratum": {}, "scoring_queue": {}}

    for a in present:
        R = [r[a] for r in per_row if a in r]
        report["by_arm"][a] = {
            "n": len(R),
            "errors": sum(1 for x in R if x["error"]),
            # --- the primary supply metric ---
            "governing_text_supplied": sum(1 for x in R if x["governing_text_supplied"]),
            "governing_named_in_prompt_only": sum(
                1 for x in R if x["governing_named_in_prompt"] and not x["governing_text_supplied"]),
            "carve_out_present": sum(1 for x in R if x["carve_out_present"]),
            # --- size and cost ---
            "mean_blocks": mean([x["n_blocks"] for x in R]),
            "mean_evidence_tokens": mean([x["evidence_tokens"] for x in R]),
            "mean_prompt_tokens": mean([x["prompt_tokens"] for x in R]),
            "total_seconds": round(sum(num(x["seconds"]) for x in R), 1),
            "mean_seconds": mean([x["seconds"] for x in R]),
            # --- safety / regression ---
            "withheld": sum(1 for x in R if x["withheld"]),
            "rows_with_hallucination_codes": sum(1 for x in R if x["hallucination_codes"]),
            "hallucination_code_counts": dict(Counter(c for x in R for c in x["hallucination_codes"]).most_common()),
            "truncation_noticed": sum(1 for x in R if x["truncation_noticed"]),
            "hit_token_ceiling": sum(1 for x in R if x["hit_token_ceiling"]),
            "mean_generated_tokens": mean([x["generated_tokens"] for x in R]),
            "cites_governing": sum(1 for x in R if x["cites_governing"]),
        }
        if a != "control":
            report["by_arm"][a]["evidence_changed"] = sum(1 for x in R if x.get("evidence_changed"))
            report["by_arm"][a]["answer_changed"] = sum(1 for x in R if x.get("answer_changed"))

    for s in sorted({r["stratum"] for r in per_row if r["stratum"]}):
        rows = [r for r in per_row if r["stratum"] == s]
        report["by_stratum"][s] = {"n": len(rows)}
        for a in present:
            report["by_stratum"][s][a] = {
                "governing_text_supplied": sum(1 for r in rows if r[a]["governing_text_supplied"]),
                "evidence_changed": sum(1 for r in rows if r[a].get("evidence_changed")) if a != "control" else None,
                "answer_changed": sum(1 for r in rows if r[a].get("answer_changed")) if a != "control" else None,
            }

    # rows that need a fresh verdict: the answer text actually differs from control
    for a in present:
        if a == "control":
            continue
        need = [r["id"] for r in per_row if r[a].get("answer_changed")]
        report["scoring_queue"][a] = {
            "needs_fresh_verdict": need,
            "inherits_stage_a_verdict": [r["id"] for r in per_row if r[a].get("answer_changed") is False],
        }

    if args.with_verdicts:
        cv = {qid: {"result": base[qid]["result"], "N": base[qid]["N"], "L": base[qid]["L"],
                    "M": base[qid]["M"], "O": base[qid]["O"], "P": base[qid]["P"], "Q": base[qid]["Q"]}
              for qid in ids if qid in base}
        report["verdicts"] = {"control": {"source": "Stage A frozen verdicts",
                                          "PASS": sum(1 for v in cv.values() if v["result"] == "PASS"),
                                          "N2": sum(1 for v in cv.values() if v["N"] == 2),
                                          "n": len(cv)}}
        for a in present:
            if a == "control":
                continue
            tv = verdicts(a)
            merged = {}
            for r in per_row:
                qid = r["id"]
                if r[a].get("answer_changed") is False and qid in cv:
                    merged[qid] = {**cv[qid], "source": "inherited"}
                elif qid in tv:
                    merged[qid] = {**tv[qid], "source": "scored"}
            report["verdicts"][a] = {
                "n_scored": len(merged),
                "missing": [r["id"] for r in per_row if r["id"] not in merged],
                "PASS": sum(1 for v in merged.values() if v.get("result") == "PASS"),
                "N2": sum(1 for v in merged.values() if v.get("N") == 2),
                "N_distribution": dict(Counter(v.get("N") for v in merged.values()).most_common()),
                "transitions": dict(Counter(
                    f"{cv.get(q, {}).get('result', '?')}->{v.get('result', '?')}"
                    for q, v in merged.items()).most_common()),
                # the distinction the experiment exists to draw
                "evidence_now_present_but_still_wrong": [
                    r["id"] for r in per_row
                    if r[a]["governing_text_supplied"] and not r["control"]["governing_text_supplied"]
                    and merged.get(r["id"], {}).get("N") != 2],
                "evidence_now_present_and_correct": [
                    r["id"] for r in per_row
                    if r[a]["governing_text_supplied"] and not r["control"]["governing_text_supplied"]
                    and merged.get(r["id"], {}).get("N") == 2],
            }

    (STAGE_B / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    (STAGE_B / "comparison_rows.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in per_row))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
