"""Compact side-by-side scoring sheets for the questions whose evidence C1+C2+C3 changed.

    .venv/bin/python scripts/c123_build_scoring_set.py <c123_run_dir> <out_dir>

For each changed question: the question, the SME draft key and its verified regulation text, the
baseline answer and its frozen rubric verdict, the new answer, and the evidence each run selected.
Scoring is done by reading these against the rubric; this only assembles them.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/acceptance_test/acceptance_rev02_20261001T083958Z"


def main() -> int:
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    nw = {json.loads(l)["question_id"]: json.loads(l) for l in open(run / "answers.jsonl", encoding="utf-8") if l.strip()}
    bl = {json.loads(l)["question_id"]: json.loads(l) for l in open(BASE / "answers.jsonl", encoding="utf-8") if l.strip()}
    prov = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    bv = {}
    for f in sorted(glob.glob(str(BASE / "scoring" / "verdicts_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                bv[r["id"]] = r
    # the LAW block and question metadata already rendered by build_scoring_evidence
    law = {}
    for f in sorted(glob.glob(str(run / "scoring" / "chunk*.txt"))):
        for block in open(f, encoding="utf-8").read().split("\n### "):
            if not block.strip():
                continue
            qid = block.split(" |", 1)[0].lstrip("# ").strip()
            law[qid] = block

    changed = [k for k in nw if bl[k].get("evidence") != nw[k].get("evidence")]
    per_file = 15
    files = 0
    for i in range(0, len(changed), per_file):
        files += 1
        lines = []
        for qid in changed[i:i + per_file]:
            b, n, p, v = bl[qid], nw[qid], prov[qid], bv[qid]
            blk = law.get(qid, "")
            head = next((l for l in blk.splitlines() if l.startswith(("#", qid))), qid)
            get = lambda tag: next((l.strip() for l in blk.splitlines() if l.strip().startswith(tag)), "")
            lines += [
                "=" * 100,
                f"### {head}",
                f"  Q: {n['question']}",
                "  " + get("DRAFT_KEY_CITATION:"),
                "  " + get("KEY_ELEMENTS:"),
                "  " + get("LAW ")[:1600],
                f"  BASE_VERDICT: {v['result']} L={v['L']} M={v['M']} N={v['N']} O={v['O']} P={v['P']} Q={v['Q']}",
                f"  BASE_NOTES: {v['notes']}",
                f"  BASE_EVAL : {v['eval']}",
                f"  BASE_EVIDENCE ({len(b.get('evidence') or [])}): {', '.join((b.get('evidence') or [])[:14])}",
                f"  NEW_EVIDENCE  ({len(n.get('evidence') or [])}): {', '.join((n.get('evidence') or [])[:14])}",
                f"  NEW_PROV: coverage={p['coverage']} sources={p['selected_sources']} chars={p['selected_chars']} "
                f"required_dropped={p['required_dropped']} c2_expanded={p['part_expanded']}",
                f"  NEW_PIPE: validation={n.get('validation_final')} repair={n.get('repair')} "
                f"answerability={n.get('answerability')} tokens={n.get('generated_tokens')}",
                f"  BASE_ANSWER: {(b.get('answer') or '')[:220]}",
                f"  NEW_ANSWER : {(n.get('answer') or '')[:1800]}",
                f"  NEW_RAW    : {(n.get('raw_model_output') or '')[:900]}",
                f"  NEW_CITES  : {', '.join(c['label'] for c in (n.get('citations') or []))}",
                "",
            ]
        (out / f"cmp{files:02}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(changed)} changed questions -> {files} files in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
