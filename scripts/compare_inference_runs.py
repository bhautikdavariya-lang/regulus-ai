"""Compare two benchmark_latency.py runs question by question (inference equivalence).

    python scripts/compare_inference_runs.py artifacts/latency/cpu_fp32_* artifacts/latency/mps_fp16_* \
        --out artifacts/latency/compare_cpu_fp32_vs_mps_fp16.md

For every question present in both runs it compares, exactly (no similarity
threshold): the prompt sent to the model (sha256), the sources in context, the
final answer, the citations, the initial and final validation (status, codes,
problems), the repair applied, the coverage action, citation support and the
number of generated tokens. Any mismatch gets an exact diff; answer mismatches
also report where the two generations first diverge. Prints a JSON summary
and writes a Markdown report. Read-only.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

FIELDS = ("prompt_sha256", "sources", "answer", "citations", "validation_initial", "validation_final", "repair",
          "coverage_action", "citation_support", "generated_tokens", "prompt_tokens", "model_called")


def load(path: str) -> tuple[dict, dict[str, dict]]:
    """Rows by question id from results.jsonl (summary.json is optional: runs whose
    summary step failed still have every per-question record)."""
    d = Path(path)
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8")) if (d / "summary.json").is_file() else {}
    rows = {}
    for line in (d / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["id"]] = r
    return summary, rows


def _norm_validation(v: dict | None) -> dict | None:
    """Validation minus fields that only restate generation length or timing (compared separately)."""
    if v is None:
        return None
    return {k: v[k] for k in sorted(v) if k not in ("generated_tokens", "max_new_tokens", "finished", "truncated")}


def first_divergence(a: str, b: str) -> dict:
    n = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return {"char": n, "common_prefix_tail": a[max(0, n - 60):n], "a_continues": a[n:n + 80], "b_continues": b[n:n + 80]}


def text_diff(a: str, b: str, la: str, lb: str) -> str:
    return "\n".join(difflib.unified_diff(a.splitlines(), b.splitlines(), la, lb, lineterm="", n=1))


def json_diff(a, b, la: str, lb: str) -> str:
    dump = lambda x: json.dumps(x, indent=1, sort_keys=True, ensure_ascii=False).splitlines()
    return "\n".join(difflib.unified_diff(dump(a), dump(b), la, lb, lineterm="", n=1))


def compare(a_rows: dict, b_rows: dict, la: str, lb: str) -> tuple[dict, list[dict]]:
    ids = [i for i in a_rows if i in b_rows]
    mismatches: list[dict] = []
    counts = {f: 0 for f in FIELDS}
    identical_questions = 0
    for qid in ids:
        a, b = a_rows[qid], b_rows[qid]
        diffs = {}
        for f in FIELDS:
            va, vb = a.get(f), b.get(f)
            if f.startswith("validation"):
                va, vb = _norm_validation(va), _norm_validation(vb)
            if va != vb:
                counts[f] += 1
                if f == "answer":
                    diffs[f] = {"diff": text_diff(va or "", vb or "", la, lb), "divergence": first_divergence(va or "", vb or "")}
                elif isinstance(va, (dict, list)) or isinstance(vb, (dict, list)):
                    diffs[f] = {"diff": json_diff(va, vb, la, lb)}
                else:
                    diffs[f] = {"a": va, "b": vb}
        if diffs:
            mismatches.append({"id": qid, "question": a.get("question"), "category": a.get("category"), "diffs": diffs})
        else:
            identical_questions += 1
    summary = {"compared": len(ids), "identical_in_every_field": identical_questions,
               "questions_with_any_difference": len(mismatches), "differences_by_field": counts,
               "only_in_a": sorted(set(a_rows) - set(b_rows)), "only_in_b": sorted(set(b_rows) - set(a_rows))}
    return summary, mismatches


def report(summary: dict, mismatches: list[dict], la: str, lb: str) -> str:
    out = [f"# Inference equivalence: {la} vs {lb}", "", "```json", json.dumps(summary, indent=1), "```", ""]
    for m in mismatches:
        out += [f"## {m['id']} ({m['category']}): {m['question']}", ""]
        for f, d in m["diffs"].items():
            out.append(f"### {f}")
            if "divergence" in d:
                dv = d["divergence"]
                out += [f"First divergence at character {dv['char']}, after: `{dv['common_prefix_tail']}`",
                        f"- {la}: `{dv['a_continues']}`", f"- {lb}: `{dv['b_continues']}`", ""]
            if "diff" in d:
                out += ["```diff", d["diff"] or "(no line-level difference: whitespace or ordering)", "```", ""]
            else:
                out += [f"- {la}: `{d['a']}`", f"- {lb}: `{d['b']}`", ""]
    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    _, a_rows = load(args.run_a)
    _, b_rows = load(args.run_b)
    la, lb = Path(args.run_a).name, Path(args.run_b).name
    summary, mismatches = compare(a_rows, b_rows, la, lb)
    print(json.dumps(summary, indent=1))
    if args.out:
        args.out.write_text(report(summary, mismatches, la, lb), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
