# Regulus database architecture (as discovered)

Stage 4 inspection of the existing `regulus` PostgreSQL database.
Everything in this document was read from the live database on 2026-09-15.
Nothing was modified. Where a fact is inferred rather than observed, it is
marked as such.

## 1. Overview

| Item | Value |
|---|---|
| Database | `regulus` |
| Server | PostgreSQL 18.4 (Windows x64), localhost:5432 |
| Size | 1157 MB |
| Schemas | `public` only |
| Tables | 76 (all in `public`) |
| Views | 1 (`usable_crosswalk`) |
| Materialized views | 0 |
| Sequences | 4 (audit log, credit ledger, credit consumption, login attempts) |
| Indexes | 241 |
| Functions | 5 user-defined (`regulus_id`, `set_updated_at`, `forbid_mutation`, `forbid_approved_clause_mutation`, `array_is_set`) |
| Triggers | 25 (`updated_at` maintenance and append-only guards) |
| Extensions | vector 0.8.6, citext 1.8, pg_trgm 1.6, pgcrypto 1.4, btree_gist 1.8, plpgsql |
| Schema management | Prisma Migrate, 42 migrations (`0_init` .. `0041_acceptance_benchmark`), applied 2026-09-02 to 2026-09-15 |
| Roles | `regulus_owner` (owns all 322 relations), `regulus_app` (application role), `postgres` (superuser) |

The database is the backend of a complete, previously built regulatory
question-answering platform, not just a corpus store. Of the 76 tables,
roughly 22 hold regulatory content and its ingestion/verification state.
The rest are application tables: users, organisations, sessions, MFA,
billing and credits, Stripe, API clients, audit log, outbox, videos,
enquiries, an answer/verification pipeline, and an evaluation harness.

### Table categories

| Category | Tables |
|---|---|
| eCFR content (Title 21) | `cfr_subchapters`, `cfr_parts`, `cfr_subparts`, `cfr_sections`, `cfr_records`, `cfr_record_versions` (empty), `cfr_cross_references`, `cfr_definitions`, `cfr_lexeme_stats`, `incorporated_standards` (empty) |
| FDA guidance | `fda_guidance`, `fda_guidance_chunks`, `fda_guidance_anchors`, `guidance_index_entries`, `guidance_verifications`, `guidance_anchor_escalations` |
| Federal Register | `federal_register_docs` (empty) |
| Ingestion / operations | `ingestion_runs`, `completeness_audits`, `job_runs` |
| Answer pipeline (application) | `queries`, `retrieval_sets`, `retrieval_items`, `answers`, `answer_citations`, `answer_assertions`, `answer_assertion_records`, `gate_results`, `gate_checks`, `gate_failures`, `guidance_expansions` |
| Editorial / ISO crosswalk (application) | `reviewed_content`, `reviewed_content_versions`, `iso_clause_index_versions`, `iso_clauses`, `cfr_iso_crosswalk`, `usable_crosswalk` (view), `legacy_qsr_terms`, `part820_section_flags` |
| Evaluation harness (application) | `evaluation_questions`, `evaluation_runs`, `evaluation_results`, `acceptance_*` (6 tables) |
| Accounts, billing, platform | `users`, `organizations`, `user_sessions`, `user_mfa_factors`, `mfa_challenges`, `password_reset_tokens`, `login_attempts`, `invitations`, `user_avatars`, `subscriptions`, `subscription_tiers`, `credit_*` (4), `billing_*` (2), `invoices`, `payment_events`, `api_clients`, `api_keys`, `idempotency_keys`, `outbox`, `admin_audit_log`, `videos`, `enquiries`, `bookmarks`, `saved_queries`, `_prisma_migrations` |

## 2. Important tables for the AI / RAG system

### `cfr_records` (Tier 1, the atomic regulation unit)

| | |
|---|---|
| Purpose | One row per verbatim paragraph of 21 CFR Chapter I, with full citation metadata. Table comment: "The only source of rule text shown to a user; never model-generated." |
| Rows | 65,341 (65,264 with embeddings; the 77 without are `[Reserved]` placeholder rows) |
| Primary key | `id` uuid (`regulus_id()`, UUIDv7) |
| Unique | (`section_number`, `paragraph_path`, `path_ordinal`) |
| Citation columns | `title` (always '21'), `chapter` (always 'I'), `subchapter_code`, `part_number`, `subpart_id`, `section_number`, `paragraph_path` (e.g. `(b)(1)`), `path_ordinal`, `ordinal`, `section_heading`, `parent_headings text[]` |
| Text | `body_text` (avg 218 chars, p95 639, max 3,388). One paragraph per row, so no chunking was needed. |
| Source | `ecfr_permalink` (100% populated), `govinfo_pdf_url` (100%), `source_endpoint` (eCFR versioner API URL, 100%), `fr_citation` (76% populated) |
| Dates / versions | `effective_date` (100%, but every value equals the snapshot date, so it is not the true section effective date), `last_amended_date` (0% populated), `snapshot_date` (all `2026-09-03`), `retrieved_at`, `created_at`, `updated_at`, `removed_on` (none set), `content_sha256`, `source_payload_sha256` |
| Embedding | `embedding halfvec(1024)`, `embedding_model`, `embedded_at`, `embedding_source_sha256`. CHECK constraint forces model + timestamp + source hash whenever a vector is present. |
| Lexical | `search_vector tsvector` (generated: heading weight A, body weight B), GIN index; trigram GIN on `section_heading` and `section_number` |
| Foreign keys | to `cfr_subchapters.code`, `cfr_parts.number`, `cfr_subparts.id`, `cfr_sections.number`, `incorporated_standards.id` |
| Referenced by | `answer_citations`, `answer_assertion_records`, `retrieval_items`, `cfr_cross_references`, `cfr_definitions`, `cfr_record_versions`, `reviewed_content`, `bookmarks` |

Representative rows (body previews):

```text
21 CFR 820.10        | ord 0 | "A manufacturer subject to this part as described by § 820.1(a) must:"
21 CFR 820.10(a)     | ord 1 | "(a) Document. Document a quality management system that complies with..."
21 CFR 820.10(b)(1)  | ord 3 | "(1) For Clause 7.5.8 in ISO 13485, Identification, the manufacturer must..."
21 CFR 211.22(a)     | ord 0 | "(a) There shall be a quality control unit that shall have the responsibility..."
parent_headings example: {"Medical Devices","Part 820 - Quality Management System Regulation", ...}
ecfr_permalink example: https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-820/section-820.10
```

### `cfr_subchapters`, `cfr_parts`, `cfr_subparts`, `cfr_sections` (eCFR hierarchy)

| Table | Rows | Key | Notable columns |
|---|---:|---|---|
| `cfr_subchapters` | 12 (A to L) | `code` | `title`, `part_range`, `sort_order` |
| `cfr_parts` | 250 (9 reserved ranges) | `number` | `title`, `subchapter_code`, `ecfr_permalink`, `govinfo_pdf_url`, `last_amended_date` (never populated), `is_reserved` |
| `cfr_subparts` | 925 | `id` | `part_number`, `designation`, `title`, `sort_order` |
| `cfr_sections` | 7,906 (77 reserved) | `number` (e.g. `820.10`) | `heading`, `part_number`, `subpart_id`, `effective_date` (never populated), `sort_order`; trigram indexes on number and heading |

No text lives in these tables; they carry the hierarchy and headings only.

### `fda_guidance` (Tier 3, guidance documents)

| | |
|---|---|
| Purpose | One row per FDA guidance document, holding the full extracted text and document-level metadata. Table comment: "FDA guidance, non-binding in all output, anchored to Title 21 by schema." |
| Rows | 1,836 total; 1,208 `retrievable = true`; 628 held out (`missing_fields` non-empty, mostly missing `disclaimer_text` and/or `docket_number`) |
| Primary key | `id` uuid |
| Unique | `source_url` |
| Metadata | `title`, `doc_class` (all 'guidance'), `status` (draft/final), `issuing_office`, `center` (CDER/CBER/CDRH/CTP/CFSAN/CVM/OCE/OTHER), `sector` (drug/biologic/device/food/supplement/tobacco/cosmetic), `docket_number`, `issued_on`, `comment_close_date`, `disclaimer_text`, `supersedes_id` (self FK) |
| Regulatory anchor | `anchor_part` (NOT NULL) and `anchor_section`: the primary 21 CFR part/section the document is tied to. Additional anchors in `fda_guidance_anchors`. |
| Text | `body_text` (avg 46,618 chars per document; 100% populated) |
| Source | `source_url` (must match `https://www.fda.gov/`), `source_endpoint` |
| Dates / versions | `issued_on` (11 nulls, some sentinel `1900-01-01`), `retrieved_at`, `verified_at`, `last_verified_at` (never populated), `under_review_since`, `withdrawn_at`, `created_at`, `updated_at`, `retrieval_hash` (SHA-256 of the fetched source) |
| Embedding | none at document level |

Sample retrievable rows:

```text
"Dental Curing Lights - Premarket Notification (510(k)) Submissions" | final | CDRH | device | anchor 807 / 807.87 | FDA-2024-D-2512
"Evaluation of Therapeutic Equivalence"                             | final | CDER | drug   | anchor 314 / 314.3  | FDA-2022-D-0528
"Draft CVM GFI #256B - Compounding Animal Drugs ..."                | draft | CVM  | food   | anchor 207 / 207.1  | FDA-2018-D-4533
```

### `fda_guidance_chunks` (guidance retrieval units and the 68,669 embeddings)

| | |
|---|---|
| Purpose | Guidance `body_text` split into overlapping passages, each embedded. Table comment: "Anchored via fda_guidance, never independently." |
| Rows | 68,669; every row has an embedding, none stale. 51,238 chunks belong to retrievable documents, 17,431 to held-out documents. |
| Primary key | `id` uuid |
| Unique | (`guidance_id`, `ordinal`) |
| Chunk fields | `guidance_id` (FK, cascade delete), `ordinal` (0-based order within document; max 1,175), `start_offset` (character offset into `fda_guidance.body_text`), `body_text`, `title_text` (equals the parent document title in every sampled row), `content_sha256` (= SHA-256 of `body_text`, verified on a sample) |
| Chunk size | 213 to 1,501 characters, median 1,459, mean 1,440. Consecutive chunks overlap by about 200 characters (66,828 of 66,833 consecutive pairs overlap). No token count, page, heading or section fields exist on the chunk. |
| Embedding | `embedding halfvec(1024)`, `embedding_model`, `embedded_at`, `embedding_source_sha256` |
| Lexical | `search_vector tsvector` (title weight A, body weight B), GIN index |
| Referenced by | `retrieval_items.guidance_chunk_id` |

Sample (one document, first chunks):

```text
ord 0 | start 0    | len 1480 | "Questions and Answers About Requirements for Additional Traceability Records..."
ord 1 | start 1281 | len 1430 | "d........4 III. Questions and Answers.......5 A. Farms......5 B..."   (table of contents noise)
ord 2 | start 2512 | len 1441 | ". I. Introduction On November 21, 2022, the Food and Drug Administration..."
```

Traceability check on a 300-chunk sample: the parent document text contains
every chunk verbatim (300/300); `start_offset` points exactly at the chunk in
261/300 cases, and is off by one leading whitespace character in the rest.

### `fda_guidance_anchors`

11,727 rows (all 1,836 documents have at least one). Columns: `guidance_id`,
`part`, `section` (nullable; 8,960 populated), `derived_from` (all
`document_text`). Unique on (`guidance_id`, `part`, `section`). This is the
many-to-many link from a guidance document to the 21 CFR parts/sections it
cites. It links by text value, not by foreign key to `cfr_parts` or
`cfr_sections`.

### Supporting content tables

| Table | Rows | What it holds |
|---|---:|---|
| `cfr_cross_references` | 17,168 | "§ 101.7(f)" style references extracted from record text, resolved to a target `cfr_records` row where possible (15,655 resolvable). |
| `cfr_definitions` | 2,857 | Marks records that are definition paragraphs, attached as context per part. `term` is empty in sampled rows. |
| `cfr_lexeme_stats` | 24,517 | Document frequency per lexeme over the live corpus, used for query-term weighting (IDF-like). |
| `guidance_index_entries` | 2,787 | Staging copy of FDA's guidance index: 1,836 promoted into `fda_guidance`, 951 escalated (no 21 CFR anchor found). Carries `regulated_products`, `communication_type`, `pdf_url`, `first_seen_at`, `last_seen_at`, `source_changed_at`. |
| `guidance_verifications` | 3,188 | Append-only log of re-checks against FDA.gov: 2,370 verified, 817 rejected, 1 changed. Last check 2026-09-09. |
| `guidance_anchor_escalations` | 1,162 | Documents refused for lack of a Title 21 anchor, all unresolved. |
| `ingestion_runs` | 841 | One row per ingestion of kind `cfr`, `guidance`, `federal_register`, `embeddings`, with state, counts, `snapshot_date`, `manifest_sha256`, resume `checkpoint` jsonb. |
| `completeness_audits` | 6 | Per-ingestion audit: last full audit `pass`, 250/250 parts, 65,341 records, snapshot 2026-09-03. |
| `cfr_record_versions` | 0 | Designed to hold superseded paragraph text with a `daterange`; append-only. Empty because only one snapshot has ever been ingested. |
| `federal_register_docs` | 0 | Tier 2 rulemaking documents. Schema exists, never populated. |
| `incorporated_standards` | 0 | Pointers to standards incorporated by reference. Empty. |

## 3. Relationships (as they actually exist)

```text
eCFR (Title 21, Chapter I)                       FDA guidance (fda.gov)

[cfr_subchapters] code (A..L)                    [guidance_index_entries]  (staging, 2,787)
      |  1:N                                           |  promoted -> guidance_id
      v                                                v
[cfr_parts] number --------+                     [fda_guidance]  (1,836 docs, full body_text,
      |  1:N               |                           |          source_url, anchor_part/section,
      v                    |                           |          issued_on, status, center, sector)
[cfr_subparts] id          |                           +-- 1:N --> [fda_guidance_anchors] (part, section: text, no FK)
      |  1:N (optional)    |                           +-- 1:N --> [guidance_verifications] (append-only audit)
      v                    |                           |
[cfr_sections] number <----+                           +-- 1:N --> [fda_guidance_chunks]  (68,669 chunks)
      |  1:N                                                           +-- embedding halfvec(1024)  <- stored IN the chunk row
      v                                                                +-- search_vector tsvector   <- generated column
[cfr_records]  (65,341 paragraphs = the chunk unit)
      +-- embedding halfvec(1024)   <- stored IN the record row
      +-- search_vector tsvector    <- generated column
      +-- 1:N --> [cfr_cross_references] --> cfr_records (resolved target)
      +-- 1:1 --> [cfr_definitions]
      +-- 1:N --> [cfr_record_versions]  (empty)

Cross-source link: fda_guidance.anchor_part / anchor_section and
fda_guidance_anchors.part / section are plain text values that match
cfr_parts.number / cfr_sections.number. There is no foreign key; the join
is by value.

Ingestion provenance: [ingestion_runs] --> [completeness_audits]
Answer provenance:    [queries] --> [retrieval_sets] --> [retrieval_items] --> cfr_records | fda_guidance_chunks
                      [queries] --> [answers] --> [answer_citations] --> cfr_records (FK)
```

Key structural facts:

- There is no separate `documents`, `sources`, `sections`, `chunks` or
  `embeddings` table. Embeddings are columns on the two content tables.
- For eCFR there is no chunking layer: the paragraph row is the retrieval
  unit and the embedding unit.
- For guidance, the document row holds the whole text and the chunk table
  holds overlapping windows over it.
- Citations built by the existing platform (`answer_citations`) reference
  `cfr_records` only; guidance chunks are surfaced separately as
  "availability" (see `answers.guidance_availability`).

## 4. Embeddings

| | eCFR (`cfr_records`) | Guidance (`fda_guidance_chunks`) |
|---|---|---|
| Column | `embedding` | `embedding` |
| Type | `halfvec(1024)` (pgvector half-precision) | `halfvec(1024)` |
| Rows with vector | 65,264 of 65,341 | 68,669 of 68,669 |
| Rows without | 77 (all `[Reserved]` stubs) | 0 |
| Stale (source hash mismatch) | 0 | 0 |
| Model recorded in `embedding_model` | `text-embedding-3-large` on all 65,264 | `text-embedding-3-large` on all 68,669 |
| `embedded_at` range | 2026-09-11 12:55 to 13:59 (+05:30) | 2026-09-11 14:12 to 14:41 (+05:30) |
| Vector norms (sample of 500) | 0.9998 to 1.0002 (unit-normalised) | 0.9998 to 1.0002 (unit-normalised) |
| Index | `cfr_records_embedding_idx` HNSW, `halfvec_cosine_ops`, m=16, ef_construction=200, 170 MB, valid | `fda_guidance_chunks_embedding_idx` HNSW, `halfvec_cosine_ops`, m=16, ef_construction=200, partial `WHERE embedding IS NOT NULL`, 179 MB, valid |
| Distance operator | `<=>` (cosine distance) | `<=>` (cosine distance) |
| Planner uses index for `ORDER BY embedding <=> $q LIMIT k` | yes (verified with EXPLAIN) | yes (verified with EXPLAIN) |
| Relationship to chunk | 1:1, same row | 1:1, same row |
| Foreign key embedding to chunk | not applicable (same row) | not applicable (same row) |

### Embedding model provenance

The per-row `embedding_model` column records `text-embedding-3-large` for
every embedded row in both tables, and a CHECK constraint on `cfr_records`
makes it impossible to store a vector without a model name. The
`embedded_at` timestamps show the whole corpus was embedded in one session on
2026-09-11, and `ingestion_runs` shows a matching `embeddings` run that
created 42,352 vectors (with 11 earlier timed-out attempts).

Two caveats:

1. The column comment on `cfr_records.embedding` says "Semantic vector,
   voyage-3-large 1024 dimensions". This contradicts the stored model name.
   The comment is documentation from the schema author; the column value was
   written by the embedding pipeline at run time, so the value is the more
   reliable evidence. The data is consistent with OpenAI's
   `text-embedding-3-large` called with `dimensions=1024` (its native size is
   3072), but the database does not record the dimension parameter, API
   provider, endpoint, or any input formatting (for example whether
   `title_text` was prepended to `body_text` before embedding).
2. No configuration table, pipeline-metadata table or jsonb field holds the
   embedding configuration. The `ingestion_runs.checkpoint` for embedding
   runs contains only `{"completedParts": []}`.

Conclusion: the model name is established from the data as
`text-embedding-3-large`, but the exact invocation (provider, truncation
dimension, input text construction, normalisation) is **not** recorded and
must be confirmed from the original ingestion code before query embeddings
can be generated compatibly. The `embedding_source_sha256` column equals
`content_sha256`, which is a hash of `body_text` alone; that suggests, but
does not prove, that only `body_text` was embedded.

## 5. Regulatory metadata (citation readiness)

| Field | eCFR (`cfr_records` and hierarchy) | FDA guidance (`fda_guidance`) |
|---|---|---|
| source / agency | implied (eCFR Title 21, FDA); `source_endpoint` holds the API URL | implied (FDA); `center` gives the issuing center |
| source_url | `ecfr_permalink` (100%), `govinfo_pdf_url` (100%) | `source_url` (100%, unique), `guidance_index_entries.pdf_url` |
| document_title | `section_heading`, `parent_headings[]`, `cfr_parts.title`, `cfr_sections.heading` | `title` |
| CFR title | `title` (always 21) | via anchor only |
| CFR chapter | `chapter` (always I) | none |
| CFR subchapter | `subchapter_code` + `cfr_subchapters.title` | derivable via anchor_part to `cfr_parts.subchapter_code` |
| CFR part | `part_number` + `cfr_parts.title` | `anchor_part` + `fda_guidance_anchors.part` |
| CFR section | `section_number` + heading | `anchor_section` + `fda_guidance_anchors.section` (nullable) |
| subsection / paragraph | `paragraph_path` e.g. `(b)(1)` (96% of rows) | none (chunks have no section/heading position) |
| guidance title | none | `title` |
| guidance identifier | none | `docket_number` (FDA-YYYY-D-NNNN; missing on about 230 docs), `source_url` |
| publication date | `fr_citation` text (76%) | `issued_on` (11 null, some sentinel 1900-01-01) |
| effective date | `effective_date` column exists but every value equals the snapshot date `2026-09-03`; `cfr_sections.effective_date` and `cfr_parts.last_amended_date` are never populated | none |
| updated date | `updated_at`, `retrieved_at`, `snapshot_date` | `updated_at`, `retrieved_at`, `verified_at`, `source_changed_at` (index entry) |
| document version | `content_sha256`, `source_payload_sha256`, `snapshot_date`; history table exists but empty | `retrieval_hash`, `supersedes_id`, `status` draft/final |

```text
Available: source_url, document_title, CFR title/chapter/subchapter/part/section,
           paragraph path, guidance title, docket number, issued date,
           draft/final status, issuing center, snapshot date, content hashes,
           ingestion timestamps.
Missing:   true per-section effective/amendment dates (columns exist, not
           populated); guidance page/section/heading position for a chunk;
           Federal Register documents (table empty); paragraph-level guidance
           citation.
Unclear:   fr_citation is populated for 76% of records and its format was
           not validated; issued_on has 1900-01-01 sentinels; anchor_section
           on guidance is the pipeline's inference, not FDA metadata.
```

A full eCFR citation of the form
`21 CFR 820.10(b)(1), Requirements for a quality management system` with an
eCFR permalink is reconstructible from a single `cfr_records` row. A guidance
citation of the form `FDA Guidance "Title" (Docket FDA-2024-D-2512, final,
CDRH, issued 2026-09-02), <source_url>` is reconstructible from
`fda_guidance_chunks` joined to `fda_guidance`, but the chunk can only be
located within the document by character offset, not by page or heading.

## 6. Data freshness and versioning

| Signal | Where | Observed value |
|---|---|---|
| eCFR snapshot date | `cfr_records.snapshot_date`, `ingestion_runs.snapshot_date`, `completeness_audits.ecfr_snapshot_date`, `queries.snapshot_date` | single snapshot, `2026-09-03` |
| eCFR ingestion time | `cfr_records.retrieved_at` / `created_at` | 2026-09-07 |
| eCFR last successful run | `ingestion_runs` kind `cfr` | 2026-09-07, succeeded, audit pass 250/250 parts |
| eCFR content hash | `cfr_records.content_sha256`, `source_payload_sha256` | 100% |
| eCFR history | `cfr_record_versions` | empty (one snapshot only) |
| Guidance fetch time | `fda_guidance.retrieved_at` | 2026-09-07 to 2026-09-09 |
| Guidance source hash | `fda_guidance.retrieval_hash`, `guidance_verifications.content_hash` | 100%; last verification 2026-09-09 |
| Guidance issue date | `fda_guidance.issued_on` | range 1900-01-01 (sentinel) to 2026-09-08 |
| Guidance index changes | `guidance_index_entries.first_seen_at/last_seen_at/source_changed_at` | present |
| Embedding time | `embedded_at` on both tables | 2026-09-11 |
| Embedding staleness detection | `embedding_source_sha256 <> content_sha256` + partial "needs embedding" indexes | 0 stale |

The database can state exactly when its content was ingested and which
eCFR snapshot it reflects. It cannot state when a given section was last
amended by FDA, because `last_amended_date` and `cfr_sections.effective_date`
were never populated.

## 7. Existing retrieval infrastructure

Everything below already exists in the database; nothing is being proposed.

| Component | Detail |
|---|---|
| Vector search | HNSW cosine indexes on both content tables (see section 4). `hnsw.ef_search` is at its default (40). |
| Full-text search | Generated `search_vector` tsvector columns (English config, heading/title weight A, body weight B) with GIN indexes on `cfr_records` and `fda_guidance_chunks`. |
| Corpus statistics | `cfr_lexeme_stats` (lexeme to document count) to weight query terms. |
| Trigram / fuzzy | `pg_trgm` GIN indexes on `cfr_records.section_heading`, `cfr_records.section_number`, `cfr_sections.heading`, `cfr_sections.number` (section-number and heading lookup). |
| Metadata filters with indexes | `cfr_records` (subchapter, part, section, ordinal, `removed_on IS NULL`); `fda_guidance` (`retrievable`, `sector`, `anchor_part`/`anchor_section`, `issued_on`); `fda_guidance_chunks` (`guidance_id`, `ordinal`). |
| Stored procedures / SQL search functions | none. The 5 user functions are ID generation, timestamp maintenance and immutability guards. Retrieval logic lived in the application, not in the database. |
| Views | `usable_crosswalk` only (ISO 13485 mapping). |
| Evidence of the previous retrieval design | `retrieval_sets` / `retrieval_items` log a hybrid pipeline: paths `direct-lookup` and `hybrid-search`, three legs (`lexical_rank`, `semantic_rank`, `trigram_rank`) fused into a `score` (values around 0.04, consistent with reciprocal-rank fusion), `relevance_threshold` 0.28, candidates then retained. Items mix `cfr_records` (1,603) and `fda_guidance_chunks` (184). `answers.model_name` shows the previous generator was `gpt-5.5`. |

## 8. Retrieval readiness for this project

Already available:

- A complete, audited eCFR Title 21 corpus at paragraph granularity with
  full citation metadata and permalinks.
- 1,208 retrievable FDA guidance documents chunked into overlapping ~1,450
  character windows, each traceable to its document and source URL.
- Cosine HNSW indexes and full-text indexes on both corpora, all valid and
  used by the planner.
- Content hashes and timestamps sufficient to detect stale vectors and to
  report "current as of 2026-09-03".

Missing or unresolved before RAG can be built:

1. **Query-side embedding compatibility.** Vectors are attributed to
   `text-embedding-3-large` at 1024 dimensions, but provider, dimension
   parameter and input formatting are not recorded. Query embeddings must be
   produced the same way or similarity scores are meaningless. The local
   Qwen3-0.6B model cannot produce these vectors.
2. **No Python integration.** The project has no PostgreSQL driver, no
   pgvector client, no connection configuration and no SQL.
3. **Guidance chunk positioning.** Chunks carry only a character offset;
   no page, heading or section identifier. Table-of-contents chunks (dot
   leaders) were embedded as-is.
4. **Effective/amendment dates** are not populated; freshness can only be
   expressed as the snapshot date.
5. **Federal Register** and **record version history** tables are empty.
6. **Retrieval logic** (hybrid fusion, thresholds, direct-lookup parsing)
   is not in the database; only its outputs are logged.
7. `hnsw.ef_search`, `work_mem` (4 MB) and `shared_buffers` (128 MB) are at
   installer defaults; not a blocker, but relevant for latency later.

## 9. Security and access (values withheld)

- Roles: `regulus_owner` owns every relation and is used for migrations;
  `regulus_app` is the intended application role. Neither is a superuser and
  neither can create databases.
- `regulus_app` has SELECT on all 76 tables plus the view, INSERT on 68,
  UPDATE on 55 and DELETE on 30. It is SELECT-only on the migration ledger,
  lexeme stats, acceptance benchmarks and the crosswalk view, and cannot
  DELETE from the regulatory corpus, answer pipeline or audit-style tables.
  Default privileges grant it read/write on future tables. This is a
  broad but not unlimited application role.
- Append-only tables are enforced by triggers, not by privileges.
- Row-level security is not enabled anywhere.
- Server authentication is `scram-sha-256` on localhost only
  (`pg_hba` allows 127.0.0.1 and ::1); `listen_addresses` is `*` and SSL is
  off. Suitable for a development machine only.
- Credentials for `postgres`, `regulus_owner` and `regulus_app` were set on
  this machine during the restore and are development-only. They are not
  stored anywhere in this repository, and this document intentionally omits
  them.
- The `users` table stores `password_hash` (scrypt, per the column comment)
  and `api_keys` stores only `key_hash`/`key_prefix`; no plaintext secrets
  were observed in the schema.

## 10. Verification that nothing changed

Before inspection, a schema-only `pg_dump` (6,017 lines) and per-table live
row counts were captured. The same capture was repeated after inspection:
row counts for all 76 tables were identical, and the schema dumps were
identical apart from the random `\restrict` session token that pg_dump 18
emits on every run. Cumulative update and delete counters for every table
were zero. All inspection used `SELECT`, `EXPLAIN` without `ANALYZE`,
catalog reads and `\d` metadata commands only.
