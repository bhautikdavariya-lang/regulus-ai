# Retrieval repair D, Experiment 2 (one-passage guidance floor): pre-registration

Written before the candidate was implemented or evaluated. This is a diagnostic experiment only: no production
enabling, no database change, no semantic index rebuild, no embedding model, no model inference, no commit or push.

## Candidate (exactly one, default off)
`ContextPolicy.general_evidence_order = "ecfr_discovery_first_guidance_floor"`.

**Scope:** it applies only where the existing eCFR reserve (RC2) applies, meaning a question that names no provision,
no docket and no guidance (`selection._binding_reserve_applies`).

**The soft-budget order is the default tier order with one change in the discovery tier:**
1. the highest-ranked guidance discovery passage, meaning the first guidance passage of the discovery tier in registry
   order (the registry orders discovery evidence by score);
2. then every eCFR discovery passage, in registry order;
3. then the remaining guidance discovery passages, in registry order.

**Unchanged:**
- structural and supporting evidence (guidance that matched every question word included);
- the 1,200-char eCFR reserve;
- every limit: 8 sources, 1,200 chars per source, 3,600 soft total, the hard ceilings;
- the usefulness filter;
- the presented order (registry order);
- retrieval, ranking, query construction, the database, prompts, model settings and answer generation.

**Reference:** experiment 1's archived diff (`../retrieval_selection_d_20261021/candidate_patch/candidate.diff`) is
read for reference only. It is not applied.

## Hypothesis and predictions
- **H.** Keeping the top-ranked guidance discovery passage ahead of the eCFR discovery rows prevents the four
  regressions experiment 1 observed:
  - COS-701.12-Q2 losing the R2 passage on the OTC-drug labeling Q&A (FDA-2007-D-0429);
  - retrieval-031 losing docket FDA-2007-D-0372;
  - retrieval-034 losing docket FDA-2017-D-6821;
  - retrieval-039 losing docket FDA-2013-D-0114.
- **Prediction, stated as uncertain.** The three target paragraphs, 70.55 (COS-70.55-Q1), 71.15(b) (COS-71.15-Q2) and
  701.3(b) (COS-701.3-Q1), **may or may not** fit within the unchanged 3,600-char budget once one guidance passage
  competes ahead of them. A1 and A2 may therefore fail.

## Benchmarks and scripts (same as experiment 1)
**Datasets:**
- 100 cosmetics questions: `artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json`,
  sha256 `0e632288…`.
- 352-row retrieval baseline: `data/evaluation/datasets/retrieval_baseline_v1.jsonl`, sha256 `b0893eb8…`.

**Required paragraphs:** parsed from each verified key as
`artifacts/retrieval_rootcause_20261021/tools/trace_retrieval.py` `required()` does it. A child row counts for its
top-level paragraph. The mis-parsed label 21 CFR 740.11(i) is excluded.

**Database and pipeline:**
- database `regulus`, ecfr identity 65,280 / `4f0457d7…`, guidance `428b3dbd…`;
- production pipeline (`retrieval_baseline.production_pipeline`: configured RagConfig, SemanticFallbackRetriever +
  ScopePolicy) with the stub generator;
- read-only, behind the guarded.py SELECT-only and semantic-loader-refusal guards.

**Scripts:**
- `tools/candidate_run.py`: runs base (`tier`) and candidate in one process over the 100 questions. It records final
  contexts (with text) and required-paragraph status, and builds the A3 pool.
- `tools/evaluate.py`: computes A1, A2, A4 and A7 from the run, and A3 from the labels.
- `scripts/retrieval_baseline.py run --general-evidence-order ecfr_discovery_first_guidance_floor` under guarded.py,
  compared per record with baseline run `retrieval_baseline_20261021T102326Z_16fa796d` (A5).
- Tests: `pytest` default suite, `-m integration` (retrieval_db, section_coverage_live, dropped_source_text_live) and the
  new focused tests (A6).
- The sha256 of every script used is recorded in `RUN_MANIFEST.json` before the evaluation run.

## Acceptance criteria (identical to experiment 1)
Every criterion is required. Each one passes only as stated.
- **A1.** Required paragraphs in the final context, over the general questions of the 100, rise by **≥ 3**, and **0**
  required paragraphs are lost in any question.
- **A2.** 70.55 (COS-70.55-Q1), 71.15(b) (COS-71.15-Q2) and 701.3(b) (COS-701.3-Q1) all enter the context.
- **A3.** **0** guidance passages adjudicated **R2** are removed from any question's context. R1 removals are reported
  and do not fail.
- **A4.** The 12 named-provision questions have identical final contexts (citation, corpus, text length).
- **A5.** On the 352-row baseline, no keyed target goes from in-context to not-in-context, and the summary counts
  (identifier and plain-language in context) are not lower.
- **A6.** The default suite has no failure beyond the 9 pre-existing ones, the integration tests all pass, and the new
  focused tests all pass.
- **A7.** No context without required evidence exceeds 8 sources or 3,600 chars, and selected sources are presented in
  registry order (unit-tested).

## A3 procedure (blind, fixed rubric)
**Rubric:** `../retrieval_selection_d_20261021/RUBRIC.md`, sha256 `fce098c0…`, unchanged.

**Reused labels:** a removed passage already judged in experiment 1, for the same question and the same passage key
and text, keeps its adjudicated experiment-1 label. Those labels were given blind under this rubric.

**Fresh judging** of every removed or added guidance passage not judged before, by the same procedure:
- a pool of the new items plus 20 fillers (guidance kept by both conditions, seed 20261021), shuffled with the same
  seed and unlabelled;
- two independent blind AI judges;
- a blind adjudicator for disagreements;
- labels joined to the key only afterwards.

**Disclosure:** AI-assisted, not SME-validated. A passage is never presumed irrelevant because it is not an answer-key
target.

## Decision (mechanical)
- **Every criterion passes:** **CANDIDATE PASSES — AWAITING EXPLICIT AUTHORIZATION TO ENABLE.** The candidate stays
  default-off and isolated.
- **Any criterion fails:** **FAIL — REMOVE CANDIDATE AND RESTORE BASELINE.** The candidate changes are removed, and the
  source files are restored byte-for-byte from `pre_edit/`.
- **Evaluation incomplete or evidence ambiguous:** **INCONCLUSIVE — KEEP DISABLED.**
- **No waivers, no threshold changes, no second candidate.**
