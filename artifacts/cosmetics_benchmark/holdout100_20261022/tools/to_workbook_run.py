"""Convert a scripts/run_cosmetics_eval.py run (answers.jsonl) and its blind double-scored verdicts into the run-directory
layout the cosmetics workbook builder reads (cosmetics100_q17_20261022T035901Z/tools/build_workbook.py):
selection.json (bank rows), results.jsonl, responses/<ID>.json, scoring/verdicts.json, scoring/run_facts.json.

    python to_workbook_run.py <answers.jsonl> <selection.json> <bank.xlsx> <scores.json> <run_facts.json> <out_run_dir>

<scores.json>: {question id: {"plain": {...}, "skeptic": {...}, "adjudicated": {...} | null}} - the two blind scorers'
rubric scores and, where they disagreed on PASS, the adjudicator's. The recorded verdict is the stricter scorer's
(the lower reporting category; the skeptical lens on a tie), or the adjudicator's on a PASS disagreement."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "artifacts/cosmetics_benchmark/cosmetics100_q17_20261022T035901Z/tools"))
from run_cosmetics_eval import read_bank  # noqa: E402
from build_workbook import category, CATEGORIES  # noqa: E402  (the workbook's own category mapping)

answers, sel_path, bank_path, scores_path, facts_path, out = sys.argv[1:7]
out = Path(out); (out / "responses").mkdir(parents=True, exist_ok=True); (out / "scoring").mkdir(exist_ok=True)
rows = {json.loads(l)["id"]: json.loads(l) for l in open(answers, encoding="utf-8") if l.strip()}
sel = json.loads(Path(sel_path).read_text())
ids = sel["summary"]["selected_ids"]
bank = read_bank(Path(bank_path))
scores = json.loads(Path(scores_path).read_text())

questions = []
for n, qid in enumerate(ids, 1):
    b = dict(bank[qid]); b["ID"] = qid; b["Run Order"] = n
    b.setdefault("Stratum", b.get("Part") or b.get("Stratum") or ""); b.setdefault("Question Type", b.get("Question Type") or "")
    b.setdefault("Difficulty", b.get("Difficulty") or "")
    questions.append(b)
(out / "selection.json").write_text(json.dumps({"summary": sel["summary"], "questions": questions}, indent=1, ensure_ascii=False, default=str))

order = {c: i for i, c in enumerate(["NOT EVALUATED", "FAIL", "PARTIALLY FAIL", "PARTIALLY PASS", "PASS"])}
verdicts = {}
with open(out / "results.jsonl", "w", encoding="utf-8") as f:
    for qid in ids:
        r = rows.get(qid)
        if r is None:
            continue
        ok = not r.get("error")
        val = r.get("validation") or {}
        init, fin = val.get("initial") or {}, val.get("final") or {}
        gen = r.get("generation") or {}
        called = bool(r.get("raw"))
        f.write(json.dumps({
            "question_id": qid, "execution_status": "SUCCESS" if ok else "ERROR", "error": r.get("error"),
            "answer": r.get("answer"), "client_seconds": r.get("seconds"),
            "input_tokens": gen.get("prompt_tokens") if called else None, "output_tokens": gen.get("generated_tokens") if called else None,
            "fallback_type": r.get("fallback_type"), "validation_initial": init.get("ok", init.get("status")),
            "validation_initial_codes": sorted({p["code"] for p in init.get("problems", []) if p.get("severity") == "error"}),
            "validation_final": fin.get("ok", fin.get("status")), "repair": val.get("repair"),
            "stop_reason": gen.get("stop_reason"), "finished": gen.get("finished"),
            "semantic_fallback": None, "query_type": None, "evidence_gap": None, "server_timings_ms": {}, "timings_ms": {},
        }, ensure_ascii=False, default=str) + "\n")
        resp = {"answer": r.get("answer"),
                "sources": [{"citation": s[0], "method": s[1]} for s in r.get("sources") or []],
                "citations": [{"index": i + 1, "label": s[0], "cited_in_answer": f"[{i + 1}]" in (r.get("answer") or "")}
                              for i, s in enumerate(r.get("sources") or [])]}
        (out / "responses" / f"{qid}.json").write_text(json.dumps(resp, indent=1, ensure_ascii=False))
        s = scores.get(qid)
        if s:
            p, k, a = s.get("plain"), s.get("skeptic"), s.get("adjudicated")
            cp, ck = category(p, "SUCCESS") if p else None, category(k, "SUCCESS") if k else None
            if a and p and k and ((cp == "PASS") != (ck == "PASS")):
                v = a
            elif p and k:
                v = p if order[cp] < order[ck] else k
            else:
                v = p or k
            verdicts[qid] = {key: v[key] for key in ("ce", "fab", "sub", "comp", "scope", "why")}
(out / "scoring" / "verdicts.json").write_text(json.dumps(verdicts, indent=1, ensure_ascii=False))
(out / "scoring" / "run_facts.json").write_text(Path(facts_path).read_text())
print(len(rows), "answers,", len(verdicts), "verdicts ->", out)
