# Fix B / F2 code experiment: pre-registration

Written before implementing or running the candidate. The authorization covers a default-off code experiment only:
- no change to the context budget, the answer-generation prompt, model configuration, database or indexes;
- no embedding model and no model inference;
- no commit or push.

## Candidate (default off)
An environment switch `REGULUS_SECTION_COVERAGE_WIDE=1`, read in `src/regulus/retrieval/lexical.py`, on the same
pattern as `REGULUS_ECFR_LITERAL_OR`.
- **When on,** the section-coverage leg (`section_coverage_ecfr`) returns up to **8 rows per section and 16 rows in
  total**, instead of 2 and 4, from the same 4 top-ranked sections (`coverage_slots = top_k // 2`).
- **Unchanged:** everything else, including the SQL, the ranking, the registry order (coverage rows still placed
  last), selection, the context budget (8 sources, 1,200, 3,600, 1,200 reserve) and the prompts.
- `system_identity` records the switch only when it is on, so the default fingerprint is unchanged.
- **Unset (the default),** behaviour must be byte-identical to today.

## Benchmarks and comparison (same as the read-only measurement)
- **100 cosmetics questions** (`selection.json` `0e632288…`; required paragraphs via `trace_retrieval.required`,
  21 CFR 740.11(i) excluded). Base and candidate are run in one process; the candidate has the switch on.
- **352-row baseline** (`retrieval_baseline_v1.jsonl` `b0893eb8…`).
  - Base is run `…16fa796d`.
  - The candidate is run with `scripts/retrieval_baseline.py run` under guarded.py, with the switch set in the
    environment of that process only.
- **Expected outcome:** the read-only measurement predicts +3 required paragraphs, 352 +3, and 0 lost.

## Required criteria (every one must pass)
- **C1.** Cosmetics final context: required paragraphs **≥ +3 and 0 lost**.
- **C2.** 352: **0 keyed targets lost**, and identifier and plain-language in-context counts not lower.
- **C3.** **0 guidance passages** present in the base context are removed (100 Qs).
- **C4. Previously successful evidence preserved:**
  - every required paragraph and keyed target in context at base is still in context;
  - every regulation row removed from a base context is judged blind and **0 are R2** (rubric `RUBRIC_ECFR.md`).
    The judging uses two independent AI judges plus a blind adjudicator, with a pool of the removed rows plus an equal
    number of added and kept rows as fillers, shuffled with seed 20261021. It is AI-assisted, not SME-validated.
- **C5.** The 12 named-provision questions have identical final contexts.
- **C6. Context budget unchanged:** no context without required evidence exceeds 8 sources or 3,600 chars.
- **C7. Default off is byte-identical:**
  - with the switch unset, the 100-question contexts equal base;
  - the existing default suite passes except the 9 pre-existing failures;
  - all integration tests pass.
- **C8. New regression tests pass.** They cover section coverage (row caps and parameters), ranking (coverage rows
  still placed last, in order), source limits, and preservation of previously returned rows (a live, read-only test:
  default rows are a subset of wide rows for the sampled questions).

## Decision
- **All of C1–C8 pass:** **CANDIDATE PASSES — LEFT DISABLED, AWAITING SEPARATE AUTHORIZATION TO ENABLE.**
- **Any criterion fails:** **FAIL.** The candidate is removed, and lexical.py and system_identity.py are restored
  byte-for-byte from `pre_edit/`. Added tests are archived.
- **Evaluation incomplete or ambiguous:** **INCONCLUSIVE — KEEP DISABLED.**
- No waivers and no threshold changes.
