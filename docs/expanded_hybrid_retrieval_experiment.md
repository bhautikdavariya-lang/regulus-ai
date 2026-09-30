# Expanded-Corpus Hybrid Retrieval Validation (Stage 10)

Experimental. The lexical retriever (Stage 5–7) remains the default. The
database's 1024-dimensional vectors (provenance UNVERIFIED,
`docs/embedding_provenance.md`) were not read or changed; all semantic vectors
are local files produced by the pinned `BAAI/bge-small-en-v1.5`.

Code: no new retrieval logic. Stage 10 adds versioned semantic corpora
(`regulus.retrieval.semantic.models.resolve_paths`, manifest schema v2),
integrity checks (`validate_items`), precision / existence / crowding metrics
in `regulus.evaluation.retrieval_eval`, `scripts/compare_retrieval_runs.py`,
the `retrieval_v2.jsonl` benchmark, and `--semantic-corpus` on the scripts.
Tests: `tests/test_semantic_expanded.py`.

---

## 1. Objective

Stage 9 found hybrid retrieval promising but measured it on a corpus where
every benchmark target was guaranteed present. Stage 10 asks whether those
gains survive realistic semantic competition, and whether identifier
authority and negative-identifier safety still hold, before hybrid becomes a
direction.

## 2. Stage 9 limitation

The Stage 8/9 corpus held 2,676 passages (1,873 targets, 803 distractors):
2 % of the database, with a target/distractor ratio of 2.3. Semantic
candidates therefore competed only with hand-picked neighbours.

## 3. Expanded corpus (`semantic_expanded_v1`)

Manifest: `data/evaluation/semantic/semantic_expanded_v1/manifest.yaml`
(tracked, schema v2: scope + explicit targets). Artifacts in
`…/semantic_expanded_v1/generated/` (gitignored, reproducible). The Stage 8
corpus and index are untouched (`--check` confirms 2,676 vectors).

| | Value |
|---|---|
| Items | **26,083** (9.7× Stage 8; 19 % of the database) |
| eCFR paragraphs | 17,281 from 1,781 sections in 81 parts |
| Guidance chunks | 8,802 from 745 documents (12 chunks each) |
| Targets / distractors | 1,136 / 24,947 (ratio **0.046**) |
| Corpus SHA-256 | `c4776e997e88b8a5ef4bfd34b8daafffa8d93f65d08fd488392292a044acbde0` |
| Manifest SHA-256 | `5b1e8ccfa3d7…` |
| Embedding | bge-small-en-v1.5 @ `5c38ec7c…`, 384-d, CLS, L2, cosine |
| Built | 2026-09-16, 2,673 s (102.5 ms/item), 40 MB float32, all finite, norms 1.0000 |

Selection (manifest): whole subchapters C (drugs: general) and D (drugs for
human use); whole parts 1, 7, 10, 11, 20, 50, 56, 58, 801, 803, 806, 807,
808, 810, 812, 814, 820, 821, 822, 830, plus classification parts 870 and
880 as high-volume distractors; eight individual sections outside that scope
that Stage 8 used; every retrievable drug- and device-sector guidance
document plus five dockets from other sectors that the benchmarks reference.
Everything not in the explicit target list is a distractor. The build fails
on duplicate keys, empty text, missing citation identifiers or a target
absent from the snapshot (none occurred).

## 4. Architecture

```
                         Query
                           │
              ┌────────────┴────────────┐
              ↓                         ↓
          PostgreSQL                Local semantic index
          lexical (Stage 7)         semantic_expanded_v1 (26,083 × 384)
              │                         │
        lexical candidates        semantic candidates (top-10, floor)
              │                         │
              └────────────┬────────────┘
                           ↓
        authority rules (exact pinned; unresolved identifier ⇒ contextual_only + note)
                           ↓
                  de-duplicate by natural key
                           ↓
                RRF fusion (k = 60) of the remaining candidates
                           ↓
                        top-K
                           ↓
        RagPipeline (exclude_contextual_only) ─► Qwen3-0.6B (unchanged)
```

## 5. Retrieval results (`retrieval_v2.jsonl`: 52 queries, 37 scored, 15 negative controls, top_k 10)

`retrieval_v1.jsonl` is unchanged; v2 keeps all 28 v1 queries with their
text and adds 24: two vocabulary-mismatch, five long natural-language
(the baseline reasoning questions), two conceptual, two guidance, and 13
negative controls (3 fake sections, 2 fake parts, 3 fake dockets, 3
real-looking invalid references, 3 unknowable). Every identifier-style
negative carries `identifier_exists_in_snapshot`, verified against the
database when written and re-checked against the lexical exact lookup at
run time (`existence_mismatches`).

| | Lexical (S7) | Semantic, Stage 8 corpus | Semantic, expanded | Hybrid C, Stage 8 corpus | **Hybrid C, expanded** | Hybrid C + floor 0.75, expanded | Hybrid B, expanded |
|---|---|---|---|---|---|---|---|
| Recall@1 | 0.703 | 0.432 | 0.378 | 0.757 | 0.676 | **0.703** | 0.568 |
| Recall@3 | 0.730 | 0.730 | 0.541 | 0.838 | 0.757 | **0.757** | 0.757 |
| Recall@5 | 0.757 | 0.757 | 0.541 | 0.892 | 0.757 | 0.757 | 0.757 |
| Recall@10 | 0.757 | 0.784 | 0.622 | 0.946 | 0.811 | **0.811** | 0.838 |
| MRR | 0.717 | 0.578 | 0.455 | 0.805 | 0.723 | **0.737** | 0.673 |
| Precision@1 | 0.703 | 0.432 | 0.378 | 0.757 | 0.676 | 0.703 | 0.568 |
| Precision@3 | 0.604 | 0.441 | 0.324 | 0.640 | 0.604 | 0.604 | 0.504 |
| Precision@5 | 0.497 | 0.405 | 0.281 | 0.611 | 0.524 | **0.535** | 0.460 |
| Negative controls | 15/15 | 15/15 | 14/15 | 14/15 | 15/15 | 15/15 | 15/15 |
| Misses | 9 | 8 | 14 | 2 | 7 | 7 | 6 |

Precision here is *target-match precision*: the share of the top-k results
that match any expected target (every paragraph of a target section counts).
It is not a graded relevance judgment; unlisted-but-relevant passages count as
non-matches, so absolute values understate true precision equally for all
runs.

Category breakdown, Recall@1 / Recall@10 / Precision@5:

| Category (n) | Lexical | Semantic expanded | Hybrid C expanded | Hybrid C + 0.75 | Hybrid B expanded |
|---|---|---|---|---|---|
| identifier (4) | 1.00/1.00/0.90 | 0.00/0.00/0.00 | 1.00/1.00/0.90 | 1.00/1.00/0.90 | **0.50**/1.00/0.55 |
| section_paragraph (4) | 1.00/1.00/0.75 | 0.00/0.25/0.10 | 1.00/1.00/0.75 | 1.00/1.00/0.75 | **0.50**/1.00/0.50 |
| cross_corpus (2) | 1.00/1.00/0.70 | 0.50/1.00/0.60 | 1.00/1.00/0.70 | 1.00/1.00/0.70 | 1.00/1.00/0.70 |
| conceptual (10) | 0.60/0.80/0.50 | 0.30/0.60/0.26 | 0.50/0.80/0.42 | 0.50/0.80/0.42 | 0.50/0.80/0.42 |
| vocabulary_mismatch (7) | 0.43/0.43/0.23 | 0.71/0.86/0.29 | 0.71/0.71/0.31 | **0.71/0.71/0.37** | 0.71/0.71/0.31 |
| long_natural_language (4) | 0.50/0.50/0.20 | 0.00/0.50/0.05 | 0.00/0.50/0.20 | 0.25/0.50/0.20 | 0.00/0.50/0.20 |
| fda_guidance (6) | 0.83/0.83/0.50 | 0.83/1.00/0.67 | 0.83/0.83/0.70 | 0.83/0.83/0.70 | 0.83/1.00/0.70 |
| negatives (15) | 15/15 | 14/15 | 15/15 | 15/15 | 15/15 |

Result files: `retrieval-v2-lexical_*`, `retrieval-v2-semantic-stage8corpus_*`,
`retrieval-v2-semantic-expanded_*`, `retrieval-v2-hybridC-stage8corpus_*`,
`retrieval-v2-hybridC-expanded_*`, `…-floor0_70_*`, `…-floor0_75_*`,
`retrieval-v2-hybridB-expanded_*`, `…-floor0_70_*` (all 2026-09-16).

## 6. Crowding analysis

Expansion (×9.7 items, target share 4.6 % instead of 70 %) changed semantic
and hybrid behaviour in three measurable ways.

1. **Semantic-only collapses.** Same benchmark, same model: Recall@10 0.784 →
   0.622, MRR 0.578 → 0.455; conceptual Recall@1 0.50 → 0.30; the long
   questions 0.50 → 0.00 at rank 1. Real neighbours outrank the targets.
2. **The hybrid gain shrinks by more than half.** Hybrid C versus lexical on
   v2: MRR +0.088 with the Stage 8 corpus, +0.006 (no floor) or +0.020
   (floor 0.75) with the expanded corpus; Recall@10 +0.189 → +0.054;
   Recall@5 +0.135 → 0.000.
3. **New regressions appear where semantic neighbours crowd the eCFR target.**
   - 011 "when is IRB review required": 56.102(g) (IRB definitions, semantic)
     outranks the lexical 56.103(c) hit: rank 1 → 2.
   - 015 "manufacturer medical device reporting requirements": 803.1(a),
     803.30, 803.20 and an MDR guidance chunk (all semantic, all
     distractors) push 803.50 from rank 3 → 7.
   - 013 "QMS requirements for device manufacturers": stays at rank 9
     (Stage 9 regression persists; semantic ranks 820.1(a) scope above 820.10).
   - 031 supplement question: 202.1(e) advertising text outranks 111.1(a)(1):
     rank 1 → 2 (floor 0.75 restores rank 1 by removing all semantic items).
   - 034 GMP question: 212.2 (PET-drug CGMP scope) takes rank 1 from the CGMP
     Q&A: rank 1 → 2.
   On the 30 hybrid-C (floor 0.75) hits, 26 are at rank 1, 4 have distractors
   above the target (0.23 on average), and the top 10 averages 5.8 eCFR /
   3.9 guidance / 3.4 semantic-sourced items.
4. **Where expansion helped:** 025 QMS/ISO 13485 rises to rank 1 (820.10(a)
   now scores above the QMS-guidance chunks that crowded it in Stage 9),
   028 sunscreen to rank 1, and 017 (Part 11 guidance) becomes reachable
   under B (rank 6).
5. **Strategy B fails at scale on identifiers**: 4 of 8 identifier queries
   drop to rank 2 because a semantic neighbour ties or beats the exact row
   under pure RRF. Authority pinning (C) keeps all eight at rank 1.
6. **The similarity floor now matters.** Expanded-corpus similarities are
   higher and denser: hits median 0.800 (0.72–0.89), misses median 0.792
   (0.67–0.88), negatives median 0.721 (0.69–0.81). A 0.75 floor removed 277
   of 520 semantic candidates, lifted Recall@1 to lexical parity and MRR to
   0.737 with no recall loss, but it cannot separate hits from misses (their
   distributions overlap almost completely).

## 7. Negative controls (hybrid C, floor 0.75, expanded)

| Query | Type | Exists | Lexical exact | Semantic top | Hybrid mode | Contextual-only in top-10 | Passed |
|---|---|---|---|---|---|---|---|
| 21 CFR 314.999 | fake section | no | none | 0.715 | lexical | 0 | yes |
| 21 CFR 820.999 design validation | fake section | no | none | 0.801 | hybrid | 3 | yes |
| 21 CFR 11.75 audit trails | fake section | no | none | 0.699 | lexical | 0 | yes |
| 21 CFR Part 1400 / AI labeling | fake part | no | none | 0.736 | lexical | 0 | yes |
| 21 CFR Part 999 cybersecurity | fake part | no | none | 0.688 | lexical | 0 | yes |
| FDA-2023-D-99999 | fake docket | no | none | 0.804 | semantic | 10 | yes |
| FDA-2020-D-77777 | fake docket | no | none | 0.811 | hybrid | 5 | yes |
| FDA-2016-D-0001 | fake docket | no | none | 0.721 | lexical | 0 | yes |
| 21 CFR 820.30(b)(1) | invalid (reserved) | no | none | 0.705 | lexical | 0 | yes |
| 21 CFR 820.50 purchasing controls | invalid (pre-QMSR) | no | none | 0.700 | lexical | 0 | yes |
| 21 CFR 201.327(z) | invalid paragraph | no | none | 0.763 | hybrid | 1 | yes |
| NDA fee FY2031 | unknowable | — | none | 0.741 | lexical | 0 | yes |
| Part 820 after the 2030 revision | unknowable | **yes** | exact | 0.703 | exact | 0 | yes |
| Warning letters in 2035 | unknowable | — | none | 0.702 | lexical | 0 | yes |
| statute vs regulation | long, no target | — | none | 0.742 | lexical | 0 | yes |

Every identifier-style negative was resolved as absent by the lexical layer
(`identifier_not_found = True`), no exact result was fabricated, and every
semantic candidate that survived the floor was marked `contextual_only`. The
question the stage asked, whether expansion produces *more* plausible
material for nonexistent identifiers, has a quantified answer: with the
Stage 8 corpus the fake-docket query had 10 contextual items at up to 0.797;
with the expanded corpus it still has 10 at 0.804, and the two fake-docket
queries now reach 0.81, the highest semantic scores among the negatives.
Expansion did not reduce this; the floor removes some of it (0 of 10
candidates for 314.999 and Part 1400) but not the docket cases.

**Answer layer.** In the RAG run the five `baseline_v1` fictitious questions
kept their Stage 7/9 behaviour: the fake docket returned the deterministic
refusal without calling the model (`contextual_only` exclusion), and the fake
section, fake part, storage-range and fee questions were refused by the model.
The broader regression test now covers 13 identifier negatives in
`retrieval_v2` at the retrieval layer; only the five in `baseline_v1` were
run through Qwen.

## 8. Hard cases (lexical → hybrid C, floor 0.75, expanded)

| Case | Result |
|---|---|
| QMS / ISO 13485 (820.10) | miss → **rank 1** (better than Stage 9's rank 5). Real competition did not push it down; 820.10(a) scored 0.752 against premarket-QMS guidance at 0.746. |
| Design controls (820.10(c)) | miss → miss in every run. Related guidance (combination-product CGMP, Q8 pharmaceutical development) is retrieved; the eCFR target never is. Not counted as found. |
| Sunscreen SPF (201.327) | miss → **rank 1** (Stage 9: rank 2); 352.50/352.3 distractors follow at 0.80. |
| UDI traceability under QMSR (820.10(b) / 830.20), new | miss → miss; semantic returns device-tracking 821.30 and 830.60 (distractors) and the OR fallback returns UDI guidance. |
| Supplement question | rank 1 → 1 (floor removes the 202.1 distractor that took rank 1 without a floor) |
| Drug approval question | miss → miss (semantic 211.132(e) and 312.315 expanded-access text outrank 314.50(j); Stage 9 had rank 3 on the small corpus) |
| OTC question | miss → miss (small-business guidance from the OR fallback; semantic OTC labeling guidances, all distractors) |
| GMP question | rank 1 → 2 (212.2 PET-drug CGMP scope, semantic, takes rank 1) |
| Statute vs regulation | nothing relevant in any run; passes as a non-identifier negative |

Net on the long questions: the Stage 9 improvements on the drug-approval and
OTC questions disappeared with realistic competition; the supplement and GMP
questions keep their lexical answers.

## 9. RAG results (`baseline_v1`, 27 questions, Qwen3-0.6B greedy 128 tokens, seed 42, prompt unchanged)

Stage 10 pipeline: hybrid C, floor 0.75, expanded corpus, `exclude_contextual_only`.
Result file `rag-stage10-hybrid-expanded_20260916_114615_82e834e6.json`.

### Objective measurements

| | Stage 7 (lexical + fallback) | Stage 9 (hybrid, Stage 8 corpus) | Stage 10 (hybrid, expanded) |
|---|---|---|---|
| Completed / failed | 27 / 0 | 27 / 0 | 27 / 0 |
| Model calls / no-context answers | 26 / 1 | 26 / 1 | 26 / 1 |
| Avg latency per question | 32.2 s | 38.4 s | 33.5 s |
| Generation (median / mean) | — | 36.0 s / 36.8 s | 32.7 s / 32.3 s |
| Avg retrieval latency (model resident) | 1.42 s | 1.61 s | 1.22 s (median 0.79 s, max 7.3 s cold) |
| Avg input tokens (max) | 930 | 994 (1,268) | 965 (1,268) |
| Avg output tokens | 60.4 | 68.7 | 64.0 |
| Avg context chars / sources | 3,069 / 2.8 | 3,216 / 3.4 | 3,148 / 3.4 (max 3,783) |
| Questions with a semantic source in context | 0 | 14 | 11 |
| Retrieval modes | — | exact 3, hybrid 15, lexical 8, semantic 1 | exact 3, hybrid 12, lexical 11, semantic 1 |
| Lexical / dedup candidates avg | — | — | 9.4 / 12.4 |
| Semantic accepted avg (removed total) | — | 3.6 (172) | 3.1 (187) |

### Manual reviewer scores (0–2; assistant-assigned against evaluation notes; not objective)

| | Baseline Qwen | Stage 7 | Stage 9 | Stage 10 |
|---|---|---|---|---|
| Mean, 27 | 0.89 | 1.11 | 1.15 | **1.07** |
| General knowledge (5) | 1.80 | 1.00 | 1.40 | 1.00 |
| Regulatory concepts (5) | 0.60 | 1.00 | 1.00 | 0.80 |
| FDA/eCFR-oriented (7) | 0.71 | 0.86 | 0.86 | 1.00 |
| Reasoning (5) | 1.40 | 1.00 | 0.80 | 0.80 |
| Unknown/hallucination (5) | 0.00 | 1.80 | 1.80 | 1.80 |

Twelve answers are identical to Stage 9, four to Stage 7 (the long
questions, where the floor removed every semantic candidate), eleven are
new. Improvements: the 510(k) answer now states substantial equivalence and
the 807.87 content requirements (1 → 2). Regressions: the clinical-trial
answer quotes the 312.3 definition without safety/effectiveness (2 → 1); the
medical-device answer became circular ("as defined in section 201(h)")
(2 → 1); the GMP answer is framed around PET drugs because 212.2 took rank 1
(2 → 1); regulation-vs-guidance is now grounded in 21 CFR 10.115 but appends
a refusal (2 → 1). Hallucination stayed at 1.80 with the answer-layer rule
in place.

## 10. Performance

Idle-machine re-run (v2 benchmark, 52 queries, after all other jobs had
finished; the earlier runs shared the CPU, but the numbers were within a few
percent, so the PostgreSQL round trips dominate, not CPU contention):

| Step | Median | Mean | Max |
|---|---|---|---|
| Lexical retriever alone, per query | 750 ms | 1,125 ms | 4,063 ms |
| Hybrid C (floor 0.75) per query | 821 ms | 1,065 ms | 3,453 ms |
| ├ lexical leg | 762 ms | | 3,395 ms |
| ├ semantic query embedding | 20.7 ms | | 27.9 ms |
| ├ semantic search over 26,083 vectors | 30.2 ms (Stage 8: 2.8 ms over 2,676) | | 43 ms |
| └ fusion + dedup | 0.2 ms | | 0.4 ms |
| Semantic model load | 0.7 s warm, 15 s cold | | |
| Corpus embedding (one-off) | 2,674 s for 26,083 items (102.5 ms/item) | | |
| RAG generation, Qwen | 32.7 s | 32.3 s | 72.9 s |

The semantic leg adds about 50 ms (6 %) to a query; the lexical leg's
multi-statement search (exact, full-text, trigram, OR fallback) is the cost
in every configuration.

Memory: 40 MB vectors + ~150 MB model; the 42 MB corpus file is read once.
The semantic search scales linearly (NumPy dot product): ~1 ms per 1,000
vectors, so the full database (134,010) would cost ~150 ms per query
without an approximate index.

## 11. Safety

PostgreSQL before/after Stage 10: row counts, 65,264 + 68,669 embeddings,
1024 dimensions, checksums over 500 stored vectors per table, 241 indexes,
818 columns, 322 relations, 76 tables, write counter 293,083 — all
unchanged. No external embedding API (the only encoder is the local pinned
bge-small). Qwen, generation settings and the RAG prompt unchanged. The
Stage 7 lexical retriever reproduces its Stage 7 results on the 28 v1
queries embedded in v2; the Stage 8 index (2,676 vectors) and the Stage 9
hybrid defaults are unchanged (`test_stage8_and_stage9_defaults_are_unchanged`),
and `--semantic-corpus` defaults to the Stage 8 corpus everywhere. Contextual-only protection
was exercised by 13 identifier negatives at the retrieval layer and by the
five `baseline_v1` fictitious questions through the RAG layer.

## 12. Limitations

- CPU-only, 8 GB RAM; embedding 19 % of the database took 45 minutes, so the
  full database was not embedded and semantic coverage remains partial
  (subchapters B, E, F, G, I–L largely absent).
- bge-small-en-v1.5 similarity does not separate hits from misses (§6.6); a
  floor trades recall for precision but is not a relevance detector.
- Target-match precision counts only listed targets; the benchmark has one
  to three targets per query, so precision values are conservative.
- Reviewer scores are assistant-assigned on 27 questions; differences of
  ±0.05 are within their noise.
- The historical 1024-d embedding provenance is still unresolved and unused.
- 12-chunk cap per guidance document; classification parts other than 870
  and 880 excluded.

## 13. Recommendation

**C — hybrid retrieval is not sufficiently beneficial at realistic scale;
retain lexical retrieval as the primary direction.**

Measured basis: with the expanded corpus, the best hybrid configuration
(C, floor 0.75) matches lexical Recall@1 (0.703 = 0.703), adds +0.027
Recall@3, +0.054 Recall@10, +0.020 MRR and +0.038 Precision@5, and keeps
all 15 negative controls; but it also introduces new crowding regressions
(011, 015, 034), loses the Stage 9 long-question gains, and its RAG reviewer
mean falls below Stage 7 (1.07 vs 1.11) with two definitional answers
degraded. The one durable benefit is the vocabulary-mismatch category
(Recall@1 0.43 → 0.71: QMS/ISO 13485 and sunscreen SPF), which is real but
narrow, and pure RRF (B) proved unsafe for identifiers at scale (Recall@1
0.57).

What would change this verdict: a stronger or domain-adapted embedding model
whose similarities separate hits from misses, a semantic leg restricted to
queries the lexical layer classifies as conceptual (never identifiers), and
a benchmark with graded relevance so precision can be measured properly.
Those are separate decisions for the next stage review; nothing beyond this
experiment was implemented.
