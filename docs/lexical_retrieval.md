# Lexical Retrieval Layer (Stage 5)

Read-only lexical retrieval over the `regulus` PostgreSQL corpus: 65,341 eCFR
paragraphs (`cfr_records`) and 68,669 FDA guidance chunks
(`fda_guidance_chunks` joined to `fda_guidance`). No embeddings, no model.

```
Question ──► LexicalRetriever ──► results + citations      (this stage)
Question ──► Retriever ──► context ──► Qwen ──► answer + citations   (later)
```

Package: `src/regulus/retrieval/`. CLI: `scripts/search.py`. Evaluation:
`scripts/evaluate_retrieval.py`. Tests: `tests/test_retrieval_*.py` (unit,
no database) and `tests/integration/test_retrieval_db.py` (live, read-only).

---

## 1. Architecture

```
CLI / future application
        │
        ▼
 LexicalRetriever.run(query, corpus, top_k, filters, methods)
        │
        ├── classify(query)  ─► EXACT_CFR | GUIDANCE_SEARCH | GENERAL_REGULATORY_SEARCH
        │
        ├── exact_cfr        cfr_records by section_number / paragraph_path   (if a CFR ref)
        ├── exact_docket     fda_guidance by docket_number                    (if a docket)
        ├── full_text:ecfr   cfr_records.search_vector @@ websearch_to_tsquery
        ├── full_text:fda_guidance   fda_guidance_chunks.search_vector @@ ...
        └── trigram          cfr_sections.number / heading % query           (conditional)
                │
                ▼
        merge(): de-duplicate by key, strongest method wins, score desc, key asc
                │
                ▼
        SearchResponse(results[RetrievalResult], timings_ms, counts, notes)
```

| Module | Responsibility |
|---|---|
| `db.py` | `DatabaseConfig` (URL from `REGULUS_DATABASE_URL`, password redaction), `Database` (one read-only connection, `query()` only) |
| `sql.py` | Six SELECT statements with named parameters; nothing else |
| `query.py` | `parse_cfr_reference`, `parse_docket`, `classify` |
| `citations.py` | `build_ecfr_citation`, `build_guidance_citation` from a row mapping |
| `models.py` | `Citation`, `RetrievalResult` (serialisable, no internal ids) |
| `ranking.py` | score constants, `merge()` |
| `base.py` | `Filters`, `Retriever` protocol |
| `lexical.py` | `LexicalRetriever`, `SearchResponse` |

`Retriever` is a `Protocol` with `search(query, *, corpus, top_k, filters)`.
A `SemanticRetriever` or `HybridRetriever` later implements the same signature
and returns the same `RetrievalResult` objects, so callers do not change.

## 2. PostgreSQL connection design

- Driver: `psycopg` 3.3.5 (binary wheel), pinned in `requirements.txt`.
- Configuration: `REGULUS_DATABASE_URL` from the environment or the gitignored
  `.env` (documented in `.env.example`). No credential appears in code, tests,
  docs, logs or CLI output; `DatabaseConfig.redacted()` and `repr()` mask the
  password.
- Read-only is enforced by the server, twice: the connection is opened with
  `options="-c default_transaction_read_only=on -c statement_timeout=15000"`,
  and psycopg's `connection.read_only = True` sets the session characteristic.
  Any INSERT/UPDATE/DELETE/DDL, including `CREATE TEMP TABLE`, raises
  `ReadOnlySqlTransaction` before touching data. The integration suite proves
  this and also asserts that `pg_stat_user_tables` write counters are identical
  before and after the run.
- `Database` exposes `query()`, `cursor()` and `status()` only. There is no
  execute-for-write method to misuse.
- `application_name = regulus-retrieval` so sessions are identifiable in
  `pg_stat_activity`.
- On this machine the `.env` uses the local `postgres` role because it is the
  only role whose password is known here. In any shared environment use a
  least-privilege read role (`regulus_app` or a new SELECT-only role); the
  session is forced read-only regardless of role.

## 3. Exact CFR lookup

`parse_cfr_reference` recognises, case-insensitively:

| Form | Example | Level |
|---|---|---|
| title + CFR + section | `21 CFR 820.10`, `21 C.F.R. § 211.132`, `What does 21 CFR 820.10 say?` | section |
| with paragraphs | `Explain 21 CFR 820.10(b)(1)`, `21 CFR §820.10 (b) (1)` | paragraph |
| section symbol only | `§ 801.109(a)(1)(i)`, `§§ 314.50` | section/paragraph, title defaults to 21 |
| "section" word | `section 50.25 elements of informed consent` | section |
| part | `21 CFR Part 820`, `part 820` | part |
| other titles | `42 CFR 493.1` | parsed, but the corpus is Title 21 only, so no exact lookup runs |

Not recognised (falls through to text search): `21 CFR`, `CFR 820`, `820.10`
on its own (ambiguous with ordinary numbers; the trigram leg covers it).

Lookup uses the existing structure only: `section_number`, `paragraph_path`
(e.g. `(b)(1)`), `ordinal`, `removed_on IS NULL`.

- Section request: every live row of the section in document order
  (`21 CFR 820.10` → the intro row plus (a), (b), (b)(1) … (e), 12 rows).
- Paragraph request: the paragraph itself (`match_kind = exact`) plus its
  descendants (`match_kind = descendant`): `820.10(b)` → (b), (b)(1)…(b)(4).
- Part request: the first row of each section in the part.
- Nothing found: the response carries a note, e.g. *"No live record for
  21 CFR 820.30(b)(1) in this eCFR snapshot (section may be reserved, removed,
  outside Title 21, or excluded by filters); remaining results are text matches
  only."* In this snapshot Part 820 is the 2026 QMSR, and `820.20-820.30` is a
  reserved range, so the classic `820.30` design-control citation has no live
  record. Exact lookup never falls back to a similar-looking section.

Exact identity beats textual similarity by construction: exact rows score 100
(95 for descendants) while normalised text scores stay below about 30.

## 4. Full-text retrieval

Both corpora have a generated `search_vector` (`to_tsvector('english', heading
or title)` weighted **A** `||` body weighted **B`) with a GIN index
(`cfr_records_search_idx`, `fda_guidance_chunks_search_idx`). The retriever
uses:

```sql
websearch_to_tsquery('english', %(query)s)          -- free text, "phrases", -exclusions
search_vector @@ q
ts_rank_cd(search_vector, q, 1)                     -- cover density, normalisation 1
```

`websearch_to_tsquery` was chosen over `plainto_tsquery` because it never
raises on user punctuation and supports quoted phrases and `-term`.

Normalisation flag **1** divides the rank by `1 + log(document length)`. Raw
`ts_rank_cd` grows with document length, which made 1,450-character guidance
chunks outrank 218-character eCFR paragraphs for almost every query. Measured
on five concept queries, the top eCFR paragraph beat the top guidance chunk in
2 of 5 cases with raw ranking and in 4 of 5 with normalisation 1. It is still a
length-sensitive statistic; see limitations.

Guidance results are capped at 3 chunks per document (`chunks_per_document`),
applied with `ROW_NUMBER() OVER (PARTITION BY guidance_id …)` over the top
`limit × 10` candidates so one long document cannot fill the list.

The corpus is preserved on every result: `corpus = "ecfr"` or
`"fda_guidance"`.

## 5. Trigram retrieval

Existing pg_trgm GIN indexes exist only on `cfr_records.section_number`,
`cfr_records.section_heading`, `cfr_sections.number` and
`cfr_sections.heading`. There is no trigram index on guidance titles or on any
body text, so trigram is used only on eCFR section identity, and only via the
indexed `%` operator (threshold `pg_trgm.similarity_threshold = 0.3`):

```sql
FROM cfr_sections s
JOIN LATERAL (first live row of the section) r ON TRUE
WHERE s.number % %(query)s OR s.heading % %(query)s
score = greatest(similarity(s.number, q), similarity(s.heading, q))
```

Why: it recovers partial identifiers (`820.3` → 820.3, 820.35, 820.1), heading
typos (`informd consent requirments` → 50.20, 50.25, 50.24, 50.27) and short
unusual terms, at section granularity, returning the section's first paragraph
as a citable passage. It never scans paragraph bodies.

When it runs (`_should_run_trigram`): the query has ≤ 4 words, or it contains a
dotted number, or eCFR full-text returned fewer than `top_k` rows. Long
descriptive questions that full-text already satisfies skip it.

## 6. Query classification

`classify(query) -> QueryClassification(query_type, cfr, docket)`:

| Input | Type |
|---|---|
| empty / whitespace | `EMPTY` (the retriever raises `ValueError`) |
| contains a CFR reference | `EXACT_CFR` (docket also captured if present) |
| contains a docket `FDA-YYYY-X-NNNN` or the word "guidance" | `GUIDANCE_SEARCH` |
| anything else | `GENERAL_REGULATORY_SEARCH` |

The type is informational for callers and drives only the exact legs; full-text
runs for every non-empty query on the selected corpora. `GUIDANCE_SEARCH`
does not suppress eCFR results because guidance questions usually have a
regulatory anchor too. 26 unit tests cover the parser and classifier,
including malformed identifiers.

## 7. Ranking

Deterministic, documented in `ranking.py`:

| Method | relevance_score |
|---|---|
| `exact_cfr` | 100.0 for requested rows, 95.0 for descendant paragraphs, minus 0.001 × ordinal (keeps document order on ties) |
| `exact_docket` | 100.0 minus 0.001 × chunk ordinal |
| `full_text` | 50.0 × `ts_rank_cd(search_vector, query, 1)` |
| `trigram` | 5.0 × `greatest(similarity(number), similarity(heading))` |

No learned weights, no vector scores. The scales were chosen so that exact
matches always win (largest normalised full-text score seen on this corpus is
about 30, trigram maxes at 5.0) and so that full-text generally outranks
trigram, which is a fallback. The per-method raw values are kept in
`metadata.scores` so a result can always be explained.

Final order: `relevance_score` desc, then `key` asc. Two runs of the same
query return identical lists (asserted by unit and integration tests).

## 8. Deduplication

Every result has a natural, non-secret `key`:
`ecfr:<section>:<paragraph_path>:<path_ordinal>` or
`fda_guidance:<source_url>#<chunk ordinal>`. `merge()` keeps one result per
key: `relevance_score = max`, `retrieval_method = strongest` by priority
(exact 3 > full_text 2 > trigram 1), `methods = all` that found it, and
`metadata.scores` merged. Example: `21 CFR 820.10` is found by exact lookup
and by trigram; the result shows `Method: exact_cfr (also: trigram)`.

## 9. Metadata filtering

`Filters` maps only to real, indexed columns and validates shape:

| Filter | Column | Validation |
|---|---|---|
| `part` | `cfr_records.part_number` | 1–4 digits |
| `section` | `cfr_records.section_number` | `NNN.NNN` |
| `subchapter` | `cfr_records.subchapter_code` | single letter A–L |
| `retrievable` | `fda_guidance.retrievable` | bool or None; **default True** (628 held-out documents excluded) |
| `sector` | `fda_guidance.sector` | non-empty string (values observed: drug, device, food, biologic, supplement, tobacco, cosmetic) |
| `center` | `fda_guidance.center` | non-empty string (CDER, CDRH, CBER, CFSAN, CVM, CTP, OTHER) |
| `status` | `fda_guidance.status` | non-empty string (final, draft) |
| `anchor_part`, `anchor_section` | `fda_guidance.anchor_part/anchor_section` | as part/section |

Values are not hard-coded; they are passed as parameters and compared for
equality. Unknown names raise `FilterError` (`Filters.from_kwargs`). All rows
also require `removed_on IS NULL` (eCFR) and `NOT is_reserved` for text
matches.

## 10. Citation construction

Separate from SQL: a row mapping goes into `build_ecfr_citation` /
`build_guidance_citation` and a `Citation` comes out. Missing fields stay
`None`; nothing is invented.

eCFR: `label = "{title} CFR {section_number}{paragraph_path}"` →
`21 CFR 820.10(b)(1)`; `url = ecfr_permalink` (section-level permalink as
stored; a paragraph anchor is not appended because the database does not store
one); `title`, `part`, `section`, `paragraph`, `heading` filled from the row.
`metadata` adds `part_title` (from `cfr_parts`), `parent_headings`,
`govinfo_pdf_url`, `snapshot_date`.

Guidance: `label = "FDA Guidance: {title} ({status}, {issued_on}, Docket {docket})"`
with each qualifier omitted when absent (257 documents have no docket; 11 have
no issue date); `url = source_url`; `document_title`, `docket_number`,
`status`, `issued_on`, `center`. Location inside the document is the chunk
ordinal and character offset only (no page numbers exist in the data).

## 11. CLI usage

```bash
python scripts/search.py "21 CFR 820.10"
python scripts/search.py "Explain 21 CFR 820.10(b)"
python scripts/search.py "quality system requirements" --top-k 5
python scripts/search.py "design controls" --corpus ecfr --part 820
python scripts/search.py "human factors" --corpus fda_guidance --sector device --status final
python scripts/search.py "820.3" --method trigram
python scripts/search.py "recall policy" --json          # full SearchResponse as JSON
python scripts/search.py "labeling" --corpus fda_guidance --include-unretrievable
```

Options: `--top-k`, `--corpus {ecfr,fda_guidance}`, `--method` (repeatable:
exact_cfr, exact_docket, full_text, trigram), eCFR filters `--part --section
--subchapter`, guidance filters `--sector --center --status --anchor-part
--anchor-section --include-unretrievable`, `--width` (text characters),
`--json`, `-v`. Output shows corpus, citation label, score, method (and other
methods that also found it), heading or chunk/sector/center, URL, text. No
credentials or internal ids are printed.

## 12. Tests

Fast suite (`pytest`, no database): 78 retrieval tests among 152 total.

- `test_retrieval_query.py`: 13 parse cases, 8 non-references, levels/labels,
  classification of exact section, paragraph, general question, guidance
  keyword, docket, empty and malformed identifiers.
- `test_retrieval_lexical.py`: eCFR and guidance citations incl. missing
  docket/optional fields; result serialisation, required and null fields,
  validation; filter defaults, 9 invalid values, unknown names, parameter
  pass-through, corpus restriction; score components, exact-outranks-text,
  determinism, merge of duplicates, ordering and truncation, trigram trigger
  rules, part-level and non-Title-21 behaviour, docket path, empty query /
  bad top_k / bad method, response notes and timings.
- SQL safety: every statement starts with SELECT, contains no write keyword,
  uses `%(name)s` parameters and no leftover `{}`; AST scan of `lexical.py` and
  `db.py` finds no f-string, `%` or `.format()` SQL; `Database` has no
  `execute`/`write`; the module forces `default_transaction_read_only=on`; URL
  redaction and env-var validation.
- `test_retrieval_eval.py`: dataset validation, target-matching rules, first
  hit rank, metric aggregation.

Integration suite (`pytest -m integration`, skipped without
`REGULUS_DATABASE_URL`): 15 tests — connection and read-only flags; four write
statements rejected with `ReadOnlySqlTransaction`; exact section (12 rows,
heading, permalink, part title), paragraph with descendants, reserved 820.30
returns no exact hit; eCFR full-text finds 211.132; guidance full-text finds
FDA-2008-D-0559 with status/date/URL from the database; exact docket; trigram
on `820.3` and a misspelling; part, section, subchapter, sector+status and
center filters; cross-corpus determinism and de-duplication; serialisation
without internal ids; write counters unchanged across the module.

## 13. Retrieval evaluation

Dataset: `data/evaluation/datasets/retrieval_v1.jsonl`, 28 queries in eight
categories; every expected target was checked to exist in the database before
being written. Target syntax: `21 CFR 820.10` (any paragraph of the section),
`21 CFR 820.10(b)` (that paragraph or nested under it), `docket:FDA-…`. One
negative control (`21 CFR 820.30(b)(1)`, empty `expected`) passes only if no
exact hit is returned.

Metric: a query hits at rank r if the r-th result satisfies any expected
target. Recall@K = share of scored queries with a hit at rank ≤ K; MRR = mean of
1/rank. Results file:
`data/evaluation/results/retrieval-lexical_20260915_171908_20d70992.json`.

| Metric | Value (27 scored, 1 negative control passed, 0 failed) |
|---|---|
| Recall@1 | 0.778 |
| Recall@3 | 0.815 |
| Recall@5 | 0.852 |
| Recall@10 | 0.852 |
| MRR | 0.798 |

| Category | n | R@1 | R@5 | MRR |
|---|---|---|---|---|
| exact_cfr | 3 | 1.00 | 1.00 | 1.00 |
| cfr_section | 2 | 1.00 | 1.00 | 1.00 |
| cfr_paragraph | 2 | 1.00 | 1.00 | 1.00 |
| regulatory_concept | 8 | 0.75 | 1.00 | 0.82 |
| fda_guidance | 5 | 0.80 | 0.80 | 0.80 |
| cross_corpus | 2 | 1.00 | 1.00 | 1.00 |
| terminology_variation | 2 | 0.50 | 0.50 | 0.50 |
| difficult_lexical | 3 | 0.33 | 0.33 | 0.33 |

Misses, all instructive:

- `retrieval-017` Part 11 scope-and-application guidance: eCFR Part 11
  sections dominate; the guidance (FDA-2003-D-0143, sector `supplement`) does not
  reach the top 10.
- `retrieval-025` "QMS documentation requirement ISO 13485": abbreviation
  and standard name never appear together with the regulation's wording.
- `retrieval-027` "design controls": the QMSR text says "design and
  development"; the phrase only appears in guidance documents.
- `retrieval-028` "sunscreen SPF labeling": 352.52 (an SPF-related section)
  outranks 201.327; the target is in the top 20 but not the top 10.

These are exactly the vocabulary-mismatch cases a semantic leg is meant to
address; they are recorded so the later comparison is concrete.

## 14. Performance baseline

Local PostgreSQL 18.4, installer defaults (`work_mem` 4 MB, `shared_buffers`
128 MB), untouched. Measured from the evaluation run (28 queries, top_k 10,
one connection reused, includes Python-side row conversion):

| Leg | Queries | Median | p90 | Max |
|---|---|---|---|---|
| exact_cfr | 9 | 1.6 ms | 5.1 ms | 13.7 ms |
| exact_docket | 1 | 1.4 ms | — | — |
| full_text:ecfr | 28 | 3.2 ms | 13.0 ms | 34.1 ms |
| full_text:fda_guidance | 28 | 11.4 ms | 80.8 ms | 2,750 ms (first, cold cache; 16 ms on re-run) |
| trigram | 23 | 97.3 ms | 154 ms | 187 ms |
| combined (`total_ms`) | 28 | 114.5 ms | 231 ms | 2,860 ms (same cold read) |

Trigram is the dominant cost: the `%` operator on both `cfr_sections`
trigram indexes plus the LATERAL lookup of each section's first row runs at
about 100 ms regardless of query. It is only run for short, identifier-like or
under-served queries. No PostgreSQL setting was changed; this is a baseline.

## 15. Known limitations

1. **Vocabulary mismatch.** Lexical search cannot bridge "design controls" ↔
   "design and development", or "QMS / ISO 13485" ↔ the regulation's wording.
2. **Length sensitivity.** Even with normalisation 1, long guidance chunks with
   repeated terms often outrank short paragraphs ("quality system
   requirements" puts 820.10(b) at rank 5 behind four guidance chunks).
3. **Reserved / renumbered sections.** Part 820 in this snapshot is the QMSR;
   requests for pre-2026 QSR sections (820.30, 820.50 …) return no exact
   record and only a note. Historical mapping is a data question, not a
   retrieval one.
4. **Guidance chunks carry no page or heading position**, so guidance
   citations are document-level plus chunk ordinal.
5. **Trigram covers eCFR section identity only**; there is no trigram index on
   guidance titles, so typos in guidance names are not recovered.
6. **Latency** of the trigram leg (~100 ms) and the first cold guidance read
   are untuned; `work_mem`/`shared_buffers` are at defaults by decision.
7. **`retrievable = true` default** hides 628 guidance documents held out by
   the ingestion pipeline for missing disclaimer/docket; they can be included
   explicitly but their metadata is incomplete.
8. **Held-out or withdrawn guidance**: `withdrawn_at` exists in the schema but
   is not yet a filter; only `retrievable` is applied.
9. The `fda_guidance_anchors` table (guidance ↔ CFR part/section links) is not
   yet used to boost guidance that anchors to a section found by exact lookup.

## 16. Why embeddings are not used yet

Stage 4.5 classified the provenance of the existing `cfr_records.embedding`
and `fda_guidance_chunks.embedding` vectors as **UNVERIFIED**: the provider,
the dimension handling (`dimensions=1024` vs client-side truncation) and the
exact input text sent to the API are not established, and the schema comment
(`voyage-3-large`) contradicts the stored label (`text-embedding-3-large`).
Query vectors produced under a guessed configuration could land in a different
space and silently degrade results. The vector columns and HNSW indexes are
therefore left completely untouched by this stage; no code in
`regulus.retrieval` references them.

## 17. Stage 7: controlled OR fallback

**Why.** Stage 6 showed that 10 of 27 benchmark questions produced nothing
usable from retrieval; 8 of them had zero results. `websearch_to_tsquery`
ANDs every term, so a verbose question ("Explain to someone with no medical
background why a new drug must be approved before it can be sold") matches
no paragraph and no chunk, and trigram cannot match a sentence.

**Primary path unchanged.** Exact lookup, AND full-text and trigram run
exactly as in Stage 5. `LexicalRetriever(db, enable_or_fallback=False)`
reproduces Stage 5 byte for byte; the Stage 5 benchmark re-run in that mode
gives the identical Recall@1 0.778 / Recall@5 0.852 / MRR 0.798.

**Exact trigger.** After the primary legs, count the distinct results whose
method is `exact_cfr`, `exact_docket` or `full_text` (trigram-only hits do not
count). If that count is below `primary_min_results` (default 3), and the
term selector returns at least one term, run one OR full-text query per
selected corpus. Configurable via `LexicalRetriever(enable_or_fallback=...,
primary_min_results=..., fallback_max_terms=...)`, `scripts/search.py
--no-fallback --primary-min-results N`, `scripts/evaluate_retrieval.py
--no-fallback`, `scripts/evaluate_baseline.py --pipeline rag --no-fallback`.

**Term selection** (`regulus.retrieval.query.fallback_terms`, no NLP
dependency): quoted phrases are kept whole; identifiers are kept with any
paragraph suffix removed (`820.30(b)(1)` → `820.30`, `510(k)` → `510`) and
bare numbers shorter than three digits are dropped; question and instruction
words, English function words, and a short list of words near-universal in
this corpus (cfr, fda, regulation(s), requirement(s), section, part,
guidance, document, recommendation(s), industry, staff, food, drug, product…)
are dropped; the remaining words are ordered longest first (a stable proxy
for rarity), capped at `fallback_max_terms` (8), and joined with ` or ` for
the same parameterised `websearch_to_tsquery` statements used by the AND
path. Examples: the long approval question → `approved or medical or sold`;
`What is the CFR?` → no terms, no fallback; the fake docket question →
`fda-2023-d-99999` only, which matches nothing.

**Ranking.** Fallback rows carry method `full_text_or` with score
`5 × ts_rank_cd(…, 1) / number_of_OR_terms`. An OR query over n terms
inflates cover-density rank with the number of matching terms (values above
3 were measured for an 8-term query, which at the first-draft scale of 25
produced scores of 88, next to exact matches), so the rank is averaged per
term and placed in the trigram band (0–5). Merge priority: exact 3 > full_text
2 > full_text_or 1 = trigram 1. Fallback results therefore never outrank a
primary hit, and a passage found by both keeps the primary method.

**Bounds.** At most `top_k` rows per corpus from the fallback; the guidance
statement keeps the 3-chunks-per-document cap; the final list is still cut
to `top_k`.

**Diagnostics** on `SearchResponse.diagnostics` (also in the CLI, the
retrieval-evaluation results and the RAG benchmark's per-question record):
`primary_result_count`, `fallback_used`, `fallback_terms`,
`fallback_candidate_count`, `final_result_count`, `retrieval_mode`
(`exact` | `primary` | `fallback` | `none`).

**Retrieval benchmark (retrieval_v1.jsonl, unchanged, top_k 10).**

| | Stage 5 (re-run, fallback off) | Stage 7 (fallback on) |
|---|---|---|
| Recall@1 | 0.778 | 0.778 |
| Recall@3 | 0.815 | 0.815 |
| Recall@5 | 0.852 | 0.852 |
| Recall@10 | 0.852 | 0.852 |
| MRR | 0.798 | 0.798 |
| Negative control (820.30(b)(1)) | passed | passed (fallback terms: `820.30`, 0 candidates) |
| Fallback activations | 0 | 2 of 28 |
| Zero-result queries before / after | 1 / 0 (trigram-only) | 1 / 0 |
| Misses | 017, 025, 027, 028 | same four |

Result files: `retrieval-lexical-stage5_20260915_175942_dd2ea6c0.json`,
`retrieval-lexical-stage7_20260915_180242_d45608c2.json`.

Per-query changes: only two queries activated the fallback. `retrieval-026`
("informd consent requirments", primary count 0, trigram found 50.20 and
50.25) gained six informed-consent guidance chunks (FDA-2006-D-0031,
FDA-2006-D-0464) ranked between the two trigram hits; the target stayed at
rank 1. `retrieval-008` (the negative control) produced no fallback
candidates. No other query changed, because the benchmark contains no long
natural-language question; every other query already had ≥ 3 primary
results. An intermediate scoring (scale 25, no per-term averaging) had
pushed 026's guidance chunks above the trigram hit and cost one Recall@1
point; that is why the final scale is 5 with per-term averaging.

**Behaviour on questions outside the benchmark** (probed with the CLI):

| Question | Terms | Result |
|---|---|---|
| "Explain … why a new drug must be approved before it can be sold" | approved, medical, sold | 12 candidates, all guidance (ANDA amendments, animal-drug feed); loosely related |
| "In simple language, what does 'good manufacturing practice' mean…" | manufacturing, medicines, practice, good | CGMP Q&A, Phase 1 CGMP, combination-product CGMP, Q7: relevant |
| "…exact FDA user fee … fiscal year 2031?" | application, dollars, amount, fiscal, user, year, 2031, fee | user-fee guidances (PDUFA, GDUFA, combination products): related, cannot answer 2031 |
| "Summarize … FDA-2023-D-99999" | fda-2023-d-99999 | no candidates |
| "What does 21 CFR Part 1400 say about artificial intelligence in drug labeling?" | intelligence, artificial, labeling, 1400 | 12 labeling guidances: unrelated to the (non-existent) Part 1400 |
| "What are the specific requirements of 21 CFR 314.999?" | 314.999 | no candidates (trigram junk as before) |

Cost: an activated fallback adds roughly 0.4–1.9 s (the guidance OR query is
the slow part; OR matches tens of thousands of chunks before the cap).

**Regressions / weaknesses.** None on the benchmark. The fallback cannot fix
vocabulary mismatch ("design controls", "QMS / ISO 13485", "sunscreen SPF")
because those queries already have ≥ 3 primary results and never trigger
it. For fabricated-part and reasoning questions it returns loosely related
guidance, which shifts the burden to the generator; see `docs/lexical_rag.md`
for the measured effect.

## 18. Adding semantic / hybrid retrieval later

1. Resolve embedding provenance (obtain the original code, or re-embed both
   corpora with a chosen local model in a dedicated stage that records
   provider, model, dimensions, input template and canonicalisation).
2. Implement `SemanticRetriever` with the same `Retriever.search()` signature.
   It returns `RetrievalResult` objects with `retrieval_method = "semantic"`
   (add the constant to `models.METHODS` and a priority to
   `ranking.METHOD_PRIORITY`), using `embedding <=> query` on the HNSW indexes
   and the same citation builders.
3. Implement `HybridRetriever` that runs `LexicalRetriever` and
   `SemanticRetriever`, then fuses with an explicit, documented rule
   (reciprocal-rank fusion is the natural candidate; the previous application's
   logs suggest it used something similar, but its exact formula is not
   available and is not copied). `merge()` already handles de-duplication by
   key and "strongest method wins".
4. Re-run `scripts/evaluate_retrieval.py` on the unchanged `retrieval_v1.jsonl`
   with `--pipeline retrieval-hybrid` and compare against the lexical baseline
   above, especially the `difficult_lexical` and `terminology_variation`
   rows.

Nothing in this stage sends retrieved text to Qwen. That is the next stage.
