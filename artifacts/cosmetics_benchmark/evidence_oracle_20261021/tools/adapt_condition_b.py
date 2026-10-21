"""Condition B records from the restored oracle run, plus the pre-registered restoration check.

    python adapt_condition_b.py <experiment_dir>

Reads run/answers.jsonl (written by recovered_step3/oracle_run.py) and recovered_step3/recovered_outputs.json.
Writes condition_b.jsonl (delivered answer, source map and the exact evidence in the prompt) and
restoration_check.json. The rule (PREREGISTRATION.md): every raw output byte-identical to Step 3's; COS-82.101-Q1
delivered identical; COS-70.50-Q2 delivered starts with Step 3's first 900 chars and ends with its last 1,500.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

E = Path(sys.argv[1]).resolve()
run = [json.loads(l) for l in (E / "run/answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
rec = json.loads((E / "recovered_step3/recovered_outputs.json").read_text(encoding="utf-8"))


def sources(prompt):
    block = prompt.split("SOURCE 1\n", 1)
    if len(block) < 2:
        return []
    body = "SOURCE 1\n" + block[1]
    out = []
    for part in re.split(r"\n\n(?=SOURCE \d+\n)", body):
        m = re.match(r"SOURCE (\d+)\n(?:.*\n)*?Citation: ([^\n]+)\n(?:Heading: [^\n]*\n)?Text:\n(.*)", part, re.S)
        if m:
            text = m.group(3)
            text = re.split(r"\n<<<|\n>>>|\n\[END OF SOURCES\]|\nEND SOURCES", text)[0]
            out.append((int(m.group(1)), m.group(2), " ".join(text.split())))
    return out


checks, out = {}, []
for r in run:
    q, ref = r["qid"], rec[r["qid"]]
    raw_ok = r["raw_model_output"] == ref["raw_model_output"]
    d = r["delivered_answer"] or ""
    if q == "COS-82.101-Q1":
        delivered_ok = d == ref["delivered_full"]
    elif q == "COS-70.50-Q2":
        delivered_ok = d.startswith(ref["delivered_first_900"]) and d.endswith(ref["delivered_last_1500"]) and len(d) == ref["delivered_chars"]
    elif ref["delivered_differs_from_raw"]:
        delivered_ok = d == ref["delivered_first_900"]
    else:
        delivered_ok = d.strip() == ref["raw_model_output"].strip()
    tokens_ok = (r["generation"]["prompt_tokens"], r["generation"]["generated_tokens"]) == (ref["prompt_tokens"], ref["generated_tokens"])
    checks[q] = {"raw_identical": raw_ok, "delivered_consistent": delivered_ok, "token_counts_identical": tokens_ok}
    src = sources(r["prompt_user"])
    out.append({"qid": q, "delivered_answer": d, "raw_model_output": r["raw_model_output"], "fallback_type": r.get("fallback_type"),
                "source_map": {i: c for i, c, _ in src}, "prompt_sources": src,
                "packet_fully_delivered": r.get("packet_fully_delivered"), "packet_rows_in_prompt": r.get("packet_rows_in_prompt"),
                "generation": r.get("generation"), "timings_ms": r.get("timings_ms"), "wall_seconds": r.get("wall_seconds"),
                "validation_initial": r.get("validation_initial"), "validation_final": r.get("validation_final"), "repair": r.get("repair")})
valid = all(all(v.values()) for v in checks.values()) and len(checks) == 12
(E / "restoration_check.json").write_text(json.dumps({"valid": valid, "per_question": checks}, indent=1), encoding="utf-8")
(E / "condition_b.jsonl").write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out), encoding="utf-8")
print(json.dumps({"valid": valid, "failed": {q: v for q, v in checks.items() if not all(v.values())}}, indent=1))
for o in out:
    print(f"{o['qid']:16} sources in prompt {len(o['prompt_sources']):2} | packet fully delivered {o['packet_fully_delivered']}")
