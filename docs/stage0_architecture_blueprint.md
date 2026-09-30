# Stage 0: Architecture Discovery and Implementation Blueprint

Status: discovery only. No code, configuration, model, index or database
content was changed while producing this document.

Inputs: the full current codebase under `src/regulus`, `scripts`, `web`,
`tests`, `configs`, `docs`; the audit in
`MODEL_SYSTEM_AUDIT_AND_TEST_REPORT.md` with its raw evidence under
`audit/results/`; and read-only inspection of the PostgreSQL database.

The document follows the twenty items requested in the mission brief, in
order, and ends with the explicit answer on model training.

---

## 1. Current architecture

One linear, single-turn pipeline. Every question is processed independently
and every stage is fixed-shape.

```
question (str)
  │
  ▼
regulus.retrieval.query.classify(question)
  │   parse_cfr_reference() → FIRST CfrReference or None
  │   parse_docket()        → docket or None
  │   → QueryClassification(query_type, cfr, docket)
  ▼
regulus.retrieval.lexical.LexicalRetriever.run(question, top_k=8)
  │   exact_cfr        if cfr parsed          score 100 / 95 (descendants)
  │   exact_docket     if docket parsed       score 100
  │   full_text        always (both corpora)  score 50 × ts_rank_cd
  │   trigram          conditional            score 5 × similarity
  │   full_text_or     if primary hits < 3    score 5 × rank / n_terms
  │   merge() → dedupe by key, strongest method, sort desc, cut to top_k
  │   → SearchResponse(results, timings, counts, notes, diagnostics)
  ▼
regulus.rag.pipeline.RagPipeline.answer()
  │   select_useful()   drop trigram-only < 0.4, drop contextual_only
  │   build_context()   ≤ 8 sources, ≤ 1,200 chars each, ≤ 3,600 total
  │   [GroundingGate]   optional: first identifier exists? some source carries it?
  │   NO_CONTEXT_ANSWER if context empty (model not called)
  │   build_messages()  system rules + SOURCES block + QUESTION
  │   generator.generate()  Qwen3-0.6B, greedy in eval/UI, 128 tokens
  │   build_citations()  every context source becomes a citation
  │   → RagAnswer
  ▼
scripts/rag.py · scripts/evaluate_baseline.py · scripts/serve_ui.py
```

Component inventory, with the file that owns each responsibility:

| Responsibility in the mission brief | Exists today? | Where |
|---|---|---|
| QueryParser | partial (first reference only) | `retrieval/query.py` |
| QueryPlanner | no | |
| CandidateRetriever | yes (fixed shape) | `retrieval/lexical.py` |
| EvidenceRanker | partial (fixed score scales, one merge) | `retrieval/ranking.py` |
| EvidenceSelector | minimal (`select_useful`, top_k cut) | `rag/pipeline.py`, `ranking.merge` |
| CoverageChecker | no | |
| GroundingGate | partial (one identifier, presence only) | `grounding/gate.py`, `grounding/identifiers.py` |
| ContextBuilder | yes (budget only, no tiering) | `rag/context.py` |
| Generator | yes | `rag/generator.py`, `inference/generate.py` |
| AnswerValidator | no | |
| CitationManager | partial (labels only, no support tracking) | `rag/pipeline.py:build_citations` |
| ConversationState | no (chat CLI keeps raw messages, no retrieval) | `scripts/chat.py` |

Experimental, not on the default path: `retrieval/hybrid.py`
(`HybridRetriever`, RRF and "authority" fusion), `retrieval/semantic/*`
(bge-small local index), the LoRA adapters under `models/qwen3-0.6b-lora/`,
and the `training` and `finetune` packages.

---

## 2. Existing retrieval flow

`LexicalRetriever.run()` (`src/regulus/retrieval/lexical.py:123-225`):

1. `classify(query)`; empty query raises.
2. `limit = top_k × CANDIDATE_MULTIPLIER (2)` = 16 candidates per leg.
3. Legs run in fixed order and all append to one candidate list:
   * `exact_cfr(classification, filters, limit)` when `classification.cfr`
     is set. Section form runs `sql.ECFR_EXACT_SECTION`: the row whose
     `paragraph_path` equals the requested path (`match_kind = 'exact'`) plus
     rows whose path starts with `requested + "("` (`'descendant'`), ordered
     by document ordinal. Part form runs `sql.ECFR_EXACT_PART`: the first
     live row of each section. If the leg returns nothing, a NOTE is
     appended ("No live record for … in this eCFR snapshot").
   * `exact_docket` when a docket was parsed: opening chunks of that
     guidance document.
   * `full_text_ecfr` and `full_text_guidance`: `websearch_to_tsquery`
     (AND semantics) over GIN tsvectors; guidance capped at 3 chunks per
     document.
   * `trigram_ecfr` when `_should_run_trigram`: query ≤ 4 words, or
     `looks_like_identifier`, or eCFR full-text under-delivered.
   * Stage 7 fallback: if distinct primary keys (exact + full_text) < 3,
     `fallback_terms()` builds an OR query and both corpora are searched
     again.
4. `merge(candidates, top_k)`: dedupe by natural key, keep strongest
   method, score = max, sort by (score desc, key), cut.
5. Diagnostics: `primary_result_count`, `fallback_used`, `fallback_terms`,
   `retrieval_mode` (exact / primary / fallback / none).

Properties that matter for the redesign:

* One `CfrReference` in, one exact query out. No loop over references.
* `top_k` is global over the merged list; there is no per-requirement
  quota, so a second requested provision competes with fallback noise.
* Score scales are fixed constants and not comparable across legs; the
  design intent (exact beats everything) holds, but nothing below exact is
  tiered.
* The fallback fires whenever exact retrieval yields a single row, because
  question words rarely appear in the paragraph text. Measured: 31 of 47
  audit requests used the fallback; it supplied the text behind most
  fabrications.
* The trigram leg matches digit trigrams of section numbers ("820.10" vs
  "1.360", "112.121") at similarity 0.40 to 0.42, which passes the 0.4 cut.

---

## 3. Existing query parsing flow

`src/regulus/retrieval/query.py`:

* Four regexes tried in order, first match wins:
  `_CFR_RE` ("21 CFR 820.10(b)(1)", "C.F.R. § 820.10", "CFR Part 820"),
  `_SYMBOL_RE` ("§ 820.10(b)(1)"), `_SECTION_WORD_RE` ("section 820.10(b)"),
  `_PART_WORD_RE` ("part 820").
* `_build()` normalises paragraph tokens into "(b)(1)" and returns a frozen
  `CfrReference(title, part, section, paragraph_path, raw)` with `level`
  (part / section / paragraph) and `label`.
* `classify()` → `QueryClassification(query_type, cfr, docket)` with
  `QueryType` EXACT_CFR / GUIDANCE_SEARCH / GENERAL_REGULATORY_SEARCH /
  EMPTY.
* `fallback_terms()` and `looks_like_identifier()` serve the retriever.
* The same parser is reused by the grounding layer:
  `grounding/identifiers.py:extract_identifier()` wraps
  `parse_cfr_reference` and `parse_docket` into a `RequestedIdentifier`.

Verified gaps (audit section 7):

| Form | Today |
|---|---|
| `21 CFR 820.10(b)(1)`, `§ 820.10(b)(1)`, `section 820.10(b)(1)` | parsed |
| `820.10(b)(1)` bare | not parsed → general search |
| `(b)(1) through (b)(4)`, `(b)(1)-(b)(4)`, `(b)(1) to (b)(4)` | first only |
| `820.10(b)(1), 820.10(b)(2), 820.10(b)(3)` | first only (if prefixed), else none |
| `(b)(1) and (b)(4)` | first only |
| two different sections in one question (`820.10(b)(2) and 820.999`) | first only |
| `subsections (b)(1) through (b)(4) of 820.10` | none |

There is no notion of a question's *intent* (define, list, compare,
explain, why) or of decomposition into requirements.

---

## 4. Existing grounding flow

`src/regulus/grounding/`:

* `identifiers.py`: `RequestedIdentifier` (kind section / paragraph / part /
  docket), `IdentifierVerification(exists, verifiable, reason, record)`,
  `verify_identifier()` against an `IdentifierIndex` protocol with two
  implementations (`CorpusIdentifierIndex` for tests, `DatabaseIdentifierIndex`
  with cached SELECTs). Reasons: FOUND, NOT_IN_SNAPSHOT, RESERVED,
  PARAGRAPH_NOT_IN_SECTION, OUTSIDE_TITLE_21.
* `gate.py`: `GroundingConfig(enabled=False, refuse_unverified_identifier,
  refuse_context_mismatch, mismatch_kinds)`, `GroundingDecision(checked,
  action, reason, matched_keys, answer)`, `match_results(identifier,
  results)` (structural: section equality; paragraph equal or descendant
  via `_paragraph_covers`; part equality; docket equality),
  `refusal_text()`, and `GroundingGate.check_identifier(question)` /
  `check_context(verification, results)`.
* Wired in `RagPipeline.answer()` after context construction and before
  generation. A refusal replaces generation with deterministic text. The
  gate never touches the prompt.

What it establishes: "the single identifier the parser found exists in the
snapshot, and at least one context source carries it." What it does not
establish: coverage of all requested identifiers, relevance of the other
sources, answer entailment, citation support. Measured: of six fabrications
in the audit, the gate as designed prevents none; it does prevent answers
about nonexistent identifiers (I1, I2) in under 6 seconds.

The structural matcher `match_results` and the verification index are
sound and reusable; they simply operate on one identifier instead of a set.

---

## 5. Existing generation flow

* Prompt (`rag/prompt.py`): five rules in the system turn; sources in the
  user turn inside `<<<SOURCES … >>>END SOURCES`, each rendered by
  `context.render_source()` as `SOURCE n`, corpus, citation, heading, URL,
  text; then `QUESTION:`. Closing instruction "Answer in a few plain
  sentences."
* `QwenGenerator.generate(messages)` → `inference.generate_chat()` →
  `GenerationResult(prompt, response, prompt_tokens, generated_tokens,
  seconds)`. No finish reason is recorded, so truncation at
  `max_new_tokens` is not observable from the result.
* `GenerationConfig` has `max_new_tokens`, `temperature`, `top_p`, `top_k`,
  `do_sample`, `enable_thinking`. No repetition control. The evaluation and
  UI paths force greedy and 128 tokens.
* Measured behaviour (audit sections 15 and 20): faithful on single
  provisions; fills gaps from any source in the context; appends the
  refusal sentence as a suffix (9 of 47); false-refuses some phrasings
  (2 of 10); loops on one (C3); truncates every list of three or more
  items; ignores the "plain sentences" instruction for lists.

---

## 6. Existing citation flow

`RagPipeline.build_citations(bundle, answer)`:

* Groups every `ContextSource` by `citation.label`; each group becomes a
  `RagCitation(index, indices, label, corpus, url, cited_in_answer,
  citation)`. Labels come from `retrieval/citations.py`
  (`build_ecfr_citation`, `build_guidance_citation`) using stored metadata
  only, so a citation can never name a nonexistent document.
* `cited_in_answer` is true when the answer text contains `[n]` for any
  index in the group. Nothing checks that the sentence carrying `[n]` is
  supported by source n.
* Every context source is listed as a citation whether or not it was used.
  Audit: every single-provision answer carried two or three guidance
  citations that contributed nothing; two answers attached a valid `[1]` to
  an unsupported claim.
* The metrics side (`evaluation/grounding_eval.py`) checks only that marker
  indices are in range.

---

## 7. Existing evaluation flow

* `evaluation/dataset.py`: `EvalExample(id, category, question, …)` loaded
  from JSONL; `baseline_v1.jsonl` (27 questions, five categories, none
  multi-provision, none about 820.10). Protected and immutable.
* `evaluation/runner.py`: `run_evaluation(dataset, answer_fn, metadata,
  …)` calls `answer_fn(question)` per example, captures `diagnostics` and
  `citations` from `RagGenerationResult`, saves an `EvaluationRun` with
  aggregates (`results.aggregate`). Manual 0/1/2 quality scores are added
  afterwards and labelled as reviewer judgments.
* `evaluation/retrieval_eval.py`: `retrieval_v1/v2.jsonl` (28 / 52
  queries), Recall@K, MRR, precision, negative controls. `target_matches()`
  accepts any paragraph at or below the target path, so a sibling paragraph
  of the same section does not count, but a section-level target accepts
  any of its paragraphs.
* `evaluation/grounding_eval.py`: refusal / hedged / answer classification,
  unsupported-answer rate, false-refusal rate, identifier grounding,
  citation-index validity, degeneration (repeated 4-grams), gate activity.
* Scripts: `evaluate_baseline.py` (flags for pipeline, retriever, adapter,
  grounding, decoding), `evaluate_retrieval.py`, `compare_runs.py`,
  `compare_grounding.py`, `analyze_failures.py`.
* Missing (audit section 21): reference-extraction accuracy, evidence
  coverage, answer completeness, citation support, truncation, multi-turn.

---

## 8. Existing UI / API configuration flow

* `scripts/serve_ui.py`: stdlib `ThreadingHTTPServer` on loopback.
  `Engine` loads tokenizer, base model and the read-only `Database` once;
  caches merged adapter models by id. `POST /api/ask` body: `question`,
  `adapter`, `grounding` (bool), `top_k` (1–20), `max_new_tokens` (16–512).
  Each request builds a fresh `RagPipeline(LexicalRetriever(db),
  QwenGenerator(model, tokenizer, gen), RagConfig(top_k), grounding=gate)`
  and returns answer, citations, sources (with text, score, method),
  grounding decision, retrieval diagnostics, timings, token counts. One
  inference at a time under a lock. `GET /api/config` lists adapters.
* `web/index.html`: model selector, gate toggle, top-k, token cap, presets,
  sources panel, diagnostics, raw JSON. No session or conversation id.
* `scripts/rag.py`: same pipeline from the command line with retriever
  and decoding flags. `scripts/chat.py`: raw model chat with in-memory
  message history, no retrieval.
* Configuration: `configs/model.yaml` (model id, cache, device, dtype,
  sampling defaults) via `config/settings.py` with `REGULUS_*` overrides.
  Retrieval and context limits are dataclass defaults (`RagConfig`,
  `ContextPolicy`, `LexicalRetriever.__init__`), not YAML.

The API surface is small and can carry new fields (plan, coverage,
validation, session id) without breaking the page.

---

## 9. Components that can be reused as they are

| Component | Why it stays |
|---|---|
| `retrieval/db.py` `Database` | read-only access, connection handling, tested |
| `retrieval/sql.py` `ECFR_EXACT_SECTION`, `ECFR_EXACT_PART`, full-text, trigram, guidance statements | correct and indexed; the exact-section statement already returns a parent with all descendants |
| `retrieval/models.py` `RetrievalResult`, `Citation` | serialisable, natural keys, `metadata` dict already carries per-method extras (`match_kind`, `requested`, `similarity`); new fields fit in `metadata` or as optional dataclass fields |
| `retrieval/citations.py` | authoritative labels from stored metadata |
| `retrieval/ranking.py` `merge()` and score functions | deduplication and the exact-beats-text invariant |
| `retrieval/query.py` `CfrReference`, `_build`, `_normalise_paragraphs`, `parse_docket`, `fallback_terms` | building blocks for the multi-reference parser |
| `grounding/identifiers.py` `IdentifierIndex`, `DatabaseIdentifierIndex`, `verify_identifier`, `IdentifierVerification` | existence verification, cached, tested with a fake index |
| `grounding/gate.py` `match_results`, `_paragraph_covers`, `refusal_text` | structural evidence matching for one identifier; the coverage checker applies it per requirement |
| `rag/context.py` `ContextSource`, `ContextBundle`, `render_source`, `_truncate` | rendering and accounting |
| `rag/generator.py`, `inference/generate.py` | model call; one small addition (finish reason) |
| `evaluation/runner.py`, `results.py`, `dataset.py` | reproducible runs and persistence; new metrics attach to `diagnostics` |
| `evaluation/grounding_eval.py` `split_sentences`, `classify_answer`, degeneration | reusable by the answer validator |
| `scripts/serve_ui.py`, `web/index.html` | transport; new response fields are additive |
| Test fakes: `FakeDatabase`, `ecfr_row`, `guidance_row` (`tests/test_retrieval_lexical.py`), `FakeRetriever`, `FakeGenerator` (`tests/test_rag.py`), `FakeIndex` (`tests/test_grounding.py`) | unit tests for every new component without a model or database |

---

## 10. Components that need modification

| Component | Change | Why |
|---|---|---|
| `retrieval/query.py` | add `parse_cfr_references()` returning all references with range/list/continuation expansion and bare-number form; keep `parse_cfr_reference()` as a thin wrapper returning the first | multi-reference understanding; backward compatibility |
| `retrieval/query.py` `classify()` | keep signature; populate a new `references: tuple[CfrReference, ...]` field on `QueryClassification` (default from the first) | existing callers keep working |
| `retrieval/lexical.py` `LexicalRetriever` | (a) `exact_cfr` accepts a `CfrReference` (currently a `QueryClassification`); (b) new `run_plan(plan, …)` entry that runs exact retrieval once per provision requirement, tags results with the requirement they satisfy, and makes the text legs and the fallback conditional on the plan; (c) `run()` stays for callers that pass a bare query | question-driven candidate retrieval |
| `retrieval/ranking.py` | add tier assignment and a tier-aware sort; `merge()` unchanged | evidence hierarchy |
| `rag/pipeline.py` `RagPipeline` | orchestrate plan → candidates → rank → select → coverage → targeted retrieval → gate → context → generate → validate → cite; keep `answer(question)` signature and `RagAnswer` shape, add fields | the mission's target data flow |
| `rag/pipeline.py` `RagConfig` | rename the role of `top_k` to a candidate-pool guardrail (`max_candidates`), add `max_evidence`, tier thresholds, targeted-retrieval switch; keep `top_k` accepted for compatibility | remove fixed final top-k |
| `rag/pipeline.py` `build_citations` | move to a `CitationManager`; cite only used or tier-1 sources; carry `source_kind` (binding / guidance / standard) | citation policy |
| `rag/context.py` `ContextPolicy`, `build_context` | tier-aware budgets (reserve for tier 1–2, smaller cap for guidance when eCFR evidence exists), requirement-to-source header, missing-provision NOTE | evidence-appropriate context |
| `rag/prompt.py` | intent-aware instruction (single vs structured multi-provision), explicit "requested provisions" list, whole-answer refusal rule instead of a suffix habit | professional answer behaviour |
| `grounding/gate.py` `GroundingGate` | new `check_plan(plan, coverage)` producing proceed / proceed_with_gaps / refuse; existing methods kept as wrappers | evidence sufficiency instead of single-identifier presence |
| `grounding/identifiers.py` `extract_identifier` | delegate to the new parser; add `extract_identifiers()` | consistency between retrieval and grounding |
| `inference/generate.py` `GenerationResult`, `config/settings.py` `GenerationConfig` | add `finished: bool` (end-of-turn token seen) and optional `repetition_penalty` / `no_repeat_ngram_size` | truncation detection, loop prevention |
| `evaluation/*` | new dataset schema fields (`expected_references`, `expected_evidence`), coverage and completeness metrics, citation-support metric, truncation flag | measurable evaluation |
| `scripts/serve_ui.py`, `web/index.html` | pass and display plan, coverage, validation; optional `session_id` for conversation state | observability and follow-ups |

---

## 11. Components that genuinely need to be added

| New component | Module (proposed) | Responsibility |
|---|---|---|
| QueryPlanner | `regulus/planning/planner.py` | turn a question (plus optional conversation state) into a `QueryPlan`: references, atomic requirements, intent, answer shape |
| Requirement expansion (ranges, lists, continuations, "part N of this chapter") | `regulus/planning/references.py` (or inside `retrieval/query.py` if kept small) | deterministic expansion of ranges and lists into explicit provisions; validation against the identifier index |
| EvidenceSelector | `regulus/evidence/selector.py` | per-requirement selection with tier rules and guardrails; replaces the top-k cut and `select_useful` |
| CoverageChecker | `regulus/evidence/coverage.py` | requested minus covered; per-requirement evidence keys; drives targeted retrieval and the gate |
| Targeted retrieval | inside `LexicalRetriever.run_plan` or `evidence/targeted.py` | exact retrieval for missing provisions; parent lookup when a child is missing; verification for absent identifiers |
| AnswerValidator | `regulus/validation/answer.py` | truncation, repetition, completeness per requirement, refusal-with-evidence, identifiers not in evidence, citation support |
| CitationManager | `regulus/rag/citations.py` (pipeline helper today) | used-source citations, source kinds, claim-to-source map |
| ConversationState | `regulus/conversation/state.py` | compact state (previous question, plan, evidence keys, answer) and reference resolution for follow-ups |
| Coverage / completeness metrics and datasets | `regulus/evaluation/coverage_eval.py`, `data/evaluation/datasets/architecture_v1.jsonl` | Stage 5 measurement |

The hybrid/semantic retrievers are not required for these stages; they can
be plugged into the candidate step later through the same `Retriever`
protocol.

---

## 12. Exact files and functions affected

Stage 1 (question understanding)

* `src/regulus/retrieval/query.py`: new `parse_cfr_references(text) ->
  tuple[CfrReference, ...]`; range/list/continuation expansion; bare-number
  recognition; `QueryClassification.references`; `classify()` populates it.
* `src/regulus/planning/planner.py` (new): `QueryPlan`, `Requirement`,
  `plan_query(question, index=None, state=None)`.
* `src/regulus/grounding/identifiers.py`: `extract_identifiers()`;
  `extract_identifier()` delegates.
* Tests: `tests/test_retrieval_query.py` (table of all forms in mission
  section 13), new `tests/test_planning.py`.

Stage 2 (dynamic evidence retrieval)

* `src/regulus/retrieval/lexical.py`: `exact_cfr(ref, filters, limit)`,
  `run_plan(plan, corpus, filters, guardrails)`, conditional text legs and
  fallback, requirement tagging in `RetrievalResult.metadata`.
* `src/regulus/retrieval/ranking.py`: `assign_tier(result, plan)`,
  `rank(results, plan)`.
* `src/regulus/evidence/selector.py` (new): `select_evidence(ranked, plan,
  guardrails) -> EvidenceSet`.
* `src/regulus/rag/pipeline.py`: `RagConfig` guardrails; `retrieve()` uses
  `run_plan`; `select_useful()` replaced by the selector (kept as a wrapper).
* Tests: `tests/test_retrieval_lexical.py` (per-reference exact runs,
  fallback suppression), new `tests/test_evidence_selector.py`.

Stage 3 (coverage, grounding, context)

* `src/regulus/evidence/coverage.py` (new): `CoverageReport`,
  `check_coverage(plan, evidence)`, using `gate.match_results`.
* `src/regulus/retrieval/lexical.py`: targeted retrieval for missing
  provisions.
* `src/regulus/grounding/gate.py`: `check_plan()`, `GroundingDecision`
  extended with `coverage`, `missing`.
* `src/regulus/rag/context.py`: tier-aware `ContextPolicy`, requirement
  header, missing NOTE, `ContextSource.requirement_ids`.
* `src/regulus/rag/pipeline.py`: the loop plan → retrieve → rank → select →
  coverage → targeted → coverage → gate → context.
* Tests: new `tests/test_coverage.py`, `tests/test_grounding.py`
  (plan-level decisions), `tests/test_rag.py` (context tiering).

Stage 4 (generation and validation)

* `src/regulus/rag/prompt.py`: `build_messages(question, context_text,
  plan)`; shape by intent.
* `src/regulus/inference/generate.py`, `src/regulus/config/settings.py`:
  `finished`, repetition controls, per-request `max_new_tokens` derived
  from requirement count within a hard cap.
* `src/regulus/validation/answer.py` (new): `validate_answer(answer,
  plan, evidence, result) -> ValidationReport`.
* `src/regulus/rag/citations.py` (new) replacing `build_citations`.
* `src/regulus/conversation/state.py` (new); `scripts/serve_ui.py`
  session map; `web/index.html` conversation controls.
* Tests: new `tests/test_answer_validation.py`,
  `tests/test_conversation.py`; `tests/test_rag.py` prompt shape.

Stage 5 (evaluation)

* `src/regulus/evaluation/coverage_eval.py` (new); `dataset.py` optional
  fields; `runner.py` diagnostics pass-through (already generic);
  `scripts/evaluate_architecture.py` (new) or flags on
  `evaluate_baseline.py`; new dataset file. Existing datasets untouched.

---

## 13. Data structures that should be introduced

All frozen dataclasses with `to_dict()`, following the project convention.
Natural keys only; no database ids.

```python
# planning
@dataclass(frozen=True)
class Requirement:
    id: str                      # "r1", "r2" ...
    kind: str                    # "provision" | "topic" | "comparison" | "explanation"
    reference: CfrReference | None   # for provision requirements
    text: str                    # the requirement in words (for text legs and validation)
    required: bool = True        # False for optional context such as a parent paragraph
    origin: str = "question"     # "question" | "range_expansion" | "list" | "conversation"

@dataclass(frozen=True)
class QueryPlan:
    question: str
    references: tuple[CfrReference, ...]      # every reference, expanded
    requirements: tuple[Requirement, ...]
    intent: str                                # "state" | "list" | "compare" | "explain" | "why" | "general"
    docket: str | None
    guidance_requested: bool
    resolved_from_state: bool                  # follow-up resolution happened
    answer_shape: str                          # "single" | "per_provision" | "comparison" | "insufficient"

# evidence
@dataclass(frozen=True)
class EvidenceUnit:
    result: RetrievalResult
    tier: int                                  # 1..6 per mission section 14
    requirement_ids: tuple[str, ...]           # which requirements it satisfies
    source_kind: str                           # "binding" | "guidance" | "standard" | "explanatory"
    reason: str                                # "exact_requested" | "parent" | "child" | "cross_reference" | "text_match" | ...

@dataclass(frozen=True)
class EvidenceSet:
    units: tuple[EvidenceUnit, ...]
    candidates_considered: int
    guardrails: dict                           # max_candidates, max_evidence, max_chars actually applied

@dataclass(frozen=True)
class CoverageReport:
    requested: tuple[str, ...]                 # requirement ids
    covered: tuple[str, ...]
    missing: tuple[str, ...]
    verified_absent: tuple[str, ...]           # identifiers the database proves do not exist
    ratio: float
    by_requirement: dict[str, tuple[str, ...]] # requirement id -> evidence keys

# grounding
@dataclass(frozen=True)
class GroundingDecision:                        # existing, extended
    action: str                                # "proceed" | "proceed_with_gaps" | "refuse"
    reason: str
    coverage: CoverageReport | None
    answer: str | None                         # deterministic text when refusing

# validation
@dataclass(frozen=True)
class ValidationReport:
    truncated: bool
    repetitive: bool
    refused_with_evidence: bool
    requirements_addressed: tuple[str, ...]
    requirements_missing: tuple[str, ...]
    unsupported_identifiers: tuple[str, ...]   # section numbers in the answer absent from evidence
    citation_support: dict[int, str]           # marker index -> "supported" | "weak" | "unsupported"
    verdict: str                               # "ok" | "flagged" | "replace_with_insufficient"

# citations
@dataclass(frozen=True)
class ClaimSupport:
    sentence: str
    marker: int | None
    evidence_key: str | None
    overlap: float

# conversation
@dataclass(frozen=True)
class ConversationState:
    previous_question: str
    plan: QueryPlan
    evidence_keys: tuple[str, ...]
    answer: str
```

`RagAnswer` gains `plan`, `evidence`, `coverage`, `validation` fields with
defaults so existing consumers (evaluation runner, UI) keep working.

Guardrails live in one place, `RagConfig`: `max_candidates` (pool),
`max_evidence` (units), `max_context_chars`, `max_new_tokens_cap`,
`max_range_expansion` (bound on range size, for example 30). They are
limits, not the selection strategy.

---

## 14. Recommended implementation order

The order follows the mission's stages and the dependency graph below. Each
step is a separately testable unit and leaves the default path working.

```
S1.1 parse_cfr_references (all forms, expansion)       ← no dependencies
S1.2 QueryPlan / Requirement / plan_query              ← S1.1
S1.3 extract_identifiers delegates to S1.1             ← S1.1
S2.1 exact_cfr(ref) + run_plan per requirement         ← S1.2
S2.2 tier assignment + tier-aware ranking              ← S2.1
S2.3 EvidenceSelector with guardrails                  ← S2.2
S2.4 fallback/trigram gated by plan and tier-1 presence ← S2.3
S3.1 CoverageChecker                                   ← S1.2, S2.3
S3.2 targeted retrieval loop                           ← S3.1, S2.1
S3.3 GroundingGate.check_plan                          ← S3.1
S3.4 tier-aware ContextBuilder with requirement header ← S2.3, S3.1
S4.1 intent-aware prompt                               ← S1.2, S3.4
S4.2 finish reason + repetition control + token budget ← none (small)
S4.3 AnswerValidator                                   ← S4.2, S3.1
S4.4 CitationManager                                   ← S4.3
S4.5 ConversationState + UI session                    ← S1.2
S5   datasets + metrics + comparison against the audit baseline
```

Within Stage 1, expansion of numeric ranges is deterministic; alphabetic
and roman ranges follow the eCFR ordering (a…z, 1…n, i…x, A…Z) and every
expanded element is verified against the identifier index so a range that
overshoots ("(b)(1) through (b)(9)") produces `verified_absent` entries
rather than silent failure.

---

## 15. Testing strategy

Principles: every stage adds unit tests that run without a model or a
database (fakes already exist), plus a small number of integration tests
against the read-only database, plus one slow end-to-end smoke. Benchmarks
are never used to select code paths.

Stage 1

* Table-driven parser tests for every form in mission section 13, including
  negatives: "2.1 million", "Phase 1", "510(k)", "Part 11 vs Part 1",
  decimals in guidance titles, "section 3 of the Act".
* Range expansion: numeric, alphabetic, roman, mixed-depth, reversed and
  oversize ranges, and continuation forms "(b)(2) and (b)(4)" inheriting the
  section.
* Planner: intent detection and requirement decomposition on the audit's 47
  questions (expected plans written by hand, no model).

Stage 2

* `FakeDatabase` tests: two references → two exact queries; parent
  reference → parent plus children; fallback suppressed when every provision
  requirement has tier-1 evidence; trigram digit-similarity rows excluded
  when tier-1 exists; guardrails respected.
* Ranking: tier ordering invariants (any tier-1 above any tier-4; two
  tier-1 rows ordered by requirement order then ordinal).

Stage 3

* Coverage: full, partial, none; verified-absent; parent covering a child
  request; child not covering a parent request.
* Targeted retrieval: missing provision fetched on second pass; absent
  provision produces a note, not a loop (bounded to one targeted pass).
* Gate: proceed / proceed_with_gaps / refuse matrices; prompt is never
  modified by the gate (existing invariant test kept).
* Context: tier-1 rows never dropped for budget while guidance is present;
  header lists requirement-to-source mapping.

Stage 4

* Validator with `FakeGenerator` outputs: truncation, repetition,
  completeness per requirement, refusal with evidence, unsupported section
  numbers, citation support scores on constructed answers.
* Prompt shape by intent; citation manager includes only used or tier-1
  sources; conversation resolution ("that", "it", "this requirement",
  "which part") against a stored state, and no resolution when the new
  question carries its own references.

Stage 5

* New dataset `architecture_v1.jsonl` with per-question
  `expected_references`, `expected_evidence` (natural keys) and
  `expected_behaviour` (answer / insufficient / refuse); the audit's 47
  questions form its first cohort. Metrics: reference-extraction accuracy,
  retrieval recall per requirement, evidence coverage, answer completeness,
  citation support, unsupported-claim rate, false-refusal rate, truncation
  rate, repetition rate, context efficiency (chars of tier-1/2 over total),
  latencies.
* Regression: `baseline_v1`, `retrieval_v1/v2` still run unchanged; Stage 7
  and Stage 13 result files remain the comparison baseline.
* Integration: `tests/integration/test_retrieval_db.py` gains
  multi-reference exact retrieval against the live snapshot (820.10 is a
  convenient fixture because the audit documented it, but tests must also
  use at least two other sections so nothing is special-cased).

---

## 16. Risks

| Risk | Mitigation |
|---|---|
| Bare-number parsing produces false positives ("2.1 million", "Phase 3.2") | require paragraph tokens or a verified section number via the identifier index; keep a negative test table |
| Range expansion overshoots or mis-orders (roman vs alphabetic "(i)") | bound expansion; verify each element; treat "(i)" after "(h)" as alphabetic and after "(A)"-level as roman using the parent's depth |
| Removing the fallback for identifier questions loses useful guidance context | do not remove; gate it on tier-1 presence and a minimum score; measure with the D-category questions |
| Per-requirement retrieval multiplies database round trips | one exact query per reference is cheap (indexed, sub-10 ms); cap by `max_candidates`; batch when references share a section (the existing parent query already returns all children) |
| Context grows with many provisions and slows CPU generation | tier-aware budget; for large ranges, prefer the parent query and compact rendering; guardrail `max_context_chars` |
| Validator rejects good answers (over-strict completeness) | completeness is a flag first, a replacement only when tier-1 evidence exists and the answer refuses, or when unsupported identifiers appear; thresholds tuned on the architecture dataset, not on `baseline_v1` |
| Conversation resolution applies stale state to an unrelated question | resolve only when the new question has no references and contains an anaphor; expose `resolved_from_state` in the response |
| Breaking the evaluation baseline reproducibility | keep `RagPipeline.answer()` and `answer_fn()` shapes; new fields default; a "legacy mode" flag can re-run the Stage 7 configuration for comparison |
| Special-casing 820.10 by accident | tests and datasets must cover at least three parts; no literal section numbers in production code |

---

## 17. Performance considerations

* Measured today: retrieval 0.7 to 10.5 s (fallback dominates variance),
  generation 8 to 80 s at 1.6 tokens/s, end-to-end median 31 s.
* Planned retrieval changes reduce work on identifier questions: one exact
  query per reference (each a few ms) and no fallback when tier-1 evidence
  exists. The fallback's second full-text pass over both corpora is the
  costliest leg today.
* Context size should not grow for single-provision questions and should
  grow proportionally for multi-provision ones; the prompt for four
  children plus parent (about 950 chars of eCFR text) is smaller than
  today's typical prompt with two 1,200-char guidance chunks.
* Generation: a per-request token budget (base plus per-requirement
  increment, hard cap) prevents truncation on lists without paying for long
  outputs on simple questions. Repetition control costs nothing measurable.
* Validation is string processing, negligible. Targeted retrieval adds at
  most one extra retrieval pass.
* The identifier index's cached SELECTs keep verification of expanded ranges
  cheap; cache per process, already implemented.
* Latency optimisation beyond this (quantisation, a larger machine, a
  different model) belongs to Stage 6, after correctness is measured.

---

## 18. Backward compatibility considerations

* `parse_cfr_reference()`, `classify()`, `LexicalRetriever.run()`,
  `RagPipeline.answer()`, `RagAnswer`, `RagGenerationResult`, and
  `run_evaluation()` keep their signatures; new fields have defaults.
* `RagConfig.top_k` remains accepted and becomes the candidate-pool
  guardrail; `min_trigram_similarity`, `no_context_behavior`,
  `exclude_contextual_only` keep their meaning.
* `GroundingGate.check_identifier()` / `check_context()` remain for the
  Stage 13 evaluation scripts; `GroundingConfig.enabled` default stays
  `False` until Stage 5 shows the plan-level gate is safe as a default.
* Stage 12/13 adapters, datasets, result files and the three benchmark
  files are untouched. The `--adapter` and `--grounding` flags keep working.
* The hybrid and semantic retrievers implement `Retriever.search()`; the
  new `run_plan()` should be added to the `Retriever` protocol as optional
  (`hasattr` check) so they continue to work in legacy mode.
* The UI's request body is unchanged; responses only gain fields.

---

## 19. What must not be changed

* The PostgreSQL database: contents, schema, indexes, the 1024-d embeddings
  (unused, provenance unverified). All access stays SELECT-only through
  `Database`.
* `data/evaluation/datasets/baseline_v1.jsonl`, `retrieval_v1.jsonl`,
  `retrieval_v2.jsonl`, and all result files under
  `data/evaluation/results/`.
* Stage 11 dataset v1 and the Stage 12/13 artefacts under `models/` and
  `data/training/`.
* `sql.py` statements (they are correct); new needs are met by new
  statements, not edits to existing ones.
* The exact-beats-text ranking invariant and the deterministic tie-break.
* The deterministic refusal path for verified-absent identifiers and the
  rule that citation labels come only from stored metadata.
* The rule that the gate never edits the prompt.
* The Stage 7 configuration must remain runnable for comparison.
* No fine-tuning, no new adapters, no changes to `configs/model_training*.yaml`
  during Stages 1 to 5.

---

## 20. Does the current architecture require model training before these problems can be solved?

No. The evidence from the audit attributes the failures as follows:

* Missing content (one of four provisions, unhandled ranges and lists, bare
  references, wrong-domain results for uncited questions, lost follow-up
  context) is caused by the parser, the fixed-shape retriever, the absence
  of coverage checking and the absence of conversation state. None of these
  involve the model. They are solved by Stages 1 to 3 in ordinary code.
* Invented content is produced by the model, but in five of six cases it was
  assembled from unrelated text that the fallback and trigram legs placed in
  the context. Removing that text (Stage 2), telling the model which
  provisions are missing (Stage 3), and validating the answer against the
  evidence (Stage 4) address the trigger and catch the residue without
  changing the weights.
* The model demonstrably does the core job when given the right evidence:
  8 of 8 single-provision questions were answered faithfully, and with all
  five 820.10(b) rows in context it summarised three of four children.
  Whether it can reliably enumerate four or more provisions in a structured
  answer is the open question; it is a prompting, token-budget and
  validation question first (Stage 4) and only then a model-capacity
  question (Stage 6).
* The Stage 13 experiment already showed the limits of training on this
  model: it reduced unsupported answers but taught over-refusal. Training
  cannot supply evidence the retriever never fetched.

So training is not a prerequisite. After Stage 5 measures the corrected
architecture, the remaining failure patterns that are purely generative
(false refusals on certain phrasings, omissions with full evidence,
formatting) will show whether prompting and decoding suffice, whether a
larger base model is warranted, or whether a targeted fine-tune on
evidence-faithful enumeration is justified.

---

## Appendix: facts established during discovery that shape the design

* The database's `cfr_cross_references` table (17,168 rows, 15,655
  resolvable) captures "§ 820.1(a)" and "paragraph (c)(1) of this section"
  forms but not "part 830 of this chapter", which is the form used by
  820.10(b)(1) to (b)(4). Tier 3 (directly referenced regulations) therefore
  needs a small "part N of this chapter" parser over the evidence text; the
  table can supply the section-level references.
* `ECFR_EXACT_SECTION` already returns a requested paragraph together with
  all its descendants. A parent reference is the cheapest way to fetch a
  whole enumerated set; the selector can prefer it when a range covers all
  children of one parent.
* `RetrievalResult.metadata` already carries `match_kind` ("exact" /
  "descendant") and `requested`, which map directly onto tier 1 and tier 2.
* `GenerationResult` has no finish reason; truncation detection needs one
  line in `generate_chat` to compare the last token with the end-of-turn id.
* The chat CLI keeps raw model messages and never retrieves; conversation
  state for retrieval must be built fresh and should be compact
  (mission section 20), not the raw message list.
* Test fakes exist for the database, retriever, generator and identifier
  index, so every new component can be unit-tested without the 30-second
  model call.
