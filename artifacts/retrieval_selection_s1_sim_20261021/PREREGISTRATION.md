# S1 offline simulation: pre-registration (written before any run)

**Authorization:** the S1 offline simulation of `../retrieval_selection_design_20261021/REPORT.md` §5–§6, both arms,
and nothing else.
- No change to production code, retrieval behaviour, prompts, configuration, database, indexes or model.
- No inference or embedding model.
- The acceptance criteria and the regression set are the report's §6 (E1–E6), used unchanged. This file only fixes the
  implementation details the report left open, before any run.

## Simulation mechanics (in process only)
- The production pipeline (`retrieval_baseline.production_pipeline`, stub generator) behind guarded.py: SELECT-only,
  semantic loader refused.
- `regulus.rag.pipeline.select_evidence` is replaced **in memory** by a copy of `selection.select_evidence`. In the
  copy, only the soft-budget phase is changed, and only when `_binding_reserve_applies(registry)`. Required, material
  and reserve phases, limits, filter and drop reasons are the original code.

## S1 rule (as in the report)
1. **Weights:** the question's lexemes are `to_tsvector('english', ' '.join(query.content_terms(question)))`. Each is
   weighted `ln(max(N_sections / df, 1))`, where df is the number of live, non-reserved cfr_records sections matching
   the lexeme, the same weighting as `sql.ECFR_SECTION_COVERAGE`. A lexeme with no match gets `ln(N_sections)`.
2. **A candidate's lexemes:** `to_tsvector('english', text as presented, i.e. cleaned and cut to 1,200 chars, + ' ' +
   citation label)`.
3. **Initial coverage:** the union of the lexemes of everything already selected before the soft-budget phase
   (required, material, reserved).
4. **Greedy step:** among the remaining candidates that pass the usefulness filter (structural evidence exempt, as
   today), fit **whole** within 3,600 chars, and leave the source count under 8:
   - take the highest **marginal value / block chars**, where marginal value is the summed weight of question lexemes
     not yet covered;
   - only candidates with value > 0 qualify;
   - ties go to the earlier position in today's order (`_optional_order`).
   - Repeat while a candidate qualifies.
5. **Fill:** then today's loop runs unchanged over the candidates not yet taken. It squeezes or drops exactly as today.
6. **Presentation:** selected optional sources are re-sorted into registry order, as the reserve path does.

## Arms
- **S1:** today's candidates.
- **S1+F2:** the section-coverage leg returns up to 8 rows per section and 16 in total from the same 4 sections. This
  is the instance-level replacement used in the read-only F2 measurement, in process only.

## Comparison
- **100 cosmetics questions:** base (production) is run in the same process.
- **352 rows:** base is run `retrieval_baseline_20261021T102326Z_16fa796d`. The arms are run with
  `retrieval_baseline.run_question`.

## Criteria (report §6, unchanged; each arm judged separately)
- **E1.** Cosmetics required paragraphs ≥ +3, 0 lost.
- **E2.** 352: 0 keyed targets lost; identifier and plain-language in-context counts not lower.
- **E3.** Every guidance passage or regulation row removed from a base context, **in the 100 cosmetics questions and in
  the 352 rows**, is judged blind. Existing labels are reused for an identical question, key and text: experiment D's
  guidance labels and F2's regulation-row labels. **0 R2 removed.**
  - **Procedure:** RUBRIC.md for guidance, RUBRIC_ECFR.md for regulation rows; two independent AI judges plus a blind
    adjudicator on disagreement; new items pooled with an equal number of kept-passage fillers, shuffled with seed
    20261021.
- **E4.** Regression set:
  - COS-74.2602a-Q1 keeps 81.30(i);
  - COS-701.12-Q2 keeps the OTC-drug Q&A passage (FDA-2007-D-0429);
  - X-001 keeps 4.1;
  - retrieval-031, -034 and -039 keep their guidance dockets;
  - COS-740.11-Q2 keeps 740.11(b)(1) (the restored warning row);
  - COS-70.3-Q1 keeps 70.3(f);
  - COS-740.12-Q1 keeps 740.12(b), and keeps 740.12(a) if base had it.
- **E5.** Named-provision, docket and guidance questions have identical contexts (100 Qs and 352 rows).
- **E6.** Limits and presented order are unchanged, and selection is deterministic: the S1 arm is run twice on the 100
  questions with identical results.

**Decision per arm:** PASSES (merits a separate implementation proposal) or FAILS, reported as measured. No fallback
change, no threshold change, nothing implemented or enabled.
