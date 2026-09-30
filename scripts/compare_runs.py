"""Compare two diagnostic runs (A = protected baseline, B = candidate); no model is loaded.

    python scripts/compare_runs.py <run A> <run B> [--pass-set <run with reviewed PASS to protect>]

Reviewed verdicts of A (A/manual_review.jsonl) carry to B only for questions whose final
answer hash is unchanged; every changed answer is reported with its automatic verdict and
listed for developer review. Nothing here edits either run.
"""
from __future__ import annotations

import argparse, collections, json, statistics
from pathlib import Path


def first(p):
    o = {}
    if Path(p).exists():
        for l in open(p, encoding="utf-8"):
            if l.strip():
                r = json.loads(l); o.setdefault(r["question_id"], r)
    return o


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def metrics(d, t, status):
    dec = lambda f: f["confidence"] in ("proven", "probable")
    has = lambda q, codes, major=False: any(f["failure_class"] in codes and dec(f) and (not major or f["severity"] != "minor") for f in d[q]["failures"])
    gen = [x for x in t.values() if x["model_called"]]
    tot = [x["timings_ms"]["total_ms"] / 1000 for x in gen]
    g = [x["timings_ms"].get("generation_ms", 0) / 1000 for x in gen]
    ft = [x["timings_ms"]["model_first_token_ms"] / 1000 for x in gen if x["timings_ms"].get("model_first_token_ms") is not None]
    return {
        "status": dict(collections.Counter(status.values())),
        "unsupported_generation_raw_F07": sum(has(q, {"F07"}) for q in d), "unsupported_reaching_F07_major": sum(has(q, {"F07"}, True) for q in d),
        "critical": sum(any(f["severity"] == "critical" and dec(f) for f in d[q]["failures"]) for q in d),
        "citation_failures_F09": sum(has(q, {"F09"}) for q in d), "citation_failures_F09_major": sum(has(q, {"F09"}, True) for q in d),
        "qualifier_failures_F08": sum(has(q, {"F08"}) for q in d), "qualifier_failures_F08_major": sum(has(q, {"F08"}, True) for q in d),
        "completeness_failures_F15": sum(has(q, {"F15"}) for q in d),
        "enumeration_incomplete_initial": sum("enumeration_incomplete" in ((t[q].get("initial_validation") or {}).get("codes") or []) for q in t),
        "safe_fallback_failures_F13_F20": sum(has(q, {"F13", "F20"}) for q in d), "repair_failures_F12": sum(has(q, {"F12"}) for q in d),
        "degenerate_F18": sum(has(q, {"F18"}) for q in d), "model_capability_F16": sum(has(q, {"F16"}) for q in d),
        "generation_called": len(gen), "blocked": sum(bool(x.get("generation_blocked")) for x in t.values()),
        "latency_s": {"median": round(statistics.median(tot), 2), "p90": round(pct(tot, 0.9), 2), "sum": round(sum(tot), 1)},
        "generation_s": {"median": round(statistics.median(g), 2), "p90": round(pct(g, 0.9), 2)},
        "first_token_s": {"median": round(statistics.median(ft), 3), "p90": round(pct(ft, 0.9), 3)} if ft else None,
        "prompt_tokens": {"median": statistics.median(x["prompt_token_count"] or 0 for x in gen), "p90": pct([x["prompt_token_count"] or 0 for x in gen], 0.9)},
        "output_tokens": {"median": statistics.median(x["output_token_count"] or 0 for x in gen), "p90": pct([x["output_token_count"] or 0 for x in gen], 0.9)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--protect", default="artifacts/diagnostics/stage4_rediagnosed_20260929T082457Z")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    A, B = Path(args.a), Path(args.b)
    da, ta, db, tb = first(A / "diagnoses.jsonl"), first(A / "traces.jsonl"), first(B / "diagnoses.jsonl"), first(B / "traces.jsonl")
    ra = first(A / "manual_review.jsonl")
    norm = lambda s: s.split(" ")[0]
    sa = {q: norm(ra[q]["reviewed_status"]) if q in ra else r["final_status"] for q, r in da.items()}
    sb, carried, review = {}, [], []
    for q, r in db.items():
        same = ta[q]["final_output_hash"] == tb[q]["final_output_hash"]
        if same and q in ra:
            sb[q] = norm(ra[q]["reviewed_status"]); carried.append(q)
        else:
            sb[q] = r["final_status"]
            if not same:
                review.append(q)
    # the protected set: reviewed PASS of the Stage 4 baseline
    P = Path(args.protect)
    dp, rp = first(P / "diagnoses.jsonl"), first(P / "manual_review.jsonl")
    protected = [q for q, r in dp.items() if (norm(rp[q]["reviewed_status"]) if q in rp else r["final_status"]) == "PASS"]
    rep = {
        "a": str(A), "b": str(B), "carried_reviews": carried, "changed_answers_needing_review": review,
        "protected_pass": {"n": len(protected), "still_pass_automatic_or_carried": sum(sb[q] == "PASS" for q in protected),
                           "not_pass": [(q, sb[q], db[q]["primary"]) for q in protected if sb[q] != "PASS"]},
        "transitions": {f"{k[0]} -> {k[1]}": v for k, v in collections.Counter((sa[q], sb[q]) for q in db).items()},
        "changed": [{"id": q, "a": sa[q], "b": sb[q], "primary_a": da[q]["primary"], "primary_b": db[q]["primary"],
                     "gate": tb[q].get("answerability_state"), "repair_b": tb[q].get("repair_type"), "fallback_b": tb[q].get("fallback_type"),
                     "sources_a": len(ta[q]["selected_context"]), "sources_b": len(tb[q]["selected_context"])} for q in review],
        "metrics_a": metrics(da, ta, sa), "metrics_b": metrics(db, tb, sb),
    }
    out = Path(args.out) if args.out else B / "comparison_vs_baseline.json"
    out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
