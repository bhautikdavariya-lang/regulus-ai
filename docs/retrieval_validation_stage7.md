# Stage 7: Retrieval, Validation & Evaluation Hardening

Date: 2026-09-30. No training, no model change, no database or benchmark change.

Every result is labelled as one of:
- **measured**
- **safety** (what the user is shown, not how many answers are correct)
- **architectural** (capability added, not yet exercised by the data)
- **hypothesis**

*Developer review* is not SME review.

## Summary

| Diagnostic set (79), reviewed | Stage 6 | Stage 7 |
|---|---:|---:|
| PASS | 46 | **49** |
| FAIL | 15 | **12** |
| NEEDS_REVIEW | 2 | 2 |
| UNVERIFIED | 13 | 13 |
| UNVERIFIED_WITH_FAILURES | 3 | 3 |

| Outcome (keyed questions) | Stage 6 | Stage 7 |
|---|---:|---:|
| correct | 46 | 49 |
| incorrect (shown) | 9 | 8 |
| unsupported content shown | 3 | **1** |
| safely withheld / declined | 3 | 3 |

Other results:
- **Protected Stage 4 PASS set:** 38/39 PASS. The exception is S5-101, whose Stage 4 PASS was shown to be a review error in Stage 6; it was FAIL in Stage 6 and remains FAIL. No new regression.
- **Determinism:** 10/10.
- **Retrieval metrics:** unchanged under the adopted defaults (§B). The semantic fallback is **architectural** for the general-question case: measured, and not enabled, because its gain was not reliable.
- **Expert verification:** **0/300 expert verified.**

## A. Engineering summary

| Change | Why | Kind |
|---|---|---|
| **Semantic fallback** `retrieval/fallback.py` (`SemanticFallbackRetriever`, implements `run_plan`), built by `retrieval/factory.py` | lexical misses evidence it cannot term-match; semantic must be a fallback, not a merge (Stage 6: the hybrid lost a known target) | architectural + measured |
| **Reference lookup** `RagPipeline.reference_lookup_plan` | "cite the provision that … meeting part 803 criteria" is a content search constrained to passages that mention the referenced provision | measured (retrieval) |
| **Scope policy** `retrieval/domain.py` + gate state `general_knowledge` | general-knowledge questions were answered (critical failures) | measured |
| **Claim-level validation** `rag/claim_validation.py` (4 checks + 1 split) | wrong-paragraph text, invented conditions and false premises passed validation | measured |
| **Repairs**: in-place row replacement, invented-sentence removal (only when nothing else is wrong), premise fallback, complete verbatim for exhaustive requests (`generation.verbatim_requested`), sentence matching after marker stripping | repair was coarse or could "launder" a bad answer | measured |
| **Repetition stop** `inference/repetition.py` | a loop ran 1,696 tokens / 265 s before validation could reject it | measured |
| **Evaluation**: `scripts/evaluate_retrieval_pipeline.py`, `run_diagnostics.py --replay-from`, outcome classes, reproducibility block, `scripts/measure_claim_checks.py` | comparable, reproducible measurement for the model ladder | architectural |
| **Expert-verification status**: reason categories + `KEY STATUS` line in `review_benchmark_key.py` | report "X verified / Y pending / Z disputed", never imply verification | architectural |
| **Backend seam**: `rag/remote_generator.py` (`OpenAICompatibleGenerator`, `load_generator`); `model.backend` / `model.endpoint` | run 4B/8B/14B locally-quantized or remote without touching retrieval, evidence or validation | architectural |

Config: `RagConfig.semantic_fallback="on"` and `scope_policy="general_knowledge"` (defaults); fingerprint version 5.

The UI (`serve_ui.py`) uses the same retriever and scope policy. Its diagnostics show the scope decision and the fallback decision.

## B. Retrieval report (retrieval metrics only; no answers)

`scripts/evaluate_retrieval_pipeline.py` runs every query through the pipeline's own retrieval path (re-plan, `run_plan`, scope, selection):
- **A:** lexical only;
- **B:** with the fallback.

**The general-question trigger was measured before it was left off by default:**

| Dataset | Variant | R@1 | R@5 | R@10 | MRR | Target reaches the prompt | Fallback runs | Recovered | Degraded |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| retrieval_v2 (37 positive) | A lexical | 0.730 | 0.757 | 0.757 | 0.735 | 0.757 | 0 | — | — |
| | B, semantic ranked above lexical broad search | 0.703 | 0.757 | 0.757 | 0.715 | 0.757 | 11 | 0 | 1 |
| | B, interleaved | 0.730 | 0.757 | 0.757 | 0.735 | 0.757 | 11 | 0 | 0 |
| benchmark draft citations (266; **not SME-verified**) | A lexical | 0.098 | 0.252 | 0.301 | 0.164 | 0.316 | 0 | — | — |
| | B, semantic first | 0.109 | 0.263 | 0.320 | 0.178 | 0.323 | 67 | 6 (+2 ranks) | 6 |
| | B, interleaved | 0.098 | 0.267 | 0.320 | 0.171 | 0.323 | 67 | 5 (+2 ranks) | 5 |

- **Interleaved, measured on what the model sees:** the target entered the prompt for 6 questions and left it for 4. Net +2 of 266, measured against unverified targets.
- **Decision:** not a reliable improvement. The general-question trigger stays **opt-in** (`FallbackConfig.general_questions`).

**Adopted defaults.** Enabled triggers:
- **reference lookup**;
- **no lexical result for a question that names no provision or docket.** A question naming a missing identifier is never answered from similar text; it stays "not found".

| Dataset | A | B (adopted) |
|---|---|---|
| retrieval_v2 | R@1 0.730, R@10 0.757, MRR 0.735 | identical (0 fallback runs) |
| benchmark drafts | R@1 0.098, R@10 0.301, MRR 0.164 | identical (0 fallback runs) |

- **Legacy query-level lexical evaluation:** R@1 0.703, R@10 0.757, the same as documented in Stage 10. The lexical layer is unchanged.
- **Reference-lookup class (S5-090), measured:** 21 CFR 820.10(b)(3) is now the first source in the prompt. Before, it was never retrieved; the 26 part-803 rows are dropped because they don't mention a *referring* provision. End-to-end this is still FAIL (§C).
- **S5-061 is not recovered.** Its lexical retrieval "succeeds" with the wrong passages, and no general rule marks it insufficient. Semantic search ranks 830.20 first (Stage 6 measurement), but nothing triggers it.

**Finding (measured, draft targets):** on benchmark-style questions, lexical retrieval puts the drafted provision into the prompt for only **31.6 %** of questions. That is the largest measured gap in the system. It is not addressed by this stage (retrieval redesign was out of scope), and no model will fix it.

## C. Diagnostic comparison

| Status | Stage 6 | Stage 7 automatic | Stage 7 reviewed |
|---|---:|---:|---:|
| PASS | 46 | 46 | **49** |
| FAIL | 15 | 15 | **12** |
| NEEDS_REVIEW | 2 | 2 | 2 |
| UNVERIFIED | 13 | 12 | 13 |
| UNVERIFIED_NEEDS_REVIEW | — | 1 | — |
| UNVERIFIED_WITH_FAILURES | 3 | 3 | 3 |

Reviewed = automatic, with Stage 6 reviews carried only where the final answer is byte-identical, plus developer review of all 10 changed answers (`manual_review.jsonl`).

Run details:
- **Run:** `artifacts/diagnostics/stage7_final_20260930T111007Z` (live, 79 questions, 10 repeats).
- **Offline replay:** `run_diagnostics.py --replay-from` predicted every change before the live run. The one question it could not replay was S5-090, whose prompt changed.

## D. Regression report

**All 10 changed answers:**

| Question | Before (S6) | After (S7) | Change | Cause | Safety impact |
|---|---|---|---|---|---|
| S5-005 (protected) | PASS | PASS | invented sentence removed | invented_condition → removal (no other error) | safer |
| S5-071 (protected) | PASS | PASS | invented sentence removed | same | safer |
| S5-081 (protected) | PASS | PASS | model decline → deterministic decline | scope policy | same |
| S5-024 | FAIL | PASS | complete verbatim of both provisions | exhaustive repair quotes every item | safer, correct |
| S5-053 | FAIL | PASS | "does not state 'annual', 'audits'" + provision verbatim | unsupported_premise → premise fallback | false premise no longer affirmed |
| S5-080 | FAIL | PASS | declined | scope policy | critical failure removed |
| S5-090 | FAIL | FAIL | wrong-provision decline → withheld | right evidence now retrieved; the model wrote "found in SOURCE 1" (prompt echo) | safe either way |
| S5-101 | FAIL | FAIL | 2 misattributed rows replaced in place | paragraph_misattribution → row repair | fewer wrong rows; the (b)(1) row still runs on |
| BM-S-019 | UNVERIFIED_WITH_FAILURES | UNVERIFIED | invented sentence removed | invented_condition | safer; the rest is suspect (review note) |
| BM-NC-003 | UNVERIFIED | UNVERIFIED_WITH_FAILURES | answer withheld | invented condition plus other errors → no removal → withheld | **safer**: Stage 6 described a non-existent "Subpart Z" |

**Protected Stage 4 PASS set:**
- 38/39 PASS; S5-101 is FAIL in Stage 6 and Stage 7 (the review correction).
- Three protected answers changed: S5-005, S5-071 and S5-081, all still PASS.

**Regressions found during development, and resolved before the final run:**
- **S5-071 withheld:** a sentence-matching bug after invalid-marker stripping; fixed.
- **AS-03 made incomplete:** row repair was too coarse; now in place.
- **BM-F-002 would have shown a wrong but "clean" remainder:** sentence removal is now gated on the absence of other errors.

All three were found by offline replay.

**Latency, measured:**
- Median per generated question 12.1 s → 14.3 s; first token 1.68 → 1.84 s.
- **This is not caused by Stage 7.** On the 61 questions with an identical prompt, 60 generated identical token counts, with a median generation-time ratio of 1.10: the same work ran 10 % slower on the machine.
- The repetition stop saved **225 s** on BM-S-001 (1,696 → 224 tokens), with a byte-identical final answer.
- The gate, scope policy and claim checks add milliseconds (no model).

## E. Validation report (live run, initial validation)

| Class | Detection | Questions | Repaired | Withheld / fallback | Shown unchanged |
|---|---|---:|---:|---:|---:|
| Wrong paragraph attribution (`paragraph_misattribution`) | **error** | 3 | 1 (in place) | 2 | 0 |
| Invented condition, in no source (`invented_condition`) | **error** | 5 | 3 (sentence removed) | 2 | 0 |
| Real condition cited to the wrong source (`condition_not_in_cited_source`) | warning | 7 | 2 | 2 | 3 |
| Affirmed false premise (`unsupported_premise`) | **error** | 1 | — | 1 (premise answer) | 0 |
| Unsupported claim (`unsupported_claim`) | warning (metric) | 2 | — | — | 2 |
| Dropped condition (`qualifier_dropped`, existing) | warning | 5 | 1 | 2 | 2 |
| Degenerate generation (existing + repetition stop) | error | 3 | 1 | 2 | 0 |

**Before enforcement,** each check was measured on all 63 recorded Stage 6 answers (`artifacts/validation_eval/`):
- **misattribution:** its only false positive, a provision named *inside* quoted text, was removed by reading only a lead label;
- **invented_condition:** split from `condition_not_in_cited_source` and matched on condition *phrases* ("if applicable"), not the bare word;
- **unsupported_claim:** fires on paraphrase and has few true positives, so it is a metric only.

**Still missed:**
- dropped conditions stay warnings, so an answer that drops "if applicable" is shown with a flag;
- unsupported claims written as paraphrase;
- semantic errors built from real source words. BM-F-002's "a qualified facility … must implement preventive controls" is lexically grounded and wrong. It is withheld only because other errors blocked it.
- Lexical checks cannot judge meaning.

**Citation policy:** there is no "every answer must cite" rule. An uncited but supported answer still passes (tested); S5-062 is protected and unchanged. Unsupported content is checked independently of citations.

## F. Scope report

Rule: a question is general knowledge only when all three signals agree:
- it names no CFR provision or docket;
- it uses **no** word of the database's own vocabulary (part titles, section headings, guidance titles; 7,662 words);
- no passage matched every term.

| Question type | Examples | Result |
|---|---|---|
| Known out of scope | S5-080 "capital of France", S5-081 "Who wrote Hamlet?" | **declined** without the model or semantic search |
| Known out of scope, not caught | S5-082 "boiling point of water in Celsius" | **missed**: water, boiling and Celsius are regulatory words (food processing); a rule cannot separate it (documented limit) |
| In-scope regulatory (431 questions measured) | all diagnostic, benchmark and retrieval questions except the two above | none declined; the fewest domain words was 1 ("informd consent requirments", a typo query) |
| Ambiguous / potentially related | domain words present, no passage matched (e.g. long scenario questions) | proceed to retrieval and the gate as before (`potentially_related`, recorded) |

`scope_policy="off"` restores the previous behaviour.

## G. Benchmark verification status

`scripts/review_benchmark_key.py status`:

```text
KEY STATUS    : 300 total / 0 expert verified / 300 pending / 0 disputed (0 accepted, awaiting sign-off)
```

**0/300 expert verified.** The workflow already existed and was verified, not rebuilt:
- review packets with provision text;
- an append-only decision log with reviewer and rationale;
- sign-off as the only route to VERIFIED.

Stage 7 adds:
- the optional reason categories `ambiguous`, `insufficient_evidence` and `needs_clarification`, recorded with NEEDS_RESEARCH or REJECTED; older decision records still load;
- the one-line status above.

An ACCEPTED row is **not** counted as verified until sign-off.

## H. Backend readiness

- **The `Generator` protocol is all the pipeline depends on** (`generate(messages, max_new_tokens, on_text)` + `describe()`). `load_generator(settings)` returns the in-process Transformers generator (default) or `OpenAICompatibleGenerator` (`model.backend: openai_compatible`, `model.endpoint`, key only via `REGULUS_MODEL_API_KEY`).
- **Tested against a local HTTP server:** a normal and a streamed request run through the unchanged pipeline, with token usage, finished flag, first-token time and streaming deltas; the key never appears in `describe()`.

| Target | Ready? | Remaining blocker |
|---|---|---|
| Qwen3-4B / 8B / 14B, in-process | yes, by `model.id` (same family, template and loader) | memory: this 8 GB Mac cannot hold them un-quantized |
| Remote inference (vLLM / TGI) | yes, via `openai_compatible` | a server to point at; per-model re-measurement of prompt/context policy |
| Quantized inference (llama.cpp / MLX-LM server, AWQ in vLLM) | yes, via the same backend | the server must run the quantized model; quality impact of quantization unmeasured |

**Not yet on the seam:**
- `serve_ui.py` still loads models in-process, because its adapter picker needs them.
- `run_diagnostics.py`'s *controlled* (exact-evidence) condition calls the generator through the same interface; it works with the remote backend but is untested there.
- The model's own token counts come from the server's `usage`; if a server omits them, truncation detection relies on `finish_reason` only.

## I. Test results

| Suite | Result |
|---|---|
| Default suite | **1,221 passed**, 1 skipped, 26 deselected (slow/integration), **0 failures** |
| New Stage 7 tests (`tests/test_stage7.py`) | 36 passed, covering the semantic fallback, scope policy, claim-level validation and repairs, degenerate-output detection and the repetition stop, the backend seam, replay safety and key-review honesty |
| Retrieval tests (default suite) | passing; the retrieval evaluations above ran on the real database |
| Integration (`-m integration`) | 20 passed, 1 failed |
| Slow (`-m slow`) | 3 passed, 3 failed |
| Diagnostic run | 79/79, determinism 10/10 |

The 3 distinct failing tests predate Stage 5 and are identical to Stages 5 and 6: `test_rag_slow` (context cap), `test_model_smoke` (TypeError) and `test_evaluation_smoke`. They were not introduced here and not fixed here.

Tests updated for intended behaviour changes:
- a false premise is now caught, not flagged-and-shown;
- one Stage 5 fixture now uses the Stage 5 context setting;
- the fingerprint is version 5.

Integrity:
- benchmark `c009d5f9…`, `stage5_v1` `7cf80fda…`, `diagnostic_v1` `f99b1106…`, `retrieval_v2` `db73c6fa…` and weights `f47f7117…` are unchanged;
- git shows no change under `data/`, the benchmark keys or the Stage 5/6 artifacts;
- DB read-only, 65,341 rows.

## J. Recommendation for Stage 8

**Is the evaluation pipeline trustworthy enough for a model ladder?** Yes, with stated limits:
- runs are reproducible: model id, revision, weight hash, prompt hash, pipeline fingerprint, retriever config and git commit are recorded per run;
- deterministic (10/10);
- comparable question by question (`compare_runs.py`, offline replay, prompt hashing);
- the backend swap does not touch retrieval, evidence or validation;
- outcomes are separated into correct / withheld / incorrect / unsupported.

**Stage 8 = the model ladder evaluation, with these conditions:**

1. **Same frozen evidence for every model.** Hold the Stage 7 defaults constant. Report one extra pass with `optional_context="always"`, because the context policy was tuned for 0.6B.
2. **Report the ladder on diagnostics as is, and on the benchmark only as UNVERIFIED** until SMEs verify keys; 0/300 today.
3. **Retrieval is the ceiling on the benchmark, not the model.** Only 31.6 % of benchmark questions get the drafted provision into the prompt, so a larger model cannot answer the rest. A retrieval stage should follow the ladder or run alongside it; it is not a reason to delay the ladder.
4. **Watch the classes lexical validation cannot see.** A larger model's errors will be more fluent. Plan developer or SME review of changed answers per rung, as in Stages 6 and 7.
5. **Hardware:** 8B+ needs a GPU server or a larger Mac behind `openai_compatible`. 4B quantized can run locally through an MLX or llama.cpp server.

**Hypotheses, not measured:**
- a larger model will fix the 9 capacity failures;
- general-question semantic fallback would help a stronger model more;
- scope and claim checks generalise beyond this set.
