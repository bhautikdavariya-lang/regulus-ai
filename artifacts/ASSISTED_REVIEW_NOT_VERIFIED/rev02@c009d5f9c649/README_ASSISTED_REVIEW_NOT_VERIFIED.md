# ASSISTED REVIEW — NOT VERIFIED

**An offline package to help the SME review the Regulus AI Acceptance Benchmark
Rev 02 (300 questions, workbook sha256 `c009d5f9c649…`, 76,773 bytes).**

Everything here is an **AI-assisted proposal** for a human subject-matter expert.

- **Nothing here is an SME decision.** Nothing was written to the authoritative
  review store (`artifacts/benchmark_keys/…/review/`), no row was marked
  VERIFIED, and no locked key exists.
- **The workbook is unchanged.** `10_integrity_check.json` records the before
  and after hashes.
- **This package must never be consumed by scoring or training.** No code in
  `src/`, `scripts/`, `tests/` or `configs/` references it. The gate only looks
  for `*/locked/*/locked_key.json` under `artifacts/benchmark_keys`, which cannot
  match anything here.
- **The package contains the benchmark's questions.** Treat it as held-out test
  material: never copy it under `data/` or into any training corpus.

## Contents

| File | What it is |
|---|---|
| `01_master_review_table.csv` | All 300 rows: the draft key, the proposal, judgments, confidence, rationale, evidence references, research items, the second-review flag and external sources, plus **blank `SME_…` columns** for your decision. UTF-8; opens in Excel. |
| `01_master_review_table.html` | The same table as a self-contained offline page, with filters and each row's verbatim eCFR quotes. It is not published anywhere. |
| `02_proposals_full.jsonl` | The complete machine-readable proposal for every row. |
| `03_second_review_queue.csv` | 145 rows for independent second review, in priority order: X-004 first, then the mandated sets, then CORRECTED, then NEEDS_RESEARCH. |
| `04_unresolved_research_queue.csv` | 77 NEEDS_RESEARCH rows, each with the specific item to establish and the source it needs. |
| `05_X-004_review_packet.md` | X-004: what the snapshot holds, a verification checklist and the proposed disposition. |
| `06_ISO_conflict_packet.md` | The 23 ISO conflicts by evidence tier, plus the other ISO-bearing rows. |
| `07_negative_control_packet.md` | The 22 negative controls. The 15 absence claims are marked, and each result is labelled as structural absence, positive contrary evidence, or no result. |
| `08_summary_statistics.json` | Counts, row-ID lists and the workload model. |
| `09_systematic_findings.md` | Patterns that suggest systematic problems in the key. |
| `10_integrity_check.json` | Part 7 checks: workbook, gates, decisions, sign-off, locked key. |
| `evidence/`, `batches/`, `pass2/`, `proposals/`, `tools/` | Provenance: raw evidence, reviewer inputs and outputs, the rubric and the scripts. |

## How the proposals were made

1. **Evidence.** Everything was read from the eCFR snapshot of **2026-09-03**
   (65,341 live records), over a connection that refuses to run unless the server
   reports it read-only. This covers:
   - the full text of every cited provision, with section ranges expanded;
   - structure: subparts, section lists and reserved ranges;
   - cross-references and the internal ISO crosswalk and clause index
     (identity only);
   - targeted synonym searches for the absence claims;
   - the project's FDA guidance table.
2. **First pass.** 200 standard rows went to 13 reviewers working under one
   rubric (`tools/REVIEW_RUBRIC.md`). The coordinator reviewed the 100
   judgment-heavy rows: Part 820 and ISO, negative controls, temporal, scope and
   platform behaviour, statute-level and part-level keys, X-003 and X-004.
3. **Second pass.** 65 rows were left open because the answer sat in an uncited
   section whose text wasn't yet in evidence. That text was retrieved and the rows
   re-decided (`tools/PASS2_INSTRUCTIONS.md`).
4. **Anti-fabrication checks.**
   - **All 928 element quotes were machine-checked** as verbatim substrings of
     evidence saved in this package.
   - Column G/J was never treated as evidence for itself.
   - General knowledge appears only as a labelled research lead.
   - **No ISO 13485 text is held in the system, and none was consulted or
     reproduced.**

## Reading a row

| Field | Values |
|---|---|
| `proposed_decision` | ACCEPTED · CORRECTED · REJECTED · NEEDS_RESEARCH (the system's own vocabulary) |
| `proposed_corrected` | The proposed replacement citation or ISO clause. **It is not applied anywhere.** |
| `proposed_substantive` / `proposed_completeness` | correct · partially_correct · incorrect |
| `iso_tier` | `T1_CFR_TEXT` (the CFR paragraph names the clause) · `T2_CORROBORATED` (internal crosswalk and index title agree; the controlled copy is still required) · `T3_UNRESOLVED` · `NONE_CLAIM` · `RANGE` |
| `absence_established` | True only where the search scope was complete, or where the text affirmatively contradicts the premise. Otherwise the result is "no result found". |
| `external_sources` | The source the SME must consult outside this system. It is derived from the research items by keyword, so treat it as a pointer. |
| `human_review_required` | True for **every** row. No automated path reaches VERIFIED. |

## Suggested order of work

1. **Before any volume:** settle the policy questions in
   `09_systematic_findings.md` §1, §3, §4 and §5. They decide dozens of rows at
   once.
2. **X-004**, using `05_X-004_review_packet.md`.
3. **The ISO batch**, with the controlled copy open (`06_…`, 38 rows need it).
4. **Negative controls** (`07_…`).
5. **The rest by domain:** confirm or overturn each proposal and fill in the
   `SME_…` columns.
6. **Record decisions only through the controlled tool**, for example:

   ```
   python scripts/review_benchmark_key.py decide <ID> --state … --reviewer "Name, Title" …
   ```

   The CSV is a worksheet. The tool is the record.
7. **Research queue**, then second review, then sign-off.
