"""Read-only feasibility check for a relevance-based selector: does a leg-independent question-coverage signal,
computed from each passage's own text, separate blind-judged R2 passages from R1/R0, and required paragraphs from the
rest? No model, no embedding model; SELECT-only database (guarded.py). Writes <out>/signal_check.json.

    python signal_check.py <out_dir>

Signal: the question's content lexemes (query.content_terms, as section coverage uses them), each weighted by its
section-level idf over cfr_records (as sql.ECFR_SECTION_COVERAGE weights them); a passage's coverage = weight of the
lexemes its own text (plus its citation heading / guidance title) contains / total weight.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval.query import content_terms  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
D1 = ROOT / "artifacts/retrieval_selection_d_20261021"
F2 = ROOT / "artifacts/retrieval_fixb_f2_20261021"

WEIGHTS_SQL = """
WITH lex AS (SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', %(q)s))) AS l),
df AS (SELECT lex.l, count(DISTINCT r.section_number) AS n FROM lex JOIN cfr_records r ON r.search_vector @@ quote_literal(lex.l)::tsquery
       WHERE r.removed_on IS NULL AND NOT r.is_reserved GROUP BY lex.l),
total AS (SELECT count(*)::float8 AS n FROM cfr_sections WHERE NOT is_reserved)
SELECT lex.l, COALESCE(ln(GREATEST(total.n / NULLIF(df.n, 0), 1.0)), ln(total.n)) AS idf FROM lex LEFT JOIN df USING (l), total
"""
TEXT_LEX = "SELECT tsvector_to_array(to_tsvector('english', %(t)s)) AS a"


def auc(pos, neg):
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    rel = json.loads((D1 / "relevance.json").read_text())
    for b in json.loads((D1 / "pool_blind.json").read_text()):
        items.append({"source": "guidance (exp D)", "item": b["item"], "question": b["question"], "text": b["passage"],
                      "extra": b["guidance_document"], "label": rel[b["item"]]["label"]})
    jud = json.loads((F2 / "judgements.json").read_text())["items"]
    for b in json.loads((F2 / "pool_blind.json").read_text()):
        items.append({"source": "ecfr (F2)", "item": b["item"], "question": b["question"], "text": b["passage"],
                      "extra": b["citation"], "label": jud[b["item"]]["final"]})
    db = Database.from_env()
    db.connect()
    weights = {}
    try:
        assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
        for it in items:
            q = it["question"]
            if q not in weights:
                weights[q] = {r["l"]: float(r["idf"]) for r in db.query(WEIGHTS_SQL, {"q": " ".join(content_terms(q))})}
            w = weights[q]
            mass = sum(w.values()) or 1.0
            body = set(db.query(TEXT_LEX, {"t": it["text"]})[0]["a"] or [])
            withx = body | set(db.query(TEXT_LEX, {"t": it["extra"] or ""})[0]["a"] or [])
            it["coverage_text"] = round(sum(v for l, v in w.items() if l in body) / mass, 4)
            it["coverage_with_title"] = round(sum(v for l, v in w.items() if l in withx) / mass, 4)
            it["chars"] = len(it["text"])
    finally:
        db.close()
    res = {}
    for sig in ("coverage_text", "coverage_with_title"):
        for src in ("guidance (exp D)", "ecfr (F2)", "all"):
            sub = [i for i in items if src == "all" or i["source"] == src]
            r2 = [i[sig] for i in sub if i["label"] == "R2"]
            rest = [i[sig] for i in sub if i["label"] != "R2"]
            r1p = [i[sig] for i in sub if i["label"] in ("R1", "R2")]
            r0 = [i[sig] for i in sub if i["label"] == "R0"]
            med = lambda xs: round(sorted(xs)[len(xs) // 2], 3) if xs else None
            res[f"{sig} | {src}"] = {"n": len(sub), "R2": len(r2), "auc_R2_vs_rest": auc(r2, rest), "auc_R1+_vs_R0": auc(r1p, r0),
                                    "median_R2": med(r2), "median_R1": med([i[sig] for i in sub if i["label"] == "R1"]), "median_R0": med(r0)}
    (OUT / "signal_check.json").write_text(json.dumps({"summary": res, "items": [{k: v for k, v in i.items() if k != "text"} for i in items]},
                                                      indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
