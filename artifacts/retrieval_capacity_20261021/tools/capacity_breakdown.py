"""Read-only, from saved artifacts only (no database, no model): (1) required paragraphs lost to context capacity vs
upstream retrieval, on the 100 cosmetics questions (post-repair baseline traces) and the 352-row baseline run;
(2) how the current contexts are packed; (3) what input length costs in the Step 6 Qwen3-1.7B MLX run."""
import json, glob, statistics as st
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
T = ROOT / "artifacts/retrieval_selection_d_20261021/baseline/traces"
res = {}
# (1a) 100 cosmetics, general questions, per required paragraph: stage
stages = Counter(); drop = Counter(); rows = []
for f in sorted(T.glob("*.json")):
    if f.name == "summary.json": continue
    d = json.loads(f.read_text())
    general = not d["gates"]["requirements"] and d["gates"]["docket"] is None
    for lab, v in d["required_status"].items():
        if lab == "21 CFR 740.11(i)": continue
        stages[("general" if general else "named", v["stage"])] += 1
        if v["stage"] == "dropped at selection": drop[v["drop_reason"]] += 1; rows.append((d["id"], lab, v["drop_reason"]))
res["cosmetics_100"] = {"stages": {f"{a} | {b}": n for (a, b), n in stages.items()}, "dropped_at_selection": rows}
# (1b) 352 baseline: keyed targets not in context, by reason
R = ROOT / "data/evaluation/results/retrieval_baseline_20261021T102326Z_16fa796d/per_question.jsonl"
c = Counter(); cap_only = []
for l in R.read_text().splitlines():
    if not l.strip(): continue
    r = json.loads(l)
    for t in r.get("targets") or []:
        if t.get("in_context"): c["in context"] += 1; continue
        dr = set(t.get("drop_reasons") or [])
        if dr and dr <= {"soft_budget", "max_results"}:
            c["dropped by soft budget/count only"] += 1; cap_only.append((r["id"], t["target"], sorted(dr)))
        elif dr: c["dropped: " + ",".join(sorted(dr))] += 1
        elif t.get("candidate_rank") is not None: c["candidate, not selected (top-k/other)"] += 1
        else: c["never a candidate (upstream)"] += 1
res["baseline_352"] = {"targets": dict(c), "capacity_only": cap_only}
# (2) packing of current contexts (experiment-1 base condition = production)
Q = json.loads((ROOT / "artifacts/retrieval_selection_d_20261021/candidates.json").read_text())["questions"]
pk = Counter(); same_doc = 0; gen_ctx = []
for q, r in Q.items():
    if not r["general"]: continue
    s = r["base"]["sources"]
    gen_ctx.append(sum(x["chars"] for x in s))
    pk["sources"] += len(s); pk["truncated"] += sum(x["truncated"] for x in s)
    pk["guidance"] += sum(x["corpus"] != "ecfr" for x in s); pk["guidance_chars"] += sum(x["chars"] for x in s if x["corpus"] != "ecfr")
    docs = Counter(x["citation"] for x in s if x["corpus"] != "ecfr")
    same_doc += sum(n - 1 for n in docs.values() if n > 1)
    pk["guidance_chunks_same_doc_extra_chars"] += sum(x["chars"] for i, x in enumerate(s) if x["corpus"] != "ecfr" and
                                                      [y["citation"] for y in s[:i]].count(x["citation"]) > 0)
res["packing_general_88"] = {**pk, "extra_chunks_of_an_already_present_guidance_document": same_doc,
                             "context_chars_median": st.median(gen_ctx), "context_chars_max": max(gen_ctx)}
# (3) Step 6 runtime: input tokens vs server wall time (1.7B MLX), least squares wall ~ a + b*in + c*out
A = [json.loads(l) for l in (ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/results.jsonl").read_text().splitlines() if l.strip()]
pts = [(x["input_tokens"], x["output_tokens"], x["wall_seconds_server"]) for x in A if x.get("model_called") and x.get("input_tokens") and x.get("wall_seconds_server")]
import numpy as np
X = np.array([[1, a, b] for a, b, _ in pts]); y = np.array([w for *_, w in pts])
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
res["runtime_step6"] = {"n": len(pts), "input_tokens_median": st.median(p[0] for p in pts), "input_tokens_max": max(p[0] for p in pts),
                        "fit_seconds": {"intercept": round(coef[0], 3), "per_input_token_ms": round(coef[1] * 1000, 3), "per_output_token_ms": round(coef[2] * 1000, 2)}}
(OUT / "capacity_breakdown.json").write_text(json.dumps(res, indent=1))
print(json.dumps({k: v for k, v in res.items()}, indent=1)[:5000])
