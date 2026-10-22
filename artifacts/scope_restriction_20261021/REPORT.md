# Does the eCFR-only restriction cause retrieval failures? (2026-10-21)

**Method:** read-only. No model inference, no change to code, prompts, configuration, the database or any index.
Database: the repaired corpus (65,280 rows, identity `4f0457d7…`), unchanged by this work. 3 adversarial verifiers
re-checked this report; their corrections are applied.

## 1. Verdict: H3 supported. H1 not supported for any scope rule. H2 not attributable to the restriction.
- **H1 (a restriction changes retrieval inputs, routing, filters or selection): not supported** for every scope *rule*
  found (M1, M2, M3, M5 below).
  - In the production configuration, no code path carries them into the query text, plan, corpus, filters, ranking or
    context selection.
  - Their one retrieval-side hook (`skip_semantic`) was reached by 0 of 100 benchmark questions.
- **Corpus scope (M4), the literal "eCFR-only": a direct cause, but not through a rule.**
  - **17 of the 100 benchmark keys cite only FD&C Act statute text (21 U.S.C.).** A further 3 cite only "21 CFR Parts
    700–740" at part level.
  - The database holds Title 21 eCFR and FDA guidance only. No statute table exists, and `federal_register_docs` has 0
    rows ([corpus_scope_check.json](corpus_scope_check.json)).
  - No change to retrieval could find that text. This is a corpus-coverage decision, not a retrieval defect.
- **H2 (sufficient evidence, but the restriction or validation prevents an answer): not attributable to the
  restriction.** An answer-stage decline problem exists, but it tracks question type, not scope:
  - In Step 6 the model's first output was a refusal for **82 of 88 general questions and 0 of 12 named-provision
    questions** (validation `answer_class`).
  - The decline wording is rule 9's, which does not mention the eCFR. Rule 5, the eCFR wording, applies only to
    requested provisions, and none of the declined questions had one.
- **H3 (the restriction affects only answer eligibility; retrieval failures originate elsewhere): supported** for
  M1–M3 and M5.
  - 53 of 80 keyed questions have no required paragraph in context after the source repair (54 in the pre-repair
    Step 6 run).
  - The stage attribution comes from the earlier root-cause report and was not re-measured here.

## 2. What "the eCFR-only restriction" is in this code

| # | Mechanism | Where (production path) | Introduced | Acts at |
|---|---|---|---|---|
| M1 | Prompt scope: "U.S. FDA regulations… strictly from the EVIDENCE"; rule 5 "not found in the available eCFR data" (requested provisions only); rule 9, the decline sentence | [generation.py:48–58](../../src/regulus/rag/generation.py#L48) `GROUNDED_SYSTEM_PROMPT` (production). prompt.py `RAG_SYSTEM_PROMPT` is the legacy no-package path ([pipeline.py:739](../../src/regulus/rag/pipeline.py#L739)) | 4396452 (2026-09-30, first commit) | generation |
| M2 | Intent scope: a named non-U.S. framework is OUT_OF_SCOPE | `analyze_question` ([intent.py:77](../../src/regulus/planning/intent.py#L77) `_FOREIGN_RE`); gate [answerability.py:113](../../src/regulus/rag/answerability.py#L113); refusal via the gate's block branch [pipeline.py:715](../../src/regulus/rag/pipeline.py#L715) and `rag/fallback.py` `blocked_answer`. pipeline.py:723 applies only under `answer_shape="structured"`, which is not production. | 4396452 | after retrieval: blocks generation |
| M3 | General-knowledge `ScopePolicy`: no named provision, no domain word, nothing matched | [domain.py:83–102](../../src/regulus/retrieval/domain.py#L83); decided at [pipeline.py:641](../../src/regulus/rag/pipeline.py#L641); gate [answerability.py:115](../../src/regulus/rag/answerability.py#L115); wired into the semantic fallback at [factory.py:31](../../src/regulus/retrieval/factory.py#L31) | e0c3135 (2026-10-01). It added domain.py, factory.py and retrieval/fallback.py; changed pipeline.py (the scope decision, plus `reference_lookup_plan`), answerability.py and rag/fallback.py (refusal text); and carried no scope logic in its other files. lexical.py, sql.py, query.py and intent.py were untouched. | after retrieval: blocks generation; `skip_semantic` during retrieval |
| M4 | Corpus content: eCFR Title 21 and FDA guidance only | the database | the dump | what exists to be retrieved |
| M5 | Title-21-only exact lookup: a non-Title-21 CFR reference skips the exact lookup and its per-requirement legs | [lexical.py:472](../../src/regulus/retrieval/lexical.py#L472) (and :720) | 4396452 | retrieval routing, for non-Title-21 references only. **Not reached by any of the 100 questions.** |

**Corpus and filters:** production calls `run_plan(corpus=None, filters: retrievable=True)`. Both corpora are
enabled on every question; a CFR-definition hit skips the keyword legs. `retrievable` is a guidance-document flag.

## 3. Causal chain (`RagPipeline.answer`)

```
question
 → plan_query (:632) → complete_plan (:633)
 → reference_lookup_plan (:635) and question_view (:637)
      analyze_question runs here, before retrieval, but only its question_type can re-plan the query;
      scope_status cannot: SCOPE_OUT needs no requirement, the re-plan needs at least one
 → retrieve (:639): run_plan(corpus=None, retrievable=True, top_k=8)
      AND legs: the question verbatim · section coverage: content_terms · guidance OR fallback
      semantic fallback only if lexical_insufficiency ≠ None (fallback.py:94)
        skip_semantic is consulted except for reference-only lookups (fallback.py:155–156)
        in production it can fire only for a general question with zero lexical results and zero domain words
 → ScopePolicy.decide (:641): between retrieval and selection; nothing flows into selection
 → build_bundle / selection (:645)
 → gate.decide (:696): OUT_OF_SCOPE (M2 or M3) → block branch (:715), the model is not called
 → generation (GROUNDED_SYSTEM_PROMPT, rule 9) → validation / repair
```

## 4. Retrieval-only trace ([scope_trace.json](scope_trace.json), [tools/scope_trace.py](tools/scope_trace.py))

| Question | Query sent | Legs | Required in context | Scope (M3) / intent (M2) / gate | Generator reached |
|---|---|---|---|---|---|
| COS-73.2725-Q1 | verbatim (the "or" branch returns 16 rows, so section coverage does not run) | 2 AND | 0/5 | in_scope / in_scope / not blocked | yes |
| COS-700.25-Q2 | verbatim; coverage terms | 5 | 0/1 | potentially_related / in_scope / not blocked | yes |
| COS-74.2317-Q1 | verbatim; coverage terms (drop "17", "D&C", "12-person") | 5 | 0/4 | potentially_related / in_scope / not blocked | yes |
| COS-70.55-Q1 | verbatim; coverage terms | 5 | 0/2 | potentially_related / in_scope / not blocked | yes |
| COS-FDCA609-Q1 | verbatim; coverage terms | 5 | key is statute (not in corpus) | potentially_related / in_scope / not blocked | yes |
| COS-70.3-Q3 | verbatim; coverage + defined terms | 6 | 3/3 | potentially_related / in_scope / not blocked | yes |
| COS-740.11-Q2 | verbatim; coverage terms | 5 | (b)(1) in; (b)(2)(i)–(iv) not | potentially_related / in_scope / not blocked | yes |
| COS-710.5-Q1 (names a provision) | exact lookup + verbatim | 3 | 1/1 | in_scope / in_scope / ANSWERABLE | yes |
| "What is the capital of France?" | verbatim | 5 | – | **general_knowledge** / in_scope / **OUT_OF_SCOPE** | **no** |
| "Who wrote Hamlet?" | verbatim | 6 | – | **general_knowledge** / in_scope / **OUT_OF_SCOPE** | **no** |
| "Boiling point of water in Celsius?" | verbatim | 5 | – | potentially_related (documented gap) / in_scope / not blocked | yes |
| "What does EU Regulation (EC) No 1223/2009 require…?" | verbatim | 5 | – | potentially_related / **out_of_scope** / **OUT_OF_SCOPE** | **no** |

- Retrieval ran in full for all 12, including the three that were then refused. Every run used `corpus=None`.
- No scope rule intervened before or during retrieval.
- Each question was also run in process with `scope_policy="off"`: legs, run arguments and final context were
  identical in 12/12. On these questions the two arms could differ only through `skip_semantic`, which none reached,
  so this run is a consistency check on the code, not an independent test.

## 5. Stale Parts 73/74 semantic index
- **Not queried in any traced case.** The semantic fallback was never invoked: `lexical_insufficient` was None for
  12/12 sample questions and 100/100 benchmark questions (post-repair traces), with 0 loader attempts.
- **How it could be reached:** only through `SemanticFallbackRetriever`, for a reference-only lookup or a
  no-identifier question with zero lexical results. Neither occurs here.
- **Conclusion:** no tested failure can be attributed to it.

## 6. Answer stage: existing logs only
Source: Step 6 arm A, Qwen3-1.7B MLX 4-bit, pre-repair; [h2_existing_logs.json](h2_existing_logs.json).
- **Scope or gate rules** blocked **0 of 80** keyed questions.
- **First model output (validation `answer_class`):**
  - general questions: refusal 82, hedged 5, answer 1 (of 88);
  - named-provision questions: answer 12 of 12.
- **Questions with every keyed top-level paragraph in context (12):**
  - 5 declined.
  - Only 2 of those had every required row: COS-700.18-Q1, delivered as a bare decline, and COS-70.3-Q3, which the
    pipeline's definitions fallback turned into a PASS.
  - The other 3 lacked keyed sub-paragraphs or lead-ins: COS-701.13-G1, COS-80.31-Q1, COS-82.6-Q1.
  - The validator withheld 1 (COS-82.1307-Q1).
- **No required paragraph in context (54):** 49 bare declines; 50 counting the withheld refusal COS-71.27-Q1. Three
  more answers contain the decline sentence but also give content.
- **The validator:** it flags a decline only when a requested provision has EXACT evidence
  ([validation.py:382](../../src/regulus/rag/validation.py#L382)). Declines on general questions therefore pass
  validation and are delivered.
- **Reading:** the decline follows question type (general against named), not any scope rule. Its wording is the
  generic rule 9, and the eCFR wording of rule 5 applied to none of these questions.

## 7. Limits
1. **No pre-restriction version of M1, M2 or M5.** They are in the repository's first commit, and no pre-restriction
   code, log or fixture exists. A before-and-after comparison cannot be established; their effect on retrieval is
   shown from code only.
2. **M3 was checked in process,** with the `scope_policy="off"` switch its own commit added, not by running the parent
   commit. That run could not discriminate (§4).
3. **The cause of the decline is not separated** (model behaviour against rule 9) without inference, which was not
   run.
4. **The answer-stage logs predate the source repair.**
5. **Not exercised:** `answer_shape="structured"` (pipeline.py:723), the grounding gate and the premise check. All
   are off in production and in Step 6.
6. **Granularity:** required-paragraph matching is at top-level-paragraph granularity. A child row counts for its
   parent.
7. **Known gap in the general-knowledge rule:** a general-knowledge question built from regulatory words ("boiling
   point of water") is not caught (domain.py).

## 8. Next step
**None arises from this investigation for the scope rules.** M1–M3 and M5 do not change retrieval; keep them as they
are.

The one decision this evidence leaves open is the corpus scope (M4). Whether the FD&C Act chapter VI text that 17
benchmark questions require should be ingested is an owner decision, outside retrieval.

The retrieval correction path is unchanged from the root-cause report.
