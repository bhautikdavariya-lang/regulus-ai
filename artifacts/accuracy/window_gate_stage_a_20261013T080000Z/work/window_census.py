"""READ-ONLY census of every adjacent-window decision the evaluator makes over the frozen data (no generation).
Datasets: F60 (frozen_inputs_60, both aligners), GUIDE8, REAL17 (both aligners) - the established 170 row-runs -
plus the test fixtures' frozen rows (extraction, real, content-gate, contradiction, relative-clause, numeric).
For each judge_window call that reaches the run gate (verdict borne out, overlap >= 0.85, two halves), it records
the verbatim runs into each half and each half's own core terms, so the effect of any own-terms threshold can be
read off without re-running. Run with PYTHONPATH=src from the repo root."""
import json, sys, importlib.util
sys.path.insert(0, ".")
from pathlib import Path
OUT = sys.argv[1]
from regulus.accuracy import evaluate, verdicts as VD
from regulus.accuracy.alignment import SemanticAligner, LexicalAligner
from regulus.accuracy.attribution import longest_run, normalise, strip_lead
from regulus.accuracy.intent import same_term
from regulus.evaluation.grounding_eval import split_sentences
from regulus.retrieval.semantic import TransformersEmbedder, load_manifest
from regulus.retrieval import Database
from regulus.grounding import DatabaseIdentifierIndex
from regulus.config import load_settings
spec = importlib.util.spec_from_file_location("av", "scripts/accuracy_validate.py"); av = importlib.util.module_from_spec(spec)
sys.modules["av"] = av; spec.loader.exec_module(av)
import tests.test_accuracy_guidance_logic as TG
import tests.test_accuracy_relevance as TR
import tests.test_accuracy_claim_extraction as TX

ctx, seen = {}, []
_orig = VD.judge_window
def probe(claim, windows, *, evidence=None):
    out = _orig(claim, windows, evidence=evidence)
    rec = {**ctx, "claim": claim, "result": out.verdict if out else None}
    if windows:
        v = VD.judge(claim, LexicalAligner().align(claim, windows), evidence=evidence)
        rec["window_verdict"] = v.verdict
        if v.alignment is not None:
            halves = split_sentences(v.alignment.passage.text)
            rec.update(window=v.alignment.passage.text, citation=v.alignment.passage.citation,
                       overlap=round(v.alignment.overlap, 3), halves=len(halves))
            if v.verdict in VD.BORNE_OUT and len(halves) >= 2 and v.alignment.overlap >= VD.WINDOW_MIN_OVERLAP:
                words = normalise(strip_lead(claim)).split()
                core = VD.core_terms(claim); st = [VD._stems(h) for h in halves[:2]]
                has = lambda t, s: any(same_term(t, x) for x in s)
                own = [sorted(t for t in core if has(t, st[i]) and not has(t, st[1 - i])) for i in (0, 1)]
                rec.update(reached_run_gate=True, runs=[longest_run(words, normalise(h))[0] for h in halves[:2]],
                           own_terms=own, core=sorted(core))
    seen.append(rec)
    return out
VD.judge_window = probe

sem = SemanticAligner(TransformersEmbedder(load_manifest().embedding, cache_dir=load_settings().model.cache_dir, local_files_only=True))
db = Database.from_env(); db.connect(); index = DatabaseIdentifierIndex(db)
ALIGNERS = (("semantic", sem), ("lexical", LexicalAligner()))
runs = 0
for r in json.load(open("artifacts/accuracy/priority3_claim_extraction_ab_2026-10-08/frozen_inputs_60.json")):
    srcs = tuple(av.Src(index=s["index"], citation=s["citation"], text=s["text"], heading=s["heading"], citation_fields=s["citation_fields"]) for s in r["sources"])
    reqs = tuple(tuple(x) for x in r["requirements"])
    for arm, al in ALIGNERS:
        ctx.clear(); ctx.update(dataset="F60", row=r["id"], aligner=arm); runs += 1
        evaluate(r["question"], r["answer"], package=av.Pkg(r["question"], reqs, tuple(r["satisfied_ids"]), srcs),
                 coverage=av.Cov(reqs, tuple(r["satisfied_ids"]), tuple(r["missing_labels"]), r["explicit"]), validation=None,
                 model_called=r["model_called"], fallback_type=r["fallback_type"], scope_status=r["scope"],
                 answerability={"state": r["answerability"]} if r["answerability"] else None,
                 identifier_index=index, aligner=al, evidence_provenance="legacy_reconstructed")
for rid, row in TG.REAL.items():
    srcs = tuple(TG.Src(i + 1, s["citation"], s["text"], s["corpus"], is_docket=s["corpus"] == "fda_guidance") for i, s in enumerate(row["sources"]))
    for arm, al in ALIGNERS:
        ctx.clear(); ctx.update(dataset="GUIDE8", row=rid, aligner=arm); runs += 1
        evaluate(row["question"], row["answer"] or "", package=TG.Pkg(row["question"], srcs), coverage=TG.Cov(),
                 model_called=row["model_called"], fallback_type=row["fallback_type"], aligner=al)
for rid, row in TR.REAL.items():
    srcs = [(s["citation"], s["text"], s.get("heading")) for s in row["sources"]]
    for arm, al in ALIGNERS:
        ctx.clear(); ctx.update(dataset="REAL17", row=rid, aligner=arm); runs += 1
        TR.run(row["question"], row["answer"] or "", srcs, model_called=row["model_called"], fallback_type=row["fallback_type"],
               answerability={"state": row["answerability"]} if row.get("answerability") else None, aligner=al)
for table_name in ("ROWS", "REAL", "GUIDE"):
    for rid in getattr(TX, table_name):
        ctx.clear(); ctx.update(dataset=f"TX.{table_name}", row=rid, aligner="lexical"); runs += 1
        try: TX.frozen(rid, getattr(TX, table_name))
        except Exception as e: seen.append({**ctx, "error": repr(e)[:200]})
for fx in ("accuracy_content_gate_rows", "accuracy_contradiction_rows", "accuracy_relative_clause_rows", "accuracy_numeric_limit_rows"):
    data = json.load(open(f"tests/fixtures/{fx}.json")); rows = data["rows"] if isinstance(data, dict) else data
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or "claim" not in row and "answer" not in row: continue
        q = row.get("question") or "What is required?"; a = row.get("answer") or row.get("claim")
        srcs = row.get("sources") or ([{"citation": row.get("citation") or "21 CFR 1.1", "text": row.get("evidence") or row.get("source_text") or ""}])
        srcs = tuple(TX.Src(j + 1, s.get("citation") or "21 CFR 1.1", s.get("text") or "", s.get("heading")) for j, s in enumerate(srcs) if isinstance(s, dict))
        if not srcs or not a: continue
        ctx.clear(); ctx.update(dataset=fx, row=row.get("id", i), aligner="lexical"); runs += 1
        try: evaluate(q, a, package=TX.Pkg(q, srcs), coverage=TX.Cov(), aligner=LexicalAligner())
        except Exception as e: seen.append({**ctx, "error": repr(e)[:200]})
db.close()
Path(OUT).write_text(json.dumps({"row_runs": runs, "calls": seen}, ensure_ascii=False, indent=0))
gate = [c for c in seen if c.get("reached_run_gate")]
print("row-runs", runs, "window calls", len(seen), "reached run gate", len(gate),
      "accepted now", sum(1 for c in seen if c.get("result")), "errors", sum(1 for c in seen if "error" in c))
