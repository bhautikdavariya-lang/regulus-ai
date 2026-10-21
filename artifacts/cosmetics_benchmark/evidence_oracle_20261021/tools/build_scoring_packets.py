"""Blind scoring packets: Condition A (Step 6 arm A, pipeline evidence) and Condition B (verified packet), per question.

    python build_scoring_packets.py <experiment_dir> <condition_b_answers.jsonl> [questions_per_batch]

Each question shows the verified key, the pre-registered checklist (recovered_step3/criteria.json) and two items,
X and Y, in a seeded random order. Every item has: how it was delivered, the delivered answer, what each [n] marker
points to, and the full evidence that answer's model saw. The condition behind each item is written only to
scoring/blind_map.json. Writes only under <experiment_dir>/scoring/.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

E = Path(sys.argv[1]).resolve()
B_ANSWERS = Path(sys.argv[2]).resolve()
PER = int(sys.argv[3]) if len(sys.argv) > 3 else 3
ROOT = E.parents[2]
ARM_A = ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off"
SEL = {q["ID"]: q for q in json.loads((ARM_A / "selection.json").read_text(encoding="utf-8"))["questions"]}
CRIT = json.loads((E / "recovered_step3/criteria.json").read_text(encoding="utf-8"))["questions"]
PACKETS = json.loads((E / "packets/packets.json").read_text(encoding="utf-8"))["questions"]
IDS = list(CRIT)
SEED = 20261021
DECLINE = "do not provide enough information to answer this"


def markers(answer, mapping):
    seen = []
    for n in re.findall(r"\[(\d+)\]", answer or ""):
        item = f"[{n}] = {mapping.get(int(n), 'UNRESOLVED')}"
        if item not in seen:
            seen.append(item)
    return "; ".join(seen) or "none"


def kind(answer, fallback):
    if fallback == "unvalidated_answer_withheld":
        return "WITHHELD by the validator (the user saw only the notice below)"
    if fallback:
        return f"FALLBACK '{fallback}' (the user saw this fallback text, not a model-written answer)"
    if DECLINE in (answer or "").lower() and len(answer or "") < 200:
        return "DECLINE (the model's own decline sentence)"
    return "GENERATED answer"


def item_a(qid):
    r = json.loads((ARM_A / "responses" / f"{qid}.json").read_text(encoding="utf-8"))
    mapping = {c.get("index"): c.get("label") for c in r.get("citations") or []}
    mapping.update({s.get("index"): s.get("citation") for s in r.get("sources") or [] if s.get("index") not in mapping})
    evidence = "\n".join(f"  SOURCE {s.get('index')}: {s.get('citation')}\n    {' '.join((s.get('text') or '').split())}" for s in r.get("sources") or [])
    return {"answer": r.get("answer"), "kind": kind(r.get("answer"), r.get("fallback_type")), "markers": markers(r.get("answer"), mapping),
            "evidence": evidence or "  (no sources)"}


def item_b(rec):
    mapping = dict(rec["source_map"])
    evidence = "\n".join(f"  SOURCE {i}: {c}\n    {t}" for i, c, t in rec["prompt_sources"])
    return {"answer": rec["delivered_answer"], "kind": kind(rec["delivered_answer"], rec.get("fallback_type")),
            "markers": markers(rec["delivered_answer"], {int(k): v for k, v in mapping.items()}), "evidence": evidence}


def main() -> int:
    b = {r["qid"]: r for r in (json.loads(l) for l in B_ANSWERS.read_text(encoding="utf-8").splitlines() if l.strip())}
    rng = random.Random(SEED)
    blocks, mapping = [], {}
    for qid in IDS:
        q, c = SEL[qid], CRIT[qid]
        head = [f"QUESTION {qid}: {q['Question (ask verbatim)']}",
                f"VERIFIED KEY - expected citation: {q['Expected Citation — VERIFIED KEY']}",
                f"VERIFIED KEY - key answer elements: {q['Key Answer Elements']}",
                "CHECKLIST (pre-registered): required elements:"]
        head += [f"  {rid} ({'core' if core else 'supporting'}): {text}" for rid, text, core in c["required"]]
        head.append("  critical errors: " + "; ".join(c["critical"]))
        if c["not_in_evidence"]:
            head.append("  NOT in the stored regulatory text (do not expect from any answer): " + "; ".join(c["not_in_evidence"]))
        pair = [("A", item_a(qid)), ("B", item_b(b[qid]))]
        rng.shuffle(pair)
        body = []
        for label, (cond, it) in zip(("X", "Y"), pair):
            iid = f"{qid}#{label}"
            mapping[iid] = cond
            body += [f"--- ITEM {iid}", f"DELIVERY: {it['kind']}", "ANSWER THE USER SAW:", it["answer"] or "(none)",
                     f"MARKERS: {it['markers']}", "EVIDENCE THIS ANSWER'S MODEL WAS GIVEN:", it["evidence"]]
        blocks.append("\n".join(head + body))
    out = E / "scoring"
    (out / "packets").mkdir(parents=True, exist_ok=True)
    (out / "blind_map.json").write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    batches = [blocks[i:i + PER] for i in range(0, len(blocks), PER)]
    for n, batch in enumerate(batches, 1):
        (out / "packets" / f"batch_{n:02d}.txt").write_text(("\n\n" + "=" * 100 + "\n").join(batch) + "\n", encoding="utf-8")
    print(f"{len(blocks)} questions, {len(mapping)} items, {len(batches)} batches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
