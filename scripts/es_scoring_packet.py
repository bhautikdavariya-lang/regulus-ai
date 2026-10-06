"""Build the scoring packet for an experiment arm.

`regulus_substantive_rubric_v1` requires the scorer to read the *actual text of the governing
provision* from the read-only snapshot, not the draft answer key. This assembles, for each row that
needs a fresh verdict, everything that judgement needs in one place:

    the question, the draft key citation and key answer elements, the verbatim regulation text of
    every governing section, the evidence the arm actually supplied, the delivered answer, the raw
    model output, and the pipeline state (validation, repair, fallback).

Read-only; writes a markdown packet under `artifacts/stage_b/`.

    .venv/bin/python scripts/es_scoring_packet.py --arm es1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.retrieval.db import Database  # noqa: E402

STAGE_B = ROOT / "artifacts/stage_b"


def provision_text(db: Database, section: str, max_paras: int = 24) -> list[tuple[str, str]]:
    rows = db.query(
        "SELECT paragraph_path, body_text, is_reserved FROM cfr_records"
        " WHERE section_number = %(s)s AND removed_on IS NULL ORDER BY ordinal LIMIT %(n)s",
        {"s": section, "n": max_paras})
    return [((r["paragraph_path"] or "—") + (" [RESERVED]" if r["is_reserved"] else ""),
             (r["body_text"] or "").strip()) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--only-changed", action="store_true", default=True)
    args = ap.parse_args()

    run = {json.loads(l)["question_id"]: json.loads(l)
           for l in (STAGE_B / f"run_{args.arm}.jsonl").read_text().splitlines() if l.strip()}
    comparison = json.loads((STAGE_B / "comparison.json").read_text())
    queue = comparison["scoring_queue"][args.arm]["needs_fresh_verdict"]
    bench = {json.loads(l)["id"]: json.loads(l)
             for l in (ROOT / "artifacts/stage_a/dataset.jsonl").read_text().splitlines() if l.strip()}

    db = Database.from_env()
    db.connect()

    out = [f"# Scoring packet — arm `{args.arm}` — {len(queue)} rows needing a fresh verdict\n",
           "Score under `regulus_substantive_rubric_v1`. The draft key is a starting point; the",
           "authority is the provision text reproduced below from the read-only snapshot.\n"]
    for qid in queue:
        r, b = run[qid], bench[qid]
        out.append("\n" + "=" * 100)
        out.append(f"## {qid}  ({b['type']} — {b['domain']})")
        out.append(f"\n**Question:** {b['question']}")
        out.append(f"\n**Draft key:** {b['key_citation_draft']}")
        out.append(f"\n**Key answer elements:** {b['key_elements']}")
        out.append(f"\n**ISO clause key (col H):** {b['iso_clause_draft']}")
        out.append("\n### Governing provision text (snapshot)")
        for sec in r.get("key_sections") or []:
            out.append(f"\n**{sec}**")
            paras = provision_text(db, sec)
            if not paras:
                out.append("  _(no live rows in the snapshot)_")
            for path, text in paras:
                out.append(f"  - `{path}` {text[:600]}")
        out.append("\n### Evidence this arm supplied")
        out.append(f"blocks={r.get('n_evidence_blocks')} evidence_tokens={r.get('evidence_tokens')} "
                   f"governing_supplied={r.get('governing_text_supplied')}")
        for i, lbl in enumerate(r.get("selected_labels") or [], 1):
            out.append(f"  {i:2}. {lbl}")
        out.append("\n### Stage A control answer (frozen verdict: "
                   f"{b['result']}, L{b['L']} M{b['M']} N{b['N']} O{b['O']} P{b['P']} Q{b['Q']})")
        out.append("```\n" + (b["answer"] or "")[:1200] + "\n```")
        out.append(f"\n### {args.arm} answer")
        out.append("```\n" + (r.get("answer") or "")[:2500] + "\n```")
        out.append(f"\n### {args.arm} raw model output")
        out.append("```\n" + (r.get("raw_model_output") or "")[:2000] + "\n```")
        out.append(f"\n**Pipeline:** validation {r.get('validation_initial')} -> {r.get('validation_final')}; "
                   f"repair={r.get('repair')}; fallback={r.get('fallback_type')}; "
                   f"stop={r.get('stop_reason')}; gen_tokens={r.get('generated_tokens')}; "
                   f"codes={r.get('validation_initial_codes')}")

    path = STAGE_B / f"scoring_packet_{args.arm}.md"
    path.write_text("\n".join(out) + "\n")
    print(f"wrote {path}  rows={len(queue)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
