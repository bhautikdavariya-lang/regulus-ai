# Regulus AI: Model System Audit and Test Report

**Scope:** read-only audit of the current implementation. No source file,
configuration, prompt, model, adapter, index, database row or benchmark was
modified. The only files written are this report and the raw test evidence
under `audit/`.

**Audited configuration:** the project default. Base `Qwen/Qwen3-0.6B`
(no adapter), `LexicalRetriever` with the Stage 7 OR fallback, `RagConfig`
defaults (top_k 8, context 8 sources / 1,200 chars each / 3,600 total),
greedy decoding, 128 new tokens, grounding gate off unless stated. All
generation tests were executed through `scripts/serve_ui.py`, which
constructs the same `RagPipeline` the evaluation scripts use. Raw responses
for every test are in `audit/results/battery.jsonl`.

**Date:** 2026-09-22. Machine: CPU only, 4 threads, 8.5 GB RAM. Database:
PostgreSQL 18.4, eCFR snapshot 2026-09-03.

---

## 1. Executive Summary

| Component | Status | Evidence |
|---|---|---|
| Database | PASS | 65,341 eCFR paragraph rows, one per paragraph; 820.10(b), (b)(1), (b)(2), (b)(3), (b)(4) each exist as an independent row (section 4); read-only enforced by the server |
| Exact CFR retrieval | PASS | every single-provision query returns the requested row at rank 1 with score 100.0 (section 15); a parent paragraph returns itself plus all children at 95.0 |
| Semantic retrieval | FAIL (by design, not wired) | no vector search is on the default path; `LexicalRetriever` is exact + full-text + trigram only; the semantic/hybrid retrievers exist as opt-in experiments and are not audited here |
| Query parsing | PARTIAL | one CFR reference per question, always the first; no range expansion; no multi-citation; forms without "CFR", "§", "section" or "part" are not recognised as identifiers (section 7) |
| Multi-provision retrieval | FAIL | "(b)(1) through (b)(4)" retrieves (b)(1) only: coverage 1/4; "(b)(1) and (b)(2)" retrieves (b)(1) only: 1/2 (section 16) |
| Ranking | PASS | deterministic, exact identifiers always outrank text matches; no reranker; scores from different methods are on documented but non-comparable scales (section 8) |
| Grounding Gate | PARTIAL | blocks generation only when a *recognised* identifier is verified absent, or exists but no retrieved row carries it; does nothing for identifier-free questions; never checks entailment, coverage or citation support (section 10) |
| Evidence coverage | FAIL | no component computes or checks whether every requested provision was retrieved; the gate checks that *at least one* row carries the single parsed identifier (section 10) |
| Generation | PARTIAL | single provisions answered accurately from evidence; hedges and general-knowledge leakage on identifier-free questions; token cap truncates multi-item answers (sections 15, 17, 20) |
| Citations | PASS (mechanism) / PARTIAL (support) | citations never come from the model; they are the retrieved sources' labels; whether `[n]` markers in the answer point at the supporting source is not verified anywhere (section 12, 19) |
| Test Module | PARTIAL | reproducible runner, saved metadata, grounding metrics; reviewer scores are manual 0/1/2; no multi-provision, coverage or completeness metric exists; benchmark has no 820.10 question (section 13) |
| Performance | PASS (measured) | retrieval 0.14 to 1.2 s; generation 20 to 60 s on this CPU; end-to-end 30 to 70 s (section 22) |


---

## 2. System Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │  PostgreSQL 18.4  "regulus"  (READ-ONLY)     │
                         │  cfr_records 65,341 paragraphs (Title 21)    │
                         │  fda_guidance 1,836 docs / 1,208 retrievable │
                         │  fda_guidance_chunks 68,669 (~1,440 chars)   │
                         │  GIN tsvector + pg_trgm indexes              │
                         │  halfvec(1024) embeddings: present, UNUSED   │
                         └───────────────┬──────────────────────────────┘
                                         │ SELECT only (server-enforced)
   question ──► regulus.retrieval.query.classify()
                   │  parse_cfr_reference()  → FIRST CFR ref only
                   │  parse_docket()
                   ▼
              regulus.retrieval.lexical.LexicalRetriever.run()
                   │  exact_cfr / exact_docket  (score 100 / 95 descendants)
                   │  full_text (websearch_to_tsquery, ts_rank_cd ×50)
                   │  trigram   (section number / heading, ×5)
                   │  OR fallback if primary hits < 3  (×5 / n_terms)
                   │  merge() dedup by key, strongest method, sort desc
                   ▼  top_k = 8
              regulus.rag.pipeline.RagPipeline.answer()
                   │  select_useful(): drop trigram-only < 0.4 similarity
                   │  build_context(): ≤ 8 sources, ≤ 1,200 chars each, ≤ 3,600 total
                   │  [GroundingGate, optional]: identifier exists? context carries it?
                   │       refuse → deterministic text, model NOT called
                   │  no context → NO_CONTEXT_ANSWER, model NOT called
                   ▼
              regulus.rag.prompt.build_messages()   (system rules + SOURCES block)
                   ▼
              regulus.inference.generate.generate_chat()  Qwen3-0.6B, greedy, 128 tok
                   ▼
              RagPipeline.build_citations()  ← labels from retrieved sources, never from the model
                   ▼
              RagAnswer {answer, citations, sources, grounding, timings}
                   │
     ┌─────────────┼──────────────────────────┐
     ▼             ▼                          ▼
 scripts/rag.py  scripts/evaluate_baseline.py  scripts/serve_ui.py + web/index.html
 (CLI)           (benchmark runner)            (local browser console)
```

Not on the default path: `regulus.retrieval.semantic` (bge-small index,
Stage 8/10), `regulus.retrieval.hybrid` (Stage 9), the LoRA adapters
(`models/qwen3-0.6b-lora/stage12_v1`, `stage13_v1`), and the training
packages `regulus.training` / `regulus.finetune`. All are opt-in.

---

## 3. Repository / Code Structure

```
src/regulus/
  config/settings.py        YAML + REGULUS_* env → ModelConfig, GenerationConfig
  model/{device,loader}.py  device/dtype resolution; Hub loading with local cache
  inference/generate.py     generate_chat(): chat template, greedy/sampling, token counts
  retrieval/
    db.py                   Database: one psycopg connection, read-only forced twice
    query.py                classify(), parse_cfr_reference(), parse_docket(), fallback_terms()
    sql.py                  six parameterised SELECTs (exact section/part, full-text, trigram, guidance)
    ranking.py              score constants, merge()
    lexical.py              LexicalRetriever.run()  ← the production retriever
    citations.py            build_ecfr_citation(), build_guidance_citation()
    models.py               Citation, RetrievalResult (natural key, no DB ids)
    base.py                 Filters, Retriever protocol
    hybrid.py, semantic/    experimental; not on the default path
  rag/
    context.py              ContextPolicy, build_context() (budget: drop, never squeeze below 200 chars)
    prompt.py               RAG_SYSTEM_PROMPT, NO_CONTEXT_ANSWER, build_messages()
    generator.py            QwenGenerator wrapper
    pipeline.py             RagPipeline.answer(): retrieve → filter → context → gate → generate → cite
  grounding/
    identifiers.py          extract_identifier(), verify_identifier(), Corpus/Database indexes
    gate.py                 GroundingGate.check_identifier(), check_context(), refusal_text()
  evaluation/
    dataset.py, runner.py, results.py   benchmark loading, run loop, persistence, aggregation
    retrieval_eval.py       Recall@K / MRR / precision / negative controls (retrieval-only benchmark)
    grounding_eval.py       refusal / unsupported / false-refusal / identifier / citation metrics
  training/, finetune/      dataset generation and LoRA training (not audited; not on the answer path)
scripts/
  rag.py, chat.py, run_inference.py            CLIs
  evaluate_baseline.py (+ --adapter, --grounding)  the benchmark runner
  evaluate_retrieval.py, compare_runs.py, compare_grounding.py, analyze_failures.py
  serve_ui.py + web/index.html                 local test console
tests/                      24 files, unit + integration + slow; 302 fast tests at last run
data/evaluation/datasets/   baseline_v1 (27 Q), retrieval_v1 (28), retrieval_v2 (52)  ← protected
docs/                       one design document per stage
```

Files inspected for this audit are listed in Appendix A.

---

## 4. Database / Knowledge Base

| Item | Observed |
|---|---|
| Technology | PostgreSQL 18.4, extensions vector 0.8.6, pg_trgm, citext |
| Access | `regulus.retrieval.db.Database`; `options="-c default_transaction_read_only=on"` plus `conn.read_only=True`; any write raises `ReadOnlySqlTransaction` (verified by integration tests) |
| eCFR unit | `cfr_records`: **one row per paragraph**, 65,341 live rows; `body_text` avg 218 chars, median 155, max 3,388. No further chunking |
| Identifier fields | `section_number` ("820.10"), `paragraph_path` ("(b)(1)"), `path_ordinal`, `ordinal` (document order), `part_number`, `subchapter_code`, `section_heading`, `parent_headings[]` |
| Guidance unit | `fda_guidance_chunks`: 68,669 chunks, 213 to 1,501 chars (avg 1,440), consecutive overlap ~199 chars; no page/heading position, only `start_offset` |
| Guidance authority metadata | `status` (draft/final), `doc_class`, `center`, `retrievable`, `issued_on`, `withdrawn_at`, `supersedes_id`, `docket_number`, `anchor_part/section` |
| Version / date fields | `snapshot_date` (all 2026-09-03), `content_sha256`, `retrieved_at`; `last_amended_date` and `effective_date` exist but are not populated with real amendment dates |
| Lexical indexes | GIN on `search_vector` (cfr_records, fda_guidance_chunks); pg_trgm GIN on section number and heading (cfr_records, cfr_sections) |
| Vector indexes | HNSW cosine on `halfvec(1024)` in both content tables; **not used by any default code path** (provenance UNVERIFIED, `docs/embedding_provenance.md`) |

**Do the requested provisions exist independently?** Yes.

| Provision | Rows | Chars | Text begins |
|---|---|---|---|
| 820.10(b) | 1 | 223 | "(b) Applicable regulatory requirements. Comply, as appropriate, with the other applicable regulatory requirements in this title, including ... to fully comply with the listed ISO 13485 Clause:" |
| 820.10(b)(1) | 1 | 216 | "(1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must document a system to assign unique device identification ... part 830" |
| 820.10(b)(2) | 1 | 197 | "(2) For Clause 7.5.9.1 in ISO 13485, Traceability—General, the manufacturer must document procedures for traceability ... part 821 ..., if applicable" |
| 820.10(b)(3) | 1 | 180 | "(3) For Clause 8.2.3 in ISO 13485, Reporting to regulatory authorities, the manufacturer must notify FDA of complaints that meet the reporting criteria of part 803" |
| 820.10(b)(4) | 1 | 139 | "(4) For Clauses 7.2.3, 8.2.3, and 8.3.3, advisory notices shall be handled in accordance with the requirements of part 806" |
| 820.10(b)(5) | 0 | | does not exist |

Note the parent (b) is a list introduction ending in a colon; its four
requirements live in the four child rows.

---

## 5. Document Processing

There is no ingestion, chunking or indexing code in this repository. The
database was populated by a previous platform (Prisma migrations, an
ingestion pipeline recorded in `ingestion_runs`). The project consumes it
as-is. Consequences for this audit:

* eCFR granularity is fixed at one paragraph per row. Nothing can be
  retrieved at a finer or coarser unit than the source stored.
* Guidance chunks carry no structural position beyond a character offset,
  so a guidance citation is document-level only.
* Chunking parameters cannot be changed from this codebase.

---

## 6. Retrieval Architecture

`LexicalRetriever.run()` (`src/regulus/retrieval/lexical.py`) executes, in
order, and unions the results:

| Leg | Runs when | SQL | Score |
|---|---|---|---|
| `exact_cfr` | `classify()` found a CFR reference | `ECFR_EXACT_SECTION` (row = section + paragraph, plus `paragraph_path LIKE '(b)(%'` descendants) or `ECFR_EXACT_PART` (first row of each section) | 100.0 exact, 95.0 descendant, minus 0.001 × ordinal |
| `exact_docket` | a docket number was found | `GUIDANCE_EXACT_DOCKET`, opening ≤ 3 chunks | 100.0 minus 0.001 × ordinal |
| `full_text` (both corpora) | always | `websearch_to_tsquery('english', query)` over the GIN tsvector; guidance capped at 3 chunks per document | 50 × `ts_rank_cd(..., 1)` |
| `trigram` | query ≤ 4 words, or looks like an identifier, or eCFR full-text under-delivered | `%` similarity on `cfr_sections.number` and `heading`, first live row of each hit | 5 × similarity |
| `full_text_or` (fallback) | primary hits (exact + full_text) < 3 | same full-text SQL with `term1 or term2 ...` from `fallback_terms()` (≤ 8 terms) | 5 × rank / n_terms |

Then `merge()`: de-duplicate by natural key, keep the strongest method
(exact > full_text > or = trigram), score = max, sort by score desc then key,
cut to `top_k`.

Observed on the 820.10 questions (retrieval only, `audit` run, section 15):
* full-text over eCFR returned **0** rows for every "What does 21 CFR
  § 820.10(b)(n) require?" question: the question's words do not appear in
  the paragraph, so the AND query fails.
* The fallback therefore fired on (b)(1) and on every multi-provision
  question, adding guidance chunks and unrelated sections (Container
  Closure Systems guidance, 866.2190(b)(7), 4.4(b)(1)(i)) at scores 0.3 to
  1.2, below the exact hit.
* `top_k` is global over the merged list, not per requested provision.
* There is **no reranker**, no semantic leg, no source-authority weighting
  beyond the fixed method scales, and no relevance threshold except the
  trigram cut-off (0.4) applied later in `select_useful()`.

---

## 7. Query Parsing / CFR Detection

`src/regulus/retrieval/query.py`. Four regexes tried in order; the first
match wins:

1. `21 CFR 820.10(b)(1)`, `21 C.F.R. § 820.10`, `CFR Part 820`
2. `§ 820.10(b)(1)`
3. `section 820.10(b)`
4. `part 820`

`parse_cfr_reference()` is documented and implemented as *"Return the first
CFR reference found in the text, or None."* Measured on the audit phrasings:

| Question | Classified as | Parsed reference | References actually present |
|---|---|---|---|
| ...§ 820.10(b)(1) and § 820.10(b)(2)? | EXACT_CFR | 820.10(b)(1) | (b)(1), (b)(2) |
| ...§ 820.10(b)(1), (b)(2), and (b)(3)? | EXACT_CFR | 820.10(b)(1) | (b)(1), (b)(2), (b)(3) |
| ...§ 820.10(b)(1) through (b)(4). | EXACT_CFR | 820.10(b)(1) | (b)(1), (b)(4) |
| Compare § 820.10(b)(2) and § 820.10(b)(4) | EXACT_CFR | 820.10(b)(2) | (b)(2), (b)(4) |
| §820.10(b)(1)-(b)(4) | EXACT_CFR | 820.10(b)(1) | range |
| §820.10(b)(1) through (b)(4) | EXACT_CFR | 820.10(b)(1) | range |
| §820.10(b)(1) to (b)(4) | EXACT_CFR | 820.10(b)(1) | range |
| 820.10(b)(1), 820.10(b)(2), 820.10(b)(3), 820.10(b)(4) | GENERAL_REGULATORY_SEARCH | none | four, but no "CFR"/"§"/"section" token |
| 820.10(b)(1)-(4) | GENERAL_REGULATORY_SEARCH | none | |
| subsections (b)(1) through (b)(4) of 820.10 | GENERAL_REGULATORY_SEARCH | none | |
| all requirements under 820.10(b) | GENERAL_REGULATORY_SEARCH | none | |
| What does 21 CFR § 820.10(b) require ...? | EXACT_CFR | 820.10(b) | parent |

Findings, all verified against code and by execution:

* **Ranges are not supported.** "(b)(1) through (b)(4)" and "(b)(1)-(b)(4)"
  parse as (b)(1). No expansion exists anywhere in the codebase.
* **Multiple citations are not supported.** Only the first is used; the
  rest are discarded before retrieval.
* **Bare numbers are not identifiers.** "820.10(b)(1)" without "CFR", "§",
  "section" or "part" is a general search. The parser's regex requires one of
  those tokens (`_CFR_RE`, `_SYMBOL_RE`, `_SECTION_WORD_RE`, `_PART_WORD_RE`).
* The seven Category C phrasings are therefore **not** treated equivalently:
  three parse to (b)(1), four parse to nothing.
* The one form that reaches all four children is the **parent** reference
  820.10(b), because `ECFR_EXACT_SECTION` includes descendants
  (`paragraph_path LIKE '(b)(%'`).

---

## 8. Ranking / Top-K

* `top_k` = 8, applied once to the merged list (`merge(candidates, top_k)`).
  Before merging, each leg fetches `limit = top_k × 2 = 16` candidates
  (guidance full-text fetches 160 then caps at 3 per document).
* Score scales are fixed constants, not learned and not calibrated against
  each other: exact 100/95, full-text 50 × rank (observed ≤ ~30), trigram
  5 × similarity (≤ 5), OR-fallback 5 × rank / n (≤ ~1.5). The design
  intent, stated in `ranking.py`, is that any exact identifier hit outranks
  any text hit; that holds.
* Ties broken by natural key for determinism. Reproduced byte-identical in
  the Stage 12 control run.
* No reranking, no cross-encoder, no MMR, no per-provision quota.
* Source authority: exact CFR rows score 100 and guidance chunks reach it
  only via an exact docket; otherwise guidance and eCFR full-text compete on
  the same 50 × rank scale. There is no explicit "prefer primary source" rule
  beyond that.

---

## 9. Context Construction

`build_context()` (`src/regulus/rag/context.py`):

* Walks results in retriever order. Each becomes a `SOURCE n` block with
  corpus, citation, heading (eCFR only), URL and text.
* Per-source cap 1,200 chars (truncation marked); total cap 3,600 chars;
  at most 8 sources. A source that would exceed the total is squeezed only if
  ≥ 200 chars would remain, otherwise **dropped**, and the count is reported
  as `dropped`.
* `select_useful()` runs first and removes trigram-only hits with similarity
  < 0.4 and (Stage 9) results flagged `contextual_only`.
* Retriever notes (for example "No live record for 21 CFR 820.999 in this
  eCFR snapshot") are appended as `NOTE:` lines inside the context.
* No relevance threshold is applied to full-text or fallback results: a
  fallback hit at score 0.29 reaches the prompt if it is within the first 8.

---

## 10. Grounding Gate

`src/regulus/grounding/gate.py`, `GroundingGate`. **Disabled by default**
(`GroundingConfig.enabled = False`); the UI checkbox and the
`--grounding` flag construct it with `enabled=True`.

### When it executes

Inside `RagPipeline.answer()`, **after** retrieval, `select_useful()` and
`build_context()`, and **before** generation. It receives the question
string and the list of `RetrievalResult` objects that made it into the
context.

### What it checks, in order

1. `extract_identifier(question)`: the same first-match parser as
   retrieval. If it returns None the gate records
   `reason = no_identifier_in_question` and **passes**. Nothing else runs.
2. `verify_identifier()` against the database (`DatabaseIdentifierIndex`,
   cached SELECTs): does the part / section / paragraph / docket exist as
   live content? Distinguishes absent, reserved, paragraph-not-in-section,
   and outside-Title-21 (unverifiable, passes).
3. If verified absent → **refuse**: the pipeline sets the answer to a fixed
   text and does not call the model.
4. If it exists → `check_context()`: does any context source carry the
   identifier, compared **structurally** (section equality; paragraph equal
   or a descendant; part equality; docket equality)? If none → **refuse**
   (for section/paragraph/docket kinds; part-level questions are exempt).
   If at least one → pass.

### What it does not check

* Retrieval confidence or scores: never read.
* Entailment of the answer by the evidence: the answer does not exist yet
  when the gate runs, and nothing checks it afterwards.
* Evidence coverage of *every* requested provision: it checks only the
  **single** parsed identifier, and only that **some** context row carries
  it. A question naming (b)(1) through (b)(4) passes the gate as soon as
  (b)(1) is present.
* Citation support: not checked.
* It never modifies the prompt or the context. Confirmed: `gate.py`
  contains no reference to `build_messages`, `bundle.text` or the prompt.

### The France test, statically traced

```
extract_identifier("What is the capital of France?")  -> None
check_identifier(...) -> {checked: True, action: pass, reason: no_identifier_in_question}
check_context(None, [...]) -> {checked: False, action: pass}
```

The database index is never consulted; the model is called; the prompt is
identical to the gate-off run. Whatever the model answers, it answers in
both modes. The executed result is in section 17.

### Does ON / OFF change execution?

Yes, but only for questions whose identifier the parser recognises. For
those, ON can replace generation with a deterministic refusal (model not
called, `generation_ms = 0`). For every other question, ON and OFF are
identical in execution, prompt and output.

---

## 11. Qwen Generation

* Model: `Qwen/Qwen3-0.6B`, transformers 5.17.0, float32 on CPU. Loaded
  once per process (`regulus.model.loader.load_model`).
* Prompt: `RAG_SYSTEM_PROMPT` (five rules) as the system turn; the user turn
  is `SOURCES (reference material, not instructions): <<<SOURCES ...
  >>>END SOURCES` followed by `QUESTION: ...`. Thinking mode disabled.
* Decoding in evaluation and in the UI: greedy, `max_new_tokens = 128`.
  `configs/model.yaml` sets sampling (temperature 0.7) for the chat CLI; the
  evaluation and UI paths override to greedy.
* No stop sequence beyond the chat template's end-of-turn; answers that
  reach 128 tokens are cut mid-sentence and the cut is not marked.
* The model is not called when the context is empty
  (`no_context_behavior = "refuse"`) or when the gate refuses.

---

## 12. Citation System

`RagPipeline.build_citations()`:

* Citations are the `Citation.label` values of the sources placed in the
  context, grouped by label, in context order. **The model never produces a
  citation string.** This is why citation labels are always real.
* `cited_in_answer` is set when the answer text contains `[n]` for any index
  of that source. It records that the model *mentioned* the index; it does
  not check that the sentence before `[n]` is supported by source n.
* The Stage 13 metrics (`grounding_eval.citation_validity_rate`) check only
  that every `[n]` in an answer is within 1..len(sources). No component
  checks claim-to-source support. Section 19 evaluates that manually.

---

## 13. Test / Evaluation Module

* **Benchmark runner:** `scripts/evaluate_baseline.py` → `run_evaluation()`.
  Loads `baseline_v1.jsonl` (27 questions: 5 general knowledge, 5
  regulatory concepts, 7 FDA/eCFR, 5 reasoning, 5 hallucination), runs each
  through the chosen pipeline, saves a JSON with full metadata, per-question
  diagnostics (retrieved, context, citations, timings, grounding) and
  objective aggregates. Deterministic under greedy decoding; a control run
  reproduced Stage 7 byte for byte.
* **Quality scores:** manual 0/1/2 written into the result file after the
  run (`quality_score`, `manual_evaluation`), labelled as assistant reviewer
  judgments. There is no automatic correctness scorer.
* **Grounding metrics:** `regulus.evaluation.grounding_eval`: refusal rate,
  unsupported-answer rate, hedged count, false-refusal rate, identifier
  grounding, citation-marker validity, degeneration, gate activity.
  Classification of an answer as refusal / hedged / answer is heuristic
  (phrase lists plus sentence splitting).
* **Retrieval benchmark:** `scripts/evaluate_retrieval.py` over
  `retrieval_v1/v2.jsonl`: Recall@K, MRR, precision, negative controls.
* **Gaps relevant to this audit:** the benchmark contains **no** 820.10
  question and **no** multi-provision or range question; there is no
  evidence-coverage metric, no generation-completeness metric, no
  claim-level citation check, and no multi-turn test. The retrieval
  benchmark's `target_matches()` treats any paragraph of a target section
  as a hit, so it cannot distinguish (b)(1) from (b)(2).

---

## 14. Test Methodology

* 47 questions across categories A to K plus the special 820.10 set, run
  once each through the local server (`POST /api/ask`), base model, greedy,
  top_k 8, 128 tokens; gate off unless the test id ends in `-on`.
* Every response saved in full to `audit/results/battery.jsonl`
  (answer, citations, all context sources with text and scores, grounding
  decision, retrieval diagnostics, timings, token counts).
* Retrieval-only probes for the 820.10 set were run separately through
  `LexicalRetriever.run()` to separate retrieval from generation.
* Follow-up questions (Category K) were run as standalone questions
  because `RagPipeline` is single-turn and has no conversation state; the
  chat CLI keeps history in memory but does not feed it to retrieval.
* Coverage and completeness are computed against the four provision rows
  in section 4. Reviewer judgments are labelled as such.

---

## 15. Test Results by Category

All 47 executed tests, base model, greedy, 128 tokens. "Parsed" is what the
query parser extracted. "Exact rows in context" lists which of the four
820.10(b) child rows reached the prompt. "In answer" lists which provisions'
substance the answer contained. Classification uses the project's own
`classify_answer` (answer / hedged / refusal). Correctness judgments are the
auditor's and are labelled as such.

### Category A: individual provisions (4/4 correct)

| Test | Parsed | Exact rows in context | Answer (abridged) | Judgment |
|---|---|---|---|---|
| A1 (b)(1) | 820.10(b)(1) | (b)(1) | "requires that the manufacturer document a system to assign unique device identification ... part 830 ... [1]" | correct, cited |
| A2 (b)(2) | 820.10(b)(2) | (b)(2) | "document procedures for traceability ... part 821 ..., if applicable." | correct, no marker |
| A3 (b)(3) | 820.10(b)(3) | (b)(3) | "notify the FDA of complaints that meet the reporting criteria of part 803" | correct, no marker |
| A4 (b)(4) | 820.10(b)(4) | (b)(4) | "advisory notices be handled in accordance with the requirements of part 806" | correct, no marker |

Each answer is a faithful paraphrase of the single retrieved row. The
ISO 13485 clause reference present in every row was omitted in all four.

### Category B: multi-provision (0/5 complete and correct)

| Test | Parsed | Exact rows in context | In answer | Outcome |
|---|---|---|---|---|
| B1 (b)(1) and (b)(2) | (b)(1) | (b)(1) only | (b)(1) | (b)(1) correct; then "(b)(2) are not provided in the available sources" (true given the context; wrong for the user) |
| B2 (b)(1), (b)(2), (b)(3) | (b)(1) | (b)(1) only | (b)(1) | (b)(1) correct; **(b)(2) fabricated** from 21 CFR 1.360(a) ("create the required records when you receive and release food"); **(b)(3) fabricated** from 21 CFR 112.121 ("identify equipment and tools ... contact"); cut at 128 tokens |
| B3 (b)(1) through (b)(4) | (b)(1) | (b)(1) only | (b)(1) | bullet list of three restatements of (b)(1), the second and third padded from the UDI guidance chunk; (b)(2) to (b)(4) absent; cut at 128 tokens |
| B4 compare (b)(2) and (b)(4) | (b)(2) | (b)(2) only | (b)(2) | (b)(2) correct; **(b)(4) fabricated** as "additional procedures for traceability ... 820.10(b)(1) and part 830"; the real (b)(4) (advisory notices, part 806) never appears |
| B5 explain (b)(1) to (b)(4) | (b)(1) | (b)(1) only | (b)(1) | numbered list: (1) correct; **(2) and (3) fabricated from the cigarette-warning guidance chunk** ("text of the required warning must appear in the predominant language"); cut at 128 tokens |

Evidence coverage for Category B: 1 of 2, 1 of 3, 1 of 4, 1 of 2, 1 of 4
requested rows retrieved. Generation completeness for the *retrieved* row:
5 of 5. Fabrication for the *missing* rows: 3 of 5 tests produced
confident false content for provisions that were not in the context (B2, B4,
B5); 1 (B1) admitted the gap; 1 (B3) padded with near-duplicates.

### Category C: range and bare phrasings (0/7 answered; 0/7 fabricated)

| Test | Query type | Parsed | Exact rows in context | Outcome |
|---|---|---|---|---|
| C1 §820.10(b)(1)-(b)(4) | EXACT_CFR | (b)(1) | (b)(1) | refusal, and it correctly says the sources "only include the text of §820.10(b)(1)" |
| C2 §820.10(b)(1) through (b)(4) | EXACT_CFR | (b)(1) | (b)(1) | refusal (hedged form) |
| C3 §820.10(b)(1) to (b)(4) | EXACT_CFR | (b)(1) | (b)(1) | **degenerate**: the refusal sentence repeated until the 128-token cap |
| C4 820.10(b)(1), 820.10(b)(2), ... | GENERAL | none | none | refusal; context is the 820.10 intro (trigram) + guidance |
| C5 820.10(b)(1)-(4) | GENERAL | none | none | refusal; context 820.10 intro + 820.1(a) |
| C6 subsections (b)(1) through (b)(4) of 820.10 | GENERAL | none | none | refusal; context is two labeling guidance chunks about "subsections" |
| C7 all requirements under 820.10(b) | GENERAL | none | none | refusal; context is QMS guidance + 21 CFR 1100.2 (tobacco) |

The seven phrasings are not handled equivalently. Three reach the (b)(1) row
through the parser; four never trigger exact retrieval at all. None reaches
(b)(2) to (b)(4). No fabrication occurred in this category: the model refused
in every case, one of them degenerately.

### Special Test A: parent paragraph (retrieval PASS, generation PARTIAL)

| Test | Parsed | Exact rows in context | In answer | Outcome |
|---|---|---|---|---|
| S1 "What does 21 CFR § 820.10(b) require ...?" | 820.10(b) | **(b), (b)(1), (b)(2), (b)(3), (b)(4)** at 100 / 95 | (b)(1), (b)(2), (b)(3) | "comply with the requirements outlined in ISO 13485, including assigning UDI ..., documenting traceability procedures, and notifying regulatory authorities of complaints. ... [1]"; **(b)(4) omitted** although it was in the context |

This is the only path in the system that assembles all four child rows. The
model then summarised three of the four and dropped advisory notices. The
answer also slightly misstates the parent: (b) says comply with *other
applicable regulatory requirements in this title* needed to comply with the
listed ISO clauses, not "comply with the requirements outlined in ISO 13485".

### Category D: general regulatory, no citation (1/5 useful)

| Test | Retrieval mode | Context | Outcome |
|---|---|---|---|
| D1 traceability requirements | trigram only, 6 rows | 21 CFR 111.355, 1.361, 111.360, 111.83(a), 111.65, 1.402(a) (dietary supplements / food) | hedged answer that presents 111.355 and 111.360 as "the traceability requirements", then appends the refusal sentence. Wrong domain; 820.10(b)(2) and part 821 never retrieved |
| D2 notify FDA about a complaint | full_text, 820.10(b)(3) rank 1 (score 3.1) | (b)(3) + two unrelated guidance chunks | correct content "complaints that meet the reporting criteria of part 803 ... [1]", then the refusal sentence appended (hedged) |
| D3 advisory notices | trigram only, 8 rows | 111.13(a), 112.133, 112.129 ... (toilet facilities, plumbing) | refusal. 820.10(b)(4) / part 806 never retrieved |
| D4 unique device identification | full_text, 8 rows of 21 CFR 830.310 | correct part | hedged: opens with the refusal sentence, then a partially correct summary of 830.310, then "the question does not specify which part ..." |
| D5 records requirements for device manufacturers | fallback only | two MDDS guidance chunks | refusal |

### Category E: unsupported questions, gate OFF vs ON (identical in all four pairs)

| Test | OFF answer | ON answer | Gate decision |
|---|---|---|---|
| E1 capital of France | "**The capital of France is Paris.** The available regulatory sources do not provide enough information to answer this." | identical | pass, `no_identifier_in_question` |
| E2 who wrote Hamlet | refusal | identical | pass, `no_identifier_in_question` |
| E3 boiling point of water | refusal | identical | pass, `no_identifier_in_question` |
| E4 control: 820.10(b)(2) | correct answer | identical | pass, `context_matches_identifier` |

E1 is a general-knowledge leak in both modes. The gate did not, and by
design could not, intervene: it has no identifier to verify and does not
evaluate the answer. The context for E1 was two fallback guidance chunks
matching the terms "capital" and "france" (U.K. plasma; a complete
submission), which the model ignored.

### Category F: partially supported (2/3 handled; 1 fabrication)

| Test | Outcome |
|---|---|
| F1 (b)(3) + population of Paris | correct: answers (b)(3), then "do not provide enough information ... population of Paris" (the "hedged" classification is a metric artefact of the appended refusal sentence) |
| F2 (b)(2) + 820.999 | (b)(2) correct; then **"21 CFR 820.999 requires the manufacturer to document procedures for traceability ..."**: a fabricated section, invented from the (b)(2) text. The parser took only 820.10(b)(2); 820.999 was never checked. Gate was off; with gate on the outcome would be the same because the gate also sees only the first identifier |
| F3 (b)(1) + Eiffel Tower | (b)(1) correct with a benign elaboration ("ensures that devices can be uniquely identified and tracked"), then a proper refusal for the Eiffel Tower |

### Category I: hallucination and constraint (gate changes 2 of 6)

| Test | OFF | ON |
|---|---|---|
| I1 21 CFR 314.999 (nonexistent) | refusal; context note says no live record | **gate refuse** in 1.6 s, model not called: "I could not verify 21 CFR 314.999 in the available eCFR data (Title 21 snapshot dated 2026-09-03) ..." |
| I2 Part 1400 (nonexistent) | refusal | **gate refuse** in 5.2 s, model not called |
| I3 penalty amount in (b)(3) | refusal (correct: no penalty exists) | not run with gate; would pass the gate, since (b)(3) exists and is in context |
| I4 FDA form number under (b)(4) | **fabrication**: "The FDA form number required under 21 CFR 820.10(b)(4) is FDA 3988. This form must be submitted electronically when required. [1]" | not run with gate; would pass the gate for the same reason |

I4 is the clearest hallucination in the battery. "FDA 3988" was lifted from
a fallback guidance chunk about animal-drug annual status reports (Forms FDA
3988 and 3989), retrieved because the question contained the words "form"
and "number". The answer cites [1], which is the (b)(4) row, which says
nothing about any form. The citation is structurally valid and semantically
false.

### Category J: paraphrase stability (3/5 answered, 2/5 refused)

| Test | Outcome |
|---|---|
| J1 What does §820.10(b)(3) require? | correct |
| J2 Explain §820.10(b)(3). | **refusal**, doubled sentence, with (b)(3) in context at rank 1 |
| J3 What must a manufacturer do under §820.10(b)(3)? | correct, cited [1] |
| J4 What obligation does §820.10(b)(3) impose? | **refusal**, with (b)(3) in context at rank 1 |
| J5 Under §820.10(b)(3), when must FDA be notified? | correct, cited [1] |

Retrieval was identical in all five (the (b)(3) row at 100 in first place).
The divergence is entirely in generation: the phrasings "Explain" and "What
obligation ... impose" produced false refusals. J4's fallback context
contained "obligation" hits from 312.52 (sponsor obligations), which may have
diluted the prompt, but J2's context was the same shape as A3's and it still
refused.

### Category K: follow-up questions (0/2 resolved; single-turn by design)

| Test | Outcome |
|---|---|
| K1 What does 21 CFR §820.10(b)(2) require? | correct |
| K2 Why is that requirement important? | retrieved 21 CFR 251.18 (drug importation) on the words "requirement/important"; answered confidently about **importer name and contact office address**; cites [1] |
| K3 Which part applies to that? | retrieved 21 CFR 822.4 (postmarket surveillance) on "part applies"; refusal |

The pipeline has no conversation state. Every question is retrieved and
answered independently. K2 is wrong relative to the user's intent, although
it is grounded in the (wrong) retrieved text.

---

## 16. Multi-Provision Query Analysis

**Fact (executed):** for every multi-provision question, exactly one child
row reached the model: the one named first. Coverage table:

| Test | Requested | Retrieved (exact) | Coverage | Answer covered | Fabricated for missing |
|---|---|---|---|---|---|
| B1 | (b)(1), (b)(2) | (b)(1) | 1/2 | 1/2 | no (admitted gap) |
| B2 | (b)(1) to (b)(3) | (b)(1) | 1/3 | 1/3 | yes: (b)(2), (b)(3) |
| B3 | (b)(1) to (b)(4) | (b)(1) | 1/4 | 1/4 | padded, not fabricated |
| B4 | (b)(2), (b)(4) | (b)(2) | 1/2 | 1/2 | yes: (b)(4) |
| B5 | (b)(1) to (b)(4) | (b)(1) | 1/4 | 1/4 | yes: (2), (3) |
| C1 to C3 | (b)(1) to (b)(4) | (b)(1) | 1/4 | 0/4 | no (refused) |
| C4 to C7 | (b)(1) to (b)(4) | none | 0/4 | 0/4 | no (refused) |
| S1 | (b) | (b), (b)(1) to (b)(4) | 5/5 | 3/4 children | no, but (b)(4) omitted |

**Root cause, verified in code:** `parse_cfr_reference()` returns the first
match and retrieval consumes exactly one `CfrReference`. There is no range
expansion, no list of references, and no "retrieve the parent when children
are enumerated" rule. The gate, when on, checks that same single reference.

**Secondary cause:** the words in "What are the requirements of ..." do not
appear in the paragraph text, so the full-text leg returns zero eCFR rows,
the primary count falls below 3, and the OR fallback fills the remaining
context slots with unrelated material (food records, cigarette warnings,
container closure guidance). That material is what the model used to
fabricate (b)(2), (b)(3) and (b)(4) content in B2, B4 and B5.

**Retrieval versus generation attribution:** retrieval failure is primary
(the rows were never fetched). Generation failure is secondary but
independent: even when the missing rows are absent, the model should say so
(as B1 did) rather than invent them (B2, B4, B5), and when all rows are
present (S1) it still dropped one.

---

## 17. Grounding Gate Analysis

Executed evidence, all from `audit/results/battery.jsonl`:

| Scenario | Gate ON behaviour | Correct? |
|---|---|---|
| Nonexistent section 314.999 (I1) | refuse before generation, reason `identifier_not_in_snapshot`, 1.6 s | yes |
| Nonexistent Part 1400 (I2) | refuse before generation, 5.2 s | yes |
| Existing (b)(2) with matching context (E4) | pass, `context_matches_identifier`, answer identical to OFF | yes |
| No identifier (E1 to E3) | pass, `no_identifier_in_question`; prompt and answer identical to OFF | by design; leaves the Paris leak untouched |

Static findings, verified by reading `gate.py` and `pipeline.py`:

* The gate cannot refuse a multi-provision question whose first provision
  is present. B2 with the gate on would pass on (b)(1) and the (b)(2)/(b)(3)
  fabrications would still be generated.
* The gate cannot refuse F2: 820.999 is the second identifier and is never
  parsed. The fabricated "820.999 requires ..." sentence would still be
  produced.
* The gate cannot refuse I4: (b)(4) exists and is in context, so the "FDA
  3988" fabrication passes.
* The gate does not read scores, does not test whether the answer is
  entailed, and does not check citation markers. It is an identifier
  existence and presence check, nothing more.
* It never alters the prompt. ON and OFF produce byte-identical prompts for
  every question it passes.

Conclusion: the gate is a reliable defence against **fabricated identifiers
in the question** and nothing else. Of the 6 fabrications observed in this
battery (B2 twice, B4, B5, F2, I4), the gate as designed would have
prevented 0.

---

## 18. Hallucination Analysis

Fabrications observed (auditor judgment, each verified against the four
provision texts and the retrieved context):

| Test | Fabricated statement | Where the words came from | Layer |
|---|---|---|---|
| B2 | "(b)(2) are to create the required records when you receive and release food" | 21 CFR 1.360(a), trigram hit (similarity 0.40) | generation, fed by trigram noise |
| B2 | "(b)(3) are to identify equipment and tools that ... contact" | 21 CFR 112.121, trigram hit | same |
| B4 | "(b)(4) specifies additional procedures for traceability ... 820.10(b)(1) and part 830" | invented from (b)(2) + question | generation (no source at all) |
| B5 | "(2) The text of the required warning must appear in the predominant language ..." and "(3) If the advertisement is in a medium ..." | cigarette-warning guidance chunk, OR fallback on "through" | generation, fed by fallback noise |
| F2 | "21 CFR 820.999 requires the manufacturer to document procedures for traceability ..." | copied from (b)(2) | generation; parser dropped the second identifier so no refusal note was emitted |
| I4 | "The FDA form number required under 21 CFR 820.10(b)(4) is FDA 3988 ... [1]" | animal-drug annual-report guidance chunk, OR fallback on "form", "number" | generation, fed by fallback noise; citation valid but unsupporting |
| K2 | importer name/address answer to "why is that requirement important" | 21 CFR 251.18 rows | retrieval (no conversation state); answer is grounded in the wrong evidence |
| E1 | "The capital of France is Paris." | model's parametric knowledge | generation; context had nothing about France |

Pattern: 5 of 8 reuse text that *was* in the context but did not belong to
the requested provision. The model treats every SOURCE block as fair game
for whatever the question asked. The OR fallback and the low-threshold
trigram leg are the suppliers. Only B4 and E1 are pure parametric
hallucinations.

No hallucination of citation labels occurred: all citation strings come from
retrieval. Two answers (I4, K2) attach a valid `[1]` to an unsupported claim.

---

## 19. Citation Analysis

* 47 responses; every citation label corresponds to a real retrieved source
  (mechanism guarantee, section 12).
* `[n]` markers appeared in 7 answers (A1, S1, D2, I4, J3, J5, K2); all
  indices were within range. Marker use is inconsistent: A2 to A4 gave
  correct answers without any marker while A1 did, on the same prompt shape.
* Semantic support of the marked sentence: 5 of 7 supported (A1, S1, D2, J3,
  J5); 2 of 7 unsupported (I4: the (b)(4) row does not mention any form; K2:
  the answer is faithful to 251.18 but not to the user's question).
* Guidance citations: every Category A answer lists two or three FDA
  guidance documents as "citations" (QMS premarket-submission guidance,
  Container Closure Systems guidance) that contributed nothing to the answer.
  The UI shows them alongside the real one. This is over-citation, not
  hallucination, and comes from the rule "every source in context is a
  citation".
* Draft guidance is not distinguished from binding regulation in the answer
  text; C7's answer ("The information provided is a draft guidance document,
  not a binding regulation") shows the model can see the `(draft, ...)`
  label but nothing enforces the distinction.

---

## 20. Generation Analysis

* **Faithfulness on single provisions:** 8 of 8 single-provision questions
  in A, E4, K1 and F1 gave a correct paraphrase. The ISO clause was dropped
  every time; "if applicable" in (b)(2) was kept.
* **False refusals with correct context:** J2, J4 (and C1 to C3, where
  refusing was defensible because the range was not available). Rate on
  single-provision questions with the row at rank 1: 2 of 10.
* **Hedging pattern:** 9 answers append the refusal sentence after a real
  answer (D1, D2, D4, F1, F3, C2, C4, C7, E1). The system prompt's rule 5
  ("If the sources do not contain the answer, say ...") is applied as a
  reflex suffix.
* **Degeneration:** C3 repeated the refusal sentence to the token cap; J2
  doubled it. 2 of 47.
* **Truncation:** B2, B3, B5, C3 hit 128 tokens mid-sentence. Every
  multi-item enumeration that tried to list three or more items was cut.
* **Format drift:** B3 and B5 produced Markdown bullets and bold despite
  "Answer in a few plain sentences".
* **Throughput:** 1.6 tokens/s mean on this CPU.

---

## 21. Test Module Analysis

* The runner is reproducible and records what is needed to audit a run
  (full context, scores, timings, gate decision). PASS.
* Coverage gaps that this audit had to fill by hand:
  * no multi-provision or range question in any benchmark;
  * no evidence-coverage metric (requested vs retrieved provisions);
  * no completeness metric (retrieved vs answered provisions);
  * no claim-level citation support check; `citation_validity_rate` is an
    index-range check and would score I4 as valid;
  * `classify_answer` labels D2 and F1 "hedged" although they contain a
    correct answer, and labels C1 a clean refusal although refusing was the
    *right* behaviour there, so the metric cannot tell good refusals from bad;
  * `target_matches()` in the retrieval benchmark treats any paragraph of a
    section as a hit, so (b)(1) retrieved for a (b)(2) target counts as
    success;
  * no multi-turn tests; no truncation metric; degeneration is detected
    only via repeated 4-grams.
* Reviewer quality scores are manual and labelled as such. No automatic
  correctness judge exists. UNKNOWN whether the manual scores would
  reproduce with a different reviewer.
* Fast unit suite executed during this audit (after the battery finished,
  to avoid competing for CPU): see Appendix C.

---

## 22. Performance Analysis

Measured on 47 requests through the local server (CPU, float32,
Qwen3-0.6B, one request at a time).

| Metric | Min | Median | Max | Mean |
|---|---|---|---|---|
| Retrieval (ms) | 696 | 1,676 | 10,482 | 2,671 |
| Generation (ms), model called | 8,099 | 29,353 | 80,397 | 32,107 |
| End-to-end (ms), model called | 9,627 | 31,258 | 90,884 | 34,749 |
| End-to-end (ms), gate refused | 1,579 | | 5,214 | |
| Input tokens | 452 | 1,058 | 1,292 | 1,037 |
| Output tokens | 14 | 43 | 128 | 55 |

* Generation dominates (about 92 % of wall time). Output rate 1.6 tokens/s.
* Retrieval variance (0.7 s to 10.5 s) tracks the fallback: fallback ran
  in 31 of 47 requests and adds a second full-text query over both corpora.
  The 10.5 s outlier (B3) coincided with fallback on the terms "through"
  and "820.10".
* Context budget: median 3 sources in the prompt; 25 of 47 requests dropped
  at least one retrieved source because the 3,600-char total was exhausted
  by 1,200-char guidance chunks. In practice the prompt holds one eCFR row
  plus two guidance chunks.
* Memory: the server process holds about 2.5 GB. This machine cannot run a
  second model concurrently (the Stage 14 overnight stall was caused by
  exactly that).

---

## 23. Failure Taxonomy

Every failure observed, mapped to the requested classes. Layer attribution
and confidence are the auditor's.

| Class | Observed? | Tests | Layer | Confidence |
|---|---|---|---|---|
| A. Retrieval miss | yes | B1 to B5, C1 to C7 (children never fetched); D1, D3 (wrong domain); D5 | retrieval / parser | high |
| B. Incorrect chunk | yes | B2, B5, I4, K2, K3: the top context after the exact row is unrelated | retrieval (fallback + trigram) | high |
| C. Multi-provision retrieval failure | yes | B1 to B5, C1 to C3 | parser (first-match only) | high |
| D. Ranking failure | partial | trigram hits at similarity 0.40 (1.360(a), 112.121) survive the 0.4 cut; guidance outranks eCFR on D5, C7 | ranking / thresholds | medium |
| E. Context truncation | yes | 25/47 requests dropped sources; S1 dropped one; guidance chunks always truncated at 1,200 | context builder | high |
| F. Prompt failure | yes | rule 5 applied as a suffix (9 hedged answers); "few plain sentences" ignored in B3/B5 | prompt + model | medium |
| G. Model hallucination | yes | B2, B4, B5, F2, I4, E1 | generation | high |
| H. Partial answer | yes | B1 to B5, S1 | retrieval (B) / generation (S1) | high |
| I. Over-refusal | yes | J2, J4 (correct row at rank 1) | generation | high |
| J. Under-refusal | yes | E1 (Paris), I4, K2 | generation; gate cannot act | high |
| K. Citation mismatch | yes | I4, K2 (valid index, unsupported claim); over-citation of guidance in A1 to A4 | citation builder + generation | high |
| L. Grounding gate false negative | yes, structural | would pass B2, F2, I4 | gate design | high |
| M. Grounding gate false positive | none observed in this battery | Stage 13 recorded 1 in 27 | gate | medium |
| N. Query parsing failure | yes | ranges, lists, bare numbers (C1 to C7, B1 to B5, F2) | parser | high |
| O. Multi-turn failure | yes | K2, K3 | pipeline (single-turn) | high |

---

## 24. Root Cause Analysis

Ordered by how many observed failures each cause explains.

1. **Single-reference query parser** (`parse_cfr_reference` first match
   only, no ranges, no lists, no bare-number form). Explains every multi-
   provision miss (B, C), the missed 820.999 in F2, and the divergence
   between the seven phrasings. Confidence: high; verified in code and by
   execution.
2. **Low-precision fallback and trigram legs filling the context.** When
   exact retrieval returns one row, the OR fallback (score under 2) and the
   trigram leg (similarity down to 0.40) supply the other two or three
   context slots with unrelated paragraphs. Explains B2, B5, I4, K2 and the
   Category D domain errors. Confidence: high.
3. **No coverage check anywhere.** Nothing compares the set of requested
   provisions with the set retrieved, so the pipeline proceeds to generation
   with 1 of 4 rows and no note. Confidence: high.
4. **Model behaviour on partial context.** Qwen3-0.6B, base, with the current
   prompt, fills gaps from whatever is in the context (B2, B5, I4) or from
   memory (B4, E1), and separately over-refuses on some phrasings (J2, J4).
   Confidence: high for the observations; the *why* (model size, prompt
   wording, decoding) is a hypothesis.
5. **Context budget geometry.** 3,600 total with 1,200 per source means a
   single guidance chunk consumes a third of the prompt. With four children
   plus the parent at 139 to 223 chars each, S1 fitted everything; with
   guidance present, most requests carry only three sources. Confidence: high.
6. **Gate scope.** By design the gate verifies one identifier's existence
   and presence, and nothing about the answer. Confidence: high.
7. **No conversation state.** Confidence: high.
8. **Token cap 128** truncates every list of three or more items.
   Confidence: high.

---

## 25. Retrieval vs Generation Attribution

| Failure | Retrieval share | Generation share | Basis |
|---|---|---|---|
| Multi-provision incompleteness (B, C) | primary | secondary | rows were never fetched; S1 shows generation drops items even when fetched |
| Fabricated provision content (B2, B4, B5) | contributory (noise supplied) | primary | B1 shows the model can admit a gap with the same context shape |
| Fabricated identifier content (F2) | primary (parser dropped it, so no note) | contributory | the note mechanism works when the identifier is parsed (I1-off) |
| Fabricated form number (I4) | contributory | primary | the (b)(4) row was in context and says nothing about forms |
| General-knowledge leak (E1) | none | primary | context was irrelevant and the model answered from memory |
| False refusals (J2, J4) | none | primary | identical retrieval to J1/J3/J5 |
| Wrong-domain answers (D1, D3) | primary | secondary | 820.10(b)(2)/(b)(4) never retrieved; the model still hedged instead of refusing on D1 |
| Follow-ups (K2, K3) | primary (no state) | none | |

Overall for this battery: retrieval and parsing account for the majority of
*missing* content; generation accounts for all *invented* content.

---

## 26. Security / Data Integrity Notes

* Database access is read-only at the connection level and was exercised
  read-only throughout (`SELECT` only; the audit scripts issue HTTP requests
  and read files).
* No credentials, DSNs, SQL text or internal row ids appear in any response
  or in this report. Errors returned by the UI pass through `sanitize_error`.
* The UI binds to loopback and has no authentication; it is a development
  tool and should not be exposed.
* The prompt wraps sources in a "reference material, not instructions"
  block. Prompt injection via guidance text was not tested in this audit
  (UNKNOWN).
* The 1024-d embeddings in the database were not used and their provenance
  remains UNVERIFIED (`docs/embedding_provenance.md`).

---

## 27. Reproducibility Notes

* Greedy decoding and a deterministic retriever: repeating any test with the
  same snapshot, top_k and token cap reproduces the same answer (the Stage 7
  control run reproduced byte for byte; A2, E4-off and K1 in this battery,
  the same question with and without "§", gave the same answer text).
* All raw outputs: `audit/results/battery.jsonl`; console log:
  `audit/results/battery.log`; per-test derived metrics:
  `audit/results/analysis.jsonl`; human-readable dump:
  `audit/results/key_tests.txt`; fast test suite output:
  `audit/results/pytest_fast.txt`.
* Scripts: `audit/run_battery.py` (posts questions to the running UI
  server), `audit/analyze_battery.py` (reads results; imports the project's
  parser and classifier, modifies nothing).
* The server used was `scripts/serve_ui.py --offline` on port 8000 with the
  base model. No adapter was loaded during the battery.

---

## 28. Limitations of This Audit

* Base model only. The Stage 12 and Stage 13 adapters were not run through
  this battery, so adapter behaviour on multi-provision questions is UNKNOWN
  beyond the Stage 13 benchmark results already documented.
* One run per question, greedy. Sampling behaviour is not covered.
* 47 questions concentrated on one section (820.10(b)). Generalisation to
  other parts is inferred from code reading, not measured here.
* Judgments of correctness, fabrication and support are the auditor's, made
  against the provision texts in section 4.
* The semantic and hybrid retrievers (Stages 8 to 10) were not exercised.
* Prompt-injection robustness, concurrency, and long-question behaviour were
  not tested.

---

## 29. Recommendations (no implementation performed)

Ordered by expected impact on the observed failures. These are proposals
for the owner to decide on; nothing below was changed.

1. **Parse every CFR reference in a question**, expand ranges
   ("(b)(1) through (b)(4)", "(b)(1)-(b)(4)", "(b)(1)-(4)"), and accept
   bare "820.10(b)(1)" when it matches an existing section. Retrieve each
   reference with the exact leg. This alone would have turned B1 to B5 and
   C1 to C3 into S1-like contexts.
2. **Add an evidence-coverage check** between retrieval and generation:
   requested provisions minus retrieved provisions. If non-empty, either
   retrieve the parent paragraph, or emit a context NOTE naming the missing
   provisions, or refuse when the gate is on.
3. **Extend the grounding gate** to verify all parsed identifiers (so F2's
   820.999 is refused or noted) and to require coverage, not presence.
4. **Raise the floor on non-exact legs when an exact hit exists.** Suppress
   the OR fallback and trigram results when an exact identifier row was
   found, or require a minimum score before they enter the prompt. This
   removes the material used in B2, B5 and I4.
5. **Reserve context budget for exact rows**: keep exact rows first (already
   true) and cap guidance at fewer characters when eCFR rows are present, so
   all children of a parent fit alongside supporting guidance.
6. **Prompt and decoding**: raise `max_new_tokens` for enumerations or
   detect truncation and mark it; add a repetition penalty or
   `no_repeat_ngram_size` to stop C3-style loops; reword rule 5 so it is a
   whole-answer decision, not a suffix.
7. **Claim-level citation check** in the evaluation module: for each
   sentence with `[n]`, test lexical overlap with source n and report
   unsupported markers (would have flagged I4).
8. **Benchmark additions**: multi-provision, range, bare-number and
   follow-up questions with per-provision expected rows; a coverage metric;
   a completeness metric; a truncation flag.
9. **Conversation state**: if follow-ups are a product goal, carry the last
   parsed identifier into the next retrieval; otherwise document the
   single-turn limit in the UI.
10. **Over-citation**: only list a source as a citation when it was used
    (marker present) or when it is the exact-identifier row.

---

## 30. Risk Assessment

| Risk | Likelihood (observed) | Impact | Note |
|---|---|---|---|
| Confident fabrication of a provision's content when a multi-provision question is asked | 3 of 5 tests | high: wrong regulatory content presented as fact with a valid-looking citation | gate does not mitigate |
| Confident fabrication of an unrelated detail (form number, penalty) | 1 of 2 tests | high | I3 refused, I4 fabricated |
| Silent partial answers (one of four provisions) | 5 of 5 | high for compliance use | no signal to the user |
| False refusal on a correct single provision | 2 of 10 phrasings | medium: usability | |
| General-knowledge leakage | 1 of 3 | low for regulatory use, high for trust | |
| Wrong-domain answers on uncited questions | 2 of 5 | medium | dietary supplement rules returned for device questions |
| Latency 30 to 90 s per answer | always | medium for interactive use | hardware bound |
| Truncated lists | 4 of 47 | medium | unmarked |

---

## 31. Open Engineering Decisions

1. Should multi-reference questions be answered by expanding to the parent
   paragraph (one retrieval, all children, as S1 demonstrates) or by
   retrieving each child independently? Parent expansion is simpler and
   already works; independent retrieval preserves ordering and allows
   per-provision coverage reporting.
2. Should the gate refuse on incomplete coverage or annotate and let the
   model answer the covered part? B1 shows the model can handle an
   annotated gap; B2 shows it cannot be trusted without one.
3. Should non-exact legs be disabled entirely when an exact identifier is
   found, or merely down-weighted? Disabling loses the QMS guidance chunk
   that sometimes adds value (D2); keeping it admits the noise that fed I4.
4. Whether to raise the context budget (more sources, slower generation on
   this CPU) or shrink the guidance chunk allowance.
5. Whether follow-up questions are in scope for the pipeline or only for
   the chat CLI.
6. Whether the Stage 13 gated adapter, which reduced unsupported answers to
   zero on the benchmark but over-refused general questions, should be the
   default for the UI, and whether it changes the multi-provision behaviour
   documented here (UNKNOWN until run).
7. Whether to adopt an automatic correctness judge for the benchmark or keep
   manual reviewer scores.

---

## Answers to Q1 to Q15

**Q1. Why does the system return only 820.10(b)(1) when a range or list is
asked?** Because `parse_cfr_reference()` returns the first CFR reference it
finds and the retriever fetches exactly that one row. Ranges and lists are
not parsed. Verified in code and by execution on 12 phrasings.

**Q2. Is this a retrieval, parsing, ranking or generation failure?**
Parsing first (the extra references are discarded before any SQL runs),
retrieval second (the fallback legs then fill the context with unrelated
text), generation third (the model fabricates the missing provisions from
that text in 3 of 5 cases instead of reporting the gap). Ranking is not the
cause: when a child row is retrieved it is always rank 1.

**Q3. Do (b)(1) to (b)(4) exist as separate retrievable rows?** Yes, one
row each, plus the parent (b). All five are returned together by the parent
query (S1). (b)(5) does not exist.

**Q4. Does the grounding gate actually change execution, or only the label?**
It changes execution only when the parsed identifier is verified absent (I1,
I2: deterministic refusal, model not called, 1.6 to 5.2 s) or when an
existing identifier has no matching context row. For every other question
the prompt, the model call and the answer are byte-identical with the gate
on or off (E1 to E4). It never edits the prompt.

**Q5. Why did the France question answer "Paris" with the gate on?** The gate
found no CFR identifier, recorded `no_identifier_in_question`, and passed.
Its only checks are identifier existence and identifier presence in context;
it does not evaluate the answer or the relevance of the context. The model
then answered from parametric knowledge and appended the refusal sentence.

**Q6. Are citations real?** The citation labels are always real: they are
copied from the retrieved rows, never generated. Whether the cited row
supports the sentence is not checked; I4 and K2 attach a valid `[1]` to an
unsupported claim.

**Q7. Does the model fabricate content?** Yes. Six fabrications in 47 tests:
B2 (two provisions), B4, B5 (two items), F2 (a nonexistent section's
content), I4 (a form number). Five of the six reuse text that was in the context for a different purpose
(B2 twice, B5, I4, and F2 copying (b)(2)); B4 is purely parametric. The Paris answer (E1) is a separate general-knowledge leak.

**Q8. Does the system answer completely when all evidence is retrieved?**
Not reliably. S1 had all five rows in context and summarised three of the
four children, omitting advisory notices. D4 had eight rows of 830.310 and
gave a hedged partial summary.

**Q9. Are the seven range phrasings handled the same way?** No. Three
(with "§") parse to (b)(1) and retrieve that row; four (bare numbers,
"subsections ... of 820.10", "all requirements under 820.10(b)") parse to
nothing and run a general search that never touches the exact leg. All seven
end in a refusal, one of them degenerate (C3).

**Q10. Is retrieval deterministic and reproducible?** Yes. Fixed score
constants, key-ordered tie-breaks, greedy decoding; repeated questions (A2,
E4-off, K1, differing only in "§") produced the same answer text.

**Q11. What does the test module measure and what does it miss?** It
measures per-question refusal, unsupported-answer, false-refusal, identifier
grounding, citation-index validity, degeneration and manual 0/1/2 quality.
It misses evidence coverage, answer completeness, claim-level citation
support, truncation, multi-provision questions and multi-turn behaviour.

**Q12. What is the latency profile?** Median 31 s end-to-end (1.7 s
retrieval, 29 s generation) on this CPU; 90 s worst case; 1.6 to 5.2 s when
the gate refuses. Generation is 92 % of the time.

**Q13. Does the fallback help or hurt?** On identifier questions it hurts:
it fired in 31 of 47 requests and supplied the unrelated text behind B2, B5,
I4 and K2. On uncited questions it is the only thing that returns anything
(D5), but what it returned was not useful there either.

**Q14. Is the database or any project artefact modified?** No. All access
was through the read-only connection and HTTP. New files created:
`audit/run_battery.py`, `audit/analyze_battery.py`, `audit/results/*` and
this report. No existing file was edited.

**Q15. What single change would most improve the observed behaviour?**
Parsing every reference in the question (with range expansion) and
retrieving each with the exact leg, combined with a coverage check that
names missing provisions in the context. That addresses classes A, C, H, N
and removes the trigger for most of G.

---

## Appendix A. Files Inspected (read only)

Source: `src/regulus/retrieval/{query,lexical,ranking,sql,db,citations,
models,base}.py`; `src/regulus/rag/{pipeline,context,prompt,generator}.py`;
`src/regulus/grounding/{identifiers,gate}.py`;
`src/regulus/evaluation/{dataset,runner,results,retrieval_eval,
grounding_eval}.py`; `src/regulus/inference/generate.py`;
`src/regulus/model/{loader,device}.py`; `src/regulus/config/settings.py`;
`src/regulus/training/{config,grounding_examples,answer_examples}.py`;
`src/regulus/finetune/{train,config,lora}.py`.
Scripts: `scripts/{serve_ui,rag,evaluate_baseline,evaluate_retrieval,
compare_grounding}.py`; `web/index.html`.
Configs: `configs/{model,training,training_v2,training_v3,model_training,
model_training_v2,model_training_v3}.yaml`.
Data: `data/evaluation/datasets/{baseline_v1,retrieval_v1,retrieval_v2}.jsonl`;
`data/evaluation/results/stage12_v1/*`, `stage13_v1/*`, `stage14_v1/*`.
Models: `models/qwen3-0.6b-lora/{stage12_v1,stage13_v1,stage14_v1}/` (listing
and metadata only).
Docs: `docs/{training_data_preparation,stage12_model_training,
stage13_grounding_and_training,stage14_overnight_training,
embedding_provenance}.md`, `README.md`.
Database (SELECT only): `cfr_records`, `cfr_sections`, `cfr_parts`,
`fda_guidance`, `fda_guidance_chunks`, index and extension catalogs.

## Appendix B. Tests Executed

47 questions via `audit/run_battery.py` (ids A1 to A4, B1 to B5, C1 to C7,
S1, D1 to D5, E1 to E4 off/on, F1 to F3, I1 to I2 off/on, I3, I4, J1 to J5,
K1 to K3); 12 retrieval-only parser/retriever probes; static traces of the
gate on the France question.

## Appendix C. Fast Unit Test Suite

Run after the battery finished, with the `slow` marker deselected:

```
322 passed, 6 deselected in 77.63s
```

No test was added, changed or removed.

## Appendix D. Confirmation of Non-Modification

No source file, configuration, prompt, model weight, adapter, checkpoint,
index, database row, benchmark dataset or test was modified during this
audit. Files created: `MODEL_SYSTEM_AUDIT_AND_TEST_REPORT.md`,
`audit/run_battery.py`, `audit/analyze_battery.py`,
`audit/results/battery.jsonl`, `audit/results/battery.log`,
`audit/results/analysis.jsonl`, `audit/results/analysis.err`,
`audit/results/key_tests.txt`, `audit/results/pytest_fast.txt`.
