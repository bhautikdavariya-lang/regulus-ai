"""Read-only: the same leg-independent coverage signal (signal_check.py) on a larger labelled set, and on the
displacement cases. Items = every source in the base and F2-wide contexts of the 100 cosmetics questions
(retrieval_fixb_f2_20261021/eval/eval100.json, texts as given to the model), labelled required (the verified key's
paragraph) or not; plus the D-experiment contexts for COS-701.12-Q2. Writes <out>/signal_check2.json.

    python signal_check2.py <out_dir>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guarded  # noqa: E402,F401
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.query import content_terms  # noqa: E402
from signal_check import TEXT_LEX, WEIGHTS_SQL, auc  # noqa: E402

sys.path.insert(0, str(ROOT / "artifacts/retrieval_rootcause_20261021/tools"))
src = (ROOT / "artifacts/retrieval_rootcause_20261021/tools/trace_retrieval.py").read_text()
ns = {}
exec(compile("import re\n" + src[src.index("CITE = re.compile"):src.index("def tsq(")], "helpers", "exec"), ns)
SEL = {q["ID"]: q for q in json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json").read_text())["questions"]}
OUT = Path(sys.argv[1]).resolve()
E = json.loads((ROOT / "artifacts/retrieval_fixb_f2_20261021/eval/eval100.json").read_text())["questions"]
DC = json.loads((ROOT / "artifacts/retrieval_selection_d_20261021/candidates.json").read_text())["questions"]


def main() -> int:
    db = Database.from_env()
    db.connect()
    rows, cases = {}, {}
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        def score(q, text, extra=""):
            w = W.setdefault(q, {r["l"]: float(r["idf"]) for r in db.query(WEIGHTS_SQL, {"q": " ".join(content_terms(q))})})
            mass = sum(w.values()) or 1.0
            lex = set(db.query(TEXT_LEX, {"t": text})[0]["a"] or []) | set(db.query(TEXT_LEX, {"t": extra})[0]["a"] or [])
            return round(sum(v for l, v in w.items() if l in lex) / mass, 4)
        W = {}
        for qid, r in E.items():
            if not r["general"]:
                continue
            req = ns["required"](SEL[qid])
            for cond in ("base", "wide"):
                for s in r[cond]["sources"]:
                    k = (qid, s["key"])
                    if k in rows:
                        continue
                    sec, path = ns["split_cit"](s["citation"])
                    is_req = s["corpus"] == "ecfr" and ns["is_required"](s["citation"], req) and s["citation"] != "21 CFR 740.11(i)"
                    rows[k] = {"qid": qid, "citation": s["citation"][:90], "corpus": s["corpus"], "required": bool(is_req),
                               "chars": s["chars"], "coverage": score(r["question"], s["text"], s["citation"])}
        # displacement cases
        for qid, keep, cond_a, cond_b, data in (("COS-74.2602a-Q1", "81.30(i)", "base", "wide", E), ("COS-701.12-Q2", None, "base", "v1", DC)):
            q = data[qid]["question"]
            seen = {}
            for cond in (cond_a, cond_b):
                for s in data[qid][cond]["sources"]:
                    if s["key"] in seen:
                        seen[s["key"]]["in"].append(cond)
                        continue
                    seen[s["key"]] = {"citation": s["citation"][:80], "corpus": s["corpus"], "chars": s["chars"],
                                      "coverage": score(q, s.get("text") or "", s["citation"]), "in": [cond]}
            cases[qid] = sorted(seen.values(), key=lambda x: -x["coverage"])
    finally:
        db.close()
    items = list(rows.values())
    req = [i["coverage"] for i in items if i["required"]]
    ecfr_non = [i["coverage"] for i in items if not i["required"] and i["corpus"] == "ecfr"]
    guid = [i["coverage"] for i in items if i["corpus"] != "ecfr"]
    med = lambda xs: round(sorted(xs)[len(xs) // 2], 3) if xs else None
    summ = {"items": len(items), "required": len(req), "auc_required_vs_nonrequired_ecfr": auc(req, ecfr_non),
            "auc_required_vs_guidance": auc(req, guid), "median_required": med(req), "median_nonrequired_ecfr": med(ecfr_non),
            "median_guidance": med(guid)}
    (OUT / "signal_check2.json").write_text(json.dumps({"summary": summ, "cases": cases, "items": items}, indent=1, ensure_ascii=False))
    print(json.dumps(summ, indent=1))
    for qid, c in cases.items():
        print("==", qid)
        for x in c:
            print(f"   {x['coverage']:.3f} {x['corpus'][:8]:8} {x['chars']:5} in={x['in']} {x['citation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
