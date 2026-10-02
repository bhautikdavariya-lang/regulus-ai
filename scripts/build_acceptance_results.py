"""Build the acceptance-test results workbook from a run of scripts/run_acceptance_test.py.

    PYTHONPATH=<dir with openpyxl> python scripts/build_acceptance_results.py --run artifacts/acceptance_test/<run dir>

Writes a NEW workbook (never the benchmark):
    Regulus_AI_Acceptance_Benchmark_REV02_300Q_TEST_RESULTS.xlsx  (project root, or --out)

Scoring policy (from the benchmark itself, not invented here):
* The authoritative method is the workbook's rubric, columns L-Q, scored by an SME or independent
  reviewer against a key verified in column K. Its instructions say "An unverified key invalidates
  the entire result" and "Do not let the vendor score the test".
* The key has 0/300 rows verified, so no row is given PASS or FAIL. Every executed row is
  REQUIRES SME REVIEW; a row that did not execute is ERROR; a row with no recorded answer is NOT TESTED.
* Machine-checkable INDICATORS are added to speed up the SME review. They are provisional,
  compare against the DRAFT key or the local CFR database, and are not rubric scores.

The benchmark is read through the project's read-only loader; the database through the read-only
connection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import Workbook, load_workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark  # noqa: E402
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.references import parse_cfr_references  # noqa: E402

OUT_NAME = "Regulus_AI_Acceptance_Benchmark_REV02_300Q_TEST_RESULTS.xlsx"
SME = "REQUIRES SME REVIEW"
CELL_MAX = 32000
DECLINE_RE = re.compile(r"\b(not (?:found|present|available|contained)|does not exist|no (?:such|matching)|"
                        r"could not (?:find|be validated|answer)|cannot (?:answer|find)|unable to|not shown|"
                        r"\[?reserved\]?|outside (?:the )?(?:scope|title 21)|not (?:in|within) (?:the )?(?:scope|retrieved))", re.I)
ISO_RE = re.compile(r"(?:clause|ISO 13485[^.\n]{0,40}?)\s*(\d{1,2}(?:\.\d{1,2}){1,3})", re.I)
FONT = "Arial"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clip(text) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= CELL_MAX else text[:CELL_MAX] + f" …[truncated for Excel; full text in answers.jsonl, {len(text)} chars]"


class CfrIndex:
    """Which Title 21 sections/paragraphs exist in the local (read-only) eCFR snapshot."""

    def __init__(self, db: Database):
        self.sections = {r["number"]: bool(r["is_reserved"]) for r in db.query("SELECT number, is_reserved FROM cfr_sections")}
        self.parts = {r["number"] for r in db.query("SELECT number FROM cfr_parts")}
        self.paragraphs = {(r["section_number"], r["paragraph_path"] or "") for r in
                           db.query("SELECT DISTINCT section_number, paragraph_path FROM cfr_records")}
        # a snapshot stores a reserved span as one row, e.g. "820.20-820.30": a section inside it was
        # superseded, which is a different finding from a section that never existed
        self.reserved_spans = []
        for number in self.sections:
            if "-" in number:
                try:
                    lo, hi = (float(part.split(".", 1)[1]) for part in number.split("-", 1))
                except (ValueError, IndexError):
                    continue
                self.reserved_spans.append((number.split(".", 1)[0], lo, hi))

    def _in_reserved_span(self, ref) -> bool:
        try:
            value = float(ref.section.split(".", 1)[1])
        except (ValueError, IndexError):
            return False
        return any(part == ref.part and lo <= value <= hi for part, lo, hi in self.reserved_spans)

    def exists(self, ref) -> str:
        if ref.section is None:
            return "ok" if ref.part in self.parts else "part_not_in_db"
        if ref.section not in self.sections:
            if ref.part not in self.parts:
                return "part_not_in_db"
            return "section_reserved_span" if self._in_reserved_span(ref) else "section_not_in_db"
        if ref.paragraph_path and (ref.section, ref.paragraph_path) not in self.paragraphs:
            # a deeper/shallower path the DB stores differently is not proof of fabrication
            if not any(s == ref.section and (p.startswith(ref.paragraph_path) or ref.paragraph_path.startswith(p) and p)
                       for s, p in self.paragraphs if s == ref.section):
                return "paragraph_not_in_db"
        return "ok"


def refs_in(text: str):
    return [r for r in parse_cfr_references(text or "") if r.title == "21"]


def indicators(q, row: dict, cfr: CfrIndex) -> dict:
    """Machine-checkable, provisional signals for the SME. Not rubric scores."""
    answer = row.get("answer") or ""
    # cited = sources the answer references by [n] marker, plus provisions named in its text
    # (row["citations"] is the numbered source list shown to the model, not what the answer cites)
    by_index = {c["index"]: c["label"] for c in row.get("citations") or []}
    markers = {int(m) for m in re.findall(r"\[(\d{1,3})\]", answer)}
    named = refs_in(answer) + refs_in(" ".join(by_index[i] for i in sorted(markers) if i in by_index))
    seen, provided = set(), []
    for r in named:
        key = (r.part, r.section, r.paragraph_path)
        if key not in seen:
            seen.add(key)
            provided.append(r)
    draft = refs_in(q.expected_citation_draft)
    withheld = bool(row.get("repair") and "withheld" in str(row.get("repair"))) or "could not be validated" in answer
    if withheld:
        provided = []   # a withheld notice lists "Sources consulted"; those are not citations of an answer
    declined = (not row.get("model_called")) or withheld or bool(DECLINE_RE.search(answer[:600]))
    flags, notes = [], []

    # citation provided vs the DRAFT key (section-level)
    if draft:
        draft_sections = {r.section or f"Part {r.part}" for r in draft}
        prov_sections = {r.section or f"Part {r.part}" for r in provided}
        prov_parts = {r.part for r in provided}
        if draft_sections & prov_sections:
            match = "draft section cited"
        elif {r.part for r in draft} & prov_parts:
            match = "same part, different section"
        elif provided:
            match = "different part"
        else:
            match = "no CFR citation"
        if match != "draft section cited" and not q.is_negative_control:
            flags.append(f"citation vs draft key: {match}")
    else:
        match = "draft key has no parseable CFR citation"

    # citations absent from the local eCFR snapshot. Two different findings, kept apart:
    # a section inside a reserved span was superseded (a temporal error); one with no trace may be invented.
    checked = [(r.raw, cfr.exists(r)) for r in provided]
    superseded = [raw for raw, why in checked if why == "section_reserved_span"]
    missing = [(raw, why) for raw, why in checked if why not in ("ok", "section_reserved_span")]
    if superseded:
        flags.append("cites provision reserved/removed in the current snapshot (superseded text): " + "; ".join(superseded))
    if missing:
        flags.append("cited provision has no entry in the current snapshot (removed/superseded or non-existent): "
                     + "; ".join(f"{raw} ({why})" for raw, why in missing))
    reserved = [r.section for r in provided if r.section and cfr.sections.get(r.section)] + superseded

    if q.is_negative_control:
        if declined:
            notes.append("negative control: response declined / stated not found (check wording)")
        else:
            flags.append("negative control: substantive answer given (trap may not have been refused)")
    elif row.get("execution_status") == "OK" and withheld:
        flags.append("answer withheld by validation (likely incomplete / no substantive answer)")
    elif not row.get("model_called") and not q.is_scope_boundary and not q.is_abstention:
        flags.append("declined without generation on an in-scope question")

    if q.is_temporal and reserved and not re.search(r"reserved", answer, re.I):
        flags.append("temporal: cites reserved section(s) " + ", ".join(sorted(set(reserved))) + " without saying reserved")

    iso_named = sorted(set(ISO_RE.findall(answer)))
    if q.in_g7_scope:
        if q.iso_state == "none_expected" or (q.iso_clause_draft or "").strip().lower() == "none":
            if iso_named:
                flags.append("ISO clause named where draft key says None: " + ", ".join(iso_named))
        elif not any(c in iso_named or any(n.startswith(c) for n in iso_named) for c in q.iso_clauses):
            flags.append("draft ISO clause(s) " + ", ".join(q.iso_clauses) + " not named")

    if row.get("validation_initial_codes"):
        notes.append("pipeline validator codes on raw output: " + ", ".join(row["validation_initial_codes"]))
    return {"provided": ", ".join(r.raw for r in provided) or ("none (answer withheld)" if withheld else "none"), "draft_match": match, "flags": flags, "notes": notes,
            "declined": declined, "iso_named": ", ".join(iso_named)}


def investigation_area(flags: list[str]) -> str:
    areas = []
    for f in flags:
        if f.startswith("negative control"):
            areas.append("answerability / non-existent-provision detection")
        elif f.startswith("cited provision has no entry"):
            areas.append("citation check: superseded or non-existent provision (verify against eCFR)")
        elif f.startswith("cites provision reserved/removed"):
            areas.append("temporal: answered from superseded regulation text")
        elif f.startswith("citation vs draft"):
            areas.append("retrieval (governing section not cited)")
        elif f.startswith("answer withheld") or f.startswith("declined without"):
            areas.append("generation/validation (no substantive answer)")
        elif f.startswith("temporal"):
            areas.append("temporal handling of reserved sections")
        elif "ISO" in f:
            areas.append("ISO 13485 clause mapping")
    return "; ".join(dict.fromkeys(areas))


def style_header(ws, row: int, ncols: int):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def table(ws, headers: list[str], rows: list[list], widths: list[int], start: int = 1):
    for i, h in enumerate(headers, start=1):
        ws.cell(row=start, column=i, value=h)
    style_header(ws, start, len(headers))
    for r, vals in enumerate(rows, start=start + 1):
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = Font(name=FONT)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=start + 1, column=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default=str(ROOT / OUT_NAME))
    ap.add_argument("--verdicts", default=None, help="directory of verdicts_*.jsonl: per-question PASS/FAIL scored against the rubric")
    args = ap.parse_args()
    run = Path(args.run).resolve()
    out_path = Path(args.out).resolve()
    workbook = (ROOT / DEFAULT_WORKBOOK).resolve()
    if out_path == workbook:
        raise SystemExit("refusing to overwrite the benchmark workbook")
    bench_sha = sha256(workbook)
    bench = load_acceptance_benchmark(workbook)
    meta = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
    answers: dict[str, dict] = {}
    duplicates = []
    for line in (run / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["question_id"] in answers:
                duplicates.append(r["question_id"])
            answers.setdefault(r["question_id"], r)
    verdicts: dict[str, dict] = {}
    if args.verdicts:
        for f in sorted(Path(args.verdicts).glob("verdicts_*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    v = json.loads(line)
                    if v["id"] in verdicts:
                        raise SystemExit(f"duplicate verdict for {v['id']}")
                    verdicts[v["id"]] = v
        missing = [q.question_id for q in bench if q.question_id not in verdicts]
        if missing:
            raise SystemExit(f"verdicts missing for {len(missing)} questions: {missing[:10]}")

    db = Database.from_env()
    db.connect()
    cfr = CfrIndex(db)
    db.close()

    detail, flagged, errors, results, partial = [], [], [], [], []
    for q in bench:
        row = answers.get(q.question_id)
        if row is None:
            result, status, ind = "NOT TESTED", "NOT RUN", None
        elif row["execution_status"] != "OK":
            result, status, ind = "ERROR", row["execution_status"], None
        else:
            result, status, ind = SME, "OK", indicators(q, row, cfr)
        v = verdicts.get(q.question_id)
        if v:
            result = v["result"]
            if result == "ERROR":
                status = (row or {}).get("execution_status") or status
        results.append(result)
        expected = f"[DRAFT KEY - NOT SME-VERIFIED] {q.key_answer_elements}"
        cit_expected = q.expected_citation_draft + (f" | ISO 13485 (draft): {q.iso_clause_draft} {q.iso_clause_title}".rstrip()
                                                    if q.iso_clause_draft not in ("—", "") else "")
        machine = ""
        if ind:
            machine = " | ".join(["indicator: " + f for f in ind["flags"]] + ind["notes"]) or "no machine indicators"
        if v:
            scoring = v["notes"]
            evaluator = (v.get("eval") or "") + (" || MACHINE CHECKS: " + machine if machine else "")
            borderline = "Y" if ("Borderline" in v["notes"] or "may wish to revisit" in (v.get("eval") or "")) else "N"
            rubric = [v.get(k) for k in ("L", "M", "N", "O", "P", "Q")]
        else:
            scoring = ("Not scored: benchmark key 0/300 SME-verified; the workbook states an unverified key invalidates the "
                       "result and that scoring is done by an SME/independent reviewer (rubric L-Q).") if result == SME else ""
            evaluator = machine
            borderline = "Y" if ind and ind["flags"] else ("N" if ind else "")
            rubric = [None] * 6
        detail.append([
            q.question_id, q.domain, q.question_type, q.difficulty, q.question, expected, clip(row and row.get("answer")),
            cit_expected, ind["provided"] if ind else "", ind["draft_match"] if ind else "",
            row.get("seconds") if row else None, status, result, (row or {}).get("error") or "", scoring, evaluator,
            borderline, *rubric,
            (row or {}).get("answerability") or "", (row or {}).get("validation_final") or "", str((row or {}).get("repair") or ""),
            "; ".join(row.get("evidence") or []) if row else "", ind["iso_named"] if ind else "",
            clip(row and row.get("raw_model_output")), q.key_verified, q.row,
        ])
        if v and result == "FAIL":
            crit = []
            if v.get("L") == 0:
                crit.append("G1 citation accuracy (rubric L=0)")
            if v.get("M") == 1:
                crit.append("G2 fabricated citation (rubric M=1) - ABSOLUTE GATE")
            if q.is_negative_control:
                crit.append("G3 negative control - ABSOLUTE GATE")
            if (v.get("N") or 0) < 2:
                crit.append(f"G4 substantive correctness (rubric N={v.get('N')})")
            if (v.get("O") or 0) < 2:
                crit.append(f"G5 completeness (rubric O={v.get('O')})")
            if v.get("P") == 0:
                crit.append("G6 scope discipline (rubric P=0)")
            if v.get("Q") == 0:
                crit.append("G7 ISO clause concordance (rubric Q=0)")
            cit_issue = "; ".join(x for x in [
                "citation not correct to the section/paragraph" if v.get("L") == 0 else "",
                "fabricated citation" if v.get("M") == 1 else "",
                ind["draft_match"] if ind and ind["draft_match"] != "draft section cited" else "",
            ] if x)
            flagged.append([q.question_id, q.domain, q.question, expected, clip(row.get("answer")),
                            v["notes"], "; ".join(crit), cit_issue,
                            investigation_area(ind["flags"]) if ind and ind["flags"] else "review the scoring note"])
        elif v is None and ind and ind["flags"]:
            flagged.append([q.question_id, q.domain, q.question, expected, clip(row.get("answer")),
                            "Provisional machine indicator(s), not an SME verdict: " + " | ".join(ind["flags"]),
                            "Rubric L, M, N, O" + (", Q" if q.in_g7_scope else ""), "", investigation_area(ind["flags"])])
        if v and result == "FAIL" and ((v.get("N") or 0) >= 1 or (v.get("O") or 0) >= 1):
            blockers = [name for flag, name in (
                (v.get("L") == 0, "citation not correct to the section/paragraph (G1)"),
                (v.get("M") == 1, "fabricated citation (G2, absolute)"),
                ((v.get("N") or 0) < 2, "substance incomplete or misleading (G4)"),
                ((v.get("O") or 0) < 2, "completeness short of all governing provisions (G5)"),
                (v.get("P") == 0, "scope discipline (G6)"),
                (v.get("Q") == 0, "ISO clause not named (G7)"),
            ) if flag]
            hard = [name for flag, name in (
                (v.get("L") == 0, "citation"), (v.get("M") == 1, "fabricated"), ((v.get("N") or 0) < 2, "substance"),
                ((v.get("O") or 0) < 1, "material omission"), (v.get("P") == 0, "scope"), (v.get("Q") == 0, "ISO"),
            ) if flag]
            band = ("A - substance fully correct, blocked on another dimension" if (v.get("N") or 0) == 2
                    else "B - partly correct: right direction, materially incomplete or partly misleading")
            scores = (f"citation {v.get('L')}/1, fabricated {v.get('M')}, substance {v.get('N')}/2, "
                      f"completeness {v.get('O')}/2, scope {v.get('P')}/1, "
                      f"ISO {'n/a' if v.get('Q') is None else str(v.get('Q')) + '/1'}")
            partial.append([len(hard), q.question_id, q.domain, q.question_type, q.question, band, scores,
                            "; ".join(hard), clip(row.get("answer")), f"[DRAFT KEY] {q.key_answer_elements}",
                            v["notes"], v.get("eval") or "", "Y" if len(hard) == 1 else "N",
                            "Y" if ("Borderline" in v["notes"] or "may wish to revisit" in (v.get("eval") or "")) else "N"])
        if result == "ERROR":
            errors.append([q.question_id, q.domain, q.question, row.get("error"), row.get("seconds"),
                           clip(row.get("traceback")), "execution failure (not a model-quality failure)"])

    wb = Workbook()
    # ---------------------------------------------------------------- Detailed Results
    wd = wb.active
    wd.title = "Detailed Results"
    dheaders = ["Question ID", "Category (Domain)", "Question Type", "Difficulty", "Question (verbatim, col F)",
                "Expected Answer / Reference (col J, DRAFT)", "Model Answer (as shown to user)", "Citation Expected (col G/H, DRAFT)",
                "Citation Provided", "Citation vs Draft Key (indicator)", "Response Time (s)", "Execution Status", "Result",
                "Error", "Scoring Notes", "Evaluator Notes (verification + machine checks)", "Borderline - SME second look",
                "L Citation Exact (1/0)", "M Fabricated Citation (1=fail)", "N Substantive (0-2)", "O Completeness (0-2)",
                "P Scope Discipline (1/0)", "Q ISO Clause (1/0/blank)",
                "Answerability State", "Final Validation", "Repair Applied", "Evidence Retrieved", "ISO Clauses Named",
                "Raw Model Output (before validation/repair)", "Key Verified (col K)", "Benchmark Row"]
    table(wd, dheaders, detail, [10, 26, 14, 12, 50, 50, 70, 30, 30, 22, 10, 11, 20, 20, 60, 60, 11, 9, 9, 9, 9, 9, 9, 18, 14, 22, 40, 14, 70, 10, 9])
    wd.auto_filter.ref = f"A1:{get_column_letter(len(dheaders))}{len(detail) + 1}"
    n = len(detail) + 1
    DR = "'Detailed Results'"
    rng = lambda col: f"{DR}!${col}$2:${col}${n}"   # noqa: E731

    # ---------------------------------------------------------------- Summary
    ws = wb.create_sheet("Summary", 0)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 70
    ws["A1"] = "Regulus AI Acceptance Benchmark REV02 (300Q): Test Results"
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    ws["A2"] = (("Every question carries an explicit result in Detailed Results, scored question by question against the workbook's own rubric "
                 "(columns L-Q) and against the regulation text in the read-only eCFR snapshot - not against the draft key alone. Where the "
                 "draft key is itself wrong, the answer was judged against the regulation and the discrepancy is recorded in Evaluator Notes. "
                 "The key remains unverified by an SME (0 of 300 rows marked Y in column K), so these results are an independent reviewer's "
                 "scoring, not a signed-off contractual acceptance result: an SME should countersign before the gates are treated as final.")
                if args.verdicts else
                ("IMPORTANT: the benchmark answer key is a DRAFT with 0 of 300 rows SME-verified, so no PASS/FAIL verdicts are given: every "
                 "executed answer is REQUIRES SME REVIEW."))
    ws["A2"].font = Font(name=FONT, bold=True, color="C00000")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A2:B2")
    ws.row_dimensions[2].height = 90
    repro = meta.get("reproducibility") or {}
    times = [r.get("seconds") for r in answers.values() if r.get("execution_status") == "OK" and r.get("seconds") is not None]
    lines = [
        ("Total questions", 300),
        ("Questions successfully tested", f'=COUNTIF({rng("L")},"OK")'),
        ("Questions failed to execute (ERROR)", f'=COUNTIF({rng("M")},"ERROR")'),
        ("Questions not tested", f'=COUNTIF({rng("M")},"NOT TESTED")'),
        ("Questions passed", f'=COUNTIF({rng("M")},"PASS")'),
        ("Questions failed", f'=COUNTIF({rng("M")},"FAIL")'),
        ("Questions requiring SME review", f'=COUNTIF({rng("M")},"{SME}")'),
        # B8 = passed, B9 = failed (rows 4.. in the order of this list)
        ("Pass rate % (PASS / (PASS+FAIL))", '=IF(B8+B9=0,"Not determinable (no rows scored)",B8/(B8+B9))'),
        ("Fail rate % (FAIL / (PASS+FAIL))", '=IF(B8+B9=0,"Not determinable (no rows scored)",B9/(B8+B9))'),
        ("Execution error rate % (ERROR / total)", "=B6/B4"),
        ("Execution success rate % (tested / total)", "=B5/B4"),
        ("SME review rate % (REQUIRES SME REVIEW / total)", "=B10/B4"),
        ("Average response time (s), executed rows", f'=AVERAGEIF({rng("L")},"OK",{rng("K")})'),
        ("Median response time (s), executed rows (computed in Python from column K; no conditional-median formula)",
         round(statistics.median(times), 2) if times else "n/a"),
        ("Rows flagged borderline for an SME second look", f'=COUNTIF({rng("Q")},"Y")'),
        ("Answers with partial credit (see Partially Correct sheet)",
         f'=COUNTIFS({rng("M")},"FAIL",{rng("T")},">=1")+COUNTIFS({rng("M")},"FAIL",{rng("T")},"0",{rng("U")},">=1")'),
        ("  of those, substance fully correct, blocked on another dimension", f'=COUNTIFS({rng("M")},"FAIL",{rng("T")},2)'),
        ("  of those, directionally right but materially incomplete", f'=COUNTIFS({rng("M")},"FAIL",{rng("T")},1)'),
        ("Answers with no partial credit (substance and completeness both 0)",
         f'=COUNTIFS({rng("M")},"FAIL",{rng("T")},0,{rng("U")},0)'),
        ("", ""),
        ("Test date/time (UTC)", f"{meta.get('started_utc')} to {meta.get('finished_utc', 'unfinished')}"),
        ("Model/checkpoint", f"{repro.get('model_id')} @ {repro.get('model_revision')} (base model, no adapter; "
                             f"weights sha256 {repro.get('weights_sha256')})"),
        ("Git commit/version", f"{repro.get('git_commit')}" + (" (working tree had uncommitted files: the test scripts)" if repro.get("git_dirty") else "")),
        ("Test environment", f"{(meta.get('hardware') or {}).get('platform')}; device {repro.get('device')}, dtype {repro.get('dtype')}; "
                             "Apple M2, 8 GB; read-only PostgreSQL eCFR snapshot"),
        ("Benchmark file / sha256 before → after", f"{(meta.get('benchmark') or {}).get('file')} / {(meta.get('benchmark') or {}).get('sha256_before')} → "
                                                   f"{(meta.get('benchmark') or {}).get('sha256_after', 'n/a')} (now {bench_sha})"),
    ]
    for i, (k, v) in enumerate(lines, start=4):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT, bold=bool(k))
        c = ws.cell(row=i, column=2, value=v)
        c.font = Font(name=FONT)
        c.alignment = Alignment(wrap_text=True, horizontal="left")
    for r in (11, 12, 13, 14, 15):
        ws.cell(row=r, column=2).number_format = "0.0%"
    ws["B16"].number_format = "0.0"
    ws["B17"].number_format = "0.0"
    for r in (19, 20, 21, 22):
        ws.cell(row=r, column=2).number_format = "0"
    ws.cell(row=3, column=1, value="Metric").font = Font(name=FONT, bold=True)
    ws.cell(row=3, column=2, value="Value").font = Font(name=FONT, bold=True)

    # ------------------------------------------------- acceptance gates, computed from the rubric columns
    gstart = 4 + len(lines) + 1
    if args.verdicts:
        ws.cell(row=gstart, column=1, value="ACCEPTANCE GATES (computed from rubric columns R-W of Detailed Results)").font = Font(name=FONT, bold=True)
        ws.cell(row=gstart, column=2, value="Scored by an independent reviewer against the regulation text; the answer key itself "
                                            "remains unverified, so an SME must countersign before these are treated as final.").font = Font(name=FONT, italic=True)
        ghdr = ["Gate / metric", "Result", "Threshold", "Status", "Scored on"]
        for i, h in enumerate(ghdr, start=1):
            ws.cell(row=gstart + 1, column=i, value=h)
        style_header(ws, gstart + 1, len(ghdr))
        nc = f'{DR}!$C$2:$C${n},"Negative Control"'
        gates = [
            ("G1 Citation accuracy", f'=SUM({rng("R")})/COUNT({rng("R")})', 0.99, ">=", "0.0%", "every scored row, rubric L"),
            ("G2 Fabricated citations (count)", f'=SUM({rng("S")})', 0, "==", "0", "every scored row, rubric M"),
            ("G3 Negative control pass rate", f'=SUMIFS({rng("R")},{nc})/COUNTIFS({nc})', 1.0, "==", "0.0%", "the 22 Negative Control rows, rubric L"),
            ("G4 Substantive correctness", f'=SUM({rng("T")})/(2*COUNT({rng("T")}))', 0.95, ">=", "0.0%", "points out of maximum, rubric N"),
            ("G5 Completeness", f'=SUM({rng("U")})/(2*COUNT({rng("U")}))', 0.90, ">=", "0.0%", "points out of maximum, rubric O"),
            ("G6 Scope discipline", f'=SUM({rng("V")})/COUNT({rng("V")})', 0.98, ">=", "0.0%", "every scored row, rubric P"),
            ("G7 ISO 13485 clause concordance", f'=SUM({rng("W")})/COUNT({rng("W")})', 0.95, ">=", "0.0%", "rows carrying an ISO clause key, rubric Q"),
        ]
        for j, (name, formula, thr, cmp_, fmt, scoped) in enumerate(gates, start=gstart + 2):
            ws.cell(row=j, column=1, value=name)
            ws.cell(row=j, column=2, value=formula).number_format = fmt
            ws.cell(row=j, column=3, value=("= 0" if cmp_ == "==" and thr == 0 else ("100%" if thr == 1 else (f"{thr:.0%}" if cmp_ == ">=" else thr))))
            ws.cell(row=j, column=4, value=(f'=IF(B{j}{"<=" if cmp_ == "==" and thr == 0 else ("=" if cmp_ == "==" else ">=")}{thr},"PASS","FAIL")'))
            ws.cell(row=j, column=5, value=scoped)
            for c in range(1, 6):
                ws.cell(row=j, column=c).font = Font(name=FONT)
        oa = gstart + 2 + len(gates)
        ws.cell(row=oa, column=1, value="OVERALL ACCEPTANCE (all seven gates must read PASS)").font = Font(name=FONT, bold=True)
        ws.cell(row=oa, column=2, value=f'=IF(COUNTIF(D{gstart + 2}:D{oa - 1},"FAIL")=0,"PASS","FAIL")').font = Font(name=FONT, bold=True, color="C00000")
        ws.cell(row=oa + 1, column=1, value="Answer key verification (benchmark column K)").font = Font(name=FONT, bold=True)
        ws.cell(row=oa + 1, column=2, value="0 of 300 rows marked Y - WARNING, key not SME-verified").font = Font(name=FONT, color="C00000")
        gstart = oa + 3
        for c in "CDE":
            ws.column_dimensions[c].width = 22
    start = gstart
    ws.cell(row=start, column=1, value="Breakdown by category (Domain, col B)").font = Font(name=FONT, bold=True)
    hdr = ["Category", "Total", "Tested", "Passed", "Failed", "Errors", "SME review", "Flagged (indicator)"]
    for i, h in enumerate(hdr, start=1):
        ws.cell(row=start + 1, column=i, value=h)
    style_header(ws, start + 1, len(hdr))
    domains = list(dict.fromkeys(q.domain for q in bench))
    for j, d in enumerate(domains, start=start + 2):
        ws.cell(row=j, column=1, value=d)
        crit = f'{rng("B")},$A{j}'
        ws.cell(row=j, column=2, value=f"=COUNTIF({crit})")
        ws.cell(row=j, column=3, value=f'=COUNTIFS({crit},{rng("L")},"OK")')
        for col, val in ((4, "PASS"), (5, "FAIL"), (6, "ERROR"), (7, SME)):
            ws.cell(row=j, column=col, value=f'=COUNTIFS({crit},{rng("M")},"{val}")')
        ws.cell(row=j, column=8, value=f'=COUNTIFS({crit},{rng("Q")},"Y")')
        for c in range(1, 9):
            ws.cell(row=j, column=c).font = Font(name=FONT)
    for c in "CDEFGH":
        ws.column_dimensions[c].width = 12

    # ---------------------------------------------------------------- Failed Questions
    wf = wb.create_sheet("Failed Questions")
    wf["A1"] = ((f"{results.count('FAIL')} questions were scored FAIL against the benchmark rubric. Each row gives the reason, the gate "
                 "and rubric dimension it fails, the citation problem if any, and where to investigate. PASS rows and the technical ERROR "
                 "are not listed here.")
                if args.verdicts else
                (f"FAIL rows: {results.count('FAIL')}. No answer can be marked FAIL because the key is unverified (see Summary). "
                 f"Listed below are the {len(flagged)} answers with machine indicators of a likely failure, for PRIORITY SME review."))
    wf["A1"].font = Font(name=FONT, bold=True, color="C00000")
    wf["A1"].alignment = Alignment(wrap_text=True)
    wf.merge_cells("A1:I1")
    wf.row_dimensions[1].height = 45
    table(wf, ["Question ID", "Category", "Question", "Expected / Reference (DRAFT)", "Model Answer", "Why flagged (provisional)",
               "Relevant acceptance criterion", "Citation issue", "Recommended investigation area"],
          flagged, [10, 24, 45, 45, 60, 55, 30, 40, 35], start=2)

    # ---------------------------------------------------------------- Partial credit
    if args.verdicts:
        partial.sort(key=lambda r: (0 if r[5].startswith("A") else 1, r[0], r[1]))
        band_a = sum(1 for r in partial if r[5].startswith("A"))
        wp = wb.create_sheet("Partially Correct")
        wp["A1"] = (f"{len(partial)} answers earned partial credit under the rubric but are not passes: {band_a} where the substance is fully "
                    f"correct and one other dimension blocks the pass (band A), and {len(partial) - band_a} that are directionally right but "
                    "materially incomplete or partly misleading (band B). Rows are ordered by how close they are to passing - fewest blocking "
                    "dimensions first - so band A and the single-blocker rows are at the top. Answers scoring 0 for both substance and "
                    "completeness are not listed here; they are in Failed Questions.")
        wp["A1"].font = Font(name=FONT, bold=True, color="7F6000")
        wp["A1"].alignment = Alignment(wrap_text=True, vertical="top")
        wp.merge_cells("A1:M1")
        wp.row_dimensions[1].height = 60
        table(wp, ["Question ID", "Category (Domain)", "Question Type", "Question", "Partial-credit band",
                   "Rubric scores", "Blocking dimensions", "Model Answer", "Expected / Reference (DRAFT)",
                   "What was right and what was missing", "Verification note", "Fails on one dimension only",
                   "Borderline - SME second look"],
              [r[1:] for r in partial], [10, 24, 14, 45, 46, 40, 30, 70, 45, 75, 60, 12, 12], start=2)
        wp.auto_filter.ref = f"A2:M{len(partial) + 2}"

    # ---------------------------------------------------------------- Errors
    we = wb.create_sheet("Errors - Execution Issues")
    we["A1"] = f"Execution errors: {len(errors)} (recorded once, not retried; separate from model-quality results)."
    we["A1"].font = Font(name=FONT, bold=True)
    table(we, ["Question ID", "Category", "Question", "Error", "Time (s)", "Traceback (tail)", "Classification"],
          errors or [["—", "", "No execution errors, timeouts or malformed responses occurred.", "", "", "", ""]],
          [10, 24, 45, 40, 9, 70, 30], start=2)

    # ---------------------------------------------------------------- Category Analysis
    wc = wb.create_sheet("Category Analysis")
    hdr = ["Category", "Total questions", "Passed", "Failed", "Errors", "SME review", "Pass rate %", "Fail rate %",
           "Flagged (indicator)", "Flagged % of tested"]
    r0 = 1
    for title, col, values in (("By Domain (benchmark col B)", "B", domains),
                               ("By Question Type (benchmark col D)", "C", list(dict.fromkeys(q.question_type for q in bench)))):
        wc.cell(row=r0, column=1, value=title).font = Font(name=FONT, bold=True)
        for i, h in enumerate(hdr, start=1):
            wc.cell(row=r0 + 1, column=i, value=h)
        style_header(wc, r0 + 1, len(hdr))
        for j, v in enumerate(values, start=r0 + 2):
            crit = f"{rng(col)},$A{j}"
            wc.cell(row=j, column=1, value=v)
            wc.cell(row=j, column=2, value=f"=COUNTIF({crit})")
            for c, val in ((3, "PASS"), (4, "FAIL"), (5, "ERROR"), (6, SME)):
                wc.cell(row=j, column=c, value=f'=COUNTIFS({crit},{rng("M")},"{val}")')
            wc.cell(row=j, column=7, value=f'=IF(C{j}+D{j}=0,"n/d",C{j}/(C{j}+D{j}))')
            wc.cell(row=j, column=8, value=f'=IF(C{j}+D{j}=0,"n/d",D{j}/(C{j}+D{j}))')
            wc.cell(row=j, column=9, value=f'=COUNTIFS({crit},{rng("Q")},"Y")')
            wc.cell(row=j, column=10, value=f'=IF(B{j}-E{j}=0,"n/d",I{j}/(B{j}-E{j}))')
            for c in range(1, 11):
                wc.cell(row=j, column=c).font = Font(name=FONT)
            for c in (7, 8, 10):
                wc.cell(row=j, column=c).number_format = "0.0%"
        r0 = r0 + 2 + len(values) + 1
    wc.cell(row=r0, column=1, value="n/d = not determinable: no row is scored PASS/FAIL while the key is unverified.").font = Font(name=FONT, italic=True)
    wc.column_dimensions["A"].width = 60
    for c in "BCDEFGHIJ":
        wc.column_dimensions[c].width = 13

    # ---------------------------------------------------------------- Test Metadata
    wm = wb.create_sheet("Test Metadata")
    bm = meta.get("benchmark") or {}
    pc = repro.get("pipeline_config") or {}
    mrows = [
        ("Benchmark filename", bm.get("file")), ("Benchmark revision", f"{bm.get('version')} ({bm.get('benchmark_key')})"),
        ("Number of questions", bm.get("questions")), ("Benchmark sha256 before test", bm.get("sha256_before")),
        ("Benchmark sha256 after test", bm.get("sha256_after")), ("Benchmark unchanged", bm.get("unchanged")),
        ("Answer-key verification", json.dumps(bm.get("key_verification"))),
        ("Active model", json.dumps(meta.get("active_model"))), ("Model id / revision", f"{repro.get('model_id')} @ {repro.get('model_revision')}"),
        ("Weights sha256", repro.get("weights_sha256")), ("Device / dtype", f"{repro.get('device')} / {repro.get('dtype')}"),
        ("Decoding", json.dumps(repro.get("decoding"))), ("System prompt sha256", repro.get("system_prompt_sha256")),
        ("Pipeline configuration", json.dumps(pc)), ("Retriever", json.dumps(repro.get("retriever"))),
        ("Git commit", repro.get("git_commit")), ("Git working tree dirty", repro.get("git_dirty")),
        ("Hardware / OS", json.dumps(meta.get("hardware"))), ("Started (UTC)", meta.get("started_utc")), ("Finished (UTC)", meta.get("finished_utc")),
        ("Test command", meta.get("command")), ("Protocol", meta.get("protocol")),
        ("Results workbook command", "PYTHONPATH=<openpyxl dir> python scripts/build_acceptance_results.py --run " + str(run.relative_to(ROOT))),
        ("Raw outputs (audit)", str((run / "answers.jsonl").relative_to(ROOT))),
        ("Environment variables", "DB connection from .env (REGULUS_DATABASE_URL; value not recorded); no REGULUS_ADAPTER; model.backend=transformers"),
        ("Scoring method", "Benchmark rubric columns L-Q (Scoring Rubric tab), SME/independent reviewer, against an SME-verified key. "
                           "Not applied: key unverified (0/300). Machine indicators are provisional aids only."),
        ("Duplicate answer records ignored", ", ".join(duplicates) or "none"),
    ]
    table(wm, ["Field", "Value"], [[k, "" if v is None else str(v)] for k, v in mrows], [32, 120])

    # ---------------------------------------------------------------- Indicator legend
    wl = wb.create_sheet("Scoring Method & Legend" if args.verdicts else "Indicator Legend")
    method = [
        ["HOW EACH QUESTION WAS SCORED", "The workbook's own rubric (Scoring Rubric tab, columns L-Q) was applied question by question. "
         "Each answer was read against the text of the cited provisions in the read-only eCFR snapshot, not against the draft key alone."],
        ["L Citation Exact (1/0)", "1 = every citation the answer attaches to a statement is correct to the section or paragraph, and the "
         "governing provision is identified. For a negative control, 1 = correctly declined."],
        ["M Fabricated Citation (1 = failure)", "1 = the answer cites a section, clause, guidance or rule that does not exist. A provision that "
         "existed but was superseded (for example the sections reserved by the QMSR) is scored as a citation error under L, not as fabrication."],
        ["N Substantive (0-2)", "2 = substantively correct. 1 = partially correct, materially incomplete or misleading. 0 = wrong, or no "
         "substantive answer delivered."],
        ["O Completeness (0-2)", "2 = all governing sections and required elements surfaced. 1 = primary provision only. 0 = material omission."],
        ["P Scope Discipline (1/0)", "1 = stayed in scope: no legal advice, no compliance guarantee, non-Title-21 topics flagged, no reproduction "
         "of copyrighted standard text, and no guidance presented as the source of a binding requirement."],
        ["Q ISO Clause (1/0/blank)", "1 = named the correct ISO 13485 clause(s) from benchmark column H, or named none where column H reads "
         "'None'. Blank where column H reads an em dash."],
        ["Result = PASS", "Awarded only where L=1, M=0, N=2, O>=1, P=1 and Q is 1 or blank: a correct, correctly cited answer with no material "
         "failure. Completeness of 1 is recorded in the notes."],
        ["Result = FAIL", "Any material failure under the rubric: wrong or missing citation, fabricated citation or requirement, substantively "
         "wrong or materially incomplete answer, scope-discipline breach, or a missed ISO clause on a gate G7 row."],
        ["Result = ERROR", "Could not be evaluated for a technical reason. One row: the database cancelled a query during retrieval, so no model "
         "answer exists. Not a model-quality failure."],
        ["Result = REQUIRES SME REVIEW", "Reserved for genuine substantive ambiguity that the benchmark, the regulation and the rubric cannot "
         "resolve. No row needed it in this run."],
        ["Partially Correct sheet", "Every answer that earned partial credit under the rubric without passing. Band A: substance scored 2 of 2 "
         "and a single other dimension - usually one misdirected citation - blocks the pass. Band B: substance scored 1 of 2, meaning the answer "
         "points the right way but is materially incomplete or partly misleading. Rows are ordered closest-to-passing first."],
        ["Blocking dimensions", "The rubric dimensions a partially correct answer still fails. A row listing one dimension would pass if that "
         "single defect were corrected; a row listing three or four needs substantive rework, not a citation fix."],
        ["Borderline - SME second look", "Y marks a row where the scoring is defensible either way, for example a complete and correct answer "
         "that fails only on one misdirected citation marker. The reason is in the Scoring Notes."],
        ["Draft key errors", "Where the draft key itself names the wrong provision, the model was judged against the regulation and not penalised "
         "for the mismatch. Those rows are identified in Evaluator Notes (for example S-004, S-007, S-021)."],
        ["", ""],
    ] if args.verdicts else []
    table(wl, ["Indicator", "Meaning / limitation"], method + [
        ["Result = REQUIRES SME REVIEW", "Executed; no verdict because the key is unverified and the vendor must not score the test."],
        ["Result = ERROR", "The pipeline raised an exception; recorded once, not retried. Not a model-quality failure."],
        ["Result = NOT TESTED", "No answer recorded for the row."],
        ["Citation vs Draft Key", "Section-level comparison of provisions named/cited in the answer with column G (DRAFT). "
                                  "'same part, different section' and 'different part' suggest a citation error IF the draft key is right."],
        ["cites provision reserved/removed in the current snapshot", "The cited section falls inside a reserved span of the current snapshot "
                                                                     "(e.g. 820.20-820.30 under the QMSR). The provision existed before; citing it as current is a temporal/citation error, not fabrication."],
        ["cited provision has no entry in the current snapshot", "A cited section/paragraph has no entry at all in the local eCFR snapshot (read-only DB): either removed "
                                                                 "entirely (e.g. 820.100, 820.198 under the QMSR) or never existed. Verify against eCFR before calling it fabrication; "
                                                                 "the snapshot may not hold every Title 21 part."],
        ["negative control: substantive answer given", "A trap question was answered rather than declined (heuristic on decline wording)."],
        ["answer withheld by validation", "The pipeline's validator replaced the model's answer with a 'could not be validated' notice: no substantive answer."],
        ["temporal: cites reserved section", "Answer cites a section the DB marks [Reserved] without saying so (QMSR transition)."],
        ["draft ISO clause(s) not named", "G7 rows: none of column H's draft clause numbers appear in the answer."],
        ["Raw Model Output", "The model's text before the pipeline's validation/repair; the 'Model Answer' column is what a user sees."],
    ], [40, 120])

    wb.calculation.fullCalcOnLoad = True
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)

    # ---------------------------------------------------------------- verification
    chk = load_workbook(out_path)
    ids = [chk["Detailed Results"].cell(row=r, column=1).value for r in range(2, chk["Detailed Results"].max_row + 1)]
    counts = Counter(results)
    report = {
        "workbook": str(out_path), "sheets": chk.sheetnames, "detail_rows": len(ids), "unique_ids": len(set(ids)),
        "all_benchmark_ids_present": set(ids) == {q.question_id for q in bench}, "results": dict(counts),
        "results_sum": sum(counts.values()), "flagged": len(flagged), "errors": len(errors),
        "median_seconds": round(statistics.median(times), 2) if times else None,
        "mean_seconds": round(statistics.mean(times), 2) if times else None,
        "benchmark_sha256_now": bench_sha, "benchmark_unchanged_vs_run_start": bench_sha == bm.get("sha256_before"),
        "duplicates_in_answers": duplicates,
    }
    (run / "results_build_check.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
