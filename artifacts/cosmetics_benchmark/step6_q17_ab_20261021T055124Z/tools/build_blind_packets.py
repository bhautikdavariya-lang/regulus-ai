"""Blind scoring packets for the Step 6 A/B (read-only on the run; writes only under <root>/scoring/).

    python build_blind_packets.py <root> [questions_per_batch]

For each question, the delivered answers of arm A and arm B are compared after whitespace normalisation.
Identical -> one unlabelled item (scored once, the score applies to both arms). Different -> two items in a
seeded random order, labelled X and Y, never named by arm. The arm of each item is written only to
scoring/blind_map.json, which scorers are not given. Everything a scorer sees is the same kind of
information for every item: question, verified key, answer, its [n] markers resolved, how it was delivered
(generated / withheld / fallback), and whether the key's sections were in the evidence it was given.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "cosmetics100_20261020T124217Z" / "tools"))
from common import evidence_check, load_run, resolve_markers  # noqa: E402

SEED = 20261021


def norm(t: str | None) -> str:
    return " ".join((t or "").split())


def delivered(r: dict | None) -> str:
    if r is None or r.get("execution_status") != "SUCCESS":
        return f"NO ANSWER RETURNED ({(r or {}).get('execution_status')}: {(r or {}).get('error')})"
    ft = r.get("fallback_type")
    if ft == "unvalidated_answer_withheld":
        return "WITHHELD by the validator: the user saw only the withholding notice below"
    if ft:
        return f"FALLBACK '{ft}': the user saw the fallback text below, not a generated answer"
    return "GENERATED answer, delivered as shown"


def item_text(label: str, r: dict | None, resp: dict | None, q: dict) -> str:
    ev = evidence_check(q, resp)
    lines = [f"--- {label}",
             f"DELIVERY: {delivered(r)}",
             "ANSWER:", (r or {}).get("answer") or "(none)",
             "MARKERS (what each [n] in the answer points to): " + ("; ".join(resolve_markers((r or {}).get("answer") or "", resp)) or "none"),
             f"KEY SECTIONS IN THE EVIDENCE GIVEN TO THE MODEL: {ev['in_evidence'] or 'none'} of expected {ev['expected']}"
             f"{' (key cites the FD&C Act / U.S.C., which is not in the corpus)' if ev['statute_key'] else ''}"]
    return "\n".join(lines)


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    a, b = load_run(root / "arm_A_switch_off"), load_run(root / "arm_B_switch_on")
    assert [x["q"]["ID"] for x in a] == [x["q"]["ID"] for x in b]
    rng = random.Random(SEED)
    blocks, mapping = [], {}
    for xa, xb in zip(a, b):
        q = xa["q"]
        head = [f"#{q['Run Order']} {q['ID']} | {q['Question Type']} | {q['Difficulty']} | section {q['Section']}",
                "QUESTION: " + q["Question (ask verbatim)"],
                "EXPECTED CITATION (verified key): " + str(q["Expected Citation — VERIFIED KEY"]),
                "KEY ANSWER ELEMENTS: " + str(q["Key Answer Elements"])]
        if q.get("Audit Correction Note"):
            head.append("AUDIT NOTE: " + str(q["Audit Correction Note"]))
        ra, rb = xa["r"], xb["r"]
        same = norm((ra or {}).get("answer")) == norm((rb or {}).get("answer")) and \
            (ra or {}).get("execution_status") == (rb or {}).get("execution_status")
        if same:
            iid = f"{q['ID']}#1"
            mapping[iid] = ["A", "B"]
            body = [item_text(f"ITEM {iid}", ra, xa["resp"], q)]
        else:
            pair = [("A", ra, xa["resp"]), ("B", rb, xb["resp"])]
            rng.shuffle(pair)
            body = []
            for label, (arm, r, resp) in zip(("X", "Y"), pair):
                iid = f"{q['ID']}#{label}"
                mapping[iid] = [arm]
                body.append(item_text(f"ITEM {iid}", r, resp, q))
        blocks.append((q["ID"], "\n".join(head + body)))
    out = root / "scoring"
    (out / "packets").mkdir(parents=True, exist_ok=True)
    (out / "blind_map.json").write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    batches = [blocks[i:i + per] for i in range(0, len(blocks), per)]
    for n, batch in enumerate(batches, 1):
        text = "\n\n" + ("=" * 100 + "\n").join(block + "\n" for _, block in batch)
        (out / "packets" / f"batch_{n:02d}.txt").write_text(text, encoding="utf-8")
    items = len(mapping)
    differing = sum(1 for v in mapping.values() if len(v) == 1) // 2
    print(f"{len(blocks)} questions, {items} items to score ({len(blocks) - differing} identical across arms, "
          f"{differing} differing), {len(batches)} batches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
