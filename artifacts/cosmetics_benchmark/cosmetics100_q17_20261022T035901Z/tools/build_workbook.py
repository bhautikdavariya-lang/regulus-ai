"""Build the cosmetics benchmark workbook from a finished run directory and its rubric verdicts.

    PYTHONPATH=<openpyxl dir> python build_workbook.py <run_dir> <out.xlsx>

Reads only: selection.json, results.jsonl, responses/*.json, run_log.jsonl, server_config_*.json,
scoring/verdicts.json, scoring/run_facts.json. Writes only <out.xlsx>.

Category mapping (rubric scores -> reporting category) is `category()` below and is written into the
Run Metadata sheet verbatim.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import evidence_check, load_run, resolve_markers  # noqa: E402

PASS, PPASS, PFAIL, FAIL, NE = "PASS", "PARTIALLY PASS", "PARTIALLY FAIL", "FAIL", "NOT EVALUATED"
CATEGORIES = [PASS, PPASS, PFAIL, FAIL, NE]

MAPPING_TEXT = (
    "Each answer is scored on the question bank's rubric (the Scoring Rubric of the main Regulus acceptance benchmark, "
    "which the bank's Instructions sheet names) against the bank's VERIFIED key: Citation Exact (1/0), Fabricated "
    "Citation (1/0, 1 = failure), Substantive (0-2), Completeness (0-2), Scope Discipline (1/0). ISO concordance is "
    "not scored (every selected row's ISO clause is '—'). The five scores are mapped to the reporting category "
    "deterministically, in this order: (1) no answer returned (execution ERROR/TIMEOUT) -> NOT EVALUATED; "
    "(2) Substantive 0 -> FAIL; (3) Substantive 1 -> PARTIALLY FAIL; (4) Substantive 2 with Fabricated 1, Scope 0 "
    "or Completeness 0 -> PARTIALLY FAIL; (5) Substantive 2, Completeness 2, Citation Exact 1, Fabricated 0, "
    "Scope 1 -> PASS; (6) otherwise (Substantive 2 with Completeness 1 and/or Citation Exact 0) -> PARTIALLY PASS. "
    "An answer withheld by the validator, or any other decline, on a question the verified key answers scores "
    "Substantive 0 / Completeness 0 and is FAIL (no supported answer where one is required); it is an evaluated "
    "outcome, not NOT EVALUATED. The project's own live evaluator (regulus_live_evidence_assessment_v2) is "
    "recorded beside it but does not decide the category: it compares the answer with the evidence retrieved for "
    "it and uses no reference answer.")


def category(v: dict | None, exec_status: str) -> str:
    if exec_status != "SUCCESS" or v is None:
        return NE
    if v["sub"] == 0:
        return FAIL
    if v["sub"] == 1:
        return PFAIL
    if v["fab"] == 1 or v["scope"] == 0 or v["comp"] == 0:
        return PFAIL
    if v["comp"] == 2 and v["ce"] == 1:
        return PASS
    return PPASS


DELIVERED = {
    None: "Generated answer",
    "unvalidated_answer_withheld": "Withheld by validator (no answer shown)",
    "verbatim_requested_provision": "Repair: requested provision quoted verbatim",
    "definitions_quoted": "Fallback: CFR definitions quoted",
    "premise_not_established": "Fallback: premise not established",
    "no_evidence": "Fallback: no evidence",
    "provision_not_found": "Fallback: provision not found",
    "out_of_scope": "Fallback: out of scope",
    "wrong_provision": "Fallback: wrong provision",
    "value_not_established": "Fallback: value not established",
    "ambiguous": "Fallback: ambiguous",
    "unsupported_request": "Fallback: unsupported request",
}

ARIAL = "Arial"
F_BASE = Font(name=ARIAL, size=10)
F_BOLD = Font(name=ARIAL, size=10, bold=True)
F_HEAD = Font(name=ARIAL, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=ARIAL, size=14, bold=True, color="1F3864")
F_SECTION = Font(name=ARIAL, size=11, bold=True, color="1F3864")
F_NOTE = Font(name=ARIAL, size=9, italic=True, color="595959")
FILL_HEAD = PatternFill("solid", fgColor="1F3864")
FILL_SECTION = PatternFill("solid", fgColor="D9E1F2")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP_TOP = Alignment(wrap_text=True, vertical="top")
CAT_FILL = {PASS: "C6EFCE", PPASS: "E2EFDA", PFAIL: "FCE4D6", FAIL: "FFC7CE", NE: "D9D9D9"}
CAT_FONT = {PASS: "006100", PPASS: "375623", PFAIL: "833C0B", FAIL: "9C0006", NE: "404040"}


def style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font, cell.fill, cell.border = F_HEAD, FILL_HEAD, BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def add_status_formatting(ws, col_letter: str, first: int, last: int) -> None:
    rng = f"{col_letter}{first}:{col_letter}{last}"
    for cat in CATEGORIES:
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f'${col_letter}{first}="{cat}"'], stopIfTrue=True,
            fill=PatternFill("solid", fgColor=CAT_FILL[cat]), font=Font(name=ARIAL, bold=True, color=CAT_FONT[cat])))


def seconds(ms):
    return None if ms is None else round(ms / 1000.0, 3)


def retrieval_notes(q, r, resp) -> str:
    if r is None or r["execution_status"] != "SUCCESS":
        return "No response: no retrieval metadata."
    ev = evidence_check(q, resp)
    parts = []
    if ev["statute_key"] and not ev["expected"]:
        parts.append("Key cites FD&C Act (statute) only; the Regulus corpus holds eCFR and FDA guidance, no statute text.")
    elif ev["statute_key"]:
        parts.append("Key cites FD&C Act (statute) and CFR; statute text is not in the Regulus corpus.")
    if ev["expected"]:
        missing = [s for s in ev["expected"] if s not in ev["in_evidence"]]
        parts.append(f"Expected CFR section(s) {', '.join(ev['expected'])}: "
                     + ("all in evidence" if not missing else
                        ("none in evidence" if len(missing) == len(ev["expected"]) else f"missing from evidence: {', '.join(missing)}"))
                     + (f"; cited in answer: {', '.join(ev['cited'])}" if ev["cited"] else "; none cited in answer") + ".")
    srcs = (resp or {}).get("sources") or []
    parts.append("Evidence (" + str(len(srcs)) + "): " + "; ".join(
        f"{(s.get('citation') or '')[:110]} [{s.get('method')}]" for s in srcs) + ".")
    sf = r.get("semantic_fallback") or {}
    parts.append(f"Query type {r.get('query_type')}; semantic fallback {'invoked' if sf.get('invoked') else 'not invoked'}"
                 + (f" (skipped: {sf.get('skipped')})" if sf.get("skipped") else "") + ".")
    cov = r.get("evidence_gap")   # results.jsonl field holds coverage.evidence_complete
    if cov is not None:
        parts.append(f"Coverage evidence_complete={cov}.")
    return " ".join(parts)


def validator_outcome(r) -> str:
    if r is None or r["execution_status"] != "SUCCESS":
        return ""
    s = f"initial {r.get('validation_initial')}"
    if r.get("validation_initial_codes"):
        s += " [" + ", ".join(r["validation_initial_codes"]) + "]"
    s += f" -> final {r.get('validation_final')}"
    if r.get("repair"):
        s += "; repair applied"
    if r.get("fallback_type"):
        s += f"; fallback {r['fallback_type']}"
    if r.get("stop_reason"):
        s += f"; stop {r['stop_reason']}"
    if r.get("finished") is False:
        s += "; generation hit token allowance"
    return s


def main() -> int:
    run_dir, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    items = load_run(run_dir)
    sel = json.loads((run_dir / "selection.json").read_text(encoding="utf-8"))["summary"]
    verdicts = json.loads((run_dir / "scoring" / "verdicts.json").read_text(encoding="utf-8"))
    facts = json.loads((run_dir / "scoring" / "run_facts.json").read_text(encoding="utf-8"))
    base_model, embed_model = facts["base_model_cell"], facts["embedding_model_cell"]

    wb = Workbook()
    wb.calculation = CalcProperties(fullCalcOnLoad=True)

    # ------------------------------------------------------------ Sheet 1: Question Results
    ws = wb.active
    ws.title = "Question Results"
    cols = [
        ("Question ID", 16), ("Question", 50), ("Reference Answer", 60), ("Generated Answer", 70),
        ("Evaluation Status", 15), ("Evaluation Explanation", 60), ("Duration (seconds)", 11), ("Input Tokens", 10),
        ("Output Tokens", 10), ("Base Model", 18), ("Embedding Model", 18), ("Execution Status", 11),
        ("Error Details", 22), ("Retrieval Notes", 60),
        # supporting columns (after the 14 required ones)
        ("Run Order", 7), ("Part (Stratum)", 10), ("Question Type", 14), ("Difficulty", 11),
        ("Expected Citation (Verified Key)", 26), ("Citation Exact (1/0)", 9), ("Fabricated Citation (1/0)", 10),
        ("Substantive (0-2)", 10), ("Completeness (0-2)", 11), ("Scope Discipline (1/0)", 10),
        ("Delivered Answer Type", 22), ("Validator Outcome", 34), ("Citations in Answer", 28),
        ("Regulus Live Evaluator Status", 15), ("Live Evaluator Score (0-100)", 11), ("Live Evaluator Explanation", 50),
        ("Pipeline Time (s)", 10), ("Retrieval Time (s)", 10), ("Generation Time (s)", 10), ("Live Evaluation Time (s)", 10),
        ("Telemetry Notes", 30),
    ]
    for i, (name, width) in enumerate(cols, start=1):
        ws.cell(row=1, column=i, value=name)
        ws.column_dimensions[get_column_letter(i)].width = width
    style_header(ws, 1, len(cols))
    ws.row_dimensions[1].height = 42

    rows_out = []
    for n, it in enumerate(items, start=2):
        q, r, resp = it["q"], it["r"], it["resp"]
        exec_status = r["execution_status"] if r else "NOT RUN"
        v = verdicts.get(q["ID"])
        cat = category(v, exec_status)
        if exec_status == "SUCCESS" and v is None:
            raise SystemExit(f"no verdict for {q['ID']}")
        if cat == NE:
            why = (f"Not evaluated: the system returned no answer ({exec_status}). "
                   + (r.get("error") or "") if r else "Not evaluated: no attempt recorded.")
        else:
            why = v["why"]
        st, t = (r or {}).get("server_timings_ms") or {}, (r or {}).get("timings_ms") or {}
        tele = []
        if exec_status == "SUCCESS":
            if r.get("input_tokens") is None:
                tele.append("input tokens not reported (model not called)")
            if r.get("output_tokens") is None:
                tele.append("output tokens not reported (model not called)")
            if (st.get("lock_wait_ms") or 0) > 1:
                tele.append(f"server lock wait {st['lock_wait_ms']} ms")
        else:
            tele.append("no response: tokens unavailable; duration is time to failure")
        markers = resolve_markers((r or {}).get("answer") or "", resp)
        live = (r or {}).get("live_eval") or {}
        values = [
            q["ID"], q["Question (ask verbatim)"], q["Key Answer Elements"], (r or {}).get("answer"),
            cat, why, (r or {}).get("client_seconds"), (r or {}).get("input_tokens"), (r or {}).get("output_tokens"),
            base_model, embed_model, exec_status, (r or {}).get("error") or "",
            retrieval_notes(q, r, resp),
            q["Run Order"], q["Stratum"], q["Question Type"], q["Difficulty"], q["Expected Citation — VERIFIED KEY"],
            v["ce"] if v else None, v["fab"] if v else None, v["sub"] if v else None, v["comp"] if v else None,
            v["scope"] if v else None,
            DELIVERED.get((r or {}).get("fallback_type"), f"Fallback: {(r or {}).get('fallback_type')}") if exec_status == "SUCCESS" else "",
            validator_outcome(r), "; ".join(markers),
            live.get("label"), live.get("score"), live.get("explanation"),
            seconds(st.get("pipeline_answer_ms")), seconds(t.get("retrieval_ms")), seconds(t.get("generation_ms")),
            seconds(st.get("accuracy_ms")), "; ".join(tele),
        ]
        for c, val in enumerate(values, start=1):
            cell = ws.cell(row=n, column=c, value=val)
            cell.font, cell.alignment, cell.border = F_BASE, WRAP_TOP, BORDER
        for c in (7, 31, 32, 33, 34):
            ws.cell(row=n, column=c).number_format = "0.000"
        for c in (8, 9):
            ws.cell(row=n, column=c).number_format = "#,##0"
        rows_out.append({"id": q["ID"], "cat": cat, "exec": exec_status, "dur": (r or {}).get("client_seconds"),
                         "in": (r or {}).get("input_tokens"), "out": (r or {}).get("output_tokens"),
                         "live": live.get("label"), "delivered": values[24], "v": v, "q": q, "r": r, "why": why})
    last = len(items) + 1
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{last}"
    add_status_formatting(ws, "E", 2, last)

    # ------------------------------------------------------------ Sheet 2: Summary
    sm = wb.create_sheet("Summary")
    QR = "'Question Results'"
    rng = lambda col: f"{QR}!${col}$2:${col}${last}"  # noqa: E731
    sm.column_dimensions["A"].width = 2
    sm.column_dimensions["B"].width = 46
    sm.column_dimensions["C"].width = 22
    sm.column_dimensions["D"].width = 70
    sm["B1"] = "Regulus Cosmetics Benchmark — 100 main questions"
    sm["B1"].font = F_TITLE
    sm["B2"] = (f"Run {facts['run_id']} · {facts['run_window']} · model {facts['base_model_short']} · rubric scoring is "
                "AI-assisted against the bank's verified key (not SME-signed)")
    sm["B2"].font = F_NOTE
    r_ = 4

    def section(title):
        nonlocal r_
        sm.cell(row=r_, column=2, value=title)
        for c in (2, 3, 4):
            sm.cell(row=r_, column=c).fill = FILL_SECTION
            sm.cell(row=r_, column=c).font = F_SECTION
        r_ += 1

    def line(label, value, note="", fmt=None, bold=False):
        nonlocal r_
        a = sm.cell(row=r_, column=2, value=label)
        b = sm.cell(row=r_, column=3, value=value)
        c = sm.cell(row=r_, column=4, value=note)
        for cell in (a, b, c):
            cell.font, cell.border, cell.alignment = (F_BOLD if bold else F_BASE), BORDER, WRAP_TOP
        c.font = F_NOTE
        b.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
        if fmt:
            b.number_format = fmt
        r_ += 1
        return f"$C${r_ - 1}"

    section("Benchmark overview")
    line("Question bank filename", facts["bank_file"], "Questions sheet only (main questions); follow-ups not used")
    sel_ref = line("Total questions selected", f"=COUNTA({rng('A')})", "rows on Question Results", "0")
    att_ref = line("Total questions attempted", f"=COUNTA({rng('L')})-COUNTIF({rng('L')},\"NOT RUN\")", "rows with an execution status other than NOT RUN", "0")
    ok_ref = line("Total successfully generated answers", f"=COUNTIF({rng('L')},\"SUCCESS\")",
                  "HTTP 200 with an answer field (includes answers the validator replaced with a withholding notice)", "0")
    line("  of which withheld by the validator", f"=COUNTIF({rng('Y')},\"Withheld*\")", "Delivered Answer Type = Withheld by validator", "0")
    line("  of which another fallback/repair text", f"=COUNTIF({rng('Y')},\"Fallback*\")+COUNTIF({rng('Y')},\"Repair*\")", "", "0")
    line("Total execution errors", f"=COUNTIF({rng('L')},\"ERROR\")", "", "0")
    line("Total timeouts", f"=COUNTIF({rng('L')},\"TIMEOUT\")", f"client timeout {facts['timeout_s']} s", "0")
    ev_ref = line("Total evaluated questions", f"=COUNTA({rng('E')})-COUNTIF({rng('E')},\"{NE}\")", "PASS + PARTIALLY PASS + PARTIALLY FAIL + FAIL", "0")
    line("Questions not evaluated", f"=COUNTIF({rng('E')},\"{NE}\")", "", "0")
    line("Benchmark execution (UTC)", facts["run_window"], "first question sent → last answer received")
    line("Benchmark run identifier", facts["run_id"], "artifacts/cosmetics_benchmark/<run id>/")
    r_ += 1

    section("Evaluation results (rubric vs verified key)")
    hdr_row = r_
    for c, txt in zip((2, 3, 4), ("Category", "Count", "Share of evaluated questions")):
        sm.cell(row=r_, column=c, value=txt)
    style_header(sm, r_, 4)
    sm.cell(row=r_, column=1).fill = PatternFill()
    r_ += 1
    cat_rows = {}
    first_cat_row = r_
    for cat in CATEGORIES:
        sm.cell(row=r_, column=2, value=cat)
        sm.cell(row=r_, column=3, value=f"=COUNTIF({rng('E')},\"{cat}\")").number_format = "0"
        if cat != NE:
            sm.cell(row=r_, column=4, value=f"=IFERROR(C{r_}/{ev_ref},\"\")").number_format = "0.0%"
        else:
            sm.cell(row=r_, column=4, value="excluded from the evaluated denominator")
        for c in (2, 3, 4):
            sm.cell(row=r_, column=c).border = BORDER
            sm.cell(row=r_, column=c).font = F_BASE
        sm.cell(row=r_, column=2).fill = PatternFill("solid", fgColor=CAT_FILL[cat])
        sm.cell(row=r_, column=2).font = Font(name=ARIAL, size=10, bold=True, color=CAT_FONT[cat])
        cat_rows[cat] = r_
        r_ += 1
    last_cat_row = r_ - 1
    sm.cell(row=r_, column=2, value="TOTAL SELECTED").font = F_BOLD
    sm.cell(row=r_, column=3, value=f"=SUM(C{first_cat_row}:C{last_cat_row})").font = F_BOLD
    sm.cell(row=r_, column=4, value=f"=IF(C{r_}={sel_ref},\"reconciles with questions selected\",\"DOES NOT RECONCILE\")").font = F_NOTE
    for c in (2, 3, 4):
        sm.cell(row=r_, column=c).border = BORDER
    r_ += 2

    section("Rates")
    P, PP, PF, F_, N_ = (f"$C${cat_rows[c]}" for c in CATEGORIES)
    line("Strict pass rate", f"=IFERROR({P}/{ev_ref},\"\")", "PASS ÷ evaluated questions", "0.0%", bold=True)
    line("Pass-or-partially-pass rate", f"=IFERROR(({P}+{PP})/{ev_ref},\"\")", "(PASS + PARTIALLY PASS) ÷ evaluated questions", "0.0%", bold=True)
    line("Partial-failure rate", f"=IFERROR({PF}/{ev_ref},\"\")", "PARTIALLY FAIL ÷ evaluated questions", "0.0%")
    line("Failure rate", f"=IFERROR({F_}/{ev_ref},\"\")", "FAIL ÷ evaluated questions", "0.0%")
    line("Evaluation coverage", f"=IFERROR({ev_ref}/{sel_ref},\"\")", "evaluated ÷ total selected", "0.0%")
    line("Execution success rate", f"=IFERROR({ok_ref}/{sel_ref},\"\")", "successful answer generations ÷ total selected", "0.0%")
    r_ += 1

    section("Performance statistics (measured values only; blanks are not zeros)")
    G, H, I_ = rng("G"), rng("H"), rng("I")
    line("Total benchmark duration — wall clock (s)", facts["wall_seconds"], "first request sent → last response received (run_log.jsonl; excludes the warm-up)", "#,##0.000")
    line("Total benchmark duration — sum of question durations (s)", f"=SUM({G})", "", "#,##0.000")
    line("Average question duration (s)", f"=IFERROR(AVERAGE({G}),\"\")", "", "0.000", bold=True)
    line("Median question duration (s)", f"=IFERROR(MEDIAN({G}),\"\")", "", "0.000", bold=True)
    line("Minimum question duration (s)", f"=IFERROR(MIN({G}),\"\")", "", "0.000")
    line("Maximum question duration (s)", f"=IFERROR(MAX({G}),\"\")", "", "0.000")
    line("Duration observations", f"=COUNT({G})", "questions with a measured duration", "0")
    line("Average input tokens", f"=IFERROR(AVERAGE({H}),\"\")", "final answer-generation call (one model call per question)", "#,##0.0")
    line("Average output tokens", f"=IFERROR(AVERAGE({I_}),\"\")", "", "#,##0.0")
    line("Total input tokens", f"=SUM({H})", "", "#,##0")
    line("Total output tokens", f"=SUM({I_})", "", "#,##0")
    line("Input-token observations", f"=COUNT({H})", "", "0")
    line("Output-token observations", f"=COUNT({I_})", "", "0")
    line("Questions missing duration", f"={sel_ref}-COUNT({G})", "", "0")
    line("Questions missing input tokens", f"={sel_ref}-COUNT({H})", "model not called or no response", "0")
    line("Questions missing output tokens", f"={sel_ref}-COUNT({I_})", "", "0")
    line("Average pipeline time (s)", f"=IFERROR(AVERAGE({rng('AE')}),\"\")", "server: RagPipeline.answer only", "0.000")
    line("Average retrieval time (s)", f"=IFERROR(AVERAGE({rng('AF')}),\"\")", "server timings_ms.retrieval_ms", "0.000")
    line("Average generation time (s)", f"=IFERROR(AVERAGE({rng('AG')}),\"\")", "server timings_ms.generation_ms", "0.000")
    line("Average live-evaluation time (s)", f"=IFERROR(AVERAGE({rng('AH')}),\"\")", "server accuracy_ms", "0.000")
    r_ += 1

    section("Regulus live evaluator (recorded alongside; does not decide the category)")
    for lab in ("PASS", "FAIL", "NOT EVALUATED", "NOT FULLY EVALUATED"):
        line(f"Live evaluator: {lab}", f"=COUNTIF({rng('AB')},\"{lab}\")", "", "0")
    r_ += 1

    section("Model configuration")
    for label, value in facts["model_config_lines"]:
        line(label, value)
    r_ += 1
    sm.cell(row=r_, column=2, value="Category definitions and the rubric-to-category mapping are on Run Metadata.").font = F_NOTE

    chart = BarChart()
    chart.type = "col"
    chart.title = "Evaluation outcome (100 questions)"
    chart.y_axis.title = "Questions"
    chart.legend = None
    data = Reference(sm, min_col=3, min_row=hdr_row, max_row=last_cat_row)
    labels = Reference(sm, min_col=2, min_row=first_cat_row, max_row=last_cat_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(labels)
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    chart.height, chart.width = 8, 15
    from openpyxl.chart.series import DataPoint
    s = chart.series[0]
    for idx, cat in enumerate(CATEGORIES):
        pt = DataPoint(idx=idx)
        pt.graphicalProperties.solidFill = {"PASS": "70AD47", PPASS: "A9D08E", PFAIL: "F4B183", FAIL: "E06666", NE: "A6A6A6"}[cat]
        s.dPt.append(pt)
    sm.add_chart(chart, "F4")

    # ------------------------------------------------------------ Sheet 3: Failed and Partial Questions
    fp = wb.create_sheet("Failed and Partial Questions")
    fcols = [("Question ID", 16), ("Question", 50), ("Generated Answer", 70), ("Evaluation Status", 15),
             ("Evaluation Explanation", 60), ("Reference Answer", 60), ("Duration (seconds)", 11), ("Input Tokens", 10),
             ("Output Tokens", 10), ("Recommended Review Action", 55), ("Delivered Answer Type", 22), ("Part (Stratum)", 10)]
    for i, (name, width) in enumerate(fcols, start=1):
        fp.cell(row=1, column=i, value=name)
        fp.column_dimensions[get_column_letter(i)].width = width
    style_header(fp, 1, len(fcols))
    fp.row_dimensions[1].height = 32
    order = {PPASS: 0, PFAIL: 1, FAIL: 2, NE: 3}
    n = 2
    for ro in sorted((x for x in rows_out if x["cat"] != PASS), key=lambda x: (order[x["cat"]], x["q"]["Run Order"])):
        action = (ro["v"] or {}).get("action") or ("Execution failure: inspect serve_ui.log and the measurement record for this "
                                                  "question, then re-run it as a separately labelled attempt.")
        vals = [ro["id"], ro["q"]["Question (ask verbatim)"], (ro["r"] or {}).get("answer"), ro["cat"], ro["why"],
                ro["q"]["Key Answer Elements"], ro["dur"], ro["in"], ro["out"], action, ro["delivered"], ro["q"]["Stratum"]]
        for c, val in enumerate(vals, start=1):
            cell = fp.cell(row=n, column=c, value=val)
            cell.font, cell.alignment, cell.border = F_BASE, WRAP_TOP, BORDER
        fp.cell(row=n, column=7).number_format = "0.000"
        n += 1
    fp.freeze_panes = "C2"
    fp.auto_filter.ref = f"A1:{get_column_letter(len(fcols))}{max(n - 1, 1)}"
    add_status_formatting(fp, "D", 2, max(n - 1, 2))

    # ------------------------------------------------------------ Sheet 4: Run Metadata
    md = wb.create_sheet("Run Metadata")
    md.column_dimensions["A"].width = 34
    md.column_dimensions["B"].width = 120
    md["A1"], md["B1"] = "Item", "Value"
    style_header(md, 1, 2)
    rr = 2
    for key, value in facts["metadata_lines"] + [("Evaluation rubric and category mapping", MAPPING_TEXT)]:
        a, b = md.cell(row=rr, column=1, value=key), md.cell(row=rr, column=2, value=value)
        a.font, b.font = F_BOLD, F_BASE
        a.alignment = b.alignment = WRAP_TOP
        a.border = b.border = BORDER
        rr += 1
    md.freeze_panes = "A2"

    # ------------------------------------------------------------ Sheet 5 (optional): comparison with a baseline run
    comparison = None
    if len(sys.argv) > 3:
        base_dir = Path(sys.argv[3]).resolve()
        b_items = {it["q"]["ID"]: it for it in load_run(base_dir)}
        b_verd = json.loads((base_dir / "scoring" / "verdicts.json").read_text(encoding="utf-8"))
        b_facts = json.loads((base_dir / "scoring" / "run_facts.json").read_text(encoding="utf-8"))
        b_label, n_label = facts["baseline_label"], facts["new_label"]
        rank = {NE: 0, FAIL: 1, PFAIL: 2, PPASS: 3, PASS: 4}
        cp = wb.create_sheet("Comparison vs Baseline")
        ccols = [("Question ID", 16), ("Question", 45), (f"Baseline Status ({b_label})", 15), (f"New Status ({n_label})", 15),
                 ("Change", 12), ("Baseline Delivered Answer Type", 22), ("New Delivered Answer Type", 22),
                 ("Baseline Duration (s)", 11), ("New Duration (s)", 11), ("Baseline Input Tokens", 10), ("New Input Tokens", 10),
                 ("Baseline Output Tokens", 10), ("New Output Tokens", 10), ("Baseline Generated Answer", 60),
                 ("Baseline Evaluation Explanation", 60)]
        for i, (name, width) in enumerate(ccols, start=1):
            cp.cell(row=1, column=i, value=name)
            cp.column_dimensions[get_column_letter(i)].width = width
        style_header(cp, 1, len(ccols))
        cp.row_dimensions[1].height = 42
        comparison = {"Improved": 0, "Regressed": 0, "Unchanged": 0, "baseline_counts": {c: 0 for c in CATEGORIES}}
        for n, ro in enumerate(rows_out, start=2):
            b = b_items[ro["id"]]
            br = b["r"] or {}
            b_exec = br.get("execution_status", "NOT RUN")
            b_cat = category(b_verd.get(ro["id"]), b_exec)
            comparison["baseline_counts"][b_cat] += 1
            change = ("Improved" if rank[ro["cat"]] > rank[b_cat] else "Regressed" if rank[ro["cat"]] < rank[b_cat] else "Unchanged")
            comparison[change] += 1
            b_why = (b_verd.get(ro["id"]) or {}).get("why") or ""
            b_deliv = DELIVERED.get(br.get("fallback_type"), f"Fallback: {br.get('fallback_type')}") if b_exec == "SUCCESS" else ""
            vals = [ro["id"], ro["q"]["Question (ask verbatim)"], b_cat, ro["cat"], change, b_deliv, ro["delivered"],
                    br.get("client_seconds"), ro["dur"], br.get("input_tokens"), ro["in"], br.get("output_tokens"), ro["out"],
                    br.get("answer"), b_why]
            for c, val in enumerate(vals, start=1):
                cell = cp.cell(row=n, column=c, value=val)
                cell.font, cell.alignment, cell.border = F_BASE, WRAP_TOP, BORDER
            for c in (8, 9):
                cp.cell(row=n, column=c).number_format = "0.000"
            for c in (10, 11, 12, 13):
                cp.cell(row=n, column=c).number_format = "#,##0"
        clast = len(rows_out) + 1
        cp.freeze_panes = "C2"
        cp.auto_filter.ref = f"A1:{get_column_letter(len(ccols))}{clast}"
        add_status_formatting(cp, "C", 2, clast)
        add_status_formatting(cp, "D", 2, clast)
        for word, colr in (("Improved", "C6EFCE"), ("Regressed", "FFC7CE")):
            cp.conditional_formatting.add(f"E2:E{clast}", FormulaRule(formula=[f'$E2="{word}"'], stopIfTrue=True,
                                                                      fill=PatternFill("solid", fgColor=colr)))

        # Summary block (formulas over the comparison sheet)
        CPR = "'Comparison vs Baseline'"
        crng = lambda col: f"{CPR}!${col}$2:${col}${clast}"  # noqa: E731
        r_ += 2
        section(f"Comparison with the baseline run ({b_label} → {n_label}, same 100 questions)")
        for c, txt in zip((2, 3, 4), ("Category", f"Baseline ({b_label})", f"New ({n_label})")):
            sm.cell(row=r_, column=c, value=txt)
        style_header(sm, r_, 4)
        sm.cell(row=r_, column=1).fill = PatternFill()
        r_ += 1
        for cat in CATEGORIES:
            sm.cell(row=r_, column=2, value=cat).font = Font(name=ARIAL, size=10, bold=True, color=CAT_FONT[cat])
            sm.cell(row=r_, column=2).fill = PatternFill("solid", fgColor=CAT_FILL[cat])
            sm.cell(row=r_, column=3, value=f"=COUNTIF({crng('C')},\"{cat}\")").number_format = "0"
            sm.cell(row=r_, column=4, value=f"=COUNTIF({crng('D')},\"{cat}\")").number_format = "0"
            for c in (2, 3, 4):
                sm.cell(row=r_, column=c).border = BORDER
            for c in (3, 4):
                sm.cell(row=r_, column=c).font = F_BASE
            r_ += 1
        line("Questions improved (category moved up)", f"=COUNTIF({crng('E')},\"Improved\")", "per-question, Comparison vs Baseline sheet", "0")
        line("Questions regressed (category moved down)", f"=COUNTIF({crng('E')},\"Regressed\")", "", "0")
        line("Questions unchanged", f"=COUNTIF({crng('E')},\"Unchanged\")", "", "0")
        line(f"Baseline strict pass rate ({b_label})", f"=IFERROR(COUNTIF({crng('C')},\"PASS\")/(COUNTA({crng('C')})-COUNTIF({crng('C')},\"{NE}\")),\"\")",
             "baseline PASS ÷ baseline evaluated questions", "0.0%")
        line(f"Baseline pass-or-partially-pass rate ({b_label})",
             f"=IFERROR((COUNTIF({crng('C')},\"PASS\")+COUNTIF({crng('C')},\"{PPASS}\"))/(COUNTA({crng('C')})-COUNTIF({crng('C')},\"{NE}\")),\"\")",
             "", "0.0%")
        line(f"Baseline average question duration (s) ({b_label})", f"=IFERROR(AVERAGE({crng('H')}),\"\")", "", "0.000")
        line(f"Baseline median question duration (s) ({b_label})", f"=IFERROR(MEDIAN({crng('H')}),\"\")", "", "0.000")
        line(f"Baseline total input tokens ({b_label})", f"=SUM({crng('J')})", "", "#,##0")
        line(f"Baseline total output tokens ({b_label})", f"=SUM({crng('L')})", "", "#,##0")
        line("Baseline run", b_facts["run_id"] + " · " + b_facts["run_window"] + " · " + b_facts["base_model_short"],
             "its workbook as first published is preserved in the baseline run directory")
        line("Comparability note", facts["comparison_note"])

    for sheet in wb.worksheets:
        sheet.sheet_view.zoomScale = 100
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)

    counts = {c: sum(1 for x in rows_out if x["cat"] == c) for c in CATEGORIES}
    durs = [x["dur"] for x in rows_out if isinstance(x["dur"], (int, float))]
    ins = [x["in"] for x in rows_out if isinstance(x["in"], int)]
    outs = [x["out"] for x in rows_out if isinstance(x["out"], int)]
    expected = {"counts": counts, "evaluated": sum(v for k, v in counts.items() if k != NE),
                "n_dur": len(durs), "avg_dur": statistics.mean(durs) if durs else None,
                "median_dur": statistics.median(durs) if durs else None, "min_dur": min(durs) if durs else None,
                "max_dur": max(durs) if durs else None, "sum_dur": sum(durs),
                "sum_in": sum(ins), "sum_out": sum(outs), "n_in": len(ins), "n_out": len(outs),
                "avg_in": statistics.mean(ins) if ins else None, "avg_out": statistics.mean(outs) if outs else None,
                "success": sum(1 for x in rows_out if x["exec"] == "SUCCESS"),
                "withheld": sum(1 for x in rows_out if str(x["delivered"]).startswith("Withheld")),
                "live": {lab: sum(1 for x in rows_out if x["live"] == lab) for lab in ("PASS", "FAIL", "NOT EVALUATED", "NOT FULLY EVALUATED")},
                "comparison": comparison}
    (out.parent / (out.stem + "_expected_values.json")).write_text(json.dumps(expected, indent=1), encoding="utf-8")
    print(json.dumps(expected, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
