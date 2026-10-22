# Retrieval repair, Step 1: baseline protection and source-data correction (2026-10-21)

**Decision: PARTIAL.** The source correction is applied, verified and idempotent, with the same test results as before.
One deployment step remains: the semantic index (section 6).

## 1. Workspace and baseline (before any change)
- **Repository:** branch main, HEAD fbd2e60, nothing staged.
- **Pre-existing work, preserved byte-identical (sha256 prefixes):**
  - `artifacts/retrieval_rootcause_20261021/REPORT.md` (modified) 5886ec09;
  - absence_check.json fe1ba933;
  - refined_classes.json 711709f8;
  - tools/absence_check.py e0fa8dea;
  - tools/refine_classes.py 5b374aef.
- **Tracked files:** no tracked file was modified. The diff against 6f94938 for src/scripts/tests/web is unchanged (1bdb467e).
- **Baseline records** ([baseline/](baseline/)):

| Baseline | Result |
|---|---|
| Full suite | 2,717 passed, **9 failed** (pre-existing: answer quality, length policy, validation, traceability, offline evaluation), 1 skipped, 7 xfailed |
| Retrieval unit suites | 484 passed, 1 failed (test_evidence_traceability::test_13, pre-existing) |
| DB integration suites | 46 passed |
| 352-row retrieval baseline (run `retrieval_baseline_20261021T091703Z_08914a7e`) | identifiers 108/119 in context, plain-language 90/157 |
| 100 cosmetics questions | traces_before/ |
| Required-text probe | probe_before.json |
| eCFR corpus identity | 65,264 rows, `9657a55c…` |

## 2. The defect (verified)
**Target database:** `regulus` on local Homebrew PostgreSQL 18.6, localhost:5432 (this Mac). Its rows are all from snapshot
2026-09-03.

**Source:**
- For parts 71, 73, 74, 81, 701 and 740, the XML was fetched from each row's own recorded `source_endpoint`
  (`api/versioner/v1/full/2026-09-03/...`).
- Its sha256 equals the `source_payload_sha256` stored on **every** row of the part (1,954 rows).
- For 701 and 740 it also equals the payload behind the existing local snapshot (`ecfr_2026-10-14`, same xml_sha256).

**Origin: parsing at ingestion.** It is not paragraph splitting or persistence.
- The original ingestion stored each section's `<P>` children: 1,763 of 1,767 are stored, and 4 differ in Part 73
  splitting (out of scope).
- It skipped every `<EXTRACT>` (block quotes: warnings, specification and name lists) and `<FP>` (flush paragraph):
  **0 of 117 and 0 of 17** are stored.
- Lead-ins such as "shall bear the following warning:" are stored; the announced text is not.
- Tables, editorial notes and citations are separate classes and were not touched.

**Rows inspected:**
- The 15 rows the root-cause report flagged, all verified against source.
- **Excluded: 71.1(c).** Its block is an 8,125-character petition form. Stored as one row it would be 2.4× the longest
  row in the corpus, and it would push requested 71.1 paragraphs out of the context. It needs a splitting decision.
- **Added: 701.13 (i)(4).** A dropped `<FP>` in a section that is renumbered anyway, so every repaired section is
  complete.

**Questions whose verified key needs a repaired row:** COS-73.2180-Q1, 73.2250-Q1, 73.2725-Q1, 740.11-Q1, 740.11-Q2
and 740.12-Q1. COS-71.1-Q2 needs 71.1(c), which is excluded.

## 3. The correction
**Tool:** `src/regulus/ingestion/dropped_text.py` with `scripts/repair_dropped_source_text.py` (plan, apply, rollback).
It is repeatable and rerun-safe.

**How a dropped element is stored:** as a row of its anchor's paragraph path with the next `path_ordinal`.
- This is how the original ingestion already stores undesignated text (3,160 rows have `path_ordinal` > 0).
- Section ordinals are renumbered to document order.
- Every other column is copied from the anchor row in SQL: snapshot 2026-09-03, endpoint, payload hash, permalink,
  headings, citation.
- `retrieved_at` is the verified fetch time.
- `content_sha256` follows the corpus's own folding rule, which reproduces 1,954 of 1,954 stored hashes in these parts.
- The embedding is NULL, as on 77 existing rows.

**Safety:**
- A section is planned only if its stored rows account for its source text exactly, in order.
- Apply needs the digest of the exact plan and its provenance, and refuses a read-only connection.
- It re-checks all rows under `FOR UPDATE` in one transaction.
- The rollback manifest is created before, and written inside, that transaction.

**Review:** 3 adversarial reviewers before authorization. The fixes they found were applied:
- the manifest-after-commit gap;
- the hash rule;
- the 71.1(c) length;
- the digest scope;
- the read-only override;
- the inline-join bug;
- the `path_ordinal` order guard.

**Applied (authorized plan `bb95cdff…5454f8d`):**
- 16 rows inserted, in 9 sections.
- 135 existing rows had **only** `ordinal` changed (their `updated_at` was stamped by the table's trigger).
- 0 rows deleted, 0 stored texts altered, no other table touched.
- Manifest: [apply_manifest.json](apply_manifest.json). Backup of the 181 prior rows: [backup_before_apply.json](backup_before_apply.json).

**Before and after, exact text:**

| Row | Before | After (new row, same path, `path_ordinal` 1) |
|---|---|---|
| 740.11(a)(1) | "…shall bear the following warning:" with nothing after it | "Warning—Avoid spraying in eyes. Contents under pressure. Do not puncture or incinerate. Do not store at temperature above 120 °F. Keep out of reach of children." |
| 740.12(b) | "The label of a feminine deodorant spray shall bear the following statement:" | "Caution—For external use only. Spray at least 8 inches from skin. Do not apply to broken, irritated, or itching skin. …" + (b)#2 "The sentence “Spray at least 8 inches from skin” need not be included …" |
| 701.3(c)(2)(i)(c) | "(c) The following names are adopted … until January 19, 1981." | "Amphoteric (all 20 numeric designations) Quaternium (all 49 numeric designations)" |
| 73.2725(b) | "…shall conform to the following specifications…" | "Lead (as Pb), not more than 20 parts per million. Arsenic (as As), not more than 3 parts per million. Mercury (as Hg), not more than 1 part per million." |

All 16 texts equal two independent renderings of the source ([plan_crosscheck.json](plan_crosscheck.json)).

## 4. Validation (after)

| Check | Result |
|---|---|
| Corpus identity | 65,280 rows, `4f0457d7…`, **exactly as precomputed** before applying |
| Rows | 16/16 present, hashes and provenance correct, 0 duplicate (section, ordinal) pairs in the whole corpus |
| Idempotence | A fresh plan finds all 16 already restored and plans nothing |
| New unit tests | 27 passed: transaction, rollback and CLI refusals, hash rule, alignment |
| New live tests | 4 passed (2 failed before the repair, as designed) |
| Existing DB integration tests | 46 passed |
| Full suite | 2,744 passed (2,717 + 27 new), **the same 9 failures as the baseline** |
| Restored text reaches the context, exact-citation questions | **15/15 anchors, 16/16 texts** (before: 0/15) |
| 100 cosmetics questions | 96 contexts identical. Required paragraphs 17 → 18. Gained: 740.11(b) (COS-740.11-Q2), 740.12(b) (COS-740.12-Q1). **Lost: 740.12(a) (COS-740.12-Q1)**. Order or off-key changes only: COS-70.3-Q1 (reordered), COS-82.1254-Q1 (one off-key row swapped) |
| 352-row baseline (run `…095043Z_0bf64f3a`) | 108/119 and 90/157, identical; no keyed-section stage changed. 4 records differ only in recorded row counts or negative-control context mix |

**The one loss is a trade, not a data fault.**
- In COS-740.12-Q1, the restored 740.12(b) caution now outranks (a) under the existing two-rows-per-section limit of
  the section-coverage search (fix B in the root-cause report, out of scope here).
- Of the 7 dependent general questions, 2 now receive the restored text. In the other 5, the anchor paragraph is not
  retrieved at all, which is fixes A, B and C, not this step.

## 5. Changed files (all uncommitted)
**New code and tests:**
- `src/regulus/ingestion/__init__.py`, `src/regulus/ingestion/dropped_text.py`: the repair library (plan, apply,
  rollback).
- `scripts/repair_dropped_source_text.py`: the CLI.
- `tests/test_dropped_source_text.py`: 27 unit tests.
- `tests/integration/test_dropped_source_text_live.py`: 4 live, read-only tests.
- `tests/fixtures/ecfr_part740_20260903.xml`: the hash-verified part 740 payload.

**Evidence:** `artifacts/retrieval_repair_step1_20261021/`.
- Payloads and fetch logs: `source_xml/`.
- Targets and plans: targets.json, plan.json, plan_v1_superseded.json.
- Recon and inventory: recon, inventory.
- Apply records: manifest, backup, expected identity.
- Comparisons: before/after traces, probes, 352-row comparison.

**Database:** cfr_records only, as above. Rollback:
`scripts/repair_dropped_source_text.py rollback --manifest artifacts/retrieval_repair_step1_20261021/apply_manifest.json --authorized-sha256 bb95cdff…`

## 6. What remains (why PARTIAL)
1. **Semantic index, the one deployment step.**
   - `semantic_expanded_v1` covers parts 73/74. Its metadata still holds the old ordinals of the 13 renumbered rows
     there, and the 5 restored rows there are not in it.
   - It still loads, and general questions never use it.
   - Rebuilding it consistently (corpus and vectors together) means running its embedding model, which this programme
     has not authorized.
2. **Not repaired here, known:**
   - 71.1(c), which needs a row-splitting rule;
   - the other 101 dropped EXTRACT/FP elements in these six parts;
   - the same class across the rest of Title 21 (796 lead-in rows without stored continuation in 104 parts).
3. **Readers that order by `path_ordinal`** before `ordinal`: key_verification and three scoring scripts. They will
   list restored rows after all designated paragraphs. This is evaluation tooling, not retrieval.
