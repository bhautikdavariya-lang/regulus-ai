"""Step 6 A/B analysis (read-only on both arms and the blind verdicts; writes scoring/analysis.json).

    python analyze.py <root> [--facts-only]

--facts-only: everything that does not need verdicts (model identity, switch application, prompt/answer
identity between arms, retrieval, timing, tokens, errors). Without it, verdicts are merged from
scoring/blind_verdicts_batch_*.json through scoring/blind_map.json and the categories compared.
The category mapping is the 20 Oct one (cosmetics100_20261020T124217Z/tools/build_workbook.py category()),
reproduced verbatim below because that module needs openpyxl.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "cosmetics100_20261020T124217Z" / "tools"))
from common import evidence_check, load_run  # noqa: E402

PASS, PPASS, PFAIL, FAIL, NE, NEV = "PASS", "PARTIALLY PASS", "PARTIALLY FAIL", "FAIL", "NOT EVALUATED", "NOT EVALUABLE"
ORDER = {FAIL: 0, PFAIL: 1, PPASS: 2, PASS: 3}
EXPECTED_MODEL = {"id": "qwen3-1.7b", "backend": "mlx", "model_id": "Qwen/Qwen3-1.7B",
                  "model_revision": "21457c6f51ed54a7c16e988c0844db973815c137", "dtype": "mlx-4bit-g128"}
DECLINE = "The available regulatory sources do not provide enough information to answer this"


def category(v: dict | None, exec_status: str) -> str:   # verbatim from the 20 Oct build_workbook.py
    if exec_status != "SUCCESS" or v is None:
        return NE
    if v["sub"] == 0:
        return FAIL
    if v["sub"] == 1:
        return PFAIL
    if v["fab"] == 1 or v["scope"] == 0 or v["comp"] == 0:
        return PFAIL
    if v["comp"] == 2 and v["ce"] == 1:
        return PASS
    return PPASS


def norm(t):
    return " ".join((t or "").split())


def kind(r: dict | None) -> str:
    if r is None or r.get("execution_status") != "SUCCESS":
        return "error"
    if r.get("fallback_type") == "unvalidated_answer_withheld":
        return "withheld"
    if r.get("fallback_type"):
        return "fallback"
    if DECLINE.lower() in (r.get("answer") or "").lower() and len(r.get("answer") or "") < 200:
        return "decline"
    return "answer"


def describe(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    if not xs:
        return None
    return {"n": len(xs), "mean": round(st.mean(xs), 2), "median": round(st.median(xs), 2), "max": round(max(xs), 2),
            "sum": round(sum(xs), 2)}


def facts(root: Path) -> dict:
    arms = {"A": load_run(root / "arm_A_switch_off"), "B": load_run(root / "arm_B_switch_on")}
    out = {"per_question": {}, "arms": {}}
    for arm, rows in arms.items():
        models = Counter(json.dumps({k: (x["resp"] or {}).get("model", {}).get(k) for k in EXPECTED_MODEL}, sort_keys=True)
                         for x in rows if x["resp"])
        recs = []
        for f in (root / f"arm_{arm}_switch_{'off' if arm == 'A' else 'on'}" / "ui_measurements").glob("*/measurement.jsonl"):
            recs += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        rec_models = Counter(json.dumps({k: r["run"]["model"].get(k) for k in ("backend", "model_id", "model_revision", "dtype")},
                                        sort_keys=True) for r in recs)
        rows_r = [x["r"] for x in rows]
        out["arms"][arm] = {
            "responses": sum(1 for x in rows if x["resp"]),
            "execution": dict(Counter((r or {}).get("execution_status", "MISSING") for r in rows_r)),
            "model_fields_in_responses": {k: n for k, n in models.items()},
            "model_identity_ok": all(json.loads(k) == EXPECTED_MODEL for k in models) and sum(models.values()) == len(rows),
            "measurement_records": len(recs), "measurement_run_models": dict(rec_models),
            "pipeline_config_sha256": sorted({r["run"].get("pipeline_config_sha256") for r in recs}),
            "delivery": dict(Counter(kind(r) for r in rows_r)),
            "client_seconds": describe([(r or {}).get("client_seconds") for r in rows_r]),
            "generation_ms": describe([((r or {}).get("timings_ms") or {}).get("generation_ms") for r in rows_r]),
            "input_tokens": describe([(r or {}).get("input_tokens") for r in rows_r]),
            "output_tokens": describe([(r or {}).get("output_tokens") for r in rows_r]),
            "stop_reasons": dict(Counter((r or {}).get("stop_reason") for r in rows_r)),
            "validation_final": dict(Counter((r or {}).get("validation_final") for r in rows_r)),
            "fallback_types": dict(Counter((r or {}).get("fallback_type") for r in rows_r)),
        }
    for xa, xb in zip(arms["A"], arms["B"]):
        q = xa["q"]
        ga, gb = (xa["resp"] or {}).get("generation") or {}, (xb["resp"] or {}).get("generation") or {}
        ev = evidence_check(q, xa["resp"])
        sel = (xa["resp"] or {}).get("selection") or {}
        out["per_question"][q["ID"]] = {
            "shape": ga.get("shape"), "mode": (ga.get("answer_plan") or {}).get("mode"),
            "switch_applied_B": gb.get("format_line") == "general", "format_line_in_A": "format_line" in ga,
            "same_sources": [s.get("citation") for s in (xa["resp"] or {}).get("sources") or []] ==
                            [s.get("citation") for s in (xb["resp"] or {}).get("sources") or []],
            "same_answer": norm((xa["r"] or {}).get("answer")) == norm((xb["r"] or {}).get("answer")),
            "kind": {"A": kind(xa["r"]), "B": kind(xb["r"])},
            "key_sections": ev["expected"], "key_in_evidence": ev["in_evidence"], "statute_key": ev["statute_key"],
            "required_dropped": len(sel.get("required_dropped") or []), "dropped": len(sel.get("dropped") or []),
            "tokens": {"A": [(xa["r"] or {}).get("input_tokens"), (xa["r"] or {}).get("output_tokens")],
                       "B": [(xb["r"] or {}).get("input_tokens"), (xb["r"] or {}).get("output_tokens")]},
        }
    pq = out["per_question"].values()
    applied = [p for p in pq if p["switch_applied_B"]]
    untouched = [p for p in pq if not p["switch_applied_B"]]
    out["summary"] = {
        "questions": len(out["per_question"]),
        "shape_counts": dict(Counter(p["shape"] for p in pq)),
        "switch_applied_in_B": len(applied), "format_line_in_A": sum(p["format_line_in_A"] for p in pq),
        "general_modes": dict(Counter(p["mode"] for p in applied)),
        "same_sources_all": all(p["same_sources"] for p in pq),
        "answers_changed_where_switch_applied": sum(not p["same_answer"] for p in applied),
        "answers_changed_where_prompt_identical": sum(not p["same_answer"] for p in untouched),
        "key_in_evidence": sum(bool(p["key_in_evidence"]) for p in pq),
        "key_sections_expected": sum(bool(p["key_sections"]) for p in pq),
        "statute_key": sum(p["statute_key"] for p in pq),
        "questions_with_required_dropped": sum(p["required_dropped"] > 0 for p in pq),
        "questions_with_any_dropped": sum(p["dropped"] > 0 for p in pq),
    }
    return out


def verdicts(root: Path, out: dict) -> dict:
    sc = root / "scoring"
    mapping = json.loads((sc / "blind_map.json").read_text(encoding="utf-8"))
    v = {}
    for p in sorted(sc.glob("blind_verdicts_batch_*.json")):
        for k, x in json.loads(p.read_text(encoding="utf-8")).items():
            assert k not in v, f"duplicate {k}"
            v[k] = x
    missing, extra = sorted(set(mapping) - set(v)), sorted(set(v) - set(mapping))
    assert not missing and not extra, (missing, extra)
    for k, x in v.items():
        assert x["ce"] in (0, 1) and x["fab"] in (0, 1) and x["sub"] in (0, 1, 2) and x["comp"] in (0, 1, 2) and x["scope"] in (0, 1), k
    arms = {"A": {r["q"]["ID"]: r for r in load_run(root / "arm_A_switch_off")},
            "B": {r["q"]["ID"]: r for r in load_run(root / "arm_B_switch_on")}}
    per = {}
    for iid, armlist in mapping.items():
        qid = iid.split("#")[0]
        for arm in armlist:
            x = v[iid]
            r = arms[arm][qid]["r"]
            cat = NEV if x.get("not_evaluable") else category(x, (r or {}).get("execution_status"))
            per.setdefault(qid, {})[arm] = {**{k: x[k] for k in ("ce", "fab", "sub", "comp", "scope")}, "category": cat,
                                            "why": x["why"], "item": iid}
    out["verdicts"] = per
    res = {}
    for arm in ("A", "B"):
        cats = Counter(per[q][arm]["category"] for q in per)
        res[arm] = {"categories": {c: cats.get(c, 0) for c in (PASS, PPASS, PFAIL, FAIL, NEV, NE)},
                    "fabricated": sum(per[q][arm]["fab"] for q in per),
                    "citation_exact": sum(per[q][arm]["ce"] for q in per),
                    "sub": dict(Counter(per[q][arm]["sub"] for q in per)),
                    "comp": dict(Counter(per[q][arm]["comp"] for q in per)),
                    "scope_fail": sum(1 - per[q][arm]["scope"] for q in per)}
    trans = Counter((per[q]["A"]["category"], per[q]["B"]["category"]) for q in per)
    better = sorted(q for q in per if per[q]["A"]["category"] in ORDER and per[q]["B"]["category"] in ORDER
                    and ORDER[per[q]["B"]["category"]] > ORDER[per[q]["A"]["category"]])
    worse = sorted(q for q in per if per[q]["A"]["category"] in ORDER and per[q]["B"]["category"] in ORDER
                   and ORDER[per[q]["B"]["category"]] < ORDER[per[q]["A"]["category"]])
    new_fab = sorted(q for q in per if per[q]["B"]["fab"] > per[q]["A"]["fab"])
    gone_fab = sorted(q for q in per if per[q]["B"]["fab"] < per[q]["A"]["fab"])
    sub_up = sorted(q for q in per if per[q]["B"]["sub"] > per[q]["A"]["sub"])
    sub_down = sorted(q for q in per if per[q]["B"]["sub"] < per[q]["A"]["sub"])
    pq = out["per_question"]
    # validator false negatives: a generated answer delivered as valid that the rubric finds wrong or invented
    fn = {arm: sorted(q for q in per if pq[q]["kind"][arm] == "answer" and (per[q][arm]["sub"] == 0 or per[q][arm]["fab"] == 1))
          for arm in ("A", "B")}
    abst = {}
    for arm in ("A", "B"):
        c = Counter()
        for q in per:
            k = pq[q]["kind"][arm]
            ev = bool(pq[q]["key_in_evidence"])
            c[f"{k}|key_in_evidence={ev}"] += 1
        abst[arm] = dict(sorted(c.items()))
    out["comparison"] = {"by_arm": res, "transitions": {f"{a} -> {b}": n for (a, b), n in sorted(trans.items())},
                         "improved": better, "regressed": worse, "new_fabrication": new_fab, "removed_fabrication": gone_fab,
                         "substantive_up": sub_up, "substantive_down": sub_down,
                         "validator_false_negatives": fn, "abstention_by_evidence": abst}
    return out


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    out = facts(root)
    if "--facts-only" not in sys.argv:
        out = verdicts(root, out)
    (root / "scoring").mkdir(exist_ok=True)
    name = "facts.json" if "--facts-only" in sys.argv else "analysis.json"
    (root / "scoring" / name).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("arms", "summary") if k in out}, indent=1, default=str))
    if "comparison" in out:
        print(json.dumps(out["comparison"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
