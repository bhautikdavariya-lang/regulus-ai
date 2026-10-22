"""Retrieval-only probe (no model, read-only database): does each anchor's dropped source text reach the final context?

    python probe_restored_text.py <out_json>

For each of the 15 anchors: (1) an exact-citation question "What does 21 CFR <section><path> require?"; (2) the benchmark
questions whose verified key needs the anchor (dependent_questions.json). The expected text is the plan's restored
body_text (from the hash-verified payload). Records the final context (citation, chars) and whether each expected
text appears, whole or truncated, in a context source. Writes only <out_json>."""
from __future__ import annotations
import json, sys
from pathlib import Path
D = Path(__file__).resolve().parents[1]
ROOT = D.parents[1]
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/retrieval_decision_20261021/tools"))
import guarded  # noqa: E402,F401
from guarded import SEMANTIC_ATTEMPTS  # noqa: E402
from regulus.evaluation import retrieval_baseline as RB  # noqa: E402
from regulus.retrieval.db import Database  # noqa: E402
from regulus.retrieval import lexical as L  # noqa: E402
assert L.ECFR_LITERAL_OR_ENABLED is False
OUT = Path(sys.argv[1]).resolve()
norm = lambda t: " ".join((t or "").split())
plan = json.loads((D / "plan.json").read_text())
expected = {}
for s in plan["sections"]:
    for r in s["inserts"]:
        expected.setdefault(f"{s['section_number']}{r['paragraph_path']}", []).append(r["body_text"])
dep = json.loads((D / "dependent_questions.json").read_text())
SEL = {q["ID"]: q for q in json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json").read_text())["questions"]}


def delivered(text, sources, section):
    """The restored text, whole or as a truncated prefix (selection's TRUNCATION_MARK), in a context source cited to the
    anchor's own section. Identical wording elsewhere (e.g. a parallel drug warning) does not count."""
    from regulus.rag.selection import TRUNCATION_MARK
    t = norm(text)
    for s in sources:
        if not (s.result.citation.label or "").startswith(f"21 CFR {section}("):
            continue
        body = norm(s.text)
        if t == body or t in body:
            return True
        if s.truncated and body.endswith(norm(TRUNCATION_MARK)):
            stem = norm(body[: -len(norm(TRUNCATION_MARK))])
            if len(stem) >= 60 and t.startswith(stem):
                return True
    return False


db = Database.from_env(); db.connect()
res = {"exact_questions": {}, "dependent_questions": {}}
try:
    assert {k: v for k, v in db.status().items() if k != "url"}["default_transaction_read_only"] == "on"
    fp0 = RB.database_fingerprint(db)
    pipe, gen = RB.production_pipeline(db)
    for anchor, texts in sorted(expected.items()):
        q = f"What does 21 CFR {anchor} require?"
        out = pipe.answer(q)
        srcs = out.context.sources
        res["exact_questions"][anchor] = {"question": q, "context": [(s.result.citation.label, len(s.text)) for s in srcs],
                                          "restored_texts": len(texts), "delivered": [delivered(t, srcs, anchor.split("(")[0]) for t in texts]}
    for qid, info in dep.items():
        out = pipe.answer(SEL[qid]["Question (ask verbatim)"])
        srcs = out.context.sources
        res["dependent_questions"][qid] = {"anchors": info["anchors"], "context": [(s.result.citation.label, len(s.text)) for s in srcs],
                                           "delivered": {a: [delivered(t, srcs, a.split("(")[0]) for t in expected[a]] for a in info["anchors"] if a in expected},
                                           "not_in_plan": [a for a in info["anchors"] if a not in expected]}
    fp1 = RB.database_fingerprint(db)
finally:
    db.close()
res["run"] = {"semantic_load_attempts": len(SEMANTIC_ATTEMPTS), "generation_stub_calls": gen.calls,
              "database_unchanged_during_probe": all(fp0[k] == fp1[k] for k in ("corpus_identity", "row_counts", "write_counters")),
              "corpus_identity": fp0["corpus_identity"]}
OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
ex = res["exact_questions"]; dq = res["dependent_questions"]
print("exact-citation questions: restored text delivered", sum(all(v["delivered"]) for v in ex.values()), "/", len(ex),
      "| texts", sum(sum(v["delivered"]) for v in ex.values()), "/", sum(len(v["delivered"]) for v in ex.values()))
print("dependent benchmark questions:", {k: v["delivered"] for k, v in dq.items()})
print(json.dumps(res["run"], default=str)[:400])
