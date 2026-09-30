"""Audit-only analysis of audit/results/battery.jsonl. Reads only."""
import json, re, sys
from collections import OrderedDict
sys.path.insert(0, "src")
from regulus.retrieval.query import classify
from regulus.evaluation.grounding_eval import classify_answer

PROV = OrderedDict([
    ("(b)(1)", ["part 830", "unique device identification", "udi"]),
    ("(b)(2)", ["part 821", "traceability"]),
    ("(b)(3)", ["part 803", "complaint"]),
    ("(b)(4)", ["part 806", "advisory notice"]),
])
LEAK = {"E1": ["paris"], "E2": ["shakespeare"], "E3": ["100"], "F1": ["million", "population of paris is", "2,1", "2.1"], "F3": ["eiffel", "1889", "gustave"]}
rows = [json.loads(l) for l in open("audit/results/battery.jsonl", encoding="utf-8") if l.strip()]
out = []
for r in rows:
    q = r["question"]; a = r.get("answer") or ""
    cq = classify(q)
    ref = cq.cfr
    ref_s = f"{ref.section}{ref.paragraph_path or ''}" if ref and ref.section else (f"Part {ref.part}" if ref else None)
    ctx_labels = [s["citation"] for s in r.get("sources", [])]
    in_ctx = [p for p in PROV if any(f"820.10{p}" == lab or lab.startswith(f"820.10{p}") or lab == f"21 CFR 820.10{p}" for lab in ctx_labels)]
    parent_in_ctx = any(lab == "21 CFR 820.10(b)" for lab in ctx_labels)
    al = a.lower()
    in_ans = [p for p, keys in PROV.items() if any(k in al for k in keys)]
    kind = classify_answer(a) if a else "empty"
    markers = re.findall(r"(?<![A-Za-z0-9])\[(\d{1,2})\]", a)
    valid_markers = [m for m in markers if 1 <= int(m) <= len(r.get("sources", []))]
    cut = (r.get("output_tokens") == 128) and not a.rstrip().endswith((".", "!", "?", "]"))
    leak = [w for w in LEAK.get(r["id"].split("-")[0], []) if w in al]
    g = r.get("grounding") or {}
    out.append(dict(id=r["id"], cat=r["_category"], gate=r["_gate"], qtype=cq.query_type.name, parsed=ref_s,
                    exact_in_ctx=in_ctx, parent=parent_in_ctx, in_answer=in_ans, kind=kind,
                    markers=markers, valid=len(valid_markers) == len(markers), cut=cut, leak=leak,
                    gate_action=g.get("action"), gate_reason=g.get("reason"), model_called=r.get("model_called"),
                    n_ctx=len(r.get("sources", [])), dropped=r.get("dropped_sources"), methods=[s["method"] for s in r.get("sources", [])],
                    corpora=[s["corpus"] for s in r.get("sources", [])],
                    fallback=r.get("retrieval", {}).get("fallback_used"), primary=r.get("retrieval", {}).get("primary_result_count"),
                    ret_ms=round((r.get("timings_ms") or {}).get("retrieval_ms", 0)), gen_ms=round((r.get("timings_ms") or {}).get("generation_ms", 0)),
                    tot_ms=round((r.get("timings_ms") or {}).get("total_ms", 0)), tin=r.get("input_tokens"), tout=r.get("output_tokens"),
                    error=r.get("_error")))
for o in out:
    print(json.dumps(o, ensure_ascii=False))
