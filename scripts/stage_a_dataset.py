"""Stage A: build the frozen analysis dataset (deliverable A2, the benchmark-to-rubric mapping).

Joins, for every one of the 300 acceptance questions, four existing records into one row:

  1. the benchmark question bank (read-only: ID, type, domain, draft key, key answer elements)
  2. the live run `answers.jsonl` (raw model output, final answer, every pipeline-stage field)
  3. the frozen hand-scored rubric verdicts `scoring/verdicts_*.jsonl` (result, columns L-Q, notes)
  4. the hand-built forensic row labels `scoring/forensic_rows.json` (reviewer attribution fields)

Nothing is recomputed and nothing is scored here: this is a join plus an integrity check, so that
every later Stage A diagnostic reads one frozen file instead of re-deriving the join. Reviewer
judgement fields are prefixed `rev_` to keep them visibly separate from machine facts.

Read-only. Imports nothing from `regulus`, touches no database, loads no model, and writes only
under `artifacts/stage_a/`. The benchmark workbook is opened read-only and hashed, never written.

    python3 scripts/stage_a_dataset.py [--run <run dir>] [--out artifacts/stage_a]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx"
DEFAULT_RUN = ROOT / "artifacts/acceptance_test/acceptance_rev02_20261001T083958Z"

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

# Question Bank column -> field name. Columns K-R are the tester's own scoring columns and are
# blank in the benchmark (the SME never locked the key); the verdicts file carries the real scores.
BANK_COLUMNS = {
    "A": "id", "B": "domain", "C": "focus", "D": "type", "E": "difficulty",
    "F": "question", "G": "key_citation_draft", "H": "iso_clause_draft",
    "I": "iso_clause_title", "J": "key_elements", "K": "key_verified",
}

ANSWER_FIELDS = (
    "execution_status", "seconds", "question", "answer", "raw_model_output", "model_called",
    "no_context", "citations", "evidence", "answerability", "scope", "fallback_type",
    "validation_initial", "validation_initial_codes", "validation_final", "repair",
    "stop_reason", "generated_tokens", "error",
)

VERDICT_FIELDS = ("result", "L", "M", "N", "O", "P", "Q", "notes", "eval")

# Reviewer-assigned (not machine-derived) fields from forensic_rows.json. Kept under a `rev_`
# prefix: Stage A re-derives its own attribution and reports where the two disagree.
FORENSIC_FIELDS = (
    "key_sections", "key_section_state", "key_retrieved", "evidence_kind", "evidence_count",
    "citations_used", "invalid_markers", "cited_sections_absent", "cited_sections_reserved",
    "guidance_in_answer", "withheld", "declined_before_model", "dangling_colon", "question_echo",
    "truncated", "artefact", "substantively_correct", "mechanical_root_cause", "model_related",
    "fixable_without_model_change", "corpus_sufficient", "key_possibly_wrong",
    "key_better_candidate", "reviewer_note", "reviewer_verification", "borderline", "trap_row",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_sheet(path: Path, sheet: str) -> list[dict[str, str | None]]:
    """Read one worksheet as a list of {column letter: value}. No openpyxl: an .xlsx is a zip of
    XML, and this reader is deliberately dependency-free so the diagnostic runs anywhere."""
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        book = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        target = None
        for sh in book.find("m:sheets", NS):
            if sh.get("name") == sheet:
                target = rels[sh.get("{%s}id" % NS["r"])].lstrip("/")
                break
        if target is None:
            raise SystemExit(f"sheet {sheet!r} not found in {path.name}")
        if not target.startswith("xl/"):
            target = "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(target)).iter("{%s}row" % NS["m"]):
            cells: dict[str, str | None] = {}
            for c in row.findall("m:c", NS):
                col = re.match(r"([A-Z]+)", c.get("r")).group(1)
                v = c.find("m:v", NS)
                if c.get("t") == "s" and v is not None:
                    cells[col] = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    node = c.find("m:is", NS)
                    cells[col] = "".join(x.text or "" for x in node.iter("{%s}t" % NS["m"])) if node is not None else None
                else:
                    cells[col] = v.text if v is not None else None
            rows.append(cells)
        return rows


def load_bank() -> dict[str, dict]:
    rows = read_sheet(BENCHMARK, "Question Bank")
    bank: dict[str, dict] = {}
    for cells in rows[1:]:
        qid = (cells.get("A") or "").strip()
        if not qid:
            continue
        bank[qid] = {name: (cells.get(col) or "").strip() or None for col, name in BANK_COLUMNS.items()}
    return bank


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/stage_a")
    args = ap.parse_args()

    run, out = args.run, args.out
    out.mkdir(parents=True, exist_ok=True)

    bank = load_bank()
    answers = {}
    for line in (run / "answers.jsonl").read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            answers[rec["question_id"]] = rec

    verdicts: dict[str, dict] = {}
    verdict_files = sorted((run / "scoring").glob("verdicts_*.jsonl"))
    for vf in verdict_files:
        for line in vf.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec["id"] in verdicts:
                    raise SystemExit(f"duplicate verdict for {rec['id']} in {vf.name}")
                verdicts[rec["id"]] = rec

    forensic = {r["id"]: r for r in json.loads((run / "scoring/forensic_rows.json").read_text())}

    problems: list[str] = []
    for label, keys in (("answers", answers), ("verdicts", verdicts), ("forensic", forensic)):
        missing = sorted(set(bank) - set(keys))
        extra = sorted(set(keys) - set(bank))
        if missing:
            problems.append(f"{label}: {len(missing)} benchmark ids absent ({missing[:5]})")
        if extra:
            problems.append(f"{label}: {len(extra)} ids not in the benchmark ({extra[:5]})")

    rows = []
    for qid, q in bank.items():
        a, v, f = answers.get(qid, {}), verdicts.get(qid, {}), forensic.get(qid, {})
        # the two hand-scored records must agree; they were written in separate passes
        for field in ("result", "L", "M", "N", "O", "P", "Q"):
            if field in v and field in f and v[field] != f[field]:
                problems.append(f"{qid}: {field} verdicts={v[field]!r} forensic={f[field]!r}")
        if a.get("question") and q["question"] and a["question"].strip() != q["question"].strip():
            problems.append(f"{qid}: question text in the run differs from the benchmark")
        row = {"id": qid}
        row.update({k: val for k, val in q.items() if k != "id"})
        row.update({k: a.get(k) for k in ANSWER_FIELDS if k != "question"})
        row.update({k: v.get(k) for k in VERDICT_FIELDS})
        row.update({f"rev_{k}": f.get(k) for k in FORENSIC_FIELDS})
        rows.append(row)

    (out / "dataset.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    manifest = {
        "stage": "A",
        "purpose": "frozen join of benchmark questions, live run output and hand-scored rubric verdicts",
        "rows": len(rows),
        "run": str(run.relative_to(ROOT)),
        "inputs": {
            "benchmark": {"path": BENCHMARK.name, "sha256": sha256(BENCHMARK), "written": False},
            "answers": {"path": str((run / "answers.jsonl").relative_to(ROOT)), "sha256": sha256(run / "answers.jsonl")},
            "verdicts": [{"path": vf.name, "sha256": sha256(vf)} for vf in verdict_files],
            "forensic": {"path": "scoring/forensic_rows.json", "sha256": sha256(run / "scoring/forensic_rows.json")},
        },
        "integrity": {"checks_failed": len(problems), "problems": problems},
    }
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"wrote {out / 'dataset.jsonl'}  rows={len(rows)}")
    print(f"integrity problems: {len(problems)}")
    for p in problems[:20]:
        print("   ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
