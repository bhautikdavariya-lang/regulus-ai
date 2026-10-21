"""Step 3B blind scoring packets from the framed run (framing_3b/run/answers.jsonl).

    python build_scoring_3b.py <experiment_dir>

Checks first that every prompt sent equals the previewed prompt (framing_3b/preview.json). Each question shows the
question as asked, the verified key and the pre-registered checklist. Its items are the model's raw output and, when
different, the delivered answer after validator repair, in a seeded random order (X/Y), unlabelled. Each item comes
with its [n] markers resolved and the evidence its model was given. Writes framing_3b/scoring/ only.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

E = Path(sys.argv[1]).resolve()
F = E / "framing_3b"
ROOT = E.parents[2]
SEL = {q["ID"]: q for q in json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json").read_text())["questions"]}
CRIT = json.loads((E / "recovered_step3/criteria.json").read_text())["questions"]
preview = json.loads((F / "preview.json").read_text(encoding="utf-8"))
run = [json.loads(l) for l in (F / "run/answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
norm = lambda t: " ".join((t or "").split())
DECLINE = "do not provide enough information to answer this"


def sources(prompt):
    body = prompt.split("<<<SOURCES\n", 1)[1].split("\n>>>END SOURCES", 1)[0]
    out = []
    for part in re.split(r"\n\n(?=SOURCE \d+\n)", body):
        m = re.match(r"SOURCE (\d+)\n(?:.*\n)*?Citation: ([^\n]+)\n(?:Heading: [^\n]*\n)?Text:\n(.*)", part, re.S)
        if m:
            out.append((int(m.group(1)), m.group(2), " ".join(m.group(3).split())))
    return out


def markers(answer, mapping):
    seen = []
    for n in re.findall(r"\[(\d+)\]", answer or ""):
        item = f"[{n}] = {mapping.get(int(n), 'UNRESOLVED')}"
        if item not in seen:
            seen.append(item)
    return "; ".join(seen) or "none"


same_prompt = {r["qid"]: r["prompt_user"] == preview[r["qid"]]["framed_prompt"] for r in run}
assert all(same_prompt.values()), same_prompt
rng = random.Random(20261021)
blocks, mapping = [], {}
for r in run:
    q, c = r["qid"], CRIT[r["qid"]]
    src = sources(r["prompt_user"])
    smap = {i: cit for i, cit, _ in src}
    evidence = "\n".join(f"  SOURCE {i}: {cit}\n    {txt}" for i, cit, txt in src)
    head = [f"QUESTION {q} (as asked): {r['question']}",
            f"VERIFIED KEY - expected citation: {SEL[q]['Expected Citation — VERIFIED KEY']}",
            f"VERIFIED KEY - key answer elements: {SEL[q]['Key Answer Elements']}",
            "CHECKLIST (pre-registered): required elements:"]
    head += [f"  {rid} ({'core' if core else 'supporting'}): {text}" for rid, text, core in c["required"]]
    head.append("  critical errors: " + "; ".join(c["critical"]))
    if c["not_in_evidence"]:
        head.append("  NOT in the stored regulatory text (do not expect from any answer): " + "; ".join(c["not_in_evidence"]))
    variants = [("raw", r["raw_model_output"])]
    if norm(r["delivered_answer"]) != norm(r["raw_model_output"]):
        variants.append(("delivered", r["delivered_answer"]))
    rng.shuffle(variants)
    body = []
    for label, (kind, text) in zip(("X", "Y"), variants):
        iid = f"{q}#{label}"
        mapping[iid] = kind
        body += [f"--- ITEM {iid}", "ANSWER:", text or "(none)", f"MARKERS: {markers(text, smap)}",
                 "EVIDENCE THIS ANSWER'S MODEL WAS GIVEN:", evidence]
    blocks.append("\n".join(head + body))
out = F / "scoring"
(out / "packets").mkdir(parents=True, exist_ok=True)
(out / "blind_map.json").write_text(json.dumps(mapping, indent=1), encoding="utf-8")
for n in range(2):
    (out / "packets" / f"batch_0{n + 1}.txt").write_text(("\n\n" + "=" * 100 + "\n").join(blocks[n * 4:(n + 1) * 4]) + "\n", encoding="utf-8")
print(f"prompts equal preview: {sum(same_prompt.values())}/8; {len(mapping)} items "
      f"({sum(1 for v in mapping.values() if v == 'delivered')} delivered variants differ from raw)")
for r in run:
    print(f"{r['qid']:16} raw decline-sentence: {DECLINE in (r['raw_model_output'] or '').lower()} | raw chars {len(r['raw_model_output'])} | "
          f"tokens {r['generation']['prompt_tokens']}->{r['generation']['generated_tokens']}/{r['generation']['max_new_tokens']} finished {r['generation']['finished']} | repair {str(r.get('repair'))[:50]}")
