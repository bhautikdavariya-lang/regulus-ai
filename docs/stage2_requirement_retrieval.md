# Stage 2: Requirement-Level Retrieval and the Evidence Registry

Stage 2 makes retrieval consume the Stage 1 `QueryPlan`. Every requirement
in the plan is retrieved on its own, every retrieved row is classified by
identity against every requirement, and the result is an `EvidenceRegistry`
that later stages can trust. Context construction, grounding, generation
and citations are unchanged.

## 1. Flow

```
question
  │
  ▼  plan_query()                         once, in RagPipeline.answer()
QueryPlan (requirements r1..rn, docket, kind)
  │
  ▼  LexicalRetriever.run_plan(plan)
  ├─ for each requirement:  exact rows      ECFR_EXACT_SECTION / ECFR_EXACT_PART
  │                         parent paragraph ECFR_EXACT_ROW (structural context)
  ├─ docket (if any):       GUIDANCE_EXACT_DOCKET
  ├─ question full-text:    ECFR_FULL_TEXT, GUIDANCE_FULL_TEXT (supporting)
  ├─ per UNRESOLVED requirement whose parent was not found:
  │                         OR full-text and trigram on that identifier (discovery)
  └─ no requirements at all: legacy trigram + question-level OR fallback
  │
  ▼  merge by natural key, classify by identity, order
EvidenceRegistry
  │   evidence (exact → structural → supporting → discovery)
  │   requirement_state (attempted, hits per tier, fallback, note)
  ▼
SearchResponse.results = protected evidence + remainder[:top_k - protected]
  │
  ▼  existing select_useful() → build_context() → gate → Qwen → citations
```

`run(question)` remains the Stage 5–7 query-level path, unchanged, for the
hybrid retriever, `scripts/search.py`, `scripts/evaluate_retrieval.py` and
the evaluation baselines. `RagPipeline` uses `run_plan` whenever the
retriever provides it and falls back to `run` otherwise.

## 2. Files

| File | Change |
|---|---|
| `src/regulus/retrieval/evidence.py` (new) | tiers, `relate()`, `Evidence`, `RequirementRetrieval`, `EvidenceRegistry`, `classify_result()`, `order_evidence()` |
| `src/regulus/retrieval/lexical.py` | `run_plan()`, `PlanRetrieval`, `exact_cfr(ref)` (takes a `CfrReference`), `exact_row()` leg, `exact_row_limit` guardrail |
| `src/regulus/retrieval/sql.py` | `ECFR_EXACT_ROW`: one row by (section, paragraph) |
| `src/regulus/retrieval/ranking.py` | `structural_score()` (90) for the parent row |
| `src/regulus/rag/pipeline.py` | builds the plan once, calls `run_plan`, keeps the registry on `RagAnswer.evidence` and in `metadata["evidence"]` |
| `src/regulus/retrieval/__init__.py` | exports |
| `tests/test_retrieval_plan.py` (new) | 35 behaviour tests on an in-memory table |
| `audit/stage2_retrieval_check.py` (new) | read-only validation on representative questions |

## 3. Evidence tiers and how they are decided

Association is by identity: the row's `(title, section, paragraph_path)`
against the requirement's. Scores and text similarity are never consulted.

| Requirement level | Row | Relation | Tier |
|---|---|---|---|
| paragraph `820.10(b)(2)` | `820.10(b)(2)` | exact | **exact**, `satisfies` r |
| paragraph `820.10(b)(2)` | `820.10(b)` or `820.10` (section row) | parent | **structural**, `structural_for` r |
| paragraph `820.10(b)(2)` | `820.10(b)(2)(i)` | child | **structural** |
| paragraph `820.10(b)(2)` | `820.10(b)(3)` | sibling | supporting or discovery, by method |
| paragraph `820.10(b)` | `820.10(b)(1)` … `(b)(4)` | child | **structural**, never exact |
| section `820.10` | any row of 820.10 | exact | **exact** (a section is its rows) |
| part `820` | first row of each section of part 820 | exact | **exact** |
| any | other section, guidance chunk | none | supporting (`full_text`, `exact_docket`) or discovery (`full_text_or`, `trigram`) |

A docket hit is exact by identity of the docket but satisfies no CFR
requirement (`satisfies = ()`). A row found by a broad method that happens
to be a requested provision is exact by identity with its method preserved;
in practice this cannot happen for the requirement that triggered discovery,
because discovery runs only when the exact lookup found nothing.

Duplicate references in a plan share one exact query and one piece of
evidence whose `satisfies` lists every requirement id; requirement order and
ids are preserved.

## 4. Fallback

* **Resolved requirement**: nothing broad runs for it, whatever `top_k` is.
* **Unresolved requirement whose parent paragraph exists**: no broad search;
  the note says the section exists and the paragraph does not.
* **Unresolved requirement with no parent row** (section or part absent):
  OR full-text on the identifier (`"820.999"`) over the selected corpora and
  trigram on the section number. Everything found is tier discovery and is
  tagged `discovered_for` that requirement.
* **Plan without requirements** (general or guidance question): the legacy
  trigram conditions and the Stage 7 question-level OR fallback apply,
  yielding supporting and discovery evidence.
* Requirements outside Title 21 or when the eCFR corpus is not selected are
  not attempted and are diagnosed as such.

## 5. Result protection

`response.results` is what the unchanged context builder receives. It is
the exact and structural evidence in full, followed by supporting and
discovery evidence up to `top_k - len(protected)`. A small `top_k` therefore
never removes a requested provision; it only shortens the tail. The context
builder's own budget (8 sources, 3,600 chars) still applies afterwards and
is Stage 3's concern.

## 6. Diagnostics

`response.diagnostics["plan"]` and `registry.diagnostics`:

```
kind, requirement_count, requirement_ids, exact_attempts,
resolved, unresolved,
tier_counts {exact, structural, supporting, discovery},
method_counts {exact_cfr, full_text, ...},
candidate_count, evidence_count, protected_count,
docket_requested, docket_hits, question_fallback_used,
requirements: {
  r2: {canonical, exact_attempted, exact_hits, structural_hits, discovery_hits,
       resolved, fallback_run, fallback_terms, note}
}
```

The legacy keys (`primary_result_count`, `fallback_used`, `fallback_terms`,
`fallback_candidate_count`, `final_result_count`, `retrieval_mode`) are
still present. Per-leg timings and counts use `method:requirement_id`
names (for example `exact_cfr:r3`, `structural:r3`, `full_text_or:r3:ecfr`).

## 7. Registry API

```
registry.evidence                 ordered tuple of Evidence
registry.exact_for(rid)           rows that ARE the provision
registry.structural_for(rid)      parent / child rows
registry.discovered_for(rid)      broad-method rows found for it
registry.evidence_for(rid)        union of the three
registry.resolved_requirements()  ids with at least one exact row
registry.unresolved_requirements()
registry.protected                exact + structural
registry.by_tier(tier), registry.all_evidence(), registry.to_dict()
```

`Evidence` carries `evidence_id`, `result` (the `RetrievalResult`), `tier`,
`satisfies`, `structural_for`, `discovered_for`, `relations` (requirement
id → exact / parent / child / sibling) and the result's method and score.

## 8. Measured on the live database (`audit/results/stage2_retrieval_check.txt`)

| Question | Requirements | Exact | Structural | Unresolved |
|---|---|---|---|---|
| 820.10(b)(2) | 1 | (b)(2) | (b) | none |
| (b)(1) and (b)(2) | 2 | (b)(1), (b)(2) | (b) shared | none |
| (b)(1) through (b)(4) | 4 | all four, in order | (b) shared | none |
| (b)(1), (b)(2), and (b)(3) | 3 | all three | (b) | none |
| 820.10(b)(2) and 820.999 | 2 | (b)(2) | (b), 820.10 | 820.999 (discovery only, noted) |
| 820.10(b) | 1 | (b) | 820.10, (b)(1)–(b)(4) as children | none |
| 820.10(b)(5) | 1 | none | (b) | (b)(5), noted "parent exists", no broad search |
| 314.999 / Part 1400 | 1 | none | none | unresolved, discovery tagged, noted |
| docket FDA-2016-D-2565 | 0 | docket chunks | | none |
| general questions | 0 | | | legacy text path, supporting/discovery only |

Per-question retrieval time on the live database: 9 ms to 0.9 s for
resolved plans; up to 4 s when trigram discovery runs on an unresolved
section (unchanged from the legacy trigram cost).

## 9. Compatibility

* `LexicalRetriever.run()`, `search()`, `SearchResponse`, `RagPipeline.answer()`,
  `RagAnswer.to_dict()` and all evaluation scripts keep their signatures and
  behaviour. `RagAnswer` gains an optional `evidence` field; `metadata`
  gains `plan` and `evidence`.
* `exact_cfr()` now takes a `CfrReference` instead of a `QueryClassification`.
  No caller outside `lexical.py` used it.
* The hybrid and semantic retrievers do not implement `run_plan`; the
  pipeline uses their `run()` and records no registry.
* Full fast suite: 446 passed, 6 slow deselected (previous baseline 411).

## 10. Limitations and the Stage 3 boundary

* The registry records coverage facts; nothing yet decides what incomplete
  coverage means. `select_useful()` and `build_context()` are unchanged, so
  the 8-source / 3,600-char budget can still drop protected evidence for a
  large section or part request. Stage 3 owns coverage decisions, evidence
  selection and budgeting.
* Supporting evidence is question-level (one full-text pass), not
  per-requirement; discovery for an unresolved section still returns
  numerically similar sections from trigram. Both are tiered honestly and
  left for Stage 3 to weigh.
* Guidance is never associated with a CFR requirement (no "guidance about
  820.10(b)(2)" link). Docket requests are not plan requirements.
* The grounding gate still verifies only the first identifier
  (`extract_identifier`); plan-level gating is Stage 3.
