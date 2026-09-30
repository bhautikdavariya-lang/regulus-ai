# Semantic Retrieval Experiment (Stage 8)

**This semantic retriever operates only on the controlled evaluation corpus.
It is an experimental retrieval leg, not the production retrieval layer.**
The database's existing 1024-dimensional vectors (provenance UNVERIFIED,
`docs/embedding_provenance.md`) were not read, compared against, or changed.
The lexical retriever (Stage 5–7) remains the default everywhere.

---

## 1. Purpose

Stages 5–7 established that lexical retrieval is exact and fast for
identifiers and heading words, but cannot bridge vocabulary: "design controls"
vs the QMSR's "design and development", "QMS / ISO 13485" vs the regulation's
wording, "sunscreen SPF labeling", and long natural-language questions that
share few words with the source. This stage asks one question, with a known
and reproducible local embedding model and without touching PostgreSQL:

> Does semantic retrieval materially improve retrieval of FDA/eCFR concepts
> that lexical retrieval misses, without creating unacceptable noise or
> weakening negative-control behaviour?

## 2. Existing lexical baseline

`retrieval_v1.jsonl`, 27 scored queries + 1 negative control, top_k 10
(Stage 7 result file `retrieval-lexical-stage7_20260915_180242_d45608c2.json`):
Recall@1 0.778, Recall@3 0.815, Recall@5 0.852, Recall@10 0.852, MRR 0.798.
Misses: 017 (Part 11 guidance), 025 (QMS / ISO 13485), 027 (design
controls), 028 (sunscreen SPF).

## 3. Embedding model

| Property | Value |
|---|---|
| Model id | `BAAI/bge-small-en-v1.5` |
| Revision (pinned) | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| Architecture | BERT, 12 layers, 33.4 M parameters, 133 MB safetensors |
| Dimension | 384 |
| Pooling | `[CLS]` token |
| Normalisation | L2-normalised in `TransformersEmbedder.embed_batch`; asserted on load |
| Similarity | cosine (dot product on unit vectors) |
| Max input | 512 tokens (truncation) |
| Query prefix | `Represent this sentence for searching relevant passages: ` (queries only, as the model card recommends for short queries) |
| Licence | MIT |
| Runtime | `transformers` 5.17.0 + `torch` 2.14.0 CPU, already installed; **no new dependency** |
| Memory | ~150 MB resident for the model; 2,676 × 384 float32 vectors = 4 MB |
| Cache | `models/models--BAAI--bge-small-en-v1.5` (same project cache as Qwen) |

Rationale: small enough to load in seconds and embed on this CPU, openly
licensed, pinned by commit hash, documented pooling and normalisation, and
loadable with the dependencies already in `requirements.txt`. It was chosen
for reproducibility on this machine, not for leaderboard position.

## 4. Experiment corpus

Configuration: `data/evaluation/semantic/manifest.yaml` (tracked).
Artifacts: `data/evaluation/semantic/generated/` (gitignored, reproducible).

| | Value |
|---|---|
| Items | 2,676 |
| eCFR paragraphs | 1,406 from 44 whole sections |
| Guidance chunks | 1,270 from 32 documents (23 dockets, first 60 chunks each) |
| Roles | 1,873 target, 803 distractor |
| Corpus SHA-256 | `741bc0cbcc899c2cbcc275dd1083ce0223d5eccdf727754385ab9c3d45bcc645` |
| Manifest SHA-256 | `d209d3021e1f…` |
| Missing sections / dockets | none |

Selection method: the manifest lists every eCFR section and guidance docket
by hand with a role. Targets are the `retrieval_v1` and `baseline_v1`
answers and their neighbours (all of Part 820 QMSR, Part 11, 211.132 /
211.68 / 211.142 / 211.100, 50.20 / 50.25, 56.103, 807.81 / 807.87, 803.50,
7.40, 201.327, 801.109, 314.50 / 314.3, 312.20, 201.66, 330.1, 111.1, and
the Part 11, process validation, human factors, cybersecurity QMS, 510(k),
recalls, data integrity, CSA, combination-product CGMP, quality-systems,
informed-consent, user-fee and supplement AER guidances). Distractors are
real, unrelated text: 352.52 (the SPF competitor lexical search returns),
food labeling 101.9 / 101.4 / 170.3, tobacco warnings 1141.10, blood SOPs
606.100, 100.1, the trigram-junk sections 21.30 / 111.360 / 1.360, and the
guidances lexical fallback surfaced for the wrong reasons (small-business
employee counting, ANDA amendments, glove detention, mobile apps, heparin,
recalls-vs-enhancements, home-use design considerations).

`scripts/build_semantic_corpus.py` reads them with two parameterised
SELECTs on the read-only connection and writes `corpus.jsonl` (id = the same
natural key the lexical retriever uses, corpus, text, content SHA-256, role,
citation metadata) plus `corpus_meta.json`. No synthetic text.

Limitation: 2,676 of 134,010 passages (2 %). Every benchmark target is
present by construction, so recall here measures ranking ability among a
curated set, not full-database coverage. Scores on the full corpus would be
lower and noisier.

## 5. Architecture

```
PostgreSQL (read-only)
    ↓  scripts/build_semantic_corpus.py   (manifest-driven, parameterised SQL)
data/evaluation/semantic/generated/corpus.jsonl  (+ corpus_meta.json, SHA-256)
    ↓  scripts/build_semantic_index.py    (TransformersEmbedder, batch 16, CPU)
vectors.npy [2676 × 384 float32] + index_meta.json
    ↓  SemanticIndex.load()  refuses a corpus-hash or embedding-config mismatch
SemanticRetriever.run(query)  →  embed query → cosine top-k → RetrievalResult[]
    ↓
scripts/evaluate_retrieval.py --retriever semantic   /   scripts/search.py --retriever semantic
```

Code: `src/regulus/retrieval/semantic/` (`models.py`, `embedder.py`,
`index.py`, `retriever.py`). Results reuse the lexical result builders, so
citations, keys and metadata are identical in shape; `retrieval_method` is
`semantic`, `relevance_score` is the cosine similarity (0–1) and is **not**
merged with lexical scores. `index_meta.json` records model, revision,
dimension, pooling, normalisation, query prefix, an embedding-config
fingerprint, corpus hash, size, timestamp, code version and build time.

## 6. Retrieval results (`retrieval_v1.jsonl`, top_k 10)

| Metric | Stage 7 lexical | Stage 8 semantic |
|---|---|---|
| Recall@1 | 0.778 | 0.370 |
| Recall@3 | 0.815 | 0.667 |
| Recall@5 | 0.852 | 0.667 |
| Recall@10 | 0.852 | 0.704 |
| MRR | 0.798 | 0.512 |
| Negative control | passed | passed (no exact method exists) |
| Queries / failures | 28 / 0 | 28 / 0 |
| Zero-result queries | 0 | 0 (semantic always returns top-k) |
| Candidates searched per query | database | 2,676 |
| Avg total retrieval latency | 208 ms | 23 ms (embed ≈ 21 ms, search ≈ 3 ms) |

By category (Recall@1 / Recall@10):

| Category | Lexical | Semantic |
|---|---|---|
| exact_cfr (3) | 1.00 / 1.00 | 0.00 / 0.00 |
| cfr_section (2) | 1.00 / 1.00 | 0.00 / 0.50 |
| cfr_paragraph (2) | 1.00 / 1.00 | 0.00 / 0.00 |
| regulatory_concept (8) | 0.75 / 1.00 | 0.50 / 0.875 |
| fda_guidance (5) | 0.80 / 0.80 | 0.20 / 1.00 |
| cross_corpus (2) | 1.00 / 1.00 | 1.00 / 1.00 |
| terminology_variation (2) | 0.50 / 0.50 | 0.50 / 1.00 |
| difficult_lexical (3) | 0.33 / 0.33 | 0.67 / 0.67 |

Semantic misses: 001, 002, 003, 005, 006, 007 (all identifier queries: an
embedding of "21 CFR 820.10" is not close to the section's paragraphs), 013
(returns 820.1(a) "scope", a neighbour of the 820.10 target), 027 (design
controls). Semantic recovered three of the four lexical misses: 017 (Part 11
guidance, rank 2), 025 (QMS / ISO 13485, rank 2), 028 (sunscreen SPF, rank 1).

Result file: `retrieval-semantic-stage8_20260916_093936_1472cdd0.json`.

## 7. Vocabulary-mismatch analysis

| Query | Expected | Lexical top | Semantic top | Target rank (semantic) | Relevant? |
|---|---|---|---|---|---|
| design controls | 21 CFR 820.10(c) | combination-product CGMP guidance chunks (full_text 26.7) | same guidance, chunk on design-control activities (0.795), then home-use design considerations (distractor, 0.726) | not in top 10 | The top chunks genuinely discuss design controls for combination products and are useful regulatory text; the eCFR target 820.10(c) ("Design and development") is not reached because the QMSR paragraph is a one-line cross-reference to ISO 13485 clause 7.3 with little lexical or semantic surface. |
| QMS documentation requirement ISO 13485 | 21 CFR 820.10 | a premarket QMS guidance (2.08) then trigram junk (251.17) | cybersecurity QMS guidance (0.752), **21 CFR 820.10(a)** (0.752) | 2 | Yes: 820.10(a) is exactly the requirement to document a QMS complying with ISO 13485. |
| sunscreen SPF labeling | 21 CFR 201.327 | 352.52(a) via trigram (2.44) | **21 CFR 201.327(a)(1)(ii)** (0.835), then 201.327(c)(2), (h) | 1 | Yes: 201.327 is the sunscreen labeling rule; the distractor 352.52 drops to rank 4. |
| Part 11 electronic records electronic signatures scope and application guidance | FDA-2003-D-0143 | exact Part 11 sections (eCFR) | CSA guidance (0.810), **Part 11 guidance** (0.804) | 2 | Yes; the Part 11 guidance fills ranks 2, 4, 5. |

Two of the three named problem areas are solved by the embedding model on
this corpus; the third ("design controls") retrieves relevant guidance but
not the regulation paragraph, for a reason that is a property of the QMSR
text rather than of either retriever.

## 8. Long-question analysis (the questions the Stage 7 OR fallback changed)

| Question | AND lexical | OR fallback (Stage 7) | Semantic |
|---|---|---|---|
| prescription drug vs dietary supplement | nothing | supplement AER Q&A chunks (relevant, rank 1) | **21 CFR 111.1(a)(1)** (supplement CGMP scope, rank 1), 314.3(b) drug definitions, 101.36 |
| why a new drug must be approved | nothing | ANDA amendments / animal-feed guidance (loosely related) | 211.132(e) (off), **314.50(j)** NDA content (rank 2), 201.66, PDUFA guidance |
| statute vs regulation | nothing | U.S.-agent registration guidance (unrelated) | 201.66(b)(1), 314.3(b), 100.1 — no passage in either corpus defines the distinction; semantic returns plausible-looking but unrelated text at 0.70 |
| OTC pain reliever considerations | nothing | small-business employee-count guidance (wrong) | 314.50(a)(3), ANDA guidance, **330.1** OTC monograph conditions (rank 3), 211.132(e) |
| good manufacturing practice | nothing | CGMP Q&A, Phase 1 CGMP (relevant, rank 1) | quality-systems CGMP guidance (rank 1), process validation, CGMP Q&A, 820.1(a) |

Semantic retrieval finds a better source than the OR fallback for three of
the five (supplement, approval, OTC), matches it for GMP, and is equally
unhelpful for the statute question, where it also cannot signal that nothing
relevant exists. It never returns an empty list.

## 9. Negative-control analysis

| Question | Lexical (Stage 7) | Semantic top result | Similarity |
|---|---|---|---|
| 21 CFR 314.999 (fake section) | trigram junk, note "no live record" | small-business guidance (distractor), then 314.50(i) | 0.672 |
| exact temperature range in Part 211 (unknowable) | exact Part 211 rows | combination-product CGMP chunks | 0.701 |
| NDA user fee FY2031 (unknowable) | user-fee guidances (fallback) | PDUFA user-fee guidance chunks ×5 | 0.729 |
| FDA-2023-D-99999 (fake docket) | **nothing** | human-factors, container-closure, 510(k) third-party guidances | **0.797** |
| Part 1400 and AI labeling (fake part) | labeling guidances (fallback), note "no live record" | human-factors guidance, 330.1(b) | 0.703 |
| 820.30(b)(1) (retrieval negative control) | no exact hit, passed | combination-product CGMP chunk | — |

Observed: semantic retrieval always returns "related but non-authoritative
results". The similarities for fabricated queries (0.67–0.80) overlap the
range of genuine hits (0.69–0.84: 201.327 at 0.835, 820.10(a) at 0.752, GMP
guidance at 0.687), so **cosine similarity alone cannot be used as an
existence test**. The fake-docket query is the worst case: 0.797 for an
unrelated guidance, because the query's own words ("guidance document",
"recommendations") dominate the embedding. The lexical layer's identifier
parsing and "no live record" notes remain the only signal that a cited
regulation does not exist; any later hybrid design must keep them. No
special-case handling was added.

In the three-question semantic RAG smoke test (opt-in
`scripts/rag.py --retriever semantic`, same Qwen, same prompt and
parameters), the Part 1400 question was still refused by the model with
three semantic sources in context; "design controls" produced a correct,
cited answer from the combination-product guidance; the GMP question
produced a correct cited answer. No full semantic RAG benchmark was run: the
retrieval numbers above show it would not be comparable to the lexical RAG
runs (identifier questions would all lose their exact sources).

## 10. Performance (CPU-only i5-4590, 8 GB RAM)

| Step | Measured |
|---|---|
| Model download | 133 MB, once |
| Model load | 15.5 s cold, 0.5–0.6 s warm (OS file cache) |
| Corpus embedding | 302 s for 2,676 items = 113 ms/item (batch 16; 206 ms/text for the first warm-up batch); guidance chunks (~350 tokens) dominate |
| Query embedding | 19–29 ms |
| Cosine search over 2,676 | 2.5–4.5 ms |
| Total semantic retrieval per query | 23 ms average, 29 ms max |
| Memory | ~150 MB model + 4 MB vectors; no pressure observed |
| Extrapolation | embedding all 134,010 passages at 113 ms each ≈ 4.2 h on this CPU; index ≈ 200 MB float32 |

## 11. Limitations

- Controlled corpus of 2 % of the database; targets are guaranteed present.
- No identifier handling: pure semantic retrieval fails every "21 CFR
  820.10"-style query and cannot see that a section is reserved or absent.
- Always returns top-k; similarities do not separate real from fabricated.
- 60-chunk cap per guidance document; long documents are partially covered.
- bge-small truncates at 512 tokens; chunk starts mid-sentence (Stage 5
  finding) also affect embeddings.
- Manual relevance judgments in §7–9 are the assistant's, not a domain expert's.
- Scores are cosine similarities and were not merged with lexical scores; no
  fusion, reranking or threshold was designed.

## 12. Recommendation

**A — semantic retrieval is promising enough to proceed to a controlled
hybrid retrieval experiment**, with two conditions drawn from the
measurements:

1. The hybrid must keep the lexical layer authoritative for identifiers,
   exact lookups and non-existence notes: semantic scored 0 on every
   identifier category and cannot detect fabricated citations.
2. Semantic evidence must be admitted as a complement (for concept and long
   questions where primary lexical retrieval is weak), with an explicit
   similarity floor tested against the negative controls, because raw
   similarities for fabricated queries overlap genuine hits.

Evidence for A: on the same benchmark semantic recovered 3 of 4 lexical
misses (sunscreen SPF rank 1, QMS/ISO 13485 rank 2, Part 11 guidance rank
2), found the correct regulation for the long supplement, approval and OTC
questions that the OR fallback answered with unrelated guidance, and costs
23 ms per query. Evidence against a naive merge: overall Recall@1 0.37 vs
0.78, and 0.80 similarity for a non-existent docket.

Nothing beyond this experiment was implemented.
