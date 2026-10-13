"""Phase 1 validation: does the live evaluator's score track the hand-scored rubric?

Runs the evaluator over a stratified subset of the already-labelled acceptance
rows and compares its output with `regulus_substantive_rubric_v1`. It changes
nothing, generates nothing and retrains nothing: the answers were produced in
`acceptance_rev02_20261001T083958Z` and hand-scored once; this only re-reads
them.

    .venv/bin/python scripts/accuracy_validate.py              # 60 rows, semantic alignment
    .venv/bin/python scripts/accuracy_validate.py --alignment lexical
    .venv/bin/python scripts/accuracy_validate.py --size 120

What it reconstructs, and what that costs in fidelity
-----------------------------------------------------
`artifacts/stage_a/dataset.jsonl` records each row's question, delivered answer,
citations, the evidence LABELS that were shown to the model, and the hand rubric
scores. It does not record the evidence TEXT, so the harness fetches each label
from the same read-only snapshot. Two consequences, both of which make the
false-high criterion HARDER rather than easier:

* `ValidationReport` is not recorded per row, so the harness passes none. Every
  dimension that depends on a validation code - fabricated figures, citation
  mismatches, asserted-missing provisions - is therefore NOT applied, so the
  evaluator scores these rows with its safety codes switched off. Anything that
  slips past is a genuine weakness of the claim reasoning.
* guidance dockets have no eCFR row, so a row whose evidence is guidance loses
  that text. Those rows are reported separately rather than silently counted.

Coverage is rebuilt from the recorded labels plus `plan_query` (pure parsing, no
retrieval): a requested provision counts as satisfied when a recorded evidence
label is that provision or one of its paragraphs.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regulus.accuracy import rubric as R
from regulus.accuracy.evaluator import evaluate
from regulus.config import PROJECT_ROOT, load_settings

DATASET = PROJECT_ROOT / "artifacts" / "stage_a" / "dataset.jsonl"
OUT_DIR = PROJECT_ROOT / "artifacts" / "accuracy"

_LABEL_RE = re.compile(r"^21 CFR (\d+\.\d+[a-z]?)((?:\([A-Za-z0-9]+\))*)$")
SQL = """SELECT body_text, section_heading FROM cfr_records
         WHERE section_number = %(s)s AND (%(p)s = '' OR paragraph_path = %(p)s)
           AND removed_on IS NULL ORDER BY ordinal"""


# ------------------------------------------------------------ the shims
# Duck-typed stand-ins for the objects the pipeline would hand the evaluator.
# They expose only what the evaluator reads, and nothing writes.


@dataclass(frozen=True)
class Src:
    index: int
    citation: str
    text: str
    tier: str = "exact"
    heading: str | None = None      # the section heading, as PackagedSource.heading carries it live
    requirement_ids: tuple[str, ...] = ()
    citation_fields: dict[str, Any] | None = None
    corpus: str = "ecfr"
    is_docket: bool = False


@dataclass(frozen=True)
class Pkg:
    question: str
    requirements: tuple[tuple[str, str], ...]
    satisfied_ids: tuple[str, ...]
    sources: tuple[Src, ...]
    answer_plan: Any = None
    question_analysis: Any = None

    @property
    def requirement_labels(self) -> dict[str, str]:
        return dict(self.requirements)


@dataclass(frozen=True)
class Cov:
    requirements: tuple[Any, ...]
    satisfied_ids: tuple[str, ...]
    missing_labels: tuple[str, ...]
    explicit: bool

    @property
    def state(self) -> str:
        if not self.explicit:
            return "NO_EXPLICIT_REQUIREMENTS"
        return "COMPLETE" if not self.missing_labels else "INCOMPLETE"


def fetch_text(db, label: str, cache: dict[str, Any]) -> tuple[str | None, str | None]:
    """(text, section heading) for one evidence label, read-only."""
    if label in cache:
        return cache[label]
    m = _LABEL_RE.match(label)
    text = heading = None
    if m:
        rows = db.query(SQL, {"s": m.group(1), "p": m.group(2) or ""})
        text = "\n".join(r["body_text"] for r in rows if r["body_text"]) or None
        heading = next((r["section_heading"] for r in rows if r.get("section_heading")), None)
    cache[label] = (text, heading)
    return text, heading


def build(row: dict[str, Any], db, cache) -> tuple[Pkg, Cov, int]:
    """The evidence package and coverage this row's answer was produced with."""
    from regulus.planning import plan_query
    from regulus.retrieval.references import parse_cfr_references

    labels = list(dict.fromkeys(row["evidence"]))
    sources, docket_labels = [], 0
    for label in labels:
        text, heading = fetch_text(db, label, cache)
        if text is None:
            docket_labels += 1
            continue
        sources.append(Src(index=len(sources) + 1, citation=label, text=text, heading=heading,
                           citation_fields=_fields(label)))

    plan = plan_query(row["question"])
    requirements = tuple((r.id, r.canonical) for r in plan.requirements)
    have = [ref for label in labels for ref in parse_cfr_references(label)]
    satisfied: list[str] = []
    for rid, canonical in requirements:
        want = next((r for r in parse_cfr_references(canonical)), None)
        if want is None:
            continue
        if any(h.section == want.section and (want.paragraph_path == "" or
                                              h.paragraph_path.startswith(want.paragraph_path))
               for h in have if h.section):
            satisfied.append(rid)
    missing = tuple(c for rid, c in requirements if rid not in satisfied)
    package = Pkg(question=row["question"], requirements=requirements,
                  satisfied_ids=tuple(satisfied), sources=tuple(sources))
    coverage = Cov(requirements=requirements, satisfied_ids=tuple(satisfied), missing_labels=missing,
                   explicit=bool(requirements))
    return package, coverage, docket_labels


def _fields(label: str) -> dict[str, Any]:
    m = _LABEL_RE.match(label)
    if not m:
        return {}
    return {"title": "21", "section": m.group(1), "paragraph": m.group(2) or ""}


# ------------------------------------------------------------ the subset


STRATA = (
    ("N2_verbatim_or_near", lambda r: r["N"] == 2 and r["result"] == "PASS" and r.get("rev_trap_row") != "yes", 6),
    ("N2_other", lambda r: r["N"] == 2 and r.get("rev_trap_row") != "yes", 4),
    ("N1_partial", lambda r: r["N"] == 1, 12),
    ("N0_incorrect", lambda r: r["N"] == 0 and r.get("rev_trap_row") != "yes", 12),
    ("fabrication_M1", lambda r: r.get("M") == 1, 2),
    ("citation_error_L0", lambda r: r.get("L") == 0 and r["N"] in (1, 2), 8),
    ("incomplete_O0", lambda r: r.get("O") == 0 and r["N"] == 1, 6),
    ("negative_control_trap", lambda r: r.get("rev_trap_row") == "yes", 8),
    ("multi_section", lambda r: r.get("type", "").lower().startswith("multi") or "through" in r["question"].lower(), 2),
    ("cross_reference", lambda r: "cross" in r.get("type", "").lower() or "incorporat" in r["question"].lower(), 2),
)


def select(rows: list[dict], size: int) -> list[dict]:
    """A stratified subset, deterministic: rows are taken in id order."""
    chosen: dict[str, dict] = {}
    tags: dict[str, str] = {}
    for name, predicate, want in STRATA:
        taken = 0
        for row in sorted(rows, key=lambda r: r["id"]):
            if taken >= want or row["id"] in chosen or row["N"] is None:
                continue
            try:
                if predicate(row):
                    chosen[row["id"]] = row
                    tags[row["id"]] = name
                    taken += 1
            except Exception:
                continue
    out = [dict(r, _stratum=tags[r["id"]]) for r in sorted(chosen.values(), key=lambda r: r["id"])]
    return out[:size] if size else out


# Ground truth for the critical-error checks, taken from the human reviewer's own
# notes in artifacts/stage_a/dataset.jsonl (confirmed row by row in the Phase 1
# forensic analysis), NOT from the evaluator: rows whose answer addresses a
# different requirement or product domain than the question asked.
WRONG_TOPIC = {
    "D-001": "quotes 211.100-211.132 production controls for a question about the SCOPE of Part 211",
    "D-003": "production-control list for a personnel question",
    "D-004": "never mentions consultants",
    "D-006": "production-control list for a ventilation question",
    "D-007": "production-control content for an equipment-cleaning question",
    "D-008": "drug question answered from 111.30 (dietary supplements)",
    "D-009": "generic written-procedures content for an incoming-components question",
    "D-010": "answered from 213.84 (PET drugs) and Part 111 (supplements)",
    "E-005": "open-systems question drifts into 510(k), reagents and food tanks",
    "E-010": "mischaracterises the guidance; no Part 11 provisions given",
    "F-003": "personnel question answered with Subpart C preventive controls",
    "K-003": "children-safeguards question answered with IDE device-description content",
}
# Refusals the human scored as wrong (the question went unanswered).
INCORRECT_REFUSALS = {"C-003": "declined although 740.10 exists", "D-005": "declined although 211.42 exists",
                      "C-001": "draft withheld; unanswered", "NC-003": "draft withheld; Subpart Z premise not refuted"}
TEMPORAL_REFUSALS = ("M-031", "M-032", "M-033", "M-035", "M-036", "M-037", "M-038")


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman's rho with average ranks for ties. Stdlib only."""
    if len(xs) < 3:
        return None

    def rank(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = average
            i = j + 1
        return ranks

    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return None if den == 0 else num / den


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--size", type=int, default=60)
    p.add_argument("--alignment", choices=("semantic", "lexical"), default="semantic")
    p.add_argument("--dataset", type=Path, default=DATASET)
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    rows = [json.loads(l) for l in args.dataset.read_text(encoding="utf-8").splitlines() if l.strip()]
    subset = select(rows, args.size)
    print(f"dataset {args.dataset.name}: {len(rows)} rows; validation subset {len(subset)}")
    print("strata:", dict(Counter(r["_stratum"] for r in subset)))

    aligner = None
    load_seconds = 0.0
    if args.alignment == "semantic":
        from regulus.accuracy.alignment import SemanticAligner
        from regulus.retrieval.semantic import TransformersEmbedder, load_manifest

        t0 = time.perf_counter()
        embedder = TransformersEmbedder(load_manifest().embedding,
                                        cache_dir=load_settings().model.cache_dir, local_files_only=True)
        load_seconds = round(time.perf_counter() - t0, 2)
        aligner = SemanticAligner(embedder)
        print(f"aligner: semantic ({embedder.describe()['model_id']}, loaded in {load_seconds}s)")
    else:
        print("aligner: lexical (no model)")

    from regulus.retrieval import Database

    db = Database.from_env()
    db.connect()
    from regulus.grounding import DatabaseIdentifierIndex

    index = DatabaseIdentifierIndex(db)
    cache: dict[str, str | None] = {}
    out_rows: list[dict[str, Any]] = []
    for row in subset:
        package, coverage, dockets = build(row, db, cache)
        t0 = time.perf_counter()
        # evidence rebuilt from the artifact's labels: NOT the exact prompt evidence, and labelled so
        assessment = evaluate(row["question"], row["answer"] or "", package=package, coverage=coverage,
                              evidence_provenance="legacy_reconstructed",
                              validation=None, model_called=bool(row.get("model_called")),
                              fallback_type=row.get("fallback_type"), scope_status=row.get("scope"),
                              answerability={"state": row.get("answerability")} if row.get("answerability") else None,
                              identifier_index=index, aligner=aligner)
        elapsed = (time.perf_counter() - t0) * 1000
        out_rows.append({
            "id": row["id"], "stratum": row["_stratum"], "N": row["N"], "L": row.get("L"), "M": row.get("M"),
            "O": row.get("O"), "result": row["result"], "trap": row.get("rev_trap_row") == "yes",
            "status": assessment.status, "accuracy": assessment.accuracy,
            "dimensions": assessment.states, "reason": assessment.reason,
            "answer_verdict": (assessment.checked.get("answer_verdict") or {}).get("verdict"),
            "claims": assessment.checked.get("material_claims"),
            "verdicts": assessment.checked.get("claim_status"),
            "intent_kind": (assessment.checked.get("intent") or {}).get("kind"),
            "abstention": (assessment.checked.get("abstention") or {}).get("outcome"),
            "sources": len(package.sources), "docket_labels_without_text": dockets,
            "evidence_provenance": assessment.evidence.get("provenance"),   # never "exact" for these rows
            "elapsed_ms": round(elapsed, 2),
        })
    db.close()

    scored = [r for r in out_rows if r["accuracy"] is not None]
    coverage_pct = 100 * len(scored) / len(out_rows) if out_rows else 0.0
    by_n = defaultdict(list)
    for r in scored:
        by_n[r["N"]].append(r["accuracy"])
    false_high = [r for r in scored if (r["N"] == 0 or r["M"] == 1) and r["accuracy"] > 50]
    traps = [r for r in out_rows if r["trap"]]
    traps_scored = [r for r in traps if r["accuracy"] is not None]
    rho = spearman([float(r["N"]) for r in scored], [float(r["accuracy"]) for r in scored])
    latency = [r["elapsed_ms"] for r in out_rows]

    print(f"\n{'stratum':24}{'n':>4}{'scored':>8}{'mean':>8}{'min':>6}{'max':>6}")
    for name, _, _ in STRATA:
        group = [r for r in out_rows if r["stratum"] == name]
        if not group:
            continue
        got = [r["accuracy"] for r in group if r["accuracy"] is not None]
        print(f"{name:24}{len(group):>4}{len(got):>8}"
              f"{(round(statistics.mean(got), 1) if got else '-'):>8}"
              f"{(min(got) if got else '-'):>6}{(max(got) if got else '-'):>6}")

    print(f"\n{'N':<4}{'rows':>6}{'scored':>8}{'mean score':>12}")
    for n in (2, 1, 0):
        group = [r for r in out_rows if r["N"] == n]
        got = by_n[n]
        print(f"{n:<4}{len(group):>6}{len(got):>8}{(round(statistics.mean(got), 1) if got else '-'):>12}")

    summary = {
        "rows": len(out_rows),
        "scored": len(scored),
        "unable_to_determine": sum(1 for r in out_rows if r["status"] == R.UNABLE),
        "not_scored": sum(1 for r in out_rows if r["status"] == R.NOT_SCORED),
        "score_coverage_pct": round(coverage_pct, 1),
        "mean_by_N": {str(n): (round(statistics.mean(v), 1) if v else None) for n, v in sorted(by_n.items(), reverse=True)},
        "ordering_holds": all(x is not None for x in (by_n.get(2), by_n.get(1), by_n.get(0))) and
                          statistics.mean(by_n[2]) > statistics.mean(by_n[1]) > statistics.mean(by_n[0])
                          if (by_n.get(2) and by_n.get(1) and by_n.get(0)) else None,
        "false_high_count": len(false_high),
        "false_high_ids": [r["id"] for r in false_high],
        "traps": len(traps),
        "traps_scored": len(traps_scored),
        "spearman_rho": None if rho is None else round(rho, 3),
        "latency_ms": {"mean": round(statistics.mean(latency), 2), "max": round(max(latency), 2),
                       "p50": round(statistics.median(latency), 2)},
        "aligner": args.alignment,
        "embedder_load_seconds": load_seconds,
        "rubric": "regulus_substantive_rubric_v1",
        "note": "validation reports are not recorded per row, so no ValidationReport was passed: the "
                "evaluator scored these rows with its validation-code safety checks switched off",
    }
    print("\n" + json.dumps(summary, indent=2))

    # Diagnostic slice, NOT the basis of the decision: rows whose evidence the
    # harness reconstructed in full (no guidance docket text lost). Guidance
    # chunks are not identified by their label, so fetching whole dockets would
    # hand the evaluator evidence the model never saw; those rows are instead
    # reported apart, as the module docstring says.
    faithful = [r for r in out_rows if not r["docket_labels_without_text"]]
    f_scored = [r for r in faithful if r["accuracy"] is not None]
    f_by_n = defaultdict(list)
    for r in f_scored:
        f_by_n[r["N"]].append(r["accuracy"])
    f_rho = spearman([float(r["N"]) for r in f_scored], [float(r["accuracy"]) for r in f_scored])
    summary["faithfully_reconstructed_slice"] = {
        "rows": len(faithful), "scored": len(f_scored),
        "score_coverage_pct": round(100 * len(f_scored) / len(faithful), 1) if faithful else None,
        "mean_by_N": {str(n): round(statistics.mean(v), 1) for n, v in sorted(f_by_n.items(), reverse=True)},
        "false_high_count": sum(1 for r in f_scored if (r["N"] == 0 or r["M"] == 1) and r["accuracy"] > 50),
        "spearman_rho": None if f_rho is None else round(f_rho, 3),
    }
    print("\nfaithfully reconstructed slice (diagnostic only):")
    print(json.dumps(summary["faithfully_reconstructed_slice"], indent=2))

    # ---- answer verdicts and the critical error types
    by_id = {r["id"]: r for r in out_rows}
    av = Counter(r["answer_verdict"] for r in out_rows)
    print("\nanswer verdicts:", dict(av))
    print(f"\n{'N':<4}{'rows':>5}{'scored':>8}  scores                                   verdicts")
    for n in (2, 1, 0):
        group = [r for r in out_rows if r["N"] == n]
        got = sorted((r["accuracy"] for r in group if r["accuracy"] is not None), reverse=True)
        print(f"{n:<4}{len(group):>5}{len(got):>8}  {str(got)[:40]:40} {dict(Counter(r['answer_verdict'] for r in group))}")
    wt = [by_id[i] for i in WRONG_TOPIC if i in by_id]
    ir = [by_id[i] for i in INCORRECT_REFUSALS if i in by_id]
    tr = [by_id[i] for i in TEMPORAL_REFUSALS if i in by_id]
    n2 = [r for r in out_rows if r["N"] == 2]
    critical = {
        "false_high_N0 (N=0 or M=1 scored >50)": sorted(r["id"] for r in out_rows if (r["N"] == 0 or r["M"] == 1)
                                                     and (r["accuracy"] or 0) > 50),
        "false_high_wrong_topic (scored >50)": sorted(r["id"] for r in wt if (r["accuracy"] or 0) > 50),
        "false_high_incorrect_refusal (scored >50)": sorted(r["id"] for r in ir if (r["accuracy"] or 0) > 50),
        "temporal_refusals_scored_>50": sorted(r["id"] for r in tr if (r["accuracy"] or 0) > 50),
        "false_low_N2 (scored <50)": sorted(r["id"] for r in n2 if r["accuracy"] is not None and r["accuracy"] < 50),
    }
    relevance = {
        "wrong_topic_rows": len(wt),
        "wrong_topic_judged_off_topic_or_incorrect": sorted(r["id"] for r in wt if r["answer_verdict"] in ("off_topic", "incorrect")),
        "wrong_topic_judged_partial": sorted(r["id"] for r in wt if r["answer_verdict"] == "partial"),
        "wrong_topic_unverifiable": sorted(r["id"] for r in wt if r["answer_verdict"] == "unverifiable"),
        "wrong_topic_judged_correct": sorted(r["id"] for r in wt if r["answer_verdict"] == "correct"),
        "N2_judged_correct": sorted(r["id"] for r in n2 if r["answer_verdict"] == "correct"),
        "N2_judged_other": {r["id"]: r["answer_verdict"] for r in n2 if r["answer_verdict"] != "correct"},
        "incorrect_refusals_detected": sorted(r["id"] for r in ir if r["answer_verdict"] == "abstention_incorrect"),
        "incorrect_refusals_missed": {r["id"]: r["answer_verdict"] for r in ir if r["answer_verdict"] != "abstention_incorrect"},
        "temporal_refusals": {r["id"]: f"{r['answer_verdict']} {r['accuracy']}" for r in tr},
    }
    summary["answer_verdicts"] = dict(av)
    summary["critical_errors"] = critical
    summary["relevance"] = relevance
    print("\ncritical errors:", json.dumps(critical, indent=2))
    print("relevance:", json.dumps(relevance, indent=2))

    criteria = {
        "score_coverage >= 50%": coverage_pct >= 50,
        "ordering N2 > N1 > N0": bool(summary["ordering_holds"]),
        "0 false highs (N=0 or M=1 above 50%)": len(false_high) == 0,
        "traps scored >= 6 of 8": len(traps_scored) >= 6,
        "spearman >= 0.6": rho is not None and rho >= 0.6,
    }
    print("\nPhase 1 criteria")
    for name, ok in criteria.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
    path = OUT_DIR / f"validation_{args.alignment}_{stamp}.json"
    path.write_text(json.dumps({"summary": summary, "criteria": criteria, "rows": out_rows},
                               indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwritten: {path.relative_to(PROJECT_ROOT)}")
    return 0 if all(criteria.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
