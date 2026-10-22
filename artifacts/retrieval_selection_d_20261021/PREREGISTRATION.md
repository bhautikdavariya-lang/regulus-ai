# Retrieval repair D (context selection): pre-registration

Written before the candidate was run on any benchmark question and before any relevance judgement.

## Candidate (exactly one)
`ContextPolicy.general_evidence_order = "ecfr_discovery_first"`.
- It applies only to a question that names no provision, no docket and no guidance.
- Within the discovery tier, every eCFR passage competes for the soft budget before every guidance passage, each in
  registry order.
- Unchanged: structural and supporting evidence (guidance that matched every question word included), the RC2 1,200-char
  eCFR reserve, every limit (8 sources, 1,200 chars per source, 3,600 total), the usefulness filter, and the presented
  order (registry order).
- **Code (default still "tier"):** selection.py `ba1665db…`, context.py `9e0bdeed…`; tests
  `tests/test_selection_ecfr_discovery_first.py` `aa29ea65…`.
- **Pre-edit copies:** `pre_edit/selection.py` `2470fb2b…`, `pre_edit/context.py` `0123fe6e…`.

**Comparator, not a candidate:** "all tiers, eCFR first" (the root-cause report's D simulation, harness only). It is
run only so that the passages it displaces (the "97") can be judged as well.

## Baseline (recorded, `baseline/`)
- **Database:** `regulus` (local Homebrew PostgreSQL 18.6), repaired corpus 65,280 rows, identity `4f0457d7…`.
- **Pipeline:** production (configured RagConfig, SemanticFallbackRetriever over LexicalRetriever, ScopePolicy), with
  a stub generator.
- **100 cosmetics questions** (`baseline/traces`): 18 of 174 required paragraphs of the general questions are in the
  context. 3 are dropped at the soft budget: 70.55 (COS-70.55-Q1), 71.15(b) (COS-71.15-Q2) and 701.3(b) (COS-701.3-Q1).
- **352-row baseline:** run `retrieval_baseline_20261021T102326Z_16fa796d`; identifiers 108/119 and plain-language
  90/157 in context.
- **Tests:** full suite 2,744 passed, 9 failed (pre-existing; list in `baseline/pytest_failed.txt`); integration
  50 passed.

## Relevance assessment (blinded)
**Pool:** every guidance passage that is in the baseline context but not in the candidate's, or the reverse, for any
of the 100 questions.
- The same applies for the comparator.
- Plus 40 guidance passages that are in both contexts, sampled with seed 20261021, as fillers.

**What a judge sees per item:**
- the question;
- the guidance document title;
- the passage text exactly as it appears in its context (baseline text for removed and filler items, candidate text
  for added items).

Items are shuffled with seed 20261021. No item carries a label of removed, added, filler, baseline or candidate.

**Judges:**
- Two independent AI judges (Claude subagents, blind, same RUBRIC.md `fce098c0…`) label every item R2, R1 or R0.
- Disagreements go to a third blind adjudicator.
- The labels are joined to the key only after adjudication.
- This is AI-assisted and not SME-validated, and is reported as such.

## Acceptance criteria (all must hold; candidate vs baseline, same questions, corpus and criteria)
- **A1. Required paragraphs.** Required paragraphs in the final context, over the general questions of the 100,
  rise by **≥ 3**, and **0** required paragraphs are lost in any question.
- **A2. Targets.** 70.55 (COS-70.55-Q1), 71.15(b) (COS-71.15-Q2) and 701.3(b) (COS-701.3-Q1) enter the context.
- **A3. Relevant guidance.** **0** guidance passages adjudicated **R2** are removed from any question's context. R1
  removals are reported but do not fail.
- **A4. Scope.** The 12 named-provision questions have identical final contexts (citation, corpus, text length).
- **A5. 352-row baseline.** No keyed section goes from in-context to not-in-context, and the summary counts are not
  lower.
- **A6. Tests.** No new failure against the 9 pre-existing; all integration tests and the new tests pass.
- **A7. Budget.** No final context exceeds the soft budget for optional evidence (3,600 chars total when no required
  evidence) or 8 sources, and selected sources stay in registry order.

## Decision rule
- **All of A1–A7 hold: PASS.**
  - `ContextPolicy.general_evidence_order` defaults to "ecfr_discovery_first".
  - The full validation (100-question trace, 352-row baseline, full tests) is re-run on the default.
- **Any criterion fails: FAIL.**
  - The default stays "tier", the source files are restored from `pre_edit/`, and the patch is kept in the artifacts
    only.
  - The blocker is reported with the smallest safe next experiment.
- **No iteration.** No second candidate is tried in this task.
