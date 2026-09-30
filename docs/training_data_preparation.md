# Training Dataset Preparation (Stage 11)

An instruction-tuning dataset built from the existing, read-only `regulus`
PostgreSQL database. No model generated any answer: every answer is verbatim
database text inside a fixed template. No data was downloaded, nothing was
written to the database, and no training was started.

Code: `src/regulus/training/` (`config`, `sources`, `text`, `models`,
`generators`, `negatives`, `dedup`, `splits`, `validate`, `pipeline`).
Scripts: `scripts/prepare_training_data.py`, `scripts/validate_training_data.py`,
`scripts/report_training_data.py`. Config: `configs/training.yaml`.
Tests: `tests/test_training_data.py` (21, model- and database-free),
`tests/integration/test_training_db.py` (2, read-only database).
Output: `data/training/datasets/` (see `data/training/README.md`).

---

## 1. Objective

Teach Qwen3-0.6B, in a later LoRA stage, how to (a) answer regulatory
questions from supplied context, (b) cite the sources it used, (c) tell
binding eCFR text from non-binding FDA guidance, (d) stay concise, and
(e) refuse when the identifier does not exist or the evidence is
insufficient. The dataset is a set of `question -> context -> answer`
records, not a copy of the corpus.

## 2. Sources (read-only)

| Source | Rows read | Used for |
|---|---:|---|
| `cfr_records` (live paragraphs) | 65,341 | eCFR context and answer text |
| `cfr_sections` / `cfr_subparts` / `cfr_parts` / `cfr_subchapters` | 7,906 / 925 / 250 / 12 | headings, hierarchy, part-level questions |
| `cfr_definitions` (with a `term`) | 1,921 | definition questions |
| `cfr_cross_references` (resolvable, cross-section) | 10,627 | relationship and multi-context questions |
| `fda_guidance` (`retrievable = true`) | 1,208 | guidance questions and citations |
| `fda_guidance_chunks` | 4,832 opening chunks, 1,188 "FDA recommends" chunks, 1,282 chunks citing the document's anchor section | guidance context |
| `fda_guidance_anchors` | 8,826 | guidance-to-section pairing (only when the chunk text cites the section verbatim) |

Not used: the 1024-dimensional embeddings (provenance UNVERIFIED), the 628
held-out guidance documents, all application tables. The session runs with
`default_transaction_read_only = on` (verified before loading; the pipeline
refuses to run otherwise) and the loader is `SELECT`-only.

Snapshot reference recorded in the manifest: eCFR snapshot `2026-09-03`
(65,341 live records, 7,906 sections, 250 parts); guidance last retrieved
`2026-09-09` (1,836 documents, 1,208 retrievable, 68,669 chunks).

## 3. Pipeline

```
read-only database
   -> source selection (sources.py: whole hierarchy + paragraphs in memory, ~40 MB)
   -> generators (one per category; deterministic templates over verbatim text)
   -> negatives (identifiers proven absent from the snapshot)
   -> de-duplication (exact key; near-duplicate Jaccard >= 0.9 within a source group)
   -> benchmark exclusion (baseline_v1, retrieval_v1, retrieval_v2 questions)
   -> per-category caps (target x share; round-robin over subtypes in hash order)
   -> group-level split (sha256(seed, group) -> train / validation / test)
   -> JSONL files + manifest (config, snapshot, counts, per-file and dataset SHA-256)
```

Runtime: about 40 s on the development machine, of which the SQL reads are
most.

## 4. Example schema

```json
{
  "id": "example_7c0d3f1a9b2e4d61",
  "type": "regulatory_qa",
  "category": "section_paragraph",
  "question": "What does 21 CFR 820.10 say about design and development?",
  "context": [
    {"source_type": "ecfr", "citation": "21 CFR 820.10(c)", "text": "(c) Design and development. ...",
     "url": "https://www.ecfr.gov/...", "part": "820", "part_title": "Quality Management System Regulation",
     "subpart": "A", "section": "820.10", "paragraph": "(c)",
     "heading": "Requirements for a quality management system.", "source_key": "ecfr:820.10:(c):0"}
  ],
  "answer": "21 CFR 820.10(c) [1] (\"Design and development\") provides: Manufacturers of ...",
  "citations": ["21 CFR 820.10(c)"],
  "grounded": true,
  "provenance": {"source_keys": ["ecfr:820.10:(c):0"], "group": "ecfr:820.10",
                 "generator": "section_paragraph/v1", "snapshot_date": "2026-09-03",
                 "extra": {"subtype": "leadin"}},
  "split": "train"
}
```

* `type` is `regulatory_qa` (grounded, cites context) or `abstention`
  (`grounded: false`, `citations: []`, refusal answer).
* `source_type` is `ecfr`, `fda_guidance` or `ecfr_hierarchy` (a structural
  statement of the Title 21 hierarchy for relationship questions).
* Guidance context carries `document_title`, `docket_number`, `status`,
  `issued_on`, `center`, `url`. Citations use the same labels as the Stage 5
  retriever (`build_ecfr_citation` / `build_guidance_citation`), so a
  fine-tuned model and the RAG pipeline agree on citation strings.
* Answers refer to context items as `[1]`, `[2]` in context order, matching
  the Stage 6 RAG prompt. `regulus.training.to_messages(example)` renders
  the example with the Stage 6 system prompt and SOURCE blocks as
  system / user / assistant turns for a chat-format trainer.
* `source_key` is the same natural key the retriever uses
  (`ecfr:<section>:<paragraph>:<path_ordinal>`, `fda_guidance:<url>#<ordinal>`);
  no database ids, credentials or vectors appear anywhere.

## 5. Categories and construction rules

| Category | Subtypes (count) | Question built from | Answer built from |
|---|---|---|---|
| `direct_cfr` (2,494) | part (118), section (2,376) | part number + title; section number + heading | part title, subchapter, and the scope section text; the section's leading paragraphs (whole records only, <= 1,200 chars, never ending on a list introduction) |
| `section_paragraph` (2,000) | leadin (1,000), plain (1,000) | the paragraph's own caption ("Design and development") or the section heading | the paragraph text |
| `definition` (977) | definition | `cfr_definitions.term` | the paragraph, only when it literally reads "<term> means / has the meaning / includes / is / refers to ..." |
| `relationship` (1,000) | subpart_sections, section_location, section_paragraphs, cross_reference (250 each) | `cfr_subparts`, `cfr_sections`, paragraph captions, `cfr_cross_references` | hierarchy statement; list of paragraph captions; the resolved target section |
| `fda_guidance` (977) | scope (320), recommendation (657) | document title | the "This guidance provides/describes/..." sentence or an "FDA recommends ..." sentence, quoted, plus a fixed non-binding statement |
| `cfr_vs_guidance` (500) | ecfr_only, guidance_only, pair (~167 each) | first sentence of the passage, or the pair of sources | source identification with binding / non-binding status |
| `citation` (497) | heading (250), definition (247) | a section heading unique in Title 21 (or within its part); a term unique within its part | the section citation + text; the defining paragraph |
| `multi_context` (500) | cross_reference (250), guidance_section (250) | referencing paragraph + referenced paragraph; anchor section + guidance chunk that cites it | both texts, in order, each with its marker |
| `abstention` (500) | fake_section, fake_part, fake_docket, invalid_paragraph, unrecorded_date, future_revision, insufficient_evidence (71-72 each) | identifiers proven absent; attributes the data does not hold; a context about another topic | refusal; when a distractor context is supplied, the answer names it and explains why it does not answer |

Answer style: "21 CFR 820.10(c) [1] provides: ..." with the verbatim
paragraph, or a one-sentence template around a quoted sentence. No
conversational filler. Guidance answers always state that guidance is
non-binding.

Quality filters (all deterministic, `text.py`): paragraphs must be 60 to
1,500 characters, end a sentence, contain no `[Reserved]` stub, table
remnants or list-introduction ending; guidance sentences must be whole
sentences (chunk-boundary fragments rejected), 40 to 500 characters, with
no URL, dot leaders or PDF footnote artefacts (`drugs2`); question-style
headings are never used as topics; definitions require the term to lead
the text. Anything failing a filter is skipped, not repaired.

Diversity caps: 2 paragraph examples per section, 12 definitions per
section, 3 guidance examples per document, 1 cross-reference pair per
section; category caps are filled round-robin over subtypes in hash order,
so no part or document dominates.

## 6. Negative examples

| Subtype | Identifier construction | Guarantee |
|---|---|---|
| fake_section | `<real part>.999` (or .998, .997, .9999, .777) | absent from `cfr_sections` (all 7,906 numbers, reserved included) |
| fake_part | numbers 1-1499 absent from `cfr_parts` and outside its reserved ranges (`83-98`, ...) | absent from `cfr_parts`; never a reserved number |
| fake_docket | `FDA-<2008..2025>-D-<90000..99998>` from a hash | absent from every `fda_guidance.docket_number`, retrievable or not |
| invalid_paragraph | `<real section>(z)` when no `(z...)` paragraph exists | the section's real top-level paragraphs are the context |
| unrecorded_date | "When was <section> last amended?" | `last_amended_date` is never populated in this database |
| future_revision | "after its 2030..2035 revision" | the snapshot is dated 2026-09-03 |
| insufficient_evidence | question about section A's heading, context from an unrelated part B | no topic word of A occurs in B's text or heading |

Half of the fake-section and fake-docket examples carry a real, different
source as a distractor so the model learns that related material is not
evidence for a nonexistent identifier (the Stage 9 finding). No fake
regulatory text is written anywhere. The validator re-checks every negative
identifier against the database.

## 7. De-duplication and benchmark exclusion

* Exact duplicates: sha256 of the normalised question, sorted citations and
  normalised answer. Near duplicates: within one source group, word-set
  Jaccard of question + answer >= 0.9. Result on this build: 0 exact, 14
  near duplicates removed after selection (about 190 before selection).
* Benchmark exclusion (`baseline_v1`, `retrieval_v1`, `retrieval_v2`; 107
  questions): a generated question is dropped when it normalises to a
  benchmark question, or when it names the same CFR/docket identifiers and
  has word-set Jaccard >= 0.5 with one ("What is 21 CFR Part 11 about?"
  vs "What does 21 CFR Part 11 cover?"), or, for identifier-free questions,
  Jaccard >= 0.75. Questions about *different* identifiers are never
  look-alikes ("Part 1" vs "Part 11"). 7 candidates were excluded on this
  build; 494 selected examples still share an identifier with a benchmark
  question (for example definitions from Part 11) but ask something else.
  The benchmark files were not modified.

## 8. Split strategy

Every example carries a `group`: the eCFR section it was built from
(`ecfr:820.10`), the guidance document (`guidance:<url>`), the part for
subpart listings (`ecfr_part:820`), or the negative identifier
(`neg:section:820.999`). The split is `sha256("42", group)` mapped to
[0, 1): < 0.8 train, < 0.9 validation, else test. All examples of one
section or document therefore land in one split, and re-running with the
same seed reproduces the assignment; adding groups never moves existing
ones. Multi-context and distinction pairs that combine a guidance document
with a section are grouped by the document; their eCFR paragraph may also
appear, in another example, in a different split. This is the one known
cross-split overlap and it is at the paragraph level, not the example
level (no question/answer pair recurs across splits: 0 found).

Result: train 7,566 / validation 962 / test 917 (80.1 / 10.2 / 9.7 %).

## 9. Validation (`scripts/validate_training_data.py`)

| Check | Result |
|---|---|
| Structural (JSON, required fields, unique ids, category, source type, type/grounded consistency, citations subset of context citations, `[n]` markers within context, context <= 3,600 chars) | 0 invalid |
| Provenance against the database (every `ecfr` row, guidance chunk + docket, hierarchy part/subpart/section) | verified, 0 invalid sources |
| Citations against the database | 0 invalid |
| Negative identifiers absent from the database | 0 failures |
| Leakage: identical question+answer across splits / group overlap | 0 / 0 (76 validation/test *questions* recur verbatim in train with different context and answer, all generic prompts such as "Does the provided source state a binding regulation or non-binding FDA guidance?") |
| Duplicate ids / duplicate question-answer pairs | 0 / 0 |
| Secret scan (connection strings, `password=`, API keys, JWTs, private keys, bearer/HF tokens, the configured database password) | 0 findings |

## 10. Statistics

| | |
|---|---|
| Total examples | 9,445 (target 10,000; definitions and guidance are database-limited) |
| eCFR-sourced / guidance-sourced / no context | 8,122 / 1,596 / 143 (abstention without context) |
| Unique CFR citations / sections cited | 13,128 / 4,761 |
| Unique guidance documents | 789 |
| Average question / answer / context length | 77 / 508 / 642 characters (1.86 context items) |
| Negative / abstention examples | 500 |
| Files | `training_v1.jsonl` 19.2 MB, `validation_v1.jsonl` 2.3 MB, `test_v1.jsonl` 2.4 MB |
| Dataset SHA-256 | `bee32e320fc5c5072b040efc5b5a1caf707bce09c96affd05586a0f039e77a54` |

Category shares against the targets: direct 26.4 % (25), section/paragraph
21.2 % (20), definitions 10.3 % (10), relationships 10.6 % (10), guidance
10.3 % (15, limited by clean scope/recommendation sentences), distinction
5.3 % (5), citation 5.3 % (5), multi-context 5.3 % (5), abstention 5.3 %
(5).

## 11. Reproducibility

Deterministic inputs: `configs/training.yaml` (seed 42), sorted SQL reads,
hash-ordered selection, content-hash ids, hash-based splits, sorted
output. Two consecutive runs against the same snapshot produced identical
files (same dataset SHA-256, byte-identical `training_v1.jsonl`). The only
nondeterministic value is `generated_at_utc` in `manifest_v1.json`, which
is not part of the dataset hash. The manifest records the configuration,
the database snapshot facts, source counts, per-category candidate /
de-duplicated / excluded / selected counts, per-file SHA-256 and the
combined hash. No credentials are stored (the manifest holds the database
name and read-only flags only).

## 12. Limitations

* Answers are template-wrapped verbatim text. They teach grounding,
  citation and refusal, not fluent paraphrase; a later stage may add
  human-written or reviewed paraphrases.
* Guidance coverage is sentence-level (scope and "FDA recommends"
  sentences). Guidance chunks still contain PDF extraction noise; the
  filters remove the common artefacts, not all of them.
* Generic distinction questions recur across splits with different
  contexts (by design); evaluation on the test split should therefore weigh
  context-dependent answers, not question novelty.
* The guidance share (10.3 % against a 15 % target) is limited by the
  number of clean scope / recommendation sentences the filters accept; the
  definition share (10.3 %) uses 977 of the 1,921 named definitions, the
  rest being list introductions, multi-paragraph definitions or terms that
  do not lead their paragraph.
* Reserved paragraphs, table-like paragraphs and list introductions are
  excluded, so some sections are represented only by their opening text.
* Benchmark exclusion is lexical; a benchmark question rephrased with
  different words and no identifiers could survive.

## 13. Next step (not started)

Stage 12: fine-tune Qwen3-0.6B with LoRA on `training_v1.jsonl` via
`to_messages()`, using `validation_v1.jsonl` for early stopping, and
re-run `baseline_v1` through the Stage 7 RAG pipeline to measure the
change against the saved Stage 7 / 9 / 10 results.
