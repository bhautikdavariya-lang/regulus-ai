# Embedding Provenance — `cfr_records.embedding` and `fda_guidance_chunks.embedding`

Stage 4.5 investigation. Read-only. Nothing in the repository, the database or
the model was modified. Every database session in this investigation ran with
`default_transaction_read_only = on`.

Date of investigation: 2026-09-15. Database: `regulus` on localhost (PostgreSQL
18.4, pgvector 0.8.6), restored on 2026-09-15 from `regulus db backup.sql`
(pg_dump custom format, dumped from PostgreSQL 18.4).

---

## 1. Executive summary

**Classification: UNVERIFIED** (see section 11 for the exact reasoning).

- **The ingestion source code is not on this machine.** The database was built by
  a separate Prisma/Node application (42 Prisma migrations, `gpt-5.5` answer
  generator). No copy of that application, its `schema.prisma`, its migration SQL,
  its `.env` or its embedding code exists anywhere on this computer. Only the
  database dump and the restore scripts were transferred. The only code project
  here that mentions eCFR (`AI Model Implementation/LLM-DEMO`) is an unrelated
  from-scratch Python model and never touches PostgreSQL, Prisma or an embedding
  API.
- **What the database does establish:** every current vector (65,264 eCFR rows,
  68,669 guidance chunks) was written on 2026-09-11 between 12:55 and 14:41
  IST, labelled `text-embedding-3-large`, stored as `halfvec(1024)`, unit-length,
  in batches of 128 rows. The embedding source hash is `sha256` of the chunk
  `body_text` (guidance) or of a canonicalised form of `body_text` (eCFR) and
  never includes headings, titles or citation metadata.
- **Provider history:** the schema was designed for `voyage-3-large` (column
  comment), the first embedding run on 2026-09-07 failed against
  `api.voyageai.com`, and by 2026-09-11 every vector was re-written under the
  `text-embedding-3-large` label. The host actually called on 2026-09-11 is not
  recorded anywhere.
- **What cannot be established:** the provider/endpoint used for the current
  vectors, whether `dimensions=1024` was requested from the API or the vectors
  were truncated and re-normalised client-side, the exact string sent to the API
  (stored text vs canonicalised text, with or without any prefix), and any
  tokenisation or truncation policy. These are precisely the details that decide
  whether a query embedding will land in the same vector space.

The consequence for Stage 5 is in section 13.

---

## 2. Source-code evidence

### 2.1 Where the code was looked for

| Location | Result |
|---|---|
| `C:\Users\PC-1\Prachi Patel\AI Model Implementation\LLM-DEMO` (+ the 950 MB zip of it) | Unrelated project: custom Python LLM trained on eCFR Part 800 text, own tokenizer and checkpoints, Flask-style demo server. No PostgreSQL, Prisma, pgvector, OpenAI or Voyage references outside its virtualenv. |
| Every Prisma project on the machine (`healthsecure-portal`, `Demo/employee-management`, `EmployeeManagementSystem`) | Unrelated schemas (May–August 2026); none defines `cfr_records`, `fda_guidance_chunks` or any embedding column. |
| `C:\Users\PC-1\source\repos`, `C:\DocuVault`, `C:\Users\PC-1\DocuVault`, `C:\inetpub`, `C:\Maven`, `C:\Users\PC-1\New folder`, `Downloads`, `Desktop`, `Documents`, `Prachi Patel.zip` | No regulus application code, no `schema.prisma` for it, no migration SQL, no `.env` referencing an embedding provider. |
| Docker images, WSL distributions | Docker not installed; no WSL distributions. |
| Full-text search of all code directories (excluding virtualenvs and `node_modules`) for `text-embedding-3-large`, `embeddings.create`, `embedding_source_sha256`, `halfvec`, `cfr_records`, `fda_guidance_chunks`, `regulus_app`, `voyage` | Only hit: this repository's own `docs/database_architecture.md`. |
| Environment variables in both shells (`PG*`, `DATABASE*`, `OPENAI*`, `VOYAGE*`, `EMBED*`), `%APPDATA%\postgresql\pgpass.conf` | None set; no pgpass file. |

### 2.2 What does exist

- `C:\Users\PC-1\Downloads\regulus db backup.sql` — the pg_dump (custom format,
  694 MB). Contains data and DDL, not application code. Migration SQL is not in a
  dump; only the `_prisma_migrations` ledger (names, checksums, timestamps) is.
- `C:\Users\PC-1\Downloads\restore-regulus.ps1` and `install-pgvector-pg18.ps1`
  — restore helpers written on this machine. The restore script contains the
  local `postgres` password, which is why it is not quoted here and must not be
  committed.

**Conclusion of the code search:** questions 1, 3, 4, 5, 6, 7, 9 and 11 of the
stage brief (provider, dimensions configuration, input text, per-corpus
differences, normalisation, headings, truncation, generating script) cannot be
answered from source code because there is no source code to inspect. Everything
below is database evidence.

---

## 3. eCFR embedding pipeline (`cfr_records`)

Reconstructed from `ingestion_runs`, column comments, constraints and the data.

| Step | Evidence |
|---|---|
| Schema created with an embedding column intended for Voyage | Migration `0017_regulatory_corpus` (2026-09-07). Column comment on `cfr_records.embedding`: *"Semantic vector, voyage-3-large 1024 dimensions. Null until the backfill reaches this row."* |
| Paragraph rows ingested | 4 `ingestion_runs` of kind `cfr` on 2026-09-07 12:25–12:45. `created_at` on all rows is 2026-09-07 ~12:38. |
| First backfill attempt against Voyage AI failed | `ingestion_runs` 2026-09-07 12:48:28, kind `embeddings`, state `failed`, `failure_reason`: *"api.voyageai.com answered 429 on every one of 4 attempts."* |
| Three small successful runs the same day | 2026-09-07 12:50 (8 records), 15:40 (32), 15:53 (48). Whatever they wrote no longer exists as such: no row has `embedded_at` before 2026-09-11. |
| Provider/model changed | Not recorded. Between 2026-09-07 and 2026-09-11 migrations `0026`–`0034` were applied, including `0034_rebuild_hnsw_graphs` (consistent with vectors being replaced), but their SQL is unavailable. The column comment was never updated. |
| Full backfill on 2026-09-11 | 12 runs from 12:55 to 13:59. Ten are `failed` with *"The operation was aborted due to timeout"* after writing 128–7,936 records each; the final run (13:40–13:59) succeeded with 42,352. Sum of `records_created` on that day = 65,264 = number of embedded rows. Batches were committed incrementally, so a timed-out run kept its completed batches. |
| Every row labelled and stamped | `embedding_model = 'text-embedding-3-large'`, `embedded_at` 2026-09-11 12:55:23 – 13:59:41 (+05:30), `embedding_source_sha256 = content_sha256` on all 65,264 rows. |
| 77 rows unembedded | All `is_reserved` stubs ("[Reserved]"), `embedding_model = ''`. |

Constraint `cfr_records_embedding_is_attributed` guarantees a non-null vector
always carries a model name, a timestamp and a source hash.

---

## 4. FDA guidance embedding pipeline (`fda_guidance_chunks`)

| Step | Evidence |
|---|---|
| Chunk table created | Migration `0029_guidance_chunks` (2026-09-11). No column comment on `embedding`; comment on `embedding_source_sha256`: *"The content hash the vector was computed from. Differs from content_sha256 exactly when the vector is stale."* |
| Chunks written and embedded in one pass | `created_at` and `embedded_at` both 2026-09-11 14:12 – 14:41. No `ingestion_runs` row of kind `embeddings` covers this window (the last one ends 13:59), so the guidance backfill either used a different job mechanism or was not logged. `job_runs` has no embedding-related rows either. |
| Every chunk labelled | `embedding_model = 'text-embedding-3-large'` on all 68,669; `embedding_source_sha256 = content_sha256 = sha256(body_text)` on all 68,669 (see section 7). |

---

## 5. Exact model / provider

| Property | eCFR | FDA guidance | Evidence |
|---|---|---|---|
| Model label stored per row | `text-embedding-3-large` (65,264 / 65,264) | `text-embedding-3-large` (68,669 / 68,669) | `embedding_model` column |
| Model per schema comment | `voyage-3-large` | none | column comment, never updated |
| Provider actually called for current vectors | **unknown** | **unknown** | no host, endpoint, API version or request id is stored for the 2026-09-11 runs |
| Provider evidence, earlier | Voyage AI (`api.voyageai.com`, 429) on 2026-09-07 | n/a | `ingestion_runs.failure_reason` |
| Generator model of the same application | `gpt-5.5` | `gpt-5.5` | `answers.model_name` |

`text-embedding-3-large` is an OpenAI model name, and the same application used
an OpenAI generation model. That makes OpenAI (direct or via Azure OpenAI or a
proxy) the most plausible provider for the 2026-09-11 vectors, but it is an
inference from a label, not a recorded fact.

---

## 6. Exact dimensionality configuration

| Property | eCFR | FDA guidance | Evidence |
|---|---|---|---|
| Column type | `halfvec(1024)` | `halfvec(1024)` | catalog |
| Actual vector length | 1024 on every sampled row (3,000 each) | 1024 | `array_length(embedding::real[], 1)` |
| L2 norm | 0.99976 – 1.00024 | 0.99976 – 1.00024 | `l2_norm()` on 3,000-row samples; deviation from 1.0 is consistent with fp16 storage of unit vectors |
| How 1024 was obtained | **unknown** | **unknown** | no configuration recorded |

The native output of `text-embedding-3-large` is 3072 dimensions. A 1024-length
unit vector is consistent with either (a) the API `dimensions: 1024` parameter,
which returns already-normalised shortened vectors, or (b) client-side truncation
of the first 1024 of 3072 values followed by re-normalisation. Both produce
unit-length 1024-vectors and both are compatible with each other in practice
(OpenAI documents the shortened output as the normalised prefix), but neither is
evidenced here. The stage brief's caution applies: the database dimension alone
does not prove `dimensions=1024` was passed.

---

## 7. Exact input construction

No code, so the only handle is `embedding_source_sha256`, which the schema
describes as the hash of the content the vector was computed from. Hashes were
recomputed in-database with `pgcrypto` (`digest(text, 'sha256')`, i.e. SHA-256
over the UTF-8 bytes) and compared with the stored values.

| Hypothesis for hashed text | eCFR (65,264 embedded rows) | Guidance (68,669 chunks) |
|---|---|---|
| `body_text` exactly as stored | 58,207 match (89.2%) | **68,669 match (100%)** |
| `section_heading + "\n" + body_text`, `heading + " " + body`, `paragraph_path + " " + body` | 0 | not applicable |
| `title_text` included in any form | not applicable | 0 (hash equals body-only hash on every chunk) |
| trimmed, whitespace-collapsed, CRLF→LF, trailing newline | 0 additional | — |
| Unicode NFKC only | 129 additional | — |
| Typographic punctuation folded to ASCII (— – → `-`; ‘ ’ → `'`; “ ” → `"`; ′ → `'`; ″ → `"`; − → `-`) | +6,363 | — |
| … plus µ (U+00B5) → μ (U+03BC) and Ω ohm sign (U+2126) → Ω (U+03A9) | +136 (running total 64,706) | — |
| … plus `§§` → `§` | +554 (**running total 65,260 = 99.994%**) | — |
| Unexplained | 4 rows | 0 |

Findings:

- **Guidance:** the hashed content is `body_text` alone, byte for byte, on every
  chunk. `title_text` is stored on the chunk (and used in the generated
  `search_vector`) but is not part of the hashed content. 45,597 chunks contain
  non-ASCII characters and still match, so no folding was applied on this path.
- **eCFR:** the hashed content is `body_text` after a canonicalisation step
  that folds typographic characters to ASCII equivalents, maps two compatibility
  characters to their Greek letters, and collapses the double section sign. The
  stored `body_text` retains the original typographic characters. Every one of
  the 7,057 rows whose raw hash differs contains at least one of these characters;
  no row without them differs. Headings, paragraph paths, parent headings,
  section numbers and citations are **not** in the hashed content.
- The 4 unexplained eCFR rows contain further combinations (e.g. curly quotes
  adjacent to `§§`) that the tested folds did not cover; they do not change the
  conclusion.

**What this does and does not prove.** It proves what text the change-detection
hash was computed over. It is strong circumstantial evidence that the embedding
input was body text only, with no heading, title or citation prefix. It does
**not** prove whether the API received the stored `body_text` or the canonicalised
form for eCFR, and it does not exclude an invisible prefix or instruction string
added at call time and not included in the hash (for a Voyage-style
`input_type`, for example). For guidance chunks the two candidate inputs coincide
(no folding), so the stored `body_text` is the best available reconstruction.

---

## 8. Normalisation / preprocessing

| Question from the brief | eCFR | FDA guidance | Evidence |
|---|---|---|---|
| Text normalised before hashing | Yes: typographic fold + µ/Ω mapping + `§§`→`§` (section 7) | No | hash reproduction |
| Text normalised before embedding | unknown (either stored or canonical text) | probably none (hash = stored text) | inference only |
| Headings / titles / metadata included | not in hashed content | not in hashed content | hash reproduction |
| Batching | Yes, 128 rows per batch: 503 timestamps carry exactly 128 rows, 3 carry 256, 1 carries 112. `records_created` in every run is a multiple of 128. | Yes, 128 rows per batch: 536 timestamps carry 128 rows, 1 carries 61. | `embedded_at` grouping |
| Truncation / token limits | Not needed: longest paragraph is 3,388 characters (well under 8,191 tokens). Whether a guard existed is unknown. | Not needed: longest chunk 1,501 characters (windows of ~1,450 chars with ~200 overlap, fixed at chunking time). | `max(length(body_text))` |
| Vectors normalised before storage | Unit length (fp16 rounding aside). Whether normalisation was done by the API or the client is unknown. | same | `l2_norm()` |
| Storage precision | `halfvec` (16-bit floats). The stored vector is a lossy copy of what the API returned. | same | catalog |

---

## 9. Database evidence (consolidated)

| Property | eCFR | FDA guidance | Evidence |
|---|---|---|---|
| Provider | unknown (Voyage AI attempted 2026-09-07; label implies OpenAI) | unknown (label implies OpenAI) | `ingestion_runs.failure_reason`, `embedding_model` |
| Model | `text-embedding-3-large` | `text-embedding-3-large` | `embedding_model` on every embedded row |
| Dimensions | 1024 (`halfvec(1024)`), mechanism unknown | same | catalog, `array_length` |
| Input construction | body text only; hashed form is canonicalised, sent form unknown | body text only, byte-exact | hash reproduction |
| Normalisation | canonicalisation of typographic characters before hashing | none | hash reproduction |
| Batching | 128 per batch | 128 per batch | `embedded_at` grouping |
| Token handling | no evidence; no text long enough to require it | no evidence; chunks are short | length statistics |
| Generation date | 2026-09-11 12:55:23 – 13:59:41 +05:30 | 2026-09-11 14:12:14 – 14:41:03 +05:30 | `embedded_at` |
| Current vector count | 65,264 of 65,341 (77 reserved stubs unembedded) | 68,669 of 68,669 | `count(*)` |
| Stale vectors | 0 (`embedding_source_sha256 = content_sha256` everywhere) | 0 | comparison |
| Index | HNSW, `halfvec_cosine_ops`, m=16, ef_construction=200 | same, partial on `embedding IS NOT NULL` | catalog (Stage 4) |
| Database-side functions that build embedding input | none (`l2_normalize` is pgvector's own; custom functions are `regulus_id`, `set_updated_at`, `forbid_mutation`, `forbid_approved_clause_mutation`, `array_is_set`, `fips_mode`) | — | `pg_proc` |
| Provider/config recorded in `ingestion_runs.checkpoint`, `job_runs.metrics`, `outbox`, `admin_audit_log` | no | no | pattern search for `openai|voyage|dimension|text-embedding` |

---

## 10. Reproducibility assessment

**Can a stored vector be regenerated from the source data and configuration?**
Not deterministically, for three independent reasons:

1. The provider call is unknown (host, model parameters, `dimensions`, any
   input-type or prefix flag). Two plausible configurations exist and they are not
   guaranteed to produce identical vectors.
2. Even with the right configuration, hosted embedding APIs are not bit-exact
   over time; providers document small run-to-run variation. Comparison must be by
   cosine similarity, not equality.
3. Storage is `halfvec`, so the stored value is already rounded to fp16.

**Can the expected input string be reconstructed for a sample row?** Yes for the
hashed form:

- eCFR sample: `cfr_records.id = 01a07aaa-764e-7810-b37b-7abfa14aa58e`, § 1.1(a),
  heading "General.", 193 characters, ASCII only. `sha256(body_text)` equals the
  stored `content_sha256`
  (`f5b4252845bffb538638ed54908e73abfee7a0604e92b223debe08d5bf1620e3`), so the
  hashed input was exactly:
  > (a) The provisions of regulations promulgated under the Federal Food, Drug, and Cosmetic Act with respect to the doing of any act shall be applicable also to the causing of such act to be done.
- Guidance sample: `fda_guidance_chunks.id = 01a08fa1-9da4-74cc-be0c-a0ab9102b317`,
  ordinal 0 of guidance `01a07b9a-3216-7a2d-b2ad-496fc411b281`, 1,480
  characters beginning "Questions and Answers About Requirements for Additional
  Traceability Records…"; `sha256(body_text)` equals the stored hash. The title
  is not part of the hashed input.

No external embedding API was called during this stage, as instructed.

A practical compatibility test for Stage 5, if an external API is acceptable:
embed 50 sampled `body_text` values with the candidate configuration, compare
against the stored vectors, and require cosine similarity above roughly 0.99 on
essentially all samples. A mismatch in provider or dimension handling shows up
immediately as similarities far below that. This test has not been run.

---

## 11. Compatibility assessment

**UNVERIFIED.**

The brief defines VERIFIED as "the original embedding invocation and input
construction are sufficiently established that we can safely generate compatible
query embeddings". That bar is not met:

- No source code or configuration for the invocation exists on this machine, so
  provider, endpoint, request parameters and input assembly are unobserved.
- The database records only a model label. It contradicts its own schema comment
  (`voyage-3-large`), and the one logged provider interaction is a failure against
  a different vendor four days before the current vectors were written.
- Dimension handling (API parameter vs client truncation) is not recorded.
- For eCFR, two different candidate input strings (stored vs canonicalised text)
  are both consistent with the evidence.

What *is* established, and would survive into a later VERIFIED status once the
call is confirmed: model label, 1024-dim unit vectors in `halfvec`, cosine
metric, body-text-only input with no heading/title prefix, batch size 128, the
exact eCFR canonicalisation applied before hashing, generation timestamps, zero
stale vectors.

The status is PARTIALLY VERIFIED only in the weaker sense that the *input text*
is well characterised; the *invocation* is not, and the invocation is what
determines the vector space.

---

## 12. Unknowns / gaps

1. Provider and endpoint for the 2026-09-11 vectors (OpenAI direct, Azure
   OpenAI, proxy) and API version.
2. Whether `dimensions: 1024` was requested or 3072-d output was truncated and
   re-normalised client-side.
3. Whether the eCFR API input was the stored `body_text` or the canonicalised
   text used for hashing; whether any prefix/instruction was prepended on either
   corpus.
4. Whether the guidance backfill (14:12–14:41) ran through the same code path as
   the eCFR backfill; it is not logged in `ingestion_runs`.
5. What the three small successful runs on 2026-09-07 (88 records) embedded
   with, and whether any Voyage vectors ever reached the table before the rewrite.
6. Client library, tokenizer/truncation guard, retry policy, and why ten
   2026-09-11 runs timed out (the timeouts did not corrupt data: batches were
   committed atomically, counts reconcile exactly).
7. The 4 eCFR rows whose hash canonicalisation is still unexplained.
8. The original application repository itself — its location, owner and whether
   it can be obtained.

---

## 13. Recommendation for Stage 5

1. **Obtain the original application code.** The only way to move to VERIFIED is
   to read the embedding call: the Prisma project whose migrations are
   `0_init` … `0041_acceptance_benchmark`, specifically the module that writes
   `embedding_model`, `embedded_at` and `embedding_source_sha256`, and its
   environment template. Ask the owner of the dump for the repository (or at
   least that module and `.env.example`). Confirm: provider SDK and base URL,
   model string, `dimensions` parameter, input assembly for each corpus, any
   input-type flag, batch size (expect 128), and the eCFR canonicalisation
   function (expect the folds listed in section 7).
2. **Decide the embedding strategy before writing any retrieval code.**
   - *Option A — keep the existing vectors.* Requires (1) and an OpenAI-compatible
     API key at query time. Run the 50-sample cosine check from section 10 before
     trusting it. Query embeddings would then be generated by an external API, not
     by Qwen; that is an architectural dependency to accept explicitly.
   - *Option B — re-embed both corpora with a chosen local model.* Removes the
     provenance problem and the external dependency at the cost of a re-embedding
     stage (133,933 texts) and new HNSW indexes. Qwen3-0.6B is a generator and
     cannot produce these vectors; a dedicated embedding model would be needed.
     This is a separate stage with its own document.
   - *Option C — lexical-first retrieval now.* The database already has GIN
     tsvector indexes, trigram indexes and lexeme statistics that need no
     embedding provenance. A hybrid pipeline can start lexical-only and add the
     semantic leg once A or B is settled.
3. **Whatever the choice, record provenance properly going forward:** provider,
   base URL, model, dimensions, input template, canonicalisation version and
   client library version, stored per row or per run, so this investigation never
   has to be repeated.
4. **Do not treat the `voyage-3-large` column comment as truth**; it is stale.
   If the schema is ever migrated, correct it.

Nothing has been implemented. No retrieval, query embedding, database
integration, package installation or model change was made in this stage.
