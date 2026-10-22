# Fix B measurement (read-only): pre-registration

Written before any run. This measurement is authorized as read-only.
- No production code, prompt, configuration, database or index change.
- No model or embedding model.
- The context budget (8 sources, 1,200 chars per source, 3,600 total, 1,200 eCFR reserve) and the ordering rules
  ("tier") are unchanged.

## What varies (in process only)
The section-coverage leg (`LexicalRetriever.section_coverage_ecfr`, SQL `ECFR_SECTION_COVERAGE`). Its call is
replaced in the harness so that the SQL parameters can vary. The same 4 top-ranked sections are always used, and
nothing else changes.

| Condition | Rows per section | Total rows | Sections |
|---|---|---|---|
| base (production) | 2 | 4 | 4 |
| F1 | 4 | 8 | 4 |
| F2 | 8 | 16 | 4 |

## Benchmarks (as in the earlier experiments)
- **100 cosmetics questions** (`selection.json` `0e632288…`). Required paragraphs come from the verified keys via
  `trace_retrieval.required`; 21 CFR 740.11(i) is excluded.
- **352-row baseline** (`retrieval_baseline_v1.jsonl` `b0893eb8…`):
  - base = run `retrieval_baseline_20261021T102326Z_16fa796d` (same code and database identity);
  - F1 and F2 run with `retrieval_baseline.run_question`.

## Measures
1. **Candidate-level recall:** required paragraphs present in the evidence registry (100 Qs), and keyed targets with a
   candidate rank (352). Gains and losses are listed per question.
2. **Final-context recall:** required paragraphs and keyed targets in the final context. Gains and losses are listed
   per question.
3. **Survival:** of the required paragraphs that become candidates only under F1 or F2, how many reach the final
   context, and why the rest are dropped (soft budget, max_results, filtered…).
4. **Displacement:**
   - guidance passages present in base but not in the variant;
   - eCFR rows present in base but not in the variant;
   - any keyed target lost.

## Acceptance criteria (fixed)
A variant is **WORTH A CODE EXPERIMENT** only if all of these hold:
- **B1.** Final-context required paragraphs (100 Qs): **≥ +3 gained and 0 lost.**
- **B2.** 352: **0 keyed targets lost**, and the in-context summary counts (identifier and plain-language) are not lower.
- **B3.** **0 guidance passages** present in the base context are removed (100 Qs).
- **B4.** **0 eCFR rows** present in the base context are removed, unless the same required paragraph is still in the
  context.

If candidate-level recall rises but B1–B4 fail, the result is **CANDIDATES ONLY**: Fix B's gains do not survive the
current selection. Otherwise the result is **NO GAIN**.

This step only measures and recommends. It implements and enables nothing.
