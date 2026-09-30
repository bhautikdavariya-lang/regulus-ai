# Stage 6: Generation Quality Engineering

Dates: 2026-09-29 to 2026-09-30.

Question asked: can Qwen3-0.6B reliably turn verified regulatory evidence into complete, correctly
qualified, correctly cited answers, and where it cannot, is the cause the model or the pipeline around it?

Measured numbers only. *Developer review* is not SME review. Nothing here was trained or fine-tuned;
the model, weights, database, benchmark, retrieval, gate, validation and citation checking are unchanged.

## Summary

| | Stage 5 (baseline) | Stage 6 |
|---|---:|---:|
| PASS / FAIL, automatic + carried reviews | 45 / 16 | **47 / 14** |
| PASS / FAIL, developer-reviewed (S5-101 corrected in both, see §4) | 44 / 17 | **46 / 15** |
| Stage 4 protected PASS set still PASS | 39/39 as recorded (38 true, S5-101 was a review error) | 39/39 (same 38 + S5-101, unchanged answer) |
| New regressions | — | **0** (every changed answer reviewed) |
| Deterministic repeats | 10/10 | 10/10 |
| Median latency per generated question (p90) | 13.9 s (53.1) | 12.1 s (49.8) |
| First token, median | 2.00 s | 1.68 s |
| Prompt tokens, median | 1,441 | 1,326 |

**The improvement is real but small: 2 questions fixed** (S5-031, AS-02) and several answers cleaner
(S5-111, S5-084, S5-030/AS-07, S5-001/S5-110).

**The main result is diagnostic.** Across 11 prompt and context representations, including the
exact-evidence-only condition, **9 of the remaining failures persist under every representation tried**.
Every representation change that fixed one answer broke another.

**The change does not reach the 300-question benchmark** (§3): its questions are part-level or general.

## Method

* **Baseline.** Stage 5 final run `artifacts/diagnostics/stage5_final_20260929T093254Z`, with its developer review.
* **Failure matrix.** `scripts/generation_matrix.py` produces
  `artifacts/generation_quality/matrix_stage5_final_….jsonl` (baseline) and `matrix_stage6_final.jsonl`. For every
  failing question it lines up the following, using the keyed expectation of `diagnostic_v1` (not edited):
  * the evidence given to the model;
  * the raw output (A);
  * the exact-evidence-only output (B, the controlled condition);
  * validation, repair, fallback and the final answer;
  * whether each missing keyed element exists in the evidence.
* **Representation experiments.** `scripts/generation_experiments.py` runs the same model on the same
  retrieved evidence with a different package or prompt:
  * every prompt is hashed and generated once, and greedy decoding makes identical prompts give identical
    outputs;
  * the base variant reproduces the Stage 5 prompts hash for hash;
  * each output is validated against its own package and scored against the key;
  * the harness covers all 63 generated diagnostic questions and 11 variants (`artifacts/generation_quality/experiments_*`).
* **A/B.** A full 79-question run under the final code is `stage6_final_20260929T110502Z`, with 10 determinism
  repeats. Questions whose prompt a later code refinement changed were re-run through the full pipeline.
  `scripts/prompt_diff.py` verifies that every other prompt is hash-identical. The merged result is
  `artifacts/diagnostics/stage6_result_final_20260930T040757Z` (see its PROVENANCE.md);
  `scripts/compare_runs.py` compares it with the baseline.

## 1. What are the remaining generation failures?

There are 18 failing questions (FAIL + UNVERIFIED_WITH_FAILURES, developer-reviewed), plus 2 NEEDS_REVIEW.

| Group | Questions | What goes wrong |
|---|---|---|
| Omitted content | S5-006 (drops "validation"), AS-06 (drops the "significant injury" condition), S5-091 | an element in the evidence is left out |
| Qualifier errors | AS-01 ("if applicable" moved to the wrong item), S5-010 ("as appropriate" dropped), S5-053 (affirms a false premise, "annual audits"), BM-S-019 | a condition is lost, moved or invented |
| Attribution errors | S5-101 (rows carry another paragraph's text), S5-012, S5-100, BM-F-002 | text or citations attached to the wrong provision |
| Omitted conditions and an invented qualifier, **not caught by validation or the key** | S5-007 | see §4 |
| Degenerate or repetitive output | S5-024 (lead-in provision), BM-S-001 | the model loops; the answer is withheld or repaired |
| Not generation | S5-061 and S5-090 (retrieval), S5-080 and S5-082 (scope policy) | see §4 |

## 2. Which failures are caused by what?

For each failure, the classification uses the exact-evidence condition plus up to 6 distinct prompts
(`artifacts/generation_quality/variant_outcomes_remaining_failures.json`). "Clean" means valid, keyed-complete,
and free of any qualifier or citation finding.

| Cause | Questions | Evidence |
|---|---|---|
| **Model capability** | S5-006, S5-010, S5-012, S5-053, S5-091, S5-101, AS-01, AS-06, BM-S-019 (9) | no representation produced a clean answer, including exact evidence only (2–6 distinct prompts each) |
| **Prompt construction** (a fix exists but regresses other questions) | S5-100 (clean only when the enumeration plan line gives a count instead of a copyable item list), BM-F-002 (clean only with conditions inlined per source) | both variants regress as many questions as they fix (§3) |
| **Evidence packaging** | S5-024 (clean with exact evidence only; kept on the Stage 5 context by the fragment safeguard) | §3 |
| **Answer planning** | S5-091: a "focus on the reference target" plan was tried live and made it worse (the model echoed requirement ids, "r1:", "r2:") | reverted |
| **Validation** | S5-007, S5-101, uncited answers (§4) | errors not detected |
| **Repair** | none new; failed-repair safety held (no ungrounded repair shown) | Stage 5 fallback unchanged |
| **Retrieval / evidence absent** | S5-061, S5-090 | §4 |
| **Scope policy** | S5-080, S5-082 | §4 |

## 3. How much did Stage 6 improve?

### The one change adopted

**Exact-evidence context** (`RagConfig.optional_context = "incomplete_only"`, the default; `"always"`
restores Stage 5; fingerprint v4).

When every requested provision has exact evidence, the prompt carries only the required evidence. Related
supporting and discovery sources, and parents or children that weren't requested, are left out.

This is **not applied** in two cases:
* **comparisons.** A comparison contrasts each side's applicability, which lives in the surrounding paragraphs.
  AS-05 overstated a provision's scope without them.
* **any requested provision whose text is not a complete sentence.** That covers a lead-in ending in ":"
  or a chained fragment like "…; or, in the absence thereof,". Without their context, S5-011 lost its content,
  S5-032 gained an invented completion, and S5-101 misattributed more rows.

### Representation experiments

63 generated questions; the key covers 51.

| Variant | Valid | Keyed complete | Qualifier warnings | Citation errors | Enumeration errors | Unsupported | Median prompt chars |
|---|---:|---:|---:|---:|---:|---:|---:|
| base (Stage 5) | 45 | 43 | 9 | 17 | 6 | 1 | 4,135 |
| h1: exact evidence only | 50 | 47 | 8 | 13 | 5 | 0 | 2,314 |
| h1 + h2: item count, not item list | 49 | 47 | 7 | 15 | 5 | 1 | 2,240 |
| h1 + h3: conditions inline per source | 49 | 48 | 5 | 13 | 6 | 0 | 2,356 |
| h1 + h2 + h3 | 46 | 47 | 2 | 17 | 6 | 1 | 2,282 |
| h1s: drop only supporting/discovery | 45 | 44 | 8 | 15 | 6 | 1 | 3,149 |
| h1r: + children the text references | 49 | 46 | 9 | 13 | 6 | 0 | — |
| h1p: + parents | 49 | 46 | 8 | 13 | 5 | 1 | 2,740 |
| h1c: + children of lead-ins | 48 | 45 | 8 | 14 | 6 | 0 | 2,778 |
| h1f: h1c + parents of fragments | 47 | 45 | 8 | 14 | 6 | 0 | 3,149 |
| **h1w: adopted** (h1 only for complete sentences, not comparisons) | **47** | **45** | 8 | 16 | 6 | 0 | 3,931 |

**Why h1 was not adopted as-is.** h1 scores best on every automatic count, yet developer review found that it
harmed four answers in ways validation and the key do not detect:
* AS-05 overstated scope;
* S5-011 lost its content;
* S5-032 invented a completion;
* S5-101 misattributed a third row.

Each regression was investigated. Adding back the right context piece by piece (h1r, h1p, h1c, h1f) fixed
one answer and broke another every time. h1w keeps the Stage 5 prompt, byte-identical, wherever the
evidence is fragmentary, so no answer is worse than Stage 5. The price is two h1 gains: S5-024, and S5-007,
which developer review failed anyway.

**Why h2 and h3 were rejected.** Per-question, h3 cleared qualifier warnings on AS-01, BM-S-019 and
BM-NC-003, but the same answers gained citation or coverage errors. h2 fixed S5-041 and S5-100 but
introduced citation gaps on S5-030, S5-031 and AS-07. The 0.6B model trades one property for another
instead of holding both.

### Before and after, full pipeline

79 questions. Counts are questions with a proven or probable record.

| Measure | Stage 5 | Stage 6 |
|---|---:|---:|
| Unsupported generation, raw (F07) | 3 | 2 |
| Unsupported reaching the final answer (F07 major) | 1 | 1 |
| Critical failures | 2 | 2 |
| Citation failures, F09 (major) | 17 (9) | 16 (9) |
| Qualifier failures, F08 (major) | 9 (6) | 8 (6) |
| Completeness failures (F15) | 6 | 4 |
| Enumeration incomplete (initial validation) | 2 | 2 |
| Safe-fallback failures (F13/F20) | 2 | 2 |
| Degenerate or truncated generation (F18) | 5 | 4 |
| Model capability, controlled condition (F16) | 7 | 7 |
| Generation calls / blocked by the gate | 63 / 16 | 63 / 16 |
| Deterministic repeat rate | 10/10 | 10/10 |

### Where it applies

* **Diagnostic set:** 20 of the 63 generated questions get the smaller context; for 12 more it is withheld by
  the safeguards.
* **300-question acceptance benchmark: 0.**
  * 168 questions are general;
  * 17 have a requested provision that was not found;
  * 112 of the remaining 115 are **part-level** ("21 CFR Part 111"). Their evidence is entirely protected
    passages of the part, with nothing optional to leave out, and those passages are mostly fragments.

  Stage 6 therefore does not change any benchmark answer.

## 4. Which failures remain unsolved?

* **Model capability: 9 questions** (§2). Omissions, qualifier drift and misattribution persist even with exact
  evidence only.
* **Validation gaps.** These errors reach users while validation passes the answer:
  * **Row misattribution** is only a `low_overlap` warning. S5-101 puts 101.54's text under 101.3(b)(2); a
    row-by-row check against the sources shows 2 of 6 rows wrong in Stage 5 and Stage 6.
  * **Omitted conditions and invented qualifiers** go undetected. S5-007 drops the (a)(1)/(a)(2) reporting
    conditions and adds "If applicable, … devices that pose a risk to health"; the key and validation both
    pass it.
  * **Uncited answers can pass.** 25 valid experiment outputs had no citation marker, from 5 distinct
    questions: S5-062, S5-081, BM-S-015, BM-S-017 and BM-PB-006. S5-081 is a correct "not enough information".
    A "no citation means invalid" rule would turn the protected PASS S5-062 into a withheld answer, so it was
    **not** changed in Stage 6.
  * **Applicability overstatement** ("applies to class I, II and III" instead of the listed class I devices)
    is not a qualifier phrase the validator knows.
* **S5-061** (safe decline): the evidence doesn't contain what a UDI must contain. The four retrieved sources
  are exceptions and guidance excerpts, and the model degenerates. Withholding the answer is correct. The gap
  is retrieval.
* **S5-090**: the gate is correct to block it. The planner reads "part 803" (the thing *referred to*) as the
  requested provision, so retrieval fetches part 803 by identity (26 exact rows, no text search). The answer,
  21 CFR 820.10(b)(3), was never a candidate, and a plain text search with the reference as a search term
  doesn't find it either (top results are unrelated guidance). Fixing this needs a reverse cross-reference
  lookup, which is retrieval work and out of scope.
* **S5-091** (answerable, the model fails): it fails with exact evidence and under 4 prompts. A focused answer
  plan made it worse.
* **General knowledge (S5-080, S5-082).**
  * *Signal found:* every general-knowledge question and both out-of-domain probes (BM-PB-001, BM-PB-006)
    retrieved only through the OR-fallback.
  * *Why it isn't a rule:* one genuine regulatory question did too (BM-S-017). A block rule would be right
    5 times in 6 and would refuse a real question.
  * *Result:* the signal is documented, and no classifier was built; the product boundary is a policy decision.
* **Review correction.** The Stage 4 developer PASS for S5-101 was wrong. The answer, unchanged since Stage 4,
  was already misattributed, so Stage 5's reviewed count is 44 PASS, not 45. This was found by the stricter
  row-level review in Stage 6.

## 5. Can Qwen3-0.6B reasonably support the current product requirements?

**For single-provision lookups, largely yes.** Questions of the form "What does 21 CFR X(y)(z) require?" pass
consistently, with or without the Stage 6 change.

**For the rest of the product, no, not without supervision.** The controlled experiments show:
* with exact, sufficient evidence, the model still fails **9 questions** under every representation tried;
* **every representation that fixed one property broke another**, in 7 of 7 refinement attempts (h2, h3, h1r,
  h1p, h1c, h1f, and the S5-091 answer plan);
* its errors are the costly kind for regulatory QA, and several pass validation:
  * conditions dropped or attached to the wrong requirement;
  * a provision's text attributed to its neighbour;
  * applicability overstated;
  * a false premise affirmed.

The Stage 5 gate and fallback keep unsupported values and irrelevant quotations out. They cannot catch a
fluent answer that states real text under the wrong provision.

## 6. What should Stage 7 be?

**Recommendation: Stage 7 — stronger base model evaluation, with validator hardening.**

* **The data points at model capability.** It is the largest cause (9 of 18) and survives every prompt and
  context representation. More prompt architecture has shown diminishing, trade-off returns. Fine-tuning a
  0.6B model is possible but slower to evaluate.
* **Stage 6 built the decisive experiment already.** `generation_experiments.py` reruns any generator on
  identical evidence and scores it the same way. Next steps:
  * run a larger model from the same family that fits the 8 GB M2 (for example Qwen3-1.7B, or 4B quantized)
    through it, together with the full diagnostic run;
  * measure how many of the 9 capability failures remain, plus latency and memory.
* **If a larger model is infeasible or doesn't help,** fine-tuning or PEFT becomes the next candidate. The
  failure matrix gives it a targeted objective: attribution, qualifier retention, and not affirming premises.
* **Validator hardening should go alongside, not after.** It needs row-to-source attribution, uncited-answer
  handling with a decision on S5-062-type answers, and applicability overstatement. Three errors in this stage
  were visible only to developer review; stronger validation protects users whatever the model.
* **Not recommended as the next step:** retrieval work. S5-061 and S5-090 are real retrieval gaps but only 2 of
  18 failures. It's worth a later stage, together with part-level retrieval, which dominates the benchmark.

**STOP.** Stage 7 has not been started.

## Tests and integrity

| | Result |
|---|---|
| Default suite | **1185 passed**, 1 skipped (0 new failures) |
| New Stage 6 tests (`tests/test_generation_quality.py`) | 22 passed |
| Integration (`-m integration`) | 20 passed, 1 failed |
| Slow (`-m slow`) | 3 passed, 3 failed |

The 3 distinct failing tests predate Stage 5 (documented in `docs/answerability_gate_stage5.md` §L):
`test_rag_slow` (context-length cap), `test_model_smoke` (TypeError) and `test_evaluation_smoke`.

The Stage 6 tests cover:
* the exact-evidence context, and its exceptions for incomplete coverage, general questions, comparisons,
  lead-ins and fragments;
* enumeration items kept;
* qualifier-bearing sources kept, with a dropped qualifier still flagged;
* renumbered citations and a stale citation caught;
* a degenerate general answer withheld, not quoted;
* a failed repair never shown;
* the generalised S5-090 (any reference target) and S5-091 behaviour;
* determinism.

Integrity, checked before and after:

| Item | State |
|---|---|
| Benchmark xlsx | `c009d5f9c6498220…`, unchanged |
| `stage5_v1.jsonl` | `7cf80fda674fd1ab…`, unchanged |
| `diagnostic_v1.jsonl` | `f99b1106aba8e053…`, unchanged since its Stage 4 creation |
| Weights | `f47f71177f32bcd1…`, unchanged |
| Database | read-only, `cfr_records` 65,341 rows |
| Stage 5 artifacts | not modified (last written before Stage 6 began) |

## Files

* **Code:**
  * `src/regulus/rag/selection.py`: `required_only`, `is_complete_sentence`;
  * `src/regulus/rag/pipeline.py`: the `optional_context` setting and its conditions in `build_bundle`;
  * fingerprint v4.
* **Scripts:**
  * `scripts/generation_matrix.py`
  * `scripts/generation_experiments.py`
  * `scripts/compare_runs.py`
  * `scripts/prompt_diff.py`
* **Artifacts:**
  * `artifacts/generation_quality/`
  * `artifacts/diagnostics/stage6_*`; the final result is `stage6_result_final_20260930T040757Z`, with
    `manual_review.jsonl`, `reviewed_distribution.json` and `comparison_vs_baseline.json`.
