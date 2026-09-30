# Hybrid Retrieval Experiment (Stage 9)

Experimental. The lexical retriever (Stage 5–7) remains the default. The
semantic leg is the Stage 8 controlled corpus (2,676 passages, 2 % of the
database); every hybrid number below inherits that limitation. The database's
existing 1024-dimensional vectors were not read or changed.

Code: `src/regulus/retrieval/hybrid.py` (`HybridConfig`, `HybridRetriever`),
`src/regulus/retrieval/semantic/loaders.py`. Opt-in everywhere with
`--retriever hybrid [--hybrid-strategy fallback|rrf|authority]
[--semantic-floor F] [--rrf-k K] [--lexical-top-n N] [--semantic-top-n N]`
on `scripts/evaluate_retrieval.py`, `scripts/search.py`, `scripts/rag.py`
and `scripts/evaluate_baseline.py --pipeline rag`. Tests: `tests/test_hybrid.py`.

---

## 1. Why hybrid retrieval was tested

Stage 7 lexical retrieval is exact for identifiers and heading words and
knows when a cited section or part does not exist, but misses vocabulary
mismatches (QMS / ISO 13485, sunscreen SPF, the Part 11 guidance) and answers
long questions only through a coarse OR fallback. Stage 8 semantic retrieval
recovered three of those four misses and found better sources for the long
questions, but scored zero on every identifier query and returned confident
material for fabricated identifiers. The two legs fail on disjoint cases, so
the question is whether a controlled fusion keeps each leg's strength.

## 2. Architecture

```
                         Query
                           │
          ┌────────────────┴────────────────┐
          ↓                                 ↓
 LexicalRetriever (Stage 7)        SemanticRetriever (Stage 8)
 exact / AND / OR-fallback / trigram   bge-small-en-v1.5, NumPy cosine
          │  top-N (10)                     │  top-N (10), similarity floor
          └────────────────┬────────────────┘
                           ↓
        Authority rules: exact hits pinned; identifier-not-found
        ⇒ semantic results marked contextual_only + note
                           ↓
        De-duplicate by natural key (lexical entry kept)
                           ↓
        Fusion (strategy) ─► top-K (8 for RAG, 10 for the benchmark)
                           ↓
                  RagPipeline (unchanged prompt)
```

Scores are never added across legs: fused results carry an RRF score
(`Σ 1/(k + rank)`, k = 60) and keep the original lexical score and cosine
similarity in `metadata.scores` / `metadata.cosine_similarity`.

## 3. Strategies tested

| Strategy | Behaviour |
|---|---|
| **A `fallback`** | Lexical results unchanged; semantic candidates appended only when the lexical primary count (exact + AND full-text) is below 3. |
| **B `rrf`** | Pure reciprocal-rank fusion of both lists, no authority rule. Kept as the control that shows what naive fusion does. |
| **C `authority`** | Exact lexical hits (`exact_cfr`, `exact_docket`) pinned first in lexical order; remaining lexical and semantic candidates fused with RRF behind them. |

Defaults: `lexical_top_n = 10`, `semantic_top_n = 10`, `rrf_k = 60`,
`semantic_floor = None` for retrieval comparison, `0.70` for the RAG run. The
RAG pipeline still asks for `top_k = 8` and the Stage 6 context policy (8
sources / 1,200 chars each / 3,600 chars) is unchanged, so hybrid cannot
enlarge the context beyond Stage 7's ceiling.

## 4. Exact identifier authority

For every query with a CFR reference or docket, the lexical layer's exact
rows are the only evidence of regulatory identity: they come from
`section_number`/`paragraph_path` equality, not similarity. Strategy C pins
them first; strategy A keeps lexical ordering; strategy B does not and, in
the unit test, lets a semantic item into the top three of an exact query. On
the benchmark all three kept Recall 1.00 on the seven identifier queries,
because exact rows also receive the top lexical ranks, but only C guarantees
it.

## 5. Negative / existence behaviour

Semantic similarity is not existence. The hybrid layer computes
`exact_identifier_detected` (a CFR reference or docket was parsed),
`exact_match_present` (lexical found exact rows) and
`identifier_not_found`. When an identifier is not found, semantic candidates
are marked `contextual_only = True`, `existence_evidence = False`, the
lexical "No live record …" note is propagated, and, new in this stage, a
note is added for an unresolved docket ("No guidance document with docket
FDA-2023-D-99999 was found in this snapshot; any retrieved passages are
related material only and do not show that the docket exists").

The first RAG run showed why the flag alone is not enough: with ten
contextual chunks and the note in context, Qwen3-0.6B still wrote "The FDA
guidance document FDA-2023-D-99999 provides nonbinding recommendations for
… human factors …". The answer layer therefore now enforces the rule:
`RagConfig.exclude_contextual_only = True` keeps contextual-only results out
of the grounding context, so an unresolved identifier with no lexical
evidence returns the deterministic not-found answer with its note. The
pre-fix run is kept as evidence (`rag-stage9-hybrid_20260916_095929_0af8a8c5.json`);
the clean run is `rag-stage9-hybrid_20260916_101820_fc0f6443.json`. Lexical
results never carry the flag, so Stage 6/7 behaviour is unaffected.

## 6. Retrieval benchmark (`retrieval_v1.jsonl`, 27 scored + 1 negative control, top_k 10)

| | Lexical (S7) | Semantic (S8) | Hybrid A | Hybrid B | Hybrid C | C floor 0.70 | C floor 0.75 |
|---|---|---|---|---|---|---|---|
| Recall@1 | 0.778 | 0.370 | 0.778 | **0.815** | **0.815** | 0.815 | 0.815 |
| Recall@3 | 0.815 | 0.667 | 0.815 | **0.852** | **0.852** | 0.852 | 0.852 |
| Recall@5 | 0.852 | 0.667 | 0.852 | **0.926** | 0.889 | 0.889 | 0.889 |
| Recall@10 | 0.852 | 0.704 | 0.852 | **0.963** | 0.926 | 0.926 | 0.926 |
| MRR | 0.797 | 0.512 | 0.797 | **0.854** | 0.845 | 0.845 | 0.847 |
| Misses | 4 | 8 | 4 | 1 (027) | 2 (017, 027) | 2 | 2 |
| Negative control | passed | passed | passed | passed | passed | passed | passed |

By category (Recall@1 / Recall@10):

| Category | Lexical | Semantic | A | B | C |
|---|---|---|---|---|---|
| exact_cfr (3) | 1.00 / 1.00 | 0.00 / 0.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| cfr_section (2) | 1.00 / 1.00 | 0.00 / 0.50 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| cfr_paragraph (2) | 1.00 / 1.00 | 0.00 / 0.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| cross_corpus (2) | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| regulatory_concept (8) | 0.75 / 1.00 | 0.50 / 0.88 | 0.75 / 1.00 | 0.88 / 1.00 | 0.88 / 1.00 |
| fda_guidance (5) | 0.80 / 0.80 | 0.20 / 1.00 | 0.80 / 0.80 | 0.80 / 1.00 | 0.80 / 0.80 |
| terminology_variation (2) | 0.50 / 0.50 | 0.50 / 1.00 | 0.50 / 0.50 | 0.50 / 1.00 | 0.50 / 1.00 |
| difficult_lexical (3) | 0.33 / 0.33 | 0.67 / 0.67 | 0.33 / 0.33 | 0.33 / 0.67 | 0.33 / 0.67 |

Per-query changes (first-hit rank, lexical → B / C): 015 manufacturer MDR
3 → 1 / 1; 017 Part 11 guidance miss → 4 / miss; 025 QMS/ISO 13485 miss → 5
/ 5; 028 sunscreen SPF miss → 2 / 2; **013 "quality management system
requirements for device manufacturers" 5 → 9 / 9** (semantic QMS-guidance
chunks crowd above the eCFR target: the one regression). Strategy A never
engaged on this benchmark: every lexical miss still had ≥ 3 primary hits.

Similarity floor: 0.70 removed 73 of 280 semantic candidates and 0.75
removed 148, with no change to any benchmark metric (0.75: MRR +0.002).
Their effect is on the negatives (§8).

Result files: `retrieval-hybrid-{fallback,rrf,authority}_20260916_09*.json`,
`retrieval-hybrid-authority-floor0_70_…`, `…floor0_75_…`,
`retrieval-hybrid-fallback-floor0_{70,75}_…`.

## 7. Hard-case analysis (strategy C, no floor; lexical / semantic for reference)

| Case | Expected | Lexical | Semantic | Hybrid C | Verdict |
|---|---|---|---|---|---|
| QMS documentation requirement ISO 13485 | 820.10 | miss (premarket QMS guidance, trigram junk) | 820.10(a) rank 2 | 820.10(a) **rank 5**; top 3 = cybersecurity-QMS guidance found by both legs, more cybersecurity, premarket QMS guidance | target retained but pushed down by guidance chunks that both legs score |
| design controls | 820.10(c) | miss (combination-product CGMP guidance) | miss (same guidance) | miss; top = combination-product CGMP and home-use design-considerations guidance | relevant guidance, **not** the eCFR target; unchanged from Stages 7/8 |
| sunscreen SPF labeling | 201.327 | miss (352.52 trigram distractor) | 201.327 rank 1 | 201.327(a)(1)(ii) **rank 2**; rank 1 = 352.52, which both legs return | semantic improvement preserved, one place lower because the distractor is dual-evidenced |
| Part 11 guidance query | FDA-2003-D-0143 | miss (exact Part 11 rows fill top 10) | rank 2 | C: miss (eight exact rows pinned); B: rank 4 | authority pinning costs this case; the exact rows are also correct answers |

## 8. Long natural-language questions (AND lexical / OR fallback / semantic / hybrid C)

| Question | AND | OR fallback (S7) | Semantic | Hybrid C |
|---|---|---|---|---|
| prescription drug vs dietary supplement | nothing | supplement AER Q&A, rank 1 | 111.1(a)(1) rank 1 | AER Q&A (both legs) ranks 1–2, 111.1(a)(1) rank 3 |
| why a new drug must be approved | nothing | ANDA amendments (unrelated) | 314.50(j) rank 2 | 211.132(e) (semantic, off), ANDA guidance, 314.50(j)(3) rank 3 |
| OTC pain reliever | nothing | small-business guidance (wrong) | 330.1 rank 3 | 314.50(a)(3), small-business guidance, postapproval ANDA, 330.1 rank 5 |
| good manufacturing practice | nothing | CGMP Q&A rank 1 | quality-systems CGMP rank 1 | CGMP Q&A (both legs) rank 1, quality-systems rank 2 |
| statute vs regulation | nothing | U.S.-agent guidance (unrelated) | 201.66, 314.3 (unrelated) | mixture of both; nothing relevant exists in either corpus |

Hybrid recovers the semantic targets for the approval and OTC questions
that the OR fallback missed, keeps the two the fallback got right, and adds
nothing for the statute question. It also carries the OR fallback's wrong
guidance along (small-business, ANDA amendments) because those chunks hold
lexical ranks 1–3.

## 9. Negative-control results

| Query | Lexical | Semantic | Hybrid C (no floor / floor 0.70) | Flags | Could the system imply existence? |
|---|---|---|---|---|---|
| 21 CFR 314.999 (fake section) | trigram junk + note | small-business guidance 0.67 | trigram junk + 5 contextual semantic / 0 semantic | detected, not found | No: note propagated; RAG excludes contextual material; model refused (score 2) |
| FDA-2023-D-99999 (fake docket) | nothing | human-factors guidance 0.80 | 10 contextual semantic (mode `semantic`) / same | detected, not found, docket note added | **Pre-fix RAG: yes (fabricated summary). After `exclude_contextual_only`: no — deterministic refusal with note** |
| 21 CFR Part 1400 (fake part) | labeling guidance (fallback) + note | human-factors guidance 0.70 | fallback guidance + 5 contextual / 1 | detected, not found | No: model refused (2) |
| NDA fee FY2031 (unknowable) | user-fee guidance (fallback) | PDUFA fee guidance 0.73 | user-fee guidance from both legs | no identifier | No: model refused (2); related material only |
| 820.30(b)(1) (retrieval control) | trigram junk + note | CGMP guidance 0.71 | junk + 5 contextual / 1 | detected, not found | No exact hit; passed |

Floor 0.70 reduces contextual semantic noise on the fake section and part
to 0–1 candidates but does nothing for the fake docket (similarities
0.77–0.80), which is why the answer-layer exclusion is the effective
safeguard.

## 10. RAG benchmark (`baseline_v1`, Qwen3-0.6B, greedy, 128 tokens, seed 42, thinking off)

Hybrid C, `semantic_floor = 0.70`, `exclude_contextual_only = True`.

### Objective measurements (from the stored result files)

| | Stage 6 lexical RAG | Stage 7 +fallback RAG | Stage 9 hybrid RAG |
|---|---|---|---|
| Completed / failed | 27 / 0 | 27 / 0 | 27 / 0 |
| Model calls | 19 | 26 | 26 |
| No-context answers | 8 | 1 | 1 |
| Avg latency per question | 22.1 s | 32.2 s | 38.4 s |
| Avg retrieval latency (model resident) | 0.99 s | 1.42 s | 1.61 s (median 0.93 s) |
| Avg input tokens | 682 | 930 | 994 |
| Avg output tokens | 40.6 | 60.4 | 68.7 |
| Avg context chars / sources | 2,201 / 2.2 | 3,069 / 2.8 | 3,216 / 3.4 (max 3,783) |
| Questions with a semantic source in context | 0 | 0 | 14 |
| Retrieval modes | — | — | exact 3, hybrid 15, lexical 8, semantic 1 |
| Semantic candidates removed by the floor | — | — | 172 of 270 |

### Manual reviewer scores (0–2; assistant-assigned against evaluation notes; not objective; to be confirmed by a human)

| | Baseline Qwen | Stage 6 | Stage 7 | Stage 9 hybrid |
|---|---|---|---|---|
| Mean, 27 questions | 0.89 | 0.93 | 1.11 | **1.15** |
| General knowledge (5) | 1.80 | 1.00 | 1.00 | 1.40 |
| Regulatory concepts (5) | 0.60 | 1.00 | 1.00 | 1.00 |
| FDA/eCFR-oriented (7) | 0.71 | 0.86 | 0.86 | 0.86 |
| Reasoning (5) | 1.40 | 0.00 | 1.00 | 0.80 |
| Unknown/hallucination (5) | 0.00 | 1.80 | 1.80 | 1.80 |

Twelve answers are byte-identical to Stage 7 and carry their scores; fifteen
changed. Improvements: clinical trial (1 → 2, now cites 50.25(c)), medical
device (1 → 2, the full statutory definition from the device FAQ guidance),
NDA and pharmaceutical drug now quote 21 CFR 314.3 definitions with
citations. Regressions: "why must a new drug be approved" (1 → 0: the model
built its answer on 211.132(e) packaging-change text that semantic
retrieval ranked first), Title 21 role stays 0 with different wrong
guidance, and the OTC question stays 0. Hallucination category unchanged at
1.80 **only because of the contextual-only exclusion**; without it the
fake-docket answer would score 0 (category 1.40).

## 11. Performance

Retrieval benchmark, hybrid C, 28 queries (machine also running other
processes; absolute lexical timings are 5–6× the Stage 5 standalone figure):

| Step | Median | Max |
|---|---|---|
| Lexical leg | 669 ms | 1,622 ms |
| Semantic query embedding | 18.9 ms | 24.0 ms |
| Semantic search (2,676 vectors) | 2.8 ms | 3.1 ms |
| Fusion + dedup | 0.3 ms | 0.3 ms |
| Total | 691 ms | 1,644 ms |

The semantic leg and fusion add about 22 ms; the hybrid's cost is
dominated by the lexical leg, exactly as in Stage 7. In the RAG run,
retrieval was 0.93 s median (1.61 s mean, one 7.2 s cold outlier) against
36 s median generation. Context grew 4.8 % in characters and 6.8 % in input
tokens over Stage 7; generation time grew 19 % because answers got longer
(68.7 vs 60.4 output tokens).

## 12. Tradeoffs

Improvements (measured): Recall@5 +0.037, Recall@10 +0.074, MRR +0.048
(strategy C) with identifier categories intact; three of four lexical
vocabulary misses recovered (two at rank ≤ 5 under C); better sources for
two long questions; RAG reviewer mean +0.04 with two clear answer
improvements; negative control and all five fictitious questions safe after
the answer-layer rule.

Costs (measured): one concept query pushed from rank 5 to 9; the Part 11
guidance stays a miss under authority pinning; semantic-first context sent
one reasoning answer off-topic; +7 % input tokens and +6 s per question;
the fake-docket case required a new safety rule in the answer layer that
Stage 6/7 did not need; and every semantic gain is measured on a corpus
where all targets are guaranteed present (2 % of the database), so
full-corpus precision is unknown.

## 13. Recommendation

**B — hybrid retrieval is promising but needs another controlled retrieval
experiment before it becomes the retrieval direction.**

Measured support for hybrid: strategy C improved every recall level and MRR
without touching identifier performance, preserved the Stage 7 fallback
gains, recovered vocabulary-mismatch targets, and, after the
contextual-only rule, kept hallucination behaviour at Stage 7 level.

Why not A yet: (1) the semantic leg searched a curated 2,676-passage corpus
in which every benchmark target exists; the crowding regression (013) and
the off-topic reasoning answer (019) already appear at this scale and would
grow on 134,010 passages; (2) the fake-docket run showed that semantic
material reaches the generator with only a note as protection, and safety
now rests on an answer-layer exclusion that must be validated on more
negative cases; (3) the RAG gain (+0.04 reviewer mean) is within the noise
of a 27-question, single-reviewer score.

The next controlled experiment should (a) extend the semantic index to at
least the Title 21 subchapters and guidance sectors the benchmark spans so
precision is measured against real competition, (b) re-run strategies B and
C with the floor on that index, (c) add negative-control queries for
dockets and parts to `retrieval_v1` so the answer-layer rule is benchmarked,
and (d) keep the lexical retriever as the default meanwhile.

Nothing beyond this experiment was implemented.
