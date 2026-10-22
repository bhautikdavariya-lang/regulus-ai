"""H2 from existing logs only (no inference): the Step 6 arm A run (Qwen3-1.7B MLX 4-bit, production switch-off arm,
pre-repair database). Per question: which required paragraphs (verified key) were in the context the model received,
whether a scope or gate rule blocked generation, whether the model was called, whether the model declined, and what the validator did. Writes <out_dir>/h2_existing_logs.json."""
import json, re, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
A = ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off"
OUT = Path(sys.argv[1]).resolve()
src = (ROOT / "artifacts/retrieval_rootcause_20261021/tools/trace_retrieval.py").read_text()
ns = {}
exec(compile("import re\n" + src[src.index("CITE = re.compile"):src.index("def tsq(")], "helpers", "exec"), ns)
SEL = {q["ID"]: q for q in json.loads((A / "selection.json").read_text())["questions"]}
DECLINE = re.compile(r"do not provide enough information to answer this", re.I)
rows = {}
for f in sorted((A / "responses").glob("*.json")):
    d = json.loads(f.read_text())
    qid = f.stem
    req = ns["required"](SEL[qid])
    ctx = [s.get("citation") or "" for s in d.get("sources") or []]
    labels = []
    for sec, paras in req.items():
        for p in sorted(paras) or [""]:
            labels.append((f"21 CFR {sec}{'(' + p + ')' if p else ''}", sec, p))
    inctx = [lab for lab, sec, p in labels if any(ns["split_cit"](c)[0] == sec and (not p or (ns["split_cit"](c)[1] or "").startswith(f"({p})")) for c in ctx)]
    # the UI response omits the raw output. With no fallback, the delivered answer is the model's own text. The
    # definitions_quoted fallback replaces a bare model decline. REPORT.md uses validation.initial.answer_class for
    # the final counts (this substring match also counts 3 answers that append the sentence to content)
    answer = d.get("answer") or ""
    val = d.get("validation") or {}
    rows[qid] = {"required": len(labels), "required_in_context": len(inctx), "scope_policy": (d.get("scope_policy") or {}).get("status"),
                 "gate_state": (d.get("answerability") or {}).get("state"), "generation_blocked": d.get("generation_blocked"),
                 "model_called": d.get("model_called"),
                 "model_declined": bool(d.get("model_called")) and d.get("fallback_type") in (None, "definitions_quoted") and bool(DECLINE.search(answer)), "fallback_type": d.get("fallback_type"), "repair": d.get("repair") or (val.get("repair") if isinstance(val, dict) else None),
                 "answer_start": (d.get("answer") or "")[:140]}
groups = {"all_required_in_context": [q for q, r in rows.items() if r["required"] and r["required_in_context"] == r["required"]],
          "some_required_in_context": [q for q, r in rows.items() if r["required"] and 0 < r["required_in_context"] < r["required"]],
          "none_in_context": [q for q, r in rows.items() if r["required"] and r["required_in_context"] == 0]}
summary = {g: {"questions": len(qs), "scope_or_gate_blocked": sum(1 for q in qs if rows[q]["generation_blocked"]),
               "scope_status": dict(Counter(rows[q]["scope_policy"] for q in qs)),
               "model_called": sum(1 for q in qs if rows[q]["model_called"]),
               "model_declined": sum(1 for q in qs if rows[q]["model_declined"]),
               "fallback_types": dict(Counter(rows[q]["fallback_type"] for q in qs))} for g, qs in groups.items()}
(OUT / "h2_existing_logs.json").write_text(json.dumps({"summary": summary, "groups": groups, "per_question": rows}, indent=1, ensure_ascii=False))
print(json.dumps(summary, indent=1))
for q in groups["all_required_in_context"] + groups["some_required_in_context"][:6]:
    r = rows[q]; print(q, {k: r[k] for k in ("required", "required_in_context", "generation_blocked", "model_called", "model_declined", "fallback_type")}, "|", r["answer_start"][:90])
